"""
Builds the instrument master and expiry calendar from NSE bhavcopy history
-- D-05/D-06/D-52.

Usage:
    .venv/Scripts/python.exe -m rules.build_instrument_master \
        --start 2024-07-08 --end 2026-09-06 --underlyings NIFTY

Deliberately does NOT build a separate underlying-level "lot size rule"
table. Confirmed live (2026-09-06): lot-size revisions aren't clean
date cutovers -- during a transition, contracts already listed keep their
original lot size (grandfathered) while newly-listed ones get the new one,
for a multi-week window. A date-only rule table can't represent that
honestly; it would have to pick one value and silently misrepresent the
other. The instrument master already carries the exact, unambiguous lot
size for every real contract directly (no inference needed), and every
lot-size use in this project (risk/portfolio/margin math) is for a real
contract we already have a row for -- so the ambiguous case (projecting a
lot size for a contract that doesn't exist yet) never actually comes up
for backtesting, and isn't worth solving speculatively (D-54).

Expiry, by contrast, genuinely is a per-date/per-underlying fact once a
contract exists (this is what D-51's rules_as_of() is actually for -- the
irregular/shifting NIFTY expiry weekday, not lot size), so the expiry
calendar stays a flat table of observed (underlying, expiry) facts.

This is reference data -- small enough to be single unpartitioned Parquet
files. D-03's (instrument_type, year, month) partitioning applies to the
bulk canonical market data (OHLCV bars), not this.
"""

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from .bhavcopy import fetch_fo_bhavcopy, parse_fo_bhavcopy

HERE = Path(__file__).resolve().parent
DEFAULT_OUT_DIR = HERE.parent / "data" / "reference"


def format_strike(raw: str) -> str:
    val = float(raw)
    return str(int(val)) if val == int(val) else str(val)


def instrument_id_for(underlying: str, instrument_type: str, expiry: str, strike: str, option_type: str) -> str:
    if instrument_type in ("IDF", "STF"):
        return f"NSE|{underlying}|{expiry}|FUT"
    return f"NSE|{underlying}|{expiry}|{format_strike(strike)}|{option_type}"


def trading_days(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def collapse_periods(daily_values: list) -> list:
    """Collapse consecutive identical (date, value) observations into
    valid_from/valid_to periods -- for a single physical contract, whose
    own lot size genuinely doesn't change mid-life in the real world, so
    this only ever produces one period per contract in practice. Kept
    general rather than assumed, in case that ever isn't true."""
    periods = []
    for d, v in daily_values:
        if periods and periods[-1]["value"] == v:
            periods[-1]["valid_to"] = d
        else:
            periods.append({"value": v, "valid_from": d, "valid_to": d})
    return periods


def build(start: date, end: date, underlyings: set, instrument_types: set, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)

    # Keyed by instrument_id (underlying+expiry+strike+type), NOT by raw
    # exchange_token -- confirmed live (2026-09-06) that NSE recycles
    # FinInstrmId numbers for unrelated contracts after expiry (e.g. token
    # 47520 was three different contracts across Dec 2024/Aug 2025/Jan
    # 2026: different expiries, strikes, even different option types).
    # Grouping by the recyclable token silently merged unrelated contracts
    # into one fake multi-period "instrument". This is exactly why D-05
    # made the composite string the primary id and the token a secondary
    # field, not the reverse.
    instrument_days = {}     # instrument_id -> [(date, lot_size, token), ...]
    instrument_static = {}   # instrument_id -> {underlying, instrument_type, expiry, strike, option_type}
    expiry_first_seen = {}   # (underlying, instrument_type, expiry) -> first date observed

    days_scanned, days_skipped = 0, 0
    legacy_days_scanned = 0
    transition_days = []      # informational only -- see module docstring
    token_reuse_warnings = []  # a token mapping to >1 instrument_id over the scan

    for d in trading_days(start, end):
        try:
            raw, is_legacy = fetch_fo_bhavcopy(d)
        except ValueError:
            days_skipped += 1
            continue
        rows = parse_fo_bhavcopy(raw, is_legacy, underlyings=underlyings, instrument_types=instrument_types)
        days_scanned += 1
        legacy_days_scanned += is_legacy

        seen_lot_today = {}
        for row in rows:
            token = row["FinInstrmId"]  # None pre-UDiFF (legacy format has no token column)
            lot = int(float(row["NewBrdLotQty"])) if row["NewBrdLotQty"] is not None else None
            underlying = row["TckrSymb"]
            itype = row["FinInstrmTp"]
            expiry = row["XpryDt"]
            strike = row.get("StrkPric")
            option_type = row.get("OptnTp")
            iid = instrument_id_for(underlying, itype, expiry, strike, option_type)

            instrument_days.setdefault(iid, []).append((d, lot, token))
            instrument_static.setdefault(iid, {
                "underlying": underlying, "instrument_type": itype, "expiry": expiry,
                "strike": strike, "option_type": option_type,
            })

            if lot is not None:
                seen_lot_today.setdefault(underlying, set()).add(lot)

            key = (underlying, itype, expiry)
            if key not in expiry_first_seen:
                expiry_first_seen[key] = d

        for underlying, lots in seen_lot_today.items():
            if len(lots) > 1:
                transition_days.append(f"{d}: {underlying} had {len(lots)} lot sizes active at once: {lots} (grandfathering, not an error)")

    # --- instrument master: one row per (contract, stable-spec period) ---
    instrument_rows = []
    lot_size_backfilled = []  # instrument_ids whose earliest days predate any known lot size (legacy era)
    for iid, days in instrument_days.items():
        static = instrument_static[iid]
        is_option = static["option_type"] in ("CE", "PE")
        # token should be constant across a single instrument_id's life
        # (excluding None -- legacy days never have one) -- confirm rather
        # than assume, and surface it if it ever isn't.
        tokens_seen = {t for _, _, t in days if t is not None}
        if len(tokens_seen) > 1:
            token_reuse_warnings.append(f"{iid}: {len(tokens_seen)} different tokens observed: {tokens_seen}")
        exchange_token = sorted(tokens_seen)[-1] if tokens_seen else None

        true_valid_from = min(d for d, _, _ in days)
        lot_days = sorted((d, lot) for d, lot, _ in days if lot is not None)
        if lot_days:
            periods = collapse_periods(lot_days)
            if periods[0]["valid_from"] > true_valid_from:
                # This instrument_id was observed earlier than any known lot
                # size (pre-UDiFF legacy days, which have no lot-size
                # column at all) -- backward-extend the earliest known
                # value rather than leave a gap. NIFTY's lot size is stable
                # for long stretches (confirmed: 25 held from well before
                # 2024-07-08 through 2024-11-22), so this is a reasonable,
                # explicitly-logged assumption, not a silent one.
                lot_size_backfilled.append(f"{iid}: backfilled lot_size={periods[0]['value']} to {true_valid_from} (legacy era, no lot-size column)")
                periods[0]["valid_from"] = true_valid_from
        else:
            # Never observed with a known lot size at all -- contract
            # existed and expired entirely within the legacy era. Can't
            # source a real value; leave it null rather than guess.
            periods = [{"value": None, "valid_from": true_valid_from, "valid_to": max(d for d, _, _ in days)}]

        for period in periods:
            instrument_rows.append({
                "instrument_id": iid,
                "exchange_token": exchange_token,
                "market_id": "NSE",
                "underlying": static["underlying"],
                "instrument_type": static["instrument_type"],
                "expiry": static["expiry"],
                "strike": format_strike(static["strike"]) if is_option else None,
                "option_type": static["option_type"] if is_option else None,
                "lot_size": period["value"],
                "valid_from": period["valid_from"],
                "valid_to": period["valid_to"],
                "source": "NSE_BHAVCOPY",
            })
    instrument_df = pd.DataFrame(instrument_rows)

    # --- expiry calendar (D-52) ---
    calendar_df = pd.DataFrame([
        {"market_id": "NSE", "underlying": u, "instrument_type": it, "expiry": exp, "first_seen": fs}
        for (u, it, exp), fs in expiry_first_seen.items()
    ])

    ingest_time = datetime.now().isoformat()
    for df in (instrument_df, calendar_df):
        if not df.empty:
            df["ingest_time"] = ingest_time

    instrument_path = out_dir / "instrument_master.parquet"
    calendar_path = out_dir / "expiry_calendar.parquet"
    instrument_df.to_parquet(instrument_path, index=False)
    calendar_df.to_parquet(calendar_path, index=False)

    manifest = {
        "built_at": ingest_time,
        "date_range": [start.isoformat(), end.isoformat()],
        "underlyings": sorted(underlyings),
        "instrument_types": sorted(instrument_types),
        "days_scanned": days_scanned,
        "days_skipped_as_holiday_or_weekend": days_skipped,
        "row_counts": {
            "instrument_master": len(instrument_df),
            "expiry_calendar": len(calendar_df),
        },
        "legacy_days_scanned": legacy_days_scanned,
        "lot_size_transition_days": transition_days,
        "token_reuse_within_one_instrument_id": token_reuse_warnings,
        "lot_size_backfilled_from_legacy_era": lot_size_backfilled,
        "content_hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (instrument_path, calendar_path)
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))

    print(f"Scanned {days_scanned} trading days ({legacy_days_scanned} legacy-format, {days_skipped} skipped as holiday/weekend/unpublished)")
    print(f"Instrument master: {len(instrument_df)} rows ({instrument_df['exchange_token'].nunique() if not instrument_df.empty else 0} distinct contracts)")
    print(f"Expiry calendar: {len(calendar_df)} rows")
    if transition_days:
        print(f"\n{len(transition_days)} lot-size-transition days detected (grandfathering, informational only)")
        print("  first:", transition_days[0])
        print("  last: ", transition_days[-1])
    if token_reuse_warnings:
        print(f"\n{len(token_reuse_warnings)} instrument_ids saw their exchange_token change mid-life (unexpected, worth checking):")
        for w in token_reuse_warnings[:5]:
            print(" ", w)
    if lot_size_backfilled:
        print(f"\n{len(lot_size_backfilled)} instrument_ids had lot_size backfilled into the legacy era (no lot-size column pre-2024-07-08):")
        print(" ", lot_size_backfilled[0])
    print(f"\nWritten to {out_dir}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--underlyings", default="NIFTY", help="comma-separated NSE TckrSymb values")
    parser.add_argument("--instrument-types", default="IDF,IDO",
                         help="comma-separated FinInstrmTp codes (IDF=index future, IDO=index option)")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args()

    build(
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        underlyings=set(args.underlyings.split(",")),
        instrument_types=set(args.instrument_types.split(",")),
        out_dir=Path(args.out_dir),
    )


if __name__ == "__main__":
    main()

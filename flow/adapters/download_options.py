"""
Downloads NIFTY front-weekly options 1-minute history from Breeze across a
date range (D-50's scope: front-weekly only, not the full listed ladder
across all expiries).

For each trading day, the front expiry is resolved via
rules/store.py's rules_as_of() (D-51/D-52 -- real observed expiry data, not
a computed weekday rule). Days are grouped by their front expiry; for each
expiry, every strike/right listed in the instrument master for that expiry
is a candidate, restricted to the sub-range of front-expiry days it was
actually listed on (valid_from/valid_to) -- deep-OTM strikes get added
mid-week as spot moves, so not every strike is live for the whole week.
Each contract's own day-list is then 2-day chunked independently.

This is a much bigger pull than index/futures (one instrument each) --
D-50's budget is ~89K requests, well over Breeze's ~5,000/day cap, and the
session token expires daily (D-49) regardless. So this script is designed
to run in daily installments: --max-requests caps how many new requests one
invocation makes (default 4500, leaving headroom under the cap), and
resumability (skipping chunks whose raw file already holds a definitive
Status-200 response -- an empty Success is a real, valid "no trades this
window", common for deep ITM/OTM strikes, not a hole to keep retrying)
means re-running with a fresh token the next day picks up exactly where
the last run stopped.

Usage (repeat daily with a fresh Breeze session token until "0 to fetch"):
    .venv/Scripts/python.exe -m adapters.download_options --start 2024-01-01 --end 2026-09-04
"""

import argparse
import sys
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.breeze import authenticate, pull_option_history, save_raw  # noqa: E402
from adapters.chunking import pair_days, trading_days  # noqa: E402
from adapters.raw_io import is_saved  # noqa: E402
from rules.store import MarketRulesStore  # noqa: E402

RAW_ROOT = Path(__file__).resolve().parent.parent / "data" / "raw" / "breeze" / "options"
MARKET_OPEN, MARKET_CLOSE = "09:15:00", "15:30:00"


def resolve_front_expiry_per_day(store, underlying, start, end, instrument_type="IDO"):
    result = {}
    for d in trading_days(start, end):
        exp = store.rules_as_of("NSE", underlying, d, rule_type="expiry", instrument_type=instrument_type, n=1)
        if exp:
            result[d] = exp[0].isoformat()
    return result


def build_contract_chunks(store, underlying, start, end, instrument_type="IDO"):
    """Returns (chunk_start, chunk_end, instrument_id, expiry, strike,
    right) tuples covering every front-weekly contract's actual listed
    trading days in [start, end]."""
    day_to_expiry = resolve_front_expiry_per_day(store, underlying, start, end, instrument_type)
    days_by_expiry = defaultdict(list)
    for d, exp in day_to_expiry.items():
        days_by_expiry[exp].append(d)

    inst = store.instruments
    chunks = []
    for expiry, days in days_by_expiry.items():
        candidates = inst[
            (inst["underlying"] == underlying) & (inst["instrument_type"] == instrument_type)
            & (inst["expiry"] == expiry)
        ]
        for _, row in candidates.iterrows():
            contract_days = [d for d in days if row["valid_from"] <= d <= row["valid_to"]]
            if not contract_days:
                continue
            for c_start, c_end in pair_days(contract_days):
                chunks.append((c_start, c_end, row["instrument_id"], expiry, row["strike"], row["option_type"]))
    return chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--underlying", default="NIFTY")
    ap.add_argument("--interval", default="1minute")
    ap.add_argument("--sleep", type=float, default=1.0, help="seconds between requests")
    ap.add_argument("--max-requests", type=int, default=4500, help="cap on new requests this run (Breeze's daily cap is ~5000)")
    args = ap.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    store = MarketRulesStore()

    print("Resolving front-weekly contracts and chunking (this walks the whole instrument master)...")
    chunks = build_contract_chunks(store, args.underlying, start, end)

    pending = []
    for c_start, c_end, instrument_id, expiry, strike, right in chunks:
        out_path = RAW_ROOT / args.underlying / expiry / f"{strike}_{right}" / f"{c_start.isoformat()}_{c_end.isoformat()}.json"
        if not is_saved(out_path):
            pending.append((c_start, c_end, instrument_id, expiry, strike, right, out_path))

    print(f"{len(chunks)} chunks total, {len(chunks) - len(pending)} already done, {len(pending)} remaining")
    if not pending:
        return

    todo = pending[:args.max_requests]
    print(f"This run: {len(todo)} requests (--max-requests {args.max_requests}); {len(pending) - len(todo)} left for a later run")

    breeze = authenticate()
    ok, failed = 0, []
    for i, (c_start, c_end, instrument_id, expiry, strike, right, out_path) in enumerate(todo, 1):
        expiry_dt = datetime.strptime(expiry, "%Y-%m-%d")
        from_dt = datetime.strptime(f"{c_start.isoformat()} {MARKET_OPEN}", "%Y-%m-%d %H:%M:%S")
        to_dt = datetime.strptime(f"{c_end.isoformat()} {MARKET_CLOSE}", "%Y-%m-%d %H:%M:%S")
        try:
            response = pull_option_history(breeze, args.underlying, expiry_dt, float(strike), right, from_dt, to_dt, args.interval)
            request_meta = {
                "underlying": args.underlying, "instrument_id": instrument_id, "expiry": expiry,
                "strike": strike, "right": right, "interval": args.interval,
                "from_dt": from_dt.isoformat(), "to_dt": to_dt.isoformat(),
                "product_type": "options", "exchange_code": "NFO",
            }
            save_raw(response, request_meta, out_path)
            if response.get("Status") == 200:
                ok += 1
            else:
                failed.append((c_start, c_end, instrument_id, response.get("Error")))
        except Exception as e:
            failed.append((c_start, c_end, instrument_id, str(e)))

        if i % 100 == 0 or i == len(todo):
            print(f"...{i}/{len(todo)} ({c_start} to {c_end}, {instrument_id}), {ok} ok so far, {len(failed)} failed")
        time.sleep(args.sleep)

    print(f"\nDone this run: {ok} ok, {len(failed)} failed, {len(pending) - len(todo)} still pending for future runs")
    for c_start, c_end, instrument_id, err in failed[:20]:
        print(f"  FAILED {c_start} to {c_end} ({instrument_id}): {err}")


if __name__ == "__main__":
    main()

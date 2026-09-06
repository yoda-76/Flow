"""
Normalizes raw Breeze historical responses (as saved by
adapters/breeze.py's save_raw()) into the canonical schema (D-04/D-09),
resolving each contract's instrument_id the same way flow/rules does (D-05)
so canonical data and the instrument master never disagree on identity.

Breeze's own response rows already carry everything needed to build
instrument_id for options and futures (stock_code, expiry_date, strike,
right) -- no external context required, which is why this walks raw files
directly rather than needing a directory-naming convention to recover
identity (D-03's partitioning scheme applies to canonical output, not raw
input, so raw files can stay simply named).
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from .schema import CANONICAL_COLUMNS


def _parse_breeze_expiry(raw: str) -> str:
    """Breeze v2 gives 'DD-MON-YYYY' (e.g. '01-SEP-2026'); our instrument
    ids use ISO 'YYYY-MM-DD' (rules/build_instrument_master.py)."""
    return datetime.strptime(raw.title(), "%d-%b-%Y").date().isoformat()


def _instrument_id_for_row(row: dict) -> str:
    product_type = (row.get("product_type") or "").lower()
    underlying = row["stock_code"]
    if product_type == "futures":
        expiry = _parse_breeze_expiry(row["expiry_date"])
        return f"NSE|{underlying}|{expiry}|FUT"
    if product_type == "options":
        expiry = _parse_breeze_expiry(row["expiry_date"])
        strike = row["strike_price"]
        strike_str = str(int(strike)) if float(strike) == int(float(strike)) else str(strike)
        option_type = "CE" if row["right"].lower() == "call" else "PE"
        return f"NSE|{underlying}|{expiry}|{strike_str}|{option_type}"
    # cash/index -- no expiry, no strike
    return f"NSE|{underlying}|INDEX" if underlying in ("NIFTY", "BANKNIFTY") else f"NSE|{underlying}|EQ"


def _row_to_canonical(row: dict, source: str, ingest_time: str, dataset_version: str) -> dict:
    return {
        "timestamp": pd.Timestamp(row["datetime"]).tz_localize("Asia/Kolkata"),
        "instrument_id": _instrument_id_for_row(row),
        "open": float(row["open"]), "high": float(row["high"]),
        "low": float(row["low"]), "close": float(row["close"]),
        "volume": float(row["volume"]),
        "open_interest": float(row["open_interest"]) if row.get("open_interest") not in (None, "") else None,
        "source": source,
        "ingest_time": ingest_time,
        "dataset_version": dataset_version,
    }


def build_from_raw_files(raw_dir: Path, source: str = "BREEZE", dataset_version: str = "unversioned") -> tuple:
    """
    Walks every *.json file under raw_dir (as written by
    adapters/breeze.py's save_raw()) and returns (canonical_df, report).

    report["negative_volume_nulled"] counts rows where the provider
    returned a literally negative volume (confirmed real, 2026-09-06 --
    e.g. a genuine Breeze bug: "volume": -65 on one illiquid bar,
    findings.md). Negative volume isn't a real quantity -- it's set to
    null (NOT 0, NOT abs()) rather than kept, meaning "we don't actually
    know the volume for this bar", not "zero trades happened".
    """
    rows = []
    ingest_time = datetime.now().isoformat()
    for f in sorted(Path(raw_dir).glob("*.json")):
        record = json.loads(f.read_text())
        for raw_row in (record.get("response") or {}).get("Success") or []:
            rows.append(_row_to_canonical(raw_row, source, ingest_time, dataset_version))

    report = {"negative_volume_nulled": 0, "duplicate_rows_deduped": 0}
    if not rows:
        return pd.DataFrame(columns=CANONICAL_COLUMNS), report

    df = pd.DataFrame(rows, columns=CANONICAL_COLUMNS)

    # Breeze can return two conflicting rows for the same (timestamp,
    # instrument_id) within a single response -- confirmed real, 2025-06-20
    # 14:33 NIFTY future: one row volume=5250, the other volume=-1543350.
    # When exactly one side of a duplicate group has a plausible
    # (non-negative) volume, keep that one; otherwise keep the last-seen
    # row (deterministic, but arbitrary -- both candidates are suspect).
    dup_mask = df.duplicated(subset=["timestamp", "instrument_id"], keep=False)
    if dup_mask.any():
        groups = df[dup_mask].groupby(["timestamp", "instrument_id"])
        report["duplicate_rows_deduped"] = int(dup_mask.sum()) - groups.ngroups
        kept = [g[g["volume"] >= 0].iloc[[-1]] if (g["volume"] >= 0).any() else g.iloc[[-1]]
                for _, g in groups]
        df = pd.concat([df[~dup_mask]] + kept, ignore_index=True)

    negative = df["volume"] < 0
    report["negative_volume_nulled"] = int(negative.sum())
    df.loc[negative, "volume"] = None

    return df.sort_values(["timestamp", "instrument_id"]).reset_index(drop=True), report


def cross_check_against_instrument_master(canonical_df: pd.DataFrame, rules_store) -> list:
    """
    For every derivative (option/future) instrument_id in canonical_df,
    confirm it's a known contract in the instrument master. Doesn't block
    anything by itself (D-44: the caller decides); a miss here means
    either the instrument master's date range doesn't cover this contract
    yet, or the two identity-construction paths have drifted apart --
    worth knowing either way, not something to silently ignore.
    """
    issues = []
    derivative_ids = [i for i in canonical_df["instrument_id"].unique() if i.count("|") >= 3]
    unknown = [i for i in derivative_ids if rules_store.get_instrument(i) is None]
    if unknown:
        issues.append(f"WARNING: {len(unknown)}/{len(derivative_ids)} derivative instrument_ids not found in instrument master: {unknown[:5]}")
    return issues

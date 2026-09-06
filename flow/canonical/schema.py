"""
The canonical market-data schema -- long-form, one table for all instrument
types, per the decisions recorded in docs/dynamic/decisions.md:

  D-04  long-form (timestamp, instrument_id, o,h,l,c,v,oi), not wide
  D-09  one table, not split per instrument type
  D-10  open_interest in the same record as OHLCV, nullable
  D-07  timestamps are tz-aware Asia/Kolkata, bar-labelled by OPEN
  D-02  raw bytes are kept separately (adapters/); this is the parsed,
        normalized form
  D-12  every record carries source/ingest_time/dataset_version
  D-13  dataset_version references a manifest (content hash), not a bare
        version number

Not covered here: this schema doesn't know about the market-rules store or
instrument master (rules/store.py) -- callers resolve instrument_id
against that separately. Keeping this module free of that dependency is
deliberate (CLAUDE.md: small modules behind clear interfaces).
"""

import pandas as pd

CANONICAL_COLUMNS = [
    "timestamp",        # tz-aware Asia/Kolkata, bar-labelled by open (D-07)
    "instrument_id",    # composite string, D-05 -- e.g. NSE|NIFTY|2026-09-08|23900|CE
    "open", "high", "low", "close",
    "volume",
    "open_interest",     # nullable -- populated for futures/options, null for equity/index
    "source",            # e.g. "BREEZE", "DHAN" (D-12)
    "ingest_time",        # when this row was pulled, not when the bar happened (D-12)
    "dataset_version",    # manifest/content-hash reference (D-13)
]


def empty_canonical_df() -> pd.DataFrame:
    return pd.DataFrame(columns=CANONICAL_COLUMNS)


def validate_canonical(df: pd.DataFrame) -> list:
    """
    Plain-Python sanity checks (D-44). Returns a list of issue strings,
    prefixed CRITICAL or WARNING -- empty list means clean. Does not raise;
    callers decide whether CRITICAL issues block promotion (matches D-44's
    "gate on promotion" policy, implemented by the caller, not baked in
    here).
    """
    issues = []

    missing_cols = [c for c in CANONICAL_COLUMNS if c not in df.columns]
    if missing_cols:
        issues.append(f"CRITICAL: missing columns: {missing_cols}")
        return issues  # nothing else is checkable without the columns

    if df.empty:
        issues.append("WARNING: dataframe is empty")
        return issues

    if not pd.api.types.is_datetime64tz_dtype(df["timestamp"]):
        issues.append("CRITICAL: timestamp column is not timezone-aware (D-07 requires Asia/Kolkata)")
    elif str(df["timestamp"].dt.tz) != "Asia/Kolkata":
        issues.append(f"CRITICAL: timestamp tz is {df['timestamp'].dt.tz}, expected Asia/Kolkata (D-07)")

    dupes = df.duplicated(subset=["timestamp", "instrument_id"])
    if dupes.any():
        issues.append(f"CRITICAL: {dupes.sum()} duplicate (timestamp, instrument_id) rows")

    bad_ohlc = df[
        (df["high"] < df[["open", "close", "low"]].max(axis=1))
        | (df["low"] > df[["open", "close", "high"]].min(axis=1))
    ]
    if not bad_ohlc.empty:
        issues.append(f"CRITICAL: {len(bad_ohlc)} rows fail OHLC sanity (high/low don't bound open/close)")

    if (df["volume"] < 0).any():
        # Should never happen -- build.py nulls negative volume out before
        # this point (findings.md: a genuine Breeze bug, "volume": -65 on
        # one real bar). This check stays as an assertion, not a fix.
        issues.append(f"CRITICAL: {(df['volume'] < 0).sum()} rows with negative volume (should have been nulled during build)")

    null_volume = df["volume"].isna().sum()
    if null_volume:
        issues.append(f"WARNING: {null_volume} rows with unknown volume (nulled out, not treated as zero)")

    zero_volume_pct = (df["volume"] == 0).mean() * 100
    if zero_volume_pct > 10:
        issues.append(f"WARNING: {zero_volume_pct:.1f}% of rows have zero volume -- eyeball before trusting (illiquid strikes do this legitimately)")

    bad_instrument_ids = df[~df["instrument_id"].str.match(r"^[A-Z]+\|")]
    if not bad_instrument_ids.empty:
        issues.append(f"CRITICAL: {len(bad_instrument_ids)} rows with malformed instrument_id (doesn't start MARKET|...)")

    if df["source"].isna().any() or df["dataset_version"].isna().any():
        issues.append("CRITICAL: null source or dataset_version -- provenance (D-12) is not optional")

    return issues

"""
D-28 spike, step 2: turn the raw sample (d28_pull_sample_data.py's output)
into canonical long-form data (D-04) with composite instrument_id (D-05),
write it as Parquet, and test the D-01 Parquet+DuckDB pattern against a
realistic query ("full chain at timestamp T") on genuine chain-shaped data.

This is scratch, not a deliverable (see ../CLAUDE.md).
"""

import json
import time
from pathlib import Path

import pandas as pd
import duckdb

HERE = Path(__file__).resolve().parent
RAW_DIR = HERE / "results" / "d28_sample" / "raw"
PARQUET_PATH = HERE / "results" / "d28_sample" / "canonical.parquet"


def build_canonical() -> pd.DataFrame:
    records = []
    for f in RAW_DIR.glob("*.json"):
        strike_str, right = f.stem.split("_")
        strike = float(strike_str)
        data = json.loads(f.read_text())
        rows = (data.get("response") or {}).get("Success") or []
        instrument_id = f"NSE|NIFTY|2026-08-04|{int(strike)}|{right}"
        for r in rows:
            records.append({
                "timestamp": r["datetime"],
                "instrument_id": instrument_id,
                "underlying": "NIFTY",
                "expiry": "2026-08-04",
                "strike": strike,
                "right": right,
                "open": float(r["open"]), "high": float(r["high"]),
                "low": float(r["low"]), "close": float(r["close"]),
                "volume": float(r["volume"]),
                "open_interest": float(r.get("open_interest") or 0),
            })
    df = pd.DataFrame.from_records(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize("Asia/Kolkata")
    return df.sort_values(["timestamp", "instrument_id"]).reset_index(drop=True)


def main():
    t0 = time.time()
    df = build_canonical()
    build_secs = time.time() - t0
    print(f"Canonical long-form built: {len(df):,} rows, {df['instrument_id'].nunique()} instruments, {build_secs:.2f}s")
    print(f"Timestamp range: {df['timestamp'].min()} to {df['timestamp'].max()}")

    PARQUET_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PARQUET_PATH, index=False)
    size_mb = PARQUET_PATH.stat().st_size / (1024 ** 2)
    print(f"Parquet written: {PARQUET_PATH} ({size_mb:.2f} MB, vs 55MB raw JSON — compression ratio {55/size_mb:.1f}x)")

    con = duckdb.connect()

    # Query 1: full chain at one specific timestamp -- the access pattern
    # D-01 flagged as one of the two dominant ones. "right" is a reserved
    # word in DuckDB SQL (RIGHT JOIN) -- must be double-quoted as an
    # identifier here, unlike in the Python/pandas code above.
    sample_ts = df["timestamp"].iloc[len(df) // 2]
    t0 = time.time()
    chain = con.execute(
        'SELECT instrument_id, strike, "right", close, open_interest '
        'FROM read_parquet(?) WHERE timestamp = ? ORDER BY strike, "right"',
        [str(PARQUET_PATH), sample_ts],
    ).df()
    q1_ms = (time.time() - t0) * 1000
    print(f"\nQuery 1 — full chain at {sample_ts}: {len(chain)} rows in {q1_ms:.1f}ms")
    print(chain.head(6).to_string(index=False))

    # Query 2: one instrument's full time series -- the other dominant pattern.
    one_instrument = df["instrument_id"].iloc[0]
    t0 = time.time()
    series = con.execute(
        "SELECT timestamp, close, open_interest FROM read_parquet(?) WHERE instrument_id = ? ORDER BY timestamp",
        [str(PARQUET_PATH), one_instrument],
    ).df()
    q2_ms = (time.time() - t0) * 1000
    print(f"\nQuery 2 — full series for {one_instrument}: {len(series)} rows in {q2_ms:.1f}ms")

    # Query 3: aggregate GEX-style scan -- OI by strike at end of window.
    t0 = time.time()
    eod = con.execute(
        'SELECT strike, "right", open_interest '
        "FROM read_parquet(?) "
        "WHERE timestamp = (SELECT max(timestamp) FROM read_parquet(?)) "
        'ORDER BY strike, "right"',
        [str(PARQUET_PATH), str(PARQUET_PATH)],
    ).df()
    q3_ms = (time.time() - t0) * 1000
    print(f"\nQuery 3 — end-of-window OI by strike: {len(eod)} rows in {q3_ms:.1f}ms")


if __name__ == "__main__":
    main()

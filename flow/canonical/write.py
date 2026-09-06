"""
Persists canonical rows to Parquet, partitioned by (instrument_type, year,
month) per D-03. Idempotent: writing into a partition that already has data
merges and dedupes on (timestamp, instrument_id) rather than overwriting or
duplicating -- safe to re-run a build over a date range that overlaps
what's already on disk (e.g. incremental daily downloads landing in the
same month's partition).
"""

from pathlib import Path

import pandas as pd


def instrument_type_of(instrument_id: str) -> str:
    suffix = instrument_id.rsplit("|", 1)[-1]
    if suffix in ("INDEX", "EQ", "FUT"):
        return suffix
    if suffix in ("CE", "PE"):
        return "OPT"
    raise ValueError(f"can't classify instrument_id: {instrument_id}")


def write_partitioned(df: pd.DataFrame, out_root: Path) -> None:
    if df.empty:
        return
    df = df.copy()
    df["_instrument_type"] = df["instrument_id"].map(instrument_type_of)
    df["_year"] = df["timestamp"].dt.year
    df["_month"] = df["timestamp"].dt.month

    for (itype, year, month), part in df.groupby(["_instrument_type", "_year", "_month"]):
        part = part.drop(columns=["_instrument_type", "_year", "_month"])
        part_dir = Path(out_root) / itype / str(year) / f"{month:02d}"
        part_dir.mkdir(parents=True, exist_ok=True)
        out_path = part_dir / "data.parquet"

        if out_path.exists():
            existing = pd.read_parquet(out_path)
            part = pd.concat([existing, part], ignore_index=True)

        part = part.drop_duplicates(subset=["timestamp", "instrument_id"], keep="last")
        part = part.sort_values(["timestamp", "instrument_id"]).reset_index(drop=True)
        part.to_parquet(out_path, index=False)

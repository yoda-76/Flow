"""
D-28 spike, part 2: NautilusTrader ships GreeksData/YieldCurveData as
@customdataclass examples, but nothing for raw open interest. Since OI is
central to this whole project (GEX, D-10, D-27...), this tests directly
whether a custom OpenInterestData type can be defined the same way and
actually round-tripped through the catalog alongside real Bar data --
not inferred from the pattern, tested against it.

This is scratch, not a deliverable (see ../CLAUDE.md).
"""

import shutil
from pathlib import Path

import duckdb
import pandas as pd

from nautilus_trader.core.data import Data
from nautilus_trader.model.custom import customdataclass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.persistence.catalog import ParquetDataCatalog

HERE = Path(__file__).resolve().parent
CANONICAL_PARQUET = HERE / "results" / "d28_sample" / "canonical.parquet"
CATALOG_PATH = HERE / "results" / "d28_sample" / "nautilus_catalog"
INSTRUMENT_ID = InstrumentId(Symbol("NIFTY26AUG04CE21600"), Venue("NSE"))


@customdataclass
class OpenInterestData(Data):
    instrument_id: InstrumentId = InstrumentId.from_str("NIFTY26AUG04CE21600.NSE")
    open_interest: float = 0.0


def main():
    con = duckdb.connect()
    df = con.execute(
        "SELECT timestamp, open_interest FROM read_parquet(?) WHERE instrument_id = ? ORDER BY timestamp",
        [str(CANONICAL_PARQUET), "NSE|NIFTY|2026-08-04|21600|CE"],
    ).df()
    print(f"Loaded {len(df)} real OI observations for {INSTRUMENT_ID}")

    # DuckDB's .df() now returns datetime64[us] (microsecond precision), not
    # pandas' traditional datetime64[ns] default -- confirmed live: a bare
    # .astype('int64') silently gave epoch-MICROSECONDS (1000x too small
    # for Nautilus's expected nanoseconds), producing 1970-01-21 instead of
    # 2026-08-xx. Must convert to datetime64[ns] explicitly first.
    ts_ns = df["timestamp"].astype("datetime64[ns, UTC]").astype("int64").to_numpy()
    oi_events = [
        OpenInterestData(
            ts_event=int(ts_ns[i]), ts_init=int(ts_ns[i]),
            instrument_id=INSTRUMENT_ID, open_interest=float(df["open_interest"].iloc[i]),
        )
        for i in range(len(df))
    ]
    print(f"Built {len(oi_events)} OpenInterestData objects. First: {oi_events[0]}")

    if CATALOG_PATH.exists():
        shutil.rmtree(CATALOG_PATH)
    CATALOG_PATH.mkdir(parents=True)
    catalog = ParquetDataCatalog(str(CATALOG_PATH))
    catalog.write_data(oi_events)

    read_back = catalog.custom_data(cls=OpenInterestData, instrument_ids=[str(INSTRUMENT_ID)])
    print(f"\nRound-trip: {len(read_back)} objects read back from catalog (wrapped as CustomData)")
    print(f"First read back: {read_back[0] if read_back else None}")
    values_back = [e.data.open_interest for e in read_back[:5]]
    print(f"First 5 OI values read back: {values_back}")
    print(f"Values match source:         {df['open_interest'].iloc[:5].tolist()}")
    print(f"Timestamps preserved correctly: {read_back[0].data.ts_event == int(ts_ns[0])}")
    print(f"Catalog files: {[str(p.relative_to(CATALOG_PATH)) for p in CATALOG_PATH.rglob('*') if p.is_file()]}")


if __name__ == "__main__":
    main()

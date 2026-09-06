"""
D-28 spike, step 3: does NautilusTrader's data ingestion path actually work
end-to-end on our real pulled sample (NIFTY 21600 CE, 2026-08-03/04)?

Tests, in order:
  1. Define an NSE OptionContract instrument with correct multiplier/lot
     size/strike/expiry (spike question #1 from 04-tooling-landscape.md §8).
  2. Wrangle our real canonical data into Nautilus Bar objects.
  3. Write to a ParquetDataCatalog, read it back, confirm round-trip.
  4. Check whether open_interest (central to this whole project) survives
     the standard Bar pipeline, or needs a custom Data type.

This is scratch, not a deliverable (see ../CLAUDE.md).
"""

import shutil
from pathlib import Path

import duckdb
import pandas as pd

from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import OptionContract
from nautilus_trader.model.enums import AssetClass, OptionKind
from nautilus_trader.model.objects import Price, Quantity, Currency
from nautilus_trader.model.data import BarType, BarSpecification
from nautilus_trader.model.enums import BarAggregation, PriceType, AggregationSource
from nautilus_trader.persistence.wranglers import BarDataWrangler
from nautilus_trader.persistence.catalog import ParquetDataCatalog

HERE = Path(__file__).resolve().parent
CANONICAL_PARQUET = HERE / "results" / "d28_sample" / "canonical.parquet"
CATALOG_PATH = HERE / "results" / "d28_sample" / "nautilus_catalog"

INSTRUMENT_ID = InstrumentId(Symbol("NIFTY26AUG04CE21600"), Venue("NSE"))


def build_instrument() -> OptionContract:
    return OptionContract(
        instrument_id=INSTRUMENT_ID,
        raw_symbol=Symbol("NIFTY26AUG04CE21600"),
        asset_class=AssetClass.INDEX,
        currency=Currency.from_str("INR"),
        price_precision=2,
        price_increment=Price.from_str("0.05"),
        multiplier=Quantity.from_int(65),   # NIFTY lot size at the time, per D-51's rules store concept
        lot_size=Quantity.from_int(65),
        underlying="NIFTY",
        option_kind=OptionKind.CALL,
        strike_price=Price.from_str("21600.00"),
        activation_ns=0,
        expiration_ns=pd.Timestamp("2026-08-04 15:30:00", tz="Asia/Kolkata").value,
        ts_event=0,
        ts_init=0,
        exchange="XNSE",  # ISO 10383 MIC for NSE
    )


def load_one_instrument_series() -> pd.DataFrame:
    con = duckdb.connect()
    df = con.execute(
        "SELECT timestamp, open, high, low, close, volume, open_interest "
        "FROM read_parquet(?) WHERE instrument_id = ? ORDER BY timestamp",
        [str(CANONICAL_PARQUET), "NSE|NIFTY|2026-08-04|21600|CE"],
    ).df()
    df = df.set_index("timestamp")
    return df


def main():
    print("--- Step 1: define OptionContract instrument ---")
    instrument = build_instrument()
    print(f"Instrument created OK: {instrument.id}")
    print(f"multiplier={instrument.multiplier} lot_size={instrument.lot_size} "
          f"strike={instrument.strike_price} expiry_ns={instrument.expiration_ns}")

    print("\n--- Step 2: wrangle real pulled data into Bar objects ---")
    df = load_one_instrument_series()
    print(f"Loaded {len(df)} rows for {INSTRUMENT_ID} from canonical Parquet")
    print(f"open_interest present in source data: {'open_interest' in df.columns}, "
          f"non-null count: {df['open_interest'].notna().sum()}")

    bar_type = BarType(
        instrument_id=INSTRUMENT_ID,
        bar_spec=BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST),
        aggregation_source=AggregationSource.EXTERNAL,
    )
    wrangler = BarDataWrangler(bar_type=bar_type, instrument=instrument)
    # pandas >= 3.0 made Copy-on-Write permanent and non-optional -- ANY
    # DataFrame's .values/.to_numpy() now returns a read-only array by
    # default, even a brand-new DataFrame built from a fresh array
    # (confirmed live: this is not specific to DuckDB's output). Nautilus's
    # Cython wrangler needs a genuinely writable buffer via memoryview, so
    # neither .copy() nor to_numpy(copy=True) into a new DataFrame helps --
    # pandas re-imposes the read-only view either way. The array's owning
    # numpy buffer must be marked writable directly.
    cols = ["open", "high", "low", "close", "volume"]
    import numpy as np
    raw = df[cols].to_numpy(copy=True, dtype=np.float64)
    raw.setflags(write=True)
    bar_input = pd.DataFrame(raw, columns=cols, index=df.index)
    bars = wrangler.process(bar_input)
    print(f"Wrangled {len(bars)} Bar objects. First: {bars[0]}")
    print("NOTE: open_interest was NOT passed to the wrangler -- BarDataWrangler.process()")
    print("only accepts open/high/low/close/volume. It is dropped unless carried separately.")

    print("\n--- Step 3: write to ParquetDataCatalog, read back ---")
    if CATALOG_PATH.exists():
        shutil.rmtree(CATALOG_PATH)
    CATALOG_PATH.mkdir(parents=True)
    catalog = ParquetDataCatalog(str(CATALOG_PATH))
    catalog.write_data([instrument])
    catalog.write_data(bars)

    read_back_instruments = catalog.instruments()
    read_back_bars = catalog.bars(bar_types=[str(bar_type)])
    print(f"Round-trip: {len(read_back_instruments)} instrument(s), {len(read_back_bars)} bar(s) read back")
    print(f"First bar read back: {read_back_bars[0] if read_back_bars else None}")
    print(f"Catalog files on disk: {[str(p.relative_to(CATALOG_PATH)) for p in CATALOG_PATH.rglob('*') if p.is_file()]}")


if __name__ == "__main__":
    main()

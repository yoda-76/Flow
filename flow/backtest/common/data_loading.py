"""
Shared data-loading/Nautilus-wiring helpers, used by every strategy's
run_backtest.py rather than copy-pasted into each one. Genuinely
cross-strategy code only -- a strategy-specific loader (e.g. one that
needs a particular options chain shape) belongs in that strategy's own
folder, not here.
"""

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from nautilus_trader.model.currencies import INR
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.wranglers import BarDataWrangler


def load_canonical_bars(canonical_root: Path, instrument_type_dir: str, start: str, end: str,
                         instrument_id: str = None) -> pd.DataFrame:
    """instrument_type_dir: 'INDEX', 'FUT', or 'OPT' (matches D-03's
    canonical partitioning, flow/canonical/write.py). instrument_id:
    optional exact-match filter (needed for FUT/OPT, which hold multiple
    contracts; INDEX has only one series so it's not needed there)."""
    where_id = f"AND instrument_id = '{instrument_id}'" if instrument_id else ""
    df = duckdb.sql(f"""
        SELECT timestamp, open, high, low, close, volume, open_interest
        FROM read_parquet('{canonical_root}/{instrument_type_dir}/**/*.parquet')
        WHERE timestamp >= '{start}' AND timestamp <= '{end} 23:59:59' {where_id}
        ORDER BY timestamp
    """).df()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("Asia/Kolkata")
    return df.set_index("timestamp")


def build_equity_instrument(instrument_id: InstrumentId, raw_symbol: str, lot_size: int,
                             currency=INR, price_precision: int = 2, price_increment: str = "0.05") -> Equity:
    """Simple tradeable-proxy instrument builder for backtesting a spot/
    index-like series. For a strategy that trades real futures/options,
    use nautilus_trader.model.instruments.FuturesContract/OptionContract
    directly instead (see experiments/d28_nautilus_ingestion_test.py for
    the proven OptionContract pattern) -- this helper only covers the
    Equity-proxy case, not a claim that every strategy should use it."""
    return Equity(
        instrument_id=instrument_id, raw_symbol=Symbol(raw_symbol), currency=currency,
        price_precision=price_precision, price_increment=Price.from_str(price_increment),
        lot_size=Quantity.from_int(lot_size), ts_event=0, ts_init=0,
    )


def load_continuous_front_month_futures(canonical_root: Path, rules_store, underlying: str,
                                         start: str, end: str) -> pd.DataFrame:
    """Splices each trading day's front-month futures bars into one
    continuous series, for backtesting a rolling futures position as a
    single Nautilus instrument without implementing multi-contract
    rollover in the engine itself. Reuses
    rules.store.MarketRulesStore.front_contract() (already built for
    D-50's futures download) for the same per-day front-month lookup,
    not a separate mechanism.

    NOT back-adjusted -- this is the raw front-month price each day,
    whichever contract that was, so the series has a real price jump at
    every rollover (the actual difference between the expiring and new
    contract's price that day). A standard, simple, clearly-documented
    simplification for a first backtest; back-adjustment (smoothing the
    roll gap) is a real v2 concern, not attempted here."""
    df = duckdb.sql(f"""
        SELECT timestamp, instrument_id, open, high, low, close, volume
        FROM read_parquet('{canonical_root}/FUT/**/*.parquet')
        WHERE timestamp >= '{start}' AND timestamp <= '{end} 23:59:59'
        ORDER BY timestamp
    """).df()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("Asia/Kolkata")
    df["date"] = df["timestamp"].dt.date

    front_by_date = {d: rules_store.front_contract(underlying, d, instrument_type="IDF") for d in df["date"].unique()}
    df["front_instrument_id"] = df["date"].map(front_by_date)
    continuous = df[df["instrument_id"] == df["front_instrument_id"]].drop(columns=["date", "front_instrument_id"])
    return continuous.set_index("timestamp").sort_index()


def wrangle_bars(df: pd.DataFrame, instrument, bar_type: BarType) -> list[Bar]:
    """df must be indexed by tz-aware timestamp with open/high/low/close/
    volume columns (extra columns are fine, ignored). Returns a list of
    Nautilus Bar objects ready for engine.add_data()."""
    # A handful of canonical rows have a genuinely unknown (nulled, not
    # zeroed -- canonical/build.py's negative-volume policy) volume.
    # Nautilus's Quantity type rejects NaN outright (confirmed live: a
    # ValueError deep in the Cython wrangler, not caught until the whole
    # 248K-bar batch had already been prepared). Dropping these rows
    # rather than filling 0 -- filling would misrepresent "we don't know"
    # as "zero trades happened", the same distinction the canonical layer
    # itself preserves.
    null_volume = df["volume"].isna().sum()
    if null_volume:
        print(f"  (dropping {null_volume} bar(s) with unknown volume before wrangling -- not zeroed)")
        df = df.dropna(subset=["volume"])
    wrangler = BarDataWrangler(bar_type=bar_type, instrument=instrument)
    # pandas 3.0's permanent Copy-on-Write makes even a fresh DataFrame's
    # array read-only; Nautilus's Cython wrangler needs a genuinely
    # writable buffer via memoryview -- neither .copy() nor
    # to_numpy(copy=True) into a new DataFrame helps, pandas re-imposes
    # the read-only view either way. The array's owning numpy buffer must
    # be marked writable directly. Confirmed live in the D-28 spike
    # (experiments/d28_nautilus_ingestion_test.py), reused here unchanged.
    cols = ["open", "high", "low", "close", "volume"]
    raw = df[cols].to_numpy(copy=True, dtype=np.float64)
    raw.setflags(write=True)
    bar_input = pd.DataFrame(raw, columns=cols, index=df.index)
    return wrangler.process(bar_input)

"""
First NautilusTrader backtest for the GEX regime follower (v1). Runs the
SAME strategy logic twice -- once per dealer-positioning convention
(standard, inverted) -- and reports both results side by side, per the
user's decision to let the backtest adjudicate D-20 rather than assume a
convention (see docs/dynamic/findings.md, GEX section).

Trades the NIFTY INDEX itself (not a future) as a simple, single,
non-rolling instrument for this first run -- the GEX model's own
underlying reference `s` is already index spot (D-19's draft assumption,
features/greeks_batch.py), so trading the same series the signal is
computed against avoids introducing a spot/future basis mismatch on top
of everything else being tested for the first time. NIFTY spot isn't
really "tradeable" in real life (only its derivatives are) -- fine for a
v1 signal-validation backtest, not something to carry into a real
strategy without swapping in a real tradeable instrument.

What "accuracy" means for THIS run, honestly: this is a wiring and signal
test, not a validated alpha claim. Known, deliberate simplifications:
  - No commission/slippage/fee model (add_venue's defaults) -- real
    NSE index trading costs would eat into any edge shown here.
  - Backtest window is limited to whatever date range currently has GEX
    computed (Jan-Apr 2024 as of when this was written) -- a small sample,
    not the full multi-year history; will widen automatically as the
    options download (D-50) progresses and features/gex.py is re-run.
  - Fixed 1-lot-equivalent position sizing, no risk management beyond
    always being flat/long/short by the regime+momentum signal.
  - Net-GEX-sign regime only (not gamma-flip price levels) -- see
    signal.py's docstring for why.
  - No hysteresis: the signal re-decides every single bar -- real
    turnover, not to be confused with the much larger, now-fixed
    resubmission bug below.

FIXED (2026-09-10): the first two runs of this backtest (this strategy
and ma_crossover_futures) used AccountType.CASH, which silently REJECTS
every short-selling order. The strategy re-submitted the rejected order
on every following bar for as long as the target stayed short, which is
why that run's "flips" count was wildly inflated relative to how often
the signal actually changed, and why the short side of both strategies
never traded at all -- the earlier reported PnL numbers (+577 / -906.55
INR) reflected an effectively long-only, mostly-broken backtest, not a
real read on either convention. Now uses common/engine_setup.py's
AccountType.MARGIN venue (leverage=1, so the economics are otherwise
identical to CASH) -- see that module's docstring for the full story.

Usage (run from flow/, as a module -- relative imports require it):
    .venv/Scripts/python.exe -m backtest.gex_regime_follower.run_backtest
"""

from pathlib import Path

import pandas as pd

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.model.data import BarSpecification, BarType
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue

from ..common.data_loading import build_equity_instrument, load_canonical_bars, wrangle_bars
from ..common.engine_setup import add_standard_venue
from ..common.nautilus_reports import extract_backtest_results
from ..common.target_position_strategy import TargetPositionStrategy, TargetPositionStrategyConfig
from .signal import build_regime_series, build_target_positions

CANONICAL_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "canonical"
GEX_TIMESERIES_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "features_tmp_gex_timeseries.parquet"

BACKTEST_START = "2024-01-01"
BACKTEST_END = "2024-04-30"
MOMENTUM_LOOKBACK_MIN = 15
TRADE_QUANTITY = 1
STARTING_BALANCE_INR = 10_000_000

VENUE = Venue("NSE")
INSTRUMENT_ID = InstrumentId(Symbol("NIFTY-INDEX"), VENUE)


def build_target_positions_ns(bar_closes: pd.Series, gex_ts: pd.DataFrame, convention: str) -> dict:
    regime = build_regime_series(gex_ts, convention)
    targets = build_target_positions(bar_closes, regime, MOMENTUM_LOOKBACK_MIN)
    return {ts.value: int(v) for ts, v in targets.items() if v != 0}


def run_single_backtest(convention: str, instrument, bar_type: BarType, bars,
                         target_positions_ns: dict) -> dict:
    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id=f"BACKTESTER-{convention.upper()}",
        logging=LoggingConfig(log_level="ERROR", log_level_file="OFF"),
    ))
    add_standard_venue(engine, VENUE, instrument, STARTING_BALANCE_INR)
    engine.add_instrument(instrument)
    engine.add_data(bars)

    strategy = TargetPositionStrategy(config=TargetPositionStrategyConfig(
        instrument_id=INSTRUMENT_ID, bar_type=bar_type, trade_quantity=TRADE_QUANTITY,
    ))
    strategy.target_positions = target_positions_ns
    engine.add_strategy(strategy)
    engine.run()

    result = {
        "convention": convention,
        "bars_seen": strategy.bars_seen,
        "bars_with_signal": strategy.bars_with_signal,
        "flips": strategy.flips,
        **extract_backtest_results(engine, VENUE, STARTING_BALANCE_INR),
    }
    engine.reset()
    engine.dispose()
    return result


def main():
    print(f"Loading NIFTY INDEX bars {BACKTEST_START} to {BACKTEST_END}...")
    df = load_canonical_bars(CANONICAL_ROOT, "INDEX", BACKTEST_START, BACKTEST_END)
    print(f"  {len(df)} bars loaded")

    gex_ts = pd.read_parquet(GEX_TIMESERIES_PATH)
    print(f"GEX time series: {len(gex_ts)} snapshots, {gex_ts['timestamp'].dt.date.nunique()} distinct days")

    instrument = build_equity_instrument(INSTRUMENT_ID, "NIFTY-INDEX", TRADE_QUANTITY)
    bar_type = BarType(
        instrument_id=INSTRUMENT_ID,
        bar_spec=BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST),
        aggregation_source=AggregationSource.EXTERNAL,
    )
    bars = wrangle_bars(df, instrument, bar_type)
    print(f"Wrangled {len(bars)} Bar objects")

    bar_closes = df["close"]

    results = []
    for convention in ("standard", "inverted"):
        target_positions_ns = build_target_positions_ns(bar_closes, gex_ts, convention)
        print(f"\n=== Running backtest: {convention} convention ({len(target_positions_ns)} non-flat signal bars) ===")
        result = run_single_backtest(convention, instrument, bar_type, bars, target_positions_ns)
        results.append(result)
        for k, v in result.items():
            print(f"  {k}: {v}")

    print("\n=== Comparison ===")
    std, inv = results
    print(f"{'metric':<25} {'standard':>15} {'inverted':>15}")
    for key in ("flips", "fills", "closed_positions", "total_realized_pnl", "win_rate"):
        print(f"{key:<25} {str(std.get(key)):>15} {str(inv.get(key)):>15}")


if __name__ == "__main__":
    main()

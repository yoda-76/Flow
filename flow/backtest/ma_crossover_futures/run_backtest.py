"""
Second NautilusTrader backtest: simple moving-average crossover on NIFTY
front-month futures (continuous, unadjusted splice -- see
common/data_loading.py's load_continuous_front_month_futures docstring).
Independent of GEX/options entirely -- exercises the shared Nautilus
wiring (common/) against a different data source and a different signal
than the first strategy, as a sanity check on the mechanics themselves.

Runs over the FULL available futures history (Jan 2024-Sep 2026, both
fully downloaded already) rather than being limited to however much GEX
data exists -- a much larger sample than the first backtest's ~4 months.

What "accuracy" means for THIS run, same honesty as the first:
  - No commission/slippage/fee model.
  - Continuous front-month series isn't back-adjusted -- a real price
    jump exists at every monthly rollover, which this v1 doesn't smooth
    out or treat specially (the crossover signal just reacts to it like
    any other price move).
  - Fixed 1-lot-equivalent sizing, MA windows (20/100 bars) picked as
    round numbers, not fitted -- "we'll optimize strategies later."
  - No hysteresis: the signal re-decides every single bar -- real
    turnover, not to be confused with the much larger, now-fixed
    resubmission bug below.

FIXED (2026-09-10): this run originally used AccountType.CASH, which
silently REJECTS every short-selling order -- confirmed via
on_order_rejected ("SHORT SELLING not permitted on a CASH account"). The
strategy re-submitted the rejected order on every following bar for as
long as the target stayed short, producing 124,005 "flips" against a
signal that only actually changes ~170 times per 1.5 months of data --
almost all of those were doomed resubmission attempts, and the short side
of the strategy never traded at all. Now uses common/engine_setup.py's
AccountType.MARGIN venue (leverage=1, economics otherwise identical to
CASH) -- see that module's docstring for the full story.

Usage (run from flow/, as a module):
    .venv/Scripts/python.exe -m backtest.ma_crossover_futures.run_backtest
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig  # noqa: E402
from nautilus_trader.config import LoggingConfig  # noqa: E402
from nautilus_trader.model.data import BarSpecification, BarType  # noqa: E402
from nautilus_trader.model.enums import AggregationSource, BarAggregation, PriceType  # noqa: E402
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue  # noqa: E402

from rules.store import MarketRulesStore  # noqa: E402

from ..common.data_loading import build_equity_instrument, load_continuous_front_month_futures, wrangle_bars  # noqa: E402
from ..common.engine_setup import add_standard_venue  # noqa: E402
from ..common.nautilus_reports import extract_backtest_results  # noqa: E402
from ..common.target_position_strategy import TargetPositionStrategy, TargetPositionStrategyConfig  # noqa: E402
from .signal import build_target_positions  # noqa: E402

CANONICAL_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "canonical"

UNDERLYING = "NIFTY"
BACKTEST_START = "2024-01-01"
BACKTEST_END = "2026-09-04"
FAST_WINDOW = 20
SLOW_WINDOW = 100
TRADE_QUANTITY = 1
STARTING_BALANCE_INR = 10_000_000

VENUE = Venue("NSE")
INSTRUMENT_ID = InstrumentId(Symbol("NIFTY-FUT-CONTINUOUS"), VENUE)


def main():
    print(f"Loading continuous front-month NIFTY futures {BACKTEST_START} to {BACKTEST_END}...")
    store = MarketRulesStore()
    df = load_continuous_front_month_futures(CANONICAL_ROOT, store, UNDERLYING, BACKTEST_START, BACKTEST_END)
    print(f"  {len(df)} bars loaded, {df['instrument_id'].nunique()} distinct contracts spliced")

    instrument = build_equity_instrument(INSTRUMENT_ID, "NIFTY-FUT-CONTINUOUS", TRADE_QUANTITY)
    bar_type = BarType(
        instrument_id=INSTRUMENT_ID,
        bar_spec=BarSpecification(1, BarAggregation.MINUTE, PriceType.LAST),
        aggregation_source=AggregationSource.EXTERNAL,
    )
    bars = wrangle_bars(df, instrument, bar_type)
    print(f"Wrangled {len(bars)} Bar objects")

    targets = build_target_positions(df["close"], FAST_WINDOW, SLOW_WINDOW)
    target_positions_ns = {ts.value: int(v) for ts, v in targets.items() if v != 0}
    print(f"{len(target_positions_ns)} non-flat signal bars (fast={FAST_WINDOW}, slow={SLOW_WINDOW})")

    engine = BacktestEngine(config=BacktestEngineConfig(
        trader_id="BACKTESTER-MA-CROSSOVER",
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
        "bars_seen": strategy.bars_seen,
        "bars_with_signal": strategy.bars_with_signal,
        "flips": strategy.flips,
        **extract_backtest_results(engine, VENUE, STARTING_BALANCE_INR),
    }
    engine.reset()
    engine.dispose()

    print("\n=== Results ===")
    for k, v in result.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()

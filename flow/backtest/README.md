# flow/backtest/ — how to add a new strategy

## Layout

```
flow/backtest/
├── common/                          shared across every strategy
│   ├── data_loading.py              canonical Parquet -> Nautilus Bar/Instrument
│   ├── engine_setup.py              venue setup (account type, fee model)
│   ├── nautilus_reports.py          result extraction from a finished BacktestEngine
│   └── target_position_strategy.py  the shared Nautilus Strategy adapter
├── <strategy_name>/                 one folder per strategy, nothing split elsewhere
│   ├── signal.py                    pure pandas: real inputs -> target position, no Nautilus import
│   └── run_backtest.py              orchestrator: loads data, wires Nautilus, runs, reports
├── gex_regime_follower/             example: GEX-based directional (NIFTY index)
└── ma_crossover_futures/            example: MA crossover (NIFTY continuous futures)
```

One folder per strategy, nothing for that strategy lives anywhere else.
`common/` is only for code genuinely shared by 2+ strategies — see "When
something belongs in common/" below before adding to it.

## Converting a strategy idea into a testable script

You have a trading idea. Here's how it becomes a script you can run and
trust the output of.

### 1. Write `signal.py` first, with zero Nautilus involved

This is the actual thinking part: given price history (and whatever else
your idea needs — GEX, indicators, order flow), what's the target
position at each point in time? Write it as plain pandas/numpy functions
that take Series/DataFrames and return a target-position Series indexed
by timestamp: `+1` (long), `-1` (short), `0` (flat / no opinion — see
below).

Rules that matter here:
- **No Nautilus imports in this file, ever.** If you can't write your
  signal without touching `nautilus_trader`, the signal is doing too
  much — separate the "what do I think" from "how do I execute it."
  This is what makes the signal testable in isolation (next step) and
  reusable if you ever swap backtest engines.
- **`0` means "no opinion," not "I looked and decided flat."** During a
  warmup period (e.g. before a moving average has enough history), or
  wherever your data has a gap, return `0` — never guess a direction to
  fill a hole. Both example strategies do this (`signal.py` in each
  folder, warmup and no-GEX-snapshot cases).
- **Take your model's genuinely open questions as arguments, not
  constants.** `gex_regime_follower/signal.py` takes `convention` as a
  parameter (GEX's dealer-positioning sign is an open question, D-20) so
  the runner can test both sides rather than the signal silently picking
  one. If your idea has an unresolved parameter like this, do the same.

Give it a `if __name__ == "__main__":` self-test block with synthetic
data — a handful of hand-built prices/inputs where you know what the
target position *should* be, asserted directly. Run it with
`.venv/Scripts/python.exe -m backtest.<strategy_name>.signal`. This has
to pass before you ever touch Nautilus — if your signal is wrong, no
amount of correct execution machinery will save the backtest.

### 2. Write `run_backtest.py`, reusing `common/` — don't rebuild Nautilus wiring

This is glue, not thinking. Shape (copy `ma_crossover_futures/run_backtest.py`
as the more complete example — index-only `gex_regime_follower` skips the
futures-splicing step):

```python
from ..common.data_loading import build_equity_instrument, load_canonical_bars, wrangle_bars
from ..common.engine_setup import add_standard_venue
from ..common.nautilus_reports import extract_backtest_results
from ..common.target_position_strategy import TargetPositionStrategy, TargetPositionStrategyConfig
from .signal import build_target_positions

def main():
    df = load_canonical_bars(...)                      # or load_continuous_front_month_futures for futures
    instrument = build_equity_instrument(...)
    bar_type = BarType(...)
    bars = wrangle_bars(df, instrument, bar_type)

    targets = build_target_positions(df["close"], ...)  # your signal.py
    target_positions_ns = {ts.value: int(v) for ts, v in targets.items() if v != 0}

    engine = BacktestEngine(config=BacktestEngineConfig(...))
    add_standard_venue(engine, VENUE, instrument, STARTING_BALANCE)
    engine.add_instrument(instrument)
    engine.add_data(bars)

    strategy = TargetPositionStrategy(config=TargetPositionStrategyConfig(
        instrument_id=INSTRUMENT_ID, bar_type=bar_type, trade_quantity=TRADE_QUANTITY,
    ))
    strategy.target_positions = target_positions_ns
    engine.add_strategy(strategy)
    engine.run()

    result = {**extract_backtest_results(engine, VENUE, STARTING_BALANCE), ...}
```

You will only need your own `Strategy` subclass (a new `strategy.py` in
your folder) if your idea needs something `TargetPositionStrategy` can't
express — multi-leg orders, stops, position sizing beyond a fixed
quantity, reacting to fills mid-bar. If a bare target-position-per-bar
is enough (most simple directional ideas are), don't write one.

Run it: `.venv/Scripts/python.exe -m backtest.<strategy_name>.run_backtest`
— always as a module, from `flow/` (relative imports require it).

### 3. Sanity-check the output before trusting any PnL number

Three real bugs have already been caught this way (full writeups in
`docs/dynamic/findings.md`) — check for their signatures before believing
a result:

- **`flips` should roughly match how often your raw signal actually
  changes, not the number of bars with a non-zero signal.** If `flips`
  is way higher than the signal's own change-count (check via
  `signal.py` directly, independent of Nautilus), something is
  re-submitting rejected orders. The known cause: `AccountType.CASH`
  silently rejects short sales — `add_standard_venue` already defaults
  to `MARGIN` to avoid this, but if you build your own venue setup,
  don't reintroduce `CASH` for anything that goes short.
- **A commission-free result isn't a real result.** `add_standard_venue`
  applies a flat placeholder fee by default (`FixedFeeModel`,
  ₹20/order) — don't pass `fee_model=None` unless you specifically want
  to isolate signal quality from cost, and if you do, say so in your
  `run_backtest.py`'s docstring the way the existing two do.
- **Don't trust `positions_report["realized_pnl"].sum()` directly.**
  Nautilus reports currency columns as `Money.__str__` ("6.80 INR"), and
  pandas silently does *string concatenation* instead of numeric
  addition on that column — no error, just a wrong number (or, if you're
  lucky, a garbage string that fails loudly at `float()`). Use
  `extract_backtest_results()` (`common/nautilus_reports.py`), which
  already parses this correctly, rather than touching the reports
  yourself.
- **NaN volume crashes the wrangler, not gracefully.** A handful of
  canonical rows have genuinely unknown (nulled, not zeroed) volume —
  `wrangle_bars()` already drops those rows before handing data to
  Nautilus (logged, not silently zeroed). If you load data some other
  way, you'll hit `ValueError: invalid 'value', was nan` deep in Cython
  unless you handle this yourself.

## When something belongs in `common/`

Only once **2+ strategies actually need it** — not because it seems
generally useful. Everything currently in `common/` was extracted after
a second strategy needed the exact same thing a first one already had
(`target_position_strategy.py`) or after a bug surfaced that would
otherwise get re-introduced per strategy (`engine_setup.py`,
`nautilus_reports.py`'s money parsing, `data_loading.py`'s NaN-volume
handling). If your strategy needs something no other strategy needs yet,
it goes in your own folder, not here.

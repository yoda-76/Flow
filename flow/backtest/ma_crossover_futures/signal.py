"""
Simple moving-average crossover signal (v1) -- second backtest strategy,
completely independent of GEX/options, trading NIFTY front-month futures
instead of the index. Deliberately the simplest classic directional
signal (no tuning, no optimization -- "we'll optimize strategies later"
per the user); the point of this one is to exercise the shared Nautilus
wiring (common/) a second time against a different data source (futures,
via common/data_loading.py's continuous front-month splice) and a
completely different, GEX-independent signal, as a sanity check that the
first backtest's mechanics weren't specific to that one setup.
"""

import pandas as pd


def build_target_positions(bar_closes: pd.Series, fast_window: int, slow_window: int) -> pd.Series:
    """+1 when the fast MA is above the slow MA, -1 when below, 0 during
    the slow MA's warmup period (not enough history yet -- stay flat,
    don't guess). No deadband/threshold on the crossover itself -- a
    known, deliberate v1 simplification (optimization deferred)."""
    fast = bar_closes.rolling(fast_window).mean()
    slow = bar_closes.rolling(slow_window).mean()
    target = pd.Series(0, index=bar_closes.index)
    valid = slow.notna()
    target.loc[valid] = (fast.loc[valid] > slow.loc[valid]).map({True: 1, False: -1})
    return target.rename("target_position")


if __name__ == "__main__":
    idx = pd.date_range("2024-01-01 09:15", periods=100, freq="1min", tz="Asia/Kolkata")
    # Uptrend then downtrend -- fast MA should lead above slow MA in the
    # uptrend, and lag below it in the downtrend.
    prices = [100 + i * 0.5 for i in range(50)] + [125 - i * 0.5 for i in range(50)]
    closes = pd.Series(prices, index=idx)

    targets = build_target_positions(closes, fast_window=5, slow_window=20)

    # Warmup period (< slow_window bars of history) must be flat, not guessed.
    assert (targets.iloc[:19] == 0).all(), targets.iloc[:19]

    # Deep into the uptrend, fast MA clearly leads -> long.
    assert targets.iloc[40] == 1, targets.iloc[40]
    # Deep into the downtrend, fast MA clearly lags -> short.
    assert targets.iloc[90] == -1, targets.iloc[90]

    print("All self-tests passed.")

"""
GEX regime signal (v1, first backtest -- see ./strategy.py). Deliberately
pure pandas, no NautilusTrader import here at all, so the signal logic is
testable and inspectable on its own before it ever touches a backtest
engine.

The strategy this feeds: "positive gamma" (net GEX > 0) implies dealers'
hedging flow dampens moves -> expect mean-reversion; "negative gamma"
(net GEX < 0) implies dealers' hedging flow amplifies moves -> expect
momentum/trending. This is the standard, widely-cited framing -- but
D-20 (dealer-positioning convention) is still open for NSE specifically,
which is exactly why gex.py computes BOTH the standard and inverted
conventions rather than picking one, and this module takes a
`convention` argument rather than assuming.

v1 uses the simple sign of total (net) GEX as the regime indicator, not
the gamma-flip price level -- flip requires a strike-level sign change to
interpolate against and is None whenever a chain doesn't have one
(common, see gex.py's own self-test), which would leave large stretches
of the backtest with no signal at all. Net-GEX sign is always available
whenever any GEX was computed for that timestamp. Revisit toward
flip-based levels once real backtest results argue for it -- not a
premature v2 abstraction here (CLAUDE.md).
"""

import pandas as pd


def build_regime_series(gex_ts: pd.DataFrame, convention: str = "standard") -> pd.Series:
    """gex_ts: output of features/gex.py's compute_gex_timeseries()
    (columns: timestamp, total_gex_standard, total_gex_inverted).
    Returns a Series indexed by timestamp, values +1 (positive gamma,
    mean-reversion regime) or -1 (negative gamma, momentum regime)."""
    if convention not in ("standard", "inverted"):
        raise ValueError(f"convention must be 'standard' or 'inverted', got {convention!r}")
    col = f"total_gex_{convention}"
    s = gex_ts.set_index("timestamp")[col]
    return s.apply(lambda v: 1 if v > 0 else -1).rename("regime")


def build_target_positions(bar_closes: pd.Series, regime: pd.Series, momentum_lookback: int) -> pd.Series:
    """bar_closes: Series of close prices indexed by timestamp (the FULL
    bar series being traded, not just timestamps with a GEX signal).
    regime: output of build_regime_series (sparser -- only timestamps
    with a computed GEX snapshot).

    Returns a Series indexed like bar_closes: +1 (target long), -1
    (target short), or 0 (no signal available this bar -- stay flat, never
    guess a direction). Momentum = close[t] - close[t-momentum_lookback];
    in a negative-gamma (momentum) regime, trade WITH that sign; in a
    positive-gamma (mean-reversion) regime, trade AGAINST it."""
    momentum = bar_closes.diff(momentum_lookback)
    regime_aligned = regime.reindex(bar_closes.index)  # NaN where no GEX snapshot exists for this bar

    def target(row):
        mom, reg = row["momentum"], row["regime"]
        if pd.isna(mom) or pd.isna(reg):
            return 0
        if mom == 0:
            return 0
        momentum_sign = 1 if mom > 0 else -1
        return momentum_sign if reg < 0 else -momentum_sign

    df = pd.DataFrame({"momentum": momentum, "regime": regime_aligned})
    return df.apply(target, axis=1).rename("target_position")


if __name__ == "__main__":
    # Offline self-test with synthetic data -- no market data needed.
    idx = pd.date_range("2024-01-01 09:15", periods=40, freq="1min", tz="Asia/Kolkata")
    closes = pd.Series([100 + i * 0.5 for i in range(40)], index=idx)  # steady uptrend

    gex_ts = pd.DataFrame({
        "timestamp": idx[::4],  # sparser than the bar series, like real data
        "total_gex_standard": [-5.0] * 5 + [5.0] * 5,   # negative gamma first half, positive second
        "total_gex_inverted": [5.0] * 5 + [-5.0] * 5,
    })

    regime_std = build_regime_series(gex_ts, "standard")
    assert (regime_std.iloc[:5] == -1).all() and (regime_std.iloc[5:] == 1).all()

    targets_std = build_target_positions(closes, regime_std, momentum_lookback=1)
    # Steady uptrend -> momentum is always positive where defined.
    # Negative-gamma (regime=-1) window -> trade WITH momentum -> target=+1.
    # Positive-gamma (regime=+1) window -> trade AGAINST momentum -> target=-1.
    first_signal_ts = regime_std.index[1]  # index[0] has no prior bar, momentum is NaN there
    last_signal_ts = regime_std.index[-1]
    assert targets_std.loc[first_signal_ts] == 1, targets_std.loc[first_signal_ts]
    assert targets_std.loc[last_signal_ts] == -1, targets_std.loc[last_signal_ts]

    # Inverted convention must give the exact opposite target at every signal timestamp.
    regime_inv = build_regime_series(gex_ts, "inverted")
    targets_inv = build_target_positions(closes, regime_inv, momentum_lookback=1)
    signal_ts = regime_std.index
    assert (targets_std.loc[signal_ts] == -targets_inv.loc[signal_ts]).all()

    # Bars with no GEX snapshot at all (beyond the last signal timestamp) -> target 0, not guessed.
    assert (targets_std.loc[targets_std.index > last_signal_ts] == 0).all()

    print("All self-tests passed.")

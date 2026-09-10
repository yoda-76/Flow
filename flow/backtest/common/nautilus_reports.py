"""
Shared result-extraction helpers for a finished BacktestEngine run.
"""

import pandas as pd


def parse_money(x):
    """Nautilus reports currency amounts as Money's __str__ ("6.80 INR"),
    not raw floats -- pandas .sum() on that column silently does STRING
    CONCATENATION, not numeric addition (caught live on the first real
    GEX backtest run: produced a several-KB garbage string instead of
    erroring loudly, only failing later at the float() conversion). Parse
    explicitly rather than assuming the column is already numeric."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    return float(str(x).split(" ")[0])


def extract_backtest_results(engine, venue, starting_balance: float) -> dict:
    """Returns the Nautilus-report-derived subset of a result dict (fills,
    closed_positions, final_balance, total_realized_pnl, win_rate).
    Callers merge this with their own strategy-specific counters (bars
    seen, signal coverage, etc.) -- this function only knows about what
    the engine's own reports carry."""
    account_report = engine.trader.generate_account_report(venue)
    fills_report = engine.trader.generate_order_fills_report()
    positions_report = engine.trader.generate_positions_report()

    final_balance = parse_money(account_report["total"].iloc[-1]) if not account_report.empty else None
    realized_pnl_series = (positions_report["realized_pnl"].map(parse_money)
                            if not positions_report.empty and "realized_pnl" in positions_report else None)
    realized_pnl = float(realized_pnl_series.sum()) if realized_pnl_series is not None else None

    result = {
        "fills": len(fills_report),
        "closed_positions": len(positions_report),
        "final_balance": final_balance,
        "starting_balance": starting_balance,
        "total_realized_pnl": realized_pnl,
    }
    if realized_pnl_series is not None and len(realized_pnl_series):
        result["win_rate"] = float((realized_pnl_series > 0).sum() / len(realized_pnl_series))
    return result

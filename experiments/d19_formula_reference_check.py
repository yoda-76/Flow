"""
D-19 rigorous formula check: does Nautilus's black_scholes_greeks/
imply_vol_and_greeks match an independent, trusted reference
implementation (py_vollib) on synthetic inputs -- no real market data
involved at all, so no stale prices, no spot-vs-forward ambiguity, no
solved-IV uncertainty. This is the test that actually isolates "is the
formula/pipeline implemented correctly," decoupled from anything Dhan- or
Breeze-specific.

py_vollib assumes plain Black-Scholes (continuous dividend q=0), which in
Nautilus's cost-of-carry parameterization (b) corresponds to b=r.

This is scratch, not a deliverable (see ../CLAUDE.md).
"""

from nautilus_trader.model.greeks import black_scholes_greeks, imply_vol_and_greeks

from py_vollib.black_scholes import black_scholes as bs_price
from py_vollib.black_scholes.greeks.analytical import delta as bs_delta
from py_vollib.black_scholes.greeks.analytical import gamma as bs_gamma
from py_vollib.black_scholes.greeks.analytical import theta as bs_theta
from py_vollib.black_scholes.greeks.analytical import vega as bs_vega
from py_vollib.black_scholes.implied_volatility import implied_volatility as bs_iv


SCENARIOS = [
    # (S, K, T_years, r, vol, label)
    (100.0, 100.0, 1.0, 0.05, 0.20, "textbook ATM, 1yr"),
    (23900.0, 23900.0, 30 / 365, 0.065, 0.10, "NIFTY-like ATM, 30d"),
    (23900.0, 23900.0, 2.5 / 365, 0.065, 0.13, "NIFTY-like ATM, 2.5d (near-expiry)"),
    (23900.0, 24500.0, 30 / 365, 0.065, 0.10, "NIFTY-like OTM call, 30d"),
    (23900.0, 23000.0, 30 / 365, 0.065, 0.10, "NIFTY-like ITM call, 30d"),
    (23900.0, 23900.0, 180 / 365, 0.065, 0.15, "NIFTY-like ATM, 6mo"),
]


def main():
    print(f"{'Scenario':<38} | {'Greek':>6} | {'Nautilus':>12} | {'py_vollib':>12} | {'Diff':>10}")
    print("-" * 100)
    max_rel_diff = 0.0
    for s, k, t, r, vol, label in SCENARIOS:
        flag = "c"
        # py_vollib plain BS == Nautilus's cost-of-carry form with b=r
        b = r
        nautilus_g = black_scholes_greeks(s, r, b, vol, True, k, t)

        py_price = bs_price(flag, s, k, t, r, vol)
        py_d = bs_delta(flag, s, k, t, r, vol)
        py_g = bs_gamma(flag, s, k, t, r, vol)
        # No rescaling needed: py_vollib's theta() is already per-calendar-day
        # by default (matches Nautilus's documented "daily changes" theta
        # convention), and its vega() is already per-1%-vol-change (matches
        # Nautilus's documented convention too) -- confirmed by the first
        # run of this script, where applying *365 and *100 produced exact
        # 365x/100x "mismatches", meaning the raw py_vollib values already
        # agreed and my own extra scaling was the bug.
        py_t = bs_theta(flag, s, k, t, r, vol)
        py_v = bs_vega(flag, s, k, t, r, vol)

        for name, nval, pval in [
            ("price", nautilus_g.price, py_price),
            ("delta", nautilus_g.delta, py_d),
            ("gamma", nautilus_g.gamma, py_g),
            ("theta", nautilus_g.theta, py_t),
            ("vega", nautilus_g.vega, py_v),
        ]:
            diff = nval - pval
            rel = abs(diff) / (abs(pval) + 1e-9)
            max_rel_diff = max(max_rel_diff, rel)
            flag_str = "  <-- MISMATCH" if rel > 0.02 else ""
            print(f"{label:<38} | {name:>6} | {nval:>12.6f} | {pval:>12.6f} | {diff:>10.6f}{flag_str}")
        print()

    print(f"Max relative difference across all scenarios/greeks: {max_rel_diff*100:.3f}%")

    # Also check imply_vol_and_greeks: solve IV from a py_vollib-generated
    # price, and confirm we recover the original input vol.
    print("\n=== IV solver round-trip (fully synthetic, no real market data) ===")
    for s, k, t, r, vol, label in SCENARIOS:
        true_price = bs_price("c", s, k, t, r, vol)
        result = imply_vol_and_greeks(s, r, r, True, k, t, true_price)
        recovered_vol = result.vol
        print(f"{label:<38} | true_vol={vol:.4f} | recovered_vol={recovered_vol:.6f} | diff={recovered_vol-vol:+.6f}")


if __name__ == "__main__":
    main()

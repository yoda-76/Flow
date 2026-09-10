"""
Vectorized (numpy/pandas) batch Greeks computation over a full canonical
options dataset -- the same math as features/greeks.py's scalar reference
implementation (already cross-checked against py_vollib to 1e-12,
findings.md), rewritten for array inputs so a multi-million-row chain runs
in seconds instead of a per-row Python loop. Cross-validated against the
scalar reference on a random sample every run (see main()) rather than
trusted blindly -- a vectorized rewrite is exactly the kind of thing that
silently diverges from its scalar original.

v1 defaults, both genuinely open per D-19 (still BLOCKED by S-04, not
decided) -- documented here as placeholders, not answers:
  - underlying_reference: spot (NIFTY index canonical data), b = r. D-19's
    own text: "Draft assumed: Black-Scholes, unqualified" -- this matches
    that draft assumption, not a resolved choice.
  - risk_free_rate: flat constant (see RISK_FREE_RATE below), not sourced
    from any real curve. D-19's "risk-free rate source and tenor" question
    is untouched by this -- change the constant, or wire in a real source,
    once that's decided.

IV solve failures (deep ITM/OTM, no-arbitrage violations, non-convergence)
come back as NaN, never a guess -- same policy as the scalar module. The
fraction of NaN rows is exactly D-19/S-04's open "what fraction of a real
chain fails?" checklist item, now answerable empirically once this runs
against real downloaded data (see main()'s printed summary).

Only the Newton-Raphson path is vectorized (no bisection fallback here,
unlike the scalar module) -- acceptable for v1 since the vast majority of
strikes in a real chain are liquid enough to converge; a row that fails
Newton is left NaN rather than force-converged via a slower per-row
bisection pass.
"""

import numpy as np
import pandas as pd
from scipy.special import ndtr

FEATURE_VERSION = "greeks_v1"

# Placeholder -- D-19's "risk-free rate source and tenor" is still open.
# ~India short-tenor rate ballpark for the covered period, not sourced
# from any real curve. Revisit once D-19 actually decides a source.
RISK_FREE_RATE = 0.065

IV_MAX_ITER = 100
IV_TOL = 1e-4
IV_INITIAL_GUESS = 0.3

# Minimum vega (raw units) for a Newton "convergence" to be trusted. A
# price-space residual under IV_TOL can still correspond to a large vol
# error when vega is tiny (deep ITM/OTM close to expiry -- exactly D-19's
# flagged failure mode). Found empirically while cross-validating against
# the scalar reference (main() below): a real case with s~24342, k~26900,
# t~1.9 days had vega ~1e-5 to 1e-2 and "converged" to an IV off by 0.045
# from the scalar solver's answer. 1e-8 (the original threshold) was far
# too permissive; vega is in the thousands for normal liquid ATM options
# on this instrument's price scale, so 1.0 cleanly separates real
# convergence from this failure mode without excluding legitimate cases.
IV_MIN_STABLE_VEGA = 1.0


def _norm_cdf(x):
    return ndtr(x)


def _norm_pdf(x):
    return np.exp(-0.5 * x * x) / np.sqrt(2 * np.pi)


def _parse_option_instrument_id(instrument_id: str):
    # NSE|NIFTY|{expiry}|{strike}|{CE|PE}
    parts = instrument_id.split("|")
    return parts[1], parts[2], float(parts[3]), parts[4]


def _bs_price_vec(s, k, t, r, b, vol, is_call):
    d1 = (np.log(s / k) + (b + 0.5 * vol * vol) * t) / (vol * np.sqrt(t))
    d2 = d1 - vol * np.sqrt(t)
    carry = np.exp((b - r) * t)
    disc = np.exp(-r * t)
    call = s * carry * _norm_cdf(d1) - k * disc * _norm_cdf(d2)
    put = k * disc * _norm_cdf(-d2) - s * carry * _norm_cdf(-d1)
    return np.where(is_call, call, put)


def _bs_vega_vec(s, k, t, r, b, vol):
    d1 = (np.log(s / k) + (b + 0.5 * vol * vol) * t) / (vol * np.sqrt(t))
    carry = np.exp((b - r) * t)
    return s * carry * _norm_pdf(d1) * np.sqrt(t)


def _bs_greeks_vec(s, k, t, r, b, vol, is_call):
    d1 = (np.log(s / k) + (b + 0.5 * vol * vol) * t) / (vol * np.sqrt(t))
    d2 = d1 - vol * np.sqrt(t)
    carry = np.exp((b - r) * t)
    disc = np.exp(-r * t)
    pdf_d1 = _norm_pdf(d1)

    gamma = carry * pdf_d1 / (s * vol * np.sqrt(t))
    vega = s * carry * pdf_d1 * np.sqrt(t)

    delta_call = carry * _norm_cdf(d1)
    delta_put = carry * (_norm_cdf(d1) - 1)
    delta = np.where(is_call, delta_call, delta_put)

    theta_call = (-s * carry * pdf_d1 * vol / (2 * np.sqrt(t))
                  - (b - r) * s * carry * _norm_cdf(d1) - r * k * disc * _norm_cdf(d2))
    theta_put = (-s * carry * pdf_d1 * vol / (2 * np.sqrt(t))
                 + (b - r) * s * carry * _norm_cdf(-d1) + r * k * disc * _norm_cdf(-d2))
    theta = np.where(is_call, theta_call, theta_put)

    rho_call = k * t * disc * _norm_cdf(d2)
    rho_put = -k * t * disc * _norm_cdf(-d2)
    rho = np.where(is_call, rho_call, rho_put)

    return delta, gamma, theta, vega, rho


def _no_arbitrage_floor_vec(s, k, t, r, b, is_call):
    carry = np.exp((b - r) * t)
    disc = np.exp(-r * t)
    call_floor = np.maximum(0.0, s * carry - k * disc)
    put_floor = np.maximum(0.0, k * disc - s * carry)
    return np.where(is_call, call_floor, put_floor)


def implied_vol_vec(price, s, k, t, r, b, is_call,
                     max_iter: int = IV_MAX_ITER, tol: float = IV_TOL):
    """Vectorized Newton-Raphson. Returns an array of vols with NaN where
    the solve failed (no-arbitrage violation, non-convergence, unstable
    vega) -- never a fabricated number."""
    price = np.asarray(price, dtype=float)
    s = np.asarray(s, dtype=float)
    k = np.asarray(k, dtype=float)
    t = np.asarray(t, dtype=float)
    is_call = np.asarray(is_call, dtype=bool)

    valid = (s > 0) & (k > 0) & (t > 0) & (price > 0)
    floor = np.full_like(price, np.nan)
    floor[valid] = _no_arbitrage_floor_vec(s[valid], k[valid], t[valid], r, b, is_call[valid])
    valid &= price >= (floor - tol)

    vol = np.full_like(price, IV_INITIAL_GUESS)
    converged = np.zeros_like(price, dtype=bool)

    for _ in range(max_iter):
        active = valid & ~converged
        if not active.any():
            break
        model_price = _bs_price_vec(s[active], k[active], t[active], r, b, vol[active], is_call[active])
        vega = _bs_vega_vec(s[active], k[active], t[active], r, b, vol[active])
        diff = model_price - price[active]

        price_close = np.abs(diff) < tol
        stable = vega > IV_MIN_STABLE_VEGA
        # A price-space match is only trustworthy where vega is large
        # enough that the match couldn't be a coincidence of the
        # near-zero-vega regime (deep ITM/OTM near expiry, where many
        # different vols price almost identically -- see IV_MIN_STABLE_VEGA's
        # comment). price_close & ~stable is therefore a FAILURE, not a
        # win, even though the price residual looks converged.
        accept = price_close & stable

        idx = np.flatnonzero(active)
        converged[idx[accept]] = True

        step_mask = stable & ~price_close
        new_vol = vol[idx[step_mask]] - diff[step_mask] / vega[step_mask]
        vol[idx[step_mask]] = np.where(new_vol > 0, new_vol, np.nan)

        # Unstable vega, whether or not price happened to look close --
        # give up on this row rather than accept an unreliable result.
        give_up_mask = ~stable
        vol[idx[give_up_mask]] = np.nan
        valid[idx[give_up_mask]] = False

    result = np.where(valid & converged, vol, np.nan)
    return result


def compute_greeks_batch(options_df: pd.DataFrame, spot_df: pd.DataFrame,
                          r: float = RISK_FREE_RATE, b: float = None) -> pd.DataFrame:
    """options_df: canonical options rows (timestamp, instrument_id, close, ...).
    spot_df: canonical index rows (timestamp, close) -- the underlying
    reference (v1: spot, per D-19's draft assumption; b defaults to r,
    i.e. no separate dividend adjustment)."""
    if b is None:
        b = r

    parsed = options_df["instrument_id"].apply(_parse_option_instrument_id)
    underlying = parsed.apply(lambda x: x[0])
    expiry = pd.to_datetime(parsed.apply(lambda x: x[1]))
    strike = parsed.apply(lambda x: x[2]).astype(float)
    option_type = parsed.apply(lambda x: x[3])

    df = options_df.copy()
    df["underlying"] = underlying.values
    df["expiry"] = expiry.values
    df["k"] = strike.values
    df["is_call"] = (option_type == "CE").values

    spot = spot_df[["timestamp", "close"]].rename(columns={"close": "s"})
    df = df.merge(spot, on="timestamp", how="inner")

    df["t"] = (df["expiry"] - df["timestamp"].dt.tz_localize(None)).dt.total_seconds() / (365 * 86400)
    df = df[df["t"] > 0].reset_index(drop=True)

    price = df["close"].to_numpy(dtype=float)
    s = df["s"].to_numpy(dtype=float)
    k = df["k"].to_numpy(dtype=float)
    t = df["t"].to_numpy(dtype=float)
    is_call = df["is_call"].to_numpy(dtype=bool)

    iv = implied_vol_vec(price, s, k, t, r, b, is_call)

    solved = ~np.isnan(iv)
    delta = np.full_like(iv, np.nan)
    gamma = np.full_like(iv, np.nan)
    theta = np.full_like(iv, np.nan)
    vega = np.full_like(iv, np.nan)
    rho = np.full_like(iv, np.nan)
    if solved.any():
        d, g, th, v, rh = _bs_greeks_vec(s[solved], k[solved], t[solved], r, b, iv[solved], is_call[solved])
        delta[solved], gamma[solved], theta[solved], vega[solved], rho[solved] = d, g, th, v, rh

    return pd.DataFrame({
        "timestamp": df["timestamp"], "instrument_id": df["instrument_id"],
        "underlying": df["underlying"], "expiry": df["expiry"], "strike": df["k"],
        "option_type": np.where(df["is_call"], "CE", "PE"),
        "s": s, "t": t, "r": r, "b": b, "price": price,
        "open_interest": df["open_interest"].to_numpy(dtype=float),
        "iv": iv, "delta": delta, "gamma": gamma, "theta": theta, "vega": vega, "rho": rho,
        "feature_version": FEATURE_VERSION,
    })


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from features.greeks import GreeksConfig, bs_greeks, implied_vol  # noqa: E402

    rng = np.random.default_rng(0)
    n = 500
    s = rng.uniform(24000, 26000, n)
    k = rng.choice(np.arange(23000, 27000, 50), n).astype(float)
    t = rng.uniform(1 / 365, 45 / 365, n)
    is_call = rng.integers(0, 2, n).astype(bool)
    r_test, b_test = 0.065, 0.065
    vol_true = rng.uniform(0.08, 0.35, n)
    price = _bs_price_vec(s, k, t, r_test, b_test, vol_true, is_call)

    iv_vec = implied_vol_vec(price, s, k, t, r_test, b_test, is_call)
    solved_mask = ~np.isnan(iv_vec)
    print(f"Vectorized solver: {solved_mask.sum()}/{n} converged ({solved_mask.mean():.1%})")

    # Cross-validate every converged row against the scalar reference
    # (already verified against py_vollib, findings.md) -- not just
    # internal consistency.
    max_iv_diff, max_greek_diff = 0.0, 0.0
    checked = 0
    for i in np.flatnonzero(solved_mask):
        scalar_iv = implied_vol(float(price[i]), float(s[i]), float(k[i]), float(t[i]),
                                 r_test, b_test, bool(is_call[i]))
        assert scalar_iv is not None, f"row {i}: vectorized converged but scalar reference did not"
        max_iv_diff = max(max_iv_diff, abs(scalar_iv - iv_vec[i]))

        scalar_g = bs_greeks(float(s[i]), float(k[i]), float(t[i]), r_test, b_test,
                              float(iv_vec[i]), bool(is_call[i]))
        vec_g = _bs_greeks_vec(np.array([s[i]]), np.array([k[i]]), np.array([t[i]]),
                                r_test, b_test, np.array([iv_vec[i]]), np.array([is_call[i]]))
        for name, scalar_v, vec_v in zip(["delta", "gamma", "theta", "vega", "rho"], scalar_g.values(), vec_g):
            max_greek_diff = max(max_greek_diff, abs(scalar_v - vec_v[0]))
        checked += 1

    print(f"Cross-validated {checked} converged rows against the scalar reference:")
    print(f"  max |iv_vectorized - iv_scalar| = {max_iv_diff:.2e}")
    print(f"  max |greek_vectorized - greek_scalar| (any of delta/gamma/theta/vega/rho) = {max_greek_diff:.2e}")
    assert max_iv_diff < 1e-4, "vectorized IV solver diverges from scalar reference"
    assert max_greek_diff < 1e-6, "vectorized greeks diverge from scalar reference"
    print("All cross-validation checks passed.")

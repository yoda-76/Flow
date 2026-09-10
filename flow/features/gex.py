"""
Gamma exposure (GEX) feature engine (D-20/D-21/08-market-abstraction.md).
Feed-agnostic -- operates on gamma/OI/spot/lot_size arrays or a DataFrame
carrying them, however they were computed (this project's own
features/greeks_batch.py today).

D-20 (dealer-positioning sign convention) is still formally OPEN, blocked
on spike S-05 -- NSE's retail-heavy option-selling market may invert the
US convention the standard formula assumes, and getting this wrong doesn't
just shift results, it inverts every signal built on top of it (D-20's own
text). Per the project's stated lean ("compute both, treat the choice as a
strategy parameter, and let backtests adjudicate"), this module always
computes BOTH conventions rather than picking one -- "standard" and
"inverted" are exact mirror images of each other (inverted = -standard),
tagged separately so a backtest can be run against either and compared.

Formula (per-contract): gamma * OI * lot_size * spot^2 * 0.01, signed
positive for calls / negative for puts under the "standard" convention
(the common "dealers long calls, short puts" framing widely cited for US
equity index GEX) -- "inverted" is its negation. This is a real, cited
convention choice, not an invented one, but which one (if either) actually
holds for NSE is exactly D-20's open question.

Gamma-flip point: the spot level implied by where cumulative GEX (summed
by strike, ascending) crosses zero, via linear interpolation between the
two bracketing strikes. This is the v1, current-spot-implied estimate
(uses gamma already computed at the real spot from features/greeks_batch.py),
not a full re-pricing of gamma across a hypothetical spot grid -- that
would be a real v2 refinement, not attempted here (CLAUDE.md: don't
over-abstract ahead of a second real case).
"""

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

FEATURE_VERSION = "gex_v1"


@dataclass(frozen=True)
class GEXConfig:
    top_n_walls: int = 5  # how many largest-|GEX| strikes to report as "walls"

    def as_dict(self) -> dict:
        return asdict(self)


def compute_gex_per_contract(gamma, oi, spot, lot_size, is_call):
    """Returns (gex_standard, gex_inverted) arrays -- exact mirror images."""
    gamma = np.asarray(gamma, dtype=float)
    oi = np.asarray(oi, dtype=float)
    is_call = np.asarray(is_call, dtype=bool)
    sign = np.where(is_call, 1.0, -1.0)
    gex_standard = sign * gamma * oi * lot_size * spot * spot * 0.01
    return gex_standard, -gex_standard


def find_gamma_flip(strikes_sorted: np.ndarray, cumulative_gex_sorted: np.ndarray):
    """strikes_sorted, cumulative_gex_sorted: ascending by strike. Returns
    the interpolated strike where cumulative GEX crosses zero, or None if
    there's no sign change across the whole range (nothing to interpolate,
    not "the flip is at the edge" -- don't guess)."""
    signs = np.sign(cumulative_gex_sorted)
    sign_changes = np.flatnonzero(np.diff(signs) != 0)
    if len(sign_changes) == 0:
        return None
    i = sign_changes[0]
    x0, x1 = strikes_sorted[i], strikes_sorted[i + 1]
    y0, y1 = cumulative_gex_sorted[i], cumulative_gex_sorted[i + 1]
    if y1 == y0:
        return None
    return x0 + (0 - y0) * (x1 - x0) / (y1 - y0)


def compute_gex_profile(df: pd.DataFrame, spot: float, lot_size: float) -> pd.DataFrame:
    """df must have columns: strike, gamma, open_interest, option_type
    ('CE'/'PE'), all for ONE timestamp/underlying/expiry snapshot. Returns
    a per-strike DataFrame with gex_standard, gex_inverted, and their
    cumulative sums (ascending by strike, the basis for the gamma-flip
    estimate)."""
    is_call = (df["option_type"] == "CE").to_numpy()
    gex_std, gex_inv = compute_gex_per_contract(df["gamma"].to_numpy(), df["open_interest"].to_numpy(),
                                                 spot, lot_size, is_call)
    per_row = df[["strike"]].copy()
    per_row["gex_standard"] = gex_std
    per_row["gex_inverted"] = gex_inv

    by_strike = per_row.groupby("strike", as_index=False).sum().sort_values("strike").reset_index(drop=True)
    by_strike["cum_gex_standard"] = by_strike["gex_standard"].cumsum()
    by_strike["cum_gex_inverted"] = by_strike["gex_inverted"].cumsum()
    return by_strike


def compute_gex_timeseries(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorized full-history version of compute_gex_per_contract, for
    building a per-bar GEX time series to backtest against (as opposed to
    build_gex_snapshot's single-timestamp deep-dive with walls/flip).

    df must have one row per (timestamp, instrument_id) with columns:
    timestamp, gamma, open_interest, option_type ('CE'/'PE'), s (spot at
    that timestamp), lot_size. No per-timestamp Python loop -- a row-wise
    vectorized calculation followed by one groupby-sum, so this scales to
    a full multi-year chain in seconds, not a slow per-bar apply.

    Returns one row per distinct timestamp: total_gex_standard,
    total_gex_inverted. Does NOT compute gamma-flip/walls per bar (that
    would need a per-timestamp strike-level groupby, the slow path) --
    call build_gex_snapshot on specific bars of interest for that."""
    gex_std, gex_inv = compute_gex_per_contract(
        df["gamma"].to_numpy(), df["open_interest"].to_numpy(),
        df["s"].to_numpy(), df["lot_size"].to_numpy(), (df["option_type"] == "CE").to_numpy(),
    )
    per_row = df[["timestamp"]].copy()
    per_row["gex_standard"] = gex_std
    per_row["gex_inverted"] = gex_inv
    return (per_row.groupby("timestamp", as_index=False)
            .sum()
            .rename(columns={"gex_standard": "total_gex_standard", "gex_inverted": "total_gex_inverted"})
            .sort_values("timestamp").reset_index(drop=True))


def build_gex_snapshot(df: pd.DataFrame, spot: float, lot_size: float, ts: str,
                        config: GEXConfig = None, extra: dict = None) -> dict:
    """The one function a caller actually needs: total GEX (both
    conventions), gamma-flip estimate (both conventions), and the top-N
    largest-|GEX| strikes ("walls"), bundled with feature_version + config
    for provenance (same convention as features/volume_profile.py's
    build_snapshot -- 08-market-abstraction.md's "feature version that
    records which config produced the series")."""
    config = config or GEXConfig()
    profile = compute_gex_profile(df, spot, lot_size)

    strikes = profile["strike"].to_numpy()
    flip_standard = find_gamma_flip(strikes, profile["cum_gex_standard"].to_numpy())
    flip_inverted = find_gamma_flip(strikes, profile["cum_gex_inverted"].to_numpy())

    walls_standard = (profile.reindex(profile["gex_standard"].abs().sort_values(ascending=False).index)
                       .head(config.top_n_walls)[["strike", "gex_standard"]]
                       .to_dict("records"))
    walls_inverted = (profile.reindex(profile["gex_inverted"].abs().sort_values(ascending=False).index)
                       .head(config.top_n_walls)[["strike", "gex_inverted"]]
                       .to_dict("records"))

    return {
        "ts": ts,
        "feature_version": FEATURE_VERSION,
        "config": config.as_dict(),
        "spot": spot, "lot_size": lot_size,
        "total_gex_standard": float(profile["gex_standard"].sum()),
        "total_gex_inverted": float(profile["gex_inverted"].sum()),
        "gamma_flip_standard": flip_standard,
        "gamma_flip_inverted": flip_inverted,
        "walls_standard": walls_standard,
        "walls_inverted": walls_inverted,
        "distinct_strikes": len(profile),
        **(extra or {}),
    }


if __name__ == "__main__":
    # Synthetic chain: 5 strikes, gamma/OI shaped so we know the answer.
    # Calls dominate above spot, puts dominate below -- constructed so the
    # standard-convention cumulative GEX crosses zero between strikes.
    spot = 25000.0
    lot_size = 75.0
    rows = []
    for strike, call_gamma, call_oi, put_gamma, put_oi in [
        (24800, 0.0003, 500, 0.0004, 4000),
        (24900, 0.0004, 800, 0.0005, 3000),
        (25000, 0.0005, 2000, 0.0005, 2000),   # ATM, symmetric
        (25100, 0.0004, 3000, 0.0004, 800),
        (25200, 0.0003, 4000, 0.0003, 500),
    ]:
        rows.append({"strike": float(strike), "gamma": call_gamma, "open_interest": call_oi, "option_type": "CE"})
        rows.append({"strike": float(strike), "gamma": put_gamma, "open_interest": put_oi, "option_type": "PE"})
    df = pd.DataFrame(rows)

    profile = compute_gex_profile(df, spot, lot_size)
    assert len(profile) == 5

    # Mirror-image check: inverted must be exactly -standard at every strike and in total.
    assert np.allclose(profile["gex_inverted"], -profile["gex_standard"])
    assert np.allclose(profile["cum_gex_inverted"], -profile["cum_gex_standard"])

    # Manual check of one strike's standard GEX: calls positive, puts negative.
    row_25000 = df[df["strike"] == 25000]
    call_row = row_25000[row_25000["option_type"] == "CE"].iloc[0]
    put_row = row_25000[row_25000["option_type"] == "PE"].iloc[0]
    expected_25000 = (call_row["gamma"] * call_row["open_interest"] * lot_size * spot * spot * 0.01
                       - put_row["gamma"] * put_row["open_interest"] * lot_size * spot * spot * 0.01)
    actual_25000 = profile.loc[profile["strike"] == 25000, "gex_standard"].iloc[0]
    assert abs(actual_25000 - expected_25000) < 1e-6, (actual_25000, expected_25000)

    # Gamma flip: a manufactured profile that's clearly negative then positive.
    test_strikes = np.array([100.0, 200.0, 300.0, 400.0])
    test_cum = np.array([-50.0, -10.0, 30.0, 80.0])  # crosses zero between 200 and 300
    flip = find_gamma_flip(test_strikes, test_cum)
    assert flip is not None and 200.0 < flip < 300.0, flip
    # Linear interpolation check: zero crossing at 200 + (0-(-10))*(300-200)/(30-(-10)) = 225
    assert abs(flip - 225.0) < 1e-9, flip

    # No sign change -- must return None, not guess.
    assert find_gamma_flip(np.array([1.0, 2.0, 3.0]), np.array([5.0, 8.0, 12.0])) is None

    snap = build_gex_snapshot(df, spot, lot_size, ts="2026-09-10T10:00:00")
    assert snap["feature_version"] == FEATURE_VERSION
    assert abs(snap["total_gex_standard"] + snap["total_gex_inverted"]) < 1e-6  # exact mirror in total too
    assert len(snap["walls_standard"]) == 5  # only 5 strikes exist, top_n_walls=5 default

    print("All self-tests passed.")
    print(f"  total_gex_standard={snap['total_gex_standard']:.2f}  total_gex_inverted={snap['total_gex_inverted']:.2f}")
    print(f"  gamma_flip_standard={snap['gamma_flip_standard']}  gamma_flip_inverted={snap['gamma_flip_inverted']}")

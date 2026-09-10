"""
Greeks feature engine (D-19, R7: "Calculate IV, Delta, Gamma, Theta, Vega
from historical option data"). Pure calculation, no data-source knowledge
-- callers supply s/k/t/r/b/vol or price, this module never touches
Breeze/Dhan/canonical data itself.

D-19 is still formally OPEN (BLOCKED by S-04 in docs/static/05-decision-register.md
-- the underlying-reference question, spot vs future, is unresolved), so
this module does NOT bake in an assumption. Per D-19's own text: "Black-76
on futures (b=0) and standard Black-Scholes on spot (b=r) are the same
function, just a parameter choice -- not two implementations to choose
between" (confirmed empirically earlier, docs/dynamic/findings.md D-19/D-21
section, cross-checked against py_vollib and NautilusTrader's
black_scholes_greeks). So instead of picking spot or future, every
function here takes the generalized cost-of-carry `b` directly as a
required argument -- the caller (or a future config-driven layer once S-04
closes) decides what b means for a given calculation, and every output
snapshot records exactly which s/k/t/r/b went in (D-19: "Every input
recorded per Greek version (R7)").

Per D-54's explicit guidance ("exercise style and settlement time as greek
parameters... two parameters now, no second implementation required"),
GreeksConfig carries exercise_style and settlement_time as real fields --
but only the European closed-form model is implemented; american raises
NotImplementedError rather than silently computing a wrong European value
for an American contract (NSE index options are European, so this costs
nothing today).

IV solver failure policy (D-19's open "null, flag, or interpolate"
question): this module always returns None on failure, never a guess --
matches the project's general epistemic caution (same spirit as R26's
"never fabricate a result for a missing day"). Interpolation, if ever
wanted, is a separate, explicitly-labelled step downstream, not hidden in
the solver.
"""

import math
from dataclasses import asdict, dataclass

FEATURE_VERSION = "greeks_v1"

_SQRT_2PI = math.sqrt(2 * math.pi)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


@dataclass(frozen=True)
class GreeksConfig:
    exercise_style: str = "european"   # D-54: NSE index options are European -- default costs nothing today
    settlement_time: str = "close"     # D-54: NSE index options are close-settled
    iv_max_iter: int = 100
    iv_tol: float = 1e-6
    iv_lower_bound: float = 1e-4       # vol search bounds for the bisection fallback
    iv_upper_bound: float = 5.0

    def __post_init__(self):
        if self.exercise_style not in ("european", "american"):
            raise ValueError(f"exercise_style must be 'european' or 'american', got {self.exercise_style!r}")
        if self.settlement_time not in ("close", "AM", "PM"):
            raise ValueError(f"settlement_time must be 'close', 'AM', or 'PM', got {self.settlement_time!r}")
        if self.iv_lower_bound <= 0 or self.iv_upper_bound <= self.iv_lower_bound:
            raise ValueError("iv_lower_bound must be positive and less than iv_upper_bound")

    def as_dict(self) -> dict:
        return asdict(self)


DEFAULT_CONFIG = GreeksConfig()


def _require_european(config: GreeksConfig) -> None:
    if config.exercise_style != "european":
        raise NotImplementedError(
            f"exercise_style={config.exercise_style!r} not yet supported -- only the European "
            "closed-form model exists so far (D-54: NSE index options are European, so this was "
            "never implemented; American needs a binomial/other model, a real second implementation)."
        )


def _d1_d2(s: float, k: float, t: float, r: float, b: float, vol: float) -> tuple:
    if s <= 0 or k <= 0 or t <= 0 or vol <= 0:
        raise ValueError(f"s, k, t, vol must all be positive: s={s} k={k} t={t} vol={vol}")
    d1 = (math.log(s / k) + (b + 0.5 * vol * vol) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    return d1, d2


def bs_price(s: float, k: float, t: float, r: float, b: float, vol: float, is_call: bool,
             config: GreeksConfig = DEFAULT_CONFIG) -> float:
    """Generalized Black-Scholes price with cost-of-carry b. b=r reduces to
    standard Black-Scholes on spot; b=0 reduces to Black-76 on futures."""
    _require_european(config)
    d1, d2 = _d1_d2(s, k, t, r, b, vol)
    carry = math.exp((b - r) * t)
    disc = math.exp(-r * t)
    if is_call:
        return s * carry * _norm_cdf(d1) - k * disc * _norm_cdf(d2)
    return k * disc * _norm_cdf(-d2) - s * carry * _norm_cdf(-d1)


def bs_greeks(s: float, k: float, t: float, r: float, b: float, vol: float, is_call: bool,
              config: GreeksConfig = DEFAULT_CONFIG) -> dict:
    """Delta, gamma, theta, vega, rho -- raw per-unit conventions (not
    rescaled per-1%-vol or per-day; a documented past mistake in this
    project was applying spurious extra scaling on top of an
    already-correct library's own convention, findings.md D-19 section).
    Caller rescales for display if wanted, not baked in here."""
    _require_european(config)
    d1, d2 = _d1_d2(s, k, t, r, b, vol)
    carry = math.exp((b - r) * t)
    disc = math.exp(-r * t)
    pdf_d1 = _norm_pdf(d1)

    gamma = carry * pdf_d1 / (s * vol * math.sqrt(t))
    vega = s * carry * pdf_d1 * math.sqrt(t)

    if is_call:
        delta = carry * _norm_cdf(d1)
        theta = (-s * carry * pdf_d1 * vol / (2 * math.sqrt(t))
                 - (b - r) * s * carry * _norm_cdf(d1) - r * k * disc * _norm_cdf(d2))
        rho = k * t * disc * _norm_cdf(d2)
    else:
        delta = carry * (_norm_cdf(d1) - 1)
        theta = (-s * carry * pdf_d1 * vol / (2 * math.sqrt(t))
                 + (b - r) * s * carry * _norm_cdf(-d1) + r * k * disc * _norm_cdf(-d2))
        rho = -k * t * disc * _norm_cdf(-d2)

    return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega, "rho": rho}


def _no_arbitrage_floor(s: float, k: float, t: float, r: float, b: float, is_call: bool) -> float:
    carry = math.exp((b - r) * t)
    disc = math.exp(-r * t)
    if is_call:
        return max(0.0, s * carry - k * disc)
    return max(0.0, k * disc - s * carry)


def implied_vol(price: float, s: float, k: float, t: float, r: float, b: float, is_call: bool,
                 config: GreeksConfig = DEFAULT_CONFIG):
    """Newton-Raphson on vega, falling back to bisection if Newton fails to
    converge or vega is too small (deep ITM/OTM, near expiry -- exactly
    D-19's flagged IV-solver-failure cases). Returns None on any failure --
    never a guess (see module docstring)."""
    _require_european(config)
    if s <= 0 or k <= 0 or t <= 0:
        return None

    floor = _no_arbitrage_floor(s, k, t, r, b, is_call)
    if price < floor - config.iv_tol:
        return None  # price violates no-arbitrage bound -- no valid vol exists

    vol = 0.3
    for _ in range(config.iv_max_iter):
        try:
            model_price = bs_price(s, k, t, r, b, vol, is_call, config)
            vega = bs_greeks(s, k, t, r, b, vol, is_call, config)["vega"]
        except ValueError:
            break
        diff = model_price - price
        if abs(diff) < config.iv_tol:
            return vol
        if vega < 1e-8:
            break  # Newton step would be unstable -- fall through to bisection
        vol -= diff / vega
        if vol <= 0:
            break

    # Bisection fallback within the configured bounds.
    lo, hi = config.iv_lower_bound, config.iv_upper_bound
    try:
        f_lo = bs_price(s, k, t, r, b, lo, is_call, config) - price
        f_hi = bs_price(s, k, t, r, b, hi, is_call, config) - price
    except ValueError:
        return None
    if f_lo * f_hi > 0:
        return None  # no sign change in range -- solver can't bracket a root

    for _ in range(config.iv_max_iter):
        mid = (lo + hi) / 2
        f_mid = bs_price(s, k, t, r, b, mid, is_call, config) - price
        if abs(f_mid) < config.iv_tol:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return None  # did not converge within iv_max_iter


def build_greeks_record(s: float, k: float, t: float, r: float, b: float, is_call: bool,
                         price: float, config: GreeksConfig = DEFAULT_CONFIG, ts: str = None,
                         extra: dict = None) -> dict:
    """Solves IV from price, then computes greeks at that IV. Bundles
    feature_version + config + every input (D-19: "every input recorded
    per Greek version") -- never just the outputs. iv=None means the
    solver failed (see implied_vol's docstring) -- greeks are also None in
    that case, not computed from a guessed vol."""
    vol = implied_vol(price, s, k, t, r, b, is_call, config)
    greeks = bs_greeks(s, k, t, r, b, vol, is_call, config) if vol is not None else None
    return {
        "ts": ts,
        "feature_version": FEATURE_VERSION,
        "config": config.as_dict(),
        "inputs": {"s": s, "k": k, "t": t, "r": r, "b": b, "is_call": is_call, "price": price},
        "iv": vol,
        "greeks": greeks,
        **(extra or {}),
    }


if __name__ == "__main__":
    # s=25000, k=25000 (ATM), t=30/365, r=0.065, vol=0.13 -- realistic-shaped NIFTY inputs.
    s, k, t, r, vol = 25000.0, 25000.0, 30 / 365, 0.065, 0.13

    # b=r (spot-based Black-Scholes) and b=0 (Black-76 on futures) both
    # exercised -- D-19's "same function, different parameter" claim.
    for b, label in [(r, "spot (b=r)"), (0.0, "future (b=0)")]:
        call_price = bs_price(s, k, t, r, b, vol, is_call=True)
        put_price = bs_price(s, k, t, r, b, vol, is_call=False)

        # Put-call parity, exact and dependency-free: C - P = S*e^((b-r)t) - K*e^(-rt).
        parity_lhs = call_price - put_price
        parity_rhs = s * math.exp((b - r) * t) - k * math.exp(-r * t)
        assert abs(parity_lhs - parity_rhs) < 1e-8, (label, parity_lhs, parity_rhs)

        call_greeks = bs_greeks(s, k, t, r, b, vol, is_call=True)
        put_greeks = bs_greeks(s, k, t, r, b, vol, is_call=False)
        # Put-call parity for delta: delta_call - delta_put = e^((b-r)t).
        assert abs((call_greeks["delta"] - put_greeks["delta"]) - math.exp((b - r) * t)) < 1e-8, label
        # Gamma and vega are identical for calls and puts at the same strike.
        assert abs(call_greeks["gamma"] - put_greeks["gamma"]) < 1e-10, label
        assert abs(call_greeks["vega"] - put_greeks["vega"]) < 1e-10, label

        # Round-trip: price -> implied_vol should recover the vol we started with.
        recovered = implied_vol(call_price, s, k, t, r, b, is_call=True)
        assert recovered is not None and abs(recovered - vol) < 1e-5, (label, recovered)

        print(f"{label}: call={call_price:.4f} put={put_price:.4f} "
              f"delta={call_greeks['delta']:.4f} gamma={call_greeks['gamma']:.6f} "
              f"vega={call_greeks['vega']:.4f} theta={call_greeks['theta']:.4f} "
              f"recovered_iv={recovered:.6f}")

    # A price below the no-arbitrage floor must return None, not a guess.
    deep_itm_call_floor = _no_arbitrage_floor(s=25000, k=15000, t=t, r=r, b=r, is_call=True)
    assert implied_vol(deep_itm_call_floor - 1.0, s=25000, k=15000, t=t, r=r, b=r, is_call=True) is None

    # American exercise style must raise, not silently compute European values.
    try:
        bs_price(s, k, t, r, r, vol, is_call=True, config=GreeksConfig(exercise_style="american"))
        raise AssertionError("expected NotImplementedError for american exercise_style")
    except NotImplementedError:
        pass

    rec = build_greeks_record(s, k, t, r, r, is_call=True, price=bs_price(s, k, t, r, r, vol, True))
    assert rec["feature_version"] == FEATURE_VERSION
    assert rec["iv"] is not None and abs(rec["iv"] - vol) < 1e-5

    print("All self-tests passed.")

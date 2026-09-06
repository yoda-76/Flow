"""
D-19/D-21 follow-up: derive the exact implied forward Dhan is pricing off,
directly from their own call+put quotes via put-call parity, rather than
guessing or fetching an external futures price. NIFTY futures are only
monthly, so for weekly option expiries there's no matching-tenor futures
contract to compare against anyway -- put-call parity is the *only* rigorous
way to get a tenor-matched forward for a weekly expiry.

Put-call parity (European): C - P = D * (F - K), where D = exp(-r*T) is the
discount factor. So F = (C - P) / D + K = (C - P) * exp(r*T) + K.
This is convention-agnostic -- it doesn't matter what rate/dividend/spot
Dhan actually used internally, this equation recovers the forward implied
by their own quoted prices directly.

Then: recompute greeks using that derived forward with b=0 (Black-76 form,
per the black_scholes_greeks(s, r, b, vol, is_call, k, t) signature found
in the D-28 spike -- b=0 means s is treated as already the forward/
cost-of-carry-free price) across several strikes, both calls and puts, and
compare against Dhan's real greeks.

Weekend note: market is closed (Saturday), so Dhan will likely serve
Friday's frozen closing snapshot. This script also checks whether repeated
calls return identical data (confirms whether it's genuinely frozen) as
part of the record, and separately re-derives the forward from a real
MONTHLY expiry, where an actual NIFTY futures contract with matching tenor
exists -- giving a second, independent way to sanity check the derived
forward against a real traded price.

This is scratch, not a deliverable (see ../CLAUDE.md). Needs
experiments/.env with DHAN_CLIENT_ID/DHAN_ACCESS_TOKEN.
"""

import json
import math
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from nautilus_trader.model.greeks import black_scholes_greeks, imply_vol_and_greeks

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

DHAN_BASE = "https://api.dhan.co/v2"
NIFTY_INDEX_SECURITY_ID = 13
NIFTY_FUT_SECURITY_ID = "68407"  # confirmed shared Breeze/Dhan token, Sep-2026 future -- see findings.md D-05
RISK_FREE_RATE = 0.065


def dhan_headers():
    client_id, token = os.getenv("DHAN_CLIENT_ID"), os.getenv("DHAN_ACCESS_TOKEN")
    if not all([client_id, token]):
        print("FATAL: Dhan credentials missing from experiments/.env")
        sys.exit(1)
    return {"access-token": token, "dhanClientId": client_id, "client-id": client_id, "Content-Type": "application/json"}


def get_expiries(headers):
    resp = requests.post(f"{DHAN_BASE}/optionchain/expirylist", headers=headers,
                          json={"UnderlyingScrip": NIFTY_INDEX_SECURITY_ID, "UnderlyingSeg": "IDX_I"}, timeout=15)
    resp.raise_for_status()
    return resp.json()["data"]


def get_option_chain(headers, expiry):
    resp = requests.post(f"{DHAN_BASE}/optionchain", headers=headers,
                          json={"UnderlyingScrip": NIFTY_INDEX_SECURITY_ID, "UnderlyingSeg": "IDX_I", "Expiry": expiry},
                          timeout=20)
    if resp.status_code != 200:
        print(f"FATAL: optionchain call failed: {resp.status_code} {resp.text[:300]}")
        sys.exit(1)
    return resp.json()["data"]


def get_nifty_futures_price(headers, expiry_hint):
    """Real traded futures price, for cross-checking against a monthly expiry's implied forward."""
    resp = requests.post(
        f"{DHAN_BASE}/optionchain/expirylist", headers=headers,
        json={"UnderlyingScrip": NIFTY_INDEX_SECURITY_ID, "UnderlyingSeg": "IDX_I"}, timeout=15,
    )
    # Use the intraday quote endpoint for the future itself
    resp = requests.post(
        f"{DHAN_BASE}/marketfeed/ltp", headers=headers,
        json={"NSE_FNO": [int(NIFTY_FUT_SECURITY_ID)]}, timeout=15,
    )
    if resp.status_code != 200:
        return None, resp.text
    return resp.json(), None


def precise_years_to_expiry(expiry_str):
    import datetime
    now = datetime.datetime.now()
    expiry_close = datetime.datetime.combine(datetime.date.fromisoformat(expiry_str), datetime.time(15, 30))
    return max((expiry_close - now).total_seconds(), 60) / (365.0 * 24 * 3600)


def analyze_expiry(headers, expiry, label, n_strikes=5):
    print(f"\n{'='*70}\n{label}: expiry {expiry}\n{'='*70}")
    chain = get_option_chain(headers, expiry)
    spot = chain["last_price"]
    t = precise_years_to_expiry(expiry)
    print(f"spot={spot}  T={t:.6f} yrs ({t*365:.2f} days)")

    strikes_available = sorted(chain["oc"].keys(), key=lambda s: abs(float(s) - spot))[:n_strikes]
    rows = []
    implied_forwards = []
    for k_str in strikes_available:
        k = float(k_str)
        ce = chain["oc"][k_str]["ce"]
        pe = chain["oc"][k_str]["pe"]
        c_price, p_price = ce["last_price"], pe["last_price"]
        if c_price <= 0 or p_price <= 0:
            continue
        # Put-call parity: F = (C - P) * exp(rT) + K
        implied_f = (c_price - p_price) * math.exp(RISK_FREE_RATE * t) + k
        implied_forwards.append(implied_f)
        rows.append({
            "strike": k, "call_price": c_price, "put_price": p_price,
            "dhan_call_delta": ce["greeks"]["delta"], "dhan_put_delta": pe["greeks"]["delta"],
            "dhan_call_iv": ce["implied_volatility"], "dhan_put_iv": pe["implied_volatility"],
            "implied_forward": implied_f,
        })

    if not implied_forwards:
        print("No valid strikes with both call and put priced -- skipping.")
        return None

    avg_forward = sum(implied_forwards) / len(implied_forwards)
    basis_pts = avg_forward - spot
    basis_pct = basis_pts / spot * 100
    print(f"\nImplied forward per strike: {[round(f, 1) for f in implied_forwards]}")
    print(f"Average implied forward: {avg_forward:.2f}  (spot={spot}, basis={basis_pts:+.2f} pts, {basis_pct:+.3f}%)")
    annualized_carry = basis_pct / 100 / t if t > 0 else float("nan")
    print(f"Implied annualized cost-of-carry: {annualized_carry*100:.2f}%")

    print(f"\n{'Strike':>8} | {'Dhan Cdelta':>11} | {'Spot Cdelta':>11} | {'Fwd Cdelta':>10} | "
          f"{'Dhan Pdelta':>11} | {'Spot Pdelta':>11} | {'Fwd Pdelta':>10}")
    for row in rows:
        k = row["strike"]
        # spot-based (b=r, first-pass convention)
        spot_call = black_scholes_greeks(spot, RISK_FREE_RATE, RISK_FREE_RATE, row["dhan_call_iv"] / 100, True, k, t)
        spot_put = black_scholes_greeks(spot, RISK_FREE_RATE, RISK_FREE_RATE, row["dhan_put_iv"] / 100, False, k, t)
        # forward-based (Black-76: b=0, s=derived forward)
        fwd_call = black_scholes_greeks(avg_forward, RISK_FREE_RATE, 0.0, row["dhan_call_iv"] / 100, True, k, t)
        fwd_put = black_scholes_greeks(avg_forward, RISK_FREE_RATE, 0.0, row["dhan_put_iv"] / 100, False, k, t)
        print(f"{k:>8.0f} | {row['dhan_call_delta']:>11.4f} | {spot_call.delta:>11.4f} | {fwd_call.delta:>10.4f} | "
              f"{row['dhan_put_delta']:>11.4f} | {spot_put.delta:>11.4f} | {fwd_put.delta:>10.4f}")

    return {
        "expiry": expiry, "spot": spot, "t_years": t, "avg_implied_forward": avg_forward,
        "basis_pts": basis_pts, "basis_pct": basis_pct, "annualized_carry": annualized_carry,
        "rows": rows,
    }


def main():
    headers = dhan_headers()
    expiries = get_expiries(headers)
    print(f"Available expiries: {expiries}")

    results = {}
    results["weekly"] = analyze_expiry(headers, expiries[0], "Nearest weekly")
    # Find a genuinely monthly-tenor expiry (last one before a big calendar gap, or just pick the 4th)
    monthly_candidate = expiries[min(4, len(expiries) - 1)]
    results["monthly"] = analyze_expiry(headers, monthly_candidate, "Further-out (monthly-like)")

    print(f"\n{'='*70}\nCross-check: real traded NIFTY futures price (Sep-2026 future)\n{'='*70}")
    fut_data, err = get_nifty_futures_price(headers, monthly_candidate)
    if err:
        print(f"Futures LTP fetch failed: {err}")
    else:
        print(json.dumps(fut_data, indent=2)[:1000])
    results["futures_ltp_raw"] = fut_data

    out_path = HERE / "results" / "d19_forward_derivation.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\nSaved to {out_path}")

    print(f"\n{'='*70}\nStale-data check: re-querying weekly chain after a short pause\n{'='*70}")
    time.sleep(20)
    chain2 = get_option_chain(headers, expiries[0])
    same_price = chain2["last_price"] == results["weekly"]["spot"]
    print(f"Spot unchanged after 20s: {same_price} ({chain2['last_price']} vs {results['weekly']['spot']})")
    k0 = results["weekly"]["rows"][0]["strike"]
    ce2 = chain2["oc"][f"{k0:.6f}"]["ce"] if f"{k0:.6f}" in chain2["oc"] else None
    if ce2:
        print(f"ATM call greeks unchanged: delta {ce2['greeks']['delta']} vs {results['weekly']['rows'][0]['dhan_call_delta']}")


if __name__ == "__main__":
    main()

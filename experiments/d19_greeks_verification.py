"""
D-19 verification: does Dhan's live option chain actually give greeks, and
do they match what we compute ourselves (Nautilus's black_scholes_greeks /
imply_vol_and_greeks)?

This only validates the LIVE case (Dhan has no historical greeks for
expired contracts -- confirmed in the D-52 experiment, its rolling-option
endpoint's `iv` field came back empty). For historical data we're on our
own regardless; this test at least confirms the formula/pipeline is
correct against a real, independently-computed reference for one live
snapshot -- if the pipeline is right, it stays right for historical data,
since Black-Scholes is a fixed formula, not something that changes over
time. What actually varies historically (and remains open, D-19/D-21) is
which inputs to feed it -- risk-free rate source, underlying reference
(spot vs futures). This test uses spot + b=r (plain equity-index BS,
ignoring dividends) as a first pass, not a final convention choice.

This is scratch, not a deliverable (see ../CLAUDE.md). Needs
experiments/.env with DHAN_CLIENT_ID/DHAN_ACCESS_TOKEN.
"""

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from nautilus_trader.model.greeks import black_scholes_greeks, imply_vol_and_greeks

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

DHAN_BASE = "https://api.dhan.co/v2"
NIFTY_INDEX_SECURITY_ID = 13
RISK_FREE_RATE = 0.065  # rough RBI repo-rate proxy -- D-19's "rate source" is still open, this is a first pass


def dhan_headers():
    client_id, token = os.getenv("DHAN_CLIENT_ID"), os.getenv("DHAN_ACCESS_TOKEN")
    if not all([client_id, token]):
        print("FATAL: Dhan credentials missing from experiments/.env")
        sys.exit(1)
    return {"access-token": token, "dhanClientId": client_id, "client-id": client_id, "Content-Type": "application/json"}


def get_nearest_expiry(headers):
    resp = requests.post(f"{DHAN_BASE}/optionchain/expirylist", headers=headers,
                          json={"UnderlyingScrip": NIFTY_INDEX_SECURITY_ID, "UnderlyingSeg": "IDX_I"}, timeout=15)
    resp.raise_for_status()
    return resp.json()["data"][0]


def get_option_chain(headers, expiry):
    resp = requests.post(f"{DHAN_BASE}/optionchain", headers=headers,
                          json={"UnderlyingScrip": NIFTY_INDEX_SECURITY_ID, "UnderlyingSeg": "IDX_I", "Expiry": expiry},
                          timeout=20)
    if resp.status_code != 200:
        print(f"FATAL: optionchain call failed: {resp.status_code} {resp.text[:300]}")
        sys.exit(1)
    return resp.json()


def run_for_expiry(headers, expiry, label):
    print(f"\n{'='*60}\nUsing NIFTY expiry: {expiry} ({label})\n{'='*60}")

    chain = get_option_chain(headers, expiry)
    data = chain["data"]
    spot = data["last_price"]
    print(f"Underlying spot: {spot}")

    # pick the strike closest to ATM
    strikes = data["oc"]
    atm_strike = min(strikes.keys(), key=lambda s: abs(float(s) - spot))
    contract = strikes[atm_strike]["ce"]
    strike = float(atm_strike)

    import datetime
    # Precise T: from now to 15:30 IST on expiry day, not a crude integer
    # day count -- this matters enormously for a near-dated option (vega/
    # theta especially), confirmed by the first pass on a 2-day contract.
    now = datetime.datetime.now()
    expiry_close = datetime.datetime.combine(datetime.date.fromisoformat(expiry), datetime.time(15, 30))
    t = max((expiry_close - now).total_seconds(), 60) / (365.0 * 24 * 3600)
    days_to_expiry = (expiry_close - now).total_seconds() / 86400

    print(f"\nATM strike: {strike}, precise time to expiry: {days_to_expiry:.3f} days (T={t:.6f} years)")
    print(f"Dhan's data for this contract: last_price={contract['last_price']}, "
          f"iv={contract['implied_volatility']}, oi={contract['oi']}")
    dhan_greeks = contract["greeks"]
    print(f"Dhan's greeks: delta={dhan_greeks['delta']} gamma={dhan_greeks['gamma']} "
          f"theta={dhan_greeks['theta']} vega={dhan_greeks['vega']}")

    # Our own pipeline: imply vol from Dhan's traded price, then compute greeks from that vol.
    market_price = contract["last_price"]
    b = RISK_FREE_RATE  # spot-based BS, no dividend adjustment -- first pass
    our_greeks_from_price = imply_vol_and_greeks(spot, RISK_FREE_RATE, b, True, strike, t, market_price)
    our_vol = our_greeks_from_price.vol
    print(f"\nOur implied vol from Dhan's own last_price: {our_vol*100:.2f}% (Dhan's IV: {contract['implied_volatility']:.2f}%)")

    # Also compute greeks directly using DHAN's OWN IV, to isolate: is our
    # BS formula correct, independent of any IV-solving discrepancy?
    dhan_iv_as_decimal = contract["implied_volatility"] / 100 if contract["implied_volatility"] > 1 else contract["implied_volatility"]
    our_greeks_from_dhan_iv = black_scholes_greeks(spot, RISK_FREE_RATE, b, dhan_iv_as_decimal, True, strike, t)

    print("\n=== Comparison ===")
    print(f"{'Greek':>8} | {'Dhan':>12} | {'Ours (our IV)':>14} | {'Ours (Dhan IV)':>15}")
    our_g1 = our_greeks_from_price
    our_g2 = our_greeks_from_dhan_iv
    for name, dhan_val, g1_attr, g2_attr in [
        ("delta", dhan_greeks["delta"], "delta", "delta"),
        ("gamma", dhan_greeks["gamma"], "gamma", "gamma"),
        ("theta", dhan_greeks["theta"], "theta", "theta"),
        ("vega", dhan_greeks["vega"], "vega", "vega"),
    ]:
        v1 = getattr(our_g1, g1_attr)
        v2 = getattr(our_g2, g2_attr)
        print(f"{name:>8} | {dhan_val:>12.4f} | {v1:>14.4f} | {v2:>15.4f}")

    result = {
        "expiry": expiry, "spot": spot, "strike": strike, "days_to_expiry": days_to_expiry,
        "market_price": market_price, "dhan_iv": contract["implied_volatility"],
        "dhan_greeks": dhan_greeks, "our_implied_vol": our_vol,
        "our_greeks_from_our_iv": {"delta": our_g1.delta, "gamma": our_g1.gamma, "theta": our_g1.theta, "vega": our_g1.vega},
        "our_greeks_from_dhan_iv": {"delta": our_g2.delta, "gamma": our_g2.gamma, "theta": our_g2.theta, "vega": our_g2.vega},
    }
    out_path = HERE / "results" / f"d19_greeks_verification_{expiry}.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))
    print(f"\nSaved to {out_path}")
    return result


def main():
    headers = dhan_headers()
    resp = requests.post(f"{DHAN_BASE}/optionchain/expirylist", headers=headers,
                          json={"UnderlyingScrip": NIFTY_INDEX_SECURITY_ID, "UnderlyingSeg": "IDX_I"}, timeout=15)
    expiries = resp.json()["data"]
    print(f"Available expiries: {expiries}")

    # Nearest (very short-dated, T-precision-sensitive) and a longer-dated
    # one (monthly-ish, less T-sensitive) -- comparing both isolates
    # whether the formula itself is right vs. just a near-expiry T-precision
    # artifact.
    run_for_expiry(headers, expiries[0], "nearest weekly")
    monthly_like = expiries[min(4, len(expiries) - 1)]
    run_for_expiry(headers, monthly_like, "further out, less T-sensitive")


if __name__ == "__main__":
    main()

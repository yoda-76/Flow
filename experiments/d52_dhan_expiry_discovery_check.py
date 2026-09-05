"""
D-52 sourcing question — can Dhan's rolling-option API be used to derive a
historical expiry calendar, without needing to already know expiry dates?

Context (docs/dynamic/findings.md): SecurityMaster is confirmed current-
listings-only, can't seed history. Dhan's docs for two candidate endpoints:

  - POST /v2/optionchain/expirylist — "all expiries for which Options
    Instruments are ACTIVE" — explicitly current-only per its own docs.
  - POST /v2/charts/rollingoption — takes expiryFlag (WEEK/MONTH) +
    expiryCode (0=near/1=next/2=far) + strike=ATM±N instead of an absolute
    expiry_date/strike, up to 5 years back, 30 days/call. Its own docs say
    "expiry discovery: must reference instrument list separately — API does
    not provide expiry listing", which suggests it won't just hand us dated
    expiries either — but that's a doc claim, not yet tested. This script
    tests it directly: pull a real historical window and see whether the
    response reveals rollover boundaries (e.g. a discontinuity in the
    'strike' field as ATM resets to a new expiry) or an explicit expiry
    field the docs summary didn't mention.

BLOCKED until the Dhan Data API subscription is active (see findings.md —
DH-902 Invalid_Access). This script is written now so it's ready to run
the moment that unblocks.

This script is scratch, not a deliverable (see ../CLAUDE.md). Output is a
JSON report under results/; read it back and add a [LIVE] entry to
docs/dynamic/findings.md by hand.

Needs experiments/.env with DHAN_CLIENT_ID/DHAN_ACCESS_TOKEN — see
.examples.env.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

RESULTS_DIR = HERE / "results"
RESULTS_DIR.mkdir(exist_ok=True)

DHAN_BASE = "https://api.dhan.co/v2"
NIFTY_INDEX_SECURITY_ID = "13"   # confirmed via search: NIFTY-INDEX [NSE I] securityId=13


def dhan_headers() -> dict:
    client_id, token = os.getenv("DHAN_CLIENT_ID"), os.getenv("DHAN_ACCESS_TOKEN")
    if not all([client_id, token]):
        print("FATAL: Dhan credentials missing from experiments/.env (DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN).")
        sys.exit(1)
    # Send both spellings — Dhan's own docs are inconsistent about the header
    # name across endpoints (/profile etc. want dhanClientId; /optionchain/
    # expirylist's own doc page says client-id). Confirmed live 2026-09-06.
    return {
        "access-token": token,
        "dhanClientId": client_id,
        "client-id": client_id,
        "Content-Type": "application/json",
    }


def check_auth(headers: dict):
    resp = requests.get(f"{DHAN_BASE}/profile", headers=headers, timeout=15)
    if resp.status_code != 200:
        print(f"FATAL: Dhan auth check failed — status={resp.status_code} body={resp.text[:300]}")
        sys.exit(1)
    print("Dhan authenticated OK.")


def check_expirylist_is_current_only(headers: dict) -> dict:
    body = {"UnderlyingScrip": int(NIFTY_INDEX_SECURITY_ID), "UnderlyingSeg": "IDX_I"}
    resp = requests.post(f"{DHAN_BASE}/optionchain/expirylist", headers=headers, json=body, timeout=15)
    print(f"expirylist: status={resp.status_code}")
    if resp.status_code != 200:
        print(f"  body={resp.text[:500]}")
        return {"status": resp.status_code, "error": resp.text}
    data = resp.json()
    print(f"  expiries returned: {data.get('data')}")
    return {"status": resp.status_code, "data": data}


def check_rolling_option_history(headers: dict, from_date: str, to_date: str) -> dict:
    body = {
        "securityId": NIFTY_INDEX_SECURITY_ID,
        "exchangeSegment": "NSE_FNO",
        "instrument": "OPTIDX",
        "expiryFlag": "WEEK",
        # expiryCode=0 ("near expiry") is broken server-side — Dhan's own
        # validation treats 0 as "not provided" and rejects with DH-905
        # (confirmed live 2026-09-06, both int and string "0" fail the same
        # way). expiryCode=1 is the workaround that actually reaches the
        # real subscription/data gate; re-test 0 once subscribed in case
        # this was coincidentally tied to the subscription check itself.
        "expiryCode": 1,
        "strike": "ATM",
        "drvOptionType": "CALL",
        "interval": "60",
        "requiredData": ["open", "high", "low", "close", "strike", "spot", "oi"],
        "fromDate": from_date,
        "toDate": to_date,
    }
    resp = requests.post(f"{DHAN_BASE}/charts/rollingoption", headers=headers, json=body, timeout=30)
    print(f"rollingoption ({from_date} to {to_date}): status={resp.status_code}")
    if resp.status_code != 200:
        print(f"  body={resp.text[:1000]}")
        return {"status": resp.status_code, "error": resp.text, "request_body": body}
    data = resp.json()

    # Inspect for rollover: does 'strike' (ATM) show discontinuities over
    # time, and is there any expiry-like field the docs summary didn't
    # mention?
    ce = data.get("ce") or {}
    keys_seen = sorted(ce.keys()) if isinstance(ce, dict) else "ce is not a dict — see raw"
    strikes = ce.get("strike") if isinstance(ce, dict) else None
    timestamps = ce.get("timestamp") if isinstance(ce, dict) else None
    print(f"  response top-level keys: {sorted(data.keys())}")
    print(f"  ce sub-keys: {keys_seen}")
    if strikes and timestamps:
        distinct_strikes_in_order = []
        for s in strikes:
            if not distinct_strikes_in_order or distinct_strikes_in_order[-1] != s:
                distinct_strikes_in_order.append(s)
        print(f"  distinct ATM strike values in sequence (rollover shows as a jump): {distinct_strikes_in_order[:20]}")

    return {"status": resp.status_code, "request_body": body, "data": data}


def main():
    headers = dhan_headers()
    check_auth(headers)

    expirylist_result = check_expirylist_is_current_only(headers)
    # A ~24-day window inside the 2024-01-25 expiry period already confirmed
    # to have real data via Breeze (findings.md) — 30-day/call limit applies.
    rolling_result = check_rolling_option_history(headers, "2024-01-02", "2024-01-26")

    report = {"expirylist": expirylist_result, "rolling_option": rolling_result}
    report_path = RESULTS_DIR / f"d52_dhan_expiry_discovery_{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nFull report written to {report_path}")
    print("Next: read this back and add a [LIVE] entry to docs/dynamic/findings.md.")


if __name__ == "__main__":
    main()

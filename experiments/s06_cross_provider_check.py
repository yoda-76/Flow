"""
S-06 cross-provider check — do Breeze and Dhan agree on the same instrument,
same day? Historical-only by design: the market is closed when this is
written, so nothing here touches Dhan's live feed (that's a separate,
market-hours-only experiment for S-03).

Answers, with real evidence:
  - Does Dhan's REST auth actually work the way its docs describe (direct
    access-token, not the MCP shortcut)?
  - On an overlapping day, do Breeze and Dhan's 1-minute NIFTY futures bars
    agree? (docs/static/06-spikes.md S-06's explicit question)
  - Does Dhan's OI figure agree with Breeze's for the same bar?

Uses the same NIFTY future (expiry 2026-09-29, NSE token/securityId 68407)
confirmed identical between Breeze's SecurityMaster and Dhan's search
results — see docs/dynamic/findings.md.

This script is scratch, not a deliverable (see ../CLAUDE.md). Output is a
JSON report under results/; read it back and add [LIVE] entries to
docs/dynamic/findings.md by hand.

Needs experiments/.env with API_KEY/API_SECRET/API_SESSION (Breeze) and
DHAN_CLIENT_ID/DHAN_ACCESS_TOKEN (Dhan) — see .examples.env.
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv
from breeze_connect import BreezeConnect

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

RESULTS_DIR = HERE / "results"
RESULTS_DIR.mkdir(exist_ok=True)

DHAN_BASE = "https://api.dhan.co/v2"
NIFTY_FUT_SECURITY_ID = "68407"   # NIFTY Sep-2026 future — same token in both providers' masters
NIFTY_FUT_EXPIRY_BREEZE = datetime(2026, 9, 29)
CHECK_DAY = datetime(2026, 8, 28)   # last clean trading day confirmed in the S-01 run
WINDOW_START = CHECK_DAY.replace(hour=9, minute=30)
WINDOW_END = CHECK_DAY.replace(hour=9, minute=40)


def fmt_breeze(dt: datetime) -> str:
    # See s01_breeze_coverage_check.py's fmt() docstring: Breeze reads this
    # as literal IST wall-clock time despite the trailing Z. Never convert.
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def authenticate_breeze() -> BreezeConnect:
    api_key, api_secret, api_session = os.getenv("API_KEY"), os.getenv("API_SECRET"), os.getenv("API_SESSION")
    if not all([api_key, api_secret, api_session]):
        print("FATAL: Breeze credentials missing from experiments/.env")
        sys.exit(1)
    breeze = BreezeConnect(api_key=api_key)
    try:
        breeze.generate_session(api_secret=api_secret, session_token=api_session)
    except Exception as e:
        print(f"FATAL: Breeze session generation failed — token likely expired (D-49). {e}")
        sys.exit(1)
    print("Breeze authenticated OK.")
    return breeze


def dhan_headers() -> dict:
    client_id, token = os.getenv("DHAN_CLIENT_ID"), os.getenv("DHAN_ACCESS_TOKEN")
    if not all([client_id, token]):
        print("FATAL: Dhan credentials missing from experiments/.env (DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN).")
        print("Generate at web.dhan.co -> My Profile -> Access DhanHQ APIs (24h validity).")
        sys.exit(1)
    return {"access-token": token, "dhanClientId": client_id, "Content-Type": "application/json"}


def check_dhan_auth(headers: dict) -> dict:
    resp = requests.get(f"{DHAN_BASE}/profile", headers=headers, timeout=15)
    ok = resp.status_code == 200
    if not ok:
        print(f"FATAL: Dhan auth check failed — status={resp.status_code} body={resp.text[:300]}")
        print("Token is valid 24h from generation; regenerate at web.dhan.co if expired.")
        sys.exit(1)
    print("Dhan authenticated OK.")
    return resp.json()


def fetch_breeze_futures(breeze: BreezeConnect) -> list:
    resp = breeze.get_historical_data_v2(
        interval="1minute",
        from_date=fmt_breeze(WINDOW_START), to_date=fmt_breeze(WINDOW_END),
        stock_code="NIFTY", exchange_code="NFO", product_type="futures",
        expiry_date=fmt_breeze(NIFTY_FUT_EXPIRY_BREEZE), right="others", strike_price="0",
    )
    rows = resp.get("Success") or []
    print(f"Breeze futures pull: status={resp.get('Status')} rows={len(rows)}")
    return rows


def fetch_dhan_futures(headers: dict) -> dict:
    body = {
        "securityId": NIFTY_FUT_SECURITY_ID,
        "exchangeSegment": "NSE_FNO",
        "instrument": "FUTIDX",
        "interval": "1",
        "oi": True,
        "fromDate": WINDOW_START.strftime("%Y-%m-%d %H:%M:%S"),
        "toDate": WINDOW_END.strftime("%Y-%m-%d %H:%M:%S"),
    }
    resp = requests.post(f"{DHAN_BASE}/charts/intraday", headers=headers, json=body, timeout=15)
    print(f"Dhan futures pull: status={resp.status_code}")
    if resp.status_code != 200:
        print(f"  body={resp.text[:500]}")
        return {"error": resp.text, "status": resp.status_code, "request_body": body}
    return {"status": resp.status_code, "data": resp.json(), "request_body": body}


def dhan_arrays_to_rows(data: dict) -> list:
    # Dhan returns column-oriented arrays (open[], high[], ...), not
    # row-per-candle like Breeze — this is exactly the raw provider shape
    # D-02/D-04 said normalization has to handle, not something to assume
    # away in the adapter.
    ts_list = data.get("timestamp") or []
    rows = []
    for i, ts in enumerate(ts_list):
        rows.append({
            "datetime": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
            "open": data.get("open", [None] * len(ts_list))[i],
            "high": data.get("high", [None] * len(ts_list))[i],
            "low": data.get("low", [None] * len(ts_list))[i],
            "close": data.get("close", [None] * len(ts_list))[i],
            "volume": data.get("volume", [None] * len(ts_list))[i],
            "open_interest": (data.get("open_interest") or [None] * len(ts_list))[i] if data.get("open_interest") else None,
        })
    return rows


def main():
    breeze = authenticate_breeze()
    dh_headers = dhan_headers()
    profile = check_dhan_auth(dh_headers)

    breeze_rows = fetch_breeze_futures(breeze)
    dhan_result = fetch_dhan_futures(dh_headers)
    dhan_rows = dhan_arrays_to_rows(dhan_result["data"]) if "data" in dhan_result else []

    breeze_by_time = {r["datetime"]: r for r in breeze_rows}
    dhan_by_time = {r["datetime"]: r for r in dhan_rows}
    all_times = sorted(set(breeze_by_time) | set(dhan_by_time))

    comparison = []
    for t in all_times:
        b, d = breeze_by_time.get(t), dhan_by_time.get(t)
        row = {"datetime": t, "breeze": b, "dhan": d}
        if b and d:
            row["close_diff"] = round(float(b["close"]) - float(d["close"]), 4)
            row["oi_diff"] = (int(float(b.get("open_interest") or 0)) - int(d.get("open_interest") or 0)) if d.get("open_interest") is not None else None
        comparison.append(row)
        print(f"  {t}  breeze_close={b['close'] if b else 'MISSING':<10} "
              f"dhan_close={d['close'] if d else 'MISSING':<10} "
              f"breeze_oi={b.get('open_interest') if b else '-':<10} dhan_oi={d.get('open_interest') if d else '-'}")

    report = {
        "dhan_profile": profile,
        "breeze_row_count": len(breeze_rows),
        "dhan_row_count": len(dhan_rows),
        "dhan_raw_result": dhan_result,
        "comparison": comparison,
    }
    report_path = RESULTS_DIR / f"s06_cross_provider_{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nFull report written to {report_path}")
    print("Next: read this back and add [LIVE] entries to docs/dynamic/findings.md.")


if __name__ == "__main__":
    main()

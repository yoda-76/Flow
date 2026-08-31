"""
S-01 coverage check — does Breeze actually deliver what its docs claim?

Answers (or at least gathers real evidence for) these open items from
docs/static/06-spikes.md:

  - Does the REST historical endpoint actually accept interval="1second",
    or is that a live-streaming-only capability wrongly documented as
    historical? (see docs/dynamic/findings.md, S-01 conflict)
  - Is open_interest populated for options, or zero/null?
  - Does an expired option contract from 2+ / 5+ years back return data?
  - Does the API fail loudly or silently (Status 200, empty list) on a
    bad request? (known hazard, already bit the equity pipeline once)
  - Does re-pulling the same request return identical data?
  - What does a single contract-day cost in bytes (rough S-02 sizing)?

This script is scratch, not a deliverable (see ../CLAUDE.md). Its output is
a JSON report under results/ — read that back and turn it into [LIVE]
entries in docs/dynamic/findings.md by hand; this script does not edit
findings.md itself.

Run with the venv in this folder:
    ./.venv/Scripts/python.exe s01_breeze_coverage_check.py

Needs experiments/.env with API_KEY, API_SECRET, API_SESSION — see
.examples.env. API_SESSION is a Breeze session token and must be refreshed
manually (SEBI daily-expiry requirement, see D-49) — if auth fails, that's
almost certainly why.
"""

import json
import os
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from breeze_connect import BreezeConnect

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

RESULTS_DIR = HERE / "results"
RESULTS_DIR.mkdir(exist_ok=True)

CALL_DELAY_SECONDS = 1.0  # 100 calls/min limit — no need to push it for ~15 calls


def fmt(dt: datetime) -> str:
    # Breeze rejects anything but exactly 3 millisecond digits (known bug,
    # see docs/static/breeze api docs and data_fetch_script.md history).
    #
    # ALSO — confirmed live 2026-08-30 (see findings.md, S-01): despite the
    # trailing "Z", Breeze reads the hour:minute:second digits as literal IST
    # wall-clock time, NOT true UTC. A properly-converted UTC timestamp (e.g.
    # 15:30 IST correctly sent as 10:00Z) gets silently misread as 10:00 IST,
    # truncating the session instead of erroring. Every `dt` passed to fmt()
    # in this script is therefore a NAIVE datetime already holding the
    # intended IST wall-clock value — never convert it, just stamp it.
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def authenticate() -> BreezeConnect:
    api_key = os.getenv("API_KEY")
    api_secret = os.getenv("API_SECRET")
    api_session = os.getenv("API_SESSION")

    missing = [n for n, v in [("API_KEY", api_key), ("API_SECRET", api_secret),
                               ("API_SESSION", api_session)] if not v]
    if missing:
        print(f"FATAL: missing from experiments/.env: {', '.join(missing)}")
        print("See experiments/.examples.env for what's required.")
        sys.exit(1)

    breeze = BreezeConnect(api_key=api_key)
    login_url = "https://api.icicidirect.com/apiuser/login?api_key=" + urllib.parse.quote_plus(api_key)

    try:
        breeze.generate_session(api_secret=api_secret, session_token=api_session)
    except Exception as e:
        print("FATAL: session generation failed — almost certainly an expired")
        print("API_SESSION (Breeze tokens expire daily/at midnight, see D-49).")
        print(f"Regenerate here, then update experiments/.env: {login_url}")
        print(f"Underlying error: {e}")
        sys.exit(1)

    print("Authenticated OK.")
    return breeze


def last_completed_trading_day(today: datetime) -> datetime:
    d = today - timedelta(days=1)
    while d.weekday() >= 5:  # Sat/Sun
        d -= timedelta(days=1)
    return d


def discover_current_nifty_contract(breeze, max_days_ahead: int = 12):
    """
    Expiry day/date is per-market, time-varying config (08-market-abstraction.md,
    D-52) — this script has no calendar to look it up, so it probes forward day
    by day using the live option-chain-quotes endpoint (cheap, no historical
    quota) until one returns a real, non-empty ladder. Returns
    (expiry_request_str, atm_strike, spot_price) or None if nothing hit within
    the window.
    """
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for days_ahead in range(max_days_ahead):
        candidate = today + timedelta(days=days_ahead)  # midnight IST, clean date only
        try:
            resp = breeze.get_option_chain_quotes(
                stock_code="NIFTY", exchange_code="NFO", product_type="options",
                right="call", expiry_date=fmt(candidate),
            )
        except Exception:
            time.sleep(CALL_DELAY_SECONDS)
            continue
        rows = resp.get("Success") or []
        if rows:
            try:
                spot = float(rows[0].get("spot_price"))
            except (TypeError, ValueError):
                spot = None
            if spot:
                best = min(rows, key=lambda r: abs(float(r["strike_price"]) - spot))
                return candidate, float(best["strike_price"]), spot
        time.sleep(CALL_DELAY_SECONDS)
    return None


def run_check(results: list, name: str, fn):
    print(f"\n--- {name} ---")
    entry = {"check": name, "timestamp": datetime.now(timezone.utc).isoformat()}
    try:
        outcome = fn()
        entry["outcome"] = outcome
        print(f"  -> {outcome.get('summary', outcome)}")
    except Exception as e:
        entry["outcome"] = {"error": str(e)}
        print(f"  -> ERROR: {e}")
    results.append(entry)
    time.sleep(CALL_DELAY_SECONDS)
    return entry


def summarize_response(resp: dict, max_rows: int = 3) -> dict:
    success = resp.get("Success")
    if success is None:
        return {"status": resp.get("Status"), "error": resp.get("Error"), "row_count": 0}
    if isinstance(success, list):
        return {
            "status": resp.get("Status"),
            "error": resp.get("Error"),
            "row_count": len(success),
            "first_rows": success[:max_rows],
            "raw_json_bytes": len(json.dumps(resp)),
        }
    return {"status": resp.get("Status"), "error": resp.get("Error"), "raw": success}


def main():
    breeze = authenticate()
    results = []
    # Naive datetimes throughout main() represent IST wall-clock directly —
    # see the fmt() docstring for why. System local tz here is already IST,
    # so datetime.now() needs no conversion.
    now_local = datetime.now()
    trading_day = last_completed_trading_day(now_local)
    window_start = trading_day.replace(hour=9, minute=30, second=0, microsecond=0)
    window_end = window_start + timedelta(minutes=2)
    full_day_start = trading_day.replace(hour=9, minute=15, second=0, microsecond=0)
    full_day_end = trading_day.replace(hour=15, minute=30, second=0, microsecond=0)

    # 1. Control: 1-minute equity cash, known-working shape, small window.
    def check_1min_control():
        resp = breeze.get_historical_data_v2(
            interval="1minute", from_date=fmt(window_start), to_date=fmt(window_end),
            stock_code="RELIND", exchange_code="NSE", product_type="cash",
        )
        s = summarize_response(resp)
        s["summary"] = f"status={s['status']} rows={s.get('row_count')}"
        return s

    # 2. The actual question: does REST accept interval="1second" at all?
    def check_1second_equity():
        resp = breeze.get_historical_data_v2(
            interval="1second", from_date=fmt(window_start), to_date=fmt(window_end),
            stock_code="RELIND", exchange_code="NSE", product_type="cash",
        )
        s = summarize_response(resp)
        s["summary"] = f"status={s['status']} rows={s.get('row_count')} error={s.get('error')}"
        return s

    # 3. Silent-empty-response check: an invalid stock_code.
    def check_invalid_stock_code():
        resp = breeze.get_historical_data_v2(
            interval="1minute", from_date=fmt(window_start), to_date=fmt(window_end),
            stock_code="ZZZINVALIDCODE", exchange_code="NSE", product_type="cash",
        )
        row_count = len(resp.get("Success") or [])
        s = {
            "status": resp.get("Status"), "error": resp.get("Error"), "row_count": row_count,
            "summary": (
                f"status={resp.get('Status')} error={resp.get('Error')} rows={row_count} "
                f"-> {'SILENT EMPTY (bad!)' if resp.get('Status') == 200 and row_count == 0 else 'fails loudly (good)'}"
            ),
        }
        return s

    # 4. Repeat-pull consistency: same request twice.
    def check_repeat_consistency():
        r1 = breeze.get_historical_data_v2(
            interval="1minute", from_date=fmt(window_start), to_date=fmt(window_end),
            stock_code="RELIND", exchange_code="NSE", product_type="cash",
        )
        time.sleep(CALL_DELAY_SECONDS)
        r2 = breeze.get_historical_data_v2(
            interval="1minute", from_date=fmt(window_start), to_date=fmt(window_end),
            stock_code="RELIND", exchange_code="NSE", product_type="cash",
        )
        identical = r1.get("Success") == r2.get("Success")
        return {"identical": identical, "summary": f"identical={identical}"}

    # 5. Options: a currently-live contract, discovered (not guessed) via the
    #    live option-chain-quotes endpoint, then pulled historically at
    #    1-minute to check OI population.
    contract_holder = {}

    def do_discover_contract():
        contract_holder["contract"] = discover_current_nifty_contract(breeze)
        c = contract_holder["contract"]
        if c is None:
            return {"summary": "no live NIFTY contract found within 12 days probed"}
        expiry, strike, spot = c
        return {"summary": f"expiry={expiry.date()} strike={strike} spot={spot}"}

    def check_option_recent():
        contract = contract_holder.get("contract")
        if contract is None:
            return {"summary": "discovery failed to find any live NIFTY contract within 12 days — see contract discovery step in report"}
        expiry, strike, spot = contract
        resp = breeze.get_historical_data_v2(
            interval="1minute", from_date=fmt(full_day_start), to_date=fmt(full_day_end),
            stock_code="NIFTY", exchange_code="NFO", product_type="options",
            expiry_date=fmt(expiry), right="call", strike_price=str(strike),
        )
        s = summarize_response(resp)
        oi_values = [row.get("open_interest") for row in (resp.get("Success") or [])]
        s["oi_populated"] = any(v not in (None, 0, "0", 0.0) for v in oi_values)
        s["discovered_contract"] = {"expiry": fmt(expiry), "strike": strike, "spot_at_discovery": spot}
        s["summary"] = f"status={s['status']} rows={s.get('row_count')} oi_populated={s['oi_populated']}"
        return s

    # 6. Deep history: a contract expired roughly 2 years back (guessed strike).
    def check_option_2y_back():
        day = datetime(2024, 1, 25)
        expiry = fmt(day)
        resp = breeze.get_historical_data_v2(
            interval="1minute",
            from_date=fmt(day.replace(hour=9, minute=15)),
            to_date=fmt(day.replace(hour=15, minute=30)),
            stock_code="NIFTY", exchange_code="NFO", product_type="options",
            expiry_date=expiry, right="call", strike_price="21000",
        )
        s = summarize_response(resp)
        s["summary"] = f"status={s['status']} rows={s.get('row_count')} (guessed strike/expiry — empty is informative, not a bug)"
        return s

    # 7. Deep history: a contract expired roughly 5 years back (guessed strike).
    def check_option_5y_back():
        day = datetime(2021, 8, 26)
        expiry = fmt(day)
        resp = breeze.get_historical_data_v2(
            interval="1minute",
            from_date=fmt(day.replace(hour=9, minute=15)),
            to_date=fmt(day.replace(hour=15, minute=30)),
            stock_code="NIFTY", exchange_code="NFO", product_type="options",
            expiry_date=expiry, right="call", strike_price="16500",
        )
        s = summarize_response(resp)
        s["summary"] = f"status={s['status']} rows={s.get('row_count')} (guessed strike/expiry — empty is informative, not a bug)"
        return s

    # 8. Rough per-contract-day size, for back-of-envelope S-02 extrapolation.
    def check_full_day_size():
        resp = breeze.get_historical_data_v2(
            interval="1minute", from_date=fmt(full_day_start), to_date=fmt(full_day_end),
            stock_code="RELIND", exchange_code="NSE", product_type="cash",
        )
        s = summarize_response(resp)
        s["summary"] = f"rows={s.get('row_count')} raw_json_bytes={s.get('raw_json_bytes')}"
        return s

    run_check(results, "1min control (RELIND cash)", check_1min_control)
    run_check(results, "1second REST support (RELIND cash)", check_1second_equity)
    run_check(results, "silent-empty-response check (invalid stock_code)", check_invalid_stock_code)
    run_check(results, "repeat-pull consistency", check_repeat_consistency)
    run_check(results, "discover a live NIFTY option contract", do_discover_contract)
    run_check(results, "option, recent expiry, OI population (discovered contract)", check_option_recent)
    run_check(results, "option, ~2 years back (guessed contract)", check_option_2y_back)
    run_check(results, "option, ~5 years back (guessed contract)", check_option_5y_back)
    run_check(results, "full trading day size, single equity contract", check_full_day_size)

    report_path = RESULTS_DIR / f"s01_coverage_{now_local.strftime('%Y%m%dT%H%M%S')}.json"
    report_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nFull report written to {report_path}")
    print("Next: read this back and add [LIVE] entries to docs/dynamic/findings.md.")


if __name__ == "__main__":
    main()

"""
D-28 spike, step 1: pull a small real sample (NIFTY options, front-week
expiry 2026-08-04, both trading days it was front-week: Aug 3-4 2026) to
use for evaluating NautilusTrader's data ingestion, and for testing the
Parquet+DuckDB storage pattern (D-01) on genuine chain-shaped data instead
of a single instrument.

Contract list (226 contracts, strikes 21600-27200) came from NSE's own
bhavcopy for 2026-08-04 (see docs/dynamic/findings.md, D-50 section) —
exact, not guessed.

Uses the 2-trading-day chunking already proven in data_fetch_script.md and
confirmed workable for this exact window in findings.md: both Aug 3 and
Aug 4 share the same front-week expiry, so this is 1 request per contract
(not 2), pulling both days' 1-minute data (~750 candles, under Breeze's
1000/request cap) in one call.

Raw output follows D-02 (store exact bytes, plus a fetch-metadata sidecar)
— one JSON file per contract under results/d28_sample/raw/, named by
strike+right so they're inspectable by eye.

This script is scratch, not a deliverable (see ../CLAUDE.md). Needs
experiments/.env with API_KEY/API_SECRET/API_SESSION (Breeze) — see
.examples.env.
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from breeze_connect import BreezeConnect

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

RAW_DIR = HERE / "results" / "d28_sample" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

CALL_DELAY_SECONDS = 0.6  # 226 requests at this pace ~= 2.5 minutes, well under 100/min

EXPIRY = datetime(2026, 8, 4)
WINDOW_START = datetime(2026, 8, 3, 9, 15)   # IST wall-clock, NOT converted to UTC — see fmt()
WINDOW_END = datetime(2026, 8, 4, 15, 30)


def fmt(dt: datetime) -> str:
    # See s01_breeze_coverage_check.py's fmt() docstring: Breeze reads this
    # as literal IST wall-clock time despite the trailing Z. Never convert.
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def authenticate() -> BreezeConnect:
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


def main():
    breeze = authenticate()
    contracts = json.loads((HERE / "results" / "nifty_20260804_contracts.json").read_text())["contracts"]
    print(f"Pulling {len(contracts)} contracts, {fmt(WINDOW_START)} to {fmt(WINDOW_END)} (1 chunked request each)")

    ok, empty, failed = 0, 0, 0
    for i, c in enumerate(contracts, 1):
        strike, right = c["strike"], c["right"]
        fname = RAW_DIR / f"{int(strike)}_{right}.json"
        if fname.exists():
            ok += 1
            continue  # resumable, matches the equity pipeline's established pattern

        try:
            resp = breeze.get_historical_data_v2(
                interval="1minute", from_date=fmt(WINDOW_START), to_date=fmt(WINDOW_END),
                stock_code="NIFTY", exchange_code="NFO", product_type="options",
                expiry_date=fmt(EXPIRY), right="call" if right == "CE" else "put",
                strike_price=str(int(strike)),
            )
        except Exception as e:
            print(f"  [{i}/{len(contracts)}] {strike} {right}: EXCEPTION {e}")
            failed += 1
            continue

        rows = resp.get("Success") or []
        record = {
            "fetch_metadata": {
                "fetched_at": datetime.now().isoformat(),
                "request": {
                    "stock_code": "NIFTY", "exchange_code": "NFO", "product_type": "options",
                    "expiry_date": fmt(EXPIRY), "right": right, "strike_price": strike,
                    "interval": "1minute", "from_date": fmt(WINDOW_START), "to_date": fmt(WINDOW_END),
                },
            },
            "response": resp,
        }
        fname.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")

        if rows:
            ok += 1
        else:
            empty += 1
        if i % 20 == 0 or i == len(contracts):
            print(f"  [{i}/{len(contracts)}] ok={ok} empty={empty} failed={failed}")
        time.sleep(CALL_DELAY_SECONDS)

    print(f"\nDone. ok={ok} empty={empty} failed={failed}. Raw files in {RAW_DIR}")


if __name__ == "__main__":
    main()

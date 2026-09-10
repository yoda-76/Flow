"""
Deliberately runs real option-history pulls past Breeze's documented
5,000/day cap to observe exactly what a breach looks like (exception?
distinct Status/Error? silent empty response?) -- we're already at ~4,880
of today's budget per the running tally, so this should only take a couple
more minutes of real, otherwise-useful downloading before it surfaces.

Hard safety rule: the moment a response looks anomalous in ANY way (not a
clean Status:200, or a raised exception), STOP immediately -- no further
requests, not even one more. This is the whole point of the experiment,
so the stop condition is intentionally paranoid/broad, not narrowly tuned
to "only stop on an explicit rate-limit message" (we don't know the exact
shape yet -- that's what we're finding out).

Scratch, not a deliverable (see ../CLAUDE.md).
"""

import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "flow"))
from adapters.breeze import authenticate, pull_option_history, save_raw  # noqa: E402
from adapters.download_options import build_contract_chunks  # noqa: E402
from adapters.raw_io import is_saved  # noqa: E402
from rules.store import MarketRulesStore  # noqa: E402

RAW_ROOT = Path(__file__).resolve().parent.parent / "flow" / "data" / "raw" / "breeze" / "options"
MARKET_OPEN, MARKET_CLOSE = "09:15:00", "15:30:00"


def main():
    store = MarketRulesStore()
    start, end = date(2024, 1, 1), date(2026, 9, 7)
    print("Building chunk list...")
    chunks = build_contract_chunks(store, "NIFTY", start, end)

    pending = []
    for c_start, c_end, instrument_id, expiry, strike, right in chunks:
        out_path = RAW_ROOT / "NIFTY" / expiry / f"{strike}_{right}" / f"{c_start.isoformat()}_{c_end.isoformat()}.json"
        if not is_saved(out_path):
            pending.append((c_start, c_end, instrument_id, expiry, strike, right, out_path))
    print(f"{len(pending)} chunks pending, starting real pulls now, sleep=1.0s...\n")

    breeze = authenticate()
    ok = 0
    for i, (c_start, c_end, instrument_id, expiry, strike, right, out_path) in enumerate(pending, 1):
        expiry_dt = datetime.strptime(expiry, "%Y-%m-%d")
        from_dt = datetime.strptime(f"{c_start.isoformat()} {MARKET_OPEN}", "%Y-%m-%d %H:%M:%S")
        to_dt = datetime.strptime(f"{c_end.isoformat()} {MARKET_CLOSE}", "%Y-%m-%d %H:%M:%S")

        try:
            response = pull_option_history(breeze, "NIFTY", expiry_dt, float(strike), right, from_dt, to_dt)
        except Exception as e:
            print(f"\n*** STOPPING: exception on request {i} ({ok} clean requests before this) ***")
            print(f"    contract: {instrument_id}, chunk: {c_start} to {c_end}")
            print(f"    exception type: {type(e).__name__}")
            print(f"    exception: {e}")
            return

        if response.get("Status") != 200:
            print(f"\n*** STOPPING: anomalous Status on request {i} ({ok} clean requests before this) ***")
            print(f"    contract: {instrument_id}, chunk: {c_start} to {c_end}")
            print(f"    full response: {response}")
            return

        save_raw(response, {
            "underlying": "NIFTY", "instrument_id": instrument_id, "expiry": expiry,
            "strike": strike, "right": right, "interval": "1minute",
            "from_dt": from_dt.isoformat(), "to_dt": to_dt.isoformat(),
            "product_type": "options", "exchange_code": "NFO",
        }, out_path)
        ok += 1

        if i % 25 == 0:
            print(f"...{i} requests made, {ok} clean so far ({c_start} to {c_end}, {instrument_id})")
        time.sleep(1.0)

    print(f"\nExhausted pending list without hitting an anomaly: {ok} clean requests total.")


if __name__ == "__main__":
    main()

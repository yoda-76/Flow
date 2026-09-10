"""
Downloads NIFTY front-month futures 1-minute history from Breeze across a
date range (D-50's scope: front-month only, not the full listed ladder).

Front-month is resolved per trading day from the instrument master
(rules/store.py's front_contract) rather than a computed rollover rule --
which contract actually traded on a given day is real observed data (same
reasoning as D-52's expiry sourcing), and NIFTY's monthly expiry weekday
has shifted historically so a computed rule would be wrong for part of any
multi-year range. A 2-day chunk is split into two solo-day chunks whenever
the front contract changes mid-pair (a rollover day), so every request
still maps to exactly one instrument -- pull_future_history takes a single
expiry_date.

Resumable the same way as download_index.py: each chunk writes one raw file
under flow/data/raw/breeze/futures/{underlying}/{expiry}/, skipped on
re-run once it holds a definitive (Status 200) response.

Usage:
    .venv/Scripts/python.exe -m adapters.download_futures --start 2024-01-01 --end 2026-09-04
"""

import argparse
import sys
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.breeze import authenticate, pull_future_history, save_raw  # noqa: E402
from adapters.chunking import trading_days  # noqa: E402
from adapters.raw_io import is_saved  # noqa: E402
from rules.store import MarketRulesStore  # noqa: E402

RAW_ROOT = Path(__file__).resolve().parent.parent / "data" / "raw" / "breeze" / "futures"
MARKET_OPEN, MARKET_CLOSE = "09:15:00", "15:30:00"


def chunk_by_front_contract(store, underlying, start, end, instrument_type="IDF"):
    """Returns (chunk_start, chunk_end, instrument_id) triples. Days the
    instrument master doesn't (yet) know the front contract for -- e.g.
    today, before its bhavcopy is published -- are silently dropped, not
    guessed."""
    days = list(trading_days(start, end))
    contract_for = {d: store.front_contract(underlying, d, instrument_type) for d in days}
    days = [d for d in days if contract_for[d] is not None]

    weeks = defaultdict(list)
    for d in days:
        weeks[d.isocalendar()[:2]].append(d)

    chunks = []
    for wk_days in weeks.values():
        wk_days = sorted(wk_days)
        i = 0
        while i < len(wk_days):
            pair = wk_days[i:i + 2]
            i += 2
            if len(pair) == 1 or contract_for[pair[0]] == contract_for[pair[1]]:
                chunks.append((pair[0], pair[-1], contract_for[pair[0]]))
            else:
                chunks.append((pair[0], pair[0], contract_for[pair[0]]))
                chunks.append((pair[1], pair[1], contract_for[pair[1]]))
    return chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--underlying", default="NIFTY")
    ap.add_argument("--interval", default="1minute")
    ap.add_argument("--sleep", type=float, default=1.0, help="seconds between requests")
    args = ap.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    store = MarketRulesStore()
    chunks = chunk_by_front_contract(store, args.underlying, start, end)

    pending = []
    for c_start, c_end, instrument_id in chunks:
        expiry = instrument_id.split("|")[2]
        out_path = RAW_ROOT / args.underlying / expiry / f"{c_start.isoformat()}_{c_end.isoformat()}.json"
        if not is_saved(out_path):
            pending.append((c_start, c_end, instrument_id, expiry, out_path))

    print(f"{len(chunks)} chunks total, {len(chunks) - len(pending)} already done, {len(pending)} to fetch")
    if not pending:
        return

    breeze = authenticate()
    ok, failed = 0, []
    for i, (c_start, c_end, instrument_id, expiry, out_path) in enumerate(pending, 1):
        expiry_dt = datetime.strptime(expiry, "%Y-%m-%d")
        from_dt = datetime.strptime(f"{c_start.isoformat()} {MARKET_OPEN}", "%Y-%m-%d %H:%M:%S")
        to_dt = datetime.strptime(f"{c_end.isoformat()} {MARKET_CLOSE}", "%Y-%m-%d %H:%M:%S")
        try:
            response = pull_future_history(breeze, args.underlying, expiry_dt, from_dt, to_dt, args.interval)
            request_meta = {
                "underlying": args.underlying, "instrument_id": instrument_id, "expiry": expiry,
                "interval": args.interval, "from_dt": from_dt.isoformat(), "to_dt": to_dt.isoformat(),
                "product_type": "futures", "exchange_code": "NFO",
            }
            save_raw(response, request_meta, out_path)
            if response.get("Status") == 200:
                ok += 1
            else:
                failed.append((c_start, c_end, instrument_id, response.get("Error")))
        except Exception as e:
            failed.append((c_start, c_end, instrument_id, str(e)))

        if i % 25 == 0 or i == len(pending):
            print(f"...{i}/{len(pending)} ({c_start} to {c_end}, {instrument_id}), {ok} ok so far, {len(failed)} failed")
        time.sleep(args.sleep)

    print(f"\nDone: {ok} ok, {len(failed)} failed")
    for c_start, c_end, instrument_id, err in failed[:20]:
        print(f"  FAILED {c_start} to {c_end} ({instrument_id}): {err}")


if __name__ == "__main__":
    main()

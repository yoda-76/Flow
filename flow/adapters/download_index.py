"""
Downloads NIFTY (or another index) 1-minute spot history from Breeze across
a date range, using the proven 2-trading-day chunking (chunking.py) and
D-49's manual daily session token.

Resumable by construction: each chunk writes one raw file
(flow/data/raw/breeze/index/{underlying}/{chunk_start}_{chunk_end}.json) and
a chunk is skipped once that file holds a definitive (Status 200) response
-- an empty Success list still counts as done (real: e.g. a holiday), not
a hole to keep retrying. Safe to Ctrl-C and re-run, or split across
multiple days if a wider pull (futures/options) ever needs more than one
day's request budget.

Usage:
    .venv/Scripts/python.exe -m adapters.download_index --start 2024-01-01 --end 2026-09-07
"""

import argparse
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.breeze import authenticate, pull_index_history, save_raw  # noqa: E402
from adapters.chunking import two_day_chunks  # noqa: E402
from adapters.raw_io import is_saved  # noqa: E402

RAW_ROOT = Path(__file__).resolve().parent.parent / "data" / "raw" / "breeze" / "index"
MARKET_OPEN, MARKET_CLOSE = "09:15:00", "15:30:00"


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
    chunks = two_day_chunks(start, end)
    out_dir = RAW_ROOT / args.underlying
    out_dir.mkdir(parents=True, exist_ok=True)

    pending = [c for c in chunks if not is_saved(out_dir / f"{c[0].isoformat()}_{c[1].isoformat()}.json")]
    print(f"{len(chunks)} chunks total, {len(chunks) - len(pending)} already done, {len(pending)} to fetch")
    if not pending:
        return

    breeze = authenticate()
    ok, failed = 0, []
    for i, (c_start, c_end) in enumerate(pending, 1):
        from_dt = datetime.strptime(f"{c_start.isoformat()} {MARKET_OPEN}", "%Y-%m-%d %H:%M:%S")
        to_dt = datetime.strptime(f"{c_end.isoformat()} {MARKET_CLOSE}", "%Y-%m-%d %H:%M:%S")
        out_path = out_dir / f"{c_start.isoformat()}_{c_end.isoformat()}.json"
        try:
            response = pull_index_history(breeze, args.underlying, from_dt, to_dt, args.interval)
            request_meta = {
                "underlying": args.underlying, "interval": args.interval,
                "from_dt": from_dt.isoformat(), "to_dt": to_dt.isoformat(),
                "product_type": "cash", "exchange_code": "NSE",
            }
            save_raw(response, request_meta, out_path)
            if response.get("Status") == 200:
                ok += 1
            else:
                failed.append((c_start, c_end, response.get("Error")))
        except Exception as e:
            failed.append((c_start, c_end, str(e)))

        if i % 25 == 0 or i == len(pending):
            print(f"...{i}/{len(pending)} ({c_start} to {c_end}), {ok} ok so far, {len(failed)} failed")
        time.sleep(args.sleep)

    print(f"\nDone: {ok} ok, {len(failed)} failed")
    for c_start, c_end, err in failed[:20]:
        print(f"  FAILED {c_start} to {c_end}: {err}")


if __name__ == "__main__":
    main()

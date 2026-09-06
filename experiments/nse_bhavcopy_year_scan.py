"""
Exact D-50 request-budget calculation for the last 1/3/6/9/12 months: how
many Breeze API requests would a NIFTY front-weekly 1-minute chain pull
actually need, day by day, using real contract counts instead of an
average-based estimate?

Uses NSE's own F&O bhavcopy (UDiFF format) directly. NOTE: jugaad-data's
built-in bhavcopy_fo_raw() hits NSE's OLD bhavcopy URL, which stopped being
served after NSE's UDiFF migration (2024-07-08) — confirmed live 2026-09-06,
it fails ("File is not a zip file") for any recent date. jugaad-data's
bhavcopy_udiff_raw() only covers the equity (CM) segment, not F&O. The real
F&O UDiFF URL was found by mirroring the CM UDiFF path's shape and
confirmed working live:

    https://archives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip

This script fetches that directly, reusing jugaad-data's NSEArchives session
(it already handles NSE's bot-protection headers/cookies) rather than
reimplementing that from scratch.

For each trading day:
  1. Pull that day's F&O bhavcopy (UDiFF format).
  2. Filter to TckrSymb == NIFTY, FinInstrmTp == IDO (index options).
  3. Front-weekly expiry = earliest XpryDt >= that day among them.
  4. Count contracts (CE+PE) at that expiry = Breeze requests needed for
     that day (1 request per contract per day; a full day's 1-minute data
     is ~376 candles, under Breeze's 1000-candle/request cap).

This is scratch, not a deliverable (see ../CLAUDE.md). Output: a JSON
report under results/ plus a printed summary table for 1/3/6/9/12 months.
"""

import csv
import io
import json
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

from jugaad_data.nse.archives import NSEArchives

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"
RESULTS_DIR.mkdir(exist_ok=True)

FO_UDIFF_URL = "https://archives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"
REQUEST_DELAY_SECONDS = 0.4  # be a considerate client, not just a fast one
BYTES_PER_CONTRACT_DAY = 108_000  # ~287 bytes/row x ~376 rows, see findings.md S-01


def fetch_fo_bhavcopy(session, d: date) -> str:
    url = FO_UDIFF_URL.format(ymd=d.strftime("%Y%m%d"))
    r = session.get(url, timeout=15)
    if r.status_code != 200 or r.content[:2] != b"PK":
        raise ValueError(f"status={r.status_code} not-a-zip (likely a holiday/weekend)")
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        return zf.open(zf.namelist()[0]).read().decode("utf-8")


def front_weekly_nifty_count(raw_csv: str, d: date):
    reader = csv.DictReader(io.StringIO(raw_csv))
    rows = [row for row in reader if row.get("TckrSymb") == "NIFTY" and row.get("FinInstrmTp") == "IDO"]
    if not rows:
        return None, 0
    expiries = sorted({datetime.strptime(r["XpryDt"], "%Y-%m-%d").date() for r in rows})
    candidates = [e for e in expiries if e >= d]
    if not candidates:
        return None, 0
    front = candidates[0]
    count = sum(1 for r in rows if datetime.strptime(r["XpryDt"], "%Y-%m-%d").date() == front)
    return front, count


def main():
    archives = NSEArchives()
    session = archives.s

    today = date.today()
    start = today - timedelta(days=380)  # 12 months + buffer
    daily_results = []

    d = start
    while d < today:
        if d.weekday() < 5:  # Mon-Fri; NSE holidays fall out naturally as fetch failures below
            try:
                raw = fetch_fo_bhavcopy(session, d)
                front, count = front_weekly_nifty_count(raw, d)
                if front:
                    daily_results.append({"date": d.isoformat(), "front_expiry": front.isoformat(), "contracts": count})
                    print(f"{d}  front_expiry={front}  contracts={count}")
                else:
                    print(f"{d}  no NIFTY IDO rows found (unexpected)")
            except Exception as e:
                print(f"{d}  skipped ({e})")
            time.sleep(REQUEST_DELAY_SECONDS)
        d += timedelta(days=1)

    report_path = RESULTS_DIR / f"nse_bhavcopy_year_scan_{today.isoformat()}.json"
    report_path.write_text(json.dumps(daily_results, indent=2), encoding="utf-8")
    print(f"\nRaw daily data written to {report_path}")

    if not daily_results:
        print("No data collected — aborting summary.")
        return

    print_request_budget(daily_results)


def chunk_into_2day_requests(daily_results):
    """
    Reproduces the proven "2 trading days per request" chunking from the
    working equity pipeline (data_fetch_script.md): group by ISO week, pair
    2-at-a-time within the week (never crossing into the next week's
    Monday). If a pair's contract count differs (a rollover landed mid-pair
    -- confirmed to actually happen, since NIFTY's weekly expiry weekday
    has shifted during the year), it can't be combined and falls back to
    two single-day requests.
    """
    from collections import defaultdict
    by_date = {date.fromisoformat(r["date"]): r["contracts"] for r in daily_results}
    days = sorted(by_date)
    weeks = defaultdict(list)
    for d in days:
        weeks[d.isocalendar()[:2]].append(d)

    requests = []  # (last_day_in_chunk, request_count)
    for wk_days in weeks.values():
        wk_days = sorted(wk_days)
        i = 0
        while i < len(wk_days):
            chunk = wk_days[i:i + 2]
            i += 2
            if len(chunk) == 1:
                requests.append((chunk[0], by_date[chunk[0]]))
            else:
                d1, d2 = chunk
                c1, c2 = by_date[d1], by_date[d2]
                if c1 == c2:
                    requests.append((d2, c1))
                else:
                    requests.append((d1, c1))
                    requests.append((d2, c2))
    return requests


def print_request_budget(daily_results):
    last_day = date.fromisoformat(daily_results[-1]["date"])
    two_day_requests = chunk_into_2day_requests(daily_results)

    print("\n=== D-50 exact request budget: NIFTY front-weekly, 1-minute, by window ===")
    header = f"{'Window':>8} | {'Trading days':>12} | {'1req/day':>10} | {'1req/2days':>11} | {'Days@5000/day':>14} | {'Raw size':>10}"
    print(header)
    for days_back, label in [(14, "2wk"), (30, "1mo"), (91, "3mo"), (182, "6mo"), (273, "9mo"), (365, "12mo")]:
        cutoff = last_day - timedelta(days=days_back)
        subset = [r for r in daily_results if date.fromisoformat(r["date"]) > cutoff]
        total_1day = sum(r["contracts"] for r in subset)
        total_2day = sum(c for d, c in two_day_requests if d > cutoff)
        trading_days = len(subset)
        calendar_days_needed = -(-total_2day // 5000) if total_2day else 0
        raw_gb = total_1day * BYTES_PER_CONTRACT_DAY / (1024 ** 3)
        print(f"{label:>8} | {trading_days:>12} | {total_1day:>10,} | {total_2day:>11,} | {calendar_days_needed:>14} | {raw_gb:>8.2f} GB")


if __name__ == "__main__":
    main()

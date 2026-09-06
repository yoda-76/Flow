"""
Exact request-budget calculation for downloading NIFTY futures + options
1-minute historical data from Breeze, for the full Jan 1 2024 - today
range (matches the instrument master's coverage, flow/rules/).

Reuses flow/rules/bhavcopy.py's dual-era (legacy + UDiFF) bhavcopy access
-- no need to duplicate that logic. Scope matches D-50's already-decided
approach: front-weekly options, front-month futures (not the full listed
ladder/all expiries) -- flag if a wider scope is wanted, this recomputes
easily.

This is scratch, not a deliverable (see ../CLAUDE.md).
"""

import math
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "flow"))
from rules.bhavcopy import fetch_fo_bhavcopy, parse_fo_bhavcopy  # noqa: E402

START = date(2024, 1, 1)
END = date(2026, 9, 7)


def trading_days(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def front_expiry_and_count(rows, itype, d):
    matching = [r for r in rows if r["FinInstrmTp"] == itype]
    expiries = sorted({r["XpryDt"] for r in matching if r["XpryDt"] >= d.isoformat()})
    if not expiries:
        return None, 0
    front = expiries[0]
    return front, sum(1 for r in matching if r["XpryDt"] == front)


def chunk_into_2day_requests(daily_results, value_key):
    """Same logic as nse_bhavcopy_year_scan.py's 2-day chunking, generalized
    to work on either the option or future contract-count series."""
    by_date = {r["date"]: r[value_key] for r in daily_results}
    days = sorted(by_date)
    weeks = defaultdict(list)
    for d in days:
        weeks[d.isocalendar()[:2]].append(d)

    requests = []
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


def main():
    daily = []
    days_scanned, days_skipped, legacy_count = 0, 0, 0

    for d in trading_days(START, END):
        try:
            raw, is_legacy = fetch_fo_bhavcopy(d)
        except ValueError:
            days_skipped += 1
            continue
        rows = parse_fo_bhavcopy(raw, is_legacy, underlyings={"NIFTY"}, instrument_types={"IDO", "IDF"})
        days_scanned += 1
        legacy_count += is_legacy

        _, opt_count = front_expiry_and_count(rows, "IDO", d)
        _, fut_count = front_expiry_and_count(rows, "IDF", d)
        daily.append({"date": d, "opt": opt_count, "fut": fut_count})
        if days_scanned % 50 == 0:
            print(f"...scanned {days_scanned} days so far ({d})")

    print(f"\nScanned {days_scanned} trading days ({legacy_count} legacy-format, {days_skipped} skipped)")

    opt_1day = sum(r["opt"] for r in daily)
    fut_1day = sum(r["fut"] for r in daily)
    opt_2day = sum(c for _, c in chunk_into_2day_requests(daily, "opt"))
    fut_2day = sum(c for _, c in chunk_into_2day_requests(daily, "fut"))

    total_1day = opt_1day + fut_1day
    total_2day = opt_2day + fut_2day

    print("\n=== Full range (2024-01-01 to 2026-09-07), front-weekly options + front-month futures ===")
    print(f"{'':>12} | {'1req/day':>10} | {'1req/2days':>11} | {'days@5000/day':>14}")
    print(f"{'Options':>12} | {opt_1day:>10,} | {opt_2day:>11,} | {math.ceil(opt_2day/5000):>14}")
    print(f"{'Futures':>12} | {fut_1day:>10,} | {fut_2day:>11,} | {math.ceil(fut_2day/5000):>14}")
    print(f"{'TOTAL':>12} | {total_1day:>10,} | {total_2day:>11,} | {math.ceil(total_2day/5000):>14}")

    raw_gb = total_1day * 200_000 / (1024 ** 3)  # ~200KB/contract-day, midpoint of measured 108-290KB range
    print(f"\nRough raw storage estimate: ~{raw_gb:.1f} GB (using ~200KB/contract-day)")
    print(f"At ~1 req/sec pacing: ~{total_2day/3600:.1f} hours of total script runtime across all days")


if __name__ == "__main__":
    main()

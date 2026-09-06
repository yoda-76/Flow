"""
The proven 2-trading-day chunking pattern (data_fetch_script.md,
findings.md D-50): pairs of trading days grouped within an ISO calendar
week, never crossing into the next week's Monday (so a chunk never spans
Friday+Monday) -- reproduces "Mon+Tue, Wed+Thu, Fri-alone" without
hardcoding weekday-of-week (NIFTY's expiry weekday has shifted historically,
this doesn't assume anything about which day means what).
"""

from collections import defaultdict
from datetime import date, timedelta


def trading_days(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def pair_days(days) -> list:
    """2-day pairing within ISO calendar weeks, generic over any day list
    (not necessarily a contiguous start/end range -- e.g. one option
    contract's own trading-day subset). Returns (chunk_start, chunk_end)
    pairs; chunk_end equals chunk_start for a solo day."""
    weeks = defaultdict(list)
    for d in days:
        weeks[d.isocalendar()[:2]].append(d)

    chunks = []
    for wk_days in weeks.values():
        wk_days = sorted(wk_days)
        i = 0
        while i < len(wk_days):
            pair = wk_days[i:i + 2]
            chunks.append((pair[0], pair[-1]))
            i += 2
    return chunks


def two_day_chunks(start: date, end: date) -> list:
    """Returns a list of (chunk_start, chunk_end) date pairs -- chunk_end
    equals chunk_start for a solo day (typically Friday, or a week with a
    holiday-shortened tail)."""
    return pair_days(trading_days(start, end))

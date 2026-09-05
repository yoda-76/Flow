"""
Does the downloaded SecurityMaster (Breeze's NSE F&O scrip master dump)
contain expired/historical contracts, or only current+near-future listings?

Answers a question for D-52 (expiry calendar sourcing): SecurityMaster.zip
is a broker's "what can I trade right now" file, regenerated daily — the
prior assumption was it's current-state only and can't seed a historical
expiry calendar. This checks that assumption against the actual file rather
than guessing.

Reads the file streaming (csv module, line by line) rather than loading it
whole — it's ~78k lines / 21MB, no need to hold it all in memory or dump it
into a chat transcript.

Usage: python check_securitymaster_expiry_coverage.py
"""

import csv
from collections import Counter
from datetime import datetime
from pathlib import Path

SECURITY_MASTER = Path(__file__).resolve().parent.parent / "SecurityMaster" / "FONSEScripMaster.txt"


def parse_expiry(s: str):
    s = s.strip()
    if not s or s == "0":
        return None
    try:
        return datetime.strptime(s, "%d-%b-%Y").date()
    except ValueError:
        return None


def main():
    # Breeze's ShortName for Bank Nifty is "CNXBAN", not "BANKNIFTY" — see
    # docs/dynamic/findings.md S-06.
    underlyings_wanted = {"NIFTY", "CNXBAN"}
    instrument_types = {"OPTIDX", "FUTIDX"}

    expiries_by_underlying = {u: set() for u in underlyings_wanted}
    total_rows = 0
    matched_rows = 0

    with open(SECURITY_MASTER, "r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {name: i for i, name in enumerate(header)}
        for row in reader:
            total_rows += 1
            if not row:
                continue
            instrument_name = row[idx["InstrumentName"]]
            short_name = row[idx["ShortName"]]
            if instrument_name not in instrument_types or short_name not in underlyings_wanted:
                continue
            expiry = parse_expiry(row[idx["ExpiryDate"]])
            if expiry:
                matched_rows += 1
                expiries_by_underlying[short_name].add(expiry)

    print(f"Total rows scanned: {total_rows}")
    print(f"Matched NIFTY/BANKNIFTY OPTIDX/FUTIDX rows: {matched_rows}\n")

    today = datetime.now().date()
    for u, dates in expiries_by_underlying.items():
        if not dates:
            print(f"{u}: no contracts found")
            continue
        sorted_dates = sorted(dates)
        past = [d for d in sorted_dates if d < today]
        future = [d for d in sorted_dates if d >= today]
        print(f"{u}: {len(sorted_dates)} distinct expiries")
        print(f"  earliest: {sorted_dates[0]}   latest: {sorted_dates[-1]}")
        print(f"  relative to today ({today}): {len(past)} in the past, {len(future)} today/future")
        print(f"  all expiries: {sorted_dates}\n")


if __name__ == "__main__":
    main()

"""
Verifies that "Status:200, Success:[]" from Breeze for a downloaded option
chunk really means "genuinely no 1-min trades that window", not "our
request didn't match a real contract" (a formatting bug) -- by
cross-checking a sample of already-downloaded empty raw files against the
same day's NSE bhavcopy volume field for that exact
(underlying, expiry, strike, right). Bypasses rules/bhavcopy.py's
normalized shape (which drops volume) and reads the raw CSV directly.

Scratch, not a deliverable (see ../CLAUDE.md).
"""

import csv
import io
import json
import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "flow"))
from rules.bhavcopy import fetch_fo_bhavcopy  # noqa: E402

RAW_ROOT = Path(__file__).resolve().parent.parent / "flow" / "data" / "raw" / "breeze" / "options" / "NIFTY"


def find_empty_files(n=15):
    empties = []
    for f in RAW_ROOT.rglob("*.json"):
        record = json.loads(f.read_text())
        resp = record.get("response") or {}
        if resp.get("Status") == 200 and not resp.get("Success"):
            empties.append((f, record))
    random.seed(42)
    return random.sample(empties, min(n, len(empties)))


def volume_for(d: date, expiry: str, strike: str, right: str):
    try:
        raw, is_legacy = fetch_fo_bhavcopy(d)
    except ValueError:
        return "HOLIDAY"

    reader = csv.DictReader(io.StringIO(raw))
    for row in reader:
        if is_legacy:
            if (row["SYMBOL"] == "NIFTY" and row["INSTRUMENT"] == "OPTIDX"
                    and row["EXPIRY_DT"] and _iso(row["EXPIRY_DT"]) == expiry
                    and _num(row["STRIKE_PR"]) == _num(strike) and row["OPTION_TYP"] == right):
                return row["CONTRACTS"]
        else:
            if (row["TckrSymb"] == "NIFTY" and row["FinInstrmTp"] == "IDO"
                    and row["XpryDt"] == expiry
                    and _num(row["StrkPric"]) == _num(strike) and row["OptnTp"] == right):
                return row["TtlTradgVol"]
    return "NOT LISTED IN BHAVCOPY"


def _iso(ddmonyyyy):
    from datetime import datetime
    return datetime.strptime(ddmonyyyy, "%d-%b-%Y").date().isoformat()


def _num(s):
    return float(s)


def main():
    sample = find_empty_files(15)
    print(f"Checking {len(sample)} empty-response raw files against bhavcopy volume...\n")

    for f, record in sample:
        req = record["fetch_metadata"]["request"]
        strike, right, expiry = req["strike"], req["right"], req["expiry"]
        c_start = date.fromisoformat(req["from_dt"][:10])
        c_end = date.fromisoformat(req["to_dt"][:10])
        days = [c_start] if c_start == c_end else [c_start, c_end]
        for d in days:
            vol = volume_for(d, expiry, strike, right)
            flag = "  <-- SUSPICIOUS (bhavcopy shows real volume)" if isinstance(vol, str) and vol.isdigit() and int(vol) > 0 else ""
            print(f"  {d} {strike}{right} exp={expiry}: bhavcopy volume={vol}{flag}")


if __name__ == "__main__":
    main()

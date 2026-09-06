"""
NSE F&O bhavcopy (UDiFF format) access.

jugaad-data's own bhavcopy_fo_raw() hits NSE's pre-2024 legacy bhavcopy URL,
dead since NSE's UDiFF migration (2024-07-08) -- confirmed in
experiments/nse_bhavcopy_year_scan.py (docs/dynamic/findings.md, D-50
section). This module uses the real UDiFF F&O URL directly, reusing
jugaad-data's NSEArchives session for NSE's bot-protection handling rather
than reimplementing it.

FinInstrmTp codes (confirmed live): IDO=index option, IDF=index future,
STO=stock option, STF=stock future.
"""

import csv
import io
import zipfile
from datetime import date

from jugaad_data.nse.archives import NSEArchives

FO_UDIFF_URL = "https://archives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"

_archives = None


def _session():
    global _archives
    if _archives is None:
        _archives = NSEArchives()
    return _archives.s


def fetch_fo_bhavcopy(d: date) -> str:
    """
    Raw UDiFF F&O bhavcopy CSV text for one trading day.

    Raises ValueError if the day has no data -- a holiday/weekend, or not
    yet published. Never fabricates a result for a missing day (R26).
    """
    session = _session()
    url = FO_UDIFF_URL.format(ymd=d.strftime("%Y%m%d"))
    resp = session.get(url, timeout=15)
    if resp.status_code != 200 or resp.content[:2] != b"PK":
        raise ValueError(f"no bhavcopy for {d} (status={resp.status_code})")
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        return zf.open(zf.namelist()[0]).read().decode("utf-8")


def parse_fo_bhavcopy(raw_csv: str, underlyings: set[str] | None = None,
                       instrument_types: set[str] | None = None) -> list[dict]:
    """
    Parse bhavcopy rows into dicts, optionally filtered by underlying
    (TckrSymb) and/or instrument type (FinInstrmTp).
    """
    reader = csv.DictReader(io.StringIO(raw_csv))
    rows = []
    for row in reader:
        if underlyings and row["TckrSymb"] not in underlyings:
            continue
        if instrument_types and row["FinInstrmTp"] not in instrument_types:
            continue
        rows.append(row)
    return rows

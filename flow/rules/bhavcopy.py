"""
NSE F&O bhavcopy access, spanning both the legacy (pre-2024-07-08) and
UDiFF (2024-07-08 onward) formats -- they use different column names and
the legacy format lacks a token/lot-size column entirely, so this module
normalizes both into one common row shape:

    TckrSymb, FinInstrmTp, XpryDt (ISO), StrkPric, OptnTp,
    NewBrdLotQty (str or None), FinInstrmId (str or None)

jugaad-data's own bhavcopy_fo_raw() hits NSE's legacy URL and works fine
for dates before the UDiFF migration -- confirmed live. It's dead for
dates after (findings.md, D-50), which is what the direct UDiFF URL below
handles instead. FinInstrmTp codes: IDO=index option, IDF=index future,
STO=stock option, STF=stock future (both eras use compatible values, just
spelled differently -- OPTIDX/FUTIDX/OPTSTK/FUTSTK in legacy).
"""

import csv
import io
import zipfile
from datetime import date, datetime

from jugaad_data.nse import bhavcopy_fo_raw as _legacy_bhavcopy_fo_raw
from jugaad_data.nse.archives import NSEArchives

FO_UDIFF_URL = "https://archives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"
UDIFF_START_DATE = date(2024, 7, 8)  # matches jugaad-data's own constant

_LEGACY_INSTRUMENT_MAP = {"FUTIDX": "IDF", "OPTIDX": "IDO", "FUTSTK": "STF", "OPTSTK": "STO"}

_archives = None


def _session():
    global _archives
    if _archives is None:
        _archives = NSEArchives()
    return _archives.s


def _fetch_udiff(d: date) -> str:
    session = _session()
    url = FO_UDIFF_URL.format(ymd=d.strftime("%Y%m%d"))
    resp = session.get(url, timeout=15)
    if resp.status_code != 200 or resp.content[:2] != b"PK":
        raise ValueError(f"no bhavcopy for {d} (status={resp.status_code})")
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        return zf.open(zf.namelist()[0]).read().decode("utf-8")


def _fetch_legacy(d: date) -> str:
    try:
        text = _legacy_bhavcopy_fo_raw(d)
    except Exception as e:
        raise ValueError(f"no bhavcopy for {d}: {e}")
    if not text or not text.strip():
        raise ValueError(f"no bhavcopy for {d} (empty response)")
    return text


def fetch_fo_bhavcopy(d: date) -> tuple:
    """Returns (raw_csv_text, is_legacy). Raises ValueError if the day has
    no data -- a holiday/weekend, or not yet published (R26: never
    fabricate a result for a missing day)."""
    if d < UDIFF_START_DATE:
        return _fetch_legacy(d), True
    return _fetch_udiff(d), False


def _normalize_legacy_row(row: dict) -> dict:
    return {
        "TckrSymb": row["SYMBOL"],
        "FinInstrmTp": _LEGACY_INSTRUMENT_MAP.get(row["INSTRUMENT"], row["INSTRUMENT"]),
        "XpryDt": datetime.strptime(row["EXPIRY_DT"], "%d-%b-%Y").date().isoformat(),
        "StrkPric": row["STRIKE_PR"],
        "OptnTp": row["OPTION_TYP"],
        "NewBrdLotQty": None,   # not present pre-UDiFF -- see module docstring
        "FinInstrmId": None,    # not present pre-UDiFF
    }


def _normalize_udiff_row(row: dict) -> dict:
    return {
        "TckrSymb": row["TckrSymb"],
        "FinInstrmTp": row["FinInstrmTp"],
        "XpryDt": row["XpryDt"],
        "StrkPric": row["StrkPric"],
        "OptnTp": row["OptnTp"],
        "NewBrdLotQty": row["NewBrdLotQty"],
        "FinInstrmId": row["FinInstrmId"],
    }


def parse_fo_bhavcopy(raw_csv: str, is_legacy: bool, underlyings: set = None,
                       instrument_types: set = None) -> list:
    """
    Parse bhavcopy rows into the common normalized shape, optionally
    filtered by underlying (TckrSymb) and/or instrument type (FinInstrmTp,
    using UDiFF-style codes regardless of source era).
    """
    reader = csv.DictReader(io.StringIO(raw_csv))
    normalize = _normalize_legacy_row if is_legacy else _normalize_udiff_row
    rows = []
    for raw_row in reader:
        row = normalize(raw_row)
        if underlyings and row["TckrSymb"] not in underlyings:
            continue
        if instrument_types and row["FinInstrmTp"] not in instrument_types:
            continue
        rows.append(row)
    return rows

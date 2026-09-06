"""
Breeze historical data adapter.

Every quirk baked in here is empirically confirmed, not assumed -- see
docs/dynamic/findings.md (S-01) and
../../backtest/breeze/data_pipeline/data_fetch_script.md for the auth
pattern this preserves unmodified:

  - Breeze reads from_date/to_date HH:MM:SS as literal IST wall-clock time
    despite the trailing "Z" -- never convert to true UTC. Getting this
    wrong doesn't error, it silently truncates the request (findings.md,
    S-01, "Request-timestamp gotcha").
  - Exactly 3-digit milliseconds required in request timestamps.
  - 2 trading days is the safe 1-minute chunk size (~750 candles, under
    the ~1000/request cap).

Raw storage caveat (D-02): breeze_connect parses the HTTP response into a
Python dict before we ever see it, so what save_raw() stores is "the dict
the SDK gave us", not the exact original response bytes. This is a known,
deliberate simplification of D-02's "store exact bytes" decision -- true
byte-level capture would mean bypassing breeze_connect's request wrapper
and reimplementing its checksum/auth headers ourselves (documented and
feasible, see docs/static/breese api docs). Not done yet; revisit if a
breeze_connect parsing bug is ever suspected.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from breeze_connect import BreezeConnect

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)


def fmt(dt: datetime) -> str:
    """IST wall-clock, stamped with a cosmetic 'Z'. Breeze reads the
    digits literally -- never convert this to true UTC (see module
    docstring)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def authenticate() -> BreezeConnect:
    api_key, api_secret, api_session = os.getenv("API_KEY"), os.getenv("API_SECRET"), os.getenv("API_SESSION")
    missing = [n for n, v in [("API_KEY", api_key), ("API_SECRET", api_secret), ("API_SESSION", api_session)] if not v]
    if missing:
        print(f"FATAL: missing from flow/.env: {', '.join(missing)}. See flow/.examples.env.")
        sys.exit(1)
    breeze = BreezeConnect(api_key=api_key)
    try:
        breeze.generate_session(api_secret=api_secret, session_token=api_session)
    except Exception as e:
        print(f"FATAL: Breeze session generation failed -- token likely expired (D-49). {e}")
        sys.exit(1)
    return breeze


def _format_strike(strike: float) -> str:
    return str(int(strike)) if float(strike) == int(float(strike)) else str(strike)


def pull_option_history(breeze, underlying: str, expiry: datetime, strike: float, right: str,
                         from_dt: datetime, to_dt: datetime, interval: str = "1minute") -> dict:
    """right: 'CE' or 'PE'."""
    return breeze.get_historical_data_v2(
        interval=interval, from_date=fmt(from_dt), to_date=fmt(to_dt),
        stock_code=underlying, exchange_code="NFO", product_type="options",
        expiry_date=fmt(expiry), right="call" if right == "CE" else "put",
        strike_price=_format_strike(strike),
    )


def pull_future_history(breeze, underlying: str, expiry: datetime,
                         from_dt: datetime, to_dt: datetime, interval: str = "1minute") -> dict:
    return breeze.get_historical_data_v2(
        interval=interval, from_date=fmt(from_dt), to_date=fmt(to_dt),
        stock_code=underlying, exchange_code="NFO", product_type="futures",
        expiry_date=fmt(expiry), right="others", strike_price="0",
    )


def pull_index_history(breeze, underlying: str, from_dt: datetime, to_dt: datetime,
                        interval: str = "1minute") -> dict:
    return breeze.get_historical_data_v2(
        interval=interval, from_date=fmt(from_dt), to_date=fmt(to_dt),
        stock_code=underlying, exchange_code="NSE", product_type="cash",
    )


def save_raw(response: dict, request_meta: dict, out_path: Path) -> None:
    """D-02: raw layer, with a fetch-metadata sidecar recording exactly
    what was requested and when. See module docstring for the
    exact-bytes caveat."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "fetch_metadata": {"fetched_at": datetime.now().isoformat(), "request": request_meta},
        "response": response,
    }
    out_path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")

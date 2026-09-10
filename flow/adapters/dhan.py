"""
Dhan live-feed adapter -- REST auth/preflight, plus a thin wrapper around
the official dhanhq SDK's DhanContext/MarketFeed for the live WebSocket
feed. Mirrors adapters/breeze.py's shape (small modules behind clear
interfaces, CLAUDE.md).

Uses dhanhq's own MarketFeed class for binary packet parsing rather than a
hand-rolled parser -- there's no local Dhan doc dump with exact byte-level
packet layouts (unlike Breeze's), and guessing struct offsets risks
silently corrupting every tick. Confirmed via introspection
(inspect.getsource) that MarketFeed.process_quote/process_full return
plain dicts with LTP, LTQ, volume (cumulative day volume -- UNVERIFIED, see
live/dhan_volume_profile_recorder.py's docstring), OI, and OHLC.

This is the only file in flow/ that imports dhanhq -- NSE_FNO/FULL are
re-exported below so callers never need their own import of it.

Sends both header spellings Dhan's docs use inconsistently (access-token +
dhanClientId + client-id) -- confirmed via
experiments/s06_cross_provider_check.py and
experiments/d52_dhan_expiry_discovery_check.py.
"""

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from dhanhq import DhanContext, MarketFeed

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)

DHAN_BASE = "https://api.dhan.co/v2"

# Re-exported so callers (live/dhan_volume_profile_recorder.py) never need
# to import dhanhq directly.
NSE_FNO = MarketFeed.NSE_FNO
FULL = MarketFeed.Full


def dhan_headers(client_id: str, token: str) -> dict:
    return {
        "access-token": token,
        "dhanClientId": client_id,
        "client-id": client_id,
        "Content-Type": "application/json",
    }


def get_credentials() -> tuple:
    client_id, token = os.getenv("DHAN_CLIENT_ID"), os.getenv("DHAN_ACCESS_TOKEN")
    missing = [n for n, v in [("DHAN_CLIENT_ID", client_id), ("DHAN_ACCESS_TOKEN", token)] if not v]
    if missing:
        print(f"FATAL: missing from flow/.env: {', '.join(missing)}. See flow/.examples.env.")
        sys.exit(1)
    return client_id, token


def preflight_check(client_id: str, token: str, security_id: str, exchange_segment: str = "NSE_FNO") -> None:
    """REST auth + LTP sanity check before opening the WS feed -- not
    market-hours-gated, so this can (and should) be smoke-tested any day.
    Fatal only on the /profile auth failure; the LTP call is warning-only
    (known weekend-empty quirk, docs/dynamic/findings.md) -- ported
    unchanged from the S-03 experiment spike."""
    headers = dhan_headers(client_id, token)
    resp = requests.get(f"{DHAN_BASE}/profile", headers=headers, timeout=15)
    if resp.status_code != 200:
        print(f"FATAL: Dhan auth check failed -- status={resp.status_code} body={resp.text[:300]}")
        print("Token is valid 24h from generation; regenerate at web.dhan.co if expired.")
        sys.exit(1)
    print("Dhan REST auth OK.")

    ltp_resp = requests.post(f"{DHAN_BASE}/marketfeed/ltp", headers=headers,
                              json={exchange_segment: [int(security_id)]}, timeout=15)
    print(f"LTP preflight for security_id={security_id}: status={ltp_resp.status_code}")
    if ltp_resp.status_code == 200:
        data = ltp_resp.json()
        print(f"  {data}")
        if not data.get("data", {}).get(exchange_segment):
            print("  WARNING: empty LTP data -- known weekend caching quirk (findings.md), but "
                  "if this is during market hours on a trading day, double-check security_id before trusting the feed.")
    else:
        print(f"  WARNING: LTP preflight returned non-200 ({ltp_resp.text[:300]}) -- proceeding anyway, "
              "the WS feed is the real test, but investigate if the feed also looks empty.")


def open_market_feed(client_id: str, token: str, instruments: list,
                      on_connect=None, on_message=None, on_close=None, on_error=None,
                      version: str = "v2") -> MarketFeed:
    """instruments: [(exchange_segment_int, security_id_str, subscribe_mode_int)],
    e.g. [(NSE_FNO, "68407", FULL)]. Returns an unstarted MarketFeed --
    caller calls .start()/.close_connection()."""
    dhan_context = DhanContext(client_id, token)
    return MarketFeed(dhan_context, instruments, version=version,
                       on_connect=on_connect, on_message=on_message,
                       on_close=on_close, on_error=on_error)


if __name__ == "__main__":
    client_id, token = get_credentials()
    preflight_check(client_id, token, security_id="68407")

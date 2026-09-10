"""
Dhan live feed experiment (S-03): for one full trading day,
  1. subscribe to NIFTY's current-month future on Dhan's live WebSocket
     feed and persist every parsed tick as newline-delimited JSON -- the
     authoritative raw record, kept even if the live analytics below have
     a bug (same "never lose the raw layer" principle as D-02's Breeze
     adapters).
  2. simultaneously build a running, price-bucketed volume profile from
     LTP+LTQ deltas, and periodically snapshot it plus derived
     POC/VAH/VAL/HVN/LVN to disk.

Uses dhanhq's own MarketFeed class for the binary packet parsing rather
than a hand-rolled parser -- there's no local Dhan doc dump with exact
byte-level packet layouts (unlike Breeze's), and guessing struct offsets
from memory risks silently corrupting every tick. Confirmed via
introspection (inspect.getsource) that MarketFeed.process_quote/
process_full return plain dicts with LTP, LTQ, volume (cumulative day
volume), OI, and OHLC -- see docs/dynamic/findings.md for the exact
fields checked.

UNVERIFIED, to be confirmed live tomorrow and logged to findings.md:
  - Whether "volume" in Quote/Full packets really is cumulative day
    volume (assumed here, standard broker convention) rather than a
    per-tick figure -- if wrong, the delta computation below silently
    produces a flat/wrong profile, which is why raw ticks are logged
    unconditionally regardless of what the live profile computes.
  - Tick frequency/latency in practice, and whether a reconnect ever
    causes the cumulative volume counter to regress (handled
    defensively: negative deltas are clamped to 0 and counted, never
    subtracted from the profile).

Needs experiments/.env: DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN (see
.examples.env; token is valid 24h from generation).

Usage (run during NSE market hours, ~09:15-15:30 IST):
    .venv/Scripts/python.exe dhan_live_volume_profile.py
    .venv/Scripts/python.exe dhan_live_volume_profile.py --bucket-size 10 --security-id 68407
"""

import argparse
import json
import os
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from dhanhq import DhanContext, MarketFeed

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

LOGS_DIR = HERE / "logs" / "dhan_live"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

DHAN_BASE = "https://api.dhan.co/v2"

# NIFTY Sep-2026 future -- confirmed identical Breeze/Dhan instrument via a
# live cross-check (docs/dynamic/findings.md, s06_cross_provider_check.py).
# Correct "current month" contract through its 2026-09-29 expiry; update
# after rollover.
DEFAULT_SECURITY_ID = "68407"
EXCHANGE_SEGMENT = MarketFeed.NSE_FNO
SUBSCRIBE_MODE = MarketFeed.Full  # LTP+LTQ+volume+OI+5-level depth in one packet

VALUE_AREA_PCT = 0.70
MARKET_CLOSE = "15:30:00"


def dhan_headers(client_id: str, token: str) -> dict:
    return {"access-token": token, "dhanClientId": client_id, "client-id": client_id, "Content-Type": "application/json"}


def preflight_check(client_id: str, token: str, security_id: str):
    headers = dhan_headers(client_id, token)
    resp = requests.get(f"{DHAN_BASE}/profile", headers=headers, timeout=15)
    if resp.status_code != 200:
        print(f"FATAL: Dhan auth check failed -- status={resp.status_code} body={resp.text[:300]}")
        print("Token is valid 24h from generation; regenerate at web.dhan.co if expired.")
        sys.exit(1)
    print("Dhan REST auth OK.")

    ltp_resp = requests.post(f"{DHAN_BASE}/marketfeed/ltp", headers=headers,
                              json={"NSE_FNO": [int(security_id)]}, timeout=15)
    print(f"LTP preflight for security_id={security_id}: status={ltp_resp.status_code}")
    if ltp_resp.status_code == 200:
        data = ltp_resp.json()
        print(f"  {data}")
        if not data.get("data", {}).get("NSE_FNO"):
            print("  WARNING: empty LTP data -- known weekend caching quirk (findings.md), but "
                  "if this is during market hours on a trading day, double-check security_id before trusting the feed.")
    else:
        print(f"  WARNING: LTP preflight returned non-200 ({ltp_resp.text[:300]}) -- proceeding anyway, "
              "the WS feed is the real test, but investigate if the feed also looks empty.")


class VolumeProfile:
    def __init__(self, bucket_size: float):
        self.bucket_size = bucket_size
        self.volumes = defaultdict(int)
        self.lock = threading.Lock()

    def bucket_of(self, price: float) -> float:
        return round(price / self.bucket_size) * self.bucket_size

    def add(self, price: float, qty: int):
        if qty <= 0:
            return
        b = self.bucket_of(price)
        with self.lock:
            self.volumes[b] += qty

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.volumes)


def compute_poc(volumes: dict):
    return max(volumes.items(), key=lambda kv: kv[1])[0] if volumes else None


def compute_value_area(volumes: dict, poc, pct: float = VALUE_AREA_PCT):
    if not volumes or poc is None:
        return None, None
    prices = sorted(volumes)
    total = sum(volumes.values())
    target = total * pct
    idx = prices.index(poc)
    lo, hi = idx, idx
    acc = volumes[poc]
    while acc < target and (lo > 0 or hi < len(prices) - 1):
        below = volumes[prices[lo - 1]] if lo > 0 else -1
        above = volumes[prices[hi + 1]] if hi < len(prices) - 1 else -1
        if above >= below:
            hi += 1
            acc += volumes[prices[hi]]
        else:
            lo -= 1
            acc += volumes[prices[lo]]
    return prices[lo], prices[hi]  # VAL, VAH


def compute_hvn_lvn(volumes: dict, min_prominence_pct: float = 0.05):
    """Local maxima/minima in the profile. A node must differ from both
    neighbors by at least min_prominence_pct of the profile's max volume
    to count -- filters tick-level noise from genuine nodes."""
    if len(volumes) < 3:
        return [], []
    prices = sorted(volumes)
    vols = [volumes[p] for p in prices]
    threshold = max(vols) * min_prominence_pct
    hvn, lvn = [], []
    for i in range(1, len(prices) - 1):
        v, left, right = vols[i], vols[i - 1], vols[i + 1]
        if v > left and v > right and (v - max(left, right)) >= threshold:
            hvn.append(prices[i])
        elif v < left and v < right and (min(left, right) - v) >= threshold:
            lvn.append(prices[i])
    return hvn, lvn


class TickLogger:
    """Every parsed message, unconditionally, as newline-delimited JSON --
    the authoritative raw record regardless of what the live profile does
    with it."""

    def __init__(self, path: Path):
        self.f = open(path, "a", encoding="utf-8")
        self.lock = threading.Lock()

    def write(self, record: dict):
        with self.lock:
            self.f.write(json.dumps(record, default=str) + "\n")
            self.f.flush()

    def close(self):
        self.f.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--security-id", default=DEFAULT_SECURITY_ID)
    ap.add_argument("--bucket-size", type=float, default=5.0, help="volume-profile price bucket width, in index points")
    ap.add_argument("--snapshot-interval", type=int, default=30, help="seconds between profile snapshots")
    args = ap.parse_args()

    client_id, token = os.getenv("DHAN_CLIENT_ID"), os.getenv("DHAN_ACCESS_TOKEN")
    if not client_id or not token:
        print("FATAL: DHAN_CLIENT_ID/DHAN_ACCESS_TOKEN missing from experiments/.env (see .examples.env).")
        sys.exit(1)

    preflight_check(client_id, token, args.security_id)

    today = datetime.now().strftime("%Y-%m-%d")
    tick_log_path = LOGS_DIR / f"nifty_fut_{args.security_id}_{today}_ticks.jsonl"
    snapshot_path = LOGS_DIR / f"nifty_fut_{args.security_id}_{today}_profile_snapshots.jsonl"
    tick_logger = TickLogger(tick_log_path)
    profile = VolumeProfile(args.bucket_size)
    state = {"last_volume": None, "ticks_seen": 0, "profile_ticks": 0, "negative_deltas": 0}

    def on_message(feed_instance, data):
        state["ticks_seen"] += 1
        tick_logger.write({"received_at": datetime.now().isoformat(), **data})

        if data.get("type") in ("Full Data", "Quote Data"):
            try:
                ltp = float(data["LTP"])
                cum_vol = int(data["volume"])
            except (KeyError, ValueError, TypeError):
                return
            last = state["last_volume"]
            delta = 0 if last is None else cum_vol - last
            if delta < 0:
                state["negative_deltas"] += 1
                delta = 0
            state["last_volume"] = cum_vol
            if delta > 0:
                profile.add(ltp, delta)
                state["profile_ticks"] += 1

    def on_connect(_feed):
        print(f"[{datetime.now().isoformat()}] Connected and subscribed (security_id={args.security_id}, mode=Full).")

    def on_error(_feed, error):
        print(f"[{datetime.now().isoformat()}] WS error: {error}")

    def on_close(_feed):
        print(f"[{datetime.now().isoformat()}] Connection closed.")

    dhan_context = DhanContext(client_id, token)
    instruments = [(EXCHANGE_SEGMENT, args.security_id, SUBSCRIBE_MODE)]
    feed = MarketFeed(dhan_context, instruments, version="v2",
                       on_connect=on_connect, on_message=on_message, on_close=on_close, on_error=on_error)

    feed.start()  # runs feed.run() in a background thread
    print(f"Feed thread started. Raw ticks -> {tick_log_path}")
    print(f"Profile snapshots every {args.snapshot_interval}s -> {snapshot_path}")

    snapshot_file = open(snapshot_path, "a", encoding="utf-8")
    try:
        while True:
            if datetime.now().strftime("%H:%M:%S") >= MARKET_CLOSE:
                print(f"[{datetime.now().isoformat()}] Market close reached, stopping.")
                break

            time.sleep(args.snapshot_interval)
            volumes = profile.snapshot()
            poc = compute_poc(volumes)
            val, vah = compute_value_area(volumes, poc)
            hvn, lvn = compute_hvn_lvn(volumes)
            snap = {
                "ts": datetime.now().isoformat(),
                "ticks_seen": state["ticks_seen"], "profile_ticks": state["profile_ticks"],
                "negative_deltas": state["negative_deltas"],
                "total_volume_in_profile": sum(volumes.values()), "distinct_buckets": len(volumes),
                "poc": poc, "val": val, "vah": vah, "hvn": hvn, "lvn": lvn,
                "profile": volumes,
            }
            snapshot_file.write(json.dumps(snap, default=str) + "\n")
            snapshot_file.flush()
            hvn_s = f"{hvn[:3]}{'...' if len(hvn) > 3 else ''}"
            lvn_s = f"{lvn[:3]}{'...' if len(lvn) > 3 else ''}"
            print(f"[{snap['ts']}] ticks={state['ticks_seen']} profile_ticks={state['profile_ticks']} "
                  f"neg_deltas={state['negative_deltas']} POC={poc} VAL={val} VAH={vah} HVN={hvn_s} LVN={lvn_s}")
    except KeyboardInterrupt:
        print("Interrupted, shutting down.")
    finally:
        feed.close_connection()
        tick_logger.close()
        snapshot_file.close()
        print(f"Done. Ticks seen: {state['ticks_seen']}, negative deltas clamped: {state['negative_deltas']}")


if __name__ == "__main__":
    main()

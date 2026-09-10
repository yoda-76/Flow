"""
Live recorder (D-37): subscribes to one instrument's Dhan WS feed, persists
every parsed tick unconditionally as raw NDJSON (D-02's raw-layer
principle -- never lost even if the live feature computation has a bug),
and periodically builds+snapshots a features/volume_profile.py feature
record (D-22) from LTP+LTQ deltas.

v1 scope: single instrument only (NIFTY current-month future). D-37's "one
recorder process handling all subscribed instruments" and its "compacted
to columnar after market close" step are deliberately NOT built here --
there is no second live-feed case yet to shape that generality against
(CLAUDE.md: don't over-abstract ahead of a second real case), and
post-close compaction is a separate follow-up once the raw NDJSON shape
has been validated against a real trading day. This is a documented,
deliberate narrowing of D-37, not an oversight.

UNVERIFIED, to be confirmed live and logged to findings.md (ported
unchanged from experiments/dhan_live_volume_profile.py's S-03 spike):
  - Whether "volume" in Quote/Full packets really is cumulative day volume
    (assumed here, standard broker convention) rather than a per-tick
    figure -- if wrong, delta computation silently produces a flat/wrong
    profile, which is why raw ticks are logged unconditionally regardless
    of what the live profile computes.
  - Tick frequency/latency in practice, and whether a reconnect ever
    causes the cumulative volume counter to regress (handled defensively:
    CumulativeVolumeDeltaTracker clamps negative deltas to 0 and counts
    them, never subtracts from the profile).

Needs flow/.env: DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN (see flow/.examples.env
-- already documented there, no env-file changes needed).

Usage (run during NSE market hours, ~09:15-15:30 IST):
    .venv/Scripts/python.exe -m live.dhan_volume_profile_recorder
    .venv/Scripts/python.exe -m live.dhan_volume_profile_recorder --tick-multiple 20 --security-id 68407
"""

import argparse
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from adapters.dhan import FULL, NSE_FNO, get_credentials, open_market_feed, preflight_check  # noqa: E402
from features.volume_profile import (  # noqa: E402
    FEATURE_VERSION, VolumeProfile, VolumeProfileConfig, build_snapshot,
)

RAW_ROOT = Path(__file__).resolve().parent.parent / "data" / "raw" / "dhan" / "live" / "trades"
FEATURE_ROOT = Path(__file__).resolve().parent.parent / "data" / "features" / "volume_profile"

# NIFTY Sep-2026 future -- cross-validated against Breeze's own token
# (docs/dynamic/findings.md S-06, experiments/s06_cross_provider_check.py).
# Correct "current month" contract through its 2026-09-29 expiry; update
# after rollover. Not sourced from rules.store.MarketRulesStore.front_contract()
# -- that needs a live trading date already reflected in the instrument
# master, and this recorder runs same-day; tracked as a follow-up, not
# silently left as a bare magic number.
DEFAULT_SECURITY_ID = "68407"
DEFAULT_UNDERLYING = "NIFTY"
DEFAULT_EXPIRY = "2026-09-29"

# NIFTY index/futures tick size -- stable NSE-wide constant. Not sourced
# from instrument_master.parquet (no tick_size field yet, confirmed by
# direct inspection when this module was written -- see
# features/volume_profile.py's docstring). Explicit here, not buried
# inside the feature engine.
NIFTY_TICK_SIZE = 0.05

MARKET_CLOSE = "15:30:00"


class CumulativeVolumeDeltaTracker:
    """Converts Dhan's cumulative day-volume field into per-tick deltas.
    Negative deltas (reconnect glitches, or the cumulative-volume
    assumption being wrong) are clamped to 0 and counted rather than fed
    to the profile -- ported unchanged from the S-03 experiment spike."""

    def __init__(self):
        self.last_volume = None
        self.negative_deltas = 0

    def delta(self, cum_vol: int) -> int:
        last = self.last_volume
        d = 0 if last is None else cum_vol - last
        if d < 0:
            self.negative_deltas += 1
            d = 0
        self.last_volume = cum_vol
        return d


class TickLogger:
    """Every parsed message, unconditionally, as newline-delimited JSON --
    the authoritative raw record regardless of what the live profile does
    with it."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(path, "a", encoding="utf-8")
        self.lock = threading.Lock()

    def write(self, record: dict) -> None:
        with self.lock:
            self.f.write(json.dumps(record, default=str) + "\n")
            self.f.flush()

    def close(self) -> None:
        self.f.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--security-id", default=DEFAULT_SECURITY_ID)
    ap.add_argument("--underlying", default=DEFAULT_UNDERLYING)
    ap.add_argument("--expiry", default=DEFAULT_EXPIRY)
    ap.add_argument("--tick-size", type=float, default=NIFTY_TICK_SIZE)
    ap.add_argument("--tick-multiple", type=int, default=100,
                     help="bucket width = tick_multiple * tick_size; default 100*0.05=5.0 points")
    ap.add_argument("--value-area-pct", type=float, default=0.70)
    ap.add_argument("--hvn-lvn-window", type=int, default=5)
    ap.add_argument("--hvn-threshold", type=float, default=1.5)
    ap.add_argument("--lvn-threshold", type=float, default=0.5)
    ap.add_argument("--snapshot-interval", type=int, default=30, help="seconds between profile snapshots")
    args = ap.parse_args()

    client_id, token = get_credentials()
    preflight_check(client_id, token, args.security_id)

    config = VolumeProfileConfig(
        tick_size=args.tick_size, tick_multiple=args.tick_multiple,
        value_area_pct=args.value_area_pct, hvn_lvn_window=args.hvn_lvn_window,
        hvn_threshold=args.hvn_threshold, lvn_threshold=args.lvn_threshold,
    )

    today = datetime.now().strftime("%Y-%m-%d")
    tick_log_path = RAW_ROOT / args.underlying / args.expiry / f"{today}_ticks.jsonl"
    snapshot_path = FEATURE_ROOT / FEATURE_VERSION / args.underlying / args.expiry / f"{today}_snapshots.jsonl"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    tick_logger = TickLogger(tick_log_path)
    profile = VolumeProfile(config)
    delta_tracker = CumulativeVolumeDeltaTracker()
    instrument_id = f"NSE|{args.underlying}|{args.expiry}|FUT"
    state = {"ticks_seen": 0, "profile_ticks": 0}

    def on_message(feed_instance, data):
        state["ticks_seen"] += 1
        tick_logger.write({"received_at": datetime.now().isoformat(), **data})
        if data.get("type") in ("Full Data", "Quote Data"):
            try:
                ltp = float(data["LTP"])
                cum_vol = int(data["volume"])
            except (KeyError, ValueError, TypeError):
                return
            d = delta_tracker.delta(cum_vol)
            if d > 0:
                profile.add(ltp, d)
                state["profile_ticks"] += 1

    def on_connect(_feed):
        print(f"[{datetime.now().isoformat()}] Connected (security_id={args.security_id}).")

    def on_error(_feed, error):
        print(f"[{datetime.now().isoformat()}] WS error: {error}")

    def on_close(_feed):
        print(f"[{datetime.now().isoformat()}] Connection closed.")

    feed = open_market_feed(client_id, token,
                             [(NSE_FNO, args.security_id, FULL)],
                             on_connect=on_connect, on_message=on_message,
                             on_close=on_close, on_error=on_error)
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
            snap = build_snapshot(volumes, config, ts=datetime.now().isoformat(), extra={
                "instrument_id": instrument_id,
                "security_id": args.security_id,
                "ticks_seen": state["ticks_seen"],
                "profile_ticks": state["profile_ticks"],
                "negative_deltas": delta_tracker.negative_deltas,
            })
            snapshot_file.write(json.dumps(snap, default=str) + "\n")
            snapshot_file.flush()
            hvn_s = f"{snap['hvn'][:3]}{'...' if len(snap['hvn']) > 3 else ''}"
            lvn_s = f"{snap['lvn'][:3]}{'...' if len(snap['lvn']) > 3 else ''}"
            print(f"[{snap['ts']}] ticks={state['ticks_seen']} profile_ticks={state['profile_ticks']} "
                  f"neg_deltas={delta_tracker.negative_deltas} POC={snap['poc']} VAL={snap['val']} "
                  f"VAH={snap['vah']} HVN={hvn_s} LVN={lvn_s}")
    except KeyboardInterrupt:
        print("Interrupted, shutting down.")
    finally:
        feed.close_connection()
        tick_logger.close()
        snapshot_file.close()
        print(f"Done. Ticks seen: {state['ticks_seen']}, negative deltas clamped: {delta_tracker.negative_deltas}")


if __name__ == "__main__":
    main()

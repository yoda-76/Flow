"""
Volume profile feature engine (D-22). Feed-agnostic: operates purely on a
{price_bucket: volume} snapshot, however it was built (live tick deltas
today; D-08's native 1-second index/futures bars, or D-22's
uniform-intrabar-spread for 1-minute options, later). Never imports
anything live-feed-specific -- that lives in live/dhan_volume_profile_recorder.py.

D-22 corrections made when porting from experiments/dhan_live_volume_profile.py's
S-03 spike (that script's version does NOT match the decided algorithm; do
not copy its bucket-sizing or HVN/LVN logic):

  1. Bin sizing: D-22 requires bin width as a FIXED TICK MULTIPLE of the
     instrument's tick size, not a bare float. VolumeProfileConfig.tick_size
     has no default -- every caller must supply it explicitly. There is no
     tick_size field in flow/data/reference/instrument_master.parquet yet
     (checked directly), so for v1 the caller (live/dhan_volume_profile_recorder.py)
     documents it as a named constant near its other instrument constants,
     not buried in this module.

  2. HVN/LVN: D-22 requires "a relative-volume threshold against a rolling
     local average" -- a bin is HVN if its volume is >= hvn_threshold times
     the average volume of its `window` neighboring bins on each side
     (excluding itself), LVN if <= lvn_threshold times that average. This
     replaces the experiment spike's local-peak/trough detection (comparing
     each bin only to its immediate left/right neighbor), which is a
     different, simpler algorithm that D-22 does not specify. This is a
     genuine reimplementation, not a copy-paste.

FEATURE_VERSION is bumped whenever the algorithm (not just config values)
changes, per D-16 (version pinned explicitly in table/path name) --
callers pin snapshot storage paths under this constant.
"""

import threading
from collections import defaultdict
from dataclasses import asdict, dataclass

FEATURE_VERSION = "volume_profile_v1"


@dataclass(frozen=True)
class VolumeProfileConfig:
    tick_size: float                 # instrument tick size -- REQUIRED, no default (see module docstring)
    tick_multiple: int = 100         # bucket width = tick_multiple * tick_size
    value_area_pct: float = 0.70     # D-22: "standard 70% value area"
    hvn_lvn_window: int = 5          # bins considered on each side for the rolling local average
    hvn_threshold: float = 1.5       # bin.volume >= hvn_threshold * rolling_avg -> HVN
    lvn_threshold: float = 0.5       # bin.volume <= lvn_threshold * rolling_avg -> LVN
    min_bins_for_hvn_lvn: int = 3    # fewer distinct bins than this -> skip HVN/LVN, don't guess

    def __post_init__(self):
        if self.tick_size <= 0:
            raise ValueError(f"tick_size must be positive, got {self.tick_size}")
        if self.tick_multiple <= 0:
            raise ValueError(f"tick_multiple must be positive, got {self.tick_multiple}")
        if self.hvn_lvn_window <= 0:
            raise ValueError(f"hvn_lvn_window must be positive, got {self.hvn_lvn_window}")

    @property
    def bucket_size(self) -> float:
        return self.tick_multiple * self.tick_size

    def as_dict(self) -> dict:
        return asdict(self)


class VolumeProfile:
    """Thread-safe running price-bucketed volume accumulator."""

    def __init__(self, config: VolumeProfileConfig):
        self.config = config
        self._volumes = defaultdict(int)
        self._lock = threading.Lock()

    def bucket_of(self, price: float) -> float:
        b = self.config.bucket_size
        return round(price / b) * b

    def add(self, price: float, qty: int) -> None:
        if qty <= 0:
            return
        bucket = self.bucket_of(price)
        with self._lock:
            self._volumes[bucket] += qty

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._volumes)


def compute_poc(volumes: dict):
    """Point of control -- the bin with the single highest volume."""
    return max(volumes.items(), key=lambda kv: kv[1])[0] if volumes else None


def compute_value_area(volumes: dict, poc, value_area_pct: float = 0.70):
    """Standard value-area expansion from POC: repeatedly add whichever
    neighboring bin (above or below the current range) has more volume,
    until value_area_pct of total volume is captured. Returns (VAL, VAH)."""
    if not volumes or poc is None:
        return None, None
    prices = sorted(volumes)
    total = sum(volumes.values())
    target = total * value_area_pct
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
    return prices[lo], prices[hi]


def compute_rolling_local_average(vols: list, window: int) -> list:
    """For each index i, the mean of vols[i]'s up-to-`window` neighbors on
    each side (excluding vols[i] itself). Edge bins use whatever fewer
    neighbors exist -- asymmetric window, never wraps around. This is the
    "rolling local average" D-22 requires HVN/LVN to be measured against."""
    n = len(vols)
    out = []
    for i in range(n):
        neighbors = vols[max(0, i - window):i] + vols[i + 1:i + 1 + window]
        out.append(sum(neighbors) / len(neighbors) if neighbors else 0.0)
    return out


def compute_hvn_lvn(volumes: dict, window: int = 5, hvn_threshold: float = 1.5,
                     lvn_threshold: float = 0.5, min_bins: int = 3):
    """D-22's method: relative-volume threshold against a rolling local
    average, NOT local-peak/trough detection (see module docstring). A bin
    whose rolling_avg == 0 (empty neighborhood) is only ever eligible for
    HVN (any positive volume there is locally exceptional by definition) --
    never flagged LVN, avoiding a divide-by-zero-shaped false positive on a
    mostly-empty profile."""
    if len(volumes) < min_bins:
        return [], []
    prices = sorted(volumes)
    vols = [volumes[p] for p in prices]
    rolling_avg = compute_rolling_local_average(vols, window)
    hvn, lvn = [], []
    for price, v, avg in zip(prices, vols, rolling_avg):
        if avg == 0:
            if v > 0:
                hvn.append(price)
            continue
        if v >= hvn_threshold * avg:
            hvn.append(price)
        elif v <= lvn_threshold * avg:
            lvn.append(price)
    return hvn, lvn


def build_snapshot(volumes: dict, config: VolumeProfileConfig, ts: str, extra: dict = None) -> dict:
    """The one function a caller (live or historical) actually needs.
    Bundles feature_version + the exact config used -- per
    docs/static/08-market-abstraction.md's "feature version that records
    which config produced the series" convention -- so no parameter is
    ever an unlabeled magic number in stored output. `extra` should carry
    instrument identity (instrument_id/security_id) -- directory structure
    must never be the sole source of identity (03-design-options.md
    principle #14)."""
    poc = compute_poc(volumes)
    val, vah = compute_value_area(volumes, poc, config.value_area_pct)
    hvn, lvn = compute_hvn_lvn(volumes, config.hvn_lvn_window, config.hvn_threshold,
                                config.lvn_threshold, config.min_bins_for_hvn_lvn)
    return {
        "ts": ts,
        "feature_version": FEATURE_VERSION,
        "config": config.as_dict(),
        "poc": poc, "val": val, "vah": vah, "hvn": hvn, "lvn": lvn,
        "total_volume": sum(volumes.values()), "distinct_buckets": len(volumes),
        "profile": volumes,
        **(extra or {}),
    }


if __name__ == "__main__":
    cfg = VolumeProfileConfig(tick_size=0.05, tick_multiple=100)  # 5.0-point buckets
    assert cfg.bucket_size == 5.0

    vp = VolumeProfile(cfg)
    for price, qty in [(24998, 10), (25000, 50), (25000, 30), (25005, 5), (24990, 1)]:
        vp.add(price, qty)
    volumes = vp.snapshot()
    poc = compute_poc(volumes)
    assert poc == 25000, poc
    val, vah = compute_value_area(volumes, poc, cfg.value_area_pct)
    assert val is not None and vah is not None and val <= poc <= vah

    # Synthetic profile with one clear spike bin and one clear trough bin --
    # the rolling-local-average method must flag both; this specifically
    # exercises the D-22 correction, not the old local-peak logic.
    synthetic = {float(i): 100 for i in range(20)}
    synthetic[10.0] = 400
    synthetic[15.0] = 10
    hvn, lvn = compute_hvn_lvn(synthetic, window=5, hvn_threshold=1.5, lvn_threshold=0.5, min_bins=3)
    assert 10.0 in hvn and 15.0 not in hvn, (hvn, lvn)
    assert 15.0 in lvn and 10.0 not in lvn, (hvn, lvn)

    # Flat profile -- nothing should qualify as HVN or LVN.
    flat = {float(i): 100 for i in range(20)}
    hvn_flat, lvn_flat = compute_hvn_lvn(flat, window=5, hvn_threshold=1.5, lvn_threshold=0.5, min_bins=3)
    assert hvn_flat == [] and lvn_flat == [], (hvn_flat, lvn_flat)

    # Too few bins -- skip rather than guess.
    assert compute_hvn_lvn({1.0: 5, 2.0: 5}, min_bins=3) == ([], [])

    snap = build_snapshot(volumes, cfg, ts="2026-09-10T10:00:00")
    assert snap["feature_version"] == FEATURE_VERSION
    assert snap["config"]["tick_size"] == 0.05

    print("All self-tests passed.")

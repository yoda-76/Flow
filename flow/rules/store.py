"""
Read-side accessors for the instrument master and expiry calendar built by
build_instrument_master.py.

Two different kinds of lookup, deliberately not conflated (see that
module's docstring for why):

  - Contract-specific facts (lot size, tick size, strike, multiplier) --
    always looked up by instrument_id directly against the instrument
    master. Exact, no ambiguity, no "as of" needed beyond picking the
    right row if a single contract's own spec ever has multiple periods.

  - Genuinely date-only facts (expiry existence/ordering) -- looked up via
    rules_as_of(), the D-51 accessor. This is what D-51 was actually for:
    NIFTY's expiry weekday has shifted more than once, so "front expiry as
    of date t" cannot be computed from a rule, only looked up from real
    observed data (D-52).
"""

from datetime import date, datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = HERE.parent / "data" / "reference"


def _to_date(v) -> date:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, str):
        return date.fromisoformat(v)
    return pd.Timestamp(v).date()


class MarketRulesStore:
    def __init__(self, data_dir: Path = DEFAULT_DATA_DIR):
        self.data_dir = Path(data_dir)
        self._instruments = None
        self._expiries = None

    @property
    def instruments(self) -> pd.DataFrame:
        if self._instruments is None:
            df = pd.read_parquet(self.data_dir / "instrument_master.parquet")
            df["valid_from"] = df["valid_from"].apply(_to_date)
            df["valid_to"] = df["valid_to"].apply(_to_date)
            self._instruments = df
        return self._instruments

    @property
    def expiries(self) -> pd.DataFrame:
        if self._expiries is None:
            df = pd.read_parquet(self.data_dir / "expiry_calendar.parquet")
            df["expiry"] = df["expiry"].apply(_to_date)
            df["first_seen"] = df["first_seen"].apply(_to_date)
            self._expiries = df
        return self._expiries

    def get_instrument(self, instrument_id: str, t: date | None = None) -> dict | None:
        """Exact contract-specific facts (lot size, strike, expiry, ...)
        for one instrument_id. If the contract had more than one spec
        period (shouldn't happen for lot size in practice, kept general),
        pass t to pick the period valid at that date; otherwise the most
        recent period is returned."""
        rows = self.instruments[self.instruments["instrument_id"] == instrument_id]
        if rows.empty:
            return None
        if t is not None:
            rows = rows[(rows["valid_from"] <= t) & (rows["valid_to"] >= t)]
            if rows.empty:
                return None
        return rows.sort_values("valid_to").iloc[-1].to_dict()

    def front_contract(self, underlying: str, t: date, instrument_type: str = "IDF") -> str | None:
        """The front-month/front-week contract instrument_id actually
        trading on date t -- nearest expiry >= t among contracts of this
        underlying/instrument_type whose observed [valid_from, valid_to]
        covers t. A pure function of the instrument master (no separate
        rollover rule needed: "front" just means nearest live expiry).
        Returns None if nothing of this type was trading on t."""
        inst = self.instruments
        t_iso = t.isoformat()
        candidates = inst[
            (inst["underlying"] == underlying) & (inst["instrument_type"] == instrument_type)
            & (inst["valid_from"] <= t) & (inst["valid_to"] >= t) & (inst["expiry"] >= t_iso)
        ]
        if candidates.empty:
            return None
        return candidates.sort_values("expiry").iloc[0]["instrument_id"]

    def rules_as_of(self, market: str, underlying: str, t: date, rule_type: str = "expiry",
                     instrument_type: str = "IDO", n: int = 1) -> list:
        """
        The D-51 accessor. Currently supports rule_type="expiry": returns
        the next `n` real, observed expiry dates >= t for this
        underlying/instrument_type, ordered soonest-first (expiries[0] is
        the "front" expiry as of t). Sourced from the expiry calendar
        (D-52), never computed from a weekday rule -- NIFTY's expiry
        weekday has changed historically, so a computed rule would be
        wrong for part of any multi-year backtest.
        """
        if rule_type != "expiry":
            raise NotImplementedError(
                f"rule_type={rule_type!r} not yet supported -- only 'expiry' exists so far. "
                "Genuinely date-only rules (session hours, cost/tax rates) belong here once "
                "we have a data source for them; lot size deliberately does not (see "
                "build_instrument_master.py's docstring)."
            )
        if market != "NSE":
            raise ValueError(f"unsupported market {market!r} -- NSE only for now (D-54)")

        df = self.expiries
        candidates = df[(df["underlying"] == underlying) & (df["instrument_type"] == instrument_type)
                         & (df["expiry"] >= t)]
        return sorted(candidates["expiry"].unique())[:n]


def _has_overlap(group: pd.DataFrame) -> bool:
    g = group.sort_values("valid_from")
    return (g["valid_from"].iloc[1:].reset_index(drop=True)
            <= g["valid_to"].iloc[:-1].reset_index(drop=True)).any()


def validate(store: MarketRulesStore) -> list:
    """Plain-Python sanity checks (D-44) -- run after every build.

    An instrument_id having multiple rows is expected (a lot-size change
    mid-life, or a delist/relist token change -- both confirmed real,
    2026-09-06) -- that's not a duplicate. The actual correctness
    requirement is that its periods never *overlap*."""
    issues = []
    inst = store.instruments
    overlapping = [iid for iid, g in inst.groupby("instrument_id") if len(g) > 1 and _has_overlap(g)]
    if overlapping:
        issues.append(f"CRITICAL: {len(overlapping)} instrument_ids have overlapping valid_from/valid_to periods: {overlapping[:5]}")
    if (inst["lot_size"] <= 0).any():
        issues.append(f"CRITICAL: {(inst['lot_size'] <= 0).sum()} rows with non-positive lot_size")
    null_lot = inst["lot_size"].isna().sum()
    if null_lot:
        # Legitimate for contracts that existed and expired entirely within
        # the pre-UDiFF legacy era, which has no lot-size column at all --
        # not backfillable (build_instrument_master.py's docstring).
        issues.append(f"WARNING: {null_lot} rows with no known lot_size (expected for legacy-era-only contracts, not backfillable)")
    bad_periods = inst[inst["valid_from"] > inst["valid_to"]]
    if not bad_periods.empty:
        issues.append(f"CRITICAL: {len(bad_periods)} rows with valid_from after valid_to")

    exp = store.expiries
    if exp.duplicated(subset=["underlying", "instrument_type", "expiry"]).any():
        issues.append("CRITICAL: duplicate (underlying, instrument_type, expiry) rows in expiry calendar")

    return issues


if __name__ == "__main__":
    store = MarketRulesStore()
    issues = validate(store)
    if issues:
        print(f"{len(issues)} validation issue(s):")
        for i in issues:
            print(" ", i)
    else:
        print("Validation clean.")

    front = store.rules_as_of("NSE", "NIFTY", date.today(), n=3)
    print(f"\nNext 3 NIFTY option expiries as of {date.today()}: {front}")

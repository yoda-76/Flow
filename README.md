# FLOW

A research platform for turning discretionary NSE trading judgment — market
structure, VWAP, volume profile, footprint, options Greeks, GEX — into
measurable, versioned, backtestable rules, and eventually a live-tradable
system.

Not a backtester and not a charting tool. The point is turning a sentence
like *"price reacted at an important level, structure turned bullish"* into
something a computer can evaluate the same way every time — and keeping
every step between raw market data and a trade decision inspectable and
reproducible.

## Where things stand

Early stage: this is architecture and data-layer work, not a working
trading system yet. Nothing in the feature layer (volume profile, footprint,
delta, GEX) is built — those are specified and decided, not written.

What *is* built is the bottom of the stack:

- **Breeze historical adapters** for index, futures and NIFTY front-weekly
  option chains, with the request-chunking and auth quirks that were
  confirmed empirically rather than read off the docs.
- **Canonical layer** — long-form schema, normalization from raw Breeze
  responses, and idempotent Parquet writes partitioned by
  `(instrument_type, year, month)`.
- **Instrument master and expiry calendar**, built from NSE F&O bhavcopy
  history across both the legacy and UDiFF formats, with a time-versioned
  accessor for the facts that genuinely can't be computed from a rule.

A lot of what's here so far is *verification* rather than building —
actually testing what Breeze's and Dhan's APIs (and third-party libraries
like NautilusTrader) really do, rather than trusting their docs. That's
found several real, undocumented bugs and quirks along the way; see
`docs/dynamic/findings.md` for the running record.

## Repo layout

- **`docs/static/`** — the original design doc set, `00` through `08`.
  Start at `00-START-HERE.md` — it explains the reading order and the one
  fixed architectural constraint everything else is built around:
  `RAW → CANONICAL → FEATURES → MARKET STATE → STRATEGY → EXECUTION`.
  This is the fixed reference point; it doesn't change as decisions get
  made, and it's a bit stale by now in the sense that a lot of what it
  poses as open questions has since been answered — see the next bullet.
- **`docs/dynamic/`** — the actual working record, and the more
  up-to-date place to look:
  - `decisions.md` — closed architectural decisions, one per question the
    static docs left open. 55 of them so far, each with a date, a
    rationale, and a link to the evidence it rests on.
  - `findings.md` — the empirical evidence behind them: what was actually
    tested against a live API or an independent reference, tagged `[DOC]`,
    `[LIVE]` or `[CODE]` by how strong the evidence is.
  - `nautilus_checklist.md` — ongoing sanity-testing of a third-party
    trading engine (NautilusTrader) being evaluated for adoption.
- **`experiments/`** — small, throwaway scripts that answer one empirical
  question each (does this field actually populate, does this library
  actually compute what it claims). Not production code — the answers they
  produce end up in `findings.md`.
- **`flow/`** — the actual system, built incrementally as the architecture
  solidifies. Three modules so far, mirroring the layer model (D-42); see
  below.
- **`SecurityMaster/`** — raw NSE/Breeze instrument listing reference
  dumps.
- **`CLAUDE.md`** — working rules for how this repo gets built with an AI
  assistant in the loop. Mostly relevant if you're doing the same.

## What's in `flow/` today

```
flow/
  adapters/     RAW        Breeze client, chunking, index/futures/options downloads
  canonical/    CANONICAL  schema, normalization, partitioned Parquet writes
  rules/        —          bhavcopy access, instrument master, time-versioned lookups
```

**`adapters/`** — `breeze.py` wraps the Breeze historical endpoints with the
quirks that were confirmed live, not assumed: `from_date`/`to_date` are read
as literal IST wall-clock despite the trailing `Z` (getting this wrong
truncates the request silently rather than erroring), exactly three-digit
milliseconds are required, and two trading days is the safe 1-minute chunk
size under the ~1000-candle cap. `chunking.py` implements that pairing
without hardcoding weekday-of-week, since NIFTY's expiry weekday has shifted
historically. `download_options.py` is built to run in daily installments
against Breeze's ~5,000 requests/day cap and a session token that expires
daily, and is resumable across runs.

**`canonical/`** — one long-form table for all instrument types
(`timestamp, instrument_id, o, h, l, c, v, oi`), timestamps tz-aware
Asia/Kolkata and bar-labelled by open, every record carrying
source/ingest-time/dataset-version provenance. Writes merge and dedupe on
`(timestamp, instrument_id)`, so re-running a build over an overlapping date
range is safe.

**`rules/`** — the instrument master is built from NSE bhavcopy across both
the pre-2024-07-08 legacy format and the UDiFF format that replaced it,
normalized into one row shape. The store deliberately separates
contract-specific facts (lot size, tick size, strike), which are looked up
exactly by `instrument_id`, from genuinely date-only facts (expiry existence
and ordering), which are looked up "as of" a date because they can't be
computed — NIFTY's expiry weekday has moved more than once.

## The core habit worth noticing

Nothing gets trusted just because it's documented — not the exchange's own
broker APIs, not well-established open-source libraries. Everything gets
checked against a real API response or an independent reference
implementation first. `docs/dynamic/findings.md` is the running log of
what that turned up.

Two examples of why this is worth the time:

- Breeze's PyPI page and its own API reference **disagree with each other**
  about whether 1-second historical data is retrievable over REST. A live
  call settled it before any decision was allowed to depend on it.
- Lot-size revisions aren't clean date cutovers. During a transition,
  already-listed contracts keep their original lot size while newly-listed
  ones get the new one, for a multi-week window. A date-keyed rule table
  can't represent that honestly, so there isn't one.

## Roadmap

Next, in order (D-47): a trivial futures strategy end-to-end to prove the
layering works, then GEX reversal, then order flow last. Order flow
constructs are validated forward only — no historical approximation
(D-46), since tick-level history at that granularity isn't something this
project sources or stores.

## Notes

Personal research project, built alongside full-time work as a developer at
a brokerage. Not affiliated with my employer, and it uses no proprietary
data or code. Not investment advice.

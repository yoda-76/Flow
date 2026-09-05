# Decisions — closed answers only

This file records decisions we've actually made, separately from the
reference doc set (`00`–`08`), which stays untouched. It mirrors the decision
IDs (`D-xx`) in `05-decision-register.md` — read that file for the options
and considerations behind each one; this file only records the outcome.

Companion file: `findings.md` holds the empirical/documentary evidence
(mirrors the `S-xx` spikes in `06-spikes.md`) that decisions here are based
on. Evidence accumulates continuously and gets superseded; decisions are
recorded once and linked back to the evidence that justified them at the
time. If a later finding invalidates a decision, we reopen it here rather
than silently editing the old entry — see "Reopened decisions" below.

**Status key** (same as `00-START-HERE.md`): OPEN · BLOCKED · DEFERRED ·
DECIDED · TRIAL · PARKED · DROPPED.

---

## Log

| ID | Decision | Status | Date | Evidence |
|---|---|---|---|---|
| D-02 | Raw layer: both exact bytes and a parsed copy | DECIDED | 2026-08-30 | — |
| D-04 | Long-form canonical, wide as derived view | DECIDED | 2026-08-30 | — |
| D-09 | One canonical table, nullable OI | DECIDED | 2026-08-30 | — |
| D-13 | Manifest with content hashes per ingest batch | DECIDED | 2026-08-30 | — |
| D-08 | 1-second for index/futures, 1-minute for options | DECIDED | 2026-08-30 | findings.md S-01 |
| D-10 | OI in same record as OHLCV, nullable | DECIDED | 2026-08-30 | — |
| D-11 | Rows absent + expected-session-calendar | DECIDED | 2026-08-30 | — |
| D-05 | Composite string primary + exchange_token field | DECIDED | 2026-09-05 | findings.md S-06 |
| D-17 | Event-driven for stateful, vectorized for stateless, per feature | DECIDED | 2026-09-05 | — |
| D-14 | Hybrid: on-demand, cached by feature+data version | DECIDED | 2026-09-05 | — |
| D-15 | Per-feature typed tables, shared naming convention | DECIDED | 2026-09-05 | — |
| D-16 | Version in table/path name, pinned explicitly | DECIDED | 2026-09-05 | — |
| D-18 | Left open — decide per feature, not globally | DEFERRED | 2026-09-05 | — |
| D-26 | Defer continuous futures series until needed | DEFERRED | 2026-09-05 | — |
| D-27 | Built on demand, cached per D-14; full listed ladder | DECIDED | 2026-09-05 | — |
| D-22 | Standard-practice bundle (tick bins, 70% VA, 1s where available) | DECIDED | 2026-09-05 | — |
| D-23 | N-bar fractal + close-through, 1-minute only | DECIDED | 2026-09-05 | — |
| D-24 | Left open until Dhan feed quality (S-03) is tested | DEFERRED | 2026-09-05 | — |
| D-25 | Rolling percentile, per instrument | DECIDED | 2026-09-05 | — |
| D-28 | Run NautilusTrader spike first, defer final call | DEFERRED | 2026-09-05 | — |
| D-29 | Event-driven primary, vectorized for screening | DECIDED | 2026-09-05 | — |
| D-30 | Fill at next bar open; pessimistic SL/TP tie-break | DECIDED | 2026-09-05 | — |
| D-31 | Full NSE F&O cost stack now, pluggable interface | DECIDED | 2026-09-05 | — |
| D-32 | Immutable snapshot with lineage id | DECIDED | 2026-09-05 | — |
| D-33 | Callback interface, on_bar(state) | DECIDED | 2026-09-05 | — |
| D-34 | Cash accounting now; gate before option-selling | DECIDED | 2026-09-05 | — |
| D-35 | Crude risk layer modeled in backtest too, now | DECIDED | 2026-09-05 | — |
| D-36 | Dhan bulk historical+live+execution, Breeze chains+1s | DECIDED | 2026-09-05 | findings.md S-01 |
| D-37 | Append-only + post-close compaction, single process | DECIDED | 2026-09-05 | — |
| D-38 | Long-form; NIFTY futures gets 200-level slot | DECIDED | 2026-09-05 | — |
| D-39 | Event time drives computation, receive time for latency | DECIDED | 2026-09-05 | — |
| D-40 | End-of-day finalization deferred to Phase 5 | DEFERRED | 2026-09-05 | — |
| D-41 | Python + pandas primary, DuckDB as query layer | DECIDED | 2026-09-05 | — |
| D-42 | One repo, modules mirror the layer model | DECIDED | 2026-09-05 | — |
| D-43 | Plotly as the v1 visualization stack | DECIDED | 2026-09-05 | — |
| D-44 | Custom plain-Python validation checks, gate on promotion | DECIDED | 2026-09-05 | — |
| D-45 | Local machine; real backup only for live-recorded data | DECIDED | 2026-09-05 | — |
| D-46 | Order flow forward-only, no historical approximation | DECIDED | (original) | — |
| D-47 | Trivial futures test → GEX reversal → order-flow last | DECIDED | 2026-09-05 | — |
| D-48 | Thin slice + recorder in parallel once Dhan is active | DECIDED | 2026-09-05 | — |
| D-49 | Manual daily token regen; loud-failure already built | DECIDED | 2026-09-05 | — |
| D-50 | Start with 1 year, NIFTY front-weekly; widen later | DECIDED | 2026-09-06 | findings.md S-02 |
| D-51 | One time-versioned rules store, one accessor | DECIDED | 2026-09-06 | — |
| D-52 | Dated table; source = NSE bhavcopy via jugaad-data | DECIDED | 2026-09-06 | findings.md |
| D-53 | One gex_config object per market, in feature version | DECIDED | 2026-09-06 | — |
| D-54 | Get seams right, implement only NSE | DECIDED | 2026-09-06 | — |
| D-55 | Single accessor + lightweight custom hardcode check | DECIDED | 2026-09-06 | — |

---

## Entries

### D-02 — Raw layer format

**Status:** DECIDED
**Date:** 2026-08-30
**Decision:** Store both the provider's exact response bytes (compressed,
with a fetch-metadata sidecar recording request params and fetch time) *and*
a lightly parsed, unmodified tabular copy.
**Rationale:** Maximum safety over the byte-only option — an audit-proof
original plus a ready-to-query form, accepting the roughly doubled storage
and write-path complexity as the cost. Raw stays immutable either way; the
parsed copy is regenerable from the bytes if the parser ever turns out wrong.

### D-04 — Long-form vs wide-form canonical data

**Status:** DECIDED
**Date:** 2026-08-30
**Decision:** Long-form canonical (`timestamp, instrument_id, o,h,l,c,v,oi`).
Wide representations remain available as derived views where a benchmark
justifies them, but are never the source of truth.
**Rationale:** Option chains have changing strike ladders — a wide schema
(column per instrument) breaks on contact with that. Long-form also gives
arbitrary instrument sets and efficient columnar scans for free.

### D-09 — One table for all instrument types, or one per type?

**Status:** DECIDED
**Date:** 2026-08-30
**Decision:** One canonical table for all instrument types, with OI as a
nullable column (populated for future/option, null for equity/index).
**Rationale:** Uniform queries across instrument types; simplest to join and
extend. Revisit only if D-03 (partitioning, currently BLOCKED on S-01/S-02)
later argues for a physical split — logically it stays one table either way.

### D-13 — Dataset versioning mechanism

**Status:** DECIDED
**Date:** 2026-08-30
**Decision:** A manifest file per ingest batch: content hashes, row counts,
generation time, source. No version column on records, no versioned
directories.
**Rationale:** Cheap, no new tooling, sufficient to answer "was this the same
data?" for a single-user research system. Upgradeable later if S-01 finds
Breeze restates historical data often enough to need something stronger.

### D-08 — Canonical base resolution

**Status:** DECIDED
**Date:** 2026-08-30 (first pass 2026-08-30, reopened same day, re-decided
same day — see "Reopened decisions" below for the full sequence)
**Decision:** 1-second canonical resolution for index and futures;
1-minute for options.
**Rationale:** The original draft's lean, now confirmed rather than assumed.
`findings.md` (S-01) ran a live experiment confirming `interval="1second"`
genuinely works via Breeze's REST v2 historical endpoint — real sparse
per-second bars (volume 0 where no tick landed, not a faked series) —
confirmed directly on **equity cash, NIFTY futures, and the NIFTY index**,
the three instrument classes this decision actually covers. Options are
excluded from 1-second by request-budget math (§4 of
`04-tooling-landscape.md`), not by a coverage question — full-chain
1-second was already known infeasible before this experiment. Accept the
mixed-resolution join complexity this creates (flagged in the original
register) as the cost of not discarding real fidelity on the instruments
that matter most for volume-profile/structure work.
**Supersedes / reopens:** supersedes the first-pass TRIAL decision recorded
earlier the same day (1-minute everywhere, pending confirmation). See below.

### D-10 — Is OI in the same record as OHLCV?

**Status:** DECIDED
**Date:** 2026-08-30
**Decision:** Same record as OHLCV, nullable `open_interest` column (null
for equity/index, populated for futures/options).
**Rationale:** Both providers appear to expose intraday OI as a field on the
historical bar itself, so the separate-series/explicit-as-of-join machinery
the register's "Lean" wanted mainly to guard against differing cadence isn't
buying much if cadence actually matches. Simpler schema chosen over the
defensive one. **Caveat:** this assumes OI cadence matches price cadence —
S-01 hasn't confirmed that empirically yet, only that the field exists and
appears populated in Breeze's documented examples (findings.md). If the
1-second/S-01 experiment (or the futures/options data being collected
separately) shows OI updates on a different cadence than price, reopen this.

### D-11 — Missing data representation

**Status:** DECIDED
**Date:** 2026-08-30
**Decision:** Missing timestamps are simply absent rows (no fabricated
candles), plus a separate expected-session-calendar (holidays, special
sessions) that validation uses to distinguish "genuinely missing" from
"market was closed."
**Rationale:** Honest gaps — every consumer must handle irregular series
rather than risk someone forward-filling nulls without thinking. The
calendar is what makes "missing" diagnosable instead of just a shrug. Note:
the working equity pipeline (`backtest/breeze`) already has an informal
version of this (`--holidays` flag on `validate_raw_data.py`) — this decision
formalizes that pattern as the canonical approach rather than a per-script
option.

### D-05 — Instrument identity scheme

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** Deterministic composite string as the primary, market-namespaced
`instrument_id` (e.g. `NSE|NIFTY|2026-08-27|25000|CE`). Additionally, store
the shared NSE-assigned numeric token as a first-class `exchange_token` field
on the instrument master.
**Rationale:** `findings.md` (S-06) confirmed Breeze's SecurityMaster `Token`
and Dhan's `securityId` are the *same* NSE-assigned number, checked on three
independent contracts (an option, a future, and an equity). That's a
reliable, already-shared join key for free — but promoting it to the primary
`instrument_id` would tie the identity scheme to NSE's numbering authority,
which won't exist for a future non-NSE market and works against the
market-abstraction goal in `08`. Keeping the composite string primary
preserves debuggability and market-agnosticism; `exchange_token` captures the
reconciliation shortcut as a secondary field rather than throwing it away.

### D-17 — Feature engine execution model

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** No single global execution model. Event-driven (state updated
per bar/event, look-ahead structurally impossible) for anything with running
state — market structure, volume profile, footprint, running VWAP.
Vectorized (pandas/polars over whole series) for features that are genuinely
stateless per-bar. The choice is made and recorded per feature as it's
built, not decided globally up front.
**Rationale:** This is the decision `05-decision-register.md` itself flags as
the hardest in the whole document, because vectorized-only breaks the "one
system, five modes" promise from `01-concept.md` (doesn't translate to live)
while event-driven-only makes research iteration slow for things like volume
profile that are naturally batch operations. Splitting by feature rather than
picking one globally keeps look-ahead risk where it's structurally
prevented (stateful features) without paying the event-driven tax where
there's no risk to prevent.
**Consequence:** Every feature's spec must now explicitly name which model
it uses — this becomes part of what "record which is which" means for D-16
(feature versioning) too.

### D-14 — Precomputed, on-demand, or cached?

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** Hybrid — compute on demand, cache keyed by
`(feature, version, params, data_version)`. Cache is never the source of
truth; canonical data and the feature definition always are.
**Rationale:** Pure precompute risks a stored feature table silently going
stale after a definition change, and is easy to join carelessly against a
future timestamp (a direct R20 look-ahead risk). Pure on-demand is safest
but too slow for the backtest iteration speed research productivity depends
on. The cache key including both feature version *and* data version is the
part that must not be skipped — that's what D-16 (feature versioning) has to
make cheap to construct correctly.

### D-15 — Feature storage schema

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** Per-feature typed tables (not one generic long table, not
grouped-by-class), with a shared naming and metadata convention across all
of them.
**Rationale:** Features come in at least four shapes (instrument-level,
market-level, chain-level, event-shaped) and a generic
`feature, version, timestamp, key, value` table loses types and becomes
awkward the moment a feature has multiple correlated outputs — volume
profile alone needs POC/VAH/VAL/HVN/LVN together, not as five separate rows.
Per-feature tables cost more schemas to maintain, but that's a fixed,
one-time cost per feature rather than an ongoing modeling tax on every
query.

### D-16 — Feature versioning mechanism

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** Version encoded in the table/path name (e.g. `features/gex/v1/`
as its own table), not as a column. Strategies must pin an exact version
explicitly — "latest" is never a valid reference.
**Rationale:** Natural fit with D-15's per-feature typed tables — one
physical table per version keeps a changed definition from ever touching
old results. Explicit pinning is what R24 requires: a changed calculation
becomes a new version that coexists with the old one, never a silent
mutation of historical results.

### D-27 — Option chain as object or query

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** Logical object, built on demand from canonical instrument +
market data — no physical chain-snapshot storage. Uses the same on-demand +
cache policy as D-14. Chain membership at time T = every strike with a
listed contract for that expiry as of T, regardless of whether it traded
that day.
**Rationale:** Avoids duplicating canonical data into snapshot storage.
The membership rule matters specifically for GEX (R8): a strike can carry
real OI with zero trades on a given day and still be part of the exposure
picture, so "membership" can't be defined by trade activity — it has to
come from the instrument master's listed contracts, checked as-of T.

### D-22 — Volume profile construction

**Status:** DECIDED (v1 — expect a v2)
**Date:** 2026-09-05
**Decision:** Fixed-tick-multiple bin sizing (relative to the instrument's
tick size); standard 70% value area; HVN/LVN identified via a relative-volume
threshold against a rolling local average. For intrabar volume distribution:
where D-08 gives native 1-second bars (index, futures), use those directly
instead of guessing how volume is spread within a 1-minute bar; for options
(1-minute only), assume volume is spread uniformly across the bar's range.
**Rationale:** The register itself flags intrabar distribution as materially
changing POC and "genuinely ambiguous" — D-08's mixed resolution turns out to
directly reduce that ambiguity for index/futures, which is the first
concrete payoff of that earlier decision. Options still need an assumption;
uniform is the least presumptive default. Ships versioned as `v1`, expected
to be revised once checked against real charts per R23.

### D-23 — Market structure algorithm

**Status:** DECIDED (v1 — expect several revisions)
**Date:** 2026-09-05
**Decision:** N-bar fractal swing detection (e.g. 5-bar); BOS/CHOCH confirmed
on candle close, not wick-through; computed on the base 1-minute timeframe
only, not multi-timeframe.
**Rationale:** Simple, well-understood starting point. The register
explicitly names this as the feature most likely to be "correct" by three
different definitions, and states visual validation (R23) matters here more
than anywhere else — so v1 is deliberately the simplest defensible choice,
not a claim that it's right, and every subsequent version must ship with its
visualization per R23/D-43.
**Trigger to revisit:** Not just visual validation — actual backtest results
once Phase 3/4 exist. If strategies built on `structure_v1` behave
suspiciously (e.g. BOS firing on noise, or GEX+structure combinations that
don't hold up), that's grounds for `structure_v2` with a different swing
definition or confirmation rule, same as any other feature version. Expect
this to be revised by evidence, not just by inspection.

### D-25 — Big trade definition

**Status:** DECIDED (methodology only — thresholds pending S-03)
**Date:** 2026-09-05
**Decision:** Rolling percentile (e.g. 95th/99th) of trade quantity,
computed per instrument rather than one global threshold. Exact percentile
and window length are tuning parameters, not fixed here.
**Rationale:** Matches the register's own requirement that a fixed quantity
threshold is insufficient, and per-instrument computation accounts for the
enormous liquidity spread across strikes/underlyings. **Caveat, carried
over from the register's own warning:** last traded quantity is an int16
field (max 32,767) — if large option prints truncate, wrap, or saturate,
they'd corrupt precisely the tail this feature depends on, silently. Verify
via S-03 (blocked on the Dhan Data API subscription, see `findings.md`)
before finalizing actual threshold values; the methodology choice itself
doesn't depend on that check.

### D-29 — Event-driven or vectorized backtesting

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** Event-driven is the primary, trustworthy backtesting engine.
A vectorized pass stays available for fast screening — eliminating
obviously-bad ideas cheaply before spending event-driven validation time on
them — but no result is trusted until it's run event-driven.
**Rationale:** Path-dependent exits (SL/TP touched intrabar), MAE/MFE, and
order-flow strategies all need event-driven semantics — and those are
exactly the project's actual hypotheses (GEX reversal, footprint), not
edge cases. Mirrors D-17's per-feature split one layer up, at the engine
level.

### D-30 — Execution timing model

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** A signal from a completed bar's close fills at the next bar's
open. When both SL and TP could plausibly fill within a single bar's OHLC
range, the pessimistic outcome (worse for the position) is assumed to fill
first.
**Rationale:** Matches R19's own suggested starting point — simple,
conservative, deterministic, and an explicit, recorded trade-off rather than
an assumed one. The pessimistic tie-break is a direct response to the
register's warning that the optimistic assumption "silently inflates every
result" — exactly the kind of error that's invisible until real money is on
the line.

### D-31 — Fill, slippage and cost model

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** The full real NSE F&O cost stack (brokerage, STT, exchange
charges, GST, stamp duty, SEBI fees) is built now, not deferred — as a
pluggable component the engine calls (given a fill, return itemized costs),
not a function with Indian tax names hardcoded into the execution path.
**Rationale:** The register's own framing: a strategy profitable before
costs and dead after them is the single most common way research time gets
wasted, and that's exactly the kind of mistake that's cheap to prevent early
and expensive to discover late. The pluggable interface means a future
market's cost stack (SEC fee, ORF, OCC, exchange fees for US options) is a
new implementation behind the same interface, not a rewrite — costs nothing
extra now, per the market-abstraction principle in `08`.

### D-32 — Market state object shape

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** Immutable snapshot with a lineage id, tagged with the
feature/data versions that produced it.
**Rationale:** Directly satisfies R24's traceability chain (trade → signal →
feature snapshot → canonical → raw) — the point isn't just "what is the
current market state" but "what did the strategy actually see when it
decided," and only a snapshot captures that after the fact. Doesn't force
eager computation of every feature every bar underneath; pairs naturally
with D-14's on-demand+cache policy.

### D-33 — Strategy interface

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** Callback interface — `on_bar(state)` / `on_event(state)`. A
strategy declares which instruments and features it needs via a
registration-time manifest, so the engine knows what to compute for it.
Multi-leg option positions are expressed as individual leg orders sharing a
strategy-assigned combo id.
**Rationale:** Common, well-understood pattern; matches how NautilusTrader
itself exposes callbacks (`on_bar`, `on_quote_tick`, `on_order_book`), so
this choice isn't wasted if D-28's spike leads there, and is a reasonable
default if it doesn't.

### D-34 — Portfolio and margin modelling depth

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** Simple cash accounting for now. Hard gate: no option-*selling*
strategy gets backtested until SPAN/exposure margin approximation exists.
**Rationale:** Matches the register's own lean exactly — margin is a
first-order constraint on returns for option-selling and ignoring it makes
those results meaningless, not just imprecise, while it barely matters for
directional/long-option strategies or the futures-only thin slice (Phase
1.5). The gate means this can't be silently skipped when the first
option-selling hypothesis actually shows up.

### D-35 — Where does risk live?

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** A crude risk layer (position limits, daily-loss cutoff, max
simultaneous positions) is modeled in the backtest too, active from early
on — not deferred to live-only.
**Rationale:** Resolves a direct contradiction in the register itself
(default status said DEFERRED to Phase 7; the register's own stated lean
said model it in backtest too). Took the lean: R21 requires forward and
historical results to be comparable, and if risk constraints only exist
live, backtest results systematically overstate what the live system would
actually have done — silently, in a way that would only surface once real
capital is on the line.

### D-36 — Provider split

**Status:** DECIDED (confirmation completed)
**Date:** 2026-09-05
**Decision:** Dhan for bulk historical (equity/index/futures 1-min + OI),
all live data (ticks, depth, chain+greeks), and execution later. Breeze for
historical option chains (absolute strike+expiry, including expired) and
1-second historical (index/futures only, per D-08).
**Rationale:** The original register already recorded this decision inline,
pending S-01 confirmation. `findings.md` (S-01) has since confirmed the
mechanism this depends on — Breeze genuinely serves absolute strike+expiry
history 2 and 5 years back with real OI, and 1-second REST works on equity,
index and futures. Closing the "pending" qualifier rather than re-deciding
from scratch — nothing changed, the open question is answered.

### D-37 — Recorder architecture

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** Append-only raw writes during the session, compacted to
columnar after market close. One recorder process handling all subscribed
instruments, not split by instrument group.
**Rationale:** Matches the register's own lean — simplest thing that
survives a crash mid-write, which is the failure that actually happens.
Single-process is the "build thinly" default (D-48's whole ethos); actual
instrument scope isn't known yet since it depends on the still-pending Dhan
subscription, so a multi-process split now would be guessing at a shape for
a load that hasn't been measured.

### D-38 — Depth representation

**Status:** DECIDED (tier allocation is a starting policy, not load-tested)
**Date:** 2026-09-05
**Decision:** Long-form depth rows (`timestamp, instrument, side, level,
price, qty, orders`), consistent with D-04's canonical philosophy. Tier
allocation: NIFTY futures gets the single scarce 200-level slot; near-ATM
NIFTY options get 20-level; everything else rides the free 5-level full
packet.
**Rationale:** Long-form over wide matches the same reasoning as D-04 —
level counts vary, most wide columns would sit empty. NIFTY futures as the
primary traded instrument is the natural claim on the one 200-level slot.
**Open:** Row-count-per-snapshot at 200 levels (the register's own "~400
rows per snapshot per instrument" concern) is not yet measured — that's
S-02, blocked on the Dhan Data API subscription (see `findings.md`). This
decision fixes the shape; it doesn't yet confirm the shape is affordable at
scale.

### D-39 — Event time vs receive time

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** Event time (LTT) drives feature computation and bar
boundaries during live operation, with a small buffering window to handle
late-arriving events. Receive time is recorded (per R16, both are required
regardless) but used only for latency measurement and debugging.
**Rationale:** This is what keeps live and replay comparable — R21's
requirement. Replaying recorded data reproduces the same event-time
ordering regardless of when each event was originally received; if receive
time drove computation instead, ordinary network jitter would make live and
replay diverge, silently breaking the reproducibility promise. The exact
buffering-window length for late arrivals is left as an implementation
parameter, not fixed here.

### D-40 — End-of-day finalization

**Status:** DEFERRED (Phase 5, per the original register)
**Date:** 2026-09-05
**Decision:** Adopting the original register's own default rather than
re-deciding: validation → canonicalization → comparison against overlapping
provider data → promotion, deferred as a pipeline to build in Phase 5.
**Rationale:** Nothing about the work done so far changes this — it's a
genuine "build later" item, not a judgment call being ducked. Recording it
formally here per the doc set's own instruction that "defer, revisit at
Phase N" is a valid, recordable decision.

### D-41 — Core language and dataframe library

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** Python with pandas as the primary dataframe library; DuckDB
alongside as the query layer for D-01's analytical access patterns ("full
chain at timestamp T", scans across a date range).
**Rationale:** Matches the existing working pipeline (`backtest/breeze`
already uses pandas + pyarrow) — no second dataframe paradigm to maintain
without evidence one's needed. At research volumes, iteration speed matters
more than raw performance; revisit only if profiling shows a genuine
bottleneck, not preemptively.

### D-42 — Repository and module layout

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** One repository, with module boundaries mirroring the layer
model (ingest / canonical / features / engine / strategies / viz). Strategies
live in-repo initially. This all lives under `flow/`, which per `CLAUDE.md`
stays empty until building actually starts.
**Rationale:** Splitting into separate installable packages or repos now
would be structure without anything yet to justify it. Split later only if
a specific boundary proves it deserves to be its own package — not before.

### D-43 — Visualization stack

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** Plotly as the v1 default for candles + overlays (VWAP,
structure, GEX levels, entries/exits/SL/TP). Footprint rendering is treated
as its own separate, later problem — not something that blocks starting
feature work now.
**Rationale:** R23 makes this a required verification tool, not a nicety —
"most feature bugs are invisible in aggregate statistics and obvious on a
chart" (01-concept.md). Plotly renders fast with good DataFrame integration;
don't let the charting choice block feature work, per the register's own
lean.

### D-44 — Validation framework

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** Custom, plain-Python validation checks, run as a gate on
promotion to canonical — no third-party validation framework.
**Rationale:** Extends the pattern already proven in
`backtest/breeze/data_pipeline/validate_raw_data.py` (CRITICAL vs. WARNING
severity, holiday-aware gap detection) rather than introducing Great
Expectations or pandera. Matches the register's own lean: frameworks add
ceremony a single-user research system doesn't need, and there's already
working code demonstrating the simpler approach is sufficient.

### D-45 — Compute and storage environment

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** Local machine for now. Recorded live data gets a real backup
policy (periodic copy elsewhere) since it's irreplaceable; historical data
pulled from Breeze/Dhan doesn't need the same rigor since it can always be
re-pulled if lost.
**Rationale:** Real size numbers now exist from S-01/S-02 (`findings.md`):
~166 bytes/row equity, ~287 bytes/row options, ~462 contracts for a NIFTY
weekly chain — low tens of MB/day even for a full weekly chain, nowhere
near a volume that justifies cloud infrastructure yet. The backup asymmetry
follows directly from D-46: order-flow/live-tape data has no historical
equivalent anywhere, so losing recorded days is permanent in a way losing
re-fetchable historical data isn't.

### D-46 — Order flow: scope and history

**Status:** DECIDED (original register — see `05-decision-register.md`)
**Date:** original
No changes here — recorded in the log for completeness since D-47/D-48/D-49
all reference it directly. Full rationale is in the static register: order
flow is in scope, forward-only by design, no historical approximation from
bars.

### D-47 — Which strategy hypothesis is first?

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** First strategy is a trivial futures-only pipeline test —
exists to validate the pipeline end-to-end (data → trade → traceable back
to raw), not to make money. Then GEX reversal as the first real hypothesis.
Order-flow hypotheses wait until the recorder has accumulated enough
forward data to say anything.
**Rationale:** Matches the register's own lean. A pipeline bug is far
easier to isolate in a trivial strategy than inside GEX reversal's full
stack (chains, Greeks, GEX, structure, dealer convention). GEX reversal is
now genuinely backtestable given Breeze's confirmed absolute-strike chain
access (`findings.md` S-01) — it was previously in doubt.

### D-48 — How much is built before the first backtest runs?

**Status:** DECIDED
**Date:** 2026-09-05
**Decision:** Thin vertical slice first (Phase 1.5) — one instrument, one
month, VWAP-only, crude engine, real fees. The live recorder starts in
parallel as soon as the Dhan subscription is active, treated as a real
deadline at that point rather than an afterthought, since D-46 makes every
day of delay permanently lost order-flow history.
**Rationale:** The register calls this the decision that determines whether
the project finishes at all — designing from the complete end state
literally means a year of infrastructure before any result. The thin slice
surfaces wrong assumptions early and cheaply. The recorder note is a
conscious acknowledgment, not a new commitment: the Dhan subscription is
currently on hold for practical reasons (see `findings.md`), and that's a
reasonable call — but it should be a deliberate choice each time it's
deferred further, not a default that goes unexamined.

### D-49 — Breeze session token handling

**Status:** DECIDED (interim)
**Date:** 2026-09-05
**Decision:** Manual daily token regeneration for now, matching the pattern
already proven in `backtest/breeze`. TOTP automation investigation is
deferred until right before it's actually the bottleneck — i.e. right
before D-50's multi-week chain pull starts, not now.
**Rationale:** The register's actionable core principle — "make token
expiry produce a loud, unambiguous failure" — is already implemented
(`experiments/s01_breeze_coverage_check.py`'s `authenticate()` fails fast
with a clear message and login URL on an expired/invalid session). The
harder question (how far TOTP automation actually gets, S-07) isn't worth
answering before it's needed.

### D-50 — Historical chain pull: scope and schedule

**Status:** DECIDED
**Date:** 2026-09-06
**Decision:** Start with 1 year of NIFTY front-weekly chain history; widen
(more years, BANKNIFTY, wider strikes) only after this validates the
pipeline end-to-end.
**Rationale:** `findings.md` (S-02) corrected the original "~6 weeks for 5
years" estimate to roughly ~6 months for the same scope, since the real
weekly ladder (~462 contracts) is ~4.6× wider than the ~100 originally
assumed. A bounded 1-year pull (~5-7 weeks of pulling at the real contract
count) proves the raw→canonical→GEX pipeline works before committing to a
multi-month operation. Also gated on D-49's token handling and D-52's
expiry-calendar sourcing being resolved enough to know which expiries to
pull.

### D-51 — Market rules as time-versioned data

**Status:** DECIDED
**Date:** 2026-09-06
**Decision:** One time-versioned market-rules store, one accessor:
`rules_as_of(market, t)`. Contract specs, expiry calendars, session times,
tick sizes, and settlement rules are all `valid_from`/`valid_to` rows keyed
by market + rule type, looked up through this single function.
**Rationale:** Matches the register's own lean. Every decision made so far
that touches market-specific facts (D-06's lot-size versioning, D-19's
exercise-style/settlement-time parameters, D-31's pluggable cost model)
already assumes this store exists — this formalizes it as one uniform
mechanism rather than ad hoc per-concern versioning. A single accessor also
makes hardcoding visible in review: if analytics can only get market facts
one way, an inline constant stands out immediately.

### D-52 — Expiry as calendar data, not computed rule

**Status:** DECIDED
**Date:** 2026-09-06
**Decision:** A dated calendar table (not a computed rule), sourced from
NSE's own historical bhavcopy — confirmed working via the `jugaad-data`
Python library (`jugaad_data.nse.bhavcopy_fo_raw(date)`), which handles
NSE's bot-protected archive access internally.
**Rationale:** Mechanism was never controversial. Sourcing took three real
experiments to close: SecurityMaster ruled out (current-listings-only
snapshot), Dhan's `/v2/charts/rollingoption` ruled out (real historical
data, but never reveals which expiry was active), then NSE's own bhavcopy
confirmed genuinely working — real 25-Jan-2024 data pulled with
`EXPIRY_DT`, strike, OHLC, `OPEN_INT`, and volume per contract, for free,
via a maintained community library rather than fighting NSE's bot
protection directly. Every plausible shortcut was ruled out by evidence,
not assumption, before landing on the one that actually works.
**Bonus, not the original ask:** bhavcopy also removes the guesswork from
D-50's chain pull — it lists the exact contracts active on a historical
day before spending a single Breeze request, rather than probing strikes
and discarding misses.
**Checked and ruled out while here:** NSE's historical **Trades**
(tick-by-tick) and **Snapshots** (order-book) archives, described in the
same source document, are **not** exposed by either `jugaad-data` or
`nsepython` — evidence they're no longer freely available (likely folded
into NSE's paid data-vending product). **D-46 was checked against this and
is unchanged** — order-flow remains forward-only; this was worth verifying
rather than assuming, and came back negative. Also checked: NSE's
**Masters** archive (would have helped D-06's lot-size-history problem) is
similarly not exposed by either library — D-06's path remains `08`'s
original suggestion of encoding known lot-size revisions by hand from
exchange circulars.
**Follow-up (not this decision):** wiring `jugaad-data` into an actual
expiry-calendar builder is new work for when `flow/` building starts, not
part of this decision.

### D-53 — GEX configuration object

**Status:** DECIDED
**Date:** 2026-09-06
**Decision:** One `gex_config` object per market, holding expiry scope
(all listed / nearest-N / DTE window), contract multiplier source (→
D-51), dealer-positioning convention (→ D-20, still blocked on S-05),
underlying reference (→ D-21, still blocked on S-04), strike-range limits,
and level-identification method. The config is captured in the GEX feature
version per D-16.
**Rationale:** The calculation is common across markets; scope, parameters
and interpretation are not (per `08-market-abstraction.md`). Recording the
exact config that produced a stored GEX series is what keeps cross-market
or cross-time comparison honest about what actually differed — without it,
a GEX series is unreproducible the moment any of these parameters change,
which R7/R24 both forbid happening silently.

### D-54 — How far to take the abstraction now

**Status:** DECIDED
**Date:** 2026-09-06
**Decision:** Get the seams right, implement only NSE. No US market
profiles, adapters, or margin models as working code yet. Validation stays
cheap: write SPX/ES market profiles as config files only, once in Phase 1
and again after Phase 2, per `08`'s own suggested check.
**Rationale:** Confirms, rather than newly decides, the pattern already
running through every prior decision that touched a market-specific fact —
D-05's `exchange_token`, D-19's exercise-style/settlement-time parameters,
D-31's pluggable cost model, D-51's rules store. Full generality now would
be guesswork shaped by a market that doesn't exist in the codebase yet;
the config-only validation check is nearly free and catches gaps while
they're still cheap to fix.

### D-55 — Where does market knowledge live?

**Status:** DECIDED
**Date:** 2026-09-06
**Decision:** `rules_as_of(market, t)` (D-51) is the only sanctioned path
to a market fact anywhere outside adapters and the rules store itself.
Backed by a lightweight custom check — not a full lint framework, just a
script (in the same spirit as D-44's validation checks) that flags
hardcoded market-name literals appearing outside the allowed directories —
run as part of the validation gate.
**Rationale:** Convention-and-review-only is exactly the erosion path `08`
itself warns about: "the first hardcoded `if market == 'NSE'` ... will look
entirely reasonable at the time." A cheap automated check catches that
before it ships, without the upfront design cost a full type-system
enforcement approach would add to a codebase that's chosen pandas/dynamic
Python elsewhere (D-41) specifically for iteration speed.

---

## Deferred decisions

### D-28 — Build the backtester, or adopt one?

**Status:** DEFERRED
**Date:** 2026-09-05
**Decision:** Not committing to build-custom or adopt (NautilusTrader /
Backtrader / vectorbt hybrid) yet. Run the 2-day NautilusTrader spike
`04-tooling-landscape.md` §8 specifies first: a trivial NIFTY futures
strategy from a CSV, an NSE option instrument with correct multiplier/lot
size/expiry (and whether that definition can be time-versioned per D-51),
a minimal Dhan adapter, and one custom chain-level feature attached to
market state.
**Trigger to revisit:** The spike's outcome, directly. §8/§10 of
`04-tooling-landscape.md` are explicit that a good outcome closes D-05,
D-17, D-18, D-28, D-29, D-32, D-33, and D-38 essentially at once — and a bad
outcome (can't do time-versioned contract specs, adapter is painful, no
seam for a custom chain-level feature) gives a firm, cheap answer to build
custom instead. This is deliberately not decided by judgment call — it's a
two-day experiment, not a debate.
**Note:** This belongs in `experiments/` as a concrete next spike, same
category as the Breeze/Dhan checks already run — not a documentation
exercise.

### D-18 — One implementation for historical and live, or two?

**Status:** DEFERRED
**Date:** 2026-09-05
**Decision:** Left open rather than declared solved by D-17. D-17's
per-feature event-driven/vectorized split *looks* like it resolves this (one
implementation per feature either way), but that's an inference, not
something tested yet.
**Trigger to revisit:** The first feature that's actually built under D-17's
split — check then whether its single implementation genuinely serves both
modes, or whether something (timing, event ordering, a live-only field)
forces a second path. The mandatory replay-parity test from
`07-build-order.md` Phase 6 is where this gets a real answer either way.

### D-24 — Trade classification for footprint

**Status:** DEFERRED
**Date:** 2026-09-05
**Decision:** Left open — not choosing between tick-rule-with-quote-fallback
and full Lee-Ready yet.
**Trigger to revisit:** S-03 (blocked on the Dhan Data API subscription,
see `findings.md`) confirming whether Dhan's depth (best bid/ask) updates in
step with trades or independently. Full Lee-Ready needs bid/ask reliably
time-aligned with each trade; if S-03 shows it isn't, that option is
effectively closed off and the tick-rule-fallback approach becomes the
default by elimination rather than a preference.
**Note:** This is forward-only regardless (D-46) — whichever rule is chosen,
it's validated against recorded live data, never backtested.

### D-26 — Continuous futures series

**Status:** DEFERRED
**Date:** 2026-09-05
**Decision:** Not built until a strategy actually needs one.
**Trigger to revisit:** A strategy hypothesis that requires a stitched
series rather than per-contract records. If/when that happens, the roll
rule (trigger + adjustment method) belongs in the market profile (`08`),
not hardcoded continuation logic — record that constraint at the point of
revisiting, not now.

---

## Reopened decisions

### D-08 — Canonical base resolution (reopened)

**Date reopened:** 2026-08-30
**Original decision:** 1-minute everywhere, explicitly TRIAL pending
confirmation that `interval="1second"` works via REST (see the D-08 entry
above).
**What changed:** `findings.md` (S-01) — the experiment confirmed
`interval="1second"` genuinely works via Breeze's REST v2 historical
endpoint, returning real sparse per-second bars, on equity cash. The
explicit trigger for revisiting this decision has been met.
**Re-decided same day** after one more confirmation pass (index + futures
directly, not just equity) — see the D-08 entry above for the closed
decision. Full sequence: TRIAL (1-minute everywhere, pending confirmation)
→ reopened on the equity-cash confirmation → DECIDED (mixed resolution)
once index/futures confirmed too.

# 05 — Decision Register

**This is the working document.** Everything here was written as settled fact in
the original technical draft. None of it is settled.

Work top to bottom. For each: fill in **Decision**, **Date**, **Rationale**.
"Defer to Phase N" is a valid decision — record it as one, with the trigger that
will force the choice.

Where I have a genuine view I've marked it **Lean:**. It is a starting point to
argue with, not a recommendation to accept.

**Status key:** OPEN · BLOCKED (by spike) · DEFERRED · DECIDED · TRIAL · PARKED · DROPPED

---

# A. Data model and identity

## D-01 — Canonical storage format
**Status:** BLOCKED by S-02 · **Blocks:** Phase 1 · **Draft assumed:** Parquet

How is canonical historical market data physically stored?

- **Parquet files** — columnar, compresses well, no server, works with everything. Poor at point lookups and row-level updates; you manage partitioning and file counts yourself.
- **DuckDB** — SQL over columnar storage, single file, excellent analytical scans, indexes, joins. Reads Parquet directly, so this isn't strictly either/or. Single-writer.
- **SQLite** — trivial, ubiquitous, transactional. Row-oriented; weaker on wide analytical scans, but at small volumes that may not matter.
- **TimescaleDB / Postgres** — real database, concurrent access, time-series functions. Operational overhead; a server to run and back up.
- **ClickHouse / kdb-style** — fast at scale. Almost certainly overkill.
- **Parquet + DuckDB as query layer** — files as source of truth, SQL over them.

Considerations: volume from S-02 is the deciding input. Single-user research
workload. Query pattern is dominated by "full chain at timestamp T" and "one
instrument over a date range" — quite different access patterns. Migration cost
later is real but bounded if the *logical* model (D-04, D-09) is stable.

**Lean:** Parquet as immutable source of truth + DuckDB as the query layer. It
defers the real decision, keeps files portable, and DuckDB reads Parquet
natively so the escape hatch stays open. But if S-02 shows the whole dataset is
small, plain DuckDB alone is simpler and you should take the simpler thing.

> **Decision:**
> **Date:**
> **Rationale:**

## D-02 — Raw layer format
**Status:** OPEN · **Draft assumed:** provider response preserved

What does "immutable raw" physically mean?

- Store the provider's exact response bytes (JSON/CSV as returned), compressed.
- Store a lightly parsed but unmodified tabular version.
- Store both: bytes for audit, parsed for use.

Considerations: raw exists so you can re-derive canonical after finding a
normalization bug. That argues for exact bytes. Cost is storage and the
annoyance of re-parsing. Also record request parameters and fetch time
alongside the response — without them you can't reproduce the pull.

**Lean:** exact bytes plus a fetch-metadata sidecar. Storage is cheap; a
normalization bug discovered after a year of collection is not.

> **Decision:**
> **Date:**
> **Rationale:**

## D-03 — Partitioning scheme
**Status:** BLOCKED by S-01, S-02 · **Draft assumed:** date / type / underlying / expiry

Considerations: too fine → thousands of tiny files, slow scans. Too coarse →
every query reads everything. The right answer depends on volume and on whether
your dominant query is by-timestamp or by-instrument. Expiry as a partition key
is attractive for options and useless for equity, which argues for different
schemes per instrument type — at the cost of uniformity.

**Explicitly defer** until S-02 numbers exist. Record the deferral rather than
guessing.

> **Decision:**
> **Date:**
> **Rationale:**

## D-04 — Long-form vs wide-form canonical data
**Status:** OPEN · **Draft assumed:** long-form

- **Long** (`timestamp, instrument_id, o,h,l,c,v,oi`) — arbitrary instrument sets, arbitrary chains, one schema for everything. Wider rows to scan for a single instrument's series.
- **Wide** (one column per instrument) — fast for a fixed small universe. Breaks immediately for option chains with changing strike ladders.
- **Long canonical, wide materialized views** for specific computations where benchmarks justify it.

**Lean:** long-form canonical. Option chains make wide untenable as the base
model. But treat "wide for computation" as available, not forbidden.

> **Decision:**
> **Date:**
> **Rationale:**

## D-05 — Instrument identity scheme
**Status:** BLOCKED by S-06 · **Draft assumed:** integer surrogate ID

- **Integer surrogate** (`123456`) — compact, fast joins. Meaningless on inspection; needs a master lookup for every debugging session; must be assigned and never reused.
- **Deterministic composite string** (`NSE|NIFTY|2026-08-27|25000|CE`) — self-describing, reproducible without central assignment, debuggable by eye. Larger, and you must freeze the format forever.
- **Hash of the composite** — compact and deterministic. Unreadable.
- **Provider token as primary** — zero mapping work. Violates provider independence outright; breaks the moment you add a second provider. *(Recommend against.)*

Considerations: how often will you read raw data by eye? (In research: constantly.)
Does anything need the ID to be assignable offline? Storage difference is
mostly erased by compression and dictionary encoding.

⚠ **Market-agnostic check (see `08`).** Whatever form you pick must namespace by
market/venue from day one — SPX and an NSE contract can otherwise collide, and
retrofitting a market dimension into an identity scheme means rewriting every
stored key. This is the cheapest thing in the entire abstraction to get right
now and among the most expensive to fix later.

**Lean:** deterministic composite string, with an integer surrogate added later
*only* if profiling shows join cost matters. Debuggability during research is
worth more than bytes, and the draft's argument for integers was never made on
measured grounds.

> **Decision:**
> **Date:**
> **Rationale:**

## D-06 — Instrument master storage and time-awareness
**Status:** BLOCKED by S-06 · **Draft assumed:** valid_from / valid_to columns

Reference data changes: lot sizes change, contracts expire, symbols get renamed.

- Single current-state table (simple; loses history; wrong for backtests spanning a lot-size change).
- `valid_from` / `valid_to` versioned rows (correct; every lookup becomes time-aware and slightly more complex).
- Daily snapshots (dead simple, wasteful, trivially correct).

Considerations: **yes, your period almost certainly contains lot-size changes** —
NSE has revised contract sizes more than once, notably around the late-2024
minimum-contract-value increase. GEX scales linearly with contract multiplier,
so applying today's lot size to older OI produces a silently wrong series that
looks like a regime shift. Time-versioning is therefore not optional here.

Also decide the authoritative source: Breeze, Dhan, or NSE's contract file
(S-06). And see D-51 — contract specs are one kind of time-versioned market
rule; there are others, and they may want the same mechanism.

> **Decision:**
> **Date:**
> **Rationale:**

## D-07 — Timestamp convention
**Status:** BLOCKED by S-01 · **Draft assumed:** tz-aware Asia/Kolkata, bar labelled by open

Three sub-decisions, all easy to get wrong and expensive to fix later:

1. **Stored timezone** — UTC internally with local at display, or IST throughout? IST-throughout is more readable for a single-market system; UTC is more standard and avoids DST bugs. ⚠ **DST is irrelevant in India and very relevant in the US** — an IST-throughout choice that hardcodes a fixed offset will not survive adding US markets. Timezone belongs on the market profile as a field (`08`), and UTC storage is the safer default once more than one market exists.
2. **Bar labelling** — does `10:31:00` mean the bar that *opens* at 10:31 or *closes* at 10:31? Both conventions exist in the wild; off-by-one-minute look-ahead is a classic silent bug. **Verify what Breeze actually does (S-01) rather than choosing.**
3. **Precision** — minute resolution for canonical bars; what precision for raw events? Milliseconds at minimum for live.

**Lean:** whatever it is, write it in one place, name it explicitly in the schema
docs, and add a validation check that asserts it on every ingest.

> **Decision:**
> **Date:**
> **Rationale:**

## D-08 — Canonical base resolution
**Status:** OPEN (was BLOCKED) · **Draft assumed:** 1 minute · **Now a real choice**

Breeze offers **1-second OHLCV**, and the request budget makes it affordable for
a few instruments but not for option chains:

| | 1-second | 1-minute |
|---|---|---|
| Index, futures | affordable (~1 yr per day of pulling) | trivial |
| Full option chain | **infeasible** (~23× budget) | ~6 weeks for 5 yrs |

Options:

- **1-minute everywhere.** Uniform, simplest, throws away available fidelity.
- **1-second for index/futures, 1-minute for options.** Affordable and matches where the fidelity actually helps — volume profile and structure on the instrument you trade. Cost: canonical resolution now varies by instrument class, and every cross-instrument join must handle it.
- **1-second everywhere**, accepting that options simply won't have it. Same as above with different framing.

Note what 1-second is and isn't: it's a finer **bar**, not a tape. No bid/ask,
no per-trade quantity, no side. It improves volume-profile fidelity
considerably over 1-minute; it does not enable order flow.

**Lean:** 1-second for index and futures, 1-minute for options — but only after
S-01 confirms 1-second actually works reliably for the dates you need. The
mixed-resolution wart is real; the fidelity gain on the traded instrument is
probably worth it.

> **Decision:**
> **Date:**
> **Rationale:**

## D-09 — One table for all instrument types, or one per type?
**Status:** OPEN

- One canonical table with nullable OI (uniform queries; nullable columns; equity rows carry unused fields).
- Separate per type (tight schemas; every cross-type query needs a union).
- One table, partitioned by instrument type (middle ground; interacts with D-03).

> **Decision:**
> **Date:**
> **Rationale:**

## D-10 — Is OI in the same record as OHLCV?
**Status:** OPEN (was BLOCKED)

Both providers expose intraday OI as a flag/field on the historical bar (Dhan
`oi`, Breeze `open_interest`), so the worst case — end-of-day-only OI — appears
not to apply. Confirm it's actually populated for options (S-01) rather than
present-but-zero. If cadences differ, one table forces you to
either duplicate or null-pad OI across every minute, both of which invite
look-ahead bugs when someone forward-fills without thinking.

- Same record, nullable.
- Separate OI time series, joined explicitly with a stated as-of rule.

**Lean:** if OI cadence differs from price cadence, separate them. The explicit
as-of join is the point — it forces the look-ahead question into the open
instead of hiding it behind a forward-fill.

> **Decision:**
> **Date:**
> **Rationale:**

## D-11 — Missing data representation
**Status:** OPEN · **Requirement:** R26 forbids silent fabrication

- Rows simply absent (honest; every consumer must handle irregular series).
- Rows present with null values (uniform grid; risks someone forward-filling without thinking).
- Absent, plus a separate expected-session-calendar used by validation to detect gaps.

Also needed: a trading-calendar source (holidays, muhurat sessions, special
timings) so "missing" can be distinguished from "market closed" at all.

> **Decision:**
> **Date:**
> **Rationale:**

## D-12 — Provenance and Breeze/Dhan overlap policy
**Status:** BLOCKED by S-06 · **Draft assumed:** source column, historical→Breeze / recorded→Dhan

- What provenance fields ride on every canonical record? (`source`, `ingest_time`, `dataset_version`, `raw_reference`?)
- When both providers cover the same period, which wins? Fixed cutover date, or per-record rule?
- What happens when they disagree — validation report only, or does disagreement block promotion to canonical?

Considerations: S-06's comparison tells you whether disagreement is rare (a
validation nicety) or common (a real problem for R17's "one timeline" claim).

> **Decision:**
> **Date:**
> **Rationale:**

## D-13 — Dataset versioning mechanism
**Status:** OPEN · **Requirement:** R24

How does a backtest record *which* data it ran on, such that the same data can
be recovered later?

- Version column on records.
- Immutable versioned directories, new version per re-ingest.
- Manifest file per dataset: content hashes, row counts, generation time, source.
- Content-hash-addressed storage.
- Git-LFS / DVC / lakeFS style tooling.

Considerations: does Breeze ever restate historical data? (S-01.) If it never
does, this can stay very simple. If it does, you need real versioning before
collecting anything.

**Lean:** manifest with content hashes per ingest batch. Cheap, no new tooling,
sufficient to answer "was this the same data?", and upgradeable later.

> **Decision:**
> **Date:**
> **Rationale:**

---

# B. Feature layer

## D-14 — Precomputed, on-demand, or cached?
**Status:** OPEN · **Draft assumed:** stored feature datasets + optional cache

- **Precompute and store all features** — fast backtests, feature reuse, easy inspection. Storage cost; every definition change means regeneration; risk of stale features silently used.
- **Compute on demand during replay** — always consistent with the current definition; no staleness. Slow repeated backtests; must be incremental.
- **Hybrid: compute on demand, cache keyed by (feature, version, params, data version)** — best of both, with cache-invalidation complexity.

Considerations: this has direct **look-ahead** consequences (R20). A stored
feature table is easy to join carelessly against a future timestamp. A streamed
feature that only ever sees past data is structurally safer. Weigh that against
backtest iteration speed, which dominates research productivity.

**Lean:** hybrid, with the cache key including the feature version *and* the data
version, and with the cache never being the source of truth.

> **Decision:**
> **Date:**
> **Rationale:**

## D-15 — Feature storage schema
**Status:** OPEN

Features come in at least four shapes: instrument-level (VWAP, Greeks),
market-level (volume profile, structure), chain-level (GEX), and event-shaped
(BOS occurrences, big trades). One schema will not fit all of them gracefully.

- Generic long table (`feature, version, timestamp, key, value`) — one schema, easy to add features; loses types, awkward for multi-column features like a full profile.
- One table per feature, typed — natural and readable; more schemas to manage.
- Grouped by feature class (instrument / market / chain / event).

**Lean:** per-feature typed tables, with a shared naming and metadata
convention. The generic long table looks elegant and becomes miserable the
first time a feature has eight correlated outputs.

> **Decision:**
> **Date:**
> **Rationale:**

## D-16 — Feature versioning mechanism
**Status:** OPEN · **Requirement:** R24

Version in the path (`features/gex/v1/`), in a column, or in a manifest? How does
a strategy declare which version it wants — pinned explicitly, or latest?

**Lean:** pinned explicitly. "Latest" silently changes historical results, which
is precisely what R24 forbids.

> **Decision:**
> **Date:**
> **Rationale:**

## D-17 — Feature engine execution model
**Status:** OPEN · **This is the hardest decision in the document**

- **Vectorized batch** (pandas/polars over whole series) — fast, natural for research, easy to express. Trivially easy to introduce look-ahead. Doesn't translate to live.
- **Event-driven incremental** (state updated per bar/event) — same code can run live; look-ahead is structurally impossible. Slower, more code, harder to express profile/structure logic.
- **Both**, with a parity test asserting identical output.

Considerations: the concept doc's central promise ("one system, five modes")
depends on this. Vectorized-only breaks it. Event-driven-only makes research
slow. Both is honest but doubles the work and the parity test is itself
non-trivial.

**Lean:** event-driven for anything with state (structure, profile, footprint,
running VWAP) where the look-ahead risk is highest; vectorized where the feature
is genuinely stateless per-bar. Decide per feature, not globally, and record
which is which.

> **Decision:**
> **Date:**
> **Rationale:**

## D-18 — One implementation for historical and live, or two?
**Status:** OPEN · Follows from D-17

If two: what proves they agree? A replay-parity test — run recorded live data
through both paths and assert identical features — is the only real answer, and
it must exist before you trust a forward test.

> **Decision:**
> **Date:**
> **Rationale:**

## D-19 — Option pricing model, and whether to compute greeks at all
**Status:** BLOCKED by S-04 · **Draft assumed:** Black-Scholes, unqualified

**New first question:** Dhan supplies delta, gamma, theta, vega and IV on the
live chain, and IV in the expired-options response. So:

- **Use provider greeks.** Free, no model choices, consistent with what the broker shows. But: undocumented methodology, unversionable, unavailable for the Breeze historical chain (which is where your GEX history comes from), and it breaks R7's reproducibility requirement outright.
- **Compute your own.** Reproducible, versioned, works uniformly across both historical sources. More work, and more ways to be wrong.
- **Both** — compute your own, use the provider's as a validation reference.

**Lean:** the third. You need your own for the Breeze historical chain
regardless, and having a free reference implementation to check against is
unusually lucky — most projects never get that.

**Then the model questions**, unchanged: Black-76 on futures vs Black-Scholes on
spot. IV solver choice and convergence handling. Risk-free rate source and
tenor. Dividend treatment. What to do with strikes that fail to solve — null,
flag, or interpolate (and interpolation is inference, so it must be labelled).

⚠ **Market-agnostic check.** Take **exercise style** (European/American) and
**settlement time** (close / AM / PM) as parameters from the market profile
rather than constants. NSE index options are European and close-settled, so
hardcoding costs nothing today — but ES options are American and monthly SPX is
AM-settled, and retrofitting either into a finished greek engine is a rewrite of
its core. Two parameters now, no second implementation required.

Every input recorded per Greek version (R7).

> **Decision:**
> **Date:**
> **Rationale:**

## D-20 — GEX dealer-positioning convention
**Status:** BLOCKED by S-05 · **This is a research question, not an implementation detail**

The sign convention determines whether your signals are right or exactly
inverted. The US-market convention in the research report may not transfer to
NSE's retail-heavy option-selling market.

- Copy the standard convention (dealers short calls / long puts) and validate empirically.
- Infer positioning from OI change plus price action.
- Compute both, treat the choice as a strategy parameter, and let backtests adjudicate.

**Lean:** the third. You do not know the answer, and versioned features exist
precisely so that you can carry `gex_v1` and `gex_v2` with different conventions
and test which describes the market better.

⚠ **This is a per-market property, not a constant** (`08`). The convention that
fits NSE's retail-heavy option selling may not fit SPX's dealer-intermediated
flow, and vice versa. It belongs in the GEX config (D-53), not in the formula.

> **Decision:**
> **Date:**
> **Rationale:**

## D-21 — Underlying reference for option calculations
**Status:** BLOCKED by S-04

Index spot, or same-expiry futures? They diverge by the basis, and the choice
changes every delta and gamma in the chain. Must be consistent between the Greek
engine and the GEX engine, and recorded in the version.

> **Decision:**
> **Date:**
> **Rationale:**

## D-22 — Volume profile construction
**Status:** OPEN

- Bin sizing: fixed tick multiple, fixed count of bins, ATR-scaled, instrument-specific?
- Value area: standard 70%, or parameterised?
- HVN/LVN definition — this is genuinely ambiguous and needs an explicit rule.
- From 1-minute bars, how is volume distributed across the bar's price range? Uniform? All at close? At typical price? **This choice materially changes POC** and is the reason profiles from 1m bars differ from tick-built profiles.

That last point deserves emphasis: a volume profile built from 1-minute OHLCV is
an approximation of a tick-built profile, and its error is not small. Decide
whether that is acceptable for the Breeze period.

> **Decision:**
> **Date:**
> **Rationale:**

## D-23 — Market structure algorithm
**Status:** OPEN

- Swing detection: N-bar fractal, ZigZag percentage, ATR-based, or something else?
- Parameters, and whether they're fixed or per-instrument.
- BOS vs CHOCH definitions — close-through or wick-through? Confirmation bars?
- Timeframe: computed on 1m only, or multi-timeframe?

Considerations: expect several versions. This is the feature most likely to be
"correct" by three different definitions, and visual validation (R23) matters
here more than anywhere else.

> **Decision:**
> **Date:**
> **Rationale:**

## D-24 — Trade classification for footprint
**Status:** OPEN (was BLOCKED — tick data confirmed available)

Real tick data with best bid/ask in the same packet, so classification is
viable. Which rule: tick rule, quote rule, Lee-Ready, or bulk-volume
classification?

Two wrinkles specific to this feed:

- **Timestamps are epoch seconds.** Multiple trades share a timestamp; intra-second ordering must come from your own receive time. Decide whether classification depends on sequence (it usually does) and how you establish it.
- **No aggressor flag.** Side is always inferred from LTP against best bid/ask.

R12 requires observed and inferred to be distinguishable **in the stored data**,
not just documented. That applies to every classified field here.

**Forward-only** — see D-46.

> **Decision:**
> **Date:**
> **Rationale:**

## D-25 — Big trade definition
**Status:** OPEN (was BLOCKED)

Percentile, ratio to rolling median, or z-score? Rolling window length. Per
instrument or per instrument-type. Side inference shares D-24's problem.

⚠ **Verify the int16 ceiling first (S-03).** Last traded quantity is a 16-bit
field, max 32,767. If large option prints truncate, wrap, or saturate, they
corrupt precisely the feature this decision is about — and they'd do it
silently, in the tail of the distribution where big-trade detection lives.
Resolve this before designing the threshold.

**Forward-only** — see D-46.

> **Decision:**
> **Date:**
> **Rationale:**

## D-26 — Continuous futures series
**Status:** OPEN · Possibly unnecessary

Do you actually need one? For a 1-minute intraday system trading the front
month, possibly not. If yes: roll trigger (days-to-expiry, volume crossover, OI
crossover) and adjustment method (none, ratio, difference) — and the adjusted
series must never be used for anything requiring true traded prices.

**Lean:** defer. Don't build it until a strategy needs it. If you do build it,
the roll rule is per-market (NSE monthly futures vs ES quarterly), so it belongs
in the market profile rather than the continuation code.

> **Decision:**
> **Date:**
> **Rationale:**

## D-27 — Option chain as object or query
**Status:** OPEN · **Draft assumed:** logical object, not a physical file

- Materialize chain snapshots at each timestamp (fast reads; large; redundant).
- Build the chain on demand from canonical data (no duplication; repeated cost).
- On demand plus cache (D-14 again).

Also: what defines chain membership at a past timestamp? All strikes that ever
existed for that expiry, or only those with data at T? A strike with no trades
still has OI and still contributes to GEX — this is not a trivial question.

> **Decision:**
> **Date:**
> **Rationale:**

---

# C. Engine

## D-28 — Build the backtester or adopt one?
**Status:** OPEN · **Draft implied:** build; **research report suggested:** Backtrader or LEAN

- **Build custom** — exact fit for option chains, GEX, multi-instrument, and your market-state model. Full control of timing semantics. Months of work, and you will rediscover known bugs.
- **Backtrader** — mature, multi-feed, customisable. Not designed for option chains of hundreds of instruments; feeding chain-level features is awkward; project activity is low.
- **LEAN / QuantConnect** — powerful, real live support. Heavy, C#-flavoured, no NSE F&O data, large learning curve.
- **vectorbt** — very fast parameter sweeps. Not event-driven; wrong shape for order-flow and path-dependent execution.
- **Hybrid** — vectorbt for fast idea screening, a custom event-driven engine for anything that reaches serious validation.

Considerations: the awkward truth is that your requirements (chain-level
features, options as first-class, custom market-state object, order-flow) are
exactly where general-purpose engines fit worst. Adoption saves less than it
looks. But building your own delays first research results by months, and
research results are the point.

**Lean:** the hybrid. Screen ideas vectorized on 1m bars where the strategy
allows it; build a minimal custom event-driven loop for the path-dependent
work. A minimal correct replay loop is smaller than it sounds — the complexity
lives in execution modelling (D-31), not in the loop.

> **Decision:**
> **Date:**
> **Rationale:**

## D-29 — Event-driven or vectorized backtesting
**Status:** OPEN · Interacts with D-17, D-28

Same tension as D-17, one layer up. Path-dependent exits (SL/TP touched
intrabar), MAE/MFE, and any order-flow strategy need event-driven. Simple
signal-and-hold research does not.

> **Decision:**
> **Date:**
> **Rationale:**

## D-30 — Execution timing model
**Status:** OPEN · **Requirement:** R19

- Signal on bar close → fill at next bar open (simple, conservative, deterministic).
- Fill at next bar's VWAP or typical price.
- Configurable delay (N bars / N seconds).
- Intrabar simulation where sub-minute data exists.

And: how are SL/TP evaluated within a bar when you only have OHLC? If both SL
and TP fall inside the same bar's range, which fills first? There is no correct
answer from OHLC alone — pick the pessimistic assumption and record it, because
the optimistic one silently inflates every result.

> **Decision:**
> **Date:**
> **Rationale:**

## D-31 — Fill, slippage and cost model
**Status:** OPEN

Brokerage, STT, exchange charges, GST, stamp duty, SEBI fees — the Indian F&O
cost stack is not a single percentage, and it differs between futures and
options and between buy and sell sides. Slippage: fixed ticks, spread-based,
volume-participation-based? Liquidity assumptions for far strikes, which is
where option backtests most often lie to you.

**Lean:** build the real cost stack early. A strategy that is profitable before
costs and unprofitable after is the single most common way research time gets
wasted.

⚠ **Market-agnostic check.** Make the cost model a pluggable component that the
engine calls, not a function with Indian tax names in it. The US stack (SEC fee,
ORF, OCC clearing, exchange fees) shares no components with the Indian one, but
the *interface* — given a fill, return itemised costs — is identical. Get the
interface right; implement only NSE.

> **Decision:**
> **Date:**
> **Rationale:**

## D-32 — Market state object shape
**Status:** OPEN · **Draft assumed:** a populated snapshot object

- Eagerly populated snapshot (simple to consume; computes everything every bar, including features the strategy ignores).
- Lazy accessor interface (`state.gex(...)` computes on access — efficient; harder to snapshot for lineage).
- Immutable snapshot with lineage id, satisfying R24's traceability requirement.

Considerations: R24 wants a feature snapshot recorded per signal so you can ask
"why did the system take this trade?". Lazy evaluation makes that harder. Some
form of "what did the strategy actually look at" capture is needed either way.

> **Decision:**
> **Date:**
> **Rationale:**

## D-33 — Strategy interface
**Status:** OPEN

Callback (`on_bar(state)`), generator, or declarative rule spec? How does a
strategy declare which instruments and features it needs, so the engine knows
what to compute? How are multi-leg option positions expressed?

> **Decision:**
> **Date:**
> **Rationale:**

## D-34 — Portfolio and margin modelling depth
**Status:** OPEN

Simple cash accounting, or SPAN/exposure margin approximation? For option
selling strategies, margin is a first-order constraint on returns and ignoring
it makes results meaningless. For buying strategies it barely matters.

**Lean:** decide once you know whether you'll be short options. If yes, this
becomes important early rather than late.

> **Decision:**
> **Date:**
> **Rationale:**

## D-35 — Where does risk live?
**Status:** DEFERRED (Phase 7) unless argued otherwise

Is the risk layer active during backtests, or only live? If only live, backtest
results overstate what the live system would have done — position limits and
daily-loss cutoffs change realised outcomes.

**Lean:** model risk in the backtest too, even crudely. Otherwise forward and
historical results aren't comparable, which R21 requires them to be.

> **Decision:**
> **Date:**
> **Rationale:**

---

# D. Live data

## D-36 — Provider split
**Status:** DECIDED (pending S-01 confirmation) · **Draft assumed:** Breeze historical, Dhan live

The documentation resolves this. Three roles, not two:

| Role | Provider | Because |
|---|---|---|
| Bulk historical (equity, index, futures, 1-min + OI) | **Dhan** | 100k req/day, 90 days/poll, 5 yrs — 20× Breeze's throughput |
| Historical option chains (absolute strikes, expired) | **Breeze** | Only source that addresses contracts by expiry + right + strike. Dhan's expired-options is ATM±10 rolling |
| 1-second historical (few core instruments) | **Breeze** | Only source offering it |
| All live (ticks, depth, chain + greeks) | **Dhan** | Tick-by-tick, 20/200-level, chain every 3s, ~₹499/m |
| Execution (later) | **Dhan** | Already integrated; Breeze prohibits market orders |

Consequence: **two historical adapters, not one.** That's more work than the
drafts assumed, and it's the main argument for keeping the adapter layer strict.

Free benefit: futures are covered by both, giving you a cross-provider
validation set for R17's "one timeline" claim (S-06).

> **Decision:** Dhan for bulk historical + all live + execution; Breeze for
> historical option chains and 1-second. Confirm on S-01.
> **Date:**
> **Rationale:**

> **Decision:**
> **Date:**
> **Rationale:**

## D-37 — Recorder architecture
**Status:** DEFERRED (Phase 1 — moved up, see 07) · **Requirement:** R16

Write path: append-only line format then compact to columnar, or direct
columnar writes? Process model: one process per instrument group, or one for
all? Restart and gap-recovery behaviour. Checkpoint contents and frequency.
Monitoring — how do you find out it stopped at 09:20 rather than at 15:30?

**Lean:** append-only raw writes during the session, compaction after close.
Simplest thing that survives a crash mid-write, which is the failure that
actually happens.

> **Decision:**
> **Date:**
> **Rationale:**

## D-38 — Depth representation
**Status:** BLOCKED by S-02 (volume only) · **Draft assumed:** long-form level rows

Level counts are now known — and there are three tiers, which is itself a
decision:

| Tier | Levels | Instruments | Source |
|---|---|---|---|
| Full packet | 5 (with order counts) | 5,000/conn × 5 | free inside the main feed |
| 20-level | 20 | 50/conn × 5 ≈ 250 | separate socket |
| 200-level | 200 | **1/conn × 5 ≈ 5** | separate socket |

So: which instruments get which tier? 200-level is scarce enough that it's a
deliberate allocation (NIFTY futures? the index?), not a default.

Representation: long-form (`timestamp, instrument, side, level, price, qty,
orders`) vs wide. Long is flexible and much larger — at 200 levels it's 400 rows
per snapshot per instrument, so measure before committing (S-02). Also: full
snapshots or deltas?

> **Decision:**
> **Date:**
> **Rationale:**

## D-39 — Event time vs receive time
**Status:** OPEN · **Requirement:** R16

Both are recorded — that much R16 settles. Open: which one drives feature
computation and bar boundaries during live operation? Event time is correct but
requires handling late arrivals; receive time is simple but makes live and
replay diverge, which breaks R21's reproducibility promise.

> **Decision:**
> **Date:**
> **Rationale:**

## D-40 — End-of-day finalization
**Status:** DEFERRED (Phase 5)

What runs after close: validation, canonicalization, comparison against any
overlapping provider data, promotion to the research archive. Automatic or
gated on a human looking at the quality report? What happens to a day that
fails validation — quarantined, or ingested with a flag?

> **Decision:**
> **Date:**
> **Rationale:**

---

# E. Tooling and infrastructure

## D-41 — Core language and dataframe library
**Status:** BLOCKED by S-02, S-07

Python is assumed throughout. Within it: pandas (ubiquitous, familiar, slow,
memory-hungry), polars (fast, lower memory, less mature ecosystem), DuckDB SQL
(excellent for joins and aggregations, awkward for iterative stateful logic), or
a mix by task.

**Lean:** pick whichever you'll actually be productive in. At research volumes
the performance difference matters less than your iteration speed, right up
until it suddenly doesn't — and S-02 tells you which regime you're in.

> **Decision:**
> **Date:**
> **Rationale:**

## D-42 — Repository and module layout
**Status:** OPEN

Single package with modules, or separate installable packages per layer
(ingest / canonical / features / engine / strategies / viz)? Where do
strategies live — in-repo or separate? How do notebooks relate to library code?

**Lean:** one repo, clear module boundaries mirroring the layer model, strategies
in-repo initially. Split later if a boundary proves it deserves to be a package.

> **Decision:**
> **Date:**
> **Rationale:**

## D-43 — Visualization stack
**Status:** OPEN · **Requirement:** R23 (this is a required tool, not a nicety)

Plotly, Bokeh, lightweight-charts, mplfinance, a custom web frontend, or
exporting to TradingView? Requirements: candles with many overlays, footprint
rendering (hard — most libraries can't), profile histograms, entry/exit markers,
and fast enough to actually use while iterating.

**Lean:** start with whatever renders a day of candles plus overlays in one
line, and treat footprint rendering as a separate later problem. Don't let the
charting choice block feature work.

> **Decision:**
> **Date:**
> **Rationale:**

## D-44 — Validation framework
**Status:** OPEN · **Requirement:** R25

Custom check functions, Great Expectations, pandera, or plain assertions in the
ingest path? Where do quality reports live and who reads them? Does failing
validation block promotion to canonical, or just warn?

**Lean:** custom checks, plain and readable, run as a gate on promotion. The
frameworks add ceremony that a single-user research system doesn't need.

> **Decision:**
> **Date:**
> **Rationale:**

## D-45 — Compute and storage environment
**Status:** BLOCKED by S-02

Local machine, NAS, or cloud? Backup strategy for data that cannot be
re-acquired — recorded live data is irreplaceable in a way historical data is
not, and deserves different treatment. Budget ceiling.

> **Decision:**
> **Date:**
> **Rationale:**

---

# F. Scope gates

*These are not technical decisions. They are decisions about what the project is.*

## D-46 — Order flow: scope and history
**Status:** DECIDED

**Two findings, opposite directions.**

*Buildable:* Dhan's feed is tick-by-tick, with LTP, last traded quantity and
best bid/ask in the same packet, plus 20- and 200-level depth. R12 and R13 are
achievable. The original research report's "1-second snapshots" claim was wrong.

*No history:* neither provider offers historical order flow. Breeze's 1-second
data is 1-second **OHLCV** — no bid/ask, no per-trade quantity, no side. It is a
finer bar, not a tape.

**Decision: order-flow features are forward-only by design.** They will not be
backtested, and no attempt will be made to approximate them from historical
bars. Footprint, delta, absorption, imbalance and big trades are validated in
forward testing against recorded data, not against history.

Three consequences that follow and should not be re-litigated later:

1. Order-flow features move out of Phase 2 (historical features) into Phase 5/6.
2. **The clock starts when the recorder starts.** Every month before then is a month those features can never be evaluated over. This is the strongest argument for moving the recorder earlier — see `07-build-order.md`.
3. Strategies combining order flow with GEX/structure/profile can only be validated forward. Strategies using only historical-capable features can be backtested normally. Keep the two classes separate in the research plan rather than discovering the constraint mid-experiment.

> **Decision:** Order flow is in scope, live/forward only. No historical
> backtesting of order-flow concepts; no bar-derived approximations.
> **Date:**
> **Rationale:** Tick data available prospectively; no historical equivalent
> exists from any accessible provider. Approximating from bars would produce
> features whose estimation error is invisible in aggregate statistics.

## D-47 — Which strategy hypothesis is first?
**Status:** OPEN

The draft names GEX reversals. That remains the hypothesis requiring the most
infrastructure: chains, Greeks, GEX, structure, and a validated dealer
convention (S-05) — plus a multi-week Breeze chain pull (D-50).

The good news is it's now *possible* — Breeze's absolute-strike historical
chains mean GEX reversal can genuinely be backtested, which was in doubt before.

Two classes of hypothesis to keep separate:

| Class | Features | Testable |
|---|---|---|
| **Historical-capable** | VWAP, volume profile, structure, GEX, greeks, OI/price | Backtest normally |
| **Forward-only** | anything using footprint, delta, absorption, big trades | Forward testing only (D-46) |

**Lean:** first strategy exists to test the *pipeline*, not to make money — pick
something trivial on futures alone. Then GEX reversal as the first real
hypothesis, since it's now backtestable. Order-flow hypotheses come last, and
only once the recorder has accumulated enough forward data to say anything.

> **Decision:**
> **Date:**
> **Rationale:**

## D-48 — How much is built before the first backtest runs?
**Status:** OPEN · **This is the decision that determines whether the project finishes**

Principle #1 says design from the complete end state. Taken literally, that
means a year of infrastructure before the first result.

The alternative: design the *data model* from the end state (because that's
genuinely expensive to change later), and build everything else thinly, in the
order research demands.

**Lean:** get one strategy running end to end on a single instrument, on one
month of data, as early as possible — even with a crude engine, no options, no
features beyond VWAP. Everything you learn from that changes the decisions
above, and you'd rather learn it before committing to them than after.

Two things now compete for "earliest": the thin slice, and starting the
**recorder**. They don't conflict — the recorder depends on almost nothing
upstream, and under D-46 every day it isn't running is a permanently lost day of
order-flow history. Run both early.

> **Decision:**
> **Date:**
> **Rationale:**

## D-49 — Breeze session token handling
**Status:** BLOCKED by S-07 · **NEW**

Breeze session tokens must be regenerated **manually every day** (SEBI
requirement), valid 24 hours or until midnight. TOTP is available.

This collides directly with D-50: a multi-week bulk pull cannot survive an
unattended token expiry, and the failure may be silent rather than loud.

- How far does TOTP automation actually get you?
- What does the client do mid-pull when the token dies — error, or empty results?
- Is a supervised long-running pull acceptable, or does this need a daily manual step for weeks?
- Does the daily ingestion pipeline (post-launch) need the same treatment?

**Lean:** whatever you do, make token expiry produce a loud, unambiguous failure
in your ingestion code. Silent empty responses are already a known hazard with
this API (S-01); an expired token producing the same symptom would be very hard
to diagnose after the fact.

> **Decision:**
> **Date:**
> **Rationale:**

## D-50 — Historical chain pull: scope and schedule
**Status:** BLOCKED by S-01, S-02 · **NEW**

The Breeze chain pull is the single largest one-time operation in the project.
Rough prior: **~8 days of continuous pulling per year of NIFTY chain history**,
so roughly 6 weeks for 5 years — bounded by 5,000 requests/day and 1,000 candles
per request.

Scope decisions, each of which multiplies the schedule:

- **How many years?** 5 is available; 1 or 2 may be enough to start research.
- **Which underlyings?** NIFTY only, or BANKNIFTY too, or stock options.
- **Which expiries?** All live expiries at each date, or front weekly only.
- **How wide a strike ladder?** Full chain is what GEX needs; a truncated ladder reintroduces exactly the limitation that made Dhan's ATM±10 insufficient.
- **Which resolution?** 1-minute (feasible) — 1-second for chains is not.

Sequencing question that matters more than it looks: **do you start the pull
before or after Phase 1 is designed?** Starting early gets data flowing but
risks pulling into a schema you later change. Starting late delays research by
weeks.

**Lean:** pull raw provider responses to disk immediately once S-01 confirms it
works, without waiting for the canonical schema. Raw is immutable and
re-normalizable by definition (D-02) — that's exactly what the raw layer is for.
Start with 1 year of NIFTY front-weekly to validate the pipeline end to end,
then widen.

⚠ Interacts with D-49: a six-week pull needs a token strategy first.

> **Decision:**
> **Date:**
> **Rationale:**

---

# G. Market abstraction

*From `08-market-abstraction.md`. The aim is that adding US options later is a
config-and-adapter exercise, not a rewrite. These decisions define the seams.*

## D-51 — Market rules as time-versioned data
**Status:** OPEN · **NEW** · **Blocks:** Phase 1

Contract specs, expiry calendars, session times, tick sizes and settlement rules
all change over time. Applying today's rules to older data contaminates
backtests silently.

- **Constants in code** — simplest, wrong the moment anything changes, and wrong invisibly.
- **One time-versioned market-rules store** (`valid_from`/`valid_to` rows keyed by market + rule type) — uniform mechanism, one lookup pattern, extends to US without new machinery.
- **Per-concern versioning** — contract specs in the instrument master (D-06), calendars separately, costs separately. Less uniform; possibly more natural per concern.

Considerations: how does a feature or the engine *ask* for rules at time t? A
single `rules_as_of(market, t)` accessor is easy to audit and easy to enforce —
if analytics can only get market facts one way, hardcoding becomes visible in
review.

Known NSE changes to encode (**verify dates against exchange circulars**): lot
size / contract value revisions; weekly expiry restricted to one benchmark index
per exchange; weekly expiry day changes; session and special-day timings; tick
size revisions.

**Lean:** one store, one accessor. The uniformity is worth more than the
per-concern fit, mainly because it gives you a single place to check whether a
rule was applied anachronistically.

> **Decision:**
> **Date:**
> **Rationale:**

## D-52 — Expiry as calendar data, not computed rule
**Status:** OPEN · **NEW**

- **Computed** (`last_thursday(month)`, `nth_friday(3)`) — compact; encodes one market's rules in code; breaks on every rule change and on every holiday shift.
- **Dated calendar** — a table of actual expiry dates per underlying and series, time-versioned, populated from the exchange or the instrument master. Verbose, boring, correct.
- **Rule DSL** — a configurable expression language for expiry rules. Flexible; a small language to build, debug and version, for a problem a table solves.

Considerations: expiry dates shift for holidays. Rules changed. Series
proliferate (weekly, monthly, quarterly, EOM, daily). A table absorbs all of
that without code changes; the other two don't.

**Lean:** dated calendar. This is the clearest case in the whole abstraction
where data beats code — and note it's also *less* work than the alternatives,
not more.

> **Decision:**
> **Date:**
> **Rationale:**

## D-53 — GEX configuration object
**Status:** OPEN · **NEW** · Interacts with D-20, D-21

The calculation is common; scope, parameters and interpretation are not. What
does a `gex_config` hold?

Candidates: expiry scope (all listed / nearest N / DTE window), contract
multiplier source (→ D-51), dealer-positioning convention (→ D-20),
underlying reference (spot vs future, → D-21), strike-range limits, level
identification method.

Considerations: expiry scope differs sharply by market — NSE concentrates in the
near weekly; SPX carries a large 0DTE component plus AM-settled monthlies. "All
expiries" and "nearest only" are different features, not different settings, and
which is right is empirical.

The config must be captured in the feature version, so a stored GEX series
records exactly what produced it. Otherwise cross-market comparison is
meaningless and cross-time comparison is unreliable.

> **Decision:**
> **Date:**
> **Rationale:**

## D-54 — How far to take the abstraction now
**Status:** OPEN · **NEW** · **The judgement call in this section**

Full generality now is a mistake — abstractions built without a second
implementation are shaped by guesses. The proposal in `08` is: get the seams
right, implement only NSE.

Seams to fix now (cheap now, migration later): market-namespaced instrument
identity (D-05), time-versioned rules (D-51, D-06), dated expiry calendars
(D-52), timezone and currency as fields (D-07), pluggable cost model (D-31),
exercise style and settlement time as greek parameters (D-19), GEX config
(D-53).

Explicitly **not** now: US market profiles as working code, US adapters, margin
models you don't use, cross-currency accounting, generic multi-asset-class
modelling.

Validation, and it's nearly free: **write the SPX and ES market profiles as
config files only** — no adapter, no data, no code. Then see whether the core
can load them. Every gap found costs minutes now and a migration later. Run it
once in Phase 1 and again after Phase 2.

> **Decision:**
> **Date:**
> **Rationale:**

## D-55 — Where does market knowledge live?
**Status:** OPEN · **NEW**

Proposed boundary: adapters and the market-profile store may know about markets.
Canonical data, feature engine, and strategies may not — they receive rules
through injection.

Open: how is that enforced? Convention and code review, a lint rule, or a type
signature that makes market facts unreachable except via `rules_as_of`?

Considerations: this is the difference between an abstraction that holds and one
that erodes. The first hardcoded `if market == "NSE"` in a feature is where it
starts, and it will look entirely reasonable at the time.

> **Decision:**
> **Date:**
> **Rationale:**

---

# Decision log

Record closed decisions here as you go, so the state is visible at a glance.

| ID | Decision | Date | Status |
|---|---|---|---|
| | | | |

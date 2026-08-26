# 02 — Requirements

*What the system must be able to do. Deliberately stripped of "how" — every
schema, format and layout that appeared here in the draft has moved to
`05-decision-register.md`.*

**Mark each requirement as you read: `MUST` / `LATER` / `CUT`.** The original
draft is maximalist. Some of this may not survive the data-availability spikes
in `06-spikes.md`, and some of it you may simply not want.

---

## R1 — Purpose

Transform a discretionary process based on market structure, VWAP, volume
profile, footprint, big trades, option Greeks, GEX, and futures/options
positioning into a measurable, backtestable, forward-testable, eventually
real-time system.

No architectural constraints are inherited from any previous implementation.

## R2 — Five capabilities, one data model

```
Historical research → Feature generation → Backtesting → Forward testing → Real-time trading
```

The same conceptual market-data and feature model must support all five.
*(This is a requirement on the model, not a claim that one code path serves
both batch and streaming — see D-17/D-18.)*

## R3 — Providers

Three roles across two providers (D-36):

| Role | Provider |
|---|---|
| Bulk historical — equity, index, futures, 1-min + OI | **Dhan** |
| Historical option chains — absolute strikes, incl. expired | **Breeze** |
| 1-second historical — few core instruments | **Breeze** |
| All live — ticks, depth, chain with greeks | **Dhan** |
| Execution (later) | **Dhan** |

This means **two historical adapters**, not one. Neither provider is assumed
permanent. Provider-specific logic stays inside the adapter layer; feature and
strategy layers must not import provider APIs.

### Required historical coverage

| Instrument | Fields |
|---|---|
| Equity | OHLCV, metadata |
| Index | OHLCV, metadata |
| Futures | OHLCV, OI, contract metadata |
| Options | OHLCV, OI, contract metadata, full chain coverage where available |

Primary research resolution: **1 minute**, with 1-second available from Breeze
for a small number of instruments (affordable for index and futures, not for
option chains — D-08). The architecture must not assume any single resolution is
permanent, and must tolerate resolution varying by instrument class.

Live data must be retained at its highest useful resolution — tick-by-tick —
rather than immediately reduced to 1-minute candles.

> ⚠ Breeze's coverage claims remain unverified. See S-01.

## R4 — Instruments

Must support at minimum: `EQUITY`, `INDEX`, `FUTURE`, `OPTION`.

Every instrument needs a **stable internal identity** that is not its display
symbol and not its file path. For derivatives, identity includes market/venue,
underlying, expiry, strike, and option type where applicable. The market
dimension is required from the start — retrofitting it means rewriting every
stored key (D-05, R27).

Reference data (what an instrument *is*) must be separate from market data
(what *happened* to it). → D-05, D-06

Instrument type must be explicit, never inferred from symbol naming.

## R5 — Historical market data

Canonical model must be able to carry: timestamp, instrument identity, OHLC,
volume, open interest. Not every instrument has every field. → D-04, D-09, D-10

Timestamps must be timezone-aware and their bar-labelling semantics explicit.
→ D-07

## R6 — Options as a first-class dataset

The option chain must be a first-class research object, reconstructible at any
historical timestamp:

```
Underlying → Expiry → all available strikes → CE + PE
```

Required for historical Greeks and GEX. → D-27

## R7 — Greeks

Calculate IV, Delta, Gamma, Theta, Vega from historical option data.

Dhan supplies greeks and IV on its live chain, but not for the Breeze historical
chain — which is where GEX history comes from. So own greeks are required
regardless; the provider's serve as a validation reference (D-19).

Greeks are **derived values, not observations**. They belong to
(option, timestamp) and must be reproducible: inputs, model and assumptions
recorded and versioned. Improving the methodology must not mutate the
underlying market data. → D-19, D-21

## R8 — GEX

Chain-level derived feature:

```
option price + OI + gamma + contract specs
  → GEX per option → GEX by strike → aggregate GEX → market GEX levels
```

Must support: GEX by strike, total GEX, positive/negative GEX, gamma flip,
major GEX levels, GEX regime.

Must be computed using only information available at that timestamp — never
later OI, later prices, later chain composition, or end-of-day values.
→ D-20 (the dealer-positioning convention is a genuine open research question,
not a formula to copy)

Historical GEX depends on the Breeze chain pull (D-50), which is a multi-week
operation. Dhan's expired-options data is ATM±10 rolling and is **not** a
substitute — total GEX and gamma flip need the full ladder.

## R9 — Market structure

Convert discretionary structure reading into explicit features:
`swing_high`, `swing_low`, `HH`, `HL`, `LH`, `LL`, `BOS`, `CHOCH`,
`liquidity_sweep`, `rejection`.

Every one needs a deterministic definition. A strategy cannot depend on "this
looks like a break of structure". → D-23

Structure should emit **events** (timestamp, type, direction, price, reference
swing, method version), not just boolean columns.

## R10 — VWAP

Session VWAP at minimum; anchored VWAP and other variants should be possible.
Reset/anchor semantics must be part of the definition.

## R11 — Volume profile

`POC`, `VAH`, `VAL`, `HVN`, `LVN`, `volume_at_price`.

Profiles for: session, previous session, custom range, opening range,
historical range. Profile definition must be explicit and versionable, and each
profile carries its own metadata (start, end, type, method version). → D-22

## R12 — Footprint

Reconstruct aggressive buying/selling. Inputs: trade price, quantity,
timestamp, bid, ask, and depth where available. Derived: `buy_volume`,
`sell_volume`, `delta`, `imbalance`, `stacked_imbalance`, `absorption`,
`exhaustion`, `volume_at_price`.

The system must distinguish what was **observed** from what was **inferred**.
Trade classification methodology must be explicit. The underlying
volume-at-price representation should be retained so different footprint
calculations can be regenerated. → D-24

> ✅ **Buildable, forward-only.** Dhan's live feed is tick-by-tick with LTP, last
> traded quantity and best bid/ask in the same packet, so classification is
> viable. But **no historical order-flow data exists** — Breeze's 1-second data
> is 1-second OHLCV, a finer bar rather than a tape.
>
> **Decision (D-46): order-flow features are forward-only by design.** They are
> not backtested, and are not approximated from historical bars. They are
> validated in forward testing against recorded data. Consequence: the clock
> starts when the recorder starts.

## R13 — Big trades

Identify unusually large transactions. A fixed quantity threshold is not
sufficient as the primary definition — support dynamic definitions (percentile,
ratio to rolling median, z-score).

Derived: `large_trade_count`, `large_buy_volume`, `large_sell_volume`,
`large_trade_pressure`. Direction inferred from market context, never from an
assumed sign convention on quantity. → D-25

*Same tick-data dependency and same forward-only scope as R12.*

⚠ Last traded quantity is a 16-bit field (max 32,767). Verify large prints don't
truncate before designing thresholds — the failure would be silent and would sit
exactly in the tail this feature cares about (S-03).

## R14 — Futures positioning

Price, volume, OI, OI change — enabling research into the four
price/OI quadrants.

Different expiry contracts must remain separate records. A continuous series,
if needed, is generated later by an explicit rollover method — never by
silently stitching. → D-26

## R15 — Three data layers

| Layer | Contains | Property |
|---|---|---|
| **Raw** | exactly what the provider supplied | immutable |
| **Processed** | normalized, validated, canonical | provider differences resolved here |
| **Features** | derived information | versioned, regenerable |

Strategies must not read raw provider payloads. → D-02

## R16 — Live recording

Dhan live data must be recorded permanently as raw events (trades, depth),
not only as derived 1-minute candles. This creates a growing order-flow
dataset usable by future backtests.

The recorder is a production service in its own right: connection loss,
reconnection, duplicate events, out-of-order events, feed gaps, process
restarts, file rotation, partial writes, checkpointing. It must run
independently of the strategy process. → D-37

Both **event time** and **receive time** must be recorded, for latency
measurement and debugging. → D-39

## R17 — Continuous dataset

Breeze historical and Dhan recorded data should form one continuous research
timeline at the canonical level, with source retained as metadata. Raw sources
stay separate. Overlaps must be handled explicitly and compared, never silently
overwritten. → D-12

## R18 — Backtesting

Operates on the same canonical data and feature definitions as everything else.

Must support: equity, index, futures, options, multi-instrument strategies,
option-chain data, GEX, order-flow features.

Must model: entry, exit, SL, TP, slippage, fees, position sizing, contract
specifications, execution timing. → D-28 through D-31

## R19 — Execution timing honesty

A signal from a completed candle executes at the next permissible point. The
system must not pretend information from inside an incomplete candle was known
at its close — a signal that occurred 15 seconds into a minute did not exist at
the minute's open.

The first research version may deliberately accept this loss of intrabar
precision in exchange for determinism. That trade must be recorded as a
decision, not assumed. → D-30

## R20 — Look-ahead prevention

> Only information available at or before the decision timestamp may be used.

Applies especially to Greeks, GEX, option chains, OI, volume profile, market
structure, footprint, big trades.

All time joins must be explicitly directional, with a maximum allowed time
difference, and must forbid future observations. Never an ordinary
nearest-neighbour join. → D-14 (precompute-vs-on-demand has direct look-ahead
consequences)

## R21 — Forward testing

Consumes the live feed, produces simulated executions, records the same
information as the backtester so results are directly comparable.

Recorded live data must be replayable later through the same feature engine and
strategy to reproduce the signals — this is the primary tool for debugging
real-time behaviour.

## R22 — Live execution (later)

Adds risk manager, order manager, broker execution — after sufficient
historical and forward validation. Not part of the first milestone.

Risk lives in its own layer, separate from strategy logic: max position size,
max daily loss, max trade loss, max portfolio exposure, max simultaneous
positions, margin checks, kill switch.

## R23 — Visualization and validation

Charts must be able to overlay candles, VWAP, structure, POC/VAH/VAL/HVN/LVN,
GEX levels, entries, exits, SL, TP, big trades, footprint.

**Purpose is verification, not presentation** — confirming that algorithms
detect what the researcher intended. Every major feature needs a way to
visualize its output. → D-43

## R24 — Reproducibility

Every backtest traceable to: data source, data version, instrument definition,
feature versions, strategy version, parameters, execution assumptions.

Feature calculations are versioned (`gex_v1`, `footprint_v1`, ...). A changed
calculation becomes a new version; it never silently changes historical
results. Versions coexist. → D-13, D-16

Every experiment records: experiment id, strategy version, feature versions,
data version, parameters, time range, instrument universe, execution
assumptions, results.

Every derived object is traceable back down the chain:
`trade → signal → feature snapshot → canonical → raw`. This is how you answer
*"why did the system take this trade?"* → D-32

## R25 — Data quality

Validate: missing timestamps, duplicate records, invalid OHLC, invalid volume,
invalid OI, instrument mismatches, expiry mismatches, strike/type mismatches,
timezone consistency, unexpected gaps, duplicate option contracts, incorrect
contract metadata.

Quality reports generated **before** a dataset becomes a research input.
Validation happens at each layer: raw, canonical, feature, strategy. → D-44

## R26 — Missing data

Gaps are never silently fabricated. If 10:31, 10:32 and 10:34 exist, the system
does not invent 10:33. Any gap-filling is an explicit, feature-specific,
recorded decision. → D-11

## R27 — Market abstraction

*Conceptual model rather than hard requirement — see `08-market-abstraction.md`.*

The core must be built around generic derivatives concepts, with market-specific
details as configurable data rather than embedded assumptions. Target: adding US
options later is a config-and-adapter exercise, not a rewrite.

Abstracted, not assumed: contract specifications, multipliers, lot sizes, tick
sizes, expiry calendars, trading sessions, settlement and exercise rules,
symbols, currencies, timezones, cost stacks, and data providers.

**Market rules are time-versioned.** Structural changes — lot size revisions,
expiry-day changes, discontinued weekly series, session changes — must be
representable as dated rules so they don't contaminate backtests. This applies
to the NSE-only case today, not only to a future US case. → D-51, D-52

For GEX specifically: the calculation framework is common; expiry scope,
multiplier, dealer-positioning convention, underlying reference and
interpretation vary by market. → D-53

Scope discipline: fix the **seams** now, implement only NSE. Do not build
untested US adapters or profiles as working code. → D-54

---

## Architectural principles

These constrain the decisions in `05`. Each is itself open to challenge — but
if you drop one, record why.

1. Design from the complete end state.
2. Keep raw provider data immutable.
3. Use a canonical, provider-agnostic data model.
4. Treat instruments as first-class entities.
5. Preserve real derivative contract identity.
6. Preserve raw live trade/depth data.
7. Separate market data, features and strategies.
8. Make every feature deterministic and versionable.
9. Prevent look-ahead by design, not by discipline.
10. Keep historical and forward execution semantics comparable.
11. Keep provider logic inside adapters.
12. Make research results reproducible.
13. Prefer preserving information over premature aggregation.
14. Never let directory structure become the source of instrument identity.
15. Decide the storage model before collecting the large historical dataset.
16. Keep market rules as time-versioned data, outside the analytics core.

**On #1 and #15:** these two are in tension with the rest of this document set.
Designing from the complete end state is how you get a coherent architecture;
it is also how you get a year of infrastructure and no research results. The
build order in `07` tries to resolve this by designing the *data model* from
the end state while deliberately deferring engine, live, and execution
decisions. #15 is why the spikes come first — you cannot choose a storage model
without knowing the volume.

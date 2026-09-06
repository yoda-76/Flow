# NautilusTrader test checklist

A living checklist, not an evidence log or a decision record — see
`findings.md` and `decisions.md` for those. This file tracks what's been
sanity-checked about NautilusTrader (D-28) versus what's still assumed.
**Rule: even a feature that looks obviously correct from its docstring
gets a real test before we trust it** — it isn't our code, and this
project has already found real bugs in three different pieces of
"trusted" external infrastructure (Breeze's docs, Dhan's API, and
Nautilus's own pandas-compatibility claim) by testing rather than reading.

Status per item: ☐ untested · 🔶 partially tested · ✅ tested, confirmed
working · ❌ tested, confirmed broken/gap (→ becomes a `findings.md` entry
and something we build ourselves).

---

## A. Market rules / time-versioning — the biggest open question

Reasoning so far (not yet fully tested): a rules change (lot size, expiry
weekday) shouldn't require Nautilus to version anything itself — it
requires *us* to construct the correct `Instrument` object per historical
contract from our own D-51 rules store. Each real contract's specs are
fixed for its own life regardless of later rule changes. So the real
question isn't "does Nautilus support versioned rules" but "does it
correctly handle a large, evolving instrument universe."

- ☐ Can many `Instrument` objects for the same logical underlying (different
  contracts across time, e.g. one per weekly expiry over 2 years) coexist
  in one backtest run without cross-contamination?
- ☐ Does the engine actually enforce `activation_ns`/`expiration_ns` —
  refusing or ignoring data for an instrument outside its valid window —
  or does it not check at all (meaning correctness is entirely on us)?
- ☐ **Concrete test**: synthetic backtest with two consecutive weekly
  option contracts carrying *different* lot sizes (simulating a rules
  change). Trade both. Confirm PnL/margin uses the correct lot size for
  each period, not a stale/cached one.
- ☐ Does anything hardcode a single session template/calendar per venue
  globally, rather than accepting whatever timestamps our own data
  provides? Test by feeding a synthetic reduced-hours/special day and
  confirming it's not rejected or silently normalized.
- ☐ Confirm nothing auto-derives lot size/tick size from a "known venue"
  table bundled with Nautilus itself (would silently override our own
  D-51-sourced values) — instruments should only ever carry what we
  explicitly constructed them with.

## B. Backtest engine / historical replay (stated priority — believed to
handle most of this, needs thorough verification before trusting it)

- ☐ **Look-ahead (R20), the most important one**: replay a stream of
  mixed data types (bars + custom OI data + option chain events)
  deliberately fed slightly out of order, and confirm the engine either
  enforces strict chronological delivery to strategies or exposes a clear
  ordering guarantee we can rely on — vs. silently trusting our own
  pre-sort with no engine-level backstop.
- ☐ Fill timing: confirm actual fill behavior matches D-30's decided
  convention (signal on bar close → fill at next bar open), not some
  different Nautilus default we haven't configured away.
- ☐ Same-bar SL/TP ambiguity: when both could trigger within one bar's
  OHLC range, what does Nautilus's matching engine actually do, and can it
  be forced to the "pessimistic fills first" convention D-30 decided?
- ☐ Multi-instrument time sync: with ~200+ instruments (a full option
  chain) loaded, confirm events interleave in true chronological order
  across instruments, not instrument-by-instrument sequentially.
- ☐ Missing-data handling (D-11): confirm absent bars stay absent through
  replay — no silent interpolation/forward-fill introduced by the engine.
- ☐ No silent corporate-action price adjustment — we explicitly don't want
  this (Breeze's data is unadjusted, D-06 territory).
- ☐ Determinism: identical input twice → byte-identical output (R24).
- ☐ Performance at realistic scale: full option chain (~200-460 contracts,
  findings.md D-50), weeks/months of 1-minute bars — does it stay usable,
  and where's the practical ceiling?
- ☐ Timezone handling: does the engine care what timezone bar timestamps
  carry, or is it agnostic as long as we're internally consistent (IST
  throughout, per our data)?

## C. Options chain / GEX attachment (spike question #3, still open)

- ☐ Can `OptionChainSlice`/`subscribe_option_chain` actually be driven by
  our own Breeze/Dhan-sourced data, or is it too tightly coupled to how
  the crypto adapters (Deribit/Bybit/OKX) currently populate it?
- ☐ Can a custom Actor compute an aggregate feature (GEX) from a chain
  snapshot and make it available to other strategies *during a running
  backtest* — not just stored and read back later, actual runtime
  consumption?
- ☐ Does custom OI data (proven for storage round-trip already) actually
  arrive at a running `Strategy.on_data()` handler correctly
  time-synchronized with the matching bars during replay?

## D. Execution simulation

- ☐ Pick 2-3 relevant fill models (`OneTickSlippageFillModel`,
  `VolumeSensitiveFillModel`) and verify their actual fill price against a
  hand-calculated expected value for a small synthetic scenario — don't
  trust the class name.
- ☐ Build a minimal NSE cost-stack `FeeModel` and confirm it's invoked
  correctly per fill, with the right values flowing into realized PnL.
- ☐ Confirm stop-market/stop-limit orders trigger correctly against
  1-minute bar data in backtest mode (not requiring tick data we don't
  have for most of history).
- ☐ Confirm slippage is cleanly configurable to match D-31's real NSE cost
  stack, not fighting a different built-in assumption.

## E. Portfolio & risk

- ☐ Margin: `StandardMarginModel`'s percentage calc, tested against a
  synthetic short-option position with a hand-verified expected margin
  number — confirms/refutes whether it's usable as-is for D-34's
  option-selling gate, or whether a real SPAN approximation is needed
  regardless (already suspected: yes, needed).
- ☐ Multi-leg positions (spreads/straddles): tracked as one combined
  position with joined P&L, or strictly per-leg? Relevant to D-33.
- ☐ Build a minimal custom risk check (e.g. max daily loss) on top of
  `RiskEngine`'s trading-state mechanism (ACTIVE/REDUCING/HALTED) and
  confirm it actually blocks trading when triggered — `RiskEngineConfig`
  itself only covers order-rate/notional limits (confirmed), so this is
  testing whether the extension point actually works, not assuming it
  does because the hook exists.

## F. Data ingestion / persistence

- ✅ Bars round-trip through `ParquetDataCatalog` (tested 2026-09-06,
  findings.md D-28 section).
- ✅ Custom data (`OpenInterestData`) round-trips correctly, real varying
  values, exact match (tested 2026-09-06).
- ☐ Confirm Nautilus's catalog and our own DuckDB-queryable canonical
  Parquet (D-01) stay cleanly separate — the catalog feeds the engine,
  our own store is for ad-hoc research querying. Not yet confirmed this
  separation holds cleanly rather than fighting itself.
- ☐ Catalog read/query performance at realistic scale (current test was
  193 instruments, 2 days — real backtests will be much larger).

## G. Adapter (confirmed: building this ourselves, not testing "does
Nautilus have one")

- ☐ Study the `_template` adapter scaffold and the Interactive Brokers
  adapter as a reference shape; estimate real effort for a minimal Dhan
  historical + live data client.
- ☐ Confirm there's a clean "replay my own historical data for backtest"
  path that doesn't require a live Dhan connection at all — i.e. a
  backtest-only data client fed from our own canonical store, separate
  from whatever a live-trading Dhan adapter would need.

## H. Indicators (deprioritized — separate future testing pass)

- ☐ `Swings` (rolling-window swing detector) — compare its actual
  algorithm against our decided D-23 "N-bar fractal" definition; almost
  certainly not identical, decide adapt-vs-build-own once actually
  compared.
- ☐ `VolumeWeightedAveragePrice` — confirm it's genuinely session-reset
  (matches R10's baseline) and check whether anchored-VWAP variants are
  buildable on top or need to be entirely custom.
- ☐ No native volume profile (POC/VAH/VAL), footprint, or GEX — confirmed
  absent already, these stay fully ours regardless of what testing finds
  elsewhere.

---

## Priority order (per 2026-09-06 discussion)

1. **A (market rules)** — foundational, blocks trusting anything else at
   multi-year backtest scale.
2. **B (backtest engine / replay correctness)** — the core trust question
   for the whole engine-adopt decision (D-28).
3. **G (adapter)** — known work regardless of test outcomes, but scoping
   it accurately matters for planning.
4. C, D, E, F — as they come up naturally while building the thin slice.
5. **H (indicators)** — explicitly deferred to a separate pass.

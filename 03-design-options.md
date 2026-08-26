# 03 — Design Sketches

> ⚠ **Nothing here is decided.** These are the candidate designs from the
> original technical draft, preserved because they're useful starting points —
> but every one of them is a *proposal attached to an open decision*, not a
> specification. Where a sketch implies a choice, the decision ID is named.
>
> Read this alongside `05-decision-register.md`. Treat each sketch as one
> option among those listed there.

---

## 1. The layer model — the one fixed thing

```
                         PROVIDERS
             ┌──────────────┴──────────────┐
          Breeze                         Dhan
     (option chains,              (bulk historical,
      1-second)                    live, execution)
             ↓                             ↓
      Breeze Adapter                 Dhan Adapter
             └──────────────┬──────────────┘
                            ↓
                    RAW DATA STORAGE          (immutable)
                            ↓
                    NORMALIZATION
                            ↓
                 CANONICAL DATA STORE
                ┌───────────┴───────────┐
          Historical                   Live
          processing                processing
                └───────────┬───────────┘
                            ↓
                     FEATURE ENGINE
                            ↓
                     MARKET STATE
                            ↓
                    STRATEGY ENGINE
                    ┌───────┴────────┐
                Backtest        Forward Test
                    └───────┬────────┘
                            ↓
                       Risk Engine
                            ↓
                      Order Manager
                            ↓
                       Execution
```

**This layering is the commitment.** Every box's internals are open.

Layer separation to maintain: data acquisition · storage · normalization ·
feature calculation · market state · strategy · execution · portfolio · risk ·
research · visualization. No layer absorbs another's responsibilities.

---

## 2. Storage layout — sketch
**Open: D-01, D-02, D-03, D-09, D-15**

```
data/
├── reference/
│   └── instruments/
├── raw/                        immutable, provider-shaped
│   ├── breeze/historical/
│   └── dhan/live/{trades,depth}/
├── processed/                  canonical, provider-agnostic
│   ├── market/{equity,index,futures,options}/
│   └── chains/
├── features/
│   └── {vwap,volume_profile,market_structure,greeks,gex,footprint,big_trades}/
├── research/
│   └── {backtests,forward_tests,experiments}/
└── validation/
```

**What is actually being claimed here:** only the three-layer separation
(raw / processed / features) plus research and validation outputs. The
directory nesting, the per-instrument-type split, and the per-feature
directories are all illustrations, not requirements — they encode D-03, D-09
and D-15 as though they were settled.

If storage ends up being DuckDB (D-01), most of this tree becomes tables and
the sketch is irrelevant except as a naming guide.

Non-negotiable regardless of layout: **directory structure must never be the
source of instrument identity** (principle #14).

---

## 3. Instrument master — sketch
**Open: D-05, D-06**

Three layers rather than one — market rules, underlying specs, instrument
(see `08`):

```
Market:  market_id, timezone, currency, calendar_ref, cost_model_ref,
         settlement_rules, quotation_conventions
Rules:   market_id, rule_type, value, valid_from, valid_to     ← D-51
Expiry:  underlying_id, series, expiry_date, settlement_time   ← D-52 (data, not computed)
```

```
instrument_id            ← form is open (D-05); must namespace by market
market_id                ← NOT assumed
symbol
exchange
segment
instrument_type          ← explicit enum, never inferred from symbol
underlying_instrument_id
underlying_symbol
expiry
strike
option_type              ← CE / PE; null for futures
lot_size                 ← time-versioned: NSE lot sizes have changed
tick_size
contract_multiplier      ← GEX scales linearly with this
currency
exercise_style           ← European / American (D-19)
valid_from               ← time-awareness is open (D-06)
valid_to
```

Analytics receive `(instrument, rules_as_of(market, t))` and never import a
market. Where a feature needs a market fact the rules object doesn't expose,
that's a missing field, not a licence to hardcode (D-55).

Types: `EQUITY` · `INDEX` · `FUTURE` · `OPTION`.

Rationale for time-awareness: reference data changes. Lot sizes are revised;
contracts cease to exist after expiry. Whether that justifies versioned rows or
daily snapshots is D-06, and depends on whether any period you care about
actually contains such a change.

---

## 4. Canonical market data — sketch
**Open: D-04, D-07, D-08, D-09, D-10, D-12**

Long-form:

```
timestamp | instrument_id | open | high | low | close | volume | open_interest | source
```

```
10:31:00   1001   ...   25012
10:31:00   2001   ...   25025
10:31:00   3001   ...     142.50
```

rather than a column per instrument. The argument: option chains have changing
strike ladders, so a wide schema breaks on contact with real data. Long-form
also gives arbitrary instrument sets, easy filtering and efficient columnar
scans. **A wide representation remains available as a derived view** where
benchmarks justify it — D-04 is about the *canonical* form, not about
forbidding wide anywhere.

Timestamp sketch: `2026-08-25 10:31:00+05:30`, meaning the bar *opening* at
10:31 — **but verify what Breeze actually returns before adopting this** (S-01,
D-07). Raw layer preserves whatever precision the provider gave.

Not every instrument carries every field: equity has no OI. Whether that means
nullable columns in one table or separate tables per type is D-09; whether OI
belongs in this record at all is D-10.

---

## 5. Raw event schemas — sketch
**Open: D-38, D-39** · **Deferred to Phase 5**

Trade event — the Dhan Full packet supplies LTP, last traded quantity, OI and
5-level depth together:

```
timestamp | instrument_id | ltp | ltq | oi | source | source_event_id
event_timestamp     ← LTT from the feed — epoch SECONDS, not ms
received_timestamp  ← when we received it (ms) — the only intra-second ordering signal
```

⚠ Two field-level facts that shape everything downstream: `ltq` is int16
(max 32,767 — verify no truncation, S-03), and there is **no aggressor flag**,
so side is always inferred from LTP against best bid/ask (D-24).

Depth, long-form by level:

```
timestamp | instrument_id | side | level | price | quantity

10:31:04.120  NIFTY  BID  1  25010.0  150
10:31:04.120  NIFTY  ASK  1  25010.5  100
```

Three depth tiers exist, and they differ enough that instrument allocation is
itself a decision (D-38):

| Tier | Levels | Instrument ceiling |
|---|---|---|
| Full packet | 5 (+ order counts) | 5,000/conn × 5 |
| 20-level | 20 | 50/conn × 5 ≈ 250 |
| 200-level | 200 | **1/conn × 5 ≈ 5** |

The argument against a wide fixed-column depth table is reasonable — level
counts vary, most columns are usually empty. But long-form multiplies row counts
by 2×levels, and at 200 levels that's 400 rows per snapshot per instrument.
Measure before committing (S-02). Genuinely open.

Keeping both event and receive time is what makes feed latency, processing
latency and execution latency measurable, and is the only way to debug why a
live signal differed from its replay.

---

## 6. Live → canonical aggregation — sketch
**Open: D-08, D-10**

```
open   = first trade price
high   = max trade price
low    = min trade price
close  = last trade price
volume = sum of trade quantity
```

**OI is not summable.** Where the provider supplies an OI snapshot, the
canonical rule must be stated explicitly — last observation in the bar, first,
or something else. This is exactly the kind of thing that silently corrupts a
year of data if left implicit.

---

## 7. Historical + recorded merge — sketch
**Open: D-12**

Canonical records carry `source` and ideally `dataset_version`:

```
2026-08-25 10:31  NIFTY FUT  source = breeze
2026-08-25 10:32  NIFTY FUT  source = dhan
```

Overlap handling:

1. Preserve both raw sources — always.
2. Compare canonical records.
3. Choose canonical per an explicit written policy.
4. Record provenance on the surviving record.

Candidate policy: historical period → Breeze, recorded period → Dhan, with a
fixed cutover. Where both exist, produce a **validation comparison** rather than
silently replacing one with the other.

S-06 tells you whether disagreement is rare or routine — which determines
whether this is a formality or a real problem.

---

## 8. Option chain object — sketch
**Open: D-27**

```
OptionChain
├── underlying
├── timestamp
├── expiry
└── contracts[]
      instrument_id, strike, option_type,
      price, volume, OI,
      IV, delta, gamma, theta, vega
```

A **logical** research object. Whether it is materialized per timestamp, built
on demand, or cached is D-27 — as is the question of what counts as chain
membership when a strike has OI but no trades at T.

Option identity lives in the instrument master (underlying, expiry, strike,
type → instrument_id). Market data then needs only `timestamp, instrument_id,
OHLCV, OI`. This keeps option identity out of file paths, which matters
(principle #14).

---

## 9. Greeks layer — sketch
**Open: D-19, D-21** · **Blocked by S-04**

```
Inputs:  option market price, underlying price, strike, time to expiry,
         interest rate, dividend assumption, option type, contract specs
Outputs: IV, delta, gamma, theta, vega
```

```
processed/options → Greek Engine → features/greeks
```

Stored as a derived feature keyed by `(timestamp, instrument_id, greek_version)`.
Raw option data stays immutable; Greeks are regenerable. This is why the draft
resists embedding Greeks into market data — the methodology *will* change.

Dhan publishes greeks and IV on its live chain. Those are not a substitute (no
methodology, no versioning, and unavailable for the Breeze historical chain) but
they make an excellent **validation reference** for your own implementation —
D-19, S-04.

Each version documents its model and assumptions. The model choice itself
(Black-76 vs BS, futures vs spot underlying) is unresolved and non-trivial —
see S-04.

---

## 10. GEX granularities — sketch
**Open: D-20** · **Blocked by S-05**

```
Option-level:  timestamp, instrument_id, gamma, OI, gex
Strike-level:  timestamp, underlying, expiry, strike, call_gex, put_gex, net_gex
Chain-level:   timestamp, underlying, expiry, total_gex, gamma_flip
Market-level:  timestamp, underlying, major_positive_levels,
               major_negative_levels, regime
```

Each level generated from the one below, never stored as unrelated numbers.

Point-in-time requirement (R20): never use later OI, later option prices, later
chain composition, future expiry information, or end-of-day values when the
decision occurs earlier.

The dealer-positioning convention that turns gamma × OI into signed exposure is
**not settled** — D-20, S-05.

---

## 11. Feature storage pattern — sketch
**Open: D-15, D-16**

```
feature_name | feature_version | timestamp | instrument_id or underlying | values...
```

Features come in classes, and one schema may not serve all of them well:

| Class | Examples | Keyed by |
|---|---|---|
| Instrument-level | VWAP, IV, delta, gamma, theta, vega | instrument |
| Price/market-level | volume profile, market structure | instrument or market |
| Order-flow-level | footprint, big trades, delta, imbalances | instrument |
| Chain-level | GEX, gamma flip, GEX by strike | underlying + expiry |
| Event-shaped | BOS/CHOCH occurrences, big trade events | timestamp + type |

That last row is the one the generic schema serves worst — see D-15.

---

## 12. Feature sketches

**Volume profile** — inputs `timestamp, price, volume`; derived `price_level,
volume_at_price, POC, VAH, VAL, HVN, LVN`. Each profile object carries
`profile_start, profile_end, profile_type, method_version` so its levels are
reproducible. Bin sizing and intra-bar volume distribution are open (D-22).

**Market structure** — engine holds state: `current_swing_high,
current_swing_low, trend_state, last_BOS, last_CHOCH`. Emits structured events
rather than boolean columns:

```
timestamp | event_type=BOS | direction=bullish | price | reference_swing | method_version
```

Swing and BOS definitions open (D-23).

**Footprint** — price levels within a candle:

```
timestamp | price | buy_volume | sell_volume | delta
+ imbalance_ratio, stacked_imbalance, absorption_score
```

Retain the underlying volume-at-price so different footprint calculations can
be regenerated. Trade classification open (D-24), **and the whole feature is
gated on S-03**.

**Big trades** — raw `timestamp, instrument_id, price, quantity` → classified
`size_percentile, side, is_big_trade` → aggregated `large_buy_volume,
large_sell_volume, large_buy_count, large_sell_count, large_trade_pressure`.
Threshold definition open (D-25), also gated on S-03.

---

## 13. Market state — sketch
**Open: D-32**

```python
MarketState(
    timestamp, instruments, prices, structure, volume_profile,
    footprint, big_trades, options, greeks, gex, vwap,
)
```

A strategy asks *"what is the current market state?"* without knowing whether
it came from a historical replay or a live feed. Whether this is eagerly
populated, lazily computed, or an immutable snapshot with a lineage id is D-32
— and R24's traceability requirement pushes toward capturing what the strategy
actually read.

---

## 14. Replay and real-time — sketch
**Open: D-17, D-18, D-28, D-29**

```
Backtest:     historical data → timestamp → feature update → strategy
                             → signal → execution simulator → portfolio state

Live:         dhan event → normalizer → state update → feature update
                             → strategy → signal
```

The difference is the source of time and events, not the strategy interface.
**Whether one implementation genuinely serves both is D-17/D-18, and it is the
hardest thing in this document set to actually deliver.**

---

## 15. Execution, portfolio, risk — sketch
**Open: D-30, D-31, D-34, D-35** · **Mostly deferred**

Execution simulator models order type, entry price, quantity, fees, slippage,
timestamp, fill assumptions. Supports market, limit, stop, SL, TP as strategies
require.

Portfolio tracks cash, positions, average entry, realized and unrealized PnL,
fees, margin, exposure — and for derivatives, contracts, lot size, contract
multiplier, expiry.

Risk sits separate from strategy logic: max position size, max daily loss, max
trade loss, max portfolio exposure, max simultaneous positions, margin checks,
kill switch.

---

## 16. Research records — sketch
**Open: D-13, D-16, D-32**

Experiment:

```
experiment_id, strategy_version, feature_versions, data_version, parameters,
start_time, end_time, instrument_universe, execution_assumptions, results
```

Trade:

```
trade_id, strategy_id, instrument_id,
entry_timestamp, entry_price, exit_timestamp, exit_price,
quantity, direction, SL, TP,
gross_pnl, fees, slippage, net_pnl, MAE, MFE, exit_reason
```

Signal — kept **separate** from trade, because signals that were never filled
are research data:

```
timestamp, strategy_id, instrument_id, direction, confidence,
entry_reference, SL, TP, reason, feature_snapshot_id
→ status: executed | rejected | expired
```

Lineage: `trade → signal → feature snapshot → canonical data → raw provider data`.
That chain is what answers *"why did the system take this trade?"*.

---

## 17. Time alignment — a constraint, not a sketch

Datasets tick at different rates: 1m candles, option chains, trade events,
depth events. Every join across them must explicitly define:

- direction (backward-looking by default)
- maximum allowed time difference
- whether future observations are forbidden (they are)

> Never an ordinary nearest-neighbour join.

This is a hard rule rather than an option, because it's the mechanism by which
R20 is enforced structurally rather than by remembering to be careful.

---

## 18. Caching — a constraint

Expensive features (GEX, chains, profiles, structure) may need caching. If so:

> **Caching is never the source of truth. Canonical data is.**

Cache keys must include feature version and data version, or you will silently
serve stale features after a definition change (D-14, D-16).

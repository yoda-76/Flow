# 04 — Tooling Landscape

*Revised twice: first after reading the Dhan v2 and Breeze API documentation
directly, then after the build-vs-adopt survey. The two halves have different
evidential status — see below.*

---

## Verification status — read this first

| Section | Source | Trust |
|---|---|---|
| **Data providers** (§2–§4) | Read directly from Dhan v2 and Breeze API docs | High. Coverage claims still need S-01. |
| **Frameworks & platforms** (§5–§6) | Prior knowledge; **search was not completed** | Low. Verify before acting. |

The framework section is the one that could change the project's shape most, and
it's the one least verified. Treat it as a list of things to go and check, not
as findings.

---

## §1 — Corrections to the original research report

| Report claimed | Actually |
|---|---|
| Dhan is 1-second snapshots, not true ticks | **Tick-by-tick event-based.** Full packet carries LTP, last traded quantity, OI and 5-level depth together. |
| 200-level depth impossible outside colocation | **Dhan offers it** — separate socket, 1 instrument per connection. 20-level allows 50/connection. |
| No turnkey greeks/GEX for NSE | Greeks and IV **are** provided (Dhan live chain; IV also in expired-options data). GEX still yours to build. |
| Breeze is just another historical source | Breeze is the **only** source of full historical option chains at absolute strikes, and offers 1-second OHLCV. |
| Build almost everything | Roughly true for **analytics**; probably false for **plumbing** — see §5. |

---

## §2 — The data stack

Three roles, two providers. This is a three-way split, not the two-way one the
original drafts assumed.

| Role | Provider | Why it and not the other |
|---|---|---|
| **Bulk historical** — equity, index, futures, 1-min + OI | **Dhan** | 100k requests/day, 90 days per poll, 5 years, all active instruments. 20× Breeze's throughput. |
| **Historical option chains** — absolute strikes, expired contracts | **Breeze** | The only one that addresses contracts by `expiry_date` + `right` + `strike_price`. Dhan's expired-options is ATM±10 rolling. |
| **Fine-grained historical** — 1-second on a few core instruments | **Breeze** | 1-second OHLCV. Affordable for index/futures; infeasible for chains. |
| **All live** — ticks, depth, chain with greeks | **Dhan** | Tick-by-tick, 20/200-level depth, full chain every 3s, cheap. |
| **Execution** (later) | **Dhan** | Already integrated; Breeze prohibits market orders and restricts algo routing. |

Consequence: **two historical adapters**, and futures covered by both — which
gives a free cross-provider validation set for R17 (S-06).

---

## §3 — Data provider comparison

| Candidate | Historical F&O | Order flow / depth | Greeks / IV | Limits | Cost | Status |
|---|---|---|---|---|---|---|
| **DhanHQ** | 1-min + OI, 5 yrs, all active instruments; expired options ATM±10 rolling with IV, OI, spot | **Tick-by-tick**; 5-level in Full packet; 20-level (50/conn); 200-level (1/conn) | Greeks + IV on live chain | 100k/day, 5/sec; chain 1 unique/3s; 5,000 instruments/conn × 5 | ~₹499/m | **ADOPT** — live + bulk historical |
| **ICICI Breeze** | 1sec/1min/5min/30min/1day; ~10 yrs claimed; **absolute strike + expiry incl. expired**; OI and `chnge_oi` | Live tick stream exists (live-only) | No historical greeks | **100/min, 5,000/day, 1,000 candles/request**; NSE only; daily manual session token | broker-linked | **ADOPT** — historical chains + 1-second |
| **TrueData** | 1-min historical; chains + OI | ticks; 20 levels | none | — | ₹₹ | **DROPPED** — Dhan covers what this was held in reserve for |
| **Zerodha Kite** | limited; no OI via API | ~1s ticks, 5-level | none | — | low | **DROPPED** — strictly worse than Dhan here |
| **TickData** | high-quality NSE tick history | trades + L1 | none | — | enterprise | **DROPPED** — cost |
| **Databento** | no India | full depth, normalized | none | — | usage-based | **DROPPED for data** — but read its DBN schema as a **reference design** for R15/R27 cross-venue normalization |

---

## §4 — Request budget: the real historical constraint

Breeze's rate limit, not its coverage, bounds the historical programme.

| Task | Feasibility |
|---|---|
| 1-min, single instrument | Trivial |
| **1-second, single instrument** (index, futures) | ~1 year of data per day of pulling — very usable |
| **1-min, full option chain** | ~8 days of pulling per year of history → roughly 6 weeks for 5 years |
| 1-second, full option chain | ~23× the above — **not feasible** |

Two consequences to decide rather than drift into:

1. **Resolution can differ by instrument class** — 1-second for index/futures, 1-minute for options. That's D-08, now a real choice.
2. **The bulk chain pull is a multi-week supervised operation** (D-50), complicated by daily token expiry (D-49). Plan it as a project, not a script.

---

## §5 — Frameworks and platforms ⚠ UNVERIFIED

**Search was not completed.** Everything here is prior knowledge and may be
wrong or out of date. It is listed because the highest-leverage item in the
whole document sits in this section.

### NautilusTrader — the one to evaluate first

Open-source, Rust core with Python API. Its central design goal is precisely
what D-17/D-18 wrestle with: **identical strategy code in backtest and live**,
event-driven underneath.

| Your decision | What it reportedly already provides |
|---|---|
| D-05 instrument identity | `InstrumentId` = Symbol + **Venue** — market-namespaced by construction |
| D-17 / D-18 batch vs streaming parity | The core value proposition |
| D-28 / D-29 engine build-vs-adopt | Event-driven, multi-venue, multi-asset |
| D-32 market state | Cache + portfolio abstraction |
| D-33 strategy interface | Callbacks — `on_bar`, `on_quote_tick`, `on_order_book` |
| D-38 depth representation | L1 / L2 / L3 order book types |
| D-01 storage | Parquet / Arrow data catalog |
| R27 market abstraction | Instrument definitions carry multiplier, lot size, tick size, precision, currency, venue |

Has `FuturesContract` and `OptionContract` instrument types; option greeks
support was reportedly added during 2024–25 — **verify**.

**Two things to check hard:** whether instrument definitions support
**time-versioned contract specs** (the D-51 lot-size problem), and how painful a
custom adapter is — Dhan and Breeze adapters do not exist.

**Status: TRIAL — spike before building any engine.** See §8.

### Others

| Candidate | Relevance | Status |
|---|---|---|
| **ArcticDB** (Man Group) | Time-series store with built-in **versioning** — D-01 and D-13 in one component. Purpose-built for this data shape. | **TRIAL** — evaluate alongside D-01 |
| **OpenAlgo** | Open-source broker-agnostic bridge for Indian brokers, Dhan included. Execution layer, not research. | **PARKED** — *reconsider at Phase 7* |
| **Backtrader** | Mature event-driven, multi-feed. Weak on option chains; low project activity. | **TRIAL** — fallback if Nautilus doesn't fit (D-28) |
| **vectorbt** | Very fast vectorized parameter sweeps. Not event-driven. | **TRIAL** — idea screening only |
| **Orderflow (OSS)** | Tick reshaping, cumulative delta, imbalance, iceberg estimators. Now genuinely applicable since real tick data is available. | **TRIAL** — Phase 5 |
| **QuantLib** | Pricing and greeks. Validate against Dhan's published greeks (S-04). | **TRIAL** — D-19 |
| **LEAN / QuantConnect** | No NSE F&O data; heavy; C#-flavoured. | **DROPPED** — *reconsider only for managed live infra* |
| **QuantRocket** | Weak India coverage. | **DROPPED** |
| **OpenBB** | Research terminal / data aggregation. Different problem. | **DROPPED** |

---

## §6 — What does not exist anywhere ⚠ UNVERIFIED

This is the part of the project that cannot be bought, and it is the part the
project is actually about.

| Component | Why nothing exists |
|---|---|
| **GEX for NSE** | No platform, library or vendor. SpotGamma, MenthorQ and similar are US-only and closed. Open-source GEX projects are CBOE/SPX-specific dashboards. The dealer-positioning convention for an Indian market is **unsolved research**, not missing software (D-20, S-05) |
| **Order-flow features as a research pipeline** | Bookmap, ATAS, Sierra Chart, Jigsaw, GoCharting, TrueData Velocity *display* order flow. None produce testable features from it |
| **Historical chain ingestion at scale** from Indian providers | Hobby repos only |
| **Research harness** | Feature versioning, ablation, lineage from trade back to raw data (D-13, D-16, R24) |
| **Market structure detection** | Nothing generic fits; expect several versions (D-23) |
| **Volume profile / TPO** | Thin libraries; 1-second data improves fidelity considerably over 1-minute (D-22) |
| **Indian F&O cost stack** | Generic engines simulate fills; the tax and fee stack is yours to encode (D-31) |
| **Time-versioned market rules** | Nothing handles lot-size changes contaminating historical GEX (D-51) |

Indian SaaS backtesters — **AlgoTest, Stockmock, Quantsapp** — run predefined
strategy templates and cannot express custom features at all. Not substitutes.

---

## §7 — The build / adopt split

Roughly **60–70% of the plumbing** may already exist: engine, storage,
instrument abstraction, backtest/live parity. Roughly **0% of the
differentiated analytics** does.

The plumbing is also where the most calendar time would go and where bugs are
least visible. That makes the split matter:

| Layer | Position |
|---|---|
| Analytics (GEX, order flow, structure, profile) | **Build** — must be |
| Research harness (versioning, ablation, lineage) | **Build** — must be |
| Provider adapters (Dhan, Breeze) | **Build** — nobody has them |
| Market rules / time-versioning | **Build** — see §6 |
| Engine, storage, instrument model, live parity | **Open** — D-28, D-48 |

Adopting Nautilus would close or constrain D-05, D-17, D-18, D-28, D-29, D-32,
D-33 and D-38 in one move. It would also mean inheriting its data model, which
may fight the time-versioned market rules of `08`. That trade is worth two days
of investigation rather than six months of assumption.

---

## §8 — The spike that should happen first

**Before Phase 1, before any engine work: two days on NautilusTrader.**

Build a trivial NIFTY futures strategy from a CSV, then answer three questions:

1. Can you define an NSE option instrument with correct multiplier, lot size and expiry — and can that definition change over time (D-51)?
2. How hard is a minimal Dhan adapter?
3. Can you attach a custom chain-level feature like GEX to the market state?

If the answers are good, a large block of the decision register closes at once
and you start on analytics months earlier. If they're bad, you've lost two days
and gained a firm answer to D-28.

This is the highest-leverage item in the entire document set, and it is cheaper
than any amount of further reading.

---

## §9 — Cost picture

- Dhan Data API: ~₹499/month + taxes, renewing every 30 days
- Breeze: free with an ICICI Direct account
- Open source (Nautilus, ArcticDB, Backtrader, vectorbt, QuantLib): free
- Storage/compute: modest for bars; meaningful for tick + depth (S-02)

Spending more money no longer changes the project's shape — Dhan delivers
tick-by-tick and 200-level depth at ₹499.

**The scarce resources are time and calendar days:** the Breeze request budget
for the historical chain pull, and days of live recording that haven't started
yet (D-46).

---

## §10 — Reconsider triggers

| If this happens | Reopen |
|---|---|
| Nautilus spike (§8) goes well | D-05, D-17, D-18, D-28, D-29, D-32, D-33, D-38 — potentially all at once |
| Nautilus can't do time-versioned contract specs | D-51 — decide whether to layer it on top or build the engine |
| S-01 shows Breeze can't serve expired option contracts | Historical GEX viability; TrueData back from DROPPED |
| Breeze 1-second proves unreliable | D-08 — fall back to 1-minute canonical throughout |
| int16 LTQ truncates large trades (S-03) | D-25 — big-trade detection needs a different basis |
| Custom engine exceeds ~2 months with no working backtest | D-28 — adopt something |
| Data volume exceeds comfortable single-machine handling | D-01, D-41, D-45 |
| Dhan changes feed granularity or pricing | D-36 — TrueData back from DROPPED |
| **A completed search contradicts §5 or §6** | This whole document — it was never verified |

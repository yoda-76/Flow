# 01 — Concept

*Nothing in this document is a decision. It is the mental model everything else
is built on.*

---

## 1. What the system is

A machine for turning discretionary trading observations into measurable,
testable hypotheses — and eventually into automated execution.

Not a backtester. Not a charting tool. A research platform that happens to be
able to trade.

## 2. The transformation

A human looks at a chart and thinks:

> Price reached an important GEX level, volume shows rejection, the footprint
> shows aggressive selling being absorbed, structure turned bullish. Reversal.

A computer cannot evaluate that sentence. Each clause has to become a
deterministic definition:

| Human phrase | Must become |
|---|---|
| "important GEX level" | a computed level, by an explicit rule |
| "price reached it" | a distance threshold |
| "volume shows rejection" | a defined volume/profile condition |
| "footprint shows absorption" | a defined order-flow condition |
| "structure turned bullish" | a defined BOS/CHOCH rule |

Same data in, same answer out, every run. If a definition cannot be written
down, it cannot be tested.

## 3. Four layers

```
1. What happened?              →  MARKET DATA     (observations)
2. What does it tell us?       →  FEATURES        (derived, deterministic)
3. What does the market look like?  →  MARKET STATE (structured snapshot)
4. What do we do about it?     →  STRATEGY        (hypothesis + rules)
```

Then: **EXECUTION** (did we get the trade?) and **RESEARCH** (did the idea work?).

The critical separations:

- **Observation vs inference.** A trade print is observed. Its aggressor side
  is inferred. Store both, label which is which.
- **Feature vs strategy.** `GEX = +X` is a feature. It is not `BUY`. The
  strategy decides what combinations of features mean.
- **Signal vs trade.** The strategy wanting a trade and the trade happening are
  two different events. Both must be recorded — signals that were never filled
  are research data.

## 4. Why raw data is kept

A candle hides the path. Given only OHLCV you cannot later ask: were there
large trades? was buying aggressive? was there absorption? what happened at
each price? what did the book do before the move?

> **Store the evidence. Derive the representation.**

Aggregation is a view, not a substitute. This is the reason live recording
stores events rather than only minute bars — the tick archive we start
collecting is the only source of order-flow research we will ever have for that
period.

## 5. Why providers are adapters, not the system

Breeze and Dhan are sources. They enter at the data boundary and stop there.

```
Breeze ──┐
         ├──→ CANONICAL ──→ FEATURES ──→ STRATEGY
Dhan ────┘
```

Consequence: adding a third provider later touches one layer. The strategy
never learns which broker it is reading.

## 6. Why one system, not five

Backtest, forward test, and live differ only in **where time comes from** and
**what happens after the signal**:

| Mode | Clock | After signal |
|---|---|---|
| Backtest | historical replay | simulated execution |
| Forward test | real | simulated execution |
| Live | real | risk manager → real execution |

Everything upstream — data, features, market state, strategy — is identical.
That identity is the whole architectural payoff, and it is why the same feature
code should ideally run in both modes (see D-18, which is genuinely hard).

## 7. Historical and live become one timeline

```
|—— Breeze historical ——|—— Dhan recorded ——|—— Dhan live ——>
```

The source changes. The conceptual dataset does not. Source stays as metadata
on every record so the join is explicit rather than accidental.

Note the asymmetry and do not paper over it: **no historical order-flow data
exists from any accessible provider.** Order-flow features therefore have no
backtest history at all — they begin the day recording begins.

This is accepted deliberately (D-46) rather than worked around. Nothing is
approximated from bars, because an order-flow feature estimated from OHLCV
carries an error that is invisible in aggregate statistics and fatal in a
strategy. The practical consequence is that the research programme has two
classes of hypothesis — historical-capable and forward-only — and they are kept
separate from the start.

## 7b. Concepts are generic; rules are not

The system reasons about underlyings, instruments, expiries, strikes, OHLCV, OI,
IV, greeks, GEX, VWAP, structure and strategies. None of those are Indian.

What *is* Indian: when contracts expire, what a lot is worth, when the market is
open, what a trade costs, how settlement works — and how each of those has
changed over time.

> **A market rule is data, not code — and it is time-versioned.**

The core knows the first list. The second enters as configuration, looked up as
of the timestamp being computed. That way NIFTY, SPX and ES are the same
architecture with different rule sets, and — more immediately useful — a
five-year NSE backtest doesn't apply today's lot size to three-year-old open
interest.

That second benefit is worth noticing: the abstraction pays for itself before
any second market exists. See `08-market-abstraction.md`.

## 8. What the system is explicitly not trying to do

- Rebuild a charting platform
- Recreate a broker interface
- Predict everything
- Assume GEX is profitable
- Assume footprint is predictive
- Assume big trades are directional
- Assume more features means better trading

> **Everything is a hypothesis until the data supports it.**

The system's job is to make it cheap to answer *"does this feature actually
help?"* — by testing GEX alone, GEX + structure, GEX + profile, GEX +
footprint, and so on, and discovering which components contribute nothing.

## 8b. Why build rather than adopt

The system is being built because a survey of existing tooling found nothing
that covers the work this project is actually about.

**What does not exist anywhere.** GEX for NSE — no platform, library or vendor
provides it, and the dealer-positioning convention for an Indian market is
unsolved research rather than missing software. Order-flow *features* as a
research pipeline — Bookmap, ATAS, Sierra Chart, GoCharting and TrueData
Velocity are charting and execution tools that display order flow, not systems
that produce testable features from it. Historical option-chain ingestion at
scale from Indian providers. And the research harness itself: feature
versioning, ablation, and lineage from trade back to raw data. Indian SaaS
backtesters (AlgoTest, Stockmock, Quantsapp) run predefined strategy templates
and cannot express custom features at all.

That set — chain-level analytics, order-flow features, and the ablation harness
— is the entire point of the project, and none of it can be bought.

**What may already exist, and is not yet ruled out.** A substantial part of the
*plumbing* — event-driven engine, backtest/live parity, instrument abstraction
with venue namespacing, order-book types, columnar storage — appears to be
covered by **NautilusTrader**, with **ArcticDB** a candidate for versioned
time-series storage. Neither has been evaluated hands-on.

> ⚠ **This survey is incomplete.** It rests on prior knowledge, not a completed
> search. Before building the engine, run the NautilusTrader spike (D-28): a
> trivial NIFTY futures strategy, an NSE option instrument with correct
> multiplier and expiry, a minimal Dhan adapter, and one custom chain-level
> feature. Two days. If it fits, it closes D-05, D-17, D-18, D-28, D-29, D-32,
> D-33 and D-38 at once — though you would inherit its data model, which may
> fight the time-versioned market rules of `08`.

**So the decision is narrower than "build everything".** The analytics and
research layers are built because they must be. The plumbing beneath them is an
open build-or-adopt question (D-28, D-48), and answering it with a two-day
experiment is much cheaper than answering it with six months of engine work.

## 9. The research loop

```
Hypothesis → formal definition → feature → visual validation → backtest
   → parameter analysis → out-of-sample → forward test → decision
```

Visual validation is not cosmetic and not optional. It is how you find out that
your BOS detector is firing on something other than what you meant. Most
feature bugs are invisible in aggregate statistics and obvious on a chart.

## 10. The loop closes

Trades create recorded data. Recorded data creates research. Research creates
better features. Better features create better strategies. Better strategies
get deployed and create more recorded data.

That circularity is why the storage and versioning decisions matter more than
they look — everything downstream is only as reproducible as the data layer.

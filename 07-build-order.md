# 07 — Build Order

*Revised after the provider investigation. Two structural changes: the recorder
moves to the front, and order-flow features move to the back.*

---

## The two changes

**1. The recorder starts in Phase 1, not Phase 5.**

Under D-46, order flow is forward-only: there is no historical order-flow data
and none will be approximated from bars. So the recorder is the only source
those features will ever have, and **every day it isn't running is permanently
lost**. It depends on almost nothing upstream — an instrument list, a socket, and
somewhere to write bytes. There is no good reason for it to wait.

**2. Order-flow features move from Phase 2 to Phase 5/6.**

Footprint, delta, absorption, imbalance and big trades can't be built against
history, so they don't belong in the historical feature phase. They're built
once the recorder has accumulated enough data to say anything.

Also retained from the previous revision: **Phase 0 (spikes)** and **Phase 1.5
(thin vertical slice)**.

---

## Phase 0 — Spikes
**Duration:** days · **Blocks:** almost everything

Run `06-spikes.md`. Record answers. Flip blocked decisions.

**Exit when:** S-01 (Breeze actually serves expired option contracts at absolute
strikes) and S-02 (volume + request budget) are answered. S-01 is the one that
matters most — the historical GEX programme depends entirely on it.

**Decide before leaving:** D-36 (confirm the three-way split), D-49 (token
strategy, because D-50 depends on it).

---

## Phase 1 — Data foundation + recorder
**Requires closed:** D-01, D-02, D-04, D-05, D-06, D-07, D-08, D-09, D-10, D-11, D-41
**Can defer:** D-03 (until volume is real), D-13 (simple manifest to start)

Two tracks, in parallel.

### Track A — historical
- **Market profile + time-versioned rules store** (D-51, D-52) — before the instrument master, since the master depends on it
- Instrument master, reconciling **three** universes: Dhan, Breeze, NSE (S-06); market-namespaced identity (D-05)
- **Two** historical adapters — Dhan (bulk) and Breeze (chains, 1-second)
- Canonical schema + normalization
- Validation checks and quality reports (D-44), including loud failure on silent-empty responses
- Begin the Breeze chain pull as raw bytes (D-50) — don't wait for the canonical schema; that's what the immutable raw layer is for
- Option chain representation (D-27)

### Track B — recorder ⬅ moved up
- Dhan websocket recorder: Full packet (LTP, LTQ, OI, 5-level depth)
- Depth tier allocation (D-38) — which instruments get 20-level, which 5 get 200-level
- Option chain snapshot poll (1 unique request / 3s)
- Raw append-only writes, post-close compaction (D-37)
- Event time **and** receive time (D-39) — receive time is your only intra-second ordering signal, since LTT is epoch seconds

**Exit when:** you can reconstruct a chain at an arbitrary past timestamp, the
validation report is clean, and the recorder has survived a full week including
a disconnect and a restart.

**Also before exiting:** run the abstraction check (D-54) — write SPX and ES
market profiles as config files only, no code, and see whether the core loads
them. An hour's work; every gap it finds is a migration avoided.

---

## Phase 1.5 — Thin vertical slice
**Requires closed:** D-30 (crudely), D-47

One instrument. One month. VWAP only. Trivial strategy. Simplest possible replay
loop. Real fees.

The output is a list of things the decision register got wrong. Expect to reopen
several decisions. That's the point.

**Exit when:** a trade appears with a plausible PnL and you can trace it back to
raw data.

---

## Phase 2 — Historical features
**Requires closed:** D-14, D-15, D-16, D-17, D-19, D-20, D-21, D-22, D-23
**Blocked by:** S-04, S-05 for the option features

Cheapest and most verifiable first:

1. VWAP — validates the feature plumbing
2. Volume profile (D-22) — first real definitional argument; 1-second data on index/futures improves fidelity here materially over 1-minute
3. Market structure (D-23) — where visual validation earns its keep
4. Greeks (D-19, S-04) — validate against Dhan's published greeks
5. GEX (D-20, S-05) — needs the Breeze chain pull complete for the target period; expect multiple versions

**Not here:** order-flow features (D-46).

Every feature ships with its visualization (R23, D-43).

GEX is built with a config object (D-53) rather than inline constants, so expiry
scope, multiplier and dealer convention are recorded per feature version.

**Re-run the abstraction check (D-54)** at the end of this phase — the feature
engine is where hardcoded market facts creep in most easily.

---

## Phase 3 — Backtester
**Requires closed:** D-28, D-29, D-30, D-31, D-32, D-33, D-34
**Can defer:** D-35

Multi-instrument, F&O, options, feature consumption, realistic execution,
performance analytics, trade and signal records.

Phase 1.5's crude loop either grows into this or gets thrown away. Both fine;
decide deliberately.

---

## Phase 4 — Strategy research (historical-capable only)
**Requires closed:** D-47

GEX reversal, plus the ablation work that's the actual point: GEX alone, GEX +
structure, GEX + profile, GEX + VWAP — finding which components contribute
nothing.

Out-of-sample discipline and robustness testing belong here.

Constrained to the **historical-capable** feature class. Order-flow
hypotheses wait for Phase 6.

---

## Phase 5 — Order-flow features
**Requires closed:** D-24, D-25 · **Blocked by:** S-03 (int16 LTQ ceiling)

Built against recorded data only. By this point the recorder has been running
since Phase 1, so there should be months of tape available.

- Trade classification (D-24) — observed vs inferred distinguishable in storage
- Footprint, delta, imbalance, absorption
- Big trades (D-25) — **verify the int16 ceiling before designing thresholds**
- End-of-day finalization pipeline (D-40)

---

## Phase 6 — Forward testing
**Requires closed:** D-18

Real-time features, strategy signals, simulated execution, forward performance
records comparable to backtest records (R21).

The **replay-parity test** — recorded data through both the historical and live
feature paths, asserting identical output — belongs here and tells you whether
D-17/D-18 were answered correctly.

This is also where **order-flow hypotheses are validated for the first time**.
They arrive with no backtest history, so forward evidence is the only evidence
they will ever have. Budget more forward time for them than for
historical-capable strategies, and set the evaluation period before you start
rather than after you see results.

---

## Phase 7 — Live execution
**Requires closed:** D-35, plus everything in R22

Risk management, order management, broker execution via Dhan. Only after
sufficient historical and forward validation.

---

## Dependency summary

```
Phase 0   spikes
   ↓
Phase 1   ┌── Track A: data foundation + Breeze chain pull
          └── Track B: recorder ⬅ starts here, runs continuously
   ↓
Phase 1.5 thin slice  → feeds back into decisions
   ↓
Phase 2   historical features   (no order flow)
   ↓
Phase 3   backtester
   ↓
Phase 4   strategy research     (historical-capable only)
   ↓
Phase 5   order-flow features   ← needs months of Track B output
   ↓
Phase 6   forward testing       ← order-flow hypotheses validated here
   ↓
Phase 7   live execution
```

---

## Sequencing risks

**Phases 1–3 are long and produce nothing observable.** That's where enthusiasm
dies. Phase 1.5 exists to put a result on the board early.

**The Breeze chain pull is a multi-week supervised operation** (D-50) complicated
by daily token expiry (D-49). It gates Phase 2's GEX work. Start it as early as
S-01 allows, in raw form.

**Order-flow features are gated on calendar time, not effort.** No amount of
work in Phases 1–4 shortens the wait. This is the entire reason Track B moved
to Phase 1 — if the recorder starts six months late, the first order-flow
evaluation is six months later, regardless of everything else.

**S-01 is the single biggest unknown left.** If Breeze can't serve expired
option contracts at absolute strikes, historical GEX collapses back to Dhan's
ATM±10 and a large part of Phase 2 and 4 changes shape. Answer it in week one.

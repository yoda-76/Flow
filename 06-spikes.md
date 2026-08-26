# 06 — Spikes: what to find out before deciding

*Revised after reading the Dhan v2 and Breeze API documentation. Three of the
original spikes are answered; what remains is narrower and mostly empirical
verification rather than open discovery.*

Each spike is a scratch script or a support ticket — not infrastructure. Write
throwaway code, record the answer here, delete the code.

---

## Answered from documentation — no longer spikes

| Old spike | Answer | Consequence |
|---|---|---|
| S-03 — is order flow achievable? | **Yes.** Dhan's live feed is tick-by-tick event-based; the Full packet carries LTP, last traded quantity, OI and 5-level depth together. 20-level and 200-level depth exist on separate sockets. | R12/R13 survive. D-46 closed. |
| 200-level depth impossible? | **Wrong.** It exists (1 instrument per connection). | Un-dropped. |
| Historical option chain at absolute strikes? | **Breeze, yes.** Its historical endpoint takes `expiry_date` + `right` + `strike_price` explicitly, including expired contracts. Dhan's expired-options API is ATM±10 rolling only. | Historical GEX is viable via Breeze. This is the reason Breeze stays in the stack. |
| Historical order flow? | **Neither provider.** Breeze's 1-second data is 1-second OHLCV — no bid/ask, no per-trade quantity, no side. | Accepted deliberately; see D-46. Not a spike. |

---

## S-01 — Verify Breeze's actual historical coverage 🔴 CRITICAL

The docs claim ~10 years and 1-second. Claims and delivery differ, and there is
a known SDK issue where 1-second retrieval returned empty arrays for dates that
had previously worked.

- [ ] Pull one expired NIFTY option contract by absolute strike + expiry, 1-min, with OI. Does it work? How far back?
- [ ] Repeat for a contract that expired 2+ years ago. Then 5 years ago.
- [ ] Does the 10-year claim hold for **F&O 1-minute**, or only equity cash?
- [ ] Is `open_interest` populated intraday, or zero/null for options?
- [ ] Can you enumerate which strikes existed for a past expiry, or must you probe a strike ladder and discard misses? (This changes the request budget in S-02 materially.)
- [ ] 1-second: does it work today, for index and futures, for the dates you care about?
- [ ] Volumes in units or lots? Verify against a known day.
- [ ] Does the timestamp label the bar's **open or close**? Verify against a session open.
- [ ] Timezone returned, and consistency across instrument types.
- [ ] Does re-pulling the same day return identical data?

**⚠ Silent failure is the danger here.** An invalid stock code has been observed
returning `Status: 200` with an empty list rather than an error. Your ingestion
must distinguish "no data exists" from "API misbehaved" — build that check into
the very first script you write, not later.

**Answers:** D-01, D-03, D-07, D-08, D-13, D-50.

---

## S-02 — Volume and request budget 🔴 CRITICAL

Two questions now: how much data, and how long to pull it.

### Size
- [ ] One full day of NIFTY option chain at 1m: row count, raw size, compressed size.
- [ ] Extrapolate: 1 year, 5 years. With BANKNIFTY. With stock options.
- [ ] One hour of live Dhan Full-packet feed for a realistic instrument set: events/sec, size/hour, projected size/day and /year.
- [ ] Same for 20-level depth on a handful of instruments.
- [ ] Time a realistic query: "full chain at timestamp T", then across a month.

### Request budget — new, and it constrains the schedule
Breeze allows **100 calls/minute, 5,000 calls/day**, max **1,000 candles per
request**. Dhan allows ~**100,000/day**, 5/sec, 90 days per poll.

- [ ] Measure actual contracts per expiry on a real NIFTY chain (the ladder is wider than the ~100 assumed below).
- [ ] Compute: requests needed for 1 year of full NIFTY chain at 1-min. Then 5 years.
- [ ] Confirm the pagination behaviour of the 1,000-candle cap.

Rough prior to check against: ~40,000 requests per year of NIFTY weekly chain →
about **8 days of continuous pulling per year of history**, so ~6 weeks for 5
years. If your measurement lands far from that, re-plan the schedule.

**Answers:** D-01, D-02, D-03, D-38, D-41, D-45, D-50.

---

## S-03 — Verify the live packet fields 🟡

Order flow is viable; three specifics still need empirical confirmation because
each one silently corrupts a feature if wrong.

- [ ] **Last traded quantity is int16 (max 32,767).** Do large option trades truncate, wrap, or saturate? Test against a known large print. This directly determines whether big-trade detection (R13) is trustworthy.
- [ ] **Last trade time is epoch seconds**, not milliseconds. Confirm. Then decide how intra-second ordering is reconstructed (receive time is the only candidate).
- [ ] Does bid/ask in the Full packet update in step with trades, or independently? Trade classification needs them time-aligned.
- [ ] Cumulative `volume` vs per-trade `ltq` — confirm which is which, empirically.
- [ ] Instrument subscription ceilings in practice: 5,000/connection × 5 for the feed; 50/connection for 20-level; 1/connection for 200-level.
- [ ] Record one hour and inspect inter-event timing to confirm genuine tick behaviour.

**Answers:** D-24, D-25, D-38, D-39.

---

## S-04 — Option pricing model 🟡

Unchanged, but with one addition: **Dhan supplies greeks and IV directly** (live
chain, and IV in the expired-options response). That makes this partly a
build-vs-adopt question — see D-19.

- [ ] NSE index options are European and cash-settled. Black-76 on futures, or Black-Scholes on spot?
- [ ] Which underlying reference: index spot or same-expiry futures? They diverge; delta and gamma change materially.
- [ ] Risk-free rate source and tenor, recorded for reproducibility.
- [ ] Dividend treatment — needed at all under a futures-based model?
- [ ] IV solver failures: deep ITM/OTM, illiquid strikes, zero-volume contracts, stale prices, crossed quotes. What fraction of a real chain fails?
- [ ] **Validate against Dhan's published greeks for a known timestamp.** You now have a free reference implementation to check yourself against — use it.

**Answers:** D-19, D-21.

---

## S-05 — Does the GEX dealer convention transfer to India? 🟡

Unchanged, and still the highest-value research question in the set. The US
convention (dealers short calls, long puts) may not transfer to NSE's
retail-heavy option-selling market. Getting the sign backwards inverts every
signal built on it.

- [ ] What assumption are you making about who is short gamma at each strike?
- [ ] Any published work on GEX specifically for NSE?
- [ ] Can OI *change* plus price action infer positioning better than a static convention? (Breeze's option chain returns `chnge_oi` alongside OI — useful here.)
- [ ] Sanity test computed gamma flip against a few known trending vs pinned expiry days.

**Answers:** D-20. Treat v1 as provisional; expect `gex_v2`.

---

## S-06 — Reconcile three instrument universes 🟡

Now a three-way problem: Breeze, Dhan, and NSE's own contract master.

- [ ] Dhan: `securityId` per instrument (available via its scrip master).
- [ ] Breeze: `stock_code` + `expiry_date` + `right` + `strike_price`; security master downloadable as a zip, regenerated daily at 08:00.
- [ ] Do option symbol conventions match, or need parsing? (Breeze uses codes like `CNXBAN` for Bank Nifty — not the exchange symbol.)
- [ ] Do lot sizes and tick sizes agree between the two, and with NSE?
- [ ] Lot sizes change over time — who represents that, and how?
- [ ] Should NSE's contract master be authoritative instead of either broker?
- [ ] **On an overlapping day, do Breeze and Dhan 1-minute futures bars agree?** By how much?

That last check is cheap and tells you how much to trust the "one continuous
timeline" idea (R17) — and you now get it free, since both providers cover
futures historically.

**Answers:** D-05, D-06, D-12.

---

## S-07 — Breeze session automation 🟡 NEW

Breeze session tokens must be regenerated **manually every day**, valid 24 hours
or until midnight, per SEBI guidelines. TOTP is available on the login page.

This is a genuine operational problem for unattended ingestion — and the bulk
historical pull (S-02) may run for weeks.

- [ ] How far can TOTP automate it in practice?
- [ ] What happens mid-pull when the token expires? Does the client fail loudly or silently return empty?
- [ ] Is a supervised long-running pull acceptable, or does this need a daily manual step for weeks?

**Answers:** D-49.

---

## S-08 — Tooling shakeout 🟢

Timeboxed, deferrable, cheap.

- [ ] Load one day of chain data in pandas, polars, DuckDB. Time it; note which felt natural. → D-41
- [ ] Trivial two-instrument strategy in Backtrader — friction to add a third feature stream? → D-28
- [ ] Render 1 day of candles + VWAP + levels in a candidate chart library. → D-43
- [ ] Estimate a minimal custom event-driven loop; compare honestly with the Backtrader friction.

---

## Recording results

Write the answer under each spike with a date, then update the affected
decisions in `05-decision-register.md` and flip their status from BLOCKED to
OPEN or DECIDED.

Keep the failures. "Breeze returns nothing for options before 2021" is exactly
the fact that gets rediscovered painfully six months later.

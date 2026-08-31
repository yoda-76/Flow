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

# Findings — evidence gathered toward the spikes

This file records empirical and documentary evidence as we gather it,
separately from the reference doc set (`00`–`08`), which stays untouched. It
mirrors the spike IDs (`S-xx`) in `06-spikes.md` — read that file for what
each spike is trying to answer; this file records what we've actually found.

**Every entry is tagged by source**, because "the docs claim X" and "we
verified X against a live call" are different strengths of evidence and
`06-spikes.md` itself warns that Breeze's claims and delivery have diverged
before:

- **[DOC]** — read from provider documentation, not yet tested live.
- **[LIVE]** — confirmed against a real API response.
- **[CODE]** — observed behavior of existing working code in this project
  (`backtest/breeze`), which is real evidence even though it predates this
  round of research.

Decisions built on a **[DOC]**-only finding should treat it as provisional
until a **[LIVE]** entry confirms or contradicts it. See `decisions.md` for
where these get turned into actual answers.

---

## S-01 — Breeze historical coverage

**[DOC]** `get_historical_data` (v1) and `get_historical_data_v2` both accept
absolute `expiry_date` + `right` + `strike_price` for options, and return
`open_interest` populated (non-null) in every documented example. This is the
mechanism D-50's whole chain-pull plan depends on — the docs at least claim
it works as assumed. *(Source: `breeze-connect` PyPI page, "Historical Data:
Options" / "Historical Data V2: OPTIONS" sections.)*

**[DOC] ⚠ Unresolved conflict — 1-second historical interval.**
- The PyPI page's headline claim ("10 years of historical market data
  including 1 sec OHLCV") and the `get_historical_data_v2` method's own NOTE
  ("interval either as `1second`,`1minute`, `5minute`, `30minute` or as
  `1day`") both assert 1-second historical retrieval works.
- But the formal HTTP parameter tables on the API Reference site, for
  **both** `/v1/historicalcharts` and `/v2/historicalcharts`, list only
  `"1minute","5minute","30minute","1day"` as accepted interval values — no
  `1second` anywhere in either table.
- The only place `1SEC` is documented without ambiguity is the **live
  streaming candle channel** (`Candle Data LIVE` / `StreamLiveOHLCV`, a
  socket.io feed) — explicitly real-time, not a historical query.
- **Conclusion: whether 1-second historical data is actually retrievable via
  REST is not established by documentation alone — Breeze's own docs
  disagree with themselves.** This is precisely what S-01 needs to settle
  with a real call before D-08 (canonical resolution) leans on it. Until
  then, treat "1-second for index/futures" as unconfirmed, not as a fallback
  default.
- **Affects:** D-08 directly. Also softens confidence in §3/§4 of
  `04-tooling-landscape.md`, which repeats the "1sec/1min/5min/30min/1day"
  claim without flagging this — not a criticism, that doc was explicit about
  §5/§6 being unverified but treated §2–§4 (read from docs) as high-trust.
  This shows even the "read directly from docs" tier needs a live check for
  claims that appear inconsistently across the same provider's own pages.

**[LIVE] ✅ Conflict resolved 2026-08-30 — `interval="1second"` works via
REST.** Ran `get_historical_data_v2(interval="1second", ...)` against RELIND
cash for a real 2-minute window: got `Status 200` and 30 distinct
sub-minute rows (e.g. `09:30:02`, `09:30:07`, `09:30:11`, ...), several with
`volume: 0` — i.e. genuine per-second bars (price repeats, volume zero when
no trade landed in that second), not a duplicated/faked 1-minute series. The
API Reference's formal parameter table was simply incomplete; the PyPI
docs' claim was correct.
**This satisfies the reopen trigger recorded on D-08 in `decisions.md`.**
See that file's "Reopened decisions" section.

**[LIVE] Confirmed on index and futures too**, same day, same 2-minute
window (`09:30`–`09:32` IST, 2026-08-28):
- **NIFTY futures** (near month, expiry `29-SEP-2026`): 97 rows over 120
  possible seconds — much denser than equity cash's 30/120, consistent with
  futures being far more liquid. `open_interest` populated
  (`15001545`), real per-second volume.
- **NIFTY index** (`stock_code="NIFTY"`, `exchange_code="NSE"`,
  `product_type="cash"`): 121 rows over a 120-second window (boundary
  inclusive both ends, i.e. essentially a tick every second), `volume: 0`
  throughout — expected, the index isn't itself traded, it's a computed
  value updated continuously.
- **Side effect: resolves the `NIFTY` vs `NIFTY 50` folder-naming ambiguity**
  noted in `backtest/breeze/data_pipeline/data_structure.md` — the real
  index is `stock_code="NIFTY"` on `exchange_code="NSE"`,
  `product_type="cash"`. Whichever of the two raw folders was populated
  through that exact combination is the canonical one; worth a quick check
  against that project's `data_fetch_script.py` config next time it's
  touched, not urgent for FLOW itself.
- **1-second historical is now confirmed across all three instrument
  classes D-08 cares about: equity, index, futures.** Not yet tested on
  options (expected infeasible at request-budget scale per the existing
  §4 request-budget analysis, not a coverage question).

**[LIVE] Silent-empty-response hazard reconfirmed** 2026-08-30, independent
of the equity pipeline's earlier encounter with it: `get_historical_data_v2`
with `stock_code="ZZZINVALIDCODE"` returned `Status 200, Error: None, Success:
[]` — no error, no signal anything was wrong. Confirmed on the v2 endpoint
specifically (the earlier [CODE] evidence was from a version of the
downloader that may have used v1 or the SDK's older wrapper).

**[LIVE] Repeat-pull consistency confirmed**: identical request issued twice
(1 second apart) returned byte-identical `Success` payloads. Weak evidence
Breeze doesn't restate data moment-to-moment; doesn't rule out later
revision (would need a pull repeated across days).

**[LIVE] ⚠ Request-timestamp gotcha, found the hard way: the `Z` suffix is
cosmetic, not UTC.** First run of the experiment script converted IST session
boundaries to true UTC before formatting (e.g. `15:30 IST → 10:00:00.000Z`,
correctly per ISO 8601). Result: every "recent day" pull came back
truncated or empty — a 2-minute equity control window returned 0 rows, and a
"full day" request (`03:45Z`–`10:00Z`, i.e. genuinely 09:15–15:30 IST)
consistently returned only 47 rows running from `09:07` to exactly `10:00`,
reproduced identically across 4 different dates and 2 different instruments.
Conclusion: **Breeze reads the `HH:MM:SS` digits in `from_date`/`to_date` as
literal IST wall-clock time regardless of the trailing `Z`** — a correctly
UTC-converted `10:00:00.000Z` (meant as 15:30 IST) gets silently reinterpreted
as 10:00 IST, truncating the request instead of erroring. This is exactly
the family of silent-misbehavior hazard `06-spikes.md` warns about, just in a
form nobody had flagged: **it doesn't fail, it silently returns a plausible
but wrong subset.** The existing working equity pipeline never hit this
because `data_fetch_script.md`'s known-working pattern already passes IST
clock values directly with a cosmetic `Z` (e.g. `09:00:00.000Z` meaning 9am
IST) rather than converting — this finding explains *why* that convention is
load-bearing, not just a stylistic choice. **Rule for all future ingestion
code: never convert session times to true UTC before sending to Breeze —
build request timestamps as IST wall-clock values with a `Z` appended,
exactly like the existing pipeline does.** Fixed in
`experiments/s01_breeze_coverage_check.py`; all results below are from the
corrected run.

**[LIVE] Deep historical option coverage confirmed — 2 years and 5 years
back, full session, real OI.** After the timestamp fix:
- A **currently-live** NIFTY contract (discovered via `get_option_chain_quotes`,
  expiry `2026-09-01`, strike `24200`, ATM): full-day pull (09:15–15:30 IST,
  1-minute) returned **376 rows**, `open_interest` populated throughout
  (e.g. `11234990` → `12152855` → `12714650`, rising through the session —
  genuinely changing, not a static placeholder).
- A **~2-year-old expired** contract (guessed: NIFTY 21000 CE, expiry
  `2024-01-25`) returned **376 rows**, full session, real OI
  (`750350` → `715900`, ...) and real volume (`71300`, `21350`, ...).
- A **~5-year-old expired** contract (guessed: NIFTY 16500 CE, expiry
  `2021-08-26`) returned **376 rows**, full session, real OI (`2349750` →
  `2399100`) and real volume (`286400`, `405700`, ...).
- All three guessed/discovered strikes happened to be reasonably liquid
  (meaningful volume throughout), so this doesn't yet establish behavior for
  deep-OTM or genuinely illiquid strikes — worth a follow-up.
- **This is strong direct evidence for D-50's core premise**: multi-year
  historical option chains at absolute strike+expiry, 1-minute, with real
  OI, are genuinely retrievable via Breeze — not just a documentation claim.
- Row count is 376, not the nominal 375 (09:15–15:29 inclusive) — a
  boundary-inclusivity quirk worth pinning down before it corrupts a
  session-count validation check (see D-11/data-quality validation).
- The equity-cash full-day pull on the *same calendar day* returned only
  **370** rows (5 fewer than the option's 376) — a concrete, real instance of
  D-11's "rows absent for genuinely missing minutes" being an actual
  phenomenon on this data, not just a theoretical concern.

**[LIVE] `count` field is v1-only, not present in v2.** None of the v2
responses captured here (equity or options) carry a `count` key — only the
PyPI docs' *v1* (`get_historical_data`) examples showed it. Resolves the
earlier [DOC] open question: nothing to chase for v2, which is what
`data_fetch_script.py` and this experiment both use.

**[LIVE] `expiry_date` format in v2 responses confirmed 4-digit year**
(`"01-SEP-2026"`, `"25-JAN-2024"`, `"26-AUG-2021"`) — matches the [DOC]
finding above, now confirmed live rather than just from a documentation
sample.

**[DOC]** Historical data (v1 and v2, all product types) explicitly does
**not** account for corporate actions: "The historical data provided does
not account for corporate adjusted data." Not previously noted anywhere in
the FLOW doc set. Matters for any equity backtest spanning a split/bonus, and
for D-06 (does the instrument master need an adjustment-factor concept, or do
we accept unadjusted history and flag known corporate events as market-rule
data per `08`'s pattern).

**[DOC]** Every historical bar response (v1 and v2, all product types)
carries a `count` field (e.g. `count: 6`), undocumented. Likely trade count
per bar. Not currently part of the canonical schema sketch in D-04. Worth a
live check — if genuine, it's a free secondary liquidity signal.

**[DOC]** `expiry_date` formatting is inconsistent across endpoint versions:
v1 responses render `'06-FEB-25'` (2-digit year), v2 responds
`'06-FEB-2025'` (4-digit year). A parsing hazard in the same family as the
timestamp-format bugs already documented in
`backtest/breeze/data_pipeline/data_fetch_script.md`.

**[CODE]** Confirmed for **equity cash only**, from the existing working
pipeline in `backtest/breeze`:
- Candle `datetime` is a naive string in IST wall-clock time
  (`"2026-01-09 12:39:00"`), not UTC despite the request timestamps using a
  trailing `Z`. First candle of a session is `09:15` → bar-labelled-by-open,
  confirming D-07's draft assumption for at least this segment.
- The silent-empty-response failure mode that `06-spikes.md` warns about is
  not hypothetical — an early version of this project's downloader wrote
  `{"status": "empty", "data": []}` files that looked complete but weren't.
  Direct evidence for D-49's "make failure loud" principle, not just a
  precaution.
- Request timestamps must have **exactly 3-digit milliseconds** (`.000Z`); 4
  digits produces `"Date not in Proper Format"`.
- ~1000 candles/request confirmed in practice; 2-trading-day chunks is the
  safe pattern for 1-minute equity cash (375 candles/day × 2 ≈ 750).
- None of the above has been verified yet for **futures or options** — that
  gap is what's currently being filled.

---

## S-02 — Volume and request budget

**[DOC]** Rate limits confirmed as previously assumed: 100 calls/min, 5,000
calls/day, max 1,000 candles/request for v2. No new information beyond what
`06-spikes.md` already had.

**[LIVE] Real per-row and per-contract-day sizes** (raw, uncompressed JSON
as returned — before any Parquet/columnar compression):
- Equity cash, 1-minute, full day (370 rows): 61,257 bytes → **~166
  bytes/row**.
- NIFTY option, 1-minute, full day (376 rows): ~107,600–108,300 bytes across
  three separate contract-days → **~287 bytes/row** (options carry
  `expiry_date`, `strike_price`, `right`, `product_type`, `open_interest` on
  top of the equity fields, roughly 1.7× the per-row cost).
- 1-second equity, 30 rows over a 2-minute window: 4,950 bytes → ~165
  bytes/row, same as 1-minute — row shape doesn't change with interval, only
  row *count* does, and count is bounded by actual tick activity, not by
  wall-clock seconds (30 rows in 120 possible seconds — the data is sparse
  where the instrument doesn't trade every second, which is good news for
  storage: 1-second data is not literally 60× the row count of 1-minute for
  a moderately-liquid name, it's activity-bounded).

**[LIVE] Real contract-per-expiry counts from the SecurityMaster** (see
`../../SecurityMaster/FONSEScripMaster.txt`, a live security-master dump —
current listings only, not historically point-in-time). This directly
answers the flagged assumption in `06-spikes.md` S-02
("Measure actual contracts per expiry on a real NIFTY chain — the ladder is
wider than the ~100 assumed"):

| Expiry | Type | CE | PE | Total |
|---|---|---|---|---|
| 01-Sep-2026 (nearest weekly) | weekly | 231 | 231 | **462** |
| 08-Sep-2026 | weekly | — | — | 432 |
| 15-Sep-2026 | weekly | — | — | 424 |
| 29-Sep-2026 (monthly) | monthly | — | — | 512 |

**The real ladder (~460 contracts for a near weekly) is roughly 4.6× the
~100 previously assumed for the request-budget math in `06-spikes.md`/D-50.**
Rough extrapolation from this and the per-contract-day request cost (1
request per contract per day suffices — 376 candles is well under the
1,000/request cap): a full weekly chain pull is ~460 requests per trading
day of history, not ~100. **This meaningfully lengthens D-50's schedule
estimate** ("~8 days of pulling per year, ~6 weeks for 5 years") — recompute
that once we decide how many expiries/underlyings D-50 actually needs
(front-weekly-only vs. all live expiries), since the multiplier compounds
with that scope choice. Flagging this for the D-50 discussion rather than
recomputing the schedule here, since expiry-scope is still open.

---

## S-06 — Reconciling instrument universes

**[DOC]** `get_names(exchange_code, stock_code)` and the downloadable
SecurityMaster confirm Breeze's own `stock_code` (e.g. `ICIBAN`) differs from
the exchange-listed symbol — the response distinguishes
`exchange_stock_code` from `isec_stock_code` plus an `isec_token`. This is
the same shape of problem as the already-known `CNXBAN` (Bank Nifty) quirk in
`06-spikes.md`, but general: **any** Breeze `stock_code` may need mapping,
not just index names. Confirms a mapping table is required, not optional, for
D-05/D-06's three-way reconciliation (Breeze / Dhan / NSE).

**[LIVE] BANKNIFTY weekly discontinuation confirmed independently.**
`08-market-abstraction.md` notes "weekly expiry restricted to one benchmark
index per exchange — BANKNIFTY, FINNIFTY, MIDCPNIFTY weeklies discontinued
(believed late 2024; verify dates)". The SecurityMaster
(`FONSEScripMaster.txt`) has **zero** `BANKNIFTY` `OPTIDX` contracts for
NIFTY's nearest weekly expiry (`01-Sep-2026`) — consistent with weeklies
being gone for that index, from a completely independent source (current
live listings, not a memory of a circular). Doesn't pin down the exact
discontinuation *date* — that still wants a circular reference — but
corroborates the claim's current-state accuracy.

---

## Dhan account readiness (blocks S-02/S-03/S-06 Dhan-side work)

**[LIVE]** 2026-08-30 — direct REST auth against Dhan (`GET /v2/profile` with
`access-token`/`dhanClientId` headers, per `experiments/s06_cross_provider_check.py`)
succeeded: token and client ID are valid. But the actual data call
(`POST /v2/charts/intraday`, NIFTY futures) failed with:

```
401 DH-902 Invalid_Access: "User has not subscribed to Data APIs or does not have
access to Trading APIs. Kindly subscribe to Data APIs to be able to fetch Data."
```

**This is an account-subscription gate, not a bug or a wrong request** — the
Data APIs subscription (~₹499/month, already noted in
`04-tooling-landscape.md` §9) isn't active on this account yet. It blocks
**all** Dhan data access: historical, live feed, everything — not just this
one call. S-02 (Dhan-side volume), S-03 (live packet fields), and S-06's
Breeze/Dhan overlap comparison are all stuck behind this specifically, not
behind anything technical. The Breeze half of the S-06 comparison ran fine
(11 rows, NIFTY futures, 2026-08-28 09:30–09:40 — `24318.0` → `24322.0`,
OI `15003040` → `15013505`) and is sitting ready in
`experiments/results/s06_cross_provider_20260830T091604.json` for the moment
Dhan's side is unblocked.

## D-27 — Option chain as object or query (evidence, not a decision)

**[DOC]** `get_option_chain_quotes(stock_code, exchange_code, product_type,
right, expiry_date)` returns the **entire strike ladder for one side** (all
calls, or all puts) of an underlying+expiry in a single call — the API
requires at least 2 of {`expiry_date`, `right`, `strike_price`}, and omitting
`strike_price` is what returns the full ladder. No greeks/IV in the response
(consistent with the existing finding that Breeze's live chain lacks greeks,
unlike Dhan's). Useful as a cheap, request-light cross-check against Dhan's
live chain — 2 calls per underlying+expiry (one per side) rather than one
call per strike.

---

*Next: still open — 1-second confirmed on equity cash but not yet directly on
index/futures; deep-history coverage confirmed only on reasonably liquid
guessed strikes, not deep-OTM/illiquid ones; exact discontinuation date for
BANKNIFTY/FINNIFTY weeklies still wants a circular reference; D-50's schedule
estimate wants recomputing against the real ~460-contract ladder width once
expiry scope is decided; S-06's futures cross-provider comparison (Breeze vs
Dhan on an overlapping day) hasn't been run yet — can be done via the Dhan
MCP tools available in this session once a concrete day is picked.*

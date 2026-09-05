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

**[LIVE] (local SecurityMaster file scan, not an API call) SecurityMaster
does NOT contain historical/expired contracts — current+near-future
listings only.** Scanned all 77,886 rows of `FONSEScripMaster.txt` via
`experiments/check_securitymaster_expiry_coverage.py` for NIFTY and
BANKNIFTY (`CNXBAN`) OPTIDX/FUTIDX expiries: earliest expiry anywhere in the
file is `2026-08-18` — right at the file's own download date (Aug 14,
2026). Nothing from 2021, 2024, or even earlier in 2026. **This settles
D-52's sourcing question in the negative**: the security master cannot seed
a historical expiry calendar, because it's a "what's tradable right now"
snapshot, regenerated daily by design — not an archive. A real historical
expiry calendar needs a different source (NSE's own historical
bhavcopy/circular archives, most likely) or has to be bootstrapped
opportunistically from the D-50 chain-pull's own responses as it runs.
Side confirmation while scanning: `CNXBAN` (Bank Nifty) has only 4 expiries
in the file, all monthly-spaced (`2026-08-25, 2026-09-29, 2026-10-27,
2026-12-29`) — no weeklies at all, consistent with the discontinuation noted
below.

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

## S-06 — Breeze/Dhan overlap comparison (the actual R17 question)

**[LIVE]** 2026-09-06, once both the Dhan subscription and a fresh Breeze
token were in place — ran `experiments/s06_cross_provider_check.py`: NIFTY
futures (expiry 29-Sep-2026, shared token/securityId `68407`), 2026-08-28,
09:30–09:40 IST, pulled independently from both providers.

**Result: perfect agreement.** Of the 11 requested minutes, 9 timestamps
came back from both providers, and every single one matched **exactly** —
close price to the decimal (e.g. `24315.1`, `24321.8`, ...) and open
interest to the exact integer (e.g. `15003625`, `15000765`, ...) on all 9.
This is the actual empirical answer to R17's "one continuous timeline"
claim and S-06's explicit question ("do Breeze and Dhan 1-minute futures
bars agree?") — on this sample, yes, without qualification. Feeds directly
into D-12 (provenance/overlap policy, still formally BLOCKED pending a
larger sample, but this is a strong positive first data point rather than
the "routine disagreement" scenario the register worried about).

**[LIVE] Boundary convention differs between providers — a real thing to
handle in the adapter layer, not a bug.** Requesting `fromDate=09:30:00,
toDate=09:40:00` from Dhan's `/v2/charts/intraday` returned only
`09:31:00`–`09:39:00` (9 candles) — **both endpoints are exclusive.**
Breeze, given the identical logical window, returned all 11 candles
inclusive of both endpoints. Anyone requesting "a full session" from Dhan
needs to pad the request window by one interval on each side to get the
true inclusive range; Breeze needs no such padding. This is exactly the
kind of provider-specific quirk principle #11 (adapters own provider
logic) exists to contain — it must not leak into canonical-layer code.

## Dhan account readiness (RESOLVED 2026-09-06 — subscription active)

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
Breeze/Dhan overlap comparison were all stuck behind this specifically, not
behind anything technical.

**Resolved 2026-09-06** — the account subscribed to Dhan's Data APIs.
Confirmed unblocked via `/v2/optionchain/expirylist` and
`/v2/charts/rollingoption` both returning real data instead of `DH-902`
(see the D-52 experiment below), and via a full S-06 comparison run (see
above). S-02's Dhan-side volume numbers and S-03's live packet-field
checks (need market hours) are the remaining unstarted work — no longer
blocked on the subscription, just not yet run.

## NSE's own historical F&O data framework (RESOLVED — closes D-52, D-46 unchanged)

**[DOC]** 2026-09-06 — `https://archives.nseindia.com/content/press/Data_Details_F_n_O.pdf`
(NSE Data & Analytics' own spec document) describes a formal historical
data framework for the F&O segment, organized by month (`yyyymm`) with five
sub-directories per month:

- **Bhavcopy** — one file per trading day, one row per contract, pipe-
  delimited: date, symbol, instrument type, **expiry date**, option type,
  corporate-action flag, strike, OHLC, LTP, open interest, total traded
  quantity/value, number of trades. **This directly answers D-52's
  outstanding sourcing question** — every day's file lists every contract's
  expiry date that had activity that day, which is a complete historical
  expiry calendar as a byproduct of something NSE already publishes daily.
- **Masters** — month-end contract master including lot size, **Token
  Number** (same concept as the Breeze/Dhan shared token already confirmed
  identical — see the D-05 finding above), issue start/maturity dates,
  exercise start/end dates. Dated monthly, which is exactly the
  time-versioned source D-06 needs for lot-size-change history — a real
  candidate for "authoritative source" that isn't Breeze or Dhan at all.
- **Snapshots** — full limit-order-book snapshots at several fixed times
  per day, back to (at least) 2003 per the document's own example.
- **Trades** — ⚠ **every single trade, every day, with trade time
  (hh:mm:ss), price, and quantity, per contract** — described as existing
  since 2003. **If this is genuinely accessible for historical dates, it
  directly contradicts D-46's premise that "no historical order-flow data
  exists from any accessible provider."** That decision was made in good
  faith based on Breeze and Dhan being the only providers considered; NSE
  itself was never checked.
- **Circulars** — exactly the historical-circular archive `08` says is
  needed to verify lot-size/expiry-day change dates rather than trusting
  memory.

**⚠ Not yet confirmed accessible.** Two measured attempts to fetch a real
bhavcopy file (`archives.nseindia.com/content/historical/DERIVATIVES/...`)
returned `503`, and even the plain `www.nseindia.com` homepage returned
`403` to a bare request — consistent with NSE's well-documented bot
protection (Akamai-style), not evidence the data itself is unavailable.
The document's own branding ("NSE Data & Analytics") also raises a real
question: this may describe NSE's **commercial** data-vending product
rather than something freely downloadable from the public archive site —
that distinction is not yet resolved either.

**[LIVE] 2026-09-06 — resolved, mixed result.** Bare `curl`/browser requests
were blocked (403/503, NSE's bot protection), but the community libraries
`jugaad-data` and `nsepython` handle NSE's session/header requirements
internally. Tested directly:

- **Bhavcopy is real, free, and working.** `jugaad_data.nse.bhavcopy_fo_raw(date(2024, 1, 25))`
  returned genuine 5.3MB of CSV — every F&O contract traded that day, with
  `EXPIRY_DT`, `STRIKE_PR`, `OPTION_TYP`, OHLC, `SETTLE_PR`, `CONTRACTS`
  (volume), `OPEN_INT`, `CHG_IN_OI`. **This closes D-52 concretely** — not
  just "NSE archives exist," but a confirmed, working, free mechanism to
  get the expiry calendar as a byproduct of data already being pulled.
  Bonus: this also removes the guesswork D-50's chain pull would otherwise
  need — bhavcopy tells you the *exact* contracts that existed on a given
  historical day before you spend a single Breeze request on it.
- **Trades/Snapshots (tick-level) are NOT exposed by either library** —
  searched both for any trade/tick/snapshot/depth/orderbook function,
  found nothing in either. Combined with the bot-protected, paid-branded
  ("NSE Data & Analytics") nature of the original PDF, this is strong
  evidence the 2003-era Trades/Snapshots archive is no longer freely
  available — it was very likely folded into NSE's commercial data-vending
  product at some point. **D-46 is NOT reopened.** Order-flow remains
  forward-only by design, as originally decided — this was worth checking
  rather than assuming, and the check came back negative.
- **Masters (lot-size history) is also not exposed by either library** —
  D-06's authoritative-source question isn't solved by this after all.
  `08`'s original suggestion (verify lot-size change dates against exchange
  circulars directly, rather than a data file) remains the live path for
  D-06 — there are only a handful of known revisions historically, likely
  more tractable to encode by hand from circulars than to find a bulk data
  source for.

---

## D-52 — Dhan expiry-discovery experiment (subscription still blocking)

**[LIVE]** 2026-09-06, after a fresh access token — the subscription block
is unchanged, but two real API quirks surfaced along the way, worth fixing
in code regardless of subscription status:

- **Header-name inconsistency across Dhan's own endpoints.** `/v2/profile`
  and `/v2/charts/intraday` accept `dhanClientId`; `/v2/optionchain/
  expirylist`'s own doc page specifies `client-id` instead — sending only
  `dhanClientId` to that endpoint gets back a misleading
  `{"810": "ClientId is invalid"}` rather than the real subscription error.
  Sending both header spellings on every request resolves it and reveals
  the actual state underneath. Fixed in both experiment scripts.
- **`expiryCode: 0` ("near expiry") is broken server-side.** `/v2/charts/
  rollingoption` rejects it with `DH-905 "expiryCode is required"` — tested
  both as JSON int `0` and string `"0"`, both fail identically. `expiryCode:
  1` ("next expiry") passes validation and reaches the real gate
  (`DH-902`). This looks like a classic falsy-value bug (0 treated as
  "not provided") in Dhan's own backend, not a mistake in our request.
  Workaround applied in `d52_dhan_expiry_discovery_check.py`; worth
  re-testing `0` once subscribed, in case it's coincidentally tied to the
  subscription check rather than a pure validation bug.

**Net result (before subscription): the Data API subscription is the single
blocker.** `/v2/optionchain/expirylist` correctly surfaces `{"806": "Data
APIs not Subscribed"}`, and `/v2/charts/rollingoption` (once past the
expiryCode bug) surfaces the same `DH-902` seen before.

**[LIVE] 2026-09-06, subscription now active — full result.**

- `/v2/optionchain/expirylist` for NIFTY now returns 18 distinct future
  expiries out to `2031-06-24` — considerably further forward than the
  downloaded SecurityMaster's snapshot (max `2027-06-29`), confirming Dhan's
  live listing is more complete than a point-in-time SecurityMaster dump.
  Still current+future only, exactly as documented — nothing before today.
- `/v2/charts/rollingoption` genuinely works: pulled real hourly OHLC + OI +
  strike + spot for NIFTY calls, `expiryFlag=WEEK`, `expiryCode=1`, from
  2024-01-02 to 2024-01-26 — **~130 real hourly bars, ATM strike visibly
  tracking spot as it moved from 21650 down through 22100 and back to
  21250-21400 across the window.** This is a second, independent
  confirmation (via Dhan, not just Breeze) that genuine 2-year-old
  historical option data exists and is retrievable.
- **But the response never reveals which expiry was active at any point** —
  no expiry field anywhere in `ce`/`pe`, despite the data clearly being
  drawn from real dated contracts underneath. Confirms the docs' own
  warning ("must reference instrument list separately") empirically, not
  just by reading it. **This closes D-52's experiment with a negative
  result**: this endpoint cannot seed a historical expiry calendar, however
  good it is for other purposes.
- Two secondary gaps, real API behavior not a request mistake: `volume` and
  `iv` came back as empty arrays despite being explicitly listed in
  `requiredData`, while `oi`/`strike`/`spot`/OHLC all populated correctly.
  Worth checking whether these are ever populated for this endpoint before
  relying on them.
- The endpoint returns one option side per call (`pe: null` here since only
  `CALL` was requested) — same two-calls-per-side shape as Breeze's
  `get_option_chain_quotes`.
- **`expiryCode=0` bug confirmed independent of subscription state** — it
  failed with `DH-905` identically both before and after the subscription
  activated; `expiryCode=1` is the correct workaround regardless.

---

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

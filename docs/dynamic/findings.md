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

## D-28 — NautilusTrader spike, part 1 (instrument + data ingestion)

**[LIVE]** 2026-09-06 — the `04-tooling-landscape.md` §8 spike, run against
a real 2-day sample (NIFTY, front-week expiry 2026-08-04, 226 contracts
pulled from Breeze — 193 with real data, 33 empty). Full pipeline exercised:
Breeze pull → raw JSON (D-02) → canonical Parquet (D-04/D-05) → DuckDB
queries → NautilusTrader ingestion.

**Parquet + DuckDB (D-01), on real chain-shaped data — strong result.**
136,867 rows, 193 instruments, built from raw JSON in ~1-3.6s. Parquet:
1.77MB vs 55MB raw JSON (**31x compression**). All three realistic query
patterns fast: full chain at one timestamp (191/193 rows — 2 genuinely
missing at that exact minute, real D-11 "rows absent" behavior, not a
bug) in 53-62ms; one instrument's full series in 11-17ms; end-of-window OI
snapshot in 10-14ms. This is a solid, real-data confirmation of D-01's
decision, not just a single-instrument toy example.

**Spike question #1 (can you define an NSE option with correct
multiplier/lot/expiry?): yes, cleanly.** `OptionContract` takes
`multiplier`, `lot_size`, `strike_price`, `option_kind` (PUT/CALL),
`underlying`, `expiration_ns`, `exchange` (ISO 10383 MIC), and an `info`
dict for extras. `InstrumentId` is `Symbol.Venue` — market-namespaced by
construction, confirming the `04-tooling-landscape.md` claim directly
rather than trusting it. **Caveat: no native time-versioning.** Each
`OptionContract` is a fixed snapshot — if a lot size changes, Nautilus
doesn't version that itself; our own D-51 rules store would still need to
construct and swap in the correct `Instrument` object for whatever period
is active. Nautilus doesn't fight this, but doesn't solve it either.

**⚠ Real bug found: NautilusTrader 1.231.0 is broken under pandas 3.x,
despite declaring `pandas>=2.3.3,<4.0.0` support.** `BarDataWrangler.process()`
failed with `ValueError: buffer source array is read-only` — pandas 3.0
made Copy-on-Write permanent and non-optional, so `.values`/`.to_numpy()`
now return read-only arrays by default, even from a brand-new DataFrame
built from a freshly-allocated writable numpy array (confirmed directly,
not DuckDB-specific). Neither `.copy()` nor `to_numpy(copy=True)` into a
new DataFrame fixes it — pandas re-imposes the read-only view regardless.
Nautilus's Cython wrangler reads the buffer via a raw memoryview, which
bypasses whatever pandas mechanism would normally trigger a real copy.
**Fix: pin `pandas<3`** (tested working at `2.3.3`, their own declared
minimum) — this is a real gap in Nautilus's declared compatibility range,
not a mistake in our code. Same "verify the metadata, don't trust it"
lesson already hit twice with Breeze and Dhan, now a third time with a
different kind of dependency (library compatibility claims, not API docs).

**Gap found: `open_interest` is not natively carried through the standard
Bar pipeline.** `BarDataWrangler.process()` only accepts
`open/high/low/close/volume` — confirmed by reading its actual docstring
and by testing (OI present in our source data, silently absent from the
resulting `Bar` objects since it was never passed in). For an
options/GEX-centric project this matters a lot. Not yet resolved: whether
Nautilus's custom-data mechanism (`@customdataclass` or similar, per
`04-tooling-landscape.md`'s general claim about extensibility) can carry
OI alongside bars, or whether OI needs to live entirely outside Nautilus's
data model in our own feature layer. This is directly relevant to spike
question #3 (attaching a custom chain-level feature like GEX) — not yet
tested.

**ParquetDataCatalog confirmed real, not just a name.** `catalog.write_data()`
+ read-back round-tripped 714 bars and 1 instrument correctly. It manages
its own internal Parquet layout (`data/option_contract/...`,
`data/bar/...`, filenames encoding the covered time range in nanosecond
timestamps) — it is **not** a matter of pointing it at our own canonical
Parquet files directly; ingestion goes through Nautilus's own object model
(`Instrument`, `Bar`) first, catalog storage is downstream of that, not a
replacement for our own canonical layer.

**Update, same day — this is much more substantial than a plain OHLC test
suggested.** Digging past the Bar pipeline into `nautilus_trader.model`
found a real, shipped options-analytics subsystem, not just generic
plumbing:

- **`GreeksData`** (`@customdataclass`): delta, gamma, vega, theta, IV,
  strike, expiry, multiplier, underlying price, cost of carry, interest
  rate — a full per-contract Greeks record, versioned/timestamped like any
  other Nautilus data.
- **`PortfolioGreeks`**: the same fields with real `__add__`/`__rmul__`
  operators — genuine portfolio-level Greeks aggregation, not just a data
  container.
- **`black_scholes_greeks(s, r, b, vol, is_call, k, t)`** — Generalized
  Black-Scholes with an explicit cost-of-carry parameter `b`. This is a
  direct, working answer to D-19/D-21's open question: Black-76 on futures
  (`b=0`) and standard Black-Scholes on spot (`b=r`) are **the same
  function**, just a parameter choice — not two implementations to choose
  between.
- **`imply_vol_and_greeks(s, r, b, is_call, k, t, price)`** — a real IV
  solver, directly relevant to D-19/S-04's "IV solver failures" checklist
  item.
- **`GreeksCalculator`** — wired into the shared cache/clock, accessible
  from any strategy/actor, for live instrument- and portfolio-level Greeks.
  Documented honest limitation: American options are treated as European
  for Greeks purposes — irrelevant for NSE (European-only, per D-19's
  market check) but would matter for a future ES/SPX profile.
- **`YieldCurveData`**: a discount-rate curve type with interpolation —
  covers D-19's "risk-free rate source" input as a first-class,
  timestamped, versionable object rather than a bare constant.

**What's still genuinely ours to build:** raw open interest is not a
native Nautilus concept (Greeks are *computed* from price+vol, OI is a raw
market observable — a different kind of thing), and GEX itself
(gamma × OI × multiplier, dealer-convention sign, chain/market-level
aggregation) is nowhere in the package. This is the expected, correct
split — Nautilus supplies the pricing/Greeks plumbing, we build the
actually-novel analytics on top, exactly matching `01-concept.md` §8b's
original framing.

**Tested directly, not inferred: can OI follow the same `@customdataclass`
pattern as `GreeksData`?** Yes — built a minimal `OpenInterestData` custom
type, converted all 714 real OI observations for one contract (genuinely
varying: 0 → 1105 → 455 across the window, not trivial zeros), wrote to
the catalog, read back. **All 714 values matched exactly**, timestamps
included. Two real bugs surfaced and fixed in the process, both about
timestamp unit handling, neither a Nautilus problem:
- `pd.DatetimeIndex(...).astype('int64')` silently produced garbage
  (a 1970 date) — needed the Series-level `.astype(...)` instead.
- **DuckDB's `.df()` now returns `datetime64[us]` (microsecond precision),
  not pandas' traditional `datetime64[ns]`** — a bare `.astype('int64')`
  silently gave epoch-microseconds, 1000x too small for the nanoseconds
  Nautilus expects everywhere. Must convert to `datetime64[ns]` explicitly
  before extracting epoch-int64. Worth remembering for any future
  DuckDB→Nautilus (or DuckDB→anything-expecting-ns) conversion code.

**Net assessment of D-28 so far**: meaningfully more promising than the
first OHLC-only pass suggested. The instrument model, Greeks/pricing
subsystem, and custom-data mechanism (proven for OI, not just assumed)
together cover a large fraction of what §8's spike was checking for.
**Not yet tested: a minimal Dhan adapter, and whether a genuinely
aggregated feature like GEX can attach to market state during a live
backtest run** (this OI test proves storage/round-trip, not runtime
consumption by a strategy) — real remaining gaps before D-28 can close.

---

## D-19/D-21 — Greeks verification against Dhan's live chain

**[LIVE]** 2026-09-06 — first empirical test of the D-19 claim "Dhan
supplies greeks on its live chain." Confirmed real: `POST
/v2/optionchain` (`UnderlyingScrip`, `UnderlyingSeg`, `Expiry`) returns, per
strike, `greeks.{delta,gamma,theta,vega}` and `implied_volatility` alongside
price/OI — not just a documentation claim, genuine live values (e.g. NIFTY
ATM call, 2026-09-08 expiry: delta=0.5292, gamma=0.00144, theta=-20.61,
vega=8.90, IV=12.34%).

**Compared against our own pipeline** (Nautilus's `imply_vol_and_greeks` /
`black_scholes_greeks`, spot-based, flat 6.5% rate proxy, no dividend
adjustment — a first-pass convention, not D-19/D-21's final answer) on two
contracts: the near-dated (2.5 days to expiry) and a 30-day-out one.

| | Dhan | Ours (our IV) | Ours (Dhan's IV) |
|---|---|---|---|
| **2.5d: delta** | 0.5292 | 0.5137 | 0.5155 |
| **2.5d: vega** | 8.896 | 7.840 | 7.839 |
| **30d: delta** | 0.6260 | 0.5721 | 0.5831 |
| **30d: vega** | 26.469 | 27.095 | 26.947 |

**Key isolation: even feeding Dhan's own stated IV directly into our
formula (bypassing our IV-solving step entirely), delta is still off by
~8-9% on the 30-day contract.** This rules out "our implied-vol solver is
wrong" as the explanation — vega actually matches well at 30 days (27.10 vs
26.47, ~2% off) once Dhan's own IV is used, but delta persistently doesn't.
That pattern — vega roughly right, delta systematically off, formula
correctness therefore not in question — points at the underlying-reference
or rate assumption, not the Black-Scholes math itself. Using plain spot
with no dividend/cost-of-carry adjustment is the most likely fixable
cause: NIFTY options are commonly priced off the futures-implied forward
rather than raw spot, which is exactly D-21's open question.
**Next concrete step, not yet run:** repeat this same comparison using the
NIFTY futures price with `b=0` (Black-76, per the `black_scholes_greeks`
signature's cost-of-carry parameter — see the D-28 findings above) instead
of spot with `b=r`, and see whether that closes the delta gap.

**Precision note confirmed along the way:** using a precise fractional
time-to-expiry (`now` → 15:30 IST on expiry day) instead of a crude integer
day count measurably improved the 2.5-day contract's match (theta gap
shrank from Dhan=-20.61 vs ours=-31.24 down to -20.61 vs -25.49) — for a
near-expiry option, T precision matters enough to change the comparison
meaningfully. Confirms this is a real methodological detail for D-19, not
a nicety.

**Limitation, unavoidable, already known from D-52's earlier test:** this
only validates the **live** case. Dhan has no historical greeks for
expired contracts (its rolling-option endpoint's `iv` field came back
empty in the D-52 test). For historical data the formula/pipeline has to
be trusted from this live validation — Black-Scholes doesn't change over
time, so if the pipeline is right here, it stays right historically,
*provided* the input conventions (rate source, underlying reference) are
settled first, which is exactly what this test is narrowing down.

---

## D-06/D-52 — bhavcopy coverage extended back to Jan 2024 (legacy + UDiFF)

**[LIVE]** 2026-09-07 — the instrument master and expiry calendar
previously only covered the UDiFF era (2024-07-08 onward, `findings.md`'s
earlier D-50 section). Extended `flow/rules/bhavcopy.py` to also handle
NSE's legacy (pre-UDiFF) bhavcopy format, per the user's request for full
Jan 2024 coverage ahead of the actual Breeze historical pull.

Confirmed live: `jugaad_data.nse.bhavcopy_fo_raw()` (the function whose
*post*-2024-07-08 behavior was already found dead — findings.md, D-50)
works correctly for dates *before* the cutover. Its column set is
genuinely different and **missing two things the UDiFF format has**: no
token/instrument-id column at all, and no lot-size column (`NewBrdLotQty`)
at all. Both formats do carry expiry/strike/right, so instrument identity
and the expiry calendar are unaffected — only lot-size and exchange_token
are unavailable for legacy-era-only observations.

Handled by: backward-extending each contract's earliest *known* lot size
(from its first UDiFF-era observation) into its legacy-era days, logged
explicitly per instrument rather than silently assumed — reasonable given
NIFTY's lot size is confirmed stable for long stretches (25, unchanged
from well before 2024-07-08 through 2024-11-22). For the further edge
case — a contract that existed and expired **entirely** within the legacy
era, with no later observation to infer from — lot_size is left `null`
rather than guessed, correctly flagged as an unavoidable, honest gap
(WARNING, not CRITICAL, in `store.py`'s validation).

**Full rebuild, Jan 1 2024 → 2026-09-07**: 661 trading days scanned (125
legacy-format, 40 holidays/weekends skipped), 31,513 instrument-period
rows across 18,756 distinct contracts, 206 expiry-calendar entries, 1,658
instrument_ids backfilled. Validation clean except the expected WARNING
(5,150 rows genuinely unbackfillable, legacy-era-only contracts).
`rules_as_of()` still correctly returns
`[2026-09-08, 2026-09-15, 2026-09-22]`.

## R25 — Breeze can return literally negative volume (real data-quality bug)

**[LIVE]** 2026-09-06 — first real run of `flow/canonical/build.py` +
`validate_canonical()` (D-44) against the Aug 3-4 2026 sample (193
instruments, 136,867 rows) caught a genuine Breeze data error: one bar
for `NIFTY 2026-08-04 27100 PE` (10:30 IST, Aug 4) has `"volume": -65`
paired with `"open_interest": 65` in Breeze's raw response — confirmed
straight from the saved raw JSON, not introduced by parsing. Deep-ITM/
illiquid strike, flat OHLC (single stale print). One isolated row out of
136,867, but a real, live confirmation that R25's validation requirement
("invalid volume") isn't a theoretical checklist item — it's already
needed on real data, on the very first canonical build attempted.
**Also confirmed working as designed**: the instrument-master cross-check
(`cross_check_against_instrument_master`) passed cleanly on all 193
instruments — the identity-construction logic in `canonical/build.py`
(built from Breeze's own row fields) agrees exactly with the
bhavcopy-derived instrument master (`rules/build_instrument_master.py`)
built independently through a completely different pipeline.

**Fixed, 2026-09-07** (per user instruction): the negative-volume bar is
no longer kept as-is or zeroed — `canonical/build.py` now nulls it out
during the raw→canonical build step itself, treated as "volume unknown for
this bar", not "zero trades" and not "-65 trades". `validate_canonical()`
now only asserts negative volume can't survive the build (would be a
CRITICAL if it ever did) and separately reports the null count as an
informational WARNING.

## D-05 — exchange_token is NOT a stable, permanent identifier (correction)

**[LIVE]** 2026-09-06, discovered while building `flow/rules/build_instrument_master.py`
from ~2.2 years of NIFTY bhavcopy (2024-07-08 to 2026-09-06). This
**corrects** the earlier S-06 finding that Breeze's `Token` and Dhan's
`securityId` are "the same NSE-assigned number" — that's still true as a
snapshot-in-time fact (confirmed on 3 contracts, same day), but two
further things are now confirmed that change what it's safe to build on:

1. **NSE recycles `FinInstrmId` (exchange token) numbers for unrelated
   contracts after expiry.** Token `47520` was three completely different
   contracts across the scan: `2024-12-19 26500 CE` (Dec 2024, lot 25),
   `2025-09-23 23200 CE` (Aug 2025, lot 75), `2026-01-20 23900 PE` (Jan
   2026, lot 65) — different expiries, different strikes, even different
   option types. A build script that grouped by raw token (an early
   version of this one did) silently merged three unrelated contracts into
   one fake multi-period "instrument" — caught immediately by a validation
   check (D-44's philosophy earning its keep in practice, not just in
   principle) rather than discovered later in a backtest.
2. **Even the same contract terms can get a new token after a delist/relist
   gap.** `NSE|NIFTY|2026-06-30|22000|CE` used token `58626` from
   2025-08-01 to 2025-12-30, then nothing for 3 months (likely delisted —
   a deep-OTM, far-dated monthly strike), then reappeared under a *new*
   token `79509` from 2026-04-01 onward. Same economic contract, new
   token — a milder, real, and different phenomenon from (1).

**This is exactly why D-05 chose the composite string as the primary
`instrument_id` and relegated the shared token to a secondary field** —
now empirically necessary, not just theoretically preferable. Had D-05
gone the other way (token as primary id), this would have been a silent,
serious correctness bug rather than a caught-and-fixed one.
**`exchange_token` remains useful** for same-day/current cross-provider
matching (which is all S-06 ever actually tested) — just not safe as a
permanent historical identifier on its own.

## D-06 — bhavcopy's lot-size field reflects genuine historical changes

**[LIVE]** 2026-09-06 — checked whether `NewBrdLotQty` in the UDiFF F&O
bhavcopy (already the D-52 mechanism) genuinely tracks historical lot-size
changes, rather than repeating a current/static value backward. Pulled
NIFTY futures' lot size across 7 dates spanning 2024-07 to 2026-08:

| Date | Lot size |
|---|---|
| 2024-07-10 | 25 |
| 2024-12-02 | 75 |
| 2025-01-06 | 75 |
| 2025-04-01 | 75 |
| 2025-07-01 | 75 |
| 2026-01-02 | 65 |
| 2026-08-28 | 65 |

**Genuinely changed on record: 25 → 75 (between Jul and Dec 2024) → 65
(between Jul 2025 and Jan 2026).** The first jump lands exactly in the
window `08-market-abstraction.md` already flagged from memory ("the
late-2024 SEBI minimum-contract-value increase") — now confirmed from real
exchange data rather than recollection. The second change wasn't
previously known/flagged anywhere in the doc set — a real example of
exactly the kind of silent historical change principle #16 and D-51 exist
to catch. **This closes D-06's sourcing question**: bhavcopy is a genuine,
free, dated source for contract-spec history, not just expiry dates —
same mechanism, same pipeline, no manual circular encoding needed.

**Refinement, found building `flow/rules/build_instrument_master.py`**:
grandfathering during a lot-size transition isn't universal or permanent.
`NSE|NIFTY|2025-03-27|18000|CE` (one single, continuously-listed contract,
same token throughout) started at lot size 25 and was force-migrated to 75
on 2025-12-27, *before its own expiry* — i.e. some already-listed
contracts got their lot size changed mid-life, not just grandfathered
until expiry. Confirms the earlier per-contract design (D-06's decision:
instrument master, not a per-underlying date rule) was the right call —
a per-underlying rule genuinely cannot represent this case either, since
it's a change to one specific existing contract, not a rule about new
listings.

**First real build, full result**: `flow/rules/build_instrument_master.py`
run over the full available UDiFF history (2024-07-08 to 2026-09-06, NIFTY
index futures+options) — 536 trading days scanned (29 holidays/weekends
skipped), 26,363 instrument-period rows (18,756 distinct contracts), 173
expiry-calendar entries. Validation (D-44) clean after two real bugs
caught and fixed (the token-recycling merge above, and a validation-logic
bug that flagged legitimate multi-period instruments as "duplicates").
`rules_as_of("NSE", "NIFTY", today, n=3)` independently returns
`[2026-09-08, 2026-09-15, 2026-09-22]` — matching Dhan's `expirylist`
result from the earlier D-52 experiment exactly, a clean cross-check that
the whole pipeline is self-consistent.

---

## D-19 — formula correctness, verified against an independent reference (not Dhan)

**[LIVE]** 2026-09-06 — `experiments/d19_formula_reference_check.py`. The
earlier "our formula is correct" claim (from the Dhan-comparison test
below) was an inference from a black-box comparison, not a real proof —
worth being precise about that distinction. This test is the actual rigorous
check: compares Nautilus's `black_scholes_greeks`/`imply_vol_and_greeks`
against `py_vollib` (an independent, separately-authored reference
library) on 6 synthetic scenarios (textbook + NIFTY-like ATM/OTM/ITM,
2.5 days to 6 months to expiry) — **pure synthetic inputs, zero real
market data, so no Dhan/Breeze staleness, no spot-vs-forward ambiguity, no
solved-IV uncertainty possible.**

**Result: matches to near machine precision across the board.**
Price/delta/gamma/vega within ~1e-6 in every scenario; theta within
~0.003-0.016 out of values around -5 to -22 (i.e. <0.1% relative —
consistent with tiny differences in each library's internal normal-CDF
approximation, not a methodology gap). **Max relative difference across
all 6 scenarios × 5 metrics: 0.069%.** The IV-solver round-trip (price →
implied vol → recovered original vol) is exact to ~1e-7 in every case.
(First run showed huge theta/vega "mismatches" — traced to an unnecessary
×365/×100 rescaling in the test script itself, not Nautilus; the two
libraries already share the same conventions once that's removed.)

**This decisively separates two previously-conflated questions.** The math
— Black-Scholes/Black-76 via Nautilus's cost-of-carry parameterization,
and the IV solver — is now verified correct, independent of any real-market
noise. The earlier Dhan-comparison finding (delta off ~8-9%, vega close)
is therefore cleanly attributable to an **input-convention** difference
(rate source, underlying reference) rather than any doubt about the
formula itself. That's exactly what the put-call-parity test below is
chasing, and what still needs Monday's live market to resolve properly.

## D-19/D-21 — forward derivation via put-call parity (weekend, inconclusive but instructive)

**[LIVE]** 2026-09-06 (Saturday, market closed) — `experiments/d19_forward_derivation_test.py`.
Rather than guess or fetch an external futures price (NIFTY futures are
monthly-only, so no matching-tenor future exists for a weekly option
anyway), derived the exact forward Dhan is implicitly pricing off directly
from their own quotes: put-call parity, `F = (C - P) × e^(rT) + K`, across
5 strikes near ATM, for both the nearest weekly (2.46 days) and a
monthly-like (30.46 days) expiry.

**Result is genuinely mixed, and the reason why matters:**
- **30-day expiry**: forward-based greeks (Black-76, `b=0`, using the
  derived forward) moved delta *closer* to Dhan's real values than
  spot-based did, across all 5 strikes (e.g. ATM: Dhan=0.6260,
  spot-based=0.5831, forward-based=0.5922 — closes about a quarter of the
  gap). Implied annualized cost-of-carry: 7.56% — a realistic number for
  NIFTY futures basis.
- **2.46-day expiry**: forward-based greeks were *worse* than spot-based
  at every strike (e.g. ATM: Dhan=0.5292, spot=0.5155, forward=0.6036 —
  spot was closer). Implied annualized cost-of-carry: **40.29%** — not a
  plausible real financing rate, a red flag the input data itself is bad
  here, not that the forward-adjustment idea is wrong.
- **Root cause, not just a guess**: per-strike implied forwards for the
  30-day expiry were dispersed across a **264-point range**
  (23931–24195) that should be nearly flat in a clean market. That
  dispersion, plus the impossible 40% carry rate on the near-dated expiry,
  is consistent with exactly what was anticipated going in — **stale,
  non-synchronous last-traded prices** (a call and its paired put may have
  last traded at different moments Friday; put-call parity assumes
  simultaneous prices, so non-synchronous last-trade noise gets amplified
  into a large, spurious "forward," especially for a short-T contract
  where dividing by a small T inflates any noise into a huge annualized
  number).
- **Confirmed directly, not assumed: Dhan's option chain is genuinely
  frozen on the weekend.** Re-queried the same chain 20 seconds apart —
  spot and every Greek were byte-identical. So further repeated pulls this
  weekend cannot produce a second, independent data point; a real repeat
  test needs Monday's live market.

**Conclusion: this specific test is inconclusive on the weekend, for a
real and now-understood reason, not a dead end.** The forward-adjustment
direction (closes gap at 30 days, realistic carry rate there) is
encouraging; the near-dated result is explained by data staleness, not
evidence against the hypothesis. **Next step, needs live market hours**:
repeat during Monday's session, ideally using bid/ask midpoint rather than
last-traded price to reduce the same non-synchronicity noise even when the
market is genuinely live (thinly-traded strikes can still have stale
last-trades intraday, just less severely than after 1.5 days closed).

**Side finding: Dhan's own market-feed caches have inconsistent weekend
availability.** `/v2/marketfeed/ltp` served frozen data fine for the NIFTY
index (`IDX_I`) but returned empty for the NIFTY future (`NSE_FNO`,
security id 68407) despite a well-formed, spec-matching request — meaning
different Dhan endpoints/segments cache weekend data differently. Worth
remembering when the recorder (D-37) has to handle a market-closed period
gracefully — "empty" doesn't uniformly mean "no data exists," it can also
mean "this particular cache doesn't serve stale values."

## S-02 — Dhan-side raw sizing (real numbers, comparable to Breeze's)

**[LIVE]** 2026-09-06 — first real Dhan-side sizing data, comparable
directly to the Breeze figures already in this file:

| | Rows | Raw bytes | Bytes/row | Breeze equivalent |
|---|---|---|---|---|
| NIFTY futures, 1 day, 1-min | 374 | 23,708 | **63.4** | ~166 (equity), ~166-ish (futures untested) |
| NIFTY option (live contract), 1 day, 1-min | 374 | 21,745 | **58.1** | ~287 |

**Dhan's raw JSON is roughly 2.6-4.9x more compact per row than Breeze's**,
purely from being column-oriented (`{"open": [...], "close": [...], ...}`,
field names appear once) versus Breeze's row-oriented shape (field names
repeated on every row). This matters for D-01/D-45 storage planning if
more historical pulling ever shifts toward Dhan directly, and is a fair,
apples-to-apples comparison now that both sides have been measured the
same way (full trading day, 1-minute, real contracts).

**Also reconfirmed**: Dhan's regular `/v2/charts/intraday` does **not**
serve already-expired option contracts (tested against a contract whose
expiry had passed a few days earlier: `status=200` but 0 rows) — consistent
with D-36's existing reasoning for why Breeze remains necessary for
historical option chains; Dhan's expired-options coverage is the separate,
ATM-relative-only `rollingoption` endpoint (see the D-52 findings above),
not this one.

---

## D-50 — exact request budget, real data (not an estimate)

**[LIVE]** 2026-09-06 — `experiments/nse_bhavcopy_year_scan.py` pulled 247
real trading days of NSE F&O bhavcopy (the modern UDiFF format — see the
URL note below) and counted the *actual* front-weekly NIFTY index-options
contract count for every single day, rather than assuming an average.

| Window | Trading days | Total Breeze requests | Days @ 5,000/day | Raw storage |
|---|---|---|---|---|
| 1 month | 22 | 4,726 | 1 | 0.48 GB |
| 3 months | 64 | 13,544 | 3 | 1.36 GB |
| 6 months | 124 | 28,870 | 6 | 2.90 GB |
| 9 months | 185 | 40,040 | 9 | 4.03 GB |
| 12 months | 247 | 51,500 | 11 | 5.18 GB |

**[LIVE] Same-day addendum — 2-trading-day request chunking, exact numbers.**
The working equity pipeline already chunks 2 trading days per Breeze
request (`data_fetch_script.md`'s proven pattern: ~750 candles/request,
under the 1,000 cap, never pairing Friday with the following Monday).
Applying the same chunking per contract to this real dataset:

| Window | Trading days | 1 req/day | 1 req/2 days | Reduction | Days @ 5,000/day |
|---|---|---|---|---|---|
| 2 weeks | 10 | 2,046 | 1,384 | 32% | 1 |
| 1 month | 22 | 4,726 | 3,176 | 33% | 1 |
| 3 months | 64 | 13,544 | 8,164 | 40% | 2 |
| 6 months | 123 | 28,670 | 17,898 | 38% | 4 |
| 9 months | 184 | 39,870 | 24,830 | 38% | 5 |
| 12 months | 247 | 51,500 | 32,630 | 37% | 7 |

Reduction is ~33-40%, not a flat 50% — Fridays still go solo, and **14 of
149 weekly chunk-pairs couldn't actually combine**: the contract count
changed mid-pair because NIFTY's weekly expiry weekday has shifted more
than once during this exact year (matches the shifting-expiry-day history
`08-market-abstraction.md` already flagged as something to verify against
circulars, now with a concrete count of how often it actually bit a naive
2-day chunking scheme). Those cases fall back to two single-day requests
automatically. Both the 1-day and 2-day budgets are now computed by
`nse_bhavcopy_year_scan.py` on every run.

**This meaningfully corrects the earlier S-02 estimate.** That estimate
used the ~462-contract count from the *live current* SecurityMaster
snapshot as a stand-in for "a typical week" — but the real historical
weekly count ranges from **160 to 328** depending on volatility (peaking
around March 2026, a higher-volatility stretch; sitting closer to 170-220
most other weeks). The live snapshot happened to be on the high side, not
representative. Real day-by-day data more than halves the earlier ~23-day
estimate down to **~11 days for a full year**. General lesson, consistent
with everything else in this file: an estimate built from one sample point
is not the same as a measurement, even when the sample is real data — this
is exactly why `nse_bhavcopy_year_scan.py` was worth writing instead of
trusting the earlier correction.

**⚠ URL note, not obvious from `jugaad-data`'s public API:** its
`bhavcopy_fo_raw()` hits NSE's pre-2024 legacy bhavcopy URL, which is dead
for any date after NSE's UDiFF migration (2024-07-08) — confirmed live,
fails with "File is not a zip file" for recent dates. Its
`bhavcopy_udiff_raw()` only covers the **equity (CM)** segment, not F&O —
confirmed by inspecting the actual rows returned (Sovereign Gold Bonds,
not NIFTY). The real, working F&O UDiFF URL
(`https://archives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip`)
was found by mirroring the CM UDiFF path's shape and confirmed by fetching
it directly (reusing `NSEArchives`'s already-authenticated session rather
than re-implementing NSE's bot-protection handling). Column names also
differ from the pre-migration format: `TckrSymb`/`XpryDt`/`StrkPric`/
`OptnTp`/`FinInstrmTp` instead of `SYMBOL`/`EXPIRY_DT`/`STRIKE_PR`/
`OPTION_TYP`/`INSTRUMENT`. `FinInstrmTp` codes confirmed:
`IDO` = index options, `IDF` = index futures (`STO`/`STF` presumably the
stock equivalents, seen in passing, not confirmed). This whole finding —
including D-52's bhavcopy mechanism — needs this corrected URL, not the
library's own default function, to work for any date after mid-2024.

---

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

**[LIVE/CODE]** NIFTY index spot, full history downloaded and built —
`flow/adapters/download_index.py` (2-day chunking via
`flow/adapters/chunking.py`, resumable by checking each raw file for a
non-empty `Success` list) pulled 2024-01-01 through 2026-09-04, 1-minute
bars. 419 chunks attempted, 408 succeeded, 11 came back with an empty
`Success`/`Error: None` — all 11 land on known NSE holidays or the
in-progress current session day, not real failures (cross-checked: canonical
build reports exactly 661 distinct trading days, matching the instrument
master's independently-scanned trading-day count for the same range
exactly). Built to canonical (`flow/canonical/build.py`) and persisted
partitioned by `(instrument_type, year, month)` per D-03
(`flow/canonical/write.py`, new — idempotent merge-and-dedupe on
`(timestamp, instrument_id)` per partition, so re-running an overlapping
pull never duplicates rows): 252,366 rows, `instrument_id = NSE|NIFTY|INDEX`,
validation clean except one expected WARNING (99.9% zero-volume bars — index
spot's `volume` field from Breeze isn't a real traded-volume series, matches
the small-scale smoke test's same finding, not a data-quality bug).

**[LIVE/CODE]** NIFTY front-month futures, full history downloaded and
built — `flow/adapters/download_futures.py` (new), front-month resolved per
trading day via `rules/store.py`'s new `front_contract()` (nearest expiry
>= t among instrument-master contracts actually trading on t — a pure
function of observed data, no rollover-weekday rule). 2024-01-01 through
2026-09-04: 419 chunks, 407 succeeded, 12 empty responses all landing on
known holidays (same cross-check as the index: exact 661-trading-day count
match). Rollover boundaries verified correct on a smoke test spanning the
2024-01-25 expiry (days 22-25 pulled the expiring contract, day 26 onward
pulled the next one).

Found a second real Breeze data-quality bug while validating (distinct from
the earlier negative-volume one): a single response can contain **two
conflicting rows for the same (timestamp, instrument_id)** — confirmed on
NIFTY's 2025-06-26 future, 2025-06-20 14:33: one row `volume=5250`, the
other `volume=-1543350` (nonsense), with slightly different OHLC too.
`canonical/build.py` now dedupes: within a duplicate group, keep the row
with a plausible (non-negative) volume if exactly one side qualifies,
otherwise keep the last-seen row. Also caught (and fixed by deleting the
stray raw file, not a code change): a leftover raw file from an earlier
rollover smoke test whose date-chunk boundary didn't match the full run's
own chunking, causing genuine double-counted rows for one day — a reminder
that raw file *names* under a given contract directory must stay mutually
exclusive by date range, not just individually correct.

After the fix: 248,280 canonical rows, 33 instrument_ids, cross-checked
clean against the instrument master, validation clean (one expected
WARNING: 53 rows with unknown volume, nulled per the existing negative-
volume policy).

Next: front-weekly options download, per D-50's already-computed budget
(~89.2K requests at 2-day chunking, 18 days at the 5,000/day cap).

---

*Next: still open — 1-second confirmed on equity cash but not yet directly on
index/futures; deep-history coverage confirmed only on reasonably liquid
guessed strikes, not deep-OTM/illiquid ones; exact discontinuation date for
BANKNIFTY/FINNIFTY weeklies still wants a circular reference; D-50's schedule
estimate wants recomputing against the real ~460-contract ladder width once
expiry scope is decided; S-06's futures cross-provider comparison (Breeze vs
Dhan on an overlapping day) hasn't been run yet — can be done via the Dhan
MCP tools available in this session once a concrete day is picked.*

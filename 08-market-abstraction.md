# 08 — Market Abstraction

*A conceptual model, not a hard requirement. The goal is that adding US options
later is a configuration and adapter exercise, not a rewrite.*

---

## The claim

The concepts are generic. The rules are not.

**Generic** — underlying, instrument, contract, expiry, strike, right, OHLCV,
OI, IV, greeks, GEX, VWAP, volume profile, market structure, signal, strategy,
backtest, execution.

**Per-market** — what an expiry *is*, when it settles, what a contract is worth,
what a tick costs, when the market is open, what it costs to trade, what
"underlying price" means, and how all of those changed over time.

The core should know only the first list. The second list enters as data.

## The one rule that makes this work

> **A market rule is data, not code — and it is time-versioned.**

Not `if market == "NSE": expiry = last_thursday(month)`. Not an expiry-rule DSL
either. Just a table of expiry dates, contract specs and session times, valid
over date ranges, loaded at the time being computed.

Rule-as-code fails twice: it hardcodes NSE, and it silently applies *today's*
rules to *last year's* data. The second failure is worse because it's invisible.

---

## What varies, concretely

Worth reading as a checklist of assumptions to keep out of the core.

| Dimension | NIFTY / BANKNIFTY | SPX | ES (futures options) |
|---|---|---|---|
| Timezone | Asia/Kolkata | America/New_York | America/Chicago |
| Session | single continuous | RTH + extended | nearly 24h, Sun–Fri |
| Expiry cadence | weekly + monthly | M/W/F weeklies + monthly + quarterly | weekly, EOM, quarterly |
| Expiry day | varies by index, **has changed** | third Friday monthly; weeklies vary | varies by series |
| Settlement time | close | **monthly AM-settled**, weeklies PM | varies |
| Exercise | European | European | **American** |
| Settlement | cash | cash | cash on options, physical on futures |
| Contract size | lot size, **changes over time** | multiplier 100, stable | multiplier 50 |
| Tick | price tick, currency = points | 0.05 / 0.10 by premium | 0.25 pts = $12.50 |
| Underlying ref | index spot vs synthetic future | index spot | the future itself |
| Volume units | verify: units vs lots | contracts | contracts |
| Currency | INR | USD | USD |
| Cost stack | STT, GST, stamp duty, exchange, SEBI | SEC fee, ORF, OCC, exchange | exchange, NFA, clearing |
| Margin | SPAN India | Reg-T / portfolio margin | SPAN |

Three of these have architectural consequences big enough to name.

**AM vs PM settlement.** US monthly SPX options settle on the *opening* prints
of expiration Friday. Gamma from those contracts disappears at the open, not the
close. Any GEX code that assumes "expiry happens at session end" produces wrong
gamma-flip timing on the most important day of the month. India has no analogue,
so this assumption will be invisible until it isn't.

**European vs American exercise.** ES options are American. Pricing and early-
exercise handling differ. If the greek engine takes exercise style as a
parameter from day one, this is free later; if it hardcodes European, the whole
engine gets revisited.

**Contract size as a time-varying quantity.** GEX scales linearly with it —
roughly `gamma × OI × multiplier × spot² × 0.01`. In the US the multiplier is a
constant. In India it is the lot size, and **lot sizes have been revised**
(notably around the late-2024 SEBI increase in minimum contract value). A GEX
series computed with today's lot size applied to three-year-old OI is wrong by
that ratio, silently, in a way that looks like a regime change.

That last one is the strongest argument for time-versioning, and it bites you in
the NSE-only case — this abstraction earns its keep before US options ever
arrive.

---

## Market-structure changes to version

Examples worth verifying and encoding as dated rules rather than constants. Each
one, applied anachronistically, contaminates a backtest:

- Lot size / contract value revisions (NSE, multiple occasions)
- Weekly expiry restricted to one benchmark index per exchange — BANKNIFTY, FINNIFTY, MIDCPNIFTY weeklies discontinued (believed late 2024; **verify dates**)
- Weekly expiry *day* changes for index options
- Session timing changes, muhurat sessions, special trading days
- Tick size revisions
- US: introduction of Monday and Wednesday SPX weeklies; daily expiries from 2022 onward

The point is not to enumerate them all now. It's that the schema must be able to
hold them, so that when you discover one you record it rather than patching
around it.

> **Verify before encoding.** The specific dates and values above are from
> memory and are exactly the kind of thing worth checking against exchange
> circulars before a five-year backtest depends on them.

---

## The shape

```
Market
├── timezone, currency
├── calendar          ── time-versioned: sessions, holidays, special days
├── expiry calendar   ── time-versioned: dates per underlying + series
├── settlement rules  ── AM/PM, cash/physical, exercise style
├── cost model        ── fee components, per instrument type and side
├── margin model
└── quotation conventions  ── volume units, OI units, price units

Underlying  (NIFTY, SPX, ES)
└── contract specs    ── time-versioned: multiplier, lot, tick size, tick value

Instrument  (generic — the thing market data attaches to)
└── underlying_id, type, expiry, strike, right
```

Analytics receive `(instrument, market_rules_as_of(t))`. They never import a
market.

### Where market knowledge is allowed to live

| Layer | May know about markets? |
|---|---|
| Provider adapters | Yes — that's their job |
| Reference / market profile | Yes — it *is* the market knowledge |
| Canonical data | No |
| Feature engine | Only via injected rules |
| Strategy | Only via injected rules and its own parameters |
| Execution / cost model | Via injected cost model |

Every place the core needs a market fact, it asks the rules object. If a feature
needs something the rules object doesn't expose, that's a signal the abstraction
is missing a field — not a licence to hardcode.

---

## GEX specifically

The user's framing is right and worth stating precisely: **the calculation is
common; the scope, parameters and interpretation are not.**

Common: per-option gamma exposure, aggregation to strike, to chain, to market;
gamma flip; level identification.

Per-market:

- **Expiry scope** — which expiries enter the aggregate. India concentrates in the near weekly; SPX has a large 0DTE component plus monthly AM-settled. "All listed expiries" and "nearest expiry only" give different answers, and the right choice differs by market.
- **Contract multiplier** — time-versioned, as above.
- **Dealer positioning convention** — the sign convention that turns gamma × OI into signed exposure. The US convention assumes a dealer-intermediated flow structure. NSE's retail-heavy option selling may invert it (D-20, S-05). **This is per-market and empirical, not a constant.**
- **Underlying reference** — spot vs future (D-21).
- **Interpretation** — what a gamma flip *means* for price behaviour is a market-specific empirical claim, not a property of the formula.

So GEX becomes: one engine, a `gex_config` per market, and a feature version
that records which config produced the series. Two markets can then be compared
honestly, because you know exactly what differed.

---

## Cost of doing this — and the honest limit

Full generality now would be a mistake. Building an SPX adapter you can't test
against real data produces abstractions shaped by guesses.

The useful split:

**Do now** (cheap, expensive to retrofit)
- Instrument identity that isn't NSE-shaped (D-05)
- Time-versioned contract specs and market rules (D-06, D-51)
- Expiry as a dated calendar, not a computed rule (D-52)
- Timezone/currency as fields, not constants (D-07)
- Cost model as a pluggable component (D-31)
- Exercise style and settlement time as greek-engine parameters (D-19)
- GEX config object rather than inline constants (D-53)

**Do later** (needs real data to design well)
- The actual US market profile
- US provider adapters
- Margin models beyond what you trade
- Cross-market portfolio logic

**Don't do** (over-abstraction)
- An expiry-rule DSL — dated calendars are simpler and more correct
- A generic "any asset class" model — derivatives on an underlying is enough
- Multi-currency portfolio accounting before you hold two currencies
- Pluggable everything — abstraction without a second implementation is guesswork

### The cheapest possible validation

Write the SPX and ES market profiles **as config files only**. No adapter, no
data, no code. Perhaps an hour's work.

Then check: does anything in the core need to change to load them? Does the
greek engine have somewhere to put "American"? Does the GEX config have an
expiry-scope field? Does the calendar hold AM settlement?

Every gap this finds costs minutes now. The same gap found after the historical
pull costs a migration. Do this once during Phase 1 and again after Phase 2 —
it's the only reliable test of whether the abstraction is real or aspirational.

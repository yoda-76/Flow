# FLOW

A research platform for turning discretionary NSE trading judgment — market
structure, VWAP, volume profile, footprint, options Greeks, GEX — into
measurable, versioned, backtestable rules, and eventually a live-tradable
system.

Not a backtester and not a charting tool. The point is turning a sentence
like *"price reacted at an important level, structure turned bullish"* into
something a computer can evaluate the same way every time — and keeping
every step between raw market data and a trade decision inspectable and
reproducible.

## Where things stand

Early stage: this is architecture and data-layer work, not a working
trading system yet. A lot of what's here so far is *verification* rather
than building — actually testing what Breeze's and Dhan's APIs (and
third-party libraries like NautilusTrader) really do, rather than trusting
their docs. That's found several real, undocumented bugs and quirks along
the way; see `docs/dynamic/findings.md` for the running record.

## Repo layout

- **`docs/static/`** — the original design doc set, `00` through `08`.
  Start at `00-START-HERE.md` — it explains the reading order and the one
  fixed architectural constraint everything else is built around:
  `RAW → CANONICAL → FEATURES → MARKET STATE → STRATEGY → EXECUTION`.
  This is the fixed reference point; it doesn't change as decisions get
  made, and it's a bit stale by now in the sense that a lot of what it
  poses as open questions has since been answered — see the next bullet.
- **`docs/dynamic/`** — the actual working record, and the more
  up-to-date place to look:
  - `decisions.md` — closed architectural decisions, one per question the
    static docs left open.
  - `findings.md` — the empirical evidence behind them: what was actually
    tested against a live API or an independent reference, tagged by how
    strong the evidence is.
  - `nautilus_checklist.md` — ongoing sanity-testing of a third-party
    trading engine (NautilusTrader) being evaluated for adoption.
- **`experiments/`** — small, throwaway scripts that answer one empirical
  question each (does this field actually populate, does this library
  actually compute what it claims). Not production code — the answers they
  produce end up in `findings.md`.
- **`flow/`** — the actual system, built incrementally as the
  architecture solidifies. Starts empty and fills in module by module.
- **`SecurityMaster/`** — raw NSE/Breeze instrument listing reference
  dumps.
- **`CLAUDE.md`** — working rules for how this repo gets built with an AI
  assistant in the loop. Mostly relevant if you're doing the same.

## The core habit worth noticing

Nothing gets trusted just because it's documented — not the exchange's own
broker APIs, not well-established open-source libraries. Everything gets
checked against a real API response or an independent reference
implementation first. `docs/dynamic/findings.md` is the running log of
what that turned up.

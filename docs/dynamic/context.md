# Context — current ongoing tasks

Informal, living scratch list of what's in progress right now. Not a
structured tracker (no fixed format promised) — the user will decide later
how this should actually be maintained. Update in place as things move;
don't worry about preserving history here (that's what findings.md/
decisions.md are for).

## In progress

- **Breeze historical download (index/futures/options)** — index and
  front-month futures are fully downloaded and validated (Jan 2024–Sep
  2026). Front-weekly options download is ongoing across daily
  request-budget-capped runs (`flow/adapters/download_options.py`) — needs
  a fresh Breeze session token (D-49) and a re-run each day until "0 to
  fetch". Last known progress: ~14% of chunks done as of 2026-09-10
  (11,821 raw files), running continuously in the background. The
  documented "5,000/day" cap isn't a hard wall in practice — a prior
  session made ~6,400+ requests in one day with no rate-limit signal — so
  this may finish faster than the original 18-day estimate assumed.

- **Greeks + GEX batch pipeline, run against real downloaded data** — see
  findings.md for full details. `flow/features/greeks_batch.py` (vectorized,
  cross-validated against the scalar `greeks.py` reference every run) run
  against all 5.1M downloaded canonical options rows: 58.5% IV-solve rate
  (a real empirical answer to D-19/S-04's open "what fraction fails"
  question). `flow/features/gex.py` extended with a vectorized
  `compute_gex_timeseries()` and run for real. Along the way, fixed a real
  bug in `build_instrument_master.py`'s lot-size backfill (11 dormant
  contracts had a later, already-changed lot size incorrectly stamped
  backward across a real transition) and confirmed + applied the correct
  legacy-era (Jan–Jul 2024) NIFTY lot size of **25** (not the guessed 50)
  via a new market-wide baseline mechanism. GEX is now computable across
  the entire downloaded range (64 distinct trading days so far, growing
  automatically as the options download continues) instead of just one
  smoke-test day.

- **Dhan live feed + volume profile** — built as a real `flow/` module
  (`flow/adapters/dhan.py`, `flow/features/volume_profile.py`,
  `flow/live/dhan_volume_profile_recorder.py`), offline-verified (self-tests
  + synthetic fixture dry-run all pass). **Not yet live-tested** — needs a
  fresh Dhan access token (24h validity) and a real trading day to run
  during market hours (~09:15–15:30 IST). Two things stay UNVERIFIED until
  that live run: whether Dhan's `volume` field is really cumulative-day,
  and real reconnect/tick-frequency behavior. Log results to findings.md
  as a `[LIVE]` entry once run.

- **Greeks feature engine** — built (`flow/features/greeks.py`, D-19/R7).
  European closed-form only (American raises `NotImplementedError`,
  per D-54). Cost-of-carry `b` is a required argument, not an assumed
  spot/future choice, since D-19 is still open (blocked on S-04). Verified
  via dependency-free self-tests (put-call parity, IV round-trip, no-
  arbitrage rejection) and an independent cross-check against `py_vollib`
  (exact to 1e-12). See findings.md for the full writeup.

- **Two NautilusTrader backtests, both fixed after a real short-selling
  bug** — `flow/backtest/`, restructured per-strategy:
  ```
  flow/backtest/
  ├── common/                          shared across all strategies
  │   ├── data_loading.py              canonical Parquet -> Nautilus Bar/Instrument, incl.
  │   │                                  continuous front-month futures splicing
  │   ├── engine_setup.py              venue setup (MARGIN, leverage=1 -- see bug below)
  │   ├── nautilus_reports.py          Money-string parsing + result extraction
  │   └── target_position_strategy.py  the one shared Nautilus Strategy adapter (both
  │                                      strategies below just supply a target-position dict)
  ├── gex_regime_follower/             signal.py + run_backtest.py only -- no strategy.py,
  │                                      uses the shared adapter directly
  └── ma_crossover_futures/            same shape, second strategy
  ```
  Run via `.venv/Scripts/python.exe -m backtest.<name>.run_backtest` (module,
  from `flow/`, relative imports require it).

  **Real bug found and fixed**: both strategies' first runs used
  `AccountType.CASH`, which silently rejects every short-sell order. The
  strategy kept re-submitting the rejected order every subsequent bar,
  which is why MA crossover showed 124,005 "flips" against a signal that
  only changes ~170 times per 1.5 months of data — the short side never
  traded at all in either strategy's first run. Fixed via
  `common/engine_setup.py` (`AccountType.MARGIN`, leverage=1) so future
  strategies inherit the fix automatically. Full writeup in findings.md.

  **Fee model added** (`common/engine_setup.py`, `FixedFeeModel`,
  ₹20/order placeholder — Nautilus has real fee-model machinery, it just
  defaults to `fee_model=None`, i.e. free, unless you pass one). Purpose,
  per the user: not to make either strategy profitable, but to prove the
  pipeline shows real, cost-adjusted numbers so a genuinely profitable
  strategy's edge would show up net of realistic costs, not as a flattering
  cost-free fiction.

  **Final results** (10M INR capital, ₹20/order commission applied):
  | | GEX standard | GEX inverted | MA crossover |
  |---|---|---|---|
  | Window | Jan–Apr 2024 | Jan–Apr 2024 | Jan 2024–Sep 2026 |
  | Fills | 6,774 | 6,774 | 6,868 |
  | PnL before costs | +1,483.55 | -1,483.55 | +4,104.10 |
  | PnL after costs | -133,996.45 | -136,963.55 | -133,255.90 |
  | Win rate after costs | 1.4% | 2.3% | 16.0% |

  All three were noise-level before costs, decisively negative after —
  expected and correct for a ~3,400-trade, untuned v1 signal at this cost
  level, not a strategy problem to chase right now.

## Up next

- **Optimization deferred per user instruction** — no hysteresis, no
  MA/window tuning yet for either strategy. Revisit once asked.
- **GEX dealer-positioning convention (D-20)**: still open, both
  conventions get run and compared every time per the established
  pattern above — no premature pick.
- Pipeline is now considered validated end-to-end (data → signal →
  Nautilus execution → realistic PnL) — ready for an actual strategy
  hypothesis whenever one shows up.

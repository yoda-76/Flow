# CLAUDE.md

Workflow rules and fundamental conventions for how we work on this project
together. This file is curated by explicit instruction only — when something
recurring shows up, it gets flagged for a decision, not added unilaterally.

## Directory structure and what each part is for

```
FLOW/
├── CLAUDE.md          this file
├── docs/
│   ├── static/        00-08 + the raw Breeze API doc dumps. Reference material.
│   └── dynamic/       decisions.md, findings.md, nautilus_checklist.md. Our working record.
├── experiments/        small throwaway scripts to resolve ambiguity empirically
└── flow/               the actual project code — stays empty for now
```

- **`docs/static/`** — the original doc set (`00`–`08`) plus reference
  material like the Breeze API doc dumps. **Never edit files in here.** They
  are the fixed reference point everything else argues against. If something
  in here turns out to be wrong, that's a `findings.md`/`decisions.md` entry,
  not an edit to the static file.
- **`docs/dynamic/`** — `decisions.md`, `findings.md`, and
  `nautilus_checklist.md`. These evolve continuously as we work; see their
  own headers for the distinction (decisions are closed answers, findings
  are the evidence behind them, the checklist is a living, in-place-updated
  list of what's been sanity-tested about NautilusTrader versus still
  assumed — not append-only like findings.md).
- **`experiments/`** — small, disposable scripts/notebooks to empirically
  resolve anything ambiguous or undocumented that couldn't be settled by
  reading docs alone (example: the 1-second historical interval conflict in
  `findings.md`). Output of a real experiment run here becomes a `[LIVE]`
  entry in `findings.md`; the script itself is scratch, not a deliverable.
- **`flow/`** — where the actual system gets built. **Stays empty until told
  otherwise.** We are still in the architecture/decision phase; building
  starts only on explicit instruction, not by inference from the rest of the
  work being far enough along.

## Secrets — `.env` files

`experiments/` and `flow/` each have `.env` and `.examples.env`.

- **Never read `.env` in either directory.** Not to check a value, not even
  if asked indirectly. This is a hard rule.
- **Only the user ever edits or writes `.env`.** Always — not just by
  default. If a credential, key, or config value needs to be added or
  changed, edit `.examples.env` to show what's needed (name, and a
  placeholder or description of the value) and tell the user; never write to
  `.env` myself, including indirectly (e.g. a script generating or modifying
  it).

## Architecture stays provisional by design

Decisions in `docs/dynamic/decisions.md` are the current best answer, not
final — expect more experiments to reshape them (D-28's engine spike,
D-52's expiry sourcing, and S-03/S-04/S-05 will each likely reopen
something). When writing code in `flow/`: keep modules small, behind clear
interfaces (adapter, cost model, market rules, feature version), so a
bottleneck can be swapped or reworked in one place instead of triggering a
rewrite. Don't over-abstract ahead of a second real case (per `08`), but
never let a module's internals leak past its interface either — that's what
makes the swap possible later.

No other standing rules recorded yet.

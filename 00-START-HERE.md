# Automated Market Research & Trading System — Document Set

## What this is

A first-draft mind dump, reorganised so you can walk through it and **record
decisions** before writing any architecture code.

*Revised after reading the Dhan v2 and Breeze API documentation. Several
assumptions in the original research turned out to be wrong — see
`04-tooling-landscape.md` for the corrections, and D-36/D-46 for what changed as
a result.*

Nothing in these documents is a committed design. Everything that looked like a
settled architectural choice in the original drafts (Parquet, long-form tables,
integer instrument IDs, directory layouts, feature schemas) has been pulled out
and moved into the **Decision Register** as an open question with options.

## Reading order

| # | File | What it's for | Read when |
|---|---|---|---|
| 01 | `01-concept.md` | The mental model. Why the system is shaped this way. | Once, first. Nothing to decide. |
| 02 | `02-requirements.md` | What the system must be able to do, stated without prescribing how. | Second. Mark scope in/out. |
| 08 | `08-market-abstraction.md` | Generic concepts vs per-market rules, so US options later isn't a rewrite. | With 02 — it shapes the data model. |
| 06 | `06-spikes.md` | Unknowns that must be resolved *before* most decisions are answerable. | Third — several of these gate everything else. |
| 04 | `04-tooling-landscape.md` | What already exists, what must be built, what was considered and parked. | Fourth. Feeds several decisions. |
| 03 | `03-design-options.md` | Candidate designs — sketches, not commitments. Each links to a decision ID. | Alongside 05. |
| 05 | `05-decision-register.md` | **The working document.** Every open choice, with options and a slot for your answer. | Continuously. This is where you write. |
| 07 | `07-build-order.md` | Phases, and which decisions must be closed before each phase starts. | Last, then revisit. |

## How to use it

1. Read 01 and 02. Cut requirements you don't actually want. The originals are
   maximalist; some capabilities may not survive contact with the data.
2. Run the spikes in 06. Roughly half the decision register is unanswerable
   until you know what Breeze and Dhan actually give you.
3. Work through 05 top to bottom. For each decision write **Decision**,
   **Date**, **Rationale**. A decision of "defer, revisit at Phase N" is a
   valid answer and should be recorded as one.
4. Only then write architecture.

## Status conventions used throughout

| Tag | Meaning |
|---|---|
| **OPEN** | No decision made. Options listed. |
| **BLOCKED** | Cannot be decided until a named spike resolves. |
| **DEFERRED** | Deliberately postponed to a later phase; recorded as such. |
| **DECIDED** | Answered, with date and rationale. |
| **TRIAL** | Adopted provisionally, with an explicit condition for revisiting. |
| **PARKED** | Considered, not pursued now, with a trigger to reconsider. |
| **DROPPED** | Considered and rejected, with the reason recorded. |

The point of PARKED and TRIAL is that this is research. Things get tried and
abandoned. A parked item with a recorded reason is worth more than a silently
forgotten one.

## The one thing that is not negotiable

The layering:

```
RAW  →  CANONICAL  →  FEATURES  →  MARKET STATE  →  STRATEGY  →  EXECUTION
```

Everything else — formats, schemas, libraries, storage, engines — is open.
That layering is the only thing carried forward from the drafts as a
constraint, because it is what lets every other decision be changed later
without a rewrite.

One companion constraint, added later and for the same reason: **market rules
are time-versioned data, not code** (`08`). Together these two are what keep the
architecture from being rewritten — once for the next storage decision, once for
the next market.

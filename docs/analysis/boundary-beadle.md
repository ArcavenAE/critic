# Boundary: critic vs beadle

Recorded session-051 (2026-06-28), after a beadle triage session repeatedly
drifted into measurement/comparison work that is properly critic's.

## The rule

| | **critic** | **beadle** |
|---|---|---|
| Verb | measure, compare, compete, **detect** | record, report, prioritize, **surface** |
| Unit of work | a run (or a cohort of runs) | a GitHub issue / a target repo's backlog |
| Output | quantitative comparison, regression/breakdown signal, metric-of-interest | triage dashboard, filed/deduped issues, intent-alignment verdict |
| Acts on GitHub? | **no** — emits findings inward | yes — proposes (propose-not-act, B2) |
| Cross-run statistics? | **yes** — its core | no |
| Per-artifact intent scoring? | no | **yes** — its differentiator (B4) |
| Time axis | between runs / between generations | within a backlog, over triage passes |

## Why the confusion arose

beadle's intent-grounded triage *surfaces* defects a volume-counter misses
(e.g. finding-007: a missing OTEL dimension). That surfacing is on-mission for
beadle. But the moment the question becomes "is run X slower than run Y," "is
$/commit drifting across generations," "is this factory configuration better
than that one" — that is **comparison across runs**, which is critic's arena.

The tell: if answering needs **more than one run** or a **trend across time**,
it's critic. If it's "is this one issue real, aligned, and prioritized," it's
beadle.

## How they compose

1. critic detects a breakdown/regression in a run's metrics.
2. If the breakdown is defect-shaped and lives in a governed target, critic's
   finding flows to beadle.
3. beadle applies the propose-not-act bar, dedupes against existing issues,
   classifies (IEEE 1044 / ODC / reproducibility), and reports — or, as in the
   resolver-storm case this session, **verifies an issue already exists and
   stays silent.**

## Defect class: beadle classifies, critic weights

A specific division that matters for the efficiency measurands. critic's headline
metric is defects per unit spend (per-token / per-dollar / per-hour) — but a raw
count is a Goodhart trap, because a lint nit and a data-loss/directional defect
are not the same unit.

- **beadle owns the class.** The defect-nature spectrum, severity (silent
  source-of-truth integrity at top), and recoverability tiers are beadle
  finding-004/005. beadle assigns a defect its class.
- **critic owns the rate.** critic consumes beadle's class, applies a class
  weight `w(class)`, and computes class-weighted efficiency across runs — always
  publishing the class histogram beside the scalar.

Neither re-does the other's half: critic never re-classifies a defect; beadle
never computes cross-run efficiency. The weight function itself is an
arena-methodology design decision (routed to aae-orc kos), but the *shape* —
class-weighted, never an unweighted count — is fixed.

## Shared substrate, opposite ends

- **OTEL per-run attribution (#324 / finding-007):** beadle *surfaced* it;
  critic *depends* on it. The same gap, read from both ends.
- **The `legion` Dolt store:** critic's index of record; beadle never touches it.
- **kos:** both graduate distilled findings into kos, linked back to their
  source (a registry row for critic; a target/issue for beadle).

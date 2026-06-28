# critic — analysis layer

> The arena's measurement engine. Where the registry (`legion` Dolt index) says
> *which runs exist*, the analysis layer says *how they compare and where they
> break down*. Pre-implementation; this doc is the scaffold that pins scope and
> vocabulary before code.

## What this layer owns (the boundary with beadle)

A boundary clarified in session-051 (see `docs/analysis/boundary-beadle.md`):

- **critic measures, compares, and detects.** Cross-run velocity, cost/commit
  drift, regression between generations, breakdown/death-spiral detection,
  metric-of-interest identification, factory-of-factories comparison. The
  quantitative arena.
- **beadle records, reports, prioritizes.** It maintains the triage dashboard,
  files and de-duplicates GitHub issues, puts findings in perspective, applies
  intent-alignment scoring. The qualitative triage surface.

They compose: critic *detects* "run X's $/commit regressed 1.8× vs its cohort";
beadle *reports* that as a prioritized finding if it's defect-shaped and clears
the propose-not-act bar. critic never posts to GitHub on its own behalf; beadle
never computes cross-run statistics.

## The measurands

Each run is one row in the `legion` Dolt table; its `metrics` column is "the
arena's input" (run-registry B-layer). The analysis layer reads `metrics` plus
the run's own on-disk telemetry and produces comparisons. Candidate measurands,
each tied to a concrete signal we have *already observed* in the live pilots:

| Measurand | Source signal | Status today |
|---|---|---|
| **velocity** | commits/active-hour; $/commit | computable machine-wide; **not per-run** (see blocker) |
| **cost** | `claude_code_cost_usage_USD_total` | machine-wide aggregate only |
| **token efficiency** | `claude_code_token_usage_tokens_total`, cacheRead:input ratio | machine-wide aggregate only |
| **breakdown / spiral** | shrinking inter-compaction interval, rising context-fill, falling velocity | **unobservable** — no compaction telemetry, no context gauge |
| **dispatcher health** | `internal.dispatcher_error` / `resolver.load_error` rate per run | **observable on disk** — strong signal (see below) |
| **convergence cost** | passes-to-clean, fix-burst count (factory `STATE.md` / cycle logs) | observable on disk, per-run |

## The load-bearing blocker — OTEL has no per-run dimension

**critic's whole comparison premise depends on attributing metrics to a run.**
Today it cannot: every `claude_code_*` metric carries only an opaque
`session_id`, with no `project` / `cwd` / `repo` / `instance` label. Two
concurrent runs of the same factory collapse into one series.

This is filed as beadle finding-007 and upstream as **drbothen/vsdd-factory#324**.
It was surfaced as a beadle triage byproduct, but it is *critic's_ substrate
requirement: until a run dimension lands on the metrics (or is reconstructed by
an offline `session_id` ⋈ dispatcher-log join), per-run velocity/cost/spiral
comparison is impossible by construction. critic should track #324 as a
precondition for the metrics-from-OTEL path, and meanwhile prefer **on-disk,
inherently per-run signals** (dispatcher logs, factory `STATE.md`, cycle dirs)
that need no label.

## First detectable breakdown — the resolver-load storm

The first concrete "breakdown" signal critic can compute today, no OTEL label
needed, fully per-run (the log lives in the run's own `.factory/logs/`):

- `internal.dispatcher_error` rate in `dispatcher-internal-*.jsonl`.
- Observed 2026-06-28 across three rc.21 pilots: ftc-blue 2887, switchboard-blue
  2162, akey 4189 identical `cannot canonicalize hook-plugins/...wasm` errors in
  one partial day; `resolver.registry_loaded` fired **0** times.
- Root cause is a *deployment* breakdown, not a code bug: the fix (vsdd-factory
  `dfc76844`, S-18.14) is on `develop` but in **no release** (rc.21 predates it);
  `git tag --contains dfc76844` is empty. Already tracked upstream as
  drbothen/vsdd-factory#242 (beadle verified; no new issue filed).

This is the template for a critic detector: a per-run, on-disk, count-with-rate
signal that distinguishes a healthy run from a degraded one **without** the
missing OTEL dimension. See `skills/critic-compare/SKILL.md`.

## Efficiency measurands — and why they MUST be class-weighted

The headline arena question is efficiency: **how much defect-detection (or
defect-*prevention*) does a run/factory buy per unit of spend?** Three spend
axes:

- **per-token** — defects per 1k tokens (input+output, or cache-adjusted)
- **per-dollar** — defects per `claude_code_cost_usage_USD_total` delta
- **per-time** — defects per active-hour / per wall-clock

But a **raw** defect count over any of these is a Goodhart trap. A factory that
emits a thousand lint nits would dominate "defects-per-token" while a factory
that prevents one silent data-loss defect would score near zero. **Defect class
dominates defect count.** A lint/hygiene finding and a logic / data-loss /
directional / source-of-truth-integrity defect are not the same unit and must
not be summed into one scalar.

### The weighting comes from beadle, not invented here

beadle already owns the defect-classification taxonomy (beadle finding-005 +
finding-004): the **defect-nature** spectrum (mechanical → conceptual: syntax/
typo → off-by-one → null/resource → concurrency → logic → algorithmic → spec →
design → **directional/intent-misalignment**), **severity** (with **silent
source-of-truth integrity** as the top class — invisibility + compounding), and
**recoverability** (regenerable output < spec/process < irreplaceable learning).
critic does not re-derive this; it **consumes** beadle's class on a defect and
applies a class weight.

### Class-weighted efficiency (the honest metric)

```
detection_value(run) = Σ over defects found  w(class_i)
efficiency_per_token = detection_value / tokens
efficiency_per_$     = detection_value / cost_usd
efficiency_per_hour  = detection_value / active_hours
```

where `w(class)` is monotonic in severity × recoverability, e.g. lint/hygiene ≪
logic ≪ data-loss/directional ≪ silent-integrity. The weights are a **design
decision routed to the arena-methodology node**, not hard-coded here — but the
*shape* is fixed: **never an unweighted count.** Report the class histogram
alongside the scalar so the weighting is auditable and a high score can't hide a
pile of trivia. (Same discipline as beadle's "pair every count with an outcome.")

### Prevention counts too, not just detection

For a factory being evaluated (not a triage tool), the valuable signal is often
defects **prevented / not introduced** per unit spend — measurable as defect
class-rate *declining* across generations of the same `source_repo`. A run that
spends more tokens but ships fewer high-class defects is winning, and a raw
detection-rate metric would misread that as "found fewer defects = worse." The
class-weighted, generation-over-generation view is what distinguishes the two.

## Non-goals (this layer)

- No GitHub mutation. critic emits findings; beadle (or a human) acts.
- No registry CRUD here — that's the registry layer.
- No Goodhart: a comparison metric is a *surfacing* device. Never rank runs by
  a single scalar that an autonomous factory could learn to game (e.g. raw
  commit count). Pair every measurand with an outcome/quality signal, the same
  discipline beadle applies to maintainer progress.

## Open questions (route to aae-orc kos)

1. Does `metrics` (Dolt JSON) hold pre-computed measurands, or does critic
   recompute from raw telemetry on each arena pass? (caching vs freshness)
2. The arena methodology node (`question-agent-arena-evaluation`) is referenced
   but not yet written — judges, holdout scenarios, statistical comparison,
   factory-of-factories. This doc is the analysis-engine half; that node is the
   evaluation-methodology half.
3. Is OTEL-attribution (#324) the right substrate, or is the offline
   `session_id` join (dispatcher log ⋈ OTEL) sufficient for critic's first pass?

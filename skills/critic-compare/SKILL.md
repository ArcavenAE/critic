---
name: critic-compare
description: Compare agent/factory runs and detect breakdowns from per-run, on-disk telemetry. Use to measure dispatcher health, convergence cost, and velocity across one or more vsdd-factory runs, identify regressions between runs/generations, and emit findings (critic does NOT post to GitHub — it hands defect-shaped findings to beadle). The Phase-0 analysis entry point for critic; reads run telemetry that needs no OTEL label, so it works despite the per-run attribution gap (#324).
---

# critic — compare & detect (Phase 0)

The minimal, useful form of critic's analysis layer: read **per-run, on-disk**
telemetry (which is inherently attributable — no missing OTEL dimension needed),
compute health/velocity/convergence measurands, and surface regressions between
runs. Read `../../docs/analysis/README.md` and `../../docs/analysis/boundary-beadle.md`
first — the beadle boundary binds this skill.

## Invariants

1. **No GitHub mutation.** critic emits findings inward. A defect-shaped finding
   is *handed to beadle*, which applies propose-not-act. critic never opens,
   comments on, or closes an issue on its own behalf.
2. **Per-run signals only, until #324 lands.** Prefer telemetry that is
   inherently per-run — the run's own `.factory/logs/`, `.factory/STATE.md`,
   cycle dirs. Do NOT attribute machine-wide OTEL aggregates to a single run;
   that is the exact error #324 makes impossible to avoid at the metric layer.
3. **No Goodhart.** Every measurand pairs a count with an outcome/quality
   signal. Never rank runs by a lone scalar a factory could learn to game.
4. **Verify before asserting.** A comparison claim is only as good as its
   evidence; an inaccurate regression report is a penalty, not neutral (same
   bar beadle applies to public posts). State what was measured and over what
   window; flag aggregates that aren't truly per-run.

## Inputs

- **Runs** — one or more run working dirs (a `.run.yaml` marker + a `.factory/`
  tree). Phase 0 takes filesystem paths; Phase 1 reads the `legion` Dolt index.
- **Window** — a date or date range (the dispatcher logs are per-day JSONL).

## Procedure

### 1. Identify the runs
For each path, read `.run.yaml` (or infer from the dir) → `source_repo`,
`factory`, `generation`, `run_id`. These name the run in the output; cohorts
share a `run_id`/`generation`.

### 2. Dispatcher health (the first detectable breakdown)
For each run, read `.factory/logs/dispatcher-internal-<date>.jsonl` and compute:
- total events, and the `type` (a.k.a. `event_type`) frequency table;
- **error rate** = `internal.dispatcher_error` + `resolver.load_error` over total;
- whether `resolver.registry_loaded` ever fired (0 = resolvers never loaded);
- the **distinct error messages** (dedupe — thousands of identical lines is one
  breakdown, not thousands).

A run with a high identical-error rate and `registry_loaded=0` is in a
**load-storm breakdown**. Distinguish a *code* breakdown from a *deployment*
breakdown: check whether a fix exists on `develop` but not in the run's pinned
release (the resolver storm is deployment — `dfc76844` is unreleased as of
rc.21). Caution: a `0` for an expected event can also be an artifact of a
*separate* telemetry defect — corroborate with the explicit error events, don't
rest a verdict on an absence alone.

### 3. Convergence cost (per-run, on-disk)
From `.factory/STATE.md` / cycle dirs: passes-to-clean, fix-burst count, streak
resets. Rising passes-to-clean across generations of the same `source_repo` is a
**convergence regression** — a candidate death-spiral proxy that needs no OTEL.

### 4. Velocity — only if honestly attributable
Commits/active-hour and $/commit are the headline velocity measurands, but the
cost/token half is machine-wide until #324. Phase 0: report commit-based
velocity from the run's own git history (per-run, honest); mark any cost/token
figure as **machine-wide aggregate, not per-run** if you surface it at all.

### 5. Compare
Across the given runs (or generations of one `source_repo`): tabulate each
measurand, flag regressions (a later generation worse than an earlier one),
identify the metric of interest (which measurand moved most). Pair every flag
with its evidence window.

### 6. Emit findings (NOT GitHub)
Write the comparison as a critic finding. If a regression is defect-shaped and
lives in a governed target, hand it to beadle for triage — do not post it.
Distilled, durable findings graduate to kos linked to the registry row.

## Output

Report: the runs compared; per-run health/convergence/velocity table; flagged
regressions with evidence windows; the metric of interest; and which findings
(if any) were routed to beadle vs kept internal. Never a GitHub side effect.

## Reference extractor

`extract-dispatcher-health.py` (this dir) implements step 2 against a run's
`.factory/logs/`. It is the worked reference for the per-run, label-free signal.

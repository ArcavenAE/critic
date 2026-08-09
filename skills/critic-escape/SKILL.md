---
name: critic-escape
description: Collect the defect escape-point tripwire — how often a defect survives past PR review into a default branch, which is by definition something every pre-merge check missed. Use to append a dated sample to critic's longitudinal series, or to check a single repo after a post-merge failure. The measure is NOT yet meaningful from one collection (1 failure in 257 post-merge runs at first measurement); its value is the trend critic accumulates over months. Read docs/analysis/defect-escape-point.md before drawing any conclusion from it.
---

# critic — defect escape point (Phase 0, prototype)

Where a defect is caught, relative to its author, is a quality signal that
volume counts cannot give. A bug found by the author's own test run and a
bug found by a stranger are the same row in a tracker and completely
different facts about a process.

This skill samples the one rung of that ladder that is cheaply instrumented
today: **post-merge CI failure on a default branch**. Such a failure is,
definitionally, a defect that survived every pre-merge check.

Read [`../../docs/analysis/defect-escape-point.md`](../../docs/analysis/defect-escape-point.md)
first. It carries the five-rung ladder, the measurement that shaped this
skill, and the honest case against over-investing here.

## The thing to understand before running this

**One collection proves nothing.** First measurement, 2026-08-08, across
sideshow, beadle, marvel and kos: **1 failure in 257 post-merge runs**, and
that one was authored the same day by the agent doing the measuring.

A rate that near zero has no distribution to trend. Sampling it once and
reporting "quality is fine" would be the same error as reading a thermometer
once and concluding the climate. **critic must study this over time** — the
series is the product, which is why the collector appends and never
overwrites.

Two outcomes are worth waiting for, and neither is visible yet:

- The rate **rises**. Pre-merge verification is weakening relative to what
  is being merged. That is the signal worth having, and it is actionable:
  it says tighten the pre-flight, not the process.
- The rate **stays at zero while defects keep appearing**. Then escapes are
  happening at rungs 3 and 4 (release, consumers, external reporters) where
  this instrument is blind, and the blind band below is the real finding.

## Invariants

These extend the four in `critic-compare`; where they overlap, they agree.

1. **No GitHub mutation.** Read-only against the Actions API. critic emits
   findings inward; a defect-shaped finding is handed to beadle.
2. **Repo-level, not run-level.** Unlike `critic-compare`, this samples a
   repository's branch history, not a single run's own telemetry. It
   therefore cannot attribute an escape to a run, a factory, or an agent.
   Do not narrate it as if it could. Every author here is the same human
   principal; the actor gap is `harness-invocation-agent-identity`.
3. **Diagnostic, never a gate.** An escape rate must not become a required
   check, a merge condition, or a session-close condition. It is a vital
   sign, not a structural check, and gating it would make agents optimise
   the number instead of reading it. See `.claude/rules/diagnostic-not-gate.md`
   in aae-orc, and ADR-007.
4. **Report the blind spots in the same breath as the number.** Every
   record carries a `blind` array, and the renderer prints it even when
   empty. A measure that cannot state its own coverage is the failure mode
   that produced this work in the first place.
5. **Never silently widen the infra-noise filter.** `INFRA_WORKFLOWS`
   excludes runs whose failure says nothing about the change. Growing that
   set quietly drives the rate toward zero and looks like improvement.
   Adding an entry is an edit someone reviews.

## Inputs

- `gh`, authenticated, with read access to the repositories.
- Optionally a parent directory of local checkouts (`--checkouts`) for
  rung-3 readiness: whether commits carry ticket refs at all. Reported,
  never scored — a repo without refs is unmeasurable at rung 3, which is a
  property of the instrument, not of the repo.

## Steps

1. Read the analysis doc. Do not skip this; the number is easy to
   misreport.
2. Collect, appending to the series:

   ```sh
   ./collect-escape-tripwire.py \
     --checkouts ~/work/aae-orc \
     --out ~/work/aae-orc/critic/data/escape-series.jsonl \
     ArcavenAE/sideshow ArcavenAE/beadle ArcavenAE/marvel ArcavenAE/kos
   ```

3. Read the `blind` band before the tripwire band. An `undefined` rate
   means no scored runs, which is not the same as zero, and the renderer
   keeps them distinct on purpose.
4. If the tripwire fired, the finding is the specific escape, not the rate:
   which change, which workflow, how long the branch stayed red, and what
   pre-merge check would have caught it. The first recorded instance
   (sideshow `61c53c8`) was a data race that local `go test` missed because
   it lacked `-race`; the fix was to the pre-flight wrapper, not to anyone's
   discipline.
5. Hand defect-shaped findings to beadle. Never post from here.

## Output

JSONL, one record per repo per collection:

```json
{"collected_at":"...","repo":"ArcavenAE/sideshow","branch":"main",
 "push_runs":93,"failures":1,"escape_rate":0.0108,
 "failing":[{"sha":"61c53c8","workflow":"CI","title":"...","url":"..."}],
 "rung3_readiness":{"commits_scanned":419,"ticket_refs":119},
 "blind":["hit the 200-run API cap; window is truncated and the rate is a floor"]}
```

## Known limits

- **Small numbers.** Even fleet-wide, this yields single-digit annual
  counts at the current rate. Aggregate across repos and months, and resist
  reporting a per-repo per-week figure.
- **The 200-run API cap** truncates busy repos, making the rate a floor.
  Recorded in `blind` when it bites.
- **Infra flakes** inflate the numerator. The filter is a blunt instrument
  and deliberately visible.
- **It cannot answer the question that motivated it** — whether
  AI-augmented sessions escape more defects than human ones — because bd
  and git record no actor. That needs `harness-invocation-agent-identity`.

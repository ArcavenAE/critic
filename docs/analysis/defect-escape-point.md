# Direction: defect escape point (frontier)

Where a defect is caught, relative to its author, rather than how many
defects exist. Handed to critic 2026-08-08 from an aae-orc session; this is
critic's domain under the adjudicated boundary (trend-across-runs → critic;
is-this-issue-real-and-aligned → beadle; does-this-run-converge → the
factory's own gates).

Sibling of [global-telemetry.md](global-telemetry.md), which covers pooling
across a distributed team. This covers *what to pool*. It lands on the
charter's third named white-space gap, defect-class-weighted efficiency.

**critic needs to study this over time.** Nothing here is concludable from
the single sample below. The instrument exists (`skills/critic-escape/`);
the series does not yet.

## The question it came from

An operator observed agent-filed sub-issues spreading and asked what was
causing it. The investigating agent measured ticket volume, found creation
outpacing closure roughly 6:1 on heavy days, and framed it as runaway
backlog and insufficient testing.

That framing was wrong, and the way it was wrong is the useful part.
Classifying the same tickets showed **81% were task, feature, decision or
epic** — design and planning output — against 19% bugs. In a
prototyping-heavy programme, creation rate is a *discovery* rate: recording
work that already existed but was invisible. The agent had built a debt
narrative on an unclassified count, which is the same unchecked-premise
error it had spent that day filing findings about.

The salvageable question: volume is confounded and says little about
quality. **Escape point is not confounded.** A bug caught by its author's
own test run and a bug caught by a stranger are the same tracker row and
entirely different facts about a process.

## The ladder

| Rung | Caught by | Instrumented today |
|---|---|---|
| 0 | author's local run | no — nothing records a local failure |
| 1 | PR CI, before merge | yes (GitHub) |
| 2 | post-merge CI on default branch | yes (GitHub) |
| 3 | release / downstream consumer | partially, via ticket↔commit links |
| 4 | external reporter | weakly, via `source:github` labels |

Mass shifting downward over time is the signal. A rising rung-2 rate means
pre-merge verification is weakening relative to what is being merged.

## First measurement, 2026-08-08

Rung 2, across four repos:

| Repo | Post-merge runs | Failures |
|---|---|---|
| sideshow | 73 | 1 |
| beadle | 86 | 0 |
| marvel | 58 | 0 |
| kos | 40 | 0 |

**1 in 257**, and that one was authored the same day by the agent doing the
measuring: a data race that passed a local `go test` because the local
invocation omitted `-race` while CI used it. `main` stayed red 17 hours, no
release was cut, and a remediation ticket waiting on that release stalled
silently.

### What this result does to the design

**Rung 2 is saturated at zero, so it is a tripwire and not a trend.** It
fired exactly once, on a real escape, and there is no distribution to plot.
Building a dashboard for it would be building a dashboard for a constant.

It also partially answers the operator's hypothesis in the negative: if
insufficiently-tested code were shipping at volume, rung 2 is where it
would surface, and it does not.

Two futures are worth waiting for, and only time distinguishes them:

- the rate **rises** — pre-merge verification is weakening; tighten the
  pre-flight, which is exactly what the one recorded instance called for;
- the rate **stays flat while defects keep appearing** — escapes are
  happening at rungs 3 and 4, where this instrument is blind, and the blind
  band becomes the finding.

## Rung 3, and why it is not built

Rung-3 latency (time from the commit that introduced a defect to the ticket
that reported it) needs bug tickets linked to introducing commits. Measured
coverage of ticket refs in commit messages since 2026-06-01:

| Repo | Commits | With a ticket ref |
|---|---|---|
| sideshow | 66 | 67 |
| marvel | 78 | 93 |
| **beadle** | **96** | **10** |

Two repos could support the measure today; one cannot. The collector reports
this as readiness, never as a score. A repo without refs is *unmeasurable at
rung 3*, which is a property of the instrument, not of the repo.

## What was built

`skills/critic-escape/` — SKILL.md plus `collect-escape-tripwire.py`.
Read-only, appends JSONL, one record per repo per collection. Three bands
per record: **tripwire** (the count), **latency** (rung-3 readiness),
**blind** (what the collection could not see).

The blind band is the design's centre of gravity. The session that produced
this analysis found five separate tools reporting success while doing
nothing: `grep -r` returning a clean bill over files it never opened, git
hooks exporting nothing and exiting zero, a version file reporting current
after behaviour changed, a pre-flight wrapper weaker than the CI it existed
to predict, and a `--notes` write that destroyed 2333 characters while
printing success. A new measure that cannot state its own coverage would be
the sixth. So `blind` prints even when empty, and an absent denominator
renders as `undefined` rather than `0.0%`.

## Standing constraint

**Diagnostic, never a gate.** An escape rate must not become a required
check, a merge condition, or a session-close condition. Per ADR-007 and
aae-orc's `.claude/rules/diagnostic-not-gate.md`, a vital sign that gates
stops measuring: agents would optimise the number rather than read it.

This is not hypothetical caution. In the originating session the same agent
proposed gating session-close on closing more tickets than were opened, a
textbook Goodhart gate on a vital sign, and the operator overruled it. The
constraint is recorded here because the failure mode is attractive, and
because it took a human to catch it.

## Open for critic

1. **Cadence.** How often to sample, given a rate this low. Monthly seems
   right; the API cap argues for more often on busy repos.
2. **Aggregation unit.** Per-repo is too sparse. Fleet-wide by month is
   probably the smallest honest unit.
3. **Infra-flake classification.** `INFRA_WORKFLOWS` is a blunt static
   filter. Distinguishing a flake from an escape may need judgment, which
   reintroduces exactly what the measure was meant to avoid.
4. **The attribution ceiling.** This cannot answer whether AI-augmented
   sessions escape more defects than human ones, because bd and git record
   no actor — every author is the same principal. That is
   `harness-invocation-agent-identity` in the aae-orc graph, and until it
   lands, this measures the fleet rather than the method.
5. **Whether rung 3 is worth the linkage discipline** it would impose on
   repos like beadle, or whether the tripwire alone is the right ceiling
   for this line of work.

## kos note

Design references remain authoritative in the aae-orc graph. The
originating measurements are in aae-orc `_kos/findings/finding-118` (ticket
composition and the sub-issue trend) and `finding-119` (the escape
specimen, and the class of instruments that report healthy without
looking).

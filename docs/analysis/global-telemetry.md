# Direction: shared team telemetry (frontier)

> Pre-implementation. Captured session-051 (2026-06-28) from a user direction.
> This is *where critic is going*, not what it does today. No code yet; this doc
> pins the scope, the prerequisites, and the prior art so the build doesn't
> reinvent settled standards or under-build the identity layer.

## The idea

critic today reads one machine's runs from local disk. The high-value form is a
**team-wide** view: a small, distributed team all emits factory-observability
telemetry to a **shared store**, so critic can mine across everyone's runs and
reach **statistical sufficiency**. One person's handful of runs can't support a
confident comparison; the pooled corpus of a whole team can. The value compounds
with volume — more runs, more factory variants, more generations → tighter
confidence intervals on every measurand and the first real chance at
factory-of-factories comparison.

This is a deliberate scope expansion of critic from *local analysis tool* to
*team observability infrastructure*. It is explicitly planned, not pre-built
(SOUL.md §7) — but the design must not paint itself into a single-machine corner.

## Prerequisites (what must be true before pooling helps)

### 1. Rich run provenance — beyond #324

The per-run attribution gap (beadle finding-007 / drbothen/vsdd-factory#324) is
the *local* form of this problem: OTEL metrics carry only `session_id`, no
project/repo/run dimension. The **team** form is strictly harder. To compare
like-with-like across machines and people, a run must be tagged with:

- **project / source_repo** under cultivation (which codebase the factory grows)
- **factory type** (ftc / switchboard / akey / others) AND
- **factory version — to the commit ref** (so a regression isn't blamed on a run
  when it's a factory change between `rc.21` and `develop`; the resolver-storm is
  exactly this — a *deployment* delta, not a run delta)
- **run id** (a stable id above OTEL's `gen_ai.conversation.id`; see §prior-art —
  OTEL has no "run" concept above conversation, so this is ours to define)
- **generation** within a `source_repo` lineage
- **operator / machine** (who/where — for fairness and to detect machine-specific
  artifacts, not for ranking people)

Without commit-ref-level factory provenance, pooled telemetry mixes factory
versions and the comparison is meaningless. Provenance is the load-bearing
prerequisite, not a nice-to-have.

### 2. Normalization across factory types

A ftc-blue run and an akey run and someone else's factory variant must produce
**comparable** measurands, or pooling produces apples-to-oranges aggregates. We
need a normalization layer: a common measurand vocabulary (dispatcher-health,
convergence cost, class-weighted detection efficiency, velocity) defined
independently of any one factory's log shape, plus per-factory adapters that map
each factory's native telemetry into it. **This is a confirmed prior-art gap**
(see below) — no standard normalizes across agentic-factory architectures; we'd
be defining it.

### 3. A distributed shared store — and it shares bd's unsolved problem

The pooled telemetry needs a shared, multi-writer store. **This is the same class
of problem as bd's distributed/shared-store question (orc charter F26), which is
NOT solved** — Phase 0 is localhost-only (`dolt sql-server` at 127.0.0.1:3307),
and the team-writable phase (F26 Phase 2: mTLS, real ops posture) is still
frontier. critic's `legion` Dolt index reuses that same Phase-0 server. So:

- critic's team-telemetry store **inherits F26's blocker** — there is no
  team-writable shared store yet.
- The friction that forced F26's phasing (YubiKey tap fatigue, multi-writer
  serialization, github-per-action touch) applies identically to telemetry push.
- **Do not build a second, parallel distributed-store solution for telemetry.**
  When F26 reaches a network-reachable / team-writable phase, critic's telemetry
  store should ride the same infrastructure. Until then, critic stays per-machine
  and this remains frontier.

## Blockers (explicit)

- **#324** — no per-run OTEL dimension (local attribution). Recoverable offline
  via `session_id` ⋈ dispatcher-log join; unrecoverable for live per-run metrics
  until a run dimension lands upstream.
- **F26 unsolved** — no team-writable shared store; bd's own distributed problem
  gates critic's telemetry-pooling.
- **No factory-version-in-telemetry** — factory commit ref is not currently
  emitted in run telemetry; provenance §1 needs the factory to stamp it (an
  upstream ask) or critic to reconstruct it from the run's pinned plugin version.

## Prior-art scan (session-051) — adopt vs build

Full scan in the session record. Bottom line:

**Adopt directly (settled standards):**
- **SWE-bench % Resolved** + pass@k — de-facto task-resolution metric
  (swebench.com, arXiv:2310.06770; Verified split:
  openai.com/index/introducing-swe-bench-verified).
- **Aider's accuracy + cost pairing** — the rare practitioner standard that puts
  a `Cost ($)` column beside correctness (aider.chat/docs/leaderboards). critic's
  class-weighted efficiency is the same instinct, generalized.
- **OTel GenAI semantic conventions** (`gen_ai.*`) — model/agent/session/token
  attributes, incl. `gen_ai.conversation.id`, `gen_ai.agent.id`
  (opentelemetry.io/docs/specs/semconv/gen-ai). Experimental/Development tier —
  expect churn. **No USD cost attribute exists in OTel** — cost is vendor-only
  (OpenInference `llm.cost.total`, Langfuse `costDetails`); define a documented
  `*.cost.usd` extension and mirror Langfuse's ingested-cost-wins precedence.
- **IEEE 1044-2009** + **ODC** (Chillarege et al., IEEE TSE 1992) — defect
  classification; already in use by beadle, confirmed canonical.

**Borrow patterns:**
- **LMArena / Chatbot Arena Bradley-Terry MLE** with bootstrap CIs — the mature
  pairwise/ELO ranking machinery (lmsys.org). Their entrants are *models*; we'd
  apply the same math to *factories*.
- **HAL — Holistic Agent Leaderboard** (hal.cs.princeton.edu, arXiv:2510.11977)
  — cost-controlled accuracy → **Pareto frontier** framing, so an expensive
  factory winning by 1% doesn't dominate. Single research group, Oct 2025.
- **"AI Agents That Matter"** (Kapoor & Narayanan, arXiv:2407.01502) — the
  intellectual case for joint cost+accuracy / cost-controlled eval.

**Confirmed gaps — no standard exists; this is critic's white space:**
1. **Pairwise / ELO head-to-head between full agentic factories.** Pairwise ELO
   is mature for *models* (LMArena, Copilot Arena); full-*agent* comparison is
   mature but score/cost-ranked (HAL, AgentBench). The intersection — pairwise
   ELO + cost control + whole-factory runs — is unfilled.
2. **Defect-class-weighted / quality-weighted efficiency.** No benchmark weights
   a resolved issue by severity or defect class; SWE-bench counts every resolved
   issue equally. This is exactly critic's class-weighted efficiency (consuming
   beadle's taxonomy — see `boundary-beadle.md`).
3. **Cross-factory normalization.** SWE-bench shares a task set but doesn't
   normalize scaffold/architecture differences; HAL normalizes harness + cost but
   not framework architecture and does no quality weighting.

The three gaps map one-to-one onto what this direction proposes to build. The
adopt/borrow list keeps us from reinventing the parts that are settled.

## kos note

This direction should graduate into a kos frontier node when the kos CLI is
available on this machine (it is not, session-051) — likely at orc level, since
it is cross-cutting (critic infra + F26 distributed-store + an external
benchmarking landscape). Until then this doc + the idea note are the capture.
See `boundary-beadle.md` (the beadle↔critic class coupling) and orc charter F26
(the distributed-store dependency).

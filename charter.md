# critic Charter

> Stub. critic's design is captured authoritatively in the `aae-orc`
> knowledge graph (the frontier nodes and idea below). This charter
> orients a collaborator and records the few decided things; it will fill
> in as critic gains its own kos graph and implementation.

Last updated: 2026-06-28 (created — repo scaffold, session-051)

## What critic is

The run registry (index of agent/factory-grown ephemeral "legion" runs) and
the agent arena (evaluation/comparison/competition of agent configs, teams,
and factories), unified in one project. See [README.md](README.md).

## Bedrock (decided)

- **B1: critic unifies registry + arena.** One project, not two. The registry
  is the critic's notebook; the arena is its judgment. Rationale: the arena
  needs the inventory it evaluates.
- **B2: dev home vs runtime are separate.** This repo is the dev/project home
  (source, CI, build, installer). The runtime — the `run/` working folder and
  the `legion` Dolt index — lives elsewhere, initially in `aae-orc`. Same
  shape as `kos` (developed in `kos/`, run across many repos).
- **B3: the store is layered.** Dolt = the index of record (high-churn roster
  + lineage DAG + status/metrics); kos = distilled findings linked to the Dolt
  row; flyloft = the study/retrieval surface (later). GitHub is never the
  source of truth.
- **B4: runs are selected, not discovered.** A run is identified by a
  case-preserving GitHub org **custom property** (`tier=legion`), never a
  public topic, plus an in-repo `.run.yaml` marker. The repo name is cosmetic.
  See [docs/run-marker-schema.md](docs/run-marker-schema.md).
- **B5: critic is a writer-consumer, not a factory owner.** marvel and the
  factories set the marker/property on spawn; critic indexes and evaluates.

## Frontier (open)

Tracked in `aae-orc`:

- Untouchable-repo path (runs we can't write a marker to).
- The factory enrollment contract (what we hand a factory to self-enroll).
- Discovery trigger + staleness (sweep cadence).
- Pruning + retention of dead/archived runs.
- The arena engine and evaluation methodology (judges, holdout, statistics,
  factory-of-factories) — `question-agent-arena-evaluation`.
- Long-term runtime location (beyond the initial aae-orc host).

## Design references (authoritative — in `aae-orc`)

- `_kos/nodes/frontier/question-legion-run-registry.yaml`
- `_kos/nodes/frontier/question-agent-arena-evaluation.yaml`
- `_kos/ideas/three-tier-repo-taxonomy.md`

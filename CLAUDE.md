# critic — run registry and agent arena

The run registry and agent arena for the Arcaven agentic-engineering
platform. critic keeps track of ephemeral, agent/factory-grown "run" repos
(replicas, spinoffs, autonomous variants), and evaluates, compares, and
competes them — the critic in the audience reviewing the performances.

Two layers in one project:

- **Run registry** — the index of record. Which runs exist, their lineage
  (a DAG), where they came from, their lifecycle and status.
- **Arena** — evaluation and comparison of runs against each other.

Pre-implementation: design lives in the aae-orc knowledge graph; this repo
holds the charter, docs, and skills as they land. The runtime (the `run/`
working folder and legion index) lives in aae-orc, not here — dev home vs
runtime, same pattern as kos.

## Build / Run / Test

No build yet (language undecided; see charter.md). Docs and skills only.

@.claude/rules/_index.md

## Conventions

- **Git workflow:** trunk-based on `main`.
- **No file deletion:** never delete user files; overwrite only with
  explicit intent.

## How to Work Here (kos Process)

### Re-introduction
Read charter.md before any substantive work. It contains bedrock (decided),
frontier (open), and graveyard (ruled out).

### Session Protocol
1. Read charter.md (orient)
2. Identify the highest-value open question — or capture ideas in _kos/ideas/
3. Write an Exploration Brief in _kos/probes/
4. Do the probe work
5. Write a finding in _kos/findings/
6. Harvest: update affected nodes in _kos/nodes/

Cross-repo questions belong in the orchestrator's `_kos/`, not here.

## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking, shared with the
orchestrator via the `.beads -> ../.beads` symlink. Run `bd prime` for
full workflow context.

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or
  markdown TODO lists
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

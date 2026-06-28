# critic

The **run registry and agent arena** for the Arcaven agentic-engineering
platform. critic keeps track of ephemeral, agent/factory-grown "run" repos
(replicas, spinoffs, autonomous variants), and evaluates, compares, and
competes them — the critic in the audience reviewing the performances.

Two layers in one project:

- **Run registry** — the index of record. Which runs exist, their lineage
  (a DAG), where they came from, their lifecycle and status. The critic's
  working notebook.
- **Arena** — the judgment. Evaluate/compare/compete agent configs, teams,
  and factories: judges, holdout scenarios, the gallery model
  (variants × generations), and "factory of factories" (which factory
  *configuration* produces better results).

## Status

**Pre-implementation.** This repo is the development/project home for critic;
the design lives (authoritatively) in the `aae-orc` knowledge graph. critic is
not yet built. See [charter.md](charter.md) for what's decided and what's open.

## Dev home vs runtime

critic is *developed in and published from* this repo. It is *run* somewhere
else — initially inside the `aae-orc` orchestrator, where the `run/` working
folder and the `legion` Dolt database are critic's runtime data. This mirrors
how `kos` is developed in its own repo but used across many repos. Don't
conflate the two: this repo holds source, CI, build, and installer; it is not
the runtime environment.

## How it fits the platform

- **Storage** — the shared Dolt service-plane holds the `legion` index table.
- **Knowledge** — distilled findings graduate into `kos`, linked back to their
  registry row (never one kos node per run).
- **Study/retrieval** — `flyloft` is the eventual surface for mining the
  latent data inside runs (errors, metrics, observations).
- **Writers, not owners** — `marvel` and the factories (e.g. vsdd-factory) set
  a run's marker and custom property on spawn. critic indexes and evaluates;
  it does not own the factories' lifecycle.

## Design references (authoritative — in `aae-orc`)

- `_kos/nodes/frontier/question-legion-run-registry.yaml` — the registry layer.
- `_kos/nodes/frontier/question-agent-arena-evaluation.yaml` — the arena layer.
- `_kos/ideas/three-tier-repo-taxonomy.md` — the full design capture
  (canon / integration / legion tiers; the run marker; the layered store).
- [docs/run-marker-schema.md](docs/run-marker-schema.md) — the `.run.yaml`
  marker contract a run carries.

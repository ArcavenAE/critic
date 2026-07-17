# `.run.yaml` — run marker schema

The marker a run repo carries at its root. It is the portable,
case-preserving, internally-visible record of what a run is, written by the
factory at spawn. It is the source of truth that travels with the repo (for
runs we can write to), and the factory's self-enrollment contract.

This same field set spans three surfaces:

- **`.run.yaml` marker** — spawn-time facts, in the run repo.
- **`legion` Dolt table** — one row per run: the marker fields **plus** the
  mutable/observed layer (status, last-seen, metrics, study state, the kos
  link). The index of record.
- **GitHub org custom property** — a tiny non-public subset (`tier`, `source`,
  `factory`) for one-query selection (`gh search repos --owner ArcavenAE
  'props.tier:legion'`). Never a public topic.

## Fields

| Field | Marker | Dolt | Property | Required | Notes |
|---|:--:|:--:|:--:|:--:|---|
| `schema_version` | ✓ | ✓ | — | **yes** | declarative-contract version |
| `tier` | ✓ | ✓ | ✓ | **yes** | `legion` for agent/factory runs; `integration` for tier-2 contribution forks |
| `kind` | ✓ | ✓ | — | **yes** | `legion` (agent/factory) \| `spike` (human throwaway) \| `fork` (human-governed contribution fork of an external upstream — renamed from `contrib`, 2026-07-17); `spike` and `fork` have `factory` empty |
| `source_repo` | ✓ | ✓ | ✓ | **yes** | the canonical repo this was struck from (case-preserving) |
| `source_remote` | ✓ | ✓ | — | no | git remote of the source |
| `factory` | ✓ | ✓ | ✓ | **yes** | e.g. `vsdd-factory` |
| `parent` | ✓ | ✓ | — | no | the lineage DAG edge — immediate parent run; empty = struck from canon |
| `run_id` | ✓ | ✓ | — | no | groups a batch / generation (cohort) |
| `generation` | ✓ | ✓ | — | no | depth in the genetic process, if tracked |
| `lifecycle` | ✓ | ✓ | — | no | `ephemeral` \| `retained` |
| `created_by` / `created_at` | ✓ | ✓ | — | no | spawn provenance |
| `question` | ✓ | ✓ | — | no | the major question this run examines (its micro kos-cycle) |
| `status` | — | ✓ | — | — | mutable: `active` / `archived` / `abandoned` — Dolt only (would drift in a marker) |
| `metrics` | — | ✓ | — | — | open JSON: error modes, performance, outcomes — the arena's input |
| `kos_finding` | — | ✓ | — | — | reference to a graduated kos finding (registry row → kos) |
| `study_status` | — | ✓ | — | — | `unstudied` / `sampled` / `studied` / `skipped` |
| `studied_by` / `skip_reason` | — | ✓ | — | — | free slot + e.g. `redundant-in-cohort` |
| `discovered_at` / `last_seen` | — | ✓ | — | — | sweep bookkeeping |
| `repo` / `remote` / `visibility` / `default_branch` | — | ✓ | — | — | from GitHub at index time |

Required = the five (`schema_version`, `tier`, `kind`, `source_repo`,
`factory`) a factory must know to self-enroll at spawn. Everything else is
optional and filled progressively.

## Example

```yaml
# .run.yaml — at the root of a run repo
schema_version: 1
tier: legion
kind: legion
source_repo: switchboard
source_remote: git@github.com:ArcavenAE/switchboard.git
factory: vsdd-factory
run_id: 2026-06-28-sweep-a
parent:            # empty — struck directly from canon
generation: 0
lifecycle: ephemeral
created_by: vsdd-factory
created_at: 2026-06-28T00:00:00Z
question: "Does the timeslice framing reduce relay latency under load?"
```

## Example — `kind: fork` (contribution fork)

> Renamed from `kind: contrib` (2026-07-17): with the orc's `contrib/`
> directory now meaning direct-contribution checkouts (origin is theirs),
> the fork variety takes the accurate name. Forks are tier-2, live in the
> orc's `forks/` directory (not `run/`), and carry `tier: integration`.

```yaml
# .run.yaml — contribution fork of an external upstream
schema_version: 1
tier: integration
kind: fork
source_repo: vsdd-factory
source_remote: git@github.com:DrBothen/vsdd-factory.git
factory:            # empty — human-governed
lifecycle: retained
created_by: skippy
created_at: 2026-07-05T00:00:00Z
question: "Can we land feature+factory-artifact changes upstream as an external contributor?"
```

`fork` marks a long-lived, human-governed fork held **only** to offer
PRs to an upstream we don't control — clone-only, never developed as its
own project. Differences from `legion`/`spike`:

- `source_repo`/`source_remote` point at the **external upstream**, not an
  ArcavenAE canon repo.
- `lifecycle: retained` — it persists as long as the contribution
  relationship does.
- **The marker is untracked** in a contribution fork (add `.run.yaml` to
  `.git/info/exclude`, not `.gitignore`): every branch may flow upstream
  as a PR, and factory metadata must never ride one. This is the
  "untouchable-repo path" (Q5) applied to our own fork of an untouchable
  upstream — the Dolt row remains the index of record; the marker is a
  local convenience.

Instances: `ArcavenAE/vsdd-factory` (→ DrBothen), `ArcavenAE/jira-cli`
and `ArcavenAE/wirerust` (→ Zious11). See aae-orc
`docs/vsdd-factory-contrib.md` and the 2026-07-17 addendum in the orc's
`_kos/ideas/three-tier-repo-taxonomy.md`.

## Notes

- The marker lives **only in the run repo** — it never flows back to the
  canonical source.
- For runs we cannot write to (not ours, or no access), there is no marker;
  the run is indexed in the Dolt store only, discovered by observation or a
  provided list.
- Lineage is structured (`parent` + `run_id` + `generation`), not a free
  string — the `parent` pointer is the DAG adjacency the registry traverses.

Authoritative design: `aae-orc` `_kos/nodes/frontier/question-legion-run-registry.yaml`.

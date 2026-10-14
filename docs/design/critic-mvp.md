# critic MVP: a run record first, then the ledger and the comparison

**Status:** proposed. Nothing here is built or ratified.
**Ticket:** aae-orc-hp96 (build critic MVP).
**Graph:** seeds `_kos/nodes/frontier/elem-run-record-model.yaml` and `_kos/nodes/frontier/elem-run-lineage.yaml`.

## 1. Why

critic has a design and no code. Its two first consumers are both waiting on the same missing piece, and it is not the piece the MVP ticket names.

The ticket (hp96, filed 2026-06-29) asks for a repository registry first:
- a `legion` Dolt table;
- `run-sync`, discovering run repos by GitHub custom property;
- `run-checkout`, for lazy clones into `run/`;
- an isolation check.

The two consumers named for it do not index repositories. They measure factory executions:

1. **The vsdd-factory team probe** (marvel `_kos/probes/probe-vsdd-factory-as-marvel-team.md`, ArcavenAE/marvel#875). Arm A runs a pinned release in one session, and arm B runs each parallel branch as its own marvel session. It needs a cache ledger, a cost meter and a paired comparison (that brief's sections 9 to 11). Its ledger blocks the pilot.
2. **The rc.22 against rc.24 side-by-side** (aae-orc-17ki). The same factory runs at two pack versions on one rig. It is the same shape as consumer 1, with the arm label being the pack version instead of the session topology.

This design gives critic one record for "a run" that serves both shapes, a lineage rule, and a build order that delivers the consumers first. Registry sync becomes one locus type of that record, built when there is something to sync.

## 2. What was checked (2026-10-14)

| premise | command | result |
|---|---|---|
| critic has no code on main | `git ls-tree -r --name-only origin/main` | holds: docs, skills and two Phase 0 scripts under `skills/` |
| run repos exist to index | `ls run/` in the orchestrator; `git log -1` in each | the same two mirrors the registry design named in June. The newer one's last commit is in September 2026; two checkouts read 09-08 and 09-09, so the day is checkout-local |
| run repos carry the `.run.yaml` marker | `find run forks contrib -maxdepth 2 -name .run.yaml` | neither run repo has one. One checkout found a marker on a contribution fork and another found none: fork markers are untracked (`.git/info/exclude`), so that count is host-local |
| the `tier=legion` org custom property exists | `gh api orgs/ArcavenAE/properties/schema --jq length` | 0: no custom properties are defined |
| a `legion` database exists on the shared Dolt server | `bd sql "show databases"` | no: only the issue tracker's databases |
| the Dolt server is local to the runtime host | `bd sql "select @@port"` and the client config | no: it is the shared bd server, reached over the LAN, on port 3307 |
| no orchestrator recipe globs `run/` (the Q10 isolation check) | `grep -n 'run/' justfile` | holds: no matches |

So run-sync would discover nothing today: no property to query, and no marker to read. The isolation check already holds structurally, and a test can keep it holding.

## 3. The run record

**One record per run.** A run is one execution that critic measures or indexes: a factory session set on a test project, a seed run, or a legion repository. Its fields extend the run-marker schema (`docs/run-marker-schema.md`), both its marker layer and its Dolt layer, and do not replace it. Every schema field keeps its meaning, and every value the schema defines keeps its meaning. One field gains a value: `kind` adds `trial`, which exists in the record only. The schema's kinds are unchanged, and a `.run.yaml` marker cannot carry `trial` unless the schema adds it in a change of its own. The fields below are new, except where a row says it is the schema's.

| field | meaning | consumer use |
|---|---|---|
| `id` | unique, immutable, lowercase, no slashes | the probe's run key |
| `kind` | the schema's field: `legion`, `spike`, `fork` (the schema's kinds), plus **`trial`**, record only: an execution measured under a protocol | probe and 17ki runs are trials |
| `factory`, `factory_ref` | `factory` is the schema's field; `factory_ref`, new, holds its pins: pack version, upstream commit, pack digest | arm A and arm B share these in the probe; 17ki's arms differ only here |
| `arm` | a free label for the treatment | `one-session` and `per-branch`; or `rc.22` and `rc.24` |
| `run_id` | the marker's field, unchanged: it groups a batch or generation, the cohort. For a trial it names the series: protocol sha plus series number. The record's `id` names the run; `run_id` names its cohort | one `run_id` per probe series |
| `block`, `order` | the pair index and position within it; empty outside a paired series | the strict pairs |
| `protocol_role` | `smoke`, `live-test`, `seed`, `pilot`, `series`, `fidelity`, `reference`, `drill`, `defaults`, or empty | only `series` enters the comparison |
| `parents` | the effective-lineage view of the edge rows (section 4, L5): the parents named by every edge that no correction supersedes. It is read from the rows, never written directly. The marker's `parent` is the first entry, as a `derived-from` edge | the seed is the parent of every pilot and series run that starts from it |
| `protocol_sha`, `harness_build` | the frozen protocol and client build | the drift stop reads them |
| `locus` | where the run's state lives: a repository at a commit, or a checkout path under the runtime root, with start and end commits | the suite runs on the end commit |
| `sessions` | harness session ids and marvel session keys | joins transcripts to seats |
| `transcript_roots` | paths to the run's transcripts, under the runtime root | the ledger's input |
| `started_at`, `ended_at` | wall clock as the protocol defines it | the speed axis |
| `status` | the schema's Dolt-layer field, unchanged: `active`, `archived` or `abandoned` | lifecycle, as for any run |
| `run_state` | the execution's state, a new field: `started`, `completed`, `stalled`, `crashed`, `timed-out`, `limit-stopped` or `void` | intent-to-treat keeps every state except `void` |
| `void_rule` | the protocol rule that set `void`, by its section; required when `run_state` is `void`, and empty otherwise | a void is never unexplained |
| `host_class` | the role of the host the run used (for example, probe host), never its name | the fairness pins |
| `outcome` | accepted count, scenario pass rate, canary hit | the primary's denominator |
| `ledger`, `cost` | path and sha256 of each derived output | reproducibility |
| `metrics` | the schema's Dolt-layer field, unchanged: open JSON | everything else |
| `kos_finding` | the schema's Dolt-layer field, unchanged: the finding a run graduated into | the harvest link |

**What never enters the record:**
- transcript content;
- secret values;
- host names. `host_class` names the role of the host, not the machine.

Transcripts stay in the runtime area, which is private. This repository holds code and fixtures only (charter B2).

## 4. Lineage

Proposed rules (`elem-run-lineage`):

- **L1. A lineage edge records derivation only,** between two runs: the child's starting state came from the parent's state. There are two edge kinds:
  - `derived-from`: the marker's `parent`, a run struck from another run;
  - `resumed-from`: a run that starts from another run's snapshot, such as a seed.

  A run struck directly from canon has no edge. Its `source_repo` records the canon repository, as the marker's "empty = struck from canon" already says.
- **L2. Grouping is not lineage.** The cohort (`run_id`), block and arm are columns. Two runs in one pair share a block, not an edge. Putting pairing into edges would make every comparison a graph query and blur the derivation the edge exists for.
- **L3. `parents` is a list from day one,** so the store is a DAG as the registry design asks. It is the effective-lineage view of L5's edge rows, not a second store. The two consumers use at most one parent per run.
- **L4. A seed is a run.** Every pilot and series run that starts from a seed lists it as `resumed-from`. A close's scope ("every close claims only the seed snapshot sha") becomes a lineage query: the claim holds for the runs descended from that seed. On the probe's S8-failure path, runs start from the brief instead and carry no lineage edge. Their scope is the test project's start commit, which the record holds as the `locus` start commit.
- **L5. Lineage is append-only.**
  - **An edge** is a row with its own identity: `edge_id`, `child`, `parent`, `kind`, `recorded_at` and `recorded_by`.
  - **A correction** is a row with `correction_id`, `supersedes` (an `edge_id`), an optional replacement edge, `reason`, `recorded_at` and `recorded_by`.
  - **The effective lineage** is every edge that no correction supersedes.
  - Nothing is edited in place, so the history the store keeps stays readable.

## 5. Build order

Two orders were weighed:

| | A. Registry first (hp96 as written) | B. Consumers first (recommended) |
|---|---|---|
| first deliverable | a `legion` table, sync by custom property, lazy checkout | the run record, the transcript ledger, the cost meter and the paired comparison |
| input it has today | two repositories, no property, no marker (section 2) | none: the probe's pilot waits on its own operator rulings, and 17ki waits on its ruling |
| input once its preconditions land | the run repos, once a factory writes markers or sets the property (the registry's Q6 enrollment contract, still open) | the probe's pilot and series runs; 17ki's runs if kept |
| build cost | three components (the table, sync, lazy checkout) plus the isolation test. Not sized | four components (section 6). Not sized |
| unblocks | nothing named | the probe's pilot (its ledger step) and both consumers' analysis |
| registry sync | first | later, as the `legion` locus of the same record, when a marker or property exists |

**Recommendation: B.** It is the operator's ruling, R1 below.

## 6. Components (each a flat builder ticket; filing is the supervisor's)

Each ships as a red/green draft PR on critic with its tests.

1. **The run record and `critic run`** (`register`, `show`, `list`, `lineage`):
   - writes and reads the section 3 record and the section 4 edges;
   - refuses a duplicate `id`, a `void` without a `void_rule`, and an edge edit in place;
   - schema tests, and a test that no orchestrator recipe globs `run/` (the isolation check).
   - Blocks 4 and 5.
2. **The transcript ledger reader:** the probe brief's section 10, outputs 1 to 8:
   - dedupe by `message.id`;
   - cold start and cache death as defined there;
   - a hand-counted fixture that reads back exactly, and the OTEL reconcile at 1% per class.
   - It reads transcripts and writes a ledger file. It does not need component 1, so it can start at once.
   - Blocks 3.
3. **The cost meter:** the probe brief's section 11:
   - a frozen price table;
   - cost by token class;
   - OTEL-only request sources priced as their own row.
   - Blocks 4.
4. **The paired comparison:**
   - the delta-method interval on the log ratio of sums, blocked by pair, with the bootstrap over pairs as a sensitivity;
   - Holm adjustment on secondaries;
   - the zero-accepted rules from the probe brief: the pilot rule in section 8.5, the canary rule in section 9.2, and the both-arms and one-arm rules in section 9.4;
   - a coverage check of the interval at the series' n.
   - Blocked by 1 and 3.
5. **Legion sync** (hp96's original scope): the `legion` locus, discovery by custom property or a provided list, and lazy checkout. Blocked by 1. It waits until a property or marker exists. Until then it is a ticket, not a build.

Component 4 also bears on an open filing question for the probe: whether its comparison script is a separate piece of work. Built here, it is one component that both consumers reuse.

## 7. Store and language

- **Store.** Charter B3 holds: Dolt is the index of record. The records and edges live in a `critic` database. The proposal puts it on the shared Dolt server, which is reachable from any fleet machine, so the probe host can write to it. Adding a database to that server changes shared state, so it is ruling R2. If that is declined, the fallback is a Dolt server local to the probe host, with the same schema. Tests run against a throwaway local Dolt either way.
- **Language.** The charter leaves it undecided. The recommendation is Python under `uv`:
  - critic's existing Phase 0 scripts are Python;
  - the components are transcript parsing and statistics;
  - the arena engine is a later, separate question.

  This is ruling R3.

## 8. What happens to hp96

- If B is ruled: hp96 stays the MVP slot, with a `REMAINING:` note naming components 1 to 4. Component 5 becomes its own flat ticket, carrying the original scope.
- If A is ruled: hp96 stands as written, and components 2 to 4 become separate tickets for the consumers.

Either way, the isolation check is recorded as already holding (section 2), with a test to keep it.

## 9. Open rulings

Each recommendation is valid until 2026-10-28; the architect role re-checks it then. Nothing here executes on silence.

| ruling | options | recommendation |
|---|---|---|
| R1. critic's first code | A. registry first; B. consumers first (section 5) | B |
| R2. where the `critic` database lives | the shared Dolt server; or a Dolt server on the probe host | the shared server |
| R3. language | Python under `uv`; Rust; Go | Python under `uv` |
| R4. 17ki as the second consumer | keep, on this rig; close; re-scope to rc.22 against rc.25 | keep. If closed, consumer 2 drops and nothing else changes |

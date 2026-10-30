# critic arena policy: leakage and holdout

**Status:** proposed. The rules are candidates (tag `H`) until the operator ratifies them. Nothing here is built.
**Ruling it rests on:** operator ruling I-35 (2026-10-30), which adopted two of the meta-harness dive's recommendations: 1, one run id joining source, score and raw trace, placed in critic's run record; and 2, leakage and holdout rules written as critic arena policy before any comparison. This document is the second. H1 restates the first as a condition on entering a comparison.
**Fills:** arena question A2 (holdout management) in the orchestrator's `question-agent-arena-evaluation` node.
**Written by:** the arcaven architect, 2026-10-30.

## 1. Why

A comparison that lets the thing being tuned see the data that grades it reports how well it memorized, not how well it works. The first arena comparison is where that habit forms, so the rules are written before any comparison runs. They cost design text now and one field and two refusals in critic later.

## 2. Terms

- **Candidate:** one configuration under comparison (a harness, a prompt, a factory version, a team shape).
- **Proposer:** whoever or whatever writes or picks candidates: a person, a seat or a search loop.
- **Task set:** the scored tasks a comparison runs, each with an automatic score.
- **Split:** every task is in exactly one of `search` (the proposer may see tasks, scores and traces), `validation` (scores used to pick a candidate; the proposer sees scores, not tasks or traces) or `test` (scored once, after the pick).

## 3. Rules

- **H1. One id per run, raw traces kept.** Every run a comparison uses is a critic run record (component 1) with its source, score and raw trace pointers under one id. Summaries may be added; they never replace the raw trace. A run with no raw trace cannot enter a comparison.
- **H2. Test data lives outside the proposer's reach.** Test tasks, their expected outputs and their scorers are stored where the proposer's workspace cannot read them: a path outside every proposer seat's working tree and sandbox, readable only by the scoring step. The comparison's protocol names that path, and critic refuses to register a test-split run whose task path sits under the proposer's working directory. That refusal is the only part of H2 critic enforces. Whether the path is also outside every proposer's sandbox, and readable only by the scoring step, is a check on the protocol, made by the person who approves it; critic does not see sandboxes or file permissions and does not claim to.
- **H3. Pick before looking.** The candidate to test is frozen before any test score exists: the protocol records the pick (the candidate's run id and source hash) with a time, and critic refuses a test-split run whose `started_at` is earlier than the frozen pick.
- **H4. No untouched test set, no confirmatory claim.** A result with no test split, or whose test split was viewed before the pick, is labelled `exploratory` in critic's output and in any finding that quotes it. Only a result that meets H2 and H3 is labelled `confirmatory`.
- **H5. Forbidden references.** Each task may list strings a candidate must not contain: its expected answer, a test file name, a scorer identifier. Before a candidate runs on the test split, critic scans the candidate's source (the files its run record names) for each string, and a hit voids the run (`run_state = void`, `void_rule = H5`).
- **H6. Rotation.** A test split is used for one confirmatory comparison. After its scores are read, its tasks move to `validation` for later rounds, and a fresh test split is drawn for the next confirmatory claim. The protocol records which tasks each split held.
- **H7. Authorship.** Whoever authors the test tasks and scorers is not a proposer in the comparisons that use them, and is named by role in the protocol.
- **H8. Every run counts.** Runs are analyzed as assigned (intent to treat). Only a run voided by a named rule (H5, or the protocol's own) leaves the analysis, with the rule recorded.

## 4. What critic enforces, and what stays a human act

critic computes and refuses (SOUL section 8, ADR-007):
- the `split` field on the run record (`search`, `validation`, `test`, or empty outside the arena);
- the refusals in H2 and H3, the scan in H5, and the `exploratory` or `confirmatory` label in H4.

People decide:
- which tasks form each split and who authors them (H6, H7);
- whether a confirmatory result changes anything. critic's label is a fact about how the result was produced, not a verdict on the candidate.

## 5. What this does not cover

- **The vsdd-factory probe and 17ki.** They run under their own frozen protocols. Their runs enter critic as records, labelled by H4 as their protocols allow; nothing here changes either protocol.
- **A fixed task set.** None exists yet (the dive found none). These rules govern one once it does; building one is separate work.
- **The search pilot** (the dive's recommendation 4), deferred by I-35.

## 6. Build impact

- Component 1's record gains `split`. The other refusals land with component 4, the comparison, since that is where splits are read.
- No change to components 2 or 3.

## 7. Candidate requirements (provisional, source class)

- H1: operator ruling I-35, from the dive's recommendation 1.
- H2, H3, H4, H5: operator ruling I-35, from the dive's recommendation 2.
- H6, H7: architect, filling arena question A2 (rotation; who authors hidden scenarios).
- H8: architect, from critic-mvp.md section 3 (`run_state`, intent to treat).

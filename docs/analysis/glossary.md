# Glossary of agent-team metrics

This glossary fixes ten terms used when the fleet measures its own agent teams, so critic, director and marvel mean the same thing by each. critic computes the numbers; director and marvel collect and emit what critic reads. Each entry names its published source, its start and end events, its unit, the fleet source, the statistic, and the instability measure it is reported with.

Every metric here is diagnostic. None is a gate, and none turns into a pass or fail without its own ratified decision. Report a median with its p25, p75 and n, never a mean alone. Report by role and team, not by seat. A throughput count is never printed alone: it sits beside its instability measure, so no single number can be chased.

Sources are those of the agent-team metrics survey behind this plan. Where two sources define a term differently, the entry says which start and end events the fleet uses.

| term | reported with |
|---|---|
| [cost-of-pass](#cost-of-pass) | change fail rate |
| [throughput](#throughput) | change fail rate, rework rate |
| [cycle time](#cycle-time) | rework rate |
| [work item age](#work-item-age) | none (a state measure) |
| [WIP](#wip) | cycle time |
| [coordination overhead](#coordination-overhead) | throughput |
| [flow efficiency](#flow-efficiency) | cycle time |
| [change fail rate](#change-fail-rate) | throughput |
| [rework rate](#rework-rate) | throughput |
| [human revision cost](#human-revision-cost) | throughput |

## cost-of-pass

- **Definition:** the cost of an attempt divided by the probability that it succeeds. Failed and unmerged attempts are charged to the successes, so spend on work that never merged is part of the numerator. The economic form is from Erol et al., "Cost-of-Pass: An Economic Framework for Evaluating Language Models" (2025, https://arxiv.org/abs/2504.13359); the FinOps Foundation's cost per successful outcome is the same idea in billing terms (https://www.finops.org/insights/token-economics/).
- **Start and end events:** start is the first spend recorded for the task; end is the merge of its pull request, or the close of the pull request unmerged. A task with no merge still has spend, and that spend is counted.
- **Unit:** USD per merged change.
- **Fleet source:** the spend ledger joined to GitHub by the task key. A session with no key is joined through its pull request head branch.
- **Statistic:** median with p25, p75 and n over tasks in the period.
- **Reported with:** change fail rate.

## throughput

- **Definition:** items finished per period, as the Kanban Guide defines it (Coleman et al., 2025, https://kanbanguides.org/english/).
- **Start and end events:** a count at the end event only: a pull request merged, or an ask closed.
- **Unit:** items per week, per role and team.
- **Fleet source:** GitHub merges; asks closed in director's asks.jsonl.
- **Statistic:** the count for the period, with the weekly series beside it; the median and spread of that series.
- **Reported with:** change fail rate and rework rate. A rise in throughput that comes with a rise in either is not an improvement.

## cycle time

- **Definition:** elapsed time from start to finish of an item (Kanban Guide). The Kanban Guide and Kanban University's guide differ on what to call this and on "lead time", so the start event is always named where the term is used.
- **Start and end events:** start is ask accepted, or pull request opened; end is ask closed, or pull request merged. Name the pair in every use.
- **Unit:** hours, or days for pull requests.
- **Fleet source:** director's asks and relay log; GitHub.
- **Statistic:** median with p25, p75 and n. Cycle times are skewed, so a mean is not reported.
- **Reported with:** rework rate.

## work item age

- **Definition:** elapsed time from start to now, for an item not yet finished (Kanban Guide).
- **Start and end events:** start as for cycle time; there is no end event. The item is still open.
- **Unit:** hours or days.
- **Fleet source:** open asks; open pull requests; bd tickets that are claimed.
- **Statistic:** the age of each open item, listed oldest first, with the median and the oldest.
- **Reported with:** none. It is a state measure, read at a moment, and it needs no instability pairing.

## WIP

- **Definition:** work in progress: items started and not finished (Kanban Guide).
- **Start and end events:** an item counts from its start event until its end event, as for cycle time.
- **Unit:** items, per role and team, at a point in time.
- **Fleet source:** open asks plus open pull requests.
- **Statistic:** the count at each reading, summarized as the median and p75 of the readings in the period.
- **Reported with:** cycle time. WIP and cycle time rise together when work piles up.

## coordination overhead

- **Definition:** the family name for extra turns spent coordinating rather than doing the work. Kim et al., "Towards a Science of Scaling Agent Systems" (2025, https://arxiv.org/abs/2512.08296) define an overhead percentage against a solo baseline. The fleet does not run a solo baseline, so it reports counts, not that percentage.
- **Start and end events:** each event is one occurrence: an empty wait that returns no message, or a wake for mail addressed to another seat.
- **Unit:** count per period, and as a share of all waits.
- **Fleet source:** the day-signals file and the ledger.
- **Statistic:** the count and the share per day, with the median and spread across days.
- **Reported with:** throughput. Fewer empty waits at lower throughput is not a gain.

## flow efficiency

- **Definition:** active time over elapsed time (the Flow Framework, in Kersten, *Project to Product*, IT Revolution, 2018). The fleet's director waiting share is its inverse.
- **Start and end events:** the same pair as the cycle time it is computed over.
- **Unit:** a ratio, 0 to 1.
- **Fleet source:** the ledger's director classes, which split active turns from waiting.
- **Statistic:** median with p25, p75 and n over items.
- **Reported with:** cycle time.

## change fail rate

- **Definition:** the share of merged changes later fixed by a fix pull request (the DORA delivery metric, https://dora.dev/guides/dora-metrics-four-keys/). The fleet has no deployments, so a merge stands in for a deployment.
- **Start and end events:** the denominator is merges in the period; a merge counts as failed when a later pull request names it with a `Fixes-PR:` trailer.
- **Unit:** a ratio of merges, by repo until a key exists (role and team wait on the task key).
- **Fleet source:** GitHub, read through the `Fixes-PR:` trailer.
- **Statistic:** the ratio for the period with n, and the series over periods. A small n is stated, not hidden.
- **Reported with:** throughput.

## rework rate

- **Definition:** the share of merged changes that are unplanned fixes. It adapts DORA's deployment rework rate (https://dora.dev/insights/dora-metrics-history/) from deployments to merges.
- **Start and end events:** a merge counts as rework when it is a fix pull request (a `Fixes-PR:` trailer) or closes a bd ticket of the bug type.
- **Unit:** a ratio of merges, by repo until a key exists (role and team wait on the task key).
- **Fleet source:** GitHub and bd.
- **Statistic:** the ratio for the period with n, and the series over periods.
- **Reported with:** throughput.

## human revision cost

- **Definition:** the number of revision rounds an output needs before it merges, and the split between merged as is and merged after revision. The idea adapts MetaGPT's human revision cost (Hong et al., 2024, https://proceedings.iclr.cc/paper_files/paper/2024/hash/6507b115562bb0a305f1958ccc87355a-Abstract-Conference.html).
- **Start and end events:** start is the first review of the pull request; each review that is in the `CHANGES_REQUESTED` state, or is a comment review whose body carries a not-yet verdict, followed by new commits, is one round; end is the merge. Both count: on the repos where the forge state is used it is the larger signal, and where reviews are posted as comments the verdict is in the body. Consecutive revision reviews answered by the same commits are one round; a base merge does not answer a review.
- **Unit:** rounds per pull request.
- **Fleet source:** GitHub reviews and commits.
- **Statistic:** median with p25, p75 and n, and the share merged with zero rounds.
- **Reported with:** throughput.

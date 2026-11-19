#!/usr/bin/env python3
# Human revision cost: revision rounds per PR. Definition: docs/analysis/glossary.md#human-revision-cost
# Fleet reviews are mostly COMMENT reviews with the verdict in the body, so CHANGES_REQUESTED alone undercounts.
# A revision review is one whose state is CHANGES_REQUESTED or whose body has a line that starts "Verdict: NOT YET".
# A round is the first commit that lands after a revision review (a base merge is not one), so two revision reviews with no commit between
# them are one round, and a revision review no commit answers is none. A line "Verdict: PASS" is not a revision.
# commits_after_first_review is reported beside rounds, because a PR can be revised after an unlabeled review.
# Input: a JSON list of PRs, each {repo, number, merged, state (MERGED, CLOSED or OPEN), reviews:[{state, submittedAt, body}],
#   commits:[{committedDate, messageHeadline}]}
#   (a `gh pr view --json` export reshaped to that form). Other keys, authors included, are ignored and never printed.
# Output: JSON with per-PR rounds, a summary (the merged count with its instability measure in one object: median, p25,
#   p75 and n of rounds, the as-is and after-revision split and the share revised; the unmerged count beside it) and the same summary by repo. Never a mean,
#   never per seat. A diagnostic, never a gate (ADR-007).
# Collect: one `gh pr view` per PR, because a list call that asks for reviews and commits together passes GitHub's
#   GraphQL node limit above about 40 PRs:
#   gh pr list --repo OWNER/REPO --state all --limit 500 --json number --jq '.[].number' \
#     | while read n; do gh pr view "$n" --repo OWNER/REPO --json number,state,mergedAt,reviews,commits; done \
#     | jq -s --arg repo OWNER/REPO '[.[] | {repo: $repo, number, state, merged: (.mergedAt != null), reviews, commits}]' > prs.json
# Usage: python3 -I revision-rounds.py PRS_JSON
import json, re, statistics, sys

# A line, after any markdown lead (quote, heading, bullet, bold), that says "Verdict: NOT YET" in any case or starts
# with the bare capitals "NOT YET". "**Verdict: NOT YET** at <sha>" and "NOT YET at <sha>" both count; prose such as
# "not yet covered" and a "NOT YET" quoted mid-line do not.
NOT_YET = re.compile(r'^[ \t>#*_-]*(?:(?i:verdict:[ \t*_]*not yet)|NOT YET)\b', re.MULTILINE)


def is_revision(r):
    return r.get('state') == 'CHANGES_REQUESTED' or bool(NOT_YET.search(r.get('body') or ''))


MERGE_HEADLINE = re.compile(r'^Merge (branch|remote-tracking branch|pull request|commit)\b')


def is_merge_commit(c):
    # A base fold is not a fix: a commit with two parents, or (the gh export has no parents) a headline git wrote.
    return len(c.get('parents') or []) > 1 or bool(MERGE_HEADLINE.match(c.get('messageHeadline') or ''))


def measure(p):
    reviews = sorted(p.get('reviews') or [], key=lambda r: r['submittedAt'])
    commits = sorted(c['committedDate'] for c in p.get('commits') or [] if not is_merge_commit(c))
    answered = set()
    for r in reviews:
        if is_revision(r):
            later = [c for c in commits if c > r['submittedAt']]
            if later:
                answered.add(later[0])
    after_first = len([c for c in commits if reviews and c > reviews[0]['submittedAt']])
    return {'repo': p['repo'], 'number': p['number'], 'merged': bool(p.get('merged')), 'state': p.get('state'),
            'rounds': len(answered), 'commits_after_first_review': after_first}


def spread(values):
    if not values:
        return {'median': None, 'p25': None, 'p75': None, 'n': 0}
    if len(values) == 1:
        return {'median': values[0], 'p25': values[0], 'p75': values[0], 'n': 1}
    q = statistics.quantiles(values, n=4, method='inclusive')
    return {'median': statistics.median(values), 'p25': q[0], 'p75': q[2], 'n': len(values)}


def summarize(rows):
    merged = [r['rounds'] for r in rows if r['merged']]
    after = len([x for x in merged if x > 0])
    # throughput never prints alone: it sits in one object with the instability measure it is read against
    return {'throughput': {'merged': len(merged),
                           'instability': {'rounds': spread(merged),
                                           'merged_as_is': len(merged) - after,
                                           'merged_after_revision': after,
                                           'share_as_is': ((len(merged) - after) / len(merged)) if merged else None,
                                           'share_after_revision': (after / len(merged)) if merged else None}},
            'closed_unmerged': len([r for r in rows if not r['merged'] and r['state'] == 'CLOSED']),
            'open': len([r for r in rows if not r['merged'] and r['state'] == 'OPEN']),
            'state_unknown': len([r for r in rows if not r['merged'] and r['state'] not in ('CLOSED', 'OPEN')])}


def main(path):
    with open(path) as f:
        rows = [measure(p) for p in json.load(f)]
    repos = sorted({r['repo'] for r in rows})
    out = {'prs': rows, 'summary': summarize(rows),
           'by_repo': {repo: summarize([r for r in rows if r['repo'] == repo]) for repo in repos}}
    print(json.dumps(out, indent=2, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1])

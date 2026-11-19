#!/usr/bin/env python3
# Human revision cost: revision rounds per PR. Definition: docs/analysis/glossary.md#human-revision-cost
# Fleet reviews are mostly COMMENT reviews with the verdict in the body, so CHANGES_REQUESTED alone undercounts.
# A revision review is one whose state is CHANGES_REQUESTED or whose body has a line that starts "Verdict: NOT YET".
# A round is the first commit that lands after a revision review, so two revision reviews with no commit between
# them are one round, and a revision review no commit answers is none. A line "Verdict: PASS" is not a revision.
# commits_after_first_review is reported beside rounds, because a PR can be revised after an unlabeled review.
# Input: a JSON list of PRs, each {repo, number, merged, reviews:[{state, submittedAt, body}], commits:[{committedDate}]}
#   (a `gh pr view --json` export reshaped to that form). Other keys, authors included, are ignored and never printed.
# Output: JSON with per-PR rounds, a summary (median, p25, p75 and n over merged PRs, with the merged count, the
#   as-is and after-revision split and the unmerged count beside it) and the same summary by repo. Never a mean,
#   never per seat. A diagnostic, never a gate (ADR-007).
# Collect: gh pr list --repo OWNER/REPO --state all --limit 200 --json number,mergedAt,reviews,commits \
#   | jq --arg repo OWNER/REPO '[.[] | {repo: $repo, number, merged: (.mergedAt != null), reviews, commits}]' > prs.json
# Usage: python3 -I revision-rounds.py PRS_JSON
import json, re, statistics, sys

NOT_YET = re.compile(r'^[ \t]*Verdict:[ \t]*NOT YET\b', re.MULTILINE | re.IGNORECASE)


def is_revision(r):
    return r.get('state') == 'CHANGES_REQUESTED' or bool(NOT_YET.search(r.get('body') or ''))


def measure(p):
    reviews = sorted(p.get('reviews') or [], key=lambda r: r['submittedAt'])
    commits = sorted(c['committedDate'] for c in p.get('commits') or [])
    answered = set()
    for r in reviews:
        if is_revision(r):
            later = [c for c in commits if c > r['submittedAt']]
            if later:
                answered.add(later[0])
    after_first = len([c for c in commits if reviews and c > reviews[0]['submittedAt']])
    return {'repo': p['repo'], 'number': p['number'], 'merged': bool(p.get('merged')),
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
    return {'rounds': spread(merged), 'throughput_merged': len(merged),
            'merged_as_is': len([x for x in merged if x == 0]),
            'merged_after_revision': len([x for x in merged if x > 0]),
            'closed_unmerged': len([r for r in rows if not r['merged']])}


def main(path):
    with open(path) as f:
        rows = [measure(p) for p in json.load(f)]
    repos = sorted({r['repo'] for r in rows})
    out = {'prs': rows, 'summary': summarize(rows),
           'by_repo': {repo: summarize([r for r in rows if r['repo'] == repo]) for repo in repos}}
    print(json.dumps(out, indent=2, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1])

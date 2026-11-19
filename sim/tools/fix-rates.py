#!/usr/bin/env python3
# Change fail rate and rework rate, by period. Definitions: docs/analysis/glossary.md#change-fail-rate and #rework-rate
# Change fail rate: the share of changes merged in a period that a later merged fix-PR names in a line that starts
#   "Fixes-PR: <owner>/<repo>#<n>" (the trailer the git-commits rule defines). A change counts once however many
#   fixes name it. A fix merged before its target does not fail it.
# Rework rate: the share of changes merged in a period that are unplanned fixes: a merged PR that carries a Fixes-PR
#   trailer, or a line that starts "Closes: <bd id>" naming a bd ticket of type bug. A "Refs:" line is not rework.
# Period: the calendar month (YYYY-MM) of the merge. A fix counts against the period of the change it fixes.
# Throughput (merged PRs in the period) prints beside both rates; a rate is never read alone. Counts and rates only,
# no mean, no author, no seat. A diagnostic, never a gate (ADR-007). Trailers are a signal; a fix with no trailer
# is invisible here, so a low rate is a floor on the failures, not proof of none.
# Input: {"prs": [{repo, number, mergedAt (null when unmerged), text (body plus commit messages)}],
#         "bd_issues": [{id, issue_type}]}. Other keys are ignored and never printed.
# Collect: one `gh pr view` per PR, because a list call that asks for commits passes GitHub's GraphQL node limit
#   above about 40 PRs:
#   gh pr list --repo OWNER/REPO --state merged --limit 500 --json number --jq '.[].number' \
#     | while read n; do gh pr view "$n" --repo OWNER/REPO --json number,mergedAt,body,commits; done \
#     | jq -s --arg repo OWNER/REPO '[.[] | {repo: $repo, number, mergedAt, text: (.body + "\n" + ([.commits[].messageBody] | join("\n")))}]'
#   and the bug ids from bd (issue_type = bug), as {id, issue_type} rows.
# Usage: python3 -I fix-rates.py IN_JSON
import json, re, sys

FIXES = re.compile(r'^[ \t]*Fixes-PR:[ \t]*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+)[ \t]*$', re.MULTILINE)
CLOSES = re.compile(r'^[ \t]*Closes:[ \t]*(.+)$', re.MULTILINE)


def key(repo, n):
    return (repo.lower(), int(n))


def fix_targets(text):
    return [key(r, n) for r, n in FIXES.findall(text or '')]


def closed_bd_ids(text):
    ids = []
    for line in CLOSES.findall(text or ''):
        ids += [t for t in re.split(r'[\s,]+', line.strip()) if t]
    return ids


def rate(num, den):
    return {'numerator': num, 'denominator': den, 'rate': (num / den) if den else None}


def main(path):
    with open(path) as f:
        d = json.load(f)
    bug_ids = {i['id'] for i in d.get('bd_issues') or [] if i.get('issue_type') == 'bug'}
    merged = [p for p in d['prs'] if p.get('mergedAt')]
    by_key = {key(p['repo'], p['number']): p for p in merged}
    failed, unresolved = set(), 0
    rework = set()
    for p in merged:
        targets = fix_targets(p.get('text'))
        if targets or any(i in bug_ids for i in closed_bd_ids(p.get('text'))):
            rework.add(key(p['repo'], p['number']))
        for t in targets:
            target = by_key.get(t)
            if target is None:
                unresolved += 1
            elif target['mergedAt'] < p['mergedAt']:
                failed.add(t)
    periods = {}
    for p in merged:
        periods.setdefault(p['mergedAt'][:7], []).append(key(p['repo'], p['number']))
    out = {}
    for period in sorted(periods):
        ks = periods[period]
        out[period] = {'throughput': len(ks),
                       'change_fail': rate(len([k for k in ks if k in failed]), len(ks)),
                       'rework': rate(len([k for k in ks if k in rework]), len(ks))}
    print(json.dumps({'by_period': out, 'unresolved_links': unresolved}, indent=2, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1])

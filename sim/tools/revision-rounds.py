#!/usr/bin/env python3
# Human revision cost: revision rounds per PR. Definition: docs/analysis/glossary.md#human-revision-cost
# Usage: python3 -I revision-rounds.py PRS_JSON
# Red stub: well-formed output with no figures, so the tests fail on their assertions.
import json, sys
prs = json.load(open(sys.argv[1]))
none = {'median': None, 'p25': None, 'p75': None, 'n': 0}
print(json.dumps({'prs': [{'repo': p['repo'], 'number': p['number'], 'rounds': None,
                           'commits_after_first_review': None} for p in prs],
                  'summary': {'rounds': none, 'throughput_merged': None, 'merged_as_is': None,
                              'merged_after_revision': None, 'closed_unmerged': None},
                  'by_repo': {}}))

#!/usr/bin/env python3
# Change fail rate and rework rate, by period. Definitions: docs/analysis/glossary.md#change-fail-rate and #rework-rate
# Red stub: well-formed output with no figures, so the tests fail on their assertions.
import json, sys
d = json.load(open(sys.argv[1]))
none = {'numerator': None, 'denominator': None, 'rate': None}
periods = {p['mergedAt'][:7] for p in d['prs'] if p.get('mergedAt')}
print(json.dumps({'by_period': {k: {'throughput': None, 'change_fail': none, 'rework': none} for k in periods},
                  'unresolved_links': None}))

#!/usr/bin/env python3
# flow-metrics.py: flow metrics for one period, from director's asks.jsonl and a gh pull request export.
# Usage: flow-metrics.py OUT_DIR ASKS_JSONL PRS_JSON PERIOD [ASOF] [LEDGER_OUT_DIR]
#   OUT_DIR       receives flow-metrics.csv
#   ASKS_JSONL    director's asks.jsonl: intake rows (ask_id, received_at) and close rows (event close, ask_id, closed_at)
#   PRS_JSON      the output of: gh pr list -R <owner/repo> --state all --limit 1000 --json number,state,createdAt,mergedAt,closedAt
#   PERIOD        the month as YYYY-MM, matched as a UTC timestamp prefix, as ledger-s10-axes.py does
#   ASOF          the instant for the state measures (work item age, WIP) as an ISO time; '' or absent means the end of PERIOD
#   LEDGER_OUT    the output directory of ledger-s10-axes.py; '' or absent means flow efficiency prints pending
# Every metric is diagnostic and never a gate (ADR-007; aae-orc .claude/rules/diagnostic-not-gate.md). Terms and their
# events are defined in critic docs/analysis/glossary.md (glossary.md#throughput, glossary.md#cycle-time,
# glossary.md#work-item-age, glossary.md#wip, glossary.md#flow-efficiency).
# Start and end events, named in every row:
#   asks   start = ask accepted (the intake row's received_at); end = ask closed (the close row's closed_at)
#   prs    start = PR opened (createdAt); end = PR merged (mergedAt). A PR closed unmerged is not throughput and has no cycle time.
# Measures:
#   throughput       items finished in PERIOD (end event in PERIOD): asks closed that have an intake row, PRs merged
#   cycle time       end minus start, in hours, for items finished in PERIOD
#   work item age    ASOF minus start, in hours, for items started on or before ASOF and not finished by ASOF
#   wip              the count of those same unfinished items
#   flow efficiency  one minus the director waiting share, from the ledger's director-wait-bridge.csv 'new' lines:
#                    director sessions / (director sessions + hub wait), by list cost. A share of cost, not a duration,
#                    so it names no start event; it is the ledger's proxy for active over elapsed until time-in-state exists.
# Statistics: every per-item figure is n, median, p25 and p75, never a mean (linear interpolation between order statistics).
# A figure with n of 0 prints n/a, never 0. A count (throughput, wip) carries n only.
# Every throughput row carries its instability measure beside it; change fail rate is not computed yet, so it prints pending.
import csv, json, os, re, sys
from datetime import datetime, timezone

def die(msg):
    print('flow-metrics: '+msg, file=sys.stderr); sys.exit(2)

if len(sys.argv) < 5: die('usage: flow-metrics.py OUT_DIR ASKS_JSONL PRS_JSON PERIOD [ASOF] [LEDGER_OUT_DIR]')
OUT, ASKS, PRS, PERIOD = sys.argv[1:5]
ASOF_ARG = sys.argv[5] if len(sys.argv) > 5 else ''
LEDGER = sys.argv[6] if len(sys.argv) > 6 else ''
if not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])', PERIOD): die('period must be YYYY-MM, got %r' % PERIOD)

def ts(s):
    # an ISO time with Z or an offset; None when absent or not a time
    if not isinstance(s, str) or not s: return None
    try: t = datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError: return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)

y, m = int(PERIOD[:4]), int(PERIOD[5:])
END = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc)
ASOF = ts(ASOF_ARG) if ASOF_ARG else END
if ASOF is None: die('as-of must be an ISO time, got %r' % ASOF_ARG)
def inperiod(t): return t is not None and t.strftime('%Y-%m') == PERIOD

try: lines = open(ASKS, errors='replace').read().splitlines()
except OSError as ex: die('cannot read the asks file %s: %s' % (ASKS, ex.__class__.__name__))
try: prs = json.load(open(PRS))
except (OSError, ValueError) as ex: die('cannot read the pull request file %s: %s' % (PRS, ex.__class__.__name__))
if not isinstance(prs, list): die('the pull request file must hold a JSON list')

# asks: one intake time per ask (the first), one close per ask (the first); a close with no intake row is not counted
start, end = {}, {}
for line in lines:
    try: r = json.loads(line)
    except ValueError: continue
    if not isinstance(r, dict) or not isinstance(r.get('ask_id'), str): continue
    if r.get('event') == 'close': end.setdefault(r['ask_id'], ts(r.get('closed_at')))
    elif ts(r.get('received_at')): start.setdefault(r['ask_id'], ts(r.get('received_at')))
asks = [(start[a], end.get(a)) for a in start]
pulls = [(ts(p.get('createdAt')), ts(p.get('mergedAt'))) for p in prs if isinstance(p, dict)]
pulls = [(s, e) for s, e in pulls if s is not None]

def pct(v, q):
    x = q * (len(v) - 1); lo = int(x); hi = min(lo + 1, len(v) - 1); return v[lo] + (v[hi] - v[lo]) * (x - lo)
def fmt(x): return str(int(x)) if x == int(x) else str(round(x, 2))
def hours(a, b): return (b - a).total_seconds() / 3600
def spread(vals):
    v = sorted(vals)
    if not v: return [0, 'n/a', 'n/a', 'n/a']
    return [len(v)] + [fmt(pct(v, q)) for q in (.5, .25, .75)]

rows = []
def add(metric, source, s_ev, e_ev, unit, stats, inst=('', '')): rows.append([metric, source, s_ev, e_ev, unit] + stats + list(inst))
ASK_S, ASK_E = 'ask accepted (intake received_at)', 'ask closed (close closed_at)'
PR_S, PR_E = 'PR opened (createdAt)', 'PR merged (mergedAt)'
UNFIN = 'as-of instant'
INST = ('change fail rate', 'pending')
done_a = [(s, e) for s, e in asks if inperiod(e)]
done_p = [(s, e) for s, e in pulls if inperiod(e)]
add('throughput', 'asks', ASK_S, ASK_E, 'asks closed', [len(done_a), '', '', ''], INST)
add('throughput', 'prs', PR_S, PR_E, 'PRs merged', [len(done_p), '', '', ''], INST)
add('cycle time', 'asks', ASK_S, ASK_E, 'hours', spread([hours(s, e) for s, e in done_a]))
add('cycle time', 'prs', PR_S, PR_E, 'hours', spread([hours(s, e) for s, e in done_p]))
def unfinished(items): return [s for s, e in items if s <= ASOF and (e is None or e > ASOF)]
ua = unfinished(asks)
# a PR closed unmerged has no merged time and would read as open forever, so it is excluded from the unfinished set
closed_unmerged = {ts(p.get('createdAt')) for p in prs if isinstance(p, dict) and p.get('state') == 'CLOSED' and not p.get('mergedAt')
                   and ts(p.get('closedAt')) is not None and ts(p.get('closedAt')) <= ASOF}
up = [s for s, e in pulls if s <= ASOF and (e is None or e > ASOF) and s not in closed_unmerged]
add('work item age', 'asks', ASK_S, UNFIN, 'hours', spread([hours(s, ASOF) for s in ua]))
add('work item age', 'prs', PR_S, UNFIN, 'hours', spread([hours(s, ASOF) for s in up]))
add('wip', 'asks', ASK_S, ASK_E, 'asks open', [len(ua), '', '', ''], ('cycle time', 'see cycle time row'))
add('wip', 'prs', PR_S, PR_E, 'PRs open', [len(up), '', '', ''], ('cycle time', 'see cycle time row'))

fe = 'pending'
if LEDGER:
    try:
        with open(os.path.join(LEDGER, 'director-wait-bridge.csv'), newline='') as fh:
            u = {r['row']: int(r['usd_micro']) for r in csv.DictReader(fh) if r['line'] == 'new'}
        d, h = u.get('director sessions (coordination)'), u.get('hub wait (bus polling)')
        fe = fmt(d / (d + h)) if d is not None and h is not None and d + h > 0 else 'n/a'
    except (OSError, KeyError, ValueError): fe = 'n/a'
add('flow efficiency', 'ledger', 'n/a (a share, not a duration)', 'n/a (a share, not a duration)', 'share of list cost', ['', fe, '', ''], ('cycle time', 'see cycle time row'))

os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, 'flow-metrics.csv'), 'w', newline='') as fh:
    w = csv.writer(fh, lineterminator='\n')
    w.writerow(['metric', 'source', 'start_event', 'end_event', 'unit', 'n', 'median', 'p25', 'p75', 'instability_measure', 'instability_value'])
    w.writerows(rows)

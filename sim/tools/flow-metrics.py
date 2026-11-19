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
#   throughput       items finished in PERIOD (end event in PERIOD): asks closed that have an intake row, PRs merged. n is the
#                    count; weekly_series is the count per seven-day bucket from the first of the month (days 1-7, 8-14, ...,
#                    the last bucket short), and median, p25 and p75 describe that series.
#   cycle time       end minus start, in hours, for items finished in PERIOD
#   work item age    ASOF minus start, in hours, for items started on or before ASOF and not finished by ASOF; oldest and
#                    oldest_id name the oldest open item, and work-item-age.csv lists every open item, oldest first
#   wip              one reading at 00:00Z of each day of PERIOD up to ASOF: items started and not finished at that instant.
#                    n is the number of readings; median, p25 and p75 are of the readings
#   flow efficiency  one minus the director waiting share, from the ledger's director-wait-bridge.csv 'new' lines:
#                    director sessions / (director sessions + hub wait), by list cost. A share of cost, not a duration,
#                    so it names no start event and prints in the value column, with no n; it is the ledger's proxy for
#                    active over elapsed until time-in-state exists.
# Statistics: every per-item figure is n, median, p25 and p75, never a mean (linear interpolation between order statistics).
# A figure with n of 0 prints n/a, never 0.
# Pairings (glossary): throughput with change fail rate and rework rate; cycle time with rework rate; WIP with cycle time.
# Change fail rate and rework rate are computed by fix-rates.py, not here, so they print pending.
# Grouping: rows are by source (asks, PRs) because no ask or PR carries a role and team key yet; the glossary unit is per role
# and team, and every row's note says so.
# A PR closed unmerged counts as open from createdAt to closedAt, so it is in WIP and work item age until it closes, and it
# is never throughput or cycle time. PRs are keyed by number, so two PRs created in the same second stay distinct.
# gh pr list stops at --limit rows. When the export holds exactly 1000 rows, the script warns on stderr and every PR row's note
# says older PRs may be missing.
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
asks = [(a, start[a], end.get(a)) for a in start]
LIMIT = 1000
pulls, pulls_open = [], []
for p in prs:
    if not isinstance(p, dict) or ts(p.get('createdAt')) is None: continue
    n = str(p.get('number'))
    pulls.append((n, ts(p.get('createdAt')), ts(p.get('mergedAt'))))
    # a PR closed unmerged is open from createdAt to closedAt (it was work in progress until then) and is never throughput;
    # its end for the open-at-an-instant measures is closedAt, and an export that omits closedAt leaves it open
    unmerged = p.get('state') == 'CLOSED' and not p.get('mergedAt')
    pulls_open.append((n, ts(p.get('createdAt')), ts(p.get('closedAt')) if unmerged else ts(p.get('mergedAt'))))
TRUNC = len(prs) == LIMIT
if TRUNC: print('flow-metrics: the pull request export holds exactly %d rows, the gh --limit; older PRs may be missing' % LIMIT, file=sys.stderr)

def pct(v, q):
    x = q * (len(v) - 1); lo = int(x); hi = min(lo + 1, len(v) - 1); return v[lo] + (v[hi] - v[lo]) * (x - lo)
def fmt(x): return str(int(x)) if x == int(x) else str(round(x, 2))
def hours(a, b): return (b - a).total_seconds() / 3600
def spread(vals):
    v = sorted(vals)
    if not v: return ['n/a', 'n/a', 'n/a']
    return [fmt(pct(v, q)) for q in (.5, .25, .75)]

NOTE = 'grouped by source until an ask or PR carries a role and team key; the glossary unit is per role and team'
PRNOTE = 'PR export holds exactly %d rows, the gh --limit; older PRs may be missing' % LIMIT
HDR = ['metric', 'source', 'start_event', 'end_event', 'unit', 'n', 'median', 'p25', 'p75', 'oldest', 'oldest_id',
       'weekly_series', 'value', 'instability_measure', 'instability_value', 'note']
rows = []
def add(metric, source, s_ev, e_ev, unit, n='', stats=('', '', ''), oldest=('', ''), weekly='', value='', inst=('', '')):
    note = NOTE + (' | ' + PRNOTE if TRUNC and source == 'prs' else '')
    rows.append([metric, source, s_ev, e_ev, unit, n, *stats, *oldest, weekly, value, *inst, note])
ASK_S, ASK_E = 'ask accepted (intake received_at)', 'ask closed (close closed_at)'
PR_S, PR_E = 'PR opened (createdAt)', 'PR merged (mergedAt)'
UNFIN = 'as-of instant'
INST_T = ('change fail rate; rework rate', 'pending; pending')
INST_C = ('rework rate', 'pending')
INST_W = ('cycle time', 'see cycle time row')
done_a = [(a, s, e) for a, s, e in asks if inperiod(e)]
done_p = [(a, s, e) for a, s, e in pulls if inperiod(e)]
ndays = (END - datetime(y, m, 1, tzinfo=timezone.utc)).days
def weekly(items):
    buckets = [0] * ((ndays + 6) // 7)
    for _, _, e in items: buckets[(e.day - 1) // 7] += 1
    return buckets
for src, done, s_ev, e_ev, unit in (('asks', done_a, ASK_S, ASK_E, 'asks closed'), ('prs', done_p, PR_S, PR_E, 'PRs merged')):
    wk = weekly(done)
    add('throughput', src, s_ev, e_ev, unit, len(done), spread(wk), weekly=';'.join(map(str, wk)), inst=INST_T)
for src, done, s_ev, e_ev in (('asks', done_a, ASK_S, ASK_E), ('prs', done_p, PR_S, PR_E)):
    add('cycle time', src, s_ev, e_ev, 'hours', len(done), spread([hours(s, e) for _, s, e in done]), inst=INST_C)
def open_at(items, t):
    return [(a, s) for a, s, e in items if s <= t and (e is None or e > t)]
age_rows = []
for src, items, s_ev in (('asks', asks, ASK_S), ('prs', pulls_open, PR_S)):
    op = sorted(open_at(items, ASOF), key=lambda x: x[1])
    ages = [hours(s, ASOF) for _, s in op]
    age_rows += [[src, a, s.strftime('%Y-%m-%dT%H:%M:%SZ'), fmt(hours(s, ASOF))] for a, s in op]
    add('work item age', src, s_ev, UNFIN, 'hours', len(op), spread(ages), oldest=(fmt(ages[0]), op[0][0]) if op else ('n/a', 'n/a'))
    readings = []
    for d in range(ndays):
        t = datetime(y, m, 1 + d, tzinfo=timezone.utc)
        if t <= ASOF: readings.append(len(open_at(items, t)))
    add('wip', src, s_ev, ASK_E if src == 'asks' else PR_E, 'items per reading', len(readings), spread(readings), inst=INST_W)

fe = 'pending'
if LEDGER:
    try:
        with open(os.path.join(LEDGER, 'director-wait-bridge.csv'), newline='') as fh:
            u = {r['row']: int(r['usd_micro']) for r in csv.DictReader(fh) if r['line'] == 'new'}
        d, h = u.get('director sessions (coordination)'), u.get('hub wait (bus polling)')
        fe = fmt(d / (d + h)) if d is not None and h is not None and d + h > 0 else 'n/a'
    except (OSError, KeyError, ValueError): fe = 'n/a'
add('flow efficiency', 'ledger', 'n/a (a share, not a duration)', 'n/a (a share, not a duration)', 'share of list cost', value=fe, inst=INST_W)

os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, 'flow-metrics.csv'), 'w', newline='') as fh:
    w = csv.writer(fh, lineterminator='\n'); w.writerow(HDR); w.writerows(rows)
# every open item at ASOF, oldest first within each source
with open(os.path.join(OUT, 'work-item-age.csv'), 'w', newline='') as fh:
    w = csv.writer(fh, lineterminator='\n'); w.writerow(['source', 'id', 'start', 'age_hours']); w.writerows(age_rows)

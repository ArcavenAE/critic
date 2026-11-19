#!/usr/bin/env python3
# Tests for flow-metrics.py. Runs the script end to end over invented asks and invented gh pull request data, so nothing
# here reads a real home directory or the network.
# Run: python3 -I sim/tools/test_flow_metrics.py
import csv, json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, 'flow-metrics.py')
COLS = ['metric', 'source', 'start_event', 'end_event', 'unit', 'n', 'median', 'p25', 'p75', 'oldest', 'oldest_id',
        'weekly_series', 'value', 'instability_measure', 'instability_value', 'note']
NOTE_ROLE = 'grouped by source until an ask or PR carries a role and team key; the glossary unit is per role and team'


class Row(dict):
    # a column the script does not write reads as a marker, so a missing column is an assertion failure and not a KeyError
    def __missing__(self, k):
        return '<no column %s>' % k


class Rows(dict):
    def __missing__(self, k):
        raise AssertionError('no row %r in flow-metrics.csv' % (k,))


def intake(a, at):
    return {'ask_id': a, 'received_at': at, 'source': 'x', 'text': 'invented'}


def close(a, at, how='answer'):
    return {'ask_id': a, 'event': 'close', 'closed_at': at, 'as': how, 'ref': ''}


ASKS = [
    intake('a1', '2026-11-01T00:00:00Z'), close('a1', '2026-11-03T00:00:00Z'),   # 48 h
    intake('a2', '2026-11-02T00:00:00Z'), close('a2', '2026-11-06T00:00:00Z'),   # 96 h
    intake('a3', '2026-11-02T00:00:00Z'), close('a3', '2026-11-12T00:00:00Z'),   # 240 h
    intake('a4', '2026-10-30T00:00:00Z'), close('a4', '2026-12-02T00:00:00Z'),   # closed after the period: open at as-of
    intake('a5', '2026-11-20T00:00:00Z'),                                        # open
    close('a6', '2026-11-10T00:00:00Z'),                                         # close row with no intake: ignored
    intake('a7', '2026-10-01T00:00:00Z'), close('a7', '2026-10-05T00:00:00Z'),   # closed before the period
]
PRS = [
    {'number': 1, 'state': 'MERGED', 'createdAt': '2026-11-01T00:00:00Z', 'mergedAt': '2026-11-01T12:00:00Z', 'closedAt': '2026-11-01T12:00:00Z'},
    {'number': 2, 'state': 'MERGED', 'createdAt': '2026-11-02T00:00:00Z', 'mergedAt': '2026-11-04T00:00:00Z', 'closedAt': '2026-11-04T00:00:00Z'},
    {'number': 3, 'state': 'CLOSED', 'createdAt': '2026-11-03T00:00:00Z', 'mergedAt': None, 'closedAt': '2026-11-05T00:00:00Z'},
    {'number': 4, 'state': 'OPEN', 'createdAt': '2026-11-25T00:00:00Z', 'mergedAt': None, 'closedAt': None},
]


def run(asks=ASKS, prs=PRS, period='2026-11', asof='', ledger=None, raw=False):
    """Returns {(metric, source): row} and the CompletedProcess."""
    with tempfile.TemporaryDirectory() as d:
        ap, pp, out = os.path.join(d, 'asks.jsonl'), os.path.join(d, 'prs.json'), os.path.join(d, 'out')
        with open(ap, 'w') as fh:
            fh.write('\n'.join(json.dumps(a) for a in asks) + '\n')
        with open(pp, 'w') as fh:
            json.dump(prs, fh)
        os.makedirs(out)
        lg = ''
        if ledger is not None:
            lg = os.path.join(d, 'ledger'); os.makedirs(lg)
            with open(os.path.join(lg, 'director-wait-bridge.csv'), 'w', newline='') as fh:
                w = csv.writer(fh, lineterminator='\n')
                w.writerow(['cluster', 'line', 'row', 'requests', 'usd_micro'])
                w.writerows(ledger)
        r = subprocess.run([sys.executable, '-I', SCRIPT, out, ap, pp, period, asof, lg], capture_output=True, text=True)
        f = os.path.join(out, 'flow-metrics.csv')
        rows = Rows()
        if os.path.exists(f):
            with open(f) as fh:
                rdr = csv.DictReader(fh)
                rows = Rows({(x['metric'], x['source']): Row(x) for x in rdr})
                rows['_cols'] = rdr.fieldnames
        af = os.path.join(out, 'work-item-age.csv')
        if os.path.exists(af):
            with open(af) as fh:
                rows['_age'] = list(csv.DictReader(fh))
        return rows, r


class Flow(unittest.TestCase):
    def setUp(self):
        self.rows, self.r = run()
        self.assertEqual(self.r.returncode, 0, self.r.stderr)
        self.assertIn(('throughput', 'asks'), self.rows)

    def test_columns_have_no_mean(self):
        self.assertEqual(self.rows['_cols'], COLS)

    def test_throughput_counts_asks_closed_in_the_period_that_have_an_intake_row(self):
        t = self.rows[('throughput', 'asks')]
        self.assertEqual(t['n'], '3')
        self.assertEqual(t['unit'], 'asks closed')

    def test_throughput_counts_merged_prs_in_the_period_and_not_closed_unmerged(self):
        self.assertEqual(self.rows[('throughput', 'prs')]['n'], '2')

    def test_every_throughput_row_is_paired_with_its_instability_measure(self):
        for src in ('asks', 'prs'):
            t = self.rows[('throughput', src)]
            self.assertEqual(t['instability_measure'], 'change fail rate; rework rate')
            self.assertEqual(t['instability_value'], 'pending; pending')

    def test_cycle_time_rows_are_paired_with_rework_rate(self):
        for src in ('asks', 'prs'):
            c = self.rows[('cycle time', src)]
            self.assertEqual([c['instability_measure'], c['instability_value']], ['rework rate', 'pending'])

    def test_throughput_has_a_weekly_series_with_its_median_and_spread(self):
        # seven-day buckets from the first of the month: days 1-7, 8-14, 15-21, 22-28, 29-30
        t = self.rows[('throughput', 'asks')]
        self.assertEqual(t['weekly_series'], '2;1;0;0;0')
        self.assertEqual([t['median'], t['p25'], t['p75']], ['0', '0', '1'])
        self.assertEqual(self.rows[('throughput', 'prs')]['weekly_series'], '2;0;0;0;0')

    def test_work_item_age_prints_the_oldest_item_and_lists_every_open_item_oldest_first(self):
        a = self.rows[('work item age', 'asks')]
        self.assertEqual([a['oldest'], a['oldest_id']], ['768', 'a4'])
        p = self.rows[('work item age', 'prs')]
        self.assertEqual([p['oldest'], p['oldest_id']], ['144', '4'])
        self.assertIn('_age', self.rows)
        self.assertEqual([(r['source'], r['id'], r['age_hours']) for r in self.rows['_age']],
                         [('asks', 'a4', '768'), ('asks', 'a5', '264'), ('prs', '4', '144')])

    def test_every_row_carries_the_missing_role_and_team_key_note(self):
        for k, row in self.rows.items():
            if isinstance(k, tuple):
                self.assertEqual(row['note'].split(' | ')[0], NOTE_ROLE, k)

    def test_cycle_time_of_asks_runs_from_accepted_to_closed_with_median_and_spread(self):
        c = self.rows[('cycle time', 'asks')]
        self.assertEqual([c['n'], c['median'], c['p25'], c['p75'], c['unit']], ['3', '96', '72', '168', 'hours'])
        self.assertEqual(c['start_event'], 'ask accepted (intake received_at)')
        self.assertEqual(c['end_event'], 'ask closed (close closed_at)')

    def test_cycle_time_of_prs_runs_from_opened_to_merged(self):
        c = self.rows[('cycle time', 'prs')]
        self.assertEqual([c['n'], c['median'], c['p25'], c['p75']], ['2', '30', '21', '39'])
        self.assertEqual(c['start_event'], 'PR opened (createdAt)')
        self.assertEqual(c['end_event'], 'PR merged (mergedAt)')

    def test_work_item_age_counts_items_unfinished_at_the_as_of_instant(self):
        # as-of defaults to the end of the period, 2026-12-01: a4 (closed 12-02) and a5 are open, ages 768 h and 264 h
        a = self.rows[('work item age', 'asks')]
        self.assertEqual([a['n'], a['median'], a['p25'], a['p75'], a['unit']], ['2', '516', '390', '642', 'hours'])
        self.assertEqual(a['end_event'], 'as-of instant')
        p = self.rows[('work item age', 'prs')]
        self.assertEqual([p['n'], p['median']], ['1', '144'])

    def test_wip_is_the_median_and_p75_of_daily_readings_over_the_period(self):
        # one reading at 00:00Z of each day of the month, 30 readings. asks open per day: 1 for 8 days, 2 for 18, 3 for 3, 4 for 1
        w = self.rows[('wip', 'asks')]
        self.assertEqual([w['n'], w['median'], w['p25'], w['p75'], w['unit']], ['30', '2', '1.25', '2', 'items per reading'])
        # PRs: 1 open on days 1-3 and 25-30, none on the other 21 days; the closed-unmerged PR is never in WIP
        p = self.rows[('wip', 'prs')]
        self.assertEqual([p['n'], p['median'], p['p75']], ['30', '0', '1'])

    def test_wip_is_paired_with_cycle_time(self):
        self.assertEqual(self.rows[('wip', 'asks')]['instability_measure'], 'cycle time')

    def test_an_explicit_as_of_moves_the_state_measures(self):
        rows, r = run(asof='2026-11-15T00:00:00Z')
        self.assertEqual(r.returncode, 0, r.stderr)
        # at 11-15: a4 open (closed 12-02), a5 not yet accepted; a2/a3 closed 11-06 and 11-12
        self.assertEqual(rows[('work item age', 'asks')]['n'], '1')
        self.assertEqual(rows[('work item age', 'asks')]['median'], '384')

    def test_no_finished_item_prints_n_a_never_zero(self):
        rows, r = run(period='2026-09')
        self.assertEqual(r.returncode, 0, r.stderr)
        c = rows[('cycle time', 'asks')]
        self.assertEqual([c['n'], c['median'], c['p25'], c['p75']], ['0', 'n/a', 'n/a', 'n/a'])

    def test_flow_efficiency_is_pending_without_the_ledger_output(self):
        f = self.rows[('flow efficiency', 'ledger')]
        self.assertEqual(f['value'], 'pending')

    def test_flow_efficiency_is_one_minus_the_director_waiting_share(self):
        led = [['demo', 'new', 'hub wait (bus polling)', 10, 300], ['demo', 'new', 'director sessions (coordination)', 20, 700],
               ['demo', 'memo', 'hub wait (bus polling)', 10, 999]]
        rows, r = run(ledger=led)
        self.assertEqual(r.returncode, 0, r.stderr)
        f = rows[('flow efficiency', 'ledger')]
        self.assertEqual([f['value'], f['median'], f['n']], ['0.7', '', ''])
        self.assertEqual(f['unit'], 'share of list cost')
        self.assertEqual(f['start_event'], 'n/a (a share, not a duration)')



class Exports(unittest.TestCase):
    def test_a_closed_unmerged_pr_is_excluded_by_number_not_by_creation_time(self):
        # #3 closed unmerged and #5 still open were created in the same second; #5 must still be counted as open
        prs = [{'number': 3, 'state': 'CLOSED', 'createdAt': '2026-11-03T00:00:00Z', 'mergedAt': None, 'closedAt': '2026-11-05T00:00:00Z'},
               {'number': 5, 'state': 'OPEN', 'createdAt': '2026-11-03T00:00:00Z', 'mergedAt': None, 'closedAt': None}]
        rows, r = run(prs=prs)
        self.assertEqual(r.returncode, 0, r.stderr)
        a = rows[('work item age', 'prs')]
        self.assertEqual([a['n'], a['oldest_id']], ['1', '5'])

    def test_an_export_that_holds_exactly_the_gh_limit_is_flagged_as_possibly_truncated(self):
        prs = [{'number': i, 'state': 'MERGED', 'createdAt': '2026-11-01T00:00:00Z', 'mergedAt': '2026-11-01T01:00:00Z',
                'closedAt': '2026-11-01T01:00:00Z'} for i in range(1, 1001)]
        rows, r = run(prs=prs)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('1000', r.stderr)
        self.assertIn('--limit', r.stderr)
        for metric in ('throughput', 'cycle time', 'work item age', 'wip'):
            self.assertIn('PR export holds exactly 1000 rows', rows[(metric, 'prs')]['note'])
        self.assertNotIn('PR export holds', rows[('throughput', 'asks')]['note'])

    def test_a_smaller_export_is_not_flagged(self):
        rows, r = run()
        self.assertEqual(r.stderr, '')
        self.assertNotIn('PR export holds', rows[('throughput', 'prs')]['note'])


class Refusals(unittest.TestCase):
    def test_an_unreadable_asks_file_fails_loudly(self):
        with tempfile.TemporaryDirectory() as d:
            pp = os.path.join(d, 'p.json')
            with open(pp, 'w') as fh:
                fh.write('[]')
            r = subprocess.run([sys.executable, '-I', SCRIPT, d, os.path.join(d, 'nope'), pp, '2026-11', '', ''],
                               capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn('asks', r.stderr)

    def test_a_period_that_is_not_yyyy_mm_is_refused(self):
        _, r = run(period='November')
        self.assertEqual(r.returncode, 2)
        self.assertIn('period', r.stderr)

    def test_the_header_names_the_glossary_the_events_and_the_no_gate_rule(self):
        self.assertTrue(os.path.exists(SCRIPT), 'flow-metrics.py does not exist')
        with open(SCRIPT) as fh:
            head = ''.join(l for l in fh if l.startswith('#'))
        for want in ('glossary.md', 'received_at', 'closed_at', 'createdAt', 'mergedAt', 'diagnostic', 'p25'):
            self.assertIn(want, head)


if __name__ == '__main__':
    unittest.main()

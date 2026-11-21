#!/usr/bin/env python3
# Tests for quota-per-mtok.py, over invented quota readings and an invented daily-tokens.csv. Nothing here reads a real
# home directory or the network.
# Run: python3 -I sim/tools/test_quota_per_mtok.py
# Measure: quota points per million tokens, docs/analysis/glossary.md#quota-points-per-million-tokens
# Design: architect reply of 2026-11-21 (aae-orc-0oejz). A series is (the whole key object, window), compared with ==;
# a rollover is resets_at changing between consecutive readings; points are never summed across accounts; the token
# classes the denominator counts are HELD for an operator ruling, so the script carries no choice: it refuses to run
# without --classes, and each test here passes its own set and computes the expected figure from that same set.
# A set the test picks is an input, not a recommendation.
import csv, json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, 'quota-per-mtok.py')
GLOSSARY = os.path.join(HERE, '..', '..', 'docs', 'analysis', 'glossary.md')
CLASSES = ('uncached_input', 'write_5m', 'write_1h', 'read', 'output')
RESET_A = '2026-11-09T00:00:00Z'
RESET_B = '2026-11-16T00:00:00Z'


def key(home='', backend='subscription', harness='claude', source=''):
    k = {'harness': harness, 'backend': backend}
    if source:
        k['credential_source'] = source
    if home:
        k['config_home'] = home
    return k


def reading(at, pct, home='', window='7d', cluster='demo', resets=RESET_A, backend='subscription'):
    """One line of marvel's account-series day file: {key, sample}. The key is the whole AccountKey."""
    return {'key': key(home, backend),
            'sample': {'cluster': cluster, 'account': 'for-people-only', 'window': window, 'used_percent': pct,
                       'resets_at': resets, 'at': at}}


def tokens_csv(path, rows):
    """rows: (cluster, day, {class: tokens}). total is the sum of the five classes."""
    with open(path, 'w', newline='') as fh:
        w = csv.writer(fh, lineterminator='\n')
        w.writerow(['cluster', 'day'] + list(CLASSES) + ['total'])
        for cluster, day, by in rows:
            vals = [by.get(c, 0) for c in CLASSES]
            w.writerow([cluster, day] + vals + [sum(vals)])


def even(total):
    """A class split in which every class is nonzero, so a denominator that counts the wrong classes shows."""
    q = total // 10
    return {'uncached_input': q, 'write_5m': q, 'write_1h': q, 'read': total - 6 * q, 'output': 3 * q}


def at(d, *keys):
    """Walk keys, failing with an assertion that names the missing key (not a KeyError)."""
    for k in keys:
        assert isinstance(d, dict) and k in d, 'missing key %r in %s' % (k, sorted(d) if isinstance(d, dict) else d)
        d = d[k]
    return d


TEST_CLASSES = ('uncached_input', 'write_5m', 'write_1h', 'output')


def tokens_m(by, classes=TEST_CLASSES):
    return sum(by[c] for c in classes if c in by) / 1e6


def run(lines_by_day, token_rows, extra_lines=(), config_home='', classes=TEST_CLASSES, want_rc=0):
    """lines_by_day: {'2026-11-02': [reading, ...]}; each reading is written to that day's file. extra_lines are raw
    strings added to the first day file (a torn line, for one). config_home is the one the token run read."""
    with tempfile.TemporaryDirectory() as d:
        series = os.path.join(d, 'account-series')
        os.mkdir(series)
        for n, (day, rs) in enumerate(sorted(lines_by_day.items())):
            with open(os.path.join(series, day + '.jsonl'), 'w') as fh:
                for r in rs:
                    fh.write(json.dumps(r) + '\n')
                if n == 0:
                    for raw in extra_lines:
                        fh.write(raw + '\n')
        tk = os.path.join(d, 'daily-tokens.csv')
        tokens_csv(tk, token_rows)
        argv = [sys.executable, '-I', SCRIPT, series, tk, config_home]
        if classes is not None:
            argv += ['--classes', ','.join(classes)]
        r = subprocess.run(argv, capture_output=True, text=True)
        if want_rc is None:
            return r
        assert r.returncode == want_rc, 'quota-per-mtok.py exited %s: %s' % (r.returncode, r.stderr)
        return json.loads(r.stdout)


def account_label(out, cluster='demo'):
    """The one account label of a run with one account."""
    accts = sorted(at(out, 'by_cluster', cluster, 'by_account'))
    assert len(accts) == 1, 'want one account, got %s' % accts
    return accts[0]


def cell(out, cluster='demo', account=None, window='7d'):
    account = account or account_label(out, cluster)
    return at(out, 'by_cluster', cluster, 'by_account', account, 'by_window', window)


def day_row(out, day, **kw):
    rows = [x for x in at(cell(out, **kw), 'days') if x['day'] == day]
    assert len(rows) == 1, 'want one row for %s, got %s' % (day, rows)
    return rows[0]


class Points(unittest.TestCase):
    def test_points_are_the_sum_of_rises_between_consecutive_readings_over_million_tokens(self):
        by = even(2000000)
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10), reading('2026-11-02T02:00:00Z', 15),
                                  reading('2026-11-02T03:00:00Z', 20)]},
                  [('demo', '2026-11-02', by)])
        r = day_row(out, '2026-11-02')
        self.assertEqual(r['points'], 10)
        self.assertAlmostEqual(r['tokens_m'], tokens_m(by))
        self.assertAlmostEqual(r['points_per_mtok'], 10 / tokens_m(by))

    def test_a_change_of_resets_at_is_a_rollover_and_adds_no_points(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 50), reading('2026-11-02T02:00:00Z', 60),
                                  reading('2026-11-02T03:00:00Z', 5, resets=RESET_B),
                                  reading('2026-11-02T04:00:00Z', 15, resets=RESET_B)]},
                  [('demo', '2026-11-02', even(1000000))])
        r = day_row(out, '2026-11-02')
        self.assertEqual((r['points'], r['rollovers'], r['falls']), (20, 1, 0))

    def test_a_reset_followed_by_use_above_the_earlier_reading_is_still_a_rollover_not_a_rise(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 50), reading('2026-11-02T02:00:00Z', 70, resets=RESET_B),
                                  reading('2026-11-02T03:00:00Z', 72, resets=RESET_B)]},
                  [('demo', '2026-11-02', even(1000000))])
        r = day_row(out, '2026-11-02')
        self.assertEqual((r['points'], r['rollovers']), (2, 1))

    def test_a_fall_inside_one_window_adds_no_points_and_is_counted_apart_from_rollovers(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 60), reading('2026-11-02T02:00:00Z', 50),
                                  reading('2026-11-02T03:00:00Z', 55)]},
                  [('demo', '2026-11-02', even(1000000))])
        r = day_row(out, '2026-11-02')
        self.assertEqual((r['points'], r['rollovers'], r['falls']), (5, 0, 1))

    def test_two_accounts_in_one_cluster_are_two_rows_and_are_never_summed(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10, home='/h/a'), reading('2026-11-02T01:30:00Z', 90, home='/h/b'),
                                  reading('2026-11-02T02:00:00Z', 14, home='/h/a'), reading('2026-11-02T02:30:00Z', 93, home='/h/b')]},
                  [('demo', '2026-11-02', even(1000000))], config_home='/h/a')
        accts = sorted(at(out, 'by_cluster', 'demo', 'by_account'))
        self.assertEqual(len(accts), 2)
        pts = {}
        for a in accts:
            pts[a] = at(cell(out, account=a), 'days')[0]['points']
        self.assertEqual(sorted(pts.values()), [3, 4])

    def test_a_series_is_the_whole_key_so_two_backends_on_one_home_are_apart(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10, backend='subscription'),
                                  reading('2026-11-02T01:30:00Z', 40, backend='api'),
                                  reading('2026-11-02T02:00:00Z', 12, backend='subscription'),
                                  reading('2026-11-02T02:30:00Z', 41, backend='api')]},
                  [('demo', '2026-11-02', even(1000000))])
        self.assertEqual(len(at(out, 'by_cluster', 'demo', 'by_account')), 2)

    def test_windows_are_reported_apart(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10, window='7d'), reading('2026-11-02T02:00:00Z', 12, window='7d'),
                                  reading('2026-11-02T01:00:00Z', 40, window='5h'), reading('2026-11-02T02:00:00Z', 50, window='5h')]},
                  [('demo', '2026-11-02', even(1000000))])
        self.assertEqual(day_row(out, '2026-11-02', window='7d')['points'], 2)
        self.assertEqual(day_row(out, '2026-11-02', window='5h')['points'], 10)

    def test_a_rise_across_midnight_belongs_to_the_day_of_the_later_reading(self):
        out = run({'2026-11-02': [reading('2026-11-02T23:00:00Z', 10)],
                   '2026-11-03': [reading('2026-11-03T01:00:00Z', 16)]},
                  [('demo', '2026-11-02', even(1000000)), ('demo', '2026-11-03', even(1000000))])
        self.assertEqual(day_row(out, '2026-11-03')['points'], 6)
        self.assertEqual(day_row(out, '2026-11-02')['points'], 0)


class Denominator(unittest.TestCase):
    def test_the_denominator_counts_exactly_the_classes_the_caller_passes(self):
        by = even(3000000)
        rows = {'2026-11-02': [reading('2026-11-02T01:00:00Z', 10), reading('2026-11-02T02:00:00Z', 16)]}
        for classes in (('read',), ('uncached_input', 'output'), ('uncached_input', 'write_5m', 'write_1h', 'read', 'output')):
            out = run(rows, [('demo', '2026-11-02', by)], classes=classes)
            self.assertAlmostEqual(day_row(out, '2026-11-02')['tokens_m'], tokens_m(by, classes), msg=str(classes))

    def test_the_report_names_the_classes_it_counted(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10), reading('2026-11-02T02:00:00Z', 16)]},
                  [('demo', '2026-11-02', even(1000000))], classes=('read', 'output'))
        self.assertEqual(at(out, 'denominator_classes'), ['read', 'output'])

    def test_without_classes_it_refuses_and_names_the_pending_ruling(self):
        r = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10)]}, [('demo', '2026-11-02', even(1000000))],
                classes=None, want_rc=None)
        self.assertNotEqual(r.returncode, 0, 'a run with no --classes must refuse, not print a report')
        self.assertEqual(r.stdout, '')
        self.assertIn('operator ruling', r.stderr)
        self.assertIn('--classes', r.stderr)

    def test_an_unknown_class_name_is_refused_and_named(self):
        r = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10)]}, [('demo', '2026-11-02', even(1000000))],
                classes=('read', 'cache_reads'), want_rc=None)
        self.assertNotEqual(r.returncode, 0, 'an unknown class name must be refused')
        self.assertIn('cache_reads', r.stderr)

    def test_the_script_header_says_the_class_choice_is_held_for_an_operator_ruling(self):
        self.assertTrue(os.path.exists(SCRIPT), 'quota-per-mtok.py is missing')
        with open(SCRIPT) as fh:
            head = ''.join(l for l in iter(lambda: fh.readline(), '') if l.startswith('#')).lower()
        self.assertIn('--classes', head)
        self.assertIn('operator ruling', head)


class Pairing(unittest.TestCase):
    def test_a_cell_whose_config_home_is_not_the_token_runs_prints_n_a_with_a_note(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10, home='/h/other'),
                                  reading('2026-11-02T02:00:00Z', 15, home='/h/other')]},
                  [('demo', '2026-11-02', even(1000000))], config_home='/h/mine')
        r = day_row(out, '2026-11-02')
        self.assertEqual(r['points_per_mtok'], 'n/a')
        self.assertIn('config home', at(cell(out), 'note'))

    def test_a_cell_whose_config_home_is_the_token_runs_is_computed(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10, home='/h/mine'),
                                  reading('2026-11-02T02:00:00Z', 15, home='/h/mine')]},
                  [('demo', '2026-11-02', even(1000000))], config_home='/h/mine')
        self.assertNotEqual(day_row(out, '2026-11-02')['points_per_mtok'], 'n/a')


class Gaps(unittest.TestCase):
    def test_a_day_with_tokens_and_no_readings_prints_n_a_not_zero(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10), reading('2026-11-02T02:00:00Z', 12)]},
                  [('demo', '2026-11-02', even(1000000)), ('demo', '2026-11-03', even(1000000))])
        r = day_row(out, '2026-11-03')
        self.assertEqual(r['points_per_mtok'], 'n/a')
        self.assertNotIn(r['points_per_mtok'], (0, 0.0))

    def test_a_day_with_readings_and_no_tokens_prints_n_a_not_a_division_error(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10), reading('2026-11-02T02:00:00Z', 12)]},
                  [('demo', '2026-11-03', even(1000000))])
        self.assertEqual(day_row(out, '2026-11-02')['points_per_mtok'], 'n/a')

    def test_a_single_reading_in_a_series_gives_no_points_to_divide(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10)]}, [('demo', '2026-11-02', even(1000000))])
        self.assertEqual(day_row(out, '2026-11-02')['points_per_mtok'], 'n/a')

    def test_a_torn_line_is_skipped_and_counted_and_does_not_stop_the_run(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10), reading('2026-11-02T02:00:00Z', 12)]},
                  [('demo', '2026-11-02', even(1000000))], extra_lines=['{"key": {"harness": "claude", "acco'])
        self.assertEqual(at(out, 'skipped_lines'), 1)
        self.assertEqual(day_row(out, '2026-11-02')['points'], 2)


class Statistics(unittest.TestCase):
    def three_days(self):
        days = {}
        for day, step in (('2026-11-02', 1), ('2026-11-03', 2), ('2026-11-04', 3)):
            days[day] = [reading(day + 'T01:00:00Z', 0), reading(day + 'T02:00:00Z', step)]
        return run(days, [('demo', d, even(1000000)) for d in days])

    def test_the_cell_figure_is_n_median_p25_p75_over_days(self):
        out = self.three_days()
        c = cell(out)
        t = tokens_m(even(1000000))
        self.assertEqual(c['n'], 3)
        self.assertAlmostEqual(c['median'], 2 / t)
        self.assertAlmostEqual(c['p25'], 1.5 / t)
        self.assertAlmostEqual(c['p75'], 2.5 / t)

    def test_no_mean_is_printed_anywhere(self):
        rep = self.three_days()
        self.assertEqual(cell(rep)['n'], 3)
        out = json.dumps(rep).lower()
        for banned in ('mean', 'average', 'avg'):
            self.assertNotIn(banned, out)

    def test_nothing_is_grouped_by_seat_or_session(self):
        rep = self.three_days()
        self.assertEqual(cell(rep)['n'], 3)
        out = json.dumps(rep).lower()
        for banned in ('session', 'seat'):
            self.assertNotIn(banned, out)

    def test_no_cluster_sum_is_printed(self):
        rep = self.three_days()
        self.assertEqual(cell(rep)['n'], 3)
        self.assertNotIn('days', at(rep, 'by_cluster', 'demo'))
        self.assertNotIn('points', at(rep, 'by_cluster', 'demo'))

    def test_a_cell_with_no_usable_day_prints_n_zero_and_n_a_statistics(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10)]}, [('demo', '2026-11-02', even(1000000))])
        c = cell(out)
        self.assertEqual((c['n'], c['median'], c['p25'], c['p75']), (0, 'n/a', 'n/a', 'n/a'))


class Documented(unittest.TestCase):
    def test_the_header_cites_the_glossary_and_says_diagnostic_never_a_gate(self):
        self.assertTrue(os.path.exists(SCRIPT), 'quota-per-mtok.py is missing')
        with open(SCRIPT) as fh:
            head = ''.join(l for l in iter(lambda: fh.readline(), '') if l.startswith('#'))
        for want in ('glossary.md#quota-points-per-million-tokens', 'ADR-007', 'diagnostic', 'never a gate'):
            self.assertIn(want, head)

    def test_the_glossary_defines_the_term_with_its_events_and_pairing(self):
        with open(GLOSSARY) as fh:
            g = fh.read()
        self.assertIn('## quota points per million tokens', g)
        body = g.split('## quota points per million tokens', 1)[1].split('\n## ', 1)[0].lower()
        for want in ('used_percent', 'window', 'resets_at', 'rollover', 'median', 'daily-tokens.csv', 'config home'):
            self.assertIn(want, body)


if __name__ == '__main__':
    unittest.main()

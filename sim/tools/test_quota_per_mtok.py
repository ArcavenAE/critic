#!/usr/bin/env python3
# Tests for quota-per-mtok.py, over invented quota readings and an invented daily-tokens.csv. Nothing here reads a real
# home directory or the network.
# Run: python3 -I sim/tools/test_quota_per_mtok.py
# Measure: quota points per million tokens, docs/analysis/glossary.md#quota-points-per-million-tokens
import csv, json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, 'quota-per-mtok.py')
GLOSSARY = os.path.join(HERE, '..', '..', 'docs', 'analysis', 'glossary.md')


def reading(at, pct, account='acct-a', window='7d', cluster='demo'):
    """One line of marvel's account-series day file: {key, sample}."""
    return {'key': {'cluster': cluster, 'account': account, 'window': window},
            'sample': {'cluster': cluster, 'account': account, 'window': window, 'used_percent': pct, 'at': at}}


def tokens_csv(path, rows):
    """rows: (cluster, day, total tokens). The four class columns are filled so that they add up to the total."""
    with open(path, 'w', newline='') as fh:
        w = csv.writer(fh, lineterminator='\n')
        w.writerow(['cluster', 'day', 'input', 'cache_write', 'cache_read', 'output', 'total'])
        for cluster, day, total in rows:
            w.writerow([cluster, day, 0, 0, total - 1, 1, total])


def at(d, *keys):
    """Walk keys, failing with an assertion that names the missing key (not a KeyError)."""
    for k in keys:
        assert isinstance(d, dict) and k in d, 'missing key %r in %s' % (k, sorted(d) if isinstance(d, dict) else d)
        d = d[k]
    return d


def run(lines_by_day, token_rows, extra_lines=()):
    """lines_by_day: {'2026-11-02': [reading, ...]}; each reading is written to that day's file. extra_lines are raw
    strings added to the first day file (a torn line, for one)."""
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
        r = subprocess.run([sys.executable, '-I', SCRIPT, series, tk], capture_output=True, text=True)
        assert r.returncode == 0, 'quota-per-mtok.py exited %s: %s' % (r.returncode, r.stderr)
        return json.loads(r.stdout)


def day_row(out, day, cluster='demo', window='7d'):
    rows = [x for x in at(out, 'by_cluster', cluster, 'by_window', window, 'days') if x['day'] == day]
    assert len(rows) == 1, 'want one row for %s, got %s' % (day, rows)
    return rows[0]


class Points(unittest.TestCase):
    def test_points_are_the_sum_of_rises_between_consecutive_readings_over_million_tokens(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10), reading('2026-11-02T02:00:00Z', 15),
                                  reading('2026-11-02T03:00:00Z', 20)]},
                  [('demo', '2026-11-02', 2000000)])
        r = day_row(out, '2026-11-02')
        self.assertEqual((r['points'], r['tokens_m'], r['points_per_mtok']), (10, 2.0, 5.0))

    def test_a_drop_is_a_window_reset_and_adds_no_points_but_is_counted(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 50), reading('2026-11-02T02:00:00Z', 60),
                                  reading('2026-11-02T03:00:00Z', 5), reading('2026-11-02T04:00:00Z', 15)]},
                  [('demo', '2026-11-02', 1000000)])
        r = day_row(out, '2026-11-02')
        self.assertEqual((r['points'], r['rollovers']), (20, 1))

    def test_two_accounts_in_one_cluster_add_and_a_series_is_never_joined_across_accounts(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10, 'acct-a'), reading('2026-11-02T01:30:00Z', 90, 'acct-b'),
                                  reading('2026-11-02T02:00:00Z', 14, 'acct-a'), reading('2026-11-02T02:30:00Z', 93, 'acct-b')]},
                  [('demo', '2026-11-02', 1000000)])
        self.assertEqual(day_row(out, '2026-11-02')['points'], 7)

    def test_windows_are_reported_apart(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10, window='7d'), reading('2026-11-02T02:00:00Z', 12, window='7d'),
                                  reading('2026-11-02T01:00:00Z', 40, window='5h'), reading('2026-11-02T02:00:00Z', 50, window='5h')]},
                  [('demo', '2026-11-02', 1000000)])
        self.assertEqual(day_row(out, '2026-11-02', window='7d')['points'], 2)
        self.assertEqual(day_row(out, '2026-11-02', window='5h')['points'], 10)

    def test_a_rise_across_midnight_belongs_to_the_day_of_the_later_reading(self):
        out = run({'2026-11-02': [reading('2026-11-02T23:00:00Z', 10)],
                   '2026-11-03': [reading('2026-11-03T01:00:00Z', 16)]},
                  [('demo', '2026-11-02', 1000000), ('demo', '2026-11-03', 1000000)])
        self.assertEqual(day_row(out, '2026-11-03')['points'], 6)
        self.assertEqual(day_row(out, '2026-11-02')['points'], 0)


class Gaps(unittest.TestCase):
    def test_a_day_with_tokens_and_no_readings_prints_n_a_not_zero(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10), reading('2026-11-02T02:00:00Z', 12)]},
                  [('demo', '2026-11-02', 1000000), ('demo', '2026-11-03', 1000000)])
        r = day_row(out, '2026-11-03')
        self.assertEqual(r['points_per_mtok'], 'n/a')
        self.assertNotIn(r['points_per_mtok'], (0, 0.0))

    def test_a_day_with_readings_and_no_tokens_prints_n_a_not_a_division_error(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10), reading('2026-11-02T02:00:00Z', 12)]},
                  [('demo', '2026-11-03', 1000000)])
        self.assertEqual(day_row(out, '2026-11-02')['points_per_mtok'], 'n/a')

    def test_a_single_reading_in_a_series_gives_no_points_to_divide(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10)]}, [('demo', '2026-11-02', 1000000)])
        self.assertEqual(day_row(out, '2026-11-02')['points_per_mtok'], 'n/a')

    def test_a_torn_line_is_skipped_and_counted_and_does_not_stop_the_run(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10), reading('2026-11-02T02:00:00Z', 12)]},
                  [('demo', '2026-11-02', 1000000)], extra_lines=['{"key": {"cluster": "demo", "acco'])
        self.assertEqual(at(out, 'skipped_lines'), 1)
        self.assertEqual(day_row(out, '2026-11-02')['points'], 2)


class Statistics(unittest.TestCase):
    def three_days(self):
        days = {}
        for n, (day, step) in enumerate((('2026-11-02', 1), ('2026-11-03', 2), ('2026-11-04', 3))):
            days[day] = [reading(day + 'T01:00:00Z', 0), reading(day + 'T02:00:00Z', step)]
        return run(days, [('demo', d, 1000000) for d in days])

    def test_the_window_figure_is_n_median_p25_p75_over_days(self):
        w = at(self.three_days(), 'by_cluster', 'demo', 'by_window', '7d')
        self.assertEqual((w['n'], w['median'], w['p25'], w['p75']), (3, 2.0, 1.5, 2.5))

    def test_no_mean_is_printed_anywhere(self):
        rep = self.three_days()
        at(rep, 'by_cluster', 'demo', 'by_window', '7d', 'median')
        out = json.dumps(rep).lower()
        self.assertNotIn('mean', out)
        self.assertNotIn('average', out)
        self.assertNotIn('avg', out)

    def test_nothing_is_grouped_by_seat_or_session(self):
        rep = self.three_days()
        at(rep, 'by_cluster', 'demo', 'by_window', '7d', 'median')
        out = json.dumps(rep).lower()
        for banned in ('session', 'seat'):
            self.assertNotIn(banned, out)

    def test_a_window_with_no_usable_day_prints_n_zero_and_n_a_statistics(self):
        out = run({'2026-11-02': [reading('2026-11-02T01:00:00Z', 10)]}, [('demo', '2026-11-02', 1000000)])
        w = at(out, 'by_cluster', 'demo', 'by_window', '7d')
        self.assertEqual((w['n'], w['median'], w['p25'], w['p75']), (0, 'n/a', 'n/a', 'n/a'))


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
        for want in ('used_percent', 'window', 'reset', 'median', 'daily-tokens.csv'):
            self.assertIn(want, body)


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
# Tests for fix-rates.py, over invented PRs and bd tickets. Nothing here reads a real home directory or the network.
# Run: python3 -I sim/tools/test_fix_rates.py
# Measures: change fail rate and rework rate, docs/analysis/glossary.md#change-fail-rate and #rework-rate
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, 'fix-rates.py')


def pr(n, merged_at, text='', repo='demo/alpha'):
    return {'repo': repo, 'number': n, 'mergedAt': merged_at, 'text': text, 'author': 'someone-seat-g1-0'}


def at(d, *keys):
    """Walk keys, failing with an assertion that names the missing key (not a KeyError)."""
    for k in keys:
        assert isinstance(d, dict) and k in d, 'missing key %r in %s' % (k, sorted(d) if isinstance(d, dict) else d)
        d = d[k]
    return d


def P(out, repo='demo/alpha'):
    return at(out, 'by_repo', repo, 'by_period')


def run(prs, bugs=(), *extra):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'in.json')
        with open(p, 'w') as f:
            json.dump({'prs': prs, 'bd_issues': [{'id': i, 'issue_type': t} for i, t in bugs]}, f)
        r = subprocess.run([sys.executable, '-I', SCRIPT, p] + list(extra), capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)


class ChangeFail(unittest.TestCase):
    def test_a_change_later_fixed_by_a_fix_pr_counts_as_failed(self):
        out = run([pr(1, '2026-11-01T10:00:00Z'), pr(2, '2026-11-02T10:00:00Z'),
                   pr(3, '2026-11-05T10:00:00Z', 'Fixes-PR: demo/alpha#1')])
        m = P(out)['2026-11']
        self.assertEqual(m['throughput'], 3)
        self.assertEqual(m['change_fail'], {'numerator': 1, 'denominator': 3, 'rate': 1 / 3})

    def test_the_fix_may_land_in_a_later_period(self):
        out = run([pr(1, '2026-10-28T10:00:00Z'), pr(3, '2026-11-02T10:00:00Z', 'Fixes-PR: demo/alpha#1')])
        self.assertEqual(P(out)['2026-10']['change_fail']['numerator'], 1)
        self.assertEqual(P(out)['2026-11']['change_fail']['numerator'], 0)

    def test_two_fixes_of_one_change_count_it_once(self):
        out = run([pr(1, '2026-11-01T10:00:00Z'),
                   pr(2, '2026-11-02T10:00:00Z', 'Fixes-PR: demo/alpha#1'),
                   pr(3, '2026-11-03T10:00:00Z', 'Fixes-PR: demo/alpha#1')])
        self.assertEqual(P(out)['2026-11']['change_fail']['numerator'], 1)

    def test_an_unmerged_fix_pr_does_not_count(self):
        out = run([pr(1, '2026-11-01T10:00:00Z'), pr(2, None, 'Fixes-PR: demo/alpha#1')])
        self.assertEqual(P(out)['2026-11']['change_fail']['numerator'], 0)
        self.assertEqual(P(out)['2026-11']['throughput'], 1)

    def test_the_trailer_must_start_a_line(self):
        out = run([pr(1, '2026-11-01T10:00:00Z'),
                   pr(2, '2026-11-02T10:00:00Z', 'quoting "Fixes-PR: demo/alpha#1" in prose')])
        self.assertEqual(P(out)['2026-11']['change_fail']['numerator'], 0)

    def test_a_trailer_naming_a_pr_outside_the_input_is_counted_as_unresolved(self):
        out = run([pr(2, '2026-11-02T10:00:00Z', 'Fixes-PR: demo/other#9')])
        self.assertEqual(out['unresolved_links'], 1)
        self.assertEqual(P(out)['2026-11']['change_fail']['numerator'], 0)

    def test_a_fix_merged_before_its_target_does_not_fail_it(self):
        out = run([pr(1, '2026-11-05T10:00:00Z'), pr(2, '2026-11-01T10:00:00Z', 'Fixes-PR: demo/alpha#1')])
        self.assertEqual(P(out)['2026-11']['change_fail']['numerator'], 0)


class Rework(unittest.TestCase):
    def test_a_fix_pr_is_rework(self):
        out = run([pr(1, '2026-11-01T10:00:00Z'), pr(2, '2026-11-02T10:00:00Z', 'Fixes-PR: demo/alpha#1')])
        self.assertEqual(P(out)['2026-11']['rework'], {'numerator': 1, 'denominator': 2, 'rate': 0.5})

    def test_a_pr_that_closes_a_bug_ticket_is_rework(self):
        out = run([pr(1, '2026-11-01T10:00:00Z', 'Closes: aae-orc-bug01'),
                   pr(2, '2026-11-02T10:00:00Z', 'Closes: aae-orc-task1')],
                  bugs=[('aae-orc-bug01', 'bug'), ('aae-orc-task1', 'task')])
        self.assertEqual(P(out)['2026-11']['rework']['numerator'], 1)

    def test_refs_to_a_bug_ticket_is_not_rework(self):
        out = run([pr(1, '2026-11-01T10:00:00Z', 'Refs: aae-orc-bug01')], bugs=[('aae-orc-bug01', 'bug')])
        self.assertEqual(P(out)['2026-11']['rework']['numerator'], 0)

    def test_a_pr_that_is_both_a_fix_pr_and_closes_a_bug_counts_once(self):
        out = run([pr(1, '2026-11-01T10:00:00Z'),
                   pr(2, '2026-11-02T10:00:00Z', 'Fixes-PR: demo/alpha#1\nCloses: aae-orc-bug01')],
                  bugs=[('aae-orc-bug01', 'bug')])
        self.assertEqual(P(out)['2026-11']['rework']['numerator'], 1)


class Grouping(unittest.TestCase):
    def test_figures_are_grouped_by_repo_not_pooled(self):
        out = run([pr(1, '2026-11-01T10:00:00Z'), pr(2, '2026-11-02T10:00:00Z', 'Fixes-PR: demo/alpha#1'),
                   pr(3, '2026-11-01T10:00:00Z', repo='demo/beta')])
        self.assertEqual(P(out, 'demo/alpha')['2026-11']['throughput'], 2)
        self.assertEqual(P(out, 'demo/beta')['2026-11']['throughput'], 1)
        self.assertEqual(P(out, 'demo/beta')['2026-11']['change_fail']['numerator'], 0)

    def test_a_fix_in_another_repo_counts_against_its_target_repo(self):
        out = run([pr(1, '2026-11-01T10:00:00Z'), pr(2, '2026-11-02T10:00:00Z', 'Fixes-PR: demo/alpha#1', repo='demo/beta')])
        self.assertEqual(P(out, 'demo/alpha')['2026-11']['change_fail']['numerator'], 1)
        self.assertEqual(P(out, 'demo/beta')['2026-11']['rework']['numerator'], 1)

    def test_there_is_no_pooled_fleet_wide_figure(self):
        self.assertNotIn('by_period', run([pr(1, '2026-11-01T10:00:00Z')]))

    def test_the_unit_waits_on_a_role_and_team_key_and_says_so(self):
        self.assertIn('role and team', at(run([]), 'grouped_by_note'))


class Unmeasured(unittest.TestCase):
    def test_trailers_seen_tells_a_clean_month_from_an_unmeasured_one(self):
        out = run([pr(1, '2026-11-01T10:00:00Z'), pr(2, '2026-11-02T10:00:00Z')])
        self.assertEqual(at(P(out)['2026-11'], 'fix_trailers_seen'), 0)
        out = run([pr(1, '2026-11-01T10:00:00Z'), pr(2, '2026-11-02T10:00:00Z', 'Fixes-PR: demo/alpha#1')])
        self.assertEqual(at(P(out)['2026-11'], 'fix_trailers_seen'), 1)

    def test_bug_closes_seen_is_counted_beside_it(self):
        out = run([pr(1, '2026-11-01T10:00:00Z', 'Closes: aae-orc-bug01')], bugs=[('aae-orc-bug01', 'bug')])
        self.assertEqual(at(P(out)['2026-11'], 'bug_closes_seen'), 1)


class Period(unittest.TestCase):
    def test_week_periods_are_available_so_throughput_can_be_read_weekly(self):
        out = run([pr(1, '2026-11-02T10:00:00Z'), pr(2, '2026-11-04T10:00:00Z'), pr(3, '2026-11-10T10:00:00Z')], (), 'week')
        self.assertEqual(P(out)['2026-W45']['throughput'], 2)
        self.assertEqual(P(out)['2026-W46']['throughput'], 1)

    def test_an_unknown_period_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'in.json')
            json.dump({'prs': [], 'bd_issues': []}, open(p, 'w'))
            r = subprocess.run([sys.executable, '-I', SCRIPT, p, 'fortnight'], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('period', r.stderr)


class Reporting(unittest.TestCase):
    def test_throughput_prints_beside_both_rates(self):
        m = P(run([pr(1, '2026-11-01T10:00:00Z')]))['2026-11']
        self.assertEqual(m['throughput'], 1)
        self.assertIn('change_fail', m)
        self.assertIn('rework', m)

    def test_rate_is_none_when_no_change_merged_in_the_period(self):
        out = run([])
        self.assertEqual(at(out, 'by_repo'), {})

    def test_never_names_an_author(self):
        out = run([pr(1, '2026-11-01T10:00:00Z')])
        self.assertNotIn('someone-seat-g1-0', json.dumps(out))

    def test_reports_counts_never_a_mean(self):
        m = P(run([pr(1, '2026-11-01T10:00:00Z')]))['2026-11']
        self.assertNotIn('mean', json.dumps(m))


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
# Tests for revision-rounds.py, over invented PR records. Nothing here reads a real home directory or the network.
# Run: python3 -I sim/tools/test_revision_rounds.py
# Measure: human revision cost, docs/analysis/glossary.md#human-revision-cost
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, 'revision-rounds.py')


def review(ts, state='COMMENTED', body=''):
    return {'state': state, 'submittedAt': ts, 'body': body}


def pr(n, reviews, commits, merged=True, repo='demo/alpha'):
    return {'repo': repo, 'number': n, 'merged': merged, 'author': 'someone-seat-g1-0',
            'reviews': reviews, 'commits': [{'committedDate': c} for c in commits]}


def run(prs):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'prs.json')
        with open(p, 'w') as f:
            json.dump(prs, f)
        r = subprocess.run([sys.executable, '-I', SCRIPT, p], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)


def by_number(out, n):
    return [x for x in out['prs'] if x['number'] == n][0]


class Rounds(unittest.TestCase):
    def test_merged_as_is_has_zero_rounds(self):
        out = run([pr(1, [review('2026-11-01T10:00:00Z', body='Verdict: PASS')], ['2026-11-01T09:00:00Z'])])
        self.assertEqual(by_number(out, 1)['rounds'], 0)
        self.assertEqual(by_number(out, 1)['commits_after_first_review'], 0)

    def test_not_yet_comment_then_commit_is_one_round(self):
        out = run([pr(2, [review('2026-11-01T10:00:00Z', body='Looks close.\nVerdict: NOT YET\nfix x'),
                          review('2026-11-01T12:00:00Z', body='Verdict: PASS')],
                      ['2026-11-01T09:00:00Z', '2026-11-01T11:00:00Z'])])
        self.assertEqual(by_number(out, 2)['rounds'], 1)
        self.assertEqual(by_number(out, 2)['commits_after_first_review'], 1)

    def test_changes_requested_state_counts_without_a_verdict_line(self):
        out = run([pr(3, [review('2026-11-01T10:00:00Z', state='CHANGES_REQUESTED'),
                          review('2026-11-01T12:00:00Z', state='CHANGES_REQUESTED'),
                          review('2026-11-01T14:00:00Z', body='Verdict: PASS')],
                      ['2026-11-01T09:00:00Z', '2026-11-01T11:00:00Z', '2026-11-01T13:00:00Z'])])
        self.assertEqual(by_number(out, 3)['rounds'], 2)

    def test_two_revision_reviews_with_no_commit_between_are_one_round(self):
        out = run([pr(4, [review('2026-11-01T10:00:00Z', body='Verdict: NOT YET'),
                          review('2026-11-01T10:30:00Z', body='Verdict: NOT YET'),
                          review('2026-11-01T12:00:00Z', body='Verdict: PASS')],
                      ['2026-11-01T09:00:00Z', '2026-11-01T11:00:00Z'])])
        self.assertEqual(by_number(out, 4)['rounds'], 1)

    def test_verdict_must_start_a_line(self):
        out = run([pr(5, [review('2026-11-01T10:00:00Z', body='The author wrote "Verdict: NOT YET" in a quote'),
                          review('2026-11-01T12:00:00Z', body='Verdict: PASS')],
                      ['2026-11-01T09:00:00Z', '2026-11-01T11:00:00Z'])])
        self.assertEqual(by_number(out, 5)['rounds'], 0)
        self.assertEqual(by_number(out, 5)['commits_after_first_review'], 1)

    def test_a_not_yet_with_no_later_commit_is_not_a_round(self):
        out = run([pr(6, [review('2026-11-01T10:00:00Z', body='Verdict: NOT YET')], ['2026-11-01T09:00:00Z'])])
        self.assertEqual(by_number(out, 6)['rounds'], 0)


class Summary(unittest.TestCase):
    def prs(self):
        def p(n, rounds, merged=True):
            revs, commits = [], ['2026-11-01T08:00:00Z']
            for i in range(rounds):
                revs.append(review('2026-11-01T%02d:00:00Z' % (10 + 2 * i), body='Verdict: NOT YET'))
                commits.append('2026-11-01T%02d:30:00Z' % (10 + 2 * i))
            revs.append(review('2026-11-01T23:00:00Z', body='Verdict: PASS'))
            return pr(n, revs, commits, merged=merged)
        return [p(1, 0), p(2, 0), p(3, 1), p(4, 2), p(5, 3), p(6, 9, merged=False)]

    def test_median_p25_p75_and_n_over_merged_prs(self):
        s = run(self.prs())['summary']['rounds']
        self.assertEqual((s['median'], s['p25'], s['p75'], s['n']), (1, 0, 2, 5))

    def test_no_mean_is_reported(self):
        s = run(self.prs())['summary']['rounds']
        self.assertNotIn('mean', s)

    def test_throughput_is_printed_beside_the_revision_figures(self):
        s = run(self.prs())['summary']
        self.assertEqual(s['throughput_merged'], 5)
        self.assertEqual(s['merged_as_is'], 2)
        self.assertEqual(s['merged_after_revision'], 3)
        self.assertEqual(s['closed_unmerged'], 1)

    def test_unmerged_prs_stay_out_of_the_distribution(self):
        out = run(self.prs())
        self.assertEqual(out['summary']['rounds']['n'], 5)
        self.assertEqual(by_number(out, 6)['rounds'], 9)

    def test_groups_by_repo_and_never_names_an_author(self):
        prs = self.prs()
        prs[0]['repo'] = 'demo/beta'
        out = run(prs)
        self.assertEqual(sorted(out['by_repo']), ['demo/alpha', 'demo/beta'])
        self.assertNotIn('someone-seat-g1-0', json.dumps(out))

    def test_empty_input_reports_n_zero_and_no_figures(self):
        s = run([])['summary']
        self.assertEqual(s['rounds']['n'], 0)
        self.assertIsNone(s['rounds']['median'])
        self.assertEqual(s['throughput_merged'], 0)


if __name__ == '__main__':
    unittest.main()

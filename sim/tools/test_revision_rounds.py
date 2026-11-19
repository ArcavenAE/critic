#!/usr/bin/env python3
# Tests for revision-rounds.py, over invented PR records. Nothing here reads a real home directory or the network.
# Run: python3 -I sim/tools/test_revision_rounds.py
# Measure: human revision cost, docs/analysis/glossary.md#human-revision-cost
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, 'revision-rounds.py')


def review(ts, state='COMMENTED', body=''):
    return {'state': state, 'submittedAt': ts, 'body': body}


def pr(n, reviews, commits, merged=True, repo='demo/alpha', state=None):
    if state is None:
        state = 'MERGED' if merged else 'CLOSED'
    return {'repo': repo, 'number': n, 'merged': merged, 'state': state, 'author': 'someone-seat-g1-0',
            'reviews': reviews,
            'commits': [c if isinstance(c, dict) else {'committedDate': c} for c in commits]}


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

    def test_markdown_and_trailing_forms_of_the_verdict_count(self):
        bodies = ['**Verdict: NOT YET** at abc1234', 'NOT YET at abc1234', '> **Verdict:** NOT YET', '## Verdict: not yet',
                  'Summary first.\n\n- **Verdict: NOT YET** at abc1234']
        for i, b in enumerate(bodies):
            n = 20 + i
            out = run([pr(n, [review('2026-11-01T10:00:00Z', body=b), review('2026-11-01T12:00:00Z', body='Verdict: PASS')],
                          ['2026-11-01T09:00:00Z', '2026-11-01T11:00:00Z'])])
            self.assertEqual(by_number(out, n)['rounds'], 1, b)

    def test_prose_that_only_mentions_not_yet_does_not_count(self):
        for i, b in enumerate(['This is not yet covered by a test.', 'Not yet implemented, per the author.',
                               'PASS at abc1234; the NOT YET from earlier is resolved']):
            n = 30 + i
            out = run([pr(n, [review('2026-11-01T10:00:00Z', body=b)], ['2026-11-01T09:00:00Z', '2026-11-01T11:00:00Z'])])
            self.assertEqual(by_number(out, n)['rounds'], 0, b)

    def test_the_verdict_shapes_in_use_in_the_fleet_count(self):
        # Opening lines of two fleet reviews, as posted on kos#216 and kos#213, with the commit hashes shortened.
        bodies = ['**Verdict: NOT YET** at `fc6b8b88140e`. I read the full diff against the head and ran the new tests.',
                  'NOT YET at 77fb6636. SI-8 is the probe\'s hardest-won lesson, so its refusal has to hold up.']
        for i, b in enumerate(bodies):
            n = 40 + i
            out = run([pr(n, [review('2026-11-01T10:00:00Z', body=b)], ['2026-11-01T09:00:00Z', '2026-11-01T11:00:00Z'])])
            self.assertEqual(by_number(out, n)['rounds'], 1, b)

    def test_a_base_merge_after_a_not_yet_is_not_the_answering_commit(self):
        merge = {'committedDate': '2026-11-01T11:00:00Z', 'messageHeadline': "Merge branch 'main' into build/x"}
        out = run([pr(50, [review('2026-11-01T10:00:00Z', body='Verdict: NOT YET')], ['2026-11-01T09:00:00Z', merge])])
        self.assertEqual(by_number(out, 50)['rounds'], 0)

    def test_a_merge_commit_with_two_parents_is_not_the_answering_commit(self):
        merge = {'committedDate': '2026-11-01T11:00:00Z', 'messageHeadline': 'sync', 'parents': ['a', 'b']}
        out = run([pr(51, [review('2026-11-01T10:00:00Z', body='Verdict: NOT YET')], ['2026-11-01T09:00:00Z', merge])])
        self.assertEqual(by_number(out, 51)['rounds'], 0)

    def test_the_real_fix_after_a_base_merge_is_the_answering_commit(self):
        merge = {'committedDate': '2026-11-01T11:00:00Z', 'messageHeadline': "Merge branch 'main' into build/x"}
        out = run([pr(52, [review('2026-11-01T10:00:00Z', body='Verdict: NOT YET')],
                      ['2026-11-01T09:00:00Z', merge, '2026-11-01T12:00:00Z'])])
        self.assertEqual(by_number(out, 52)['rounds'], 1)


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
        s = run(self.prs())['summary']['throughput']['instability']['rounds']
        self.assertEqual((s['median'], s['p25'], s['p75'], s['n']), (1, 0, 2, 5))

    def test_no_mean_is_reported(self):
        self.assertNotIn('mean', json.dumps(run(self.prs())['summary']))

    def test_throughput_is_printed_beside_the_revision_figures(self):
        s = run(self.prs())['summary']
        self.assertEqual(s['closed_unmerged'], 1)

    def test_unmerged_prs_stay_out_of_the_distribution(self):
        out = run(self.prs())
        self.assertEqual(out['summary']['throughput']['instability']['rounds']['n'], 5)
        self.assertEqual(by_number(out, 6)['rounds'], 9)

    def test_throughput_sits_in_one_object_with_its_instability_measure(self):
        pair = run(self.prs())['summary']['throughput']
        self.assertEqual(pair['merged'], 5)
        self.assertEqual(pair['instability']['rounds']['median'], 1)
        self.assertEqual(pair['instability']['merged_after_revision'], 3)
        self.assertEqual(pair['instability']['share_after_revision'], 0.6)
        self.assertEqual(pair['instability']['merged_as_is'], 2)

    def test_every_repo_group_carries_the_same_pairing(self):
        by = run(self.prs())['by_repo']['demo/alpha']
        self.assertEqual(by['throughput']['merged'], 5)
        self.assertIn('rounds', by['throughput']['instability'])

    def test_no_bare_throughput_count_outside_the_pairing(self):
        s = run(self.prs())['summary']
        self.assertNotIn('throughput_merged', s)
        self.assertNotIn('merged_as_is', s)
        self.assertNotIn('merged_after_revision', s)

    def test_an_open_pr_is_not_counted_as_closed_unmerged(self):
        prs = self.prs() + [pr(7, [], ['2026-11-01T08:00:00Z'], merged=False, state='OPEN')]
        s = run(prs)['summary']
        self.assertEqual(s['closed_unmerged'], 1)
        self.assertEqual(s['open'], 1)

    def test_a_non_merged_pr_with_no_state_is_reported_as_unknown_not_closed(self):
        p = pr(8, [], [], merged=False)
        del p['state']
        s = run(self.prs()[:1] + [p])['summary']
        self.assertEqual(s['closed_unmerged'], 0)
        self.assertEqual(s['state_unknown'], 1)

    def test_share_merged_with_zero_rounds_is_reported(self):
        i = run(self.prs())['summary']['throughput']['instability']
        self.assertEqual(i['share_as_is'], 0.4)

    def test_groups_by_repo_and_never_names_an_author(self):
        prs = self.prs()
        prs[0]['repo'] = 'demo/beta'
        out = run(prs)
        self.assertEqual(sorted(out['by_repo']), ['demo/alpha', 'demo/beta'])
        self.assertNotIn('someone-seat-g1-0', json.dumps(out))

    def test_empty_input_reports_n_zero_and_no_figures(self):
        s = run([])['summary']['throughput']
        self.assertEqual(s['instability']['rounds']['n'], 0)
        self.assertIsNone(s['instability']['rounds']['median'])
        self.assertIsNone(s['instability']['share_after_revision'])
        self.assertEqual(s['merged'], 0)


if __name__ == '__main__':
    unittest.main()

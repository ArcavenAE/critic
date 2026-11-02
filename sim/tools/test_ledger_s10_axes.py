#!/usr/bin/env python3
# Tests for ledger-s10-axes.py. Runs the script end to end over invented transcripts, an invented map and an
# invented marvel log, so nothing here reads a real home directory.
# Run: python3 -I sim/tools/test_ledger_s10_axes.py
import csv, gzip, json, os, subprocess, sys, tempfile, unittest, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, 'ledger-s10-axes.py')
MODEL = 'demo-model'
PRICES = {MODEL: {'in': 10000, 'cw5': 10000, 'cw1': 10000, 'cr': 10000, 'out': 10000}}
MAP = [('kind', 'match', 'value', 'note'),
       ('own', '^/srv/demo-own/', '', ''),
       ('own_skill', 'demo-coach', '', ''),
       ('orchestrator', '^/srv/demo-orch/', 'demo-orch', '')]

# label -> (team, role, activity); the role parser table from the I-119 spec.
TABLE = [
    ('reviewer-reviewer-claude-g17-0', 'reviewer', 'reviewer', 'review'),
    ('acme-reviewer-reviewer-claude-g24-0', 'acme', 'reviewer', 'review'),
    ('reviewer-reviewer-codex-g3-0', 'reviewer', 'reviewer', 'review'),
    ('reviewer-reviewer-opencode-g1-0', 'reviewer', 'reviewer', 'review'),
    ('reviewer-reviewer-crush-g1-0', 'reviewer', 'reviewer', 'review'),
    ('reviewer-reviewer-goose-g1-0', 'reviewer', 'reviewer', 'review'),
    ('reviewer-supervisor-g22-0', 'reviewer', 'supervisor', 'supervision and relay'),
    ('product-reviewer-g34-0', 'product', 'reviewer', 'review'),
    ('arcaven-claude-reviewer-g1-0', 'arcaven-claude', 'reviewer', 'review'),
]


def rec(sid, n, cwd='/srv/demo-fleet/a', tools=(), skill=None, ts='2026-10-05T10:00:00Z'):
    content = [{'type': 'tool_use', 'name': t} for t in tools]
    if skill:
        content.append({'type': 'tool_use', 'name': 'Skill', 'input': {'skill': skill}})
    return {'type': 'assistant', 'timestamp': ts, 'sessionId': sid, 'cwd': cwd, 'requestId': 'r%s' % n,
            'uuid': 'u%s' % n, 'message': {'id': 'm%s' % n, 'model': MODEL, 'content': content,
            'usage': {'input_tokens': 10, 'output_tokens': 5, 'cache_read_input_tokens': 100,
                      'cache_creation_input_tokens': 0}}}


def run(script, sessions, launch_lines=(), gz_lines=()):
    """sessions: list of (sid, agent_name or None, [records]). Returns {file: rows} from the output dir."""
    with tempfile.TemporaryDirectory() as d:
        proj = os.path.join(d, 'cfg', 'projects', 'p'); os.makedirs(proj)
        for sid, name, recs in sessions:
            with open(os.path.join(proj, sid + '.jsonl'), 'w') as fh:
                if name:
                    fh.write(json.dumps({'type': 'agent-name', 'agentName': name, 'sessionId': sid}) + '\n')
                for r in recs:
                    fh.write(json.dumps(r) + '\n')
        logd = os.path.join(d, 'log'); os.makedirs(logd)
        with open(os.path.join(logd, 'daemon.log'), 'w') as fh:
            fh.write('\n'.join(launch_lines) + '\n')
        with gzip.open(os.path.join(logd, 'daemon.log.20261010T000000Z.gz'), 'wt') as fh:
            fh.write('\n'.join(gz_lines) + '\n')
        with open(os.path.join(d, 'cfg', '.claude.json'), 'w') as fh:
            json.dump({'oauthAccount': {'emailAddress': 'Someone@Example.test'}}, fh)
        with open(os.path.join(d, 'prices.json'), 'w') as fh:
            json.dump(PRICES, fh)
        with open(os.path.join(d, 'map.csv'), 'w', newline='') as fh:
            csv.writer(fh).writerows(MAP)
        out = os.path.join(d, 'out'); os.makedirs(out)
        r = subprocess.run([sys.executable, '-I', script, out, os.path.join(d, 'prices.json'), 'demo',
                            os.path.join(d, 'map.csv'), os.path.join(d, 'cfg', 'projects'), logd],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        res = {}
        for f in os.listdir(out):
            with open(os.path.join(out, f)) as fh:
                res[f] = list(csv.DictReader(fh)) if f.endswith('.csv') else fh.read()
        return res


def table_mismatches(script):
    sess = [('s%d' % i, lab, [rec('s%d' % i, i)]) for i, (lab, _, _, _) in enumerate(TABLE)]
    got = {}
    for r in run(script, sess)['by-seat-label.csv']:
        got[(r['team'], r['role'], r['activity'])] = got.get((r['team'], r['role'], r['activity']), 0) + int(r['requests'])
    want = {}
    for _, t, ro, a in TABLE:
        want[(t, ro, a)] = want.get((t, ro, a), 0) + 1
    return {k: (want.get(k), got.get(k)) for k in set(want) | set(got) if want.get(k) != got.get(k)}


class T(unittest.TestCase):
    def test_role_table(self):
        self.assertEqual(table_mismatches(SCRIPT), {})

    def test_role_table_mutant_turns_red(self):
        with open(SCRIPT) as fh:
            src = fh.read()
        needle = "if sb.endswith('-'+h): sb=sb[:-len(h)-1]; break"
        self.assertEqual(src.count(needle), 1)
        with tempfile.TemporaryDirectory() as d:
            m = os.path.join(d, 'mutant.py')
            with open(m, 'w') as fh:
                fh.write(src.replace(needle, 'pass'))
            self.assertNotEqual(table_mismatches(m), {})

    def test_launch_log_fills_missing_agent_name(self):
        u1 = '11111111-1111-4111-8111-111111111111'
        u2 = '22222222-2222-4222-8222-222222222222'
        line = "2026/10/22 15:14:00 session demo-ws/%s exec: /bin/claude '--session-id' '%s' '--x' 'y'"
        res = run(SCRIPT, [(u1, None, [rec(u1, 1)]), (u2, None, [rec(u2, 2)])],
                  [line % ('reviewer-reviewer-claude-g9-0', u1)], [line % ('demo-builder-g2-0', u2)])
        by = {r['label_base']: r for r in res['by-seat-label.csv']}
        self.assertEqual((by['reviewer-reviewer-claude']['method'], by['reviewer-reviewer-claude']['team'],
                          by['reviewer-reviewer-claude']['role']), ('launch-log', 'reviewer', 'reviewer'))
        self.assertEqual(by['demo-builder']['method'], 'launch-log')
        self.assertIn('requests_launch_log=2', res['attribution-meta.txt'])
        self.assertEqual(res['unattributed-sessions.csv'], [])

    def test_agent_name_wins_over_launch_log(self):
        u = '33333333-3333-4333-8333-333333333333'
        res = run(SCRIPT, [(u, 'product-builder-g1-0', [rec(u, 1)])],
                  ["session demo-ws/other-envoy-g1-0 exec: x '--session-id' '%s'" % u])
        self.assertEqual(res['by-seat-label.csv'][0]['method'], 'agent-name')
        self.assertEqual(res['by-seat-label.csv'][0]['role'], 'builder')

    def test_unnamed_split_and_sums(self):
        s = [('a1', None, [rec('a1', 1, '/srv/demo-own/notes')]),
             ('a2', None, [rec('a2', 2, '/srv/demo-fleet/x', skill='demo-coach')]),
             ('a3', None, [rec('a3', 3, '/srv/demo-orch/client-x/repo')]),
             ('a4', None, [rec('a4', 4, '/srv/demo-fleet/y'),
                           rec('a4', 5, '/srv/demo-fleet/y', tools=['mcp__director__wait_for_message'])]),
             ('a5', 'product-builder-g1-0', [rec('a5', 6)])]
        res = run(SCRIPT, s)
        cls = {r['session_hash']: r for r in res['unattributed-sessions.csv']}
        h = lambda x: hashlib.sha256(x.encode()).hexdigest()[:12]
        self.assertEqual(cls[h('a1')]['class'], 'operator own work (outside fleet)')
        self.assertEqual(cls[h('a2')]['class'], 'operator own work (outside fleet)')
        self.assertEqual(cls[h('a3')]['class'], 'external orchestration (outside marvel)')
        self.assertEqual(cls[h('a3')]['project_dir'], 'demo-orch')
        self.assertEqual(cls[h('a4')]['class'], 'no seat name (unattributed)')
        self.assertEqual(len(cls), 4)
        self.assertGreater(float(cls[h('a4')]['hub_wait_usd']), 0)
        self.assertNotIn('operator direct or unnamed', json.dumps(res))
        tot = lambda f: round(sum(float(r['list_usd']) for r in res[f]), 2)
        self.assertEqual(tot('by-seat-label.csv'), tot('axes-rows.csv'))
        self.assertEqual(tot('daily-by-model.csv'), tot('axes-rows.csv'))
        self.assertIn('requests_none=5', res['attribution-meta.txt'])
        self.assertIn('requests_agent_name=1', res['attribution-meta.txt'])

    def test_signin_hash_is_lowercased_email_hash_and_no_text_leaks(self):
        res = run(SCRIPT, [('b1', None, [rec('b1', 1)])])
        want = hashlib.sha256(b'someone@example.test').hexdigest()[:12]
        self.assertIn('signin_hash=' + want, res['attribution-meta.txt'])
        self.assertNotIn('example.test', json.dumps(res))


if __name__ == '__main__':
    unittest.main()

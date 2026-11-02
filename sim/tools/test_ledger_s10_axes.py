#!/usr/bin/env python3
# Tests for ledger-s10-axes.py. Runs the script end to end over invented transcripts, an invented map and an
# invented marvel log, so nothing here reads a real home directory.
# Run: python3 -I sim/tools/test_ledger_s10_axes.py
import csv, gzip, json, os, shutil, subprocess, sys, tempfile, unittest, hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, 'ledger-s10-axes.py')
MODEL = 'demo-model'
PRICES = {MODEL: {'in': 10000, 'cw5': 10000, 'cw1': 10000, 'cr': 10000, 'out': 10000}}
MAP = [('kind', 'match', 'value', 'note'),
       ('own', '^/srv/demo-own/', 'vault', ''),
       ('own_skill', 'demo-coach', 'coach', ''),
       ('orchestrator', '^/srv/demo-orch/', 'demo-orch', ''),
       ('own', '^/srv/demo-both/', 'both-path', ''),
       ('orchestrator', '^/srv/demo-both/', 'demo-orch', '')]

# label -> (team, role, activity); the role parser table from the I-119 spec, with invented seat names of the same shapes.
TABLE = [
    ('acme-reviewer-claude-g1-0', 'acme', 'reviewer', 'review'),
    ('acme-reviewer-reviewer-claude-g24-0', 'acme', 'reviewer', 'review'),
    ('widget-reviewer-codex-g3-0', 'widget', 'reviewer', 'review'),
    ('widget-reviewer-opencode-g1-0', 'widget', 'reviewer', 'review'),
    ('widget-reviewer-crush-g1-0', 'widget', 'reviewer', 'review'),
    ('widget-reviewer-goose-g1-0', 'widget', 'reviewer', 'review'),
    ('acme-reviewer-supervisor-g1-0', 'acme-reviewer', 'supervisor', 'supervision and relay'),
    ('widget-reviewer-g1-0', 'widget', 'reviewer', 'review'),
    ('acme-claude-reviewer-g1-0', 'acme-claude', 'reviewer', 'review'),
    ('widget-test-architect-g1-0', 'widget', 'test-architect', 'design'),
    ('widget-architect-g1-0', 'widget', 'architect', 'design'),
]


def rec(sid, n, cwd='/srv/demo-fleet/a', tools=(), skill=None, ts='2026-10-05T10:00:00Z'):
    content = [{'type': 'tool_use', 'name': t} for t in tools]
    if skill:
        content.append({'type': 'tool_use', 'name': 'Skill', 'input': {'skill': skill}})
    return {'type': 'assistant', 'timestamp': ts, 'sessionId': sid, 'cwd': cwd, 'requestId': 'r%s' % n,
            'uuid': 'u%s' % n, 'message': {'id': 'm%s' % n, 'model': MODEL, 'content': content,
            'usage': {'input_tokens': 10, 'output_tokens': 5, 'cache_read_input_tokens': 100,
                      'cache_creation_input_tokens': 0}}}


def run(script, sessions, launch_lines=(), gz_lines=(), prices=None, mkout=True, cache=None):
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
            json.dump(PRICES if prices is None else prices, fh)
        with open(os.path.join(d, 'map.csv'), 'w', newline='') as fh:
            csv.writer(fh).writerows(MAP)
        out = os.path.join(d, 'out')
        if mkout:
            os.makedirs(out)
        # the repo cache sidecar never lands in a real home: each run gets its own file unless the test shares one
        env = dict(os.environ, LEDGER_REPO_CACHE=cache or os.path.join(d, 'repo-cache.csv'))
        r = subprocess.run([sys.executable, '-I', script, out, os.path.join(d, 'prices.json'), 'demo',
                            os.path.join(d, 'map.csv'), os.path.join(d, 'cfg', 'projects'), logd],
                           capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
        res = {'_cr': []}
        for f in os.listdir(out):
            with open(os.path.join(out, f), 'rb') as fh:
                if b'\r' in fh.read():
                    res['_cr'].append(f)
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
        needle = "if sb.endswith('-'+h): sb=sb[:-len(h)-1]; harness=True; break"
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
        res = run(SCRIPT, [(u, 'widget-builder-g1-0', [rec(u, 1)])],
                  ["session demo-ws/other-envoy-g1-0 exec: x '--session-id' '%s'" % u])
        self.assertEqual(res['by-seat-label.csv'][0]['method'], 'agent-name')
        self.assertEqual(res['by-seat-label.csv'][0]['role'], 'builder')

    def test_unnamed_split_and_sums(self):
        s = [('a1', None, [rec('a1', 1, '/srv/demo-own/notes')]),
             ('a2', None, [rec('a2', 2, '/srv/demo-fleet/x', skill='demo-coach')]),
             ('a3', None, [rec('a3', 3, '/srv/demo-orch/client-x/repo')]),
             ('a4', None, [rec('a4', 4, '/srv/demo-fleet/y'),
                           rec('a4', 5, '/srv/demo-fleet/y', tools=['mcp__director__wait_for_message'])]),
             ('a5', 'widget-builder-g1-0', [rec('a5', 6)])]
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

    def dirs(self, script, cwds):
        s = [('d%d' % i, None, [rec('d%d' % i, 70 + i, c)]) for i, c in enumerate(cwds)]
        return sorted(r['project_dir'] for r in run(script, s)['unattributed-sessions.csv'])

    CWDS = ['/private/tmp/claude-1/scratchpad-9f2c/work', '/tmp/x/y', '/Users/demo-user/work/other-org/some-repo',
            '/srv/demo-own/notes', '/srv/demo-orch/client-x/repo', '/srv/x/scratchpad-1/w']

    WANT = sorted(['temp', 'temp', 'temp', 'home', 'own', 'demo-orch'])

    def test_project_dir_is_rolled_up_never_raw(self):
        self.assertEqual(self.dirs(SCRIPT, self.CWDS), self.WANT)

    def test_rollup_mutant_that_prints_raw_turns_red(self):
        with open(SCRIPT) as fh:
            src = fh.read()
        needle = "_cc[sid]=(c,rollup(k,orch,own),"
        self.assertEqual(src.count(needle), 1)
        with tempfile.TemporaryDirectory() as d:
            m = os.path.join(d, 'mutant.py')
            with open(m, 'w') as fh:
                fh.write(src.replace(needle, "_cc[sid]=(c,k,"))
            self.assertNotEqual(self.dirs(m, self.CWDS), self.WANT)

    def mutant(self, old, new, count=1):
        with open(SCRIPT) as fh:
            src = fh.read()
        self.assertEqual(src.count(old), count)
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        m = os.path.join(d, 'mutant.py')
        with open(m, 'w') as fh:
            fh.write(src.replace(old, new))
        return m

    def test_scratchpad_clause_is_pinned(self):
        m = self.mutant(" or 'scratchpad' in k", "")
        self.assertNotEqual(self.dirs(m, self.CWDS), self.WANT)

    def test_own_wins_over_orchestrator_in_class_and_rollup(self):
        s = [('b1', None, [rec('b1', 80, '/srv/demo-both/p')])]
        row = run(SCRIPT, s)['unattributed-sessions.csv'][0]
        self.assertEqual((row['class'], row['project_dir']), ('operator own work (outside fleet)', 'own'))
        m = self.mutant("    if own: return 'own'\n    if orch is not None: return orch\n",
                        "    if orch is not None: return orch\n    if own: return 'own'\n")
        self.assertEqual(run(m, s)['unattributed-sessions.csv'][0]['project_dir'], 'demo-orch')

    def test_signin_note_says_pseudonym(self):
        res = run(SCRIPT, [('c1', None, [rec('c1', 90)])])
        self.assertIn('unsalted 12-hex pseudonym', res['attribution-meta.txt'])

    def test_signin_hash_is_lowercased_email_hash_and_no_text_leaks(self):
        res = run(SCRIPT, [('b1', None, [rec('b1', 1)])])
        want = hashlib.sha256(b'someone@example.test').hexdigest()[:12]
        self.assertIn('signin_hash=' + want, res['attribution-meta.txt'])
        self.assertNotIn('example.test', json.dumps(res))


    def test_not_a_seat_method_prints_no_name(self):
        s = [('n1', 'demo-director', [rec('n1', 100, '/srv/demo-orch/x')]),
             ('n2', 'demo-other-thing', [rec('n2', 101, '/srv/demo-orch/x')])]
        res = run(SCRIPT, s)
        self.assertIn('requests_agent_name_not_a_seat=2', res['attribution-meta.txt'])
        self.assertIn('requests_agent_name=0', res['attribution-meta.txt'])
        self.assertEqual({r['method'] for r in res['by-seat-label.csv']}, {'agent-name (not a seat)'})
        self.assertNotIn('named-sessions.csv', res)
        self.assertNotIn('demo-director', json.dumps(res))
        self.assertNotIn('demo-other-thing', json.dumps(res))
        m = self.mutant("'agent-name (not a seat)' if method=='agent-name' else method", "method")
        self.assertNotIn('requests_agent_name_not_a_seat=2', run(m, s)['attribution-meta.txt'])

    DIR = 'director sessions (coordination)'
    ORCH = 'external orchestration (outside marvel)'

    def director_classes(self, script):
        mcp = 'mcp__director__send_message'
        s = [('d1', None, [rec('d1', 150, '/srv/demo-orch/x', skill='director')]),
             ('d2', None, [rec('d2', 151, '/srv/demo-orch/x', tools=[mcp, mcp, 'Bash'])]),
             ('d3', None, [rec('d3', 152, '/srv/demo-orch/x', tools=[mcp, 'Bash', 'Read'])]),
             ('d4', None, [rec('d4', 153, '/srv/demo-orch/x', skill='demo-other-skill')]),
             ('d5', None, [rec('d5', 154, '/srv/demo-orch/x', skill='director', tools=[mcp, mcp])]),
             ('d6', None, [rec('d6', 155, '/srv/demo-fleet/z', skill='director')]),
             ('d7', None, [rec('d7', 156, '/srv/demo-orch/x', tools=[mcp, 'Bash'])])]
        h = lambda x: hashlib.sha256(x.encode()).hexdigest()[:12]
        rows = {r['session_hash']: (r['class'], r['director_rule']) for r in run(script, s)['unattributed-sessions.csv']}
        want = {h('d1'): (self.DIR, 'skill'), h('d2'): (self.DIR, 'mcp-majority'), h('d3'): (self.ORCH, ''),
                h('d4'): (self.ORCH, ''), h('d5'): (self.DIR, 'skill+mcp-majority'),
                h('d6'): ('no seat name (unattributed)', ''), h('d7'): (self.ORCH, '')}
        return rows, want

    def test_director_sessions_are_classed_by_tool_calls(self):
        got, want = self.director_classes(SCRIPT)
        self.assertEqual(got, want)

    def test_director_class_mutants_turn_red(self):
        old = "    elif orch is not None: c=C_DIR if dr else C_ORCH\n"
        for new in ("    elif orch is not None: c=C_ORCH\n",
                    "    elif orch is not None: c=C_DIR\n"):
            got, want = self.director_classes(self.mutant(old, new))
            self.assertNotEqual(got, want)
        for a, b in (("'director' in skills.get(sid,set())", "False"),
                     ("2*tc['director']>tc['n']", "2*tc['director']>=tc['n']"),
                     ("bool(tc['n']) and 2*tc['director']>tc['n']", "False")):
            got, want = self.director_classes(self.mutant(a, b))
            self.assertNotEqual(got, want)

    def test_own_skill_rolls_up_to_own(self):
        s = [('k1', None, [rec('k1', 160, '/srv/demo-orch/x', skill='demo-coach')]),
             ('k2', None, [rec('k2', 161, '/srv/demo-fleet/y', skill='demo-coach')])]
        got = lambda sc: sorted((r['class'], r['project_dir']) for r in run(sc, s)['unattributed-sessions.csv'])
        want = [('operator own work (outside fleet)', 'own')] * 2
        self.assertEqual(got(SCRIPT), want)
        m = self.mutant("    own=bool(prules) or bool(srules)\n", "    own=bool(prules)\n")
        self.assertNotEqual(sorted(r['project_dir'] for r in run(m, s)['unattributed-sessions.csv']), ['own', 'own'])

    def seat_rows(self, script, labels):
        s = [('t%d' % i, n, [rec('t%d' % i, 170 + i)]) for i, n in enumerate(labels)]
        return {r['label_base']: (r['method'], r['activity']) for r in run(script, s)['by-seat-label.csv']}

    def test_only_role_words_make_a_seat_label(self):
        labels = ['acme-notes-g1-0', 'acme-superbuilder-g1-0', 'acme-builder-g1-0', 'dryrun-widget-g1-0']
        got = self.seat_rows(SCRIPT, labels)
        self.assertEqual(got['acme-builder'], ('agent-name', 'building'))
        self.assertEqual(got['dryrun-widget'], ('agent-name', 'other seat roles'))
        self.assertEqual(sorted(got), ['acme-builder', 'dryrun-widget', 'no seat name (unattributed)'])
        self.assertEqual(got['no seat name (unattributed)'][0], 'agent-name (not a seat)')
        m = self.mutant("        if not sb.startswith('dryrun-'): return None\n", "")
        self.assertIn('acme-notes', self.seat_rows(m, labels))

    def test_generic_role_words_are_seats_with_their_activity(self):
        want = {'filer': 'filing', 'maintainer': 'maintenance', 'monitor': 'other seat roles', 'reader': 'research',
                'writer': 'design', 'worker': 'building', 'editor': 'design', 'analyst': 'research',
                'retrospector': 'research', 'introspector': 'research', 'sweeper': 'maintenance',
                'fact-checker': 'review', 'merge-queue': 'other seat roles', 'researcher': 'research',
                'director': 'supervision and relay', 'lead': 'supervision and relay', 'screener': 'review',
                'panelist': 'design'}
        got = self.seat_rows(SCRIPT, ['acme-%s-g1-0' % w for w in want])
        self.assertEqual({k[len('acme-'):]: v for k, v in got.items()}, {w: ('agent-name', a) for w, a in want.items()})
        m = self.mutant("'sweeper':'maintenance'", "'sweeper':'review'")
        self.assertNotEqual(self.seat_rows(m, ['acme-sweeper-g1-0']), {'acme-sweeper': ('agent-name', 'maintenance')})
        m = self.mutant("'researcher','director','lead','screener','panelist']", "'director','lead','screener','panelist']")
        self.assertNotIn('acme-researcher', self.seat_rows(m, ['acme-researcher-g1-0']))

    def test_shard_token_is_stripped_before_the_role_match(self):
        labels = ['acme-ax-reader-f1-g1-0', 'acme-i72-reader-f6f7-g1-0', 'acme-ax-monitor-g1-0', 'acme-ax-notes-f2-g1-0']
        got = self.seat_rows(SCRIPT, labels)
        self.assertEqual(got['acme-ax-reader-f1'], ('agent-name', 'research'))
        self.assertEqual(got['acme-i72-reader-f6f7'], ('agent-name', 'research'))
        self.assertEqual(got['acme-ax-monitor'], ('agent-name', 'other seat roles'))
        self.assertNotIn('acme-ax-notes-f2', got)
        s = [('h1', 'acme-ax-reader-f1-g1-0', [rec('h1', 190)])]
        row = run(SCRIPT, s)['by-seat-label.csv'][0]
        self.assertEqual((row['team'], row['role']), ('acme-ax', 'reader'))
        m = self.mutant("t=re.sub(r'-f[0-9]+(f[0-9]+)*$','',sb); shard=(t!=sb); sb=t", "pass")
        self.assertNotIn('acme-ax-reader-f1', self.seat_rows(m, labels))

    def test_a_missing_output_dir_is_created(self):
        s = [('o1', 'acme-builder-g1-0', [rec('o1', 200)])]
        self.assertEqual(run(SCRIPT, s, mkout=False)['by-seat-label.csv'][0]['label_base'], 'acme-builder')
        m = self.mutant("os.makedirs(out,exist_ok=True); ", "")
        with self.assertRaises(AssertionError):
            run(m, s, mkout=False)

    def test_harness_and_shard_tokens_strip_in_either_order(self):
        labels = ['acme-ax-reader-f1-claude-g1-0', 'acme-ax-reader-claude-f6f7-g1-0', 'acme-ax-reader-g1-0']
        got = self.seat_rows(SCRIPT, labels)
        self.assertEqual(sorted(got), ['acme-ax-reader', 'acme-ax-reader-claude-f6f7', 'acme-ax-reader-f1-claude'])
        self.assertTrue(all(v == ('agent-name', 'research') for v in got.values()))
        m = self.mutant("for _ in (0,1):", "for _ in (0,):")
        self.assertNotEqual(sorted(self.seat_rows(m, labels)), sorted(got))

    def test_rule_column(self):
        s = [('r1', None, [rec('r1', 110, '/srv/demo-own/notes')]),
             ('r2', None, [rec('r2', 111, '/srv/demo-fleet/x', skill='demo-coach')]),
             ('r3', None, [rec('r3', 112, '/srv/demo-own/notes', skill='demo-coach')]),
             ('r4', None, [rec('r4', 113, '/srv/demo-orch/x')])]
        h = lambda x: hashlib.sha256(x.encode()).hexdigest()[:12]
        want = {h('r1'): 'vault', h('r2'): 'coach', h('r3'): 'vault+coach', h('r4'): ''}
        got = lambda sc: {r['session_hash']: r['rule'] for r in run(sc, s)['unattributed-sessions.csv']}
        self.assertEqual(got(SCRIPT), want)
        self.assertNotEqual(got(self.mutant("'+'.join(dict.fromkeys(prules+srules))", "'+'.join(dict.fromkeys(prules))")), want)

    def test_dated_model_id_is_priced(self):
        p = {'claude-demo-1': PRICES[MODEL]}
        dated = rec('p1', 120); dated['message']['model'] = 'claude-demo-1-20251001'
        s = [('p1', None, [dated])]
        res = run(SCRIPT, s, prices=p)
        self.assertEqual(res['daily-by-model.csv'][0]['unpriced'], '0')
        self.assertEqual(res['daily-by-model.csv'][0]['model'], 'claude-demo-1-20251001')
        m = self.mutant("return P.get(model) or P.get(re.sub(r'-\\d{8}$','',model or ''))", "return P.get(model)")
        self.assertEqual(run(m, s, prices=p)['daily-by-model.csv'][0]['unpriced'], '1')

    def test_filer_and_maintainer_activities(self):
        s = [('f1', 'widget-filer-g1-0', [rec('f1', 130)]), ('f2', 'widget-maintainer-g1-0', [rec('f2', 131)]),
             ('f3', 'dryrun-widget-g1-0', [rec('f3', 132)])]
        got = lambda sc: {r['label_base']: r['activity'] for r in run(sc, s)['by-seat-label.csv']}
        want = {'widget-filer': 'filing', 'widget-maintainer': 'maintenance', 'dryrun-widget': 'other seat roles'}
        self.assertEqual(got(SCRIPT), want)
        self.assertNotEqual(got(self.mutant("'filer':'filing','maintainer':'maintenance',", "")), want)

    def test_no_output_has_a_cr_byte(self):
        s = [('x1', None, [rec('x1', 140)]), ('x2', 'demo-director', [rec('x2', 141)])]
        self.assertEqual(run(SCRIPT, s)['_cr'], [])
        m = self.mutant("w=csv.writer(fh,lineterminator='\\n');", "w=csv.writer(fh);", 2)
        self.assertNotEqual(run(m, s)['_cr'], [])

    # by-token-class.csv: list price split by input, cache write, cache read and output. The prices are per class
    # (dollars per million tokens), so each class has a distinct, checkable dollar figure on invented token counts.
    TOK_PRICES = {MODEL: {'in': 3.0, 'cw5': 3.75, 'cw1': 6.0, 'cr': 0.3, 'out': 15.0}}

    @staticmethod
    def tok_rec(sid, n, model=MODEL, **u):
        r = rec(sid, n)
        r['message']['model'] = model
        r['message']['usage'] = u
        return r

    def tok_sessions(self):
        full = self.tok_rec('t1', 200, input_tokens=1000000, output_tokens=100000, cache_read_input_tokens=2000000,
                            cache_creation_input_tokens=650000,
                            cache_creation={'ephemeral_5m_input_tokens': 400000, 'ephemeral_1h_input_tokens': 250000})
        out_only = self.tok_rec('t1', 201, output_tokens=100000)
        unpriced = self.tok_rec('t1', 202, model='demo-unpriced', input_tokens=5000000, output_tokens=5000000)
        return [('t1', None, [full, out_only, unpriced])]

    def tok_rows(self, script):
        res = run(script, self.tok_sessions(), prices=self.TOK_PRICES)
        return [(r['token_class'], r['requests'], r['list_usd']) for r in res['by-token-class.csv']], res

    TOK_WANT = [('input', '1', '3.0'), ('cache write', '1', '3.0'), ('cache read', '1', '0.6'), ('output', '2', '3.0')]

    def test_token_class_rows(self):
        got, res = self.tok_rows(SCRIPT)
        self.assertEqual(got, self.TOK_WANT)
        self.assertEqual({r['cluster'] for r in res['by-token-class.csv']}, {'demo'})
        self.assertEqual(list(res['by-token-class.csv'][0]), ['cluster', 'token_class', 'requests', 'list_usd'])

    def test_token_class_rows_reconcile_with_the_total(self):
        got, res = self.tok_rows(SCRIPT)
        total = json.loads(res['axes-meta.json'])['list_usd']
        self.assertAlmostEqual(sum(float(x[2]) for x in got), total, places=2)

    def test_token_class_mutants_turn_red(self):
        # a cache write priced at the 5 minute rate only, and a request counted without tokens of the class
        got, _ = self.tok_rows(self.mutant("+e['cw1']*p['cw1']),\n", "),\n"))
        self.assertNotEqual(got, self.TOK_WANT)
        got, _ = self.tok_rows(self.mutant("if n_tok>0: tk[nm]['requests']+=1", "tk[nm]['requests']+=1"))
        self.assertNotEqual(got, self.TOK_WANT)

    # Repo cache: a cwd resolved from git is kept in a sidecar, so a rerun after the worktree is removed gives the same repo.
    def worktree_fixture(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        g = ['git', '-c', 'user.name=demo', '-c', 'user.email=demo@example.test']
        main = os.path.join(d, 'main-repo'); wt = os.path.join(d, 'wt1')
        for cmd in (g + ['init', '-q', main], g + ['-C', main, 'commit', '-q', '--allow-empty', '-m', 'init'],
                    g + ['-C', main, 'remote', 'add', 'origin', 'https://example.test/demo-org/demo-repo.git'],
                    g + ['-C', main, 'worktree', 'add', '-q', wt, '-b', 'demo-branch']):
            subprocess.run(cmd, check=True, capture_output=True)
        def remove():
            subprocess.run(g + ['-C', main, 'worktree', 'remove', '--force', wt], check=True, capture_output=True)
        return d, wt, remove

    def repos(self, script, wt, cache):
        res = run(script, [('w1', None, [rec('w1', 300, cwd=wt)])], cache=cache)
        return sorted((r['repo'], r['requests']) for r in res['by-repo.csv'])

    def test_repo_survives_a_removed_worktree(self):
        d, wt, remove = self.worktree_fixture()
        cache = os.path.join(d, 'sidecar', 'cache.csv')
        want = [('demo-org/demo-repo', '1')]
        self.assertEqual(self.repos(SCRIPT, wt, cache), want)
        remove()
        self.assertEqual(self.repos(SCRIPT, wt, cache), want)
        # without the sidecar the same input reads unknown: the defect the cache closes
        self.assertEqual(self.repos(SCRIPT, wt, os.path.join(d, 'other.csv')), [('unknown', '1')])
        with open(cache) as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual([(r['cwd'], r['repo']) for r in rows], [(wt, 'demo-org/demo-repo')])
        self.assertRegex(rows[0]['first_seen'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$')
        self.assertEqual(oct(os.stat(cache).st_mode & 0o777), '0o600')
        self.assertEqual(oct(os.stat(os.path.dirname(cache)).st_mode & 0o777), '0o700')

    def test_repo_cache_mutant_that_skips_the_cache_turns_red(self):
        d, wt, remove = self.worktree_fixture()
        cache = os.path.join(d, 'cache.csv')
        m = self.mutant("if v is None and cwd in RCACHE: v=RCACHE[cwd][0]", "if False: pass")
        self.assertEqual(self.repos(m, wt, cache), [('demo-org/demo-repo', '1')])
        remove()
        self.assertEqual(self.repos(m, wt, cache), [('unknown', '1')])

    def test_unresolved_cwd_is_not_cached_and_the_sidecar_is_not_output(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        cache = os.path.join(d, 'cache.csv')
        res = run(SCRIPT, [('g1', None, [rec('g1', 301, cwd='/srv/demo-gone/x')])], cache=cache)
        self.assertEqual([r['repo'] for r in res['by-repo.csv']], ['unknown'])
        self.assertFalse(os.path.exists(cache))
        self.assertFalse(any('cache' in f for f in res))

    def test_price_files(self):
        def sha(f):
            with open(os.path.join(HERE, f), 'rb') as fh:
                return hashlib.sha256(fh.read()).hexdigest()
        self.assertEqual(sha('prices-s11.json'), 'ac42f453392f' + sha('prices-s11.json')[12:])
        with open(os.path.join(HERE, 'prices-s11.json')) as fh:
            s11 = json.load(fh)
        with open(os.path.join(HERE, 'prices-s12.json')) as fh:
            s12 = json.load(fh)
        for k, v in s11.items():
            if k != '_source':
                self.assertEqual(s12[k], v)
        want = {'claude-opus-5': (5.0, 25.0, 0.5, 6.25, 10.0), 'claude-sonnet-5': (2.0, 10.0, 0.2, 2.5, 4.0),
                'claude-haiku-4-5': (1.0, 5.0, 0.1, 1.25, 2.0), 'claude-fable-5-1': (10.0, 50.0, 0.25, 12.5, 20.0)}
        for k, (i, o, cr, w5, w1) in want.items():
            self.assertEqual((s12[k]['in'], s12[k]['out'], s12[k]['cr'], s12[k]['cw5'], s12[k]['cw1']), (i, o, cr, w5, w1))
        self.assertEqual(sorted(set(s12) - set(s11)), sorted(want))
        self.assertIn('cached list rates', s12['_source'])


if __name__ == '__main__':
    unittest.main()

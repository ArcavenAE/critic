#!/usr/bin/env python3
# Tests for ledger-s10-axes.py. Runs the script end to end over invented transcripts, an invented map and an
# invented marvel log, so nothing here reads a real home directory.
# Run: python3 -I sim/tools/test_ledger_s10_axes.py
import collections, concurrent.futures, csv, glob, gzip, json, os, shutil, subprocess, sys, tempfile, unittest, hashlib

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


def rec_part(sid, n, part, uses, cwd='/srv/demo-orch/x', ts='2026-10-05T10:00:00Z'):
    """One record of message n, whose content arrives over several records that share the message id.
    uses: list of (tool_use id, tool name)."""
    content = [{'type': 'tool_use', 'id': i, 'name': t} for i, t in uses]
    return {'type': 'assistant', 'timestamp': ts, 'sessionId': sid, 'cwd': cwd, 'requestId': 'r%s' % n,
            'uuid': 'u%s-%s' % (n, part), 'message': {'id': 'm%s' % n, 'model': MODEL, 'content': content,
            'usage': {'input_tokens': 10, 'output_tokens': 5, 'cache_read_input_tokens': 100,
                      'cache_creation_input_tokens': 0}}}


def rec_use(sid, n, uses, cwd='/srv/demo-orch/x', ts='2026-10-05T10:00:00Z'):
    """One request. uses: list of tool names, or (tool name, Bash command) pairs."""
    content = []
    for i, u in enumerate(uses):
        name, cmd = (u, None) if isinstance(u, str) else u
        b = {'type': 'tool_use', 'id': 'tu%s-%s' % (n, i), 'name': name}
        if cmd is not None:
            b['input'] = {'command': cmd}
        content.append(b)
    return {'type': 'assistant', 'timestamp': ts, 'sessionId': sid, 'cwd': cwd, 'requestId': 'r%s' % n,
            'uuid': 'u%s' % n, 'message': {'id': 'm%s' % n, 'model': MODEL, 'content': content,
            'usage': {'input_tokens': 10, 'output_tokens': 5, 'cache_read_input_tokens': 100,
                      'cache_creation_input_tokens': 0}}}


def run(script, sessions, launch_lines=(), gz_lines=(), prices=None, mkout=True, cache=None, maprows=(), counts=None, asks=None):
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
            csv.writer(fh).writerows(list(MAP) + list(maprows))
        out = os.path.join(d, 'out')
        if mkout:
            os.makedirs(out)
        # the repo cache sidecar never lands in a real home: each run gets its own file unless the test shares one
        env = dict(os.environ, LEDGER_REPO_CACHE=cache or os.path.join(d, 'repo-cache.csv'))
        env.pop('LEDGER_UNIT_COUNTS', None)
        if counts is not None:
            with open(os.path.join(d, 'counts.csv'), 'w', newline='') as fh:
                csv.writer(fh).writerows([('unit', 'count')] + list(counts))
            env['LEDGER_UNIT_COUNTS'] = os.path.join(d, 'counts.csv')
        argv = [os.path.join(d, 'cfg', 'projects'), logd]
        if asks is not None:
            with open(os.path.join(d, 'asks.jsonl'), 'w') as fh:
                fh.write('\n'.join(a if isinstance(a, str) else json.dumps(a) for a in asks) + '\n')
            argv.append(os.path.join(d, 'asks.jsonl'))
        r = subprocess.run([sys.executable, '-I', script, out, os.path.join(d, 'prices.json'), 'demo',
                            os.path.join(d, 'map.csv')] + argv,
                           capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
        res = {'_cr': [], '_stderr': r.stderr}
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

    def split_message_classes(self, script):
        mcp = 'mcp__director__send_message'
        # d8: one message id over two records; the first holds a Bash call, the second two director calls.
        # d9: one message id over two records; the second record repeats tool_use t1 and adds a Bash call.
        s = [('d8', None, [rec_part('d8', 170, 0, [('t1', 'Bash')]),
                           rec_part('d8', 170, 1, [('t2', mcp), ('t3', mcp)])]),
             ('d9', None, [rec_part('d9', 171, 0, [('t1', mcp)]),
                           rec_part('d9', 171, 1, [('t1', mcp), ('t2', 'Bash')])])]
        h = lambda x: hashlib.sha256(x.encode()).hexdigest()[:12]
        rows = {r['session_hash']: (r['class'], r['director_rule']) for r in run(script, s)['unattributed-sessions.csv']}
        want = {h('d8'): (self.DIR, 'mcp-majority'), h('d9'): (self.ORCH, '')}
        return rows, want

    def test_tool_use_blocks_are_counted_by_id_across_the_records_of_a_message(self):
        # d8 holds two director calls of three, so it is a director session only when the second record counts.
        # d9 holds one director call of two once t1 is counted a single time; counted twice it would be two of three.
        got, want = self.split_message_classes(SCRIPT)
        self.assertEqual(got, want)

    def test_by_id_counting_mutants_turn_red(self):
        for a, b in (("if key in seen_tu: continue", "pass"),
                     ("key=(mid,b['id']) if b.get('id') else ('noid',mid,r.get('uuid'),i)", "key=('noid',mid,r.get('uuid'),i)")):
            got, want = self.split_message_classes(self.mutant(a, b))
            self.assertNotEqual(got, want)

    # The director signature table, as the design's section 2 lists it, written as map rows. match syntax: "tool:NAME"
    # (a trailing * is a prefix), "all:A|B" (every tool of the request is one of them), "bash:WORDS" (some segment of
    # some Bash command starts with those words), "bashtext:TEXT" (a Bash command contains TEXT), "*" (anything);
    # clauses joined with & must all hold. First row that matches wins.
    W = 'mcp__director__wait_for_message'
    MG, DR, IR, OS = 'merge gating', 'decision routing', 'intake and relay', 'operator support'
    CU, FC, FR, DO = 'custody and records', 'fleet care', 'fleet reads', 'director other'

    def sig_rows(self, version='1'):
        t = lambda m, v: ('director_sig', m, v, '')
        rows = [] if version is None else [('director_sig_version', '', version, 'invented table')]
        rows += [t('all:mcp__director__wait_for_message|mcp__director__inbox_summary', 'waiting'),
                 t('bash:merge-guard', self.MG), t('bashtext:gh pr merge', self.MG),
                 t('bash:card-ingest', self.DR), t('bash:desk-snapshot&bashtext:--answers', self.DR)]
        rows += [t('tool:mcp__director__' + x, self.IR) for x in ('send_message', 'broadcast', 'report_status', 'set_presence')]
        rows += [t('bash:' + x, self.IR) for x in ('relay-log', 'route-ledger')]
        rows += [t('tool:Artifact*', self.OS)]
        rows += [t('bash:' + x, self.OS) for x in ('desk-snapshot', 'dash-writer', 'board-html', 'nav-sync', 'page-namespace',
                                                    'shelf-row', 'freebusy')]
        rows += [t('bash:' + x, self.CU) for x in ('bd', 'lane-ledger', 'draft-sweep')]
        rows += [t('tool:' + x, self.CU) for x in ('mcp__director__audit_lookup', 'Write', 'Edit')]
        rows += [t('bash:' + x, self.FC) for x in ('marvel inject', 'marvel capture', 'marvel events', 'tmux', 'composer-check',
                                                    'idle-shadow', 'unattached', 'standing-hook', 'sweep-firings', 'schedule-ack')]
        rows += [t('tool:mcp__director__list_roster', self.FR)]
        rows += [t('bash:' + x, self.FR) for x in ('marvel get', 'marvel describe', 'dsi', 'dsx', 'dws', 'dbi', 'vector-pin-drift')]
        rows += [t('*', self.DO)]
        return rows

    def sig_fixtures(self):
        b = lambda cmd: [('Bash', cmd)]
        return [
            ('waiting', [self.W]), ('waiting', [self.W, 'mcp__director__inbox_summary']),
            (self.CU, [self.W, ('Bash', 'bd list')]),
            (self.MG, b('merge-guard 12')), (self.MG, b('gh pr merge 5 --squash')), (self.MG, b('cd /x && merge-guard 12')),
            (self.MG, b('FOO=1 /usr/local/bin/merge-guard 3')), (self.MG, b('for n in 1 2; do merge-guard $n; done')),
            (self.MG, b('git log | merge-guard 1')), (self.MG, b('false || merge-guard 1')),
            (self.DR, b('card-ingest a')), (self.DR, b('desk-snapshot --answers')), (self.OS, b('desk-snapshot')),
            (self.IR, ['mcp__director__send_message']), (self.IR, ['mcp__director__broadcast']),
            (self.IR, ['mcp__director__report_status']), (self.IR, ['mcp__director__set_presence']),
            (self.IR, b('relay-log tail')), (self.IR, b('route-ledger x')),
            (self.OS, ['Artifact']), (self.OS, ['ArtifactData']), (self.OS, b('dash-writer x')), (self.OS, b('board-html x')),
            (self.OS, b('nav-sync')), (self.OS, b('page-namespace x')), (self.OS, b('shelf-row x')), (self.OS, b('freebusy')),
            (self.CU, b('bd ready')), (self.CU, b('lane-ledger x')), (self.CU, b('draft-sweep')),
            (self.CU, ['mcp__director__audit_lookup']), (self.CU, ['Write']), (self.CU, ['Edit']),
            (self.FC, b('marvel inject s hi')), (self.FC, b('marvel capture s')), (self.FC, b('marvel events')),
            (self.FC, b('tmux ls')), (self.FC, b('composer-check')), (self.FC, b('idle-shadow')), (self.FC, b('unattached')),
            (self.FC, b('standing-hook')), (self.FC, b('sweep-firings')), (self.FC, b('schedule-ack')),
            (self.FR, ['mcp__director__list_roster']), (self.FR, b('marvel get seats')), (self.FR, b('marvel describe s')),
            (self.FR, b('dsi')), (self.FR, b('dsx')), (self.FR, b('dws')), (self.FR, b('dbi')), (self.FR, b('vector-pin-drift')),
            (self.DO, ['Read']), (self.DO, ['Grep']), (self.DO, b('ls -l')), (self.DO, b('marvelous inject')),
            (self.DO, b('echo bd')),
        ]

    def sig_run(self, fixtures, maprows, script=None):
        # One director session (it calls the director skill once; that request is "director other" through the star row).
        recs = [rec('ds', 400, '/srv/demo-orch/x', skill='director')]
        recs += [rec_use('ds', 401 + i, uses) for i, (_, uses) in enumerate(fixtures)]
        res = run(script or SCRIPT, [('ds', None, recs)], maprows=maprows)
        return res, {r['class']: int(r['requests']) for r in (res.get('by-director-class.csv') or [])}

    def test_each_signature_row_lands_in_its_class(self):
        fx = self.sig_fixtures()
        want = collections.Counter(c for c, _ in fx)
        want[self.DO] += 1
        res, got = self.sig_run(fx, self.sig_rows())
        self.assertEqual(got, dict(want))

    def test_the_first_matching_row_wins_so_reordering_the_table_changes_the_answer(self):
        fx = [(self.MG, [('Bash', 'bd list && merge-guard 1')])]
        res, got = self.sig_run(fx, self.sig_rows())
        self.assertEqual(got, {self.MG: 1, self.DO: 1})
        rows = self.sig_rows()
        custody = [r for r in rows if r[1] == 'bash:bd'][0]
        rows.remove(custody)
        rows.insert(1, custody)
        res, got = self.sig_run(fx, rows)
        self.assertEqual(got, {self.CU: 1, self.DO: 1})

    def test_command_text_is_read_and_not_kept(self):
        fx = [(self.MG, [('Bash', 'echo SECRETWORD123 | merge-guard 1')])]
        res, got = self.sig_run(fx, self.sig_rows())
        self.assertEqual(got, {self.MG: 1, self.DO: 1})
        self.assertNotIn('SECRETWORD123', json.dumps(res))

    RESIDUAL = 'no class (no tool call in the session)'
    SEND, ROSTER = 'mcp__director__send_message', 'mcp__director__list_roster'

    def inherit_run(self, files, script=None):
        """files: list of (file name, [(second, uses)]); every request belongs to one director session, ds, which is
        a director session by tool-call majority. A request with an empty uses list is text-only."""
        sessions = []
        n = 500
        for fname, reqs in files:
            recs = []
            for sec, uses in reqs:
                n += 1
                recs.append(rec_use('ds', n, uses, ts='2026-10-05T10:00:%02dZ' % sec))
            sessions.append((fname, None, recs))
        res = run(script or SCRIPT, sessions, maprows=self.sig_rows())
        cls = {r['class']: int(r['requests']) for r in (res.get('by-director-class.csv') or [])}
        inh = {(r['class'], r['direction']): int(r['requests']) for r in (res.get('by-director-inheritance.csv') or [])}
        return cls, inh

    def test_a_text_only_request_takes_the_class_of_the_next_tool_request(self):
        # stream order: send_message, text only, list_roster. The text-only request is between them and takes the next.
        cls, inh = self.inherit_run([('ds', [(1, [self.SEND]), (2, []), (3, [self.ROSTER])])])
        self.assertEqual(cls, {self.IR: 1, self.FR: 2})
        self.assertEqual(inh, {(self.IR, 'direct'): 1, (self.FR, 'direct'): 1, (self.FR, 'next'): 1})

    def test_a_leading_text_only_request_takes_the_next_class_not_a_previous_one(self):
        cls, inh = self.inherit_run([('ds', [(1, []), (2, [self.ROSTER]), (3, [self.SEND])])])
        self.assertEqual(cls, {self.FR: 2, self.IR: 1})
        self.assertEqual(inh, {(self.FR, 'direct'): 1, (self.FR, 'next'): 1, (self.IR, 'direct'): 1})

    def test_a_trailing_text_only_request_takes_the_previous_class(self):
        cls, inh = self.inherit_run([('ds', [(1, [self.SEND]), (2, [self.SEND]), (3, [])])])
        self.assertEqual(cls, {self.IR: 3})
        self.assertEqual(inh, {(self.IR, 'direct'): 2, (self.IR, 'previous'): 1})

    def test_a_stream_with_no_tool_request_takes_the_residual(self):
        # file dsb holds only text-only requests of session ds; the tool calls that make ds a director session are in file ds.
        cls, inh = self.inherit_run([('ds', [(1, [self.SEND])]), ('dsb', [(2, []), (3, [])])])
        self.assertEqual(cls, {self.IR: 1, self.RESIDUAL: 2})
        self.assertEqual(inh, {(self.IR, 'direct'): 1, (self.RESIDUAL, 'none'): 2})

    HUB, DIRACT = 'hub wait (bus polling)', 'director sessions (coordination)'
    REQ = (10 + 100 + 5) * 10000    # micro-dollars of one fixture request: input, cache read and output tokens at 10000 each

    def bridge_run(self, script=None):
        W = 'mcp__director__wait_for_message'
        sessions = [('b1', 'acme-builder-claude-g1-0', [rec('b1', 601, tools=[W]), rec('b1', 602, tools=[W])]),
                    ('ds', None, [rec_use('ds', 610, [W]), rec_use('ds', 611, [W]), rec_use('ds', 612, [W]),
                                  rec_use('ds', 613, [self.SEND])])]
        res = run(script or SCRIPT, sessions)
        b = {(r['line'], r['row']): (int(r['requests']), int(r['usd_micro'])) for r in (res.get('director-wait-bridge.csv') or [])}
        act = collections.Counter()
        for r in res['axes-rows.csv']:
            act[r['activity']] += int(r['requests'])
        return b, act

    MOVED = 'moved from hub wait to director sessions'

    def test_director_waits_move_out_of_hub_wait_with_a_bridge_that_balances_to_the_micro_dollar(self):
        b, act = self.bridge_run()
        R = self.REQ
        self.assertEqual(b, {('memo', self.HUB): (5, 5 * R), ('memo', self.DIRACT): (1, R),
                             ('new', self.HUB): (2, 2 * R), ('new', self.DIRACT): (4, 4 * R),
                             ('bridge', self.MOVED): (3, 3 * R)})
        # new rows plus the bridge equal the old rows, and the two totals are equal
        self.assertEqual(b[('new', self.HUB)][1] + b[('bridge', self.MOVED)][1], b[('memo', self.HUB)][1])
        self.assertEqual(b[('new', self.DIRACT)][1] - b[('bridge', self.MOVED)][1], b[('memo', self.DIRACT)][1])
        self.assertEqual(act[self.HUB], 2)
        self.assertEqual(act[self.DIRACT], 4)

    def noid_rows(self, script):
        # No id and no uuid on any record: the key must still tell the three messages apart. Counted once each, the
        # session holds two director calls of three and is a director session; keyed by position alone it holds one call.
        def r(n, name):
            return {'type': 'assistant', 'timestamp': '2026-10-05T10:00:00Z', 'sessionId': 'dn', 'cwd': '/srv/demo-orch/x',
                    'requestId': 'r%s' % n, 'message': {'id': 'm%s' % n, 'model': MODEL, 'content': [{'type': 'tool_use', 'name': name}],
                    'usage': {'input_tokens': 10, 'output_tokens': 5, 'cache_read_input_tokens': 100, 'cache_creation_input_tokens': 0}}}
        s = [('dn', None, [r(701, 'Bash'), r(702, self.SEND), r(703, self.SEND)])]
        return {x['session_hash']: (x['class'], x['director_rule']) for x in run(script, s)['unattributed-sessions.csv']}

    def test_a_tool_use_block_without_an_id_is_keyed_by_its_message_too(self):
        self.assertEqual(self.noid_rows(SCRIPT), {hashlib.sha256(b'dn').hexdigest()[:12]: (self.DIR, 'mcp-majority')})

    def test_bridge_and_key_mutants_turn_red(self):
        good, _ = self.bridge_run()
        for a, b in (("    if dirfirst and role=='-' and cls==C_DIR: return cls\n", "    pass\n"),
                     ("if a_old==HUBWAIT and a==C_DIR:", "if False:"),
                     ("for line,act_name in (('memo',a_old),('new',a)):", "for line,act_name in (('memo',a),('new',a)):")):
            self.assertNotEqual(self.bridge_run(self.mutant(a, b))[0], good, a)
        for a, b in (("else ('noid',mid,r.get('uuid'),i)", "else ('noid',r.get('uuid'),i)"),):
            m = self.mutant(a, b)
            self.assertNotEqual(self.noid_rows(m), self.noid_rows(SCRIPT), a)

    UNITS = [('unit_cost', 'per relay', 'intake and relay', 'relay-log entries'),
             ('unit_cost', 'per merge', 'merge gating', 'GitHub merged-PR list'),
             ('unit_cost', 'per operator decision', 'decision routing', 'desk-snapshot answered cards'),
             # a value that is not a class says the status: "pending" (a source not built yet) or "n/a" (no source exists)
             ('unit_cost', 'per ask closed', 'pending', 'asks.jsonl joined to the workstream ledger'),
             ('unit_cost', 'per stall cleared', 'n/a', 'none: nothing records a stall cleared')]

    def unit_run(self, counts, units=None, script=None):
        # director session ds: 3 relays, 2 merge-guard calls, 1 card-ingest call and the director skill call
        recs = [rec('ds', 800, '/srv/demo-orch/x', skill='director')]
        uses = [[self.SEND]] * 3 + [[('Bash', 'merge-guard 1')]] * 2 + [[('Bash', 'card-ingest a')]]
        recs += [rec_use('ds', 801 + i, u) for i, u in enumerate(uses)]
        res = run(script or SCRIPT, [('ds', None, recs)], maprows=self.sig_rows() + (self.UNITS if units is None else units),
                  counts=counts)
        return {r['unit']: r for r in (res.get('unit-costs.csv') or [])}

    def test_unit_costs_divide_a_class_by_a_counted_denominator(self):
        R = self.REQ
        t = self.unit_run([('per relay', '2'), ('per merge', '4'), ('per operator decision', '0'), ('per stall cleared', '9')])
        self.assertEqual({u: (r['class_usd_micro'], r['denominator'], r['source'], r['unit_usd_micro']) for u, r in t.items()},
                         {'per relay': (str(3 * R), '2', 'relay-log entries', str(3 * R // 2)),
                          'per merge': (str(2 * R), '4', 'GitHub merged-PR list', str(2 * R // 4)),
                          'per operator decision': (str(R), '0', 'desk-snapshot answered cards', 'n/a'),
                          'per ask closed': ('', '', 'asks.jsonl joined to the workstream ledger', 'pending'),
                          'per stall cleared': ('', '9', 'none: nothing records a stall cleared', 'n/a')})

    def test_a_missing_unit_or_a_missing_file_prints_n_a_with_its_source_never_zero(self):
        t = self.unit_run([('per relay', '2')])
        g = lambda u, k: t.get(u, {}).get(k)
        self.assertEqual((g('per merge', 'unit_usd_micro'), g('per merge', 'source')), ('n/a', 'GitHub merged-PR list'))
        self.assertEqual((g('per operator decision', 'unit_usd_micro'), g('per operator decision', 'denominator')), ('n/a', ''))
        t = self.unit_run(None)
        self.assertEqual({u: r['unit_usd_micro'] for u, r in t.items()},
                         {'per relay': 'n/a', 'per merge': 'n/a', 'per operator decision': 'n/a',
                          'per ask closed': 'pending', 'per stall cleared': 'n/a'})
        self.assertTrue(t and '0' not in [r['unit_usd_micro'] for r in t.values()])

    ASKUNIT = [('unit_cost', 'per ask closed', 'join:asks', 'asks.jsonl, intake rows joined to close rows by ask_id')]

    def asks_rows(self):
        # synthetic rows in the asks.jsonl shapes; the text and reason fields must never reach an output
        i = lambda n, day: {'ask_id': 'I-%d' % n, 'received_at': '2026-10-%02dT10:00:00Z' % day, 'source': 'operator',
                            'text': 'SECRETTEXT%d' % n}
        c = lambda n, day, how, **kw: dict({'event': 'close', 'ask_id': 'I-%d' % n, 'closed_at': day, 'as': how, 'ref': 'where'}, **kw)
        return [i(1, 3), i(2, 4), i(3, 5), i(4, 6), i(5, 7),
                c(1, '2026-10-04T10:00:00Z', 'answered'), c(2, '2026-10-05T10:00:00Z', 'carded'),
                c(3, '2026-10-06T10:00:00Z', 'not-an-ask', reason='SECRETREASON'),
                c(1, '2026-10-09T10:00:00Z', 'answered'),          # a second close of the same ask counts once
                c(5, '2026-11-01T10:00:00Z', 'answered'),          # closed after the audit window
                c(9, '2026-10-08T10:00:00Z', 'answered'),          # a close with no intake row
                'not json at all', '{"event": "close"}']

    def ask_run(self, asks, units=None):
        recs = [rec('ds', 900, '/srv/demo-orch/x', skill='director')]
        uses = [[self.SEND]] * 3 + [[('Bash', 'merge-guard 1')]] * 2 + [[('Bash', 'card-ingest a')]]
        recs += [rec_use('ds', 901 + i, u) for i, u in enumerate(uses)]
        res = run(SCRIPT, [('ds', None, recs)], maprows=self.sig_rows() + (self.ASKUNIT if units is None else units), asks=asks)
        closed = {r['as']: int(r['closed']) for r in (res.get('asks-closed.csv') or [])}
        unit = {r['unit']: r for r in (res.get('unit-costs.csv') or [])}
        return res, closed, unit

    def test_the_asks_join_yields_the_closed_count_and_the_per_ask_cost(self):
        res, closed, unit = self.ask_run(self.asks_rows())
        self.assertEqual(closed, {'all': 3, 'answered': 1, 'carded': 1, 'not-an-ask': 1})
        u = unit.get('per ask closed', {})
        self.assertEqual((u.get('class'), u.get('denominator'), u.get('unit_usd_micro')), ('all director classes', '3', str(round(7 * self.REQ / 3))))
        text = json.dumps(res)
        for word in ('SECRETTEXT', 'SECRETREASON'):
            self.assertNotIn(word, text)

    def test_without_the_asks_file_the_cell_prints_pending(self):
        res, closed, unit = self.ask_run(None)
        self.assertEqual(closed, {})
        self.assertNotIn('asks-closed.csv', res)
        self.assertEqual(unit.get('per ask closed', {}).get('unit_usd_micro'), 'pending')

    def test_an_asks_file_with_no_closes_prints_n_a_with_its_source_not_zero(self):
        res, closed, unit = self.ask_run([r for r in self.asks_rows() if isinstance(r, dict) and r.get('event') != 'close'])
        self.assertEqual(closed, {'all': 0})
        u = unit.get('per ask closed', {})
        self.assertEqual((u.get('unit_usd_micro'), u.get('source')), ('n/a', 'asks.jsonl, intake rows joined to close rows by ask_id'))


    def test_unit_cost_mutants_turn_red(self):
        counts = [('per relay', '2'), ('per operator decision', '0'), ('per stall cleared', '9')]   # per merge is absent
        good = self.unit_run(counts)
        for a, b, n in (("round(usd/cnt) if cnt else 'n/a'", "round(usd/cnt) if cnt else 0", 2),
                        ("'pending' if val=='pending' else 'n/a'", "'n/a'", 1),
                        ("usd=dirrows[val]['usd_micro'] if val in dirrows else 0", "usd=0", 1),
                        ("cnt=UNIT_COUNTS.get(unit)", "cnt=UNIT_COUNTS.get(unit,1)", 1)):
            self.assertNotEqual(self.unit_run(counts, script=self.mutant(a, b, n)), good, a)

    def test_asks_join_mutants_turn_red(self):
        good = self.ask_run(self.asks_rows())[1]
        for a, b in (("at.startswith(WINDOW))", "True)"), ("if a in intake and", "if True and")):
            m = self.mutant(a, b)
            res = run(m, [('ds', None, [rec('ds', 900, '/srv/demo-orch/x', skill='director')])], maprows=self.sig_rows() + self.ASKUNIT,
                      asks=self.asks_rows())
            closed = {r['as']: int(r['closed']) for r in (res.get('asks-closed.csv') or [])}
            self.assertNotEqual(closed, good, a)

    def test_the_unit_table_is_data_so_a_rename_in_the_map_moves_the_label(self):
        units = [('unit_cost', 'per message passed on', 'intake and relay', 'relay-log entries')]
        t = self.unit_run([('per message passed on', '3')], units)
        self.assertEqual({u: r['unit_usd_micro'] for u, r in t.items()}, {'per message passed on': str(self.REQ)})


        cases = [([('ds', [(1, [self.SEND]), (2, []), (3, [self.ROSTER])])]),
                 ([('ds', [(1, []), (2, [self.ROSTER]), (3, [self.SEND])])]),
                 ([('ds', [(1, [self.SEND]), (2, [self.SEND]), (3, [])])]),
                 ([('ds', [(1, [self.SEND])]), ('dsb', [(2, []), (3, [])])]),
                 ([('ds', [(1, [self.SEND]), (2, []), (3, []), (4, [self.ROSTER])])])]
        good = [self.inherit_run(c) for c in cases]
        for a, b in (("            if own[i] is not None: nxt=own[i]\n", "            nxt=own[i]\n"),
                     ("elif nx[i] is not None: e['dclass'],e['dsrc']=nx[i],'next'", "elif prv is not None: e['dclass'],e['dsrc']=prv,'previous'"),
                     ("            elif prv is not None: e['dclass'],e['dsrc']=prv,'previous'\n", "            elif False: pass\n"),
                     ("else: e['dclass'],e['dsrc']=RESIDUAL,'none'", "else: e['dclass'],e['dsrc']='unclassed','none'"),
                     ("for i in range(len(L)-1,-1,-1):", "for i in range(len(L)):")):
            m = self.mutant(a, b)
            self.assertNotEqual([self.inherit_run(c, m) for c in cases], good, a)

    def test_signature_mutants_turn_red(self):
        fx = self.sig_fixtures()
        want = collections.Counter(c for c, _ in fx)
        want[self.DO] += 1
        for a, b in (("for s in SEGSPLIT.split(cmd):", "for s in [cmd]:"),
                     ("w[0]=w[0].rsplit('/',1)[-1]; res.append", "res.append"),
                     ("while w and w[0] in ('do','then','else','{','(','!'): w=w[1:]", "pass"),
                     ("    for cl,v in DSIG:\n", "    for cl,v in reversed(DSIG):\n"),
                     ("if all(clause_hits(c,blocks) for c in cl)", "if any(clause_hits(c,blocks) for c in cl)"),
                     ("return bool(names) and set(names)<=set(arg.split('|'))", "return bool(set(names)&set(arg.split('|')))"),
                     ("return bool(w) and any(s[:len(w)]==w", "return bool(w) and any(w[0] in s")):
            res, got = self.sig_run(fx, self.sig_rows(), script=self.mutant(a, b))
            self.assertNotEqual(got, dict(want), a)

    def test_the_table_version_is_printed_by_every_audit(self):
        res, _ = self.sig_run([], self.sig_rows('7'))
        self.assertIn('director_sig_version=7\n', res['attribution-meta.txt'])
        res, _ = self.sig_run([], self.sig_rows(None))
        self.assertIn('director_sig_version=unversioned\n', res['attribution-meta.txt'])

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

    # Round 1 fixes: live git wins while the path exists, a bad sidecar is moved aside, concurrent writers keep each other's rows.
    GIT = ['git', '-c', 'user.name=demo', '-c', 'user.email=demo@example.test']

    def make_repo(self, d, name, origin):
        main = os.path.join(d, name)
        for cmd in (self.GIT + ['init', '-q', main], self.GIT + ['-C', main, 'commit', '-q', '--allow-empty', '-m', 'init'],
                    self.GIT + ['-C', main, 'remote', 'add', 'origin', 'https://example.test/%s.git' % origin]):
            subprocess.run(cmd, check=True, capture_output=True)
        return main

    def add_wt(self, main, path):
        subprocess.run(self.GIT + ['-C', main, 'worktree', 'add', '-q', path, '-b', 'b' + str(abs(hash(path)))], check=True, capture_output=True)

    def rm_wt(self, main, path):
        subprocess.run(self.GIT + ['-C', main, 'worktree', 'remove', '--force', path], check=True, capture_output=True)

    def two_sessions(self, script, cwd, cache):
        s = [('s1', None, [rec('s1', 310, cwd=cwd)]), ('s2', None, [rec('s2', 311, cwd=cwd)])]
        return sorted((r['repo'], r['requests']) for r in run(script, s, cache=cache)['by-repo.csv'])

    def reused_path(self, script):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        a = self.make_repo(d, 'main-a', 'demo-org/repo-a'); bb = self.make_repo(d, 'main-b', 'demo-org/repo-b')
        slot = os.path.join(d, 'slot1'); cache = os.path.join(d, 'cache.csv')
        self.add_wt(a, slot)
        first = self.two_sessions(script, slot, cache)
        self.rm_wt(a, slot)
        self.add_wt(bb, slot)       # the same path, now a worktree of another repo
        second = self.two_sessions(script, slot, cache)
        self.rm_wt(bb, slot)
        third = self.two_sessions(script, slot, cache)   # path gone: the sidecar holds the latest repo
        return first, second, third

    def test_reused_path_follows_the_live_repo(self):
        first, second, third = self.reused_path(SCRIPT)
        self.assertEqual(first, [('demo-org/repo-a', '2')])
        self.assertEqual(second, [('demo-org/repo-b', '2')])
        self.assertEqual(third, [('demo-org/repo-b', '2')])

    def test_reused_path_mutant_that_reads_the_cache_first_turns_red(self):
        m = self.mutant("    if v is None and cwd and os.path.isdir(cwd):", "    if v is None and cwd and cwd not in RCACHE and os.path.isdir(cwd):")
        self.assertEqual(self.reused_path(m)[1], [('demo-org/repo-a', '2')])

    def bad_sidecar(self, script):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        main = self.make_repo(d, 'main-a', 'demo-org/repo-a'); wt = os.path.join(d, 'wt1'); self.add_wt(main, wt)
        cache = os.path.join(d, 'cache.csv')
        bad = 'cwd,repo,first_seen\n/srv/demo-old/x,demo-org/old,2026-10-01T00:00:00+00:00\n/srv/demo-nul/\x00y,demo-org/nul,2026-10-01T00:00:00+00:00\n'
        with open(cache, 'w') as fh:
            fh.write(bad)
        res = run(script, [('w1', None, [rec('w1', 320, cwd=wt)])], cache=cache)
        return d, cache, bad, res

    def test_unparsable_sidecar_is_moved_aside_not_replaced(self):
        d, cache, bad, res = self.bad_sidecar(SCRIPT)
        aside = glob.glob(cache + '.bad-*')
        self.assertEqual(len(aside), 1)
        with open(aside[0]) as fh:
            self.assertEqual(fh.read(), bad)
        self.assertEqual(len([l for l in res['_stderr'].splitlines() if l.strip()]), 1)
        self.assertIn('moved aside', res['_stderr'])
        with open(cache) as fh:
            self.assertEqual([r['repo'] for r in csv.DictReader(fh)], ['demo-org/repo-a'])
        self.assertEqual([r['repo'] for r in res['by-repo.csv']], ['demo-org/repo-a'])

    def test_sidecar_mutant_that_does_not_move_it_aside_turns_red(self):
        m = self.mutant("    try: os.replace(path,aside)\n", "    try: pass\n")
        d, cache, bad, res = self.bad_sidecar(m)
        self.assertEqual(glob.glob(cache + '.bad-*'), [])

    def concurrent_rows(self, script, writers=12):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        cache = os.path.join(d, 'cache.csv')
        cwds = [self.make_repo(d, 'r%d' % i, 'demo-org/r%d' % i) for i in range(writers)]
        def one(c):
            return run(script, [('c1', None, [rec('c1', 330, cwd=c)])], cache=cache)
        with concurrent.futures.ThreadPoolExecutor(max_workers=writers) as ex:
            list(ex.map(one, cwds))
        with open(cache) as fh:
            return sorted(r['cwd'] for r in csv.DictReader(fh)), sorted(cwds)

    def test_concurrent_runs_keep_each_others_rows(self):
        got, want = self.concurrent_rows(SCRIPT)
        self.assertEqual(got, want)

    def test_concurrent_mutant_that_writes_its_own_snapshot_turns_red(self):
        m = self.mutant("            cur,why=read_repo_cache(CACHEF)\n", "            cur,why=dict(RCACHE),None\n")
        for _ in range(5):
            got, want = self.concurrent_rows(m)
            if got != want:
                return
        self.fail('the mutant lost no row in 5 rounds of 12 writers')

    # Lows from the approval of critic#42: blank lines in the sidecar, and a path where git gives no answer.
    def blank_lines_sidecar(self, script):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        cache = os.path.join(d, 'cache.csv')
        gone = os.path.join(d, 'gone-worktree')
        text = 'cwd,repo,first_seen\n\n%s,demo-org/kept,2026-10-01T00:00:00+00:00\n\n\n' % gone
        with open(cache, 'w') as fh:
            fh.write(text)
        res = run(script, [('g1', None, [rec('g1', 340, cwd=gone)])], cache=cache)
        return cache, text, res

    def test_blank_lines_in_the_sidecar_are_skipped(self):
        cache, text, res = self.blank_lines_sidecar(SCRIPT)
        self.assertEqual([r['repo'] for r in res['by-repo.csv']], ['demo-org/kept'])
        self.assertEqual(glob.glob(cache + '.bad-*'), [])
        self.assertEqual(res['_stderr'], '')
        with open(cache) as fh:
            self.assertEqual(fh.read(), text)

    def test_blank_line_mutant_that_quarantines_turns_red(self):
        m = self.mutant("            if len(row)<=1 and not ''.join(row).strip(): continue   # a blank line is not a row\n", "")
        cache, text, res = self.blank_lines_sidecar(m)
        self.assertEqual(len(glob.glob(cache + '.bad-*')), 1)

    def git_fails_on_existing_path(self, script):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        main = self.make_repo(d, 'main-a', 'demo-org/repo-a'); slot = os.path.join(d, 'slot1'); cache = os.path.join(d, 'cache.csv')
        self.add_wt(main, slot)
        first = self.two_sessions(script, slot, cache)
        self.rm_wt(main, slot)
        os.mkdir(slot)                 # the path exists again but is no repository: git gives no answer
        return first, self.two_sessions(script, slot, cache)

    def test_sidecar_answers_when_git_fails_on_an_existing_path(self):
        first, second = self.git_fails_on_existing_path(SCRIPT)
        self.assertEqual(first, [('demo-org/repo-a', '2')])
        self.assertEqual(second, [('demo-org/repo-a', '2')])

    def test_fallback_mutant_that_reports_unknown_turns_red(self):
        m = self.mutant("    if v is None and cwd in RCACHE: v=RCACHE[cwd][0]   # the path is gone, or git gave no answer for it\n",
                        "    if v is None and cwd in RCACHE and not os.path.isdir(cwd): v=RCACHE[cwd][0]\n")
        self.assertEqual(self.git_fails_on_existing_path(m)[1], [('unknown', '2')])

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

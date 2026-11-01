#!/usr/bin/env python3
# Transcript ledger with two extra axes: repo and goal. Same counting, cold-start, cache-death and
# pricing rules as ledger-s10.py (which stays unchanged, so October 2026 stays reproducible).
# Adds to every request: repo, from the record's cwd (path rules in the map table first, then the
# git common dir and its origin remote, so worktrees map to their parent repo, else "unknown");
# and goal, from the same map table. The script names no repo, team or goal; all of them live in
# the map table, which the operator edits. Writes aggregate rows only. No transcript text out.
# Usage: python3 -I ledger-s10-axes.py OUT_DIR PRICES_JSON CLUSTER_LABEL MAP_CSV [PROJECTS_ROOT]
# MAP_CSV columns: kind,match,value,note. Kinds, applied in this order for goal:
#   activity       match = activity name                 -> goal (applies to every repo)
#   activity_repo  match = "activity|repo"               -> goal
#   team_first     match = team                          -> goal (before repo: a team whose work is its goal wherever it runs)
#   repo           match = repo (owner/name)             -> goal
#   team           match = team                          -> goal
#   path           match = regex on the cwd, home as ~    -> repo (applied before git)
# Unmatched goal is "unmapped"; unmatched repo is "unknown". Both are reported as their own rows.
# git runs in every cwd that no path rule claims, so the map's path rules must claim any root git
# must not run in (quarantine and other read-only material). Git calls run with GIT_* cleared, so an
# inherited GIT_DIR cannot redirect them; a git call that hangs past its timeout maps that cwd to unknown.
import json,glob,os,re,collections,csv,sys
from datetime import datetime
out=sys.argv[1]; P=json.load(open(sys.argv[2])); CLUSTER=sys.argv[3]; MAPF=sys.argv[4]
root=os.path.expanduser(sys.argv[5] if len(sys.argv)>5 else '~/.claude/projects')
import subprocess
HOME=os.path.expanduser('~')
MAP=collections.defaultdict(list)
for row in csv.DictReader(open(MAPF)):
    MAP[row['kind'].strip()].append((row['match'].strip(),row['value'].strip()))
PATHR=[(re.compile(m),v) for m,v in MAP['path']]
GOAL={k:dict(MAP[k]) for k in ('activity','activity_repo','team_first','repo','team')}
SEAT=re.compile(r'^([a-z0-9]+(?:-[a-z0-9]+)*?)-g(\d+)-(\d+)$')
WAIT={'mcp__director__wait_for_message','mcp__director__inbox_summary'}
ROLES=['research-supervisor','supervisor','builder','reviewer','architect','envoy','author','critic']
names={}; msgs={}; rid_n=set(); recs=0
for f in glob.glob(root+'/**/*.jsonl',recursive=True):
    sub='/subagents/' in f
    with open(f,'rb') as fh:
        for line in fh:
            try: r=json.loads(line)
            except Exception: continue
            t=r.get('type')
            if t=='agent-name' and r.get('agentName'): names[r.get('sessionId')]=r['agentName']; continue
            if t!='assistant': continue
            ts=r.get('timestamp') or ''
            if not ts.startswith('2026-10'): continue
            recs+=1; m=r.get('message') or {}; mid=m.get('id') or ('nomid:'+str(r.get('uuid'))); rid_n.add(r.get('requestId'))
            u=m.get('usage') or {}; cc=u.get('cache_creation') or {}
            tools={b.get('name') for b in (m.get('content') or []) if isinstance(b,dict) and b.get('type')=='tool_use'}
            e=msgs.get(mid)
            if e is None:
                e=msgs[mid]={'cwd':r.get('cwd') or '','ts':ts,'model':m.get('model'),'sid':r.get('sessionId'),'stream':f,'side':bool(r.get('isSidechain')) or sub,
                  'in':u.get('input_tokens') or 0,'cr':u.get('cache_read_input_tokens') or 0,'cw':u.get('cache_creation_input_tokens') or 0,
                  'cw5':cc.get('ephemeral_5m_input_tokens'),'cw1':cc.get('ephemeral_1h_input_tokens') or 0,'out':u.get('output_tokens') or 0,
                  'err':bool(r.get('isApiErrorMessage') or r.get('apiErrorStatus')),'tools':set(),'usage_differs':False}
            else:
                if (u.get('output_tokens') or 0)!=e['out'] or (u.get('cache_read_input_tokens') or 0)!=e['cr']: e['usage_differs']=True
                e['out']=max(e['out'],u.get('output_tokens') or 0)
            e['tools']|=tools
def seat(sid):
    n=names.get(sid)
    if not n: return ('(no seat name)','-','-')
    mm=SEAT.match(n)
    if not mm: return ('(named, not a seat label)','-','-')
    b=mm.group(1); role=next((x for x in ROLES if b.endswith(x)),b.split('-')[-1]); team=b[:-len(role)-1] if len(b)>len(role) else '-'
    return (n,team,role)
# per stream ordering for cold start / cache death
streams=collections.defaultdict(list)
for mid,e in msgs.items(): streams[e['stream']].append(e)
def T(s): return datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()
for s,L in streams.items():
    L.sort(key=lambda e:e['ts']); prev=None
    for e in L:
        cw5=e['cw5'] if e['cw5'] is not None else max(e['cw']-e['cw1'],0); e['cw5v']=cw5
        e['undetermined']= (e['cr']==0 and e['cw']==0 and not e['err'] and e['model']!='<synthetic>')
        e['cold']= (e['cw']>0 and e['cr']==0 and not e['err'])
        e['death']=False
        if prev:
            ttl=3600 if prev['cw1']>0 else 300
            prompt=prev['in']+prev['cr']+prev['cw']
            if T(e['ts'])-T(prev['ts'])>ttl and prompt>0 and e['cw']>=0.5*prompt: e['death']=True
        prev=e
def act(e,role):
    if e['model']=='<synthetic>': return 'synthetic'
    if e['err']: return 'api errors'
    if e['side']: return 'subagent work'
    if e['tools'] and e['tools']<=WAIT: return 'hub wait (bus polling)'
    if role=='-': return 'operator direct or unnamed'
    return {'builder':'building','reviewer':'review','research-supervisor':'research','supervisor':'supervision and relay','architect':'design','author':'design','envoy':'triage','critic':'review'}.get(role,'other seat roles')
_rc={}
GITENV={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
def git(d,*a):
    try: r=subprocess.run(['git','--no-optional-locks','-c','core.fsmonitor=false','-C',d,*a],capture_output=True,timeout=20,env=GITENV)
    except subprocess.TimeoutExpired: return ''
    return r.stdout.decode('utf-8','replace').strip() if r.returncode==0 else ''
def repo_of(cwd):
    if cwd in _rc: return _rc[cwd]
    k=cwd.replace(HOME,'~',1) if cwd.startswith(HOME) else cwd
    v=next((val for rx,val in PATHR if rx.search(k)),None)
    if v is None and cwd and os.path.isdir(cwd):
        common=git(cwd,'rev-parse','--path-format=absolute','--git-common-dir')
        if common:
            top=common[:-5] if common.endswith('/.git') else common
            url=git(top,'remote','get-url','origin')
            if url:
                u=re.sub(r'\.git$','',url.rstrip('/')); parts=re.split(r'[:/]',u); v='/'.join(parts[-2:])
            else: v=os.path.basename(top.rstrip('/'))
    _rc[cwd]=v or 'unknown'; return _rc[cwd]
def goal_of(a,repo,team):
    for key,src in ((a,'activity'),(a+'|'+repo,'activity_repo'),(team,'team_first'),(repo,'repo'),(team,'team')):
        if key in GOAL[src]: return GOAL[src][key]
    return 'unmapped'
rows=collections.defaultdict(lambda:collections.Counter())
for e in msgs.values():
    if e['model']=='<synthetic>': continue
    lab,team,role=seat(e['sid']); a=act(e,role); p=P.get(e['model']); repo=repo_of(e['cwd']); goal=goal_of(a,repo,team)
    k=(e['ts'][:10],repo,goal,a,team,role)
    c=rows[k]; c['requests']+=1
    if p: c['usd_micro']+=round((e['in']*p['in']+e['cw5v']*p['cw5']+e['cw1']*p['cw1']+e['cr']*p['cr']+e['out']*p['out']))
    else: c['unpriced']+=1
def write(name,keyf,hdr):
    t=collections.defaultdict(lambda:collections.Counter())
    for k,c in rows.items(): t[keyf(k)].update(c)
    with open(out+'/'+name,'w',newline='') as fh:
        w=csv.writer(fh); w.writerow(['cluster',*hdr,'requests','unpriced','list_usd'])
        for k in sorted(t,key=lambda k:-t[k]['usd_micro']): w.writerow([CLUSTER,*k,t[k]['requests'],t[k]['unpriced'],round(t[k]['usd_micro']/1e6,2)])
write('axes-rows.csv',lambda k:k,['day','repo','goal','activity','team','role'])
write('by-repo.csv',lambda k:(k[1],),['repo'])
write('by-goal.csv',lambda k:(k[2],),['goal'])
write('repo-by-activity.csv',lambda k:(k[1],k[3]),['repo','activity'])
tot=collections.Counter()
for c in rows.values(): tot.update(c)
meta={'requests_priced_or_not':tot['requests'],'unpriced':tot['unpriced'],'list_usd':round(tot['usd_micro']/1e6,2),
 'unknown_repo_usd':round(sum(c['usd_micro'] for k,c in rows.items() if k[1]=='unknown')/1e6,2),
 'unmapped_goal_usd':round(sum(c['usd_micro'] for k,c in rows.items() if k[2]=='unmapped')/1e6,2),'distinct_cwds':len(_rc)}
json.dump(meta,open(out+'/axes-meta.json','w'),indent=1); print(json.dumps(meta,indent=1))

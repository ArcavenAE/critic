#!/usr/bin/env python3
# Transcript ledger with two extra axes: repo and goal. Same counting, cold-start, cache-death and
# pricing rules as ledger-s10.py (which stays unchanged, so October 2026 stays reproducible).
# Adds to every request: repo, from the record's cwd (path rules in the map table first, then the
# git common dir and its origin remote, so worktrees map to their parent repo, else "unknown");
# and goal, from the same map table. The script names no repo, team or goal; all of them live in
# the map table, which the operator edits. Writes aggregate rows only. No transcript text out.
# Usage: python3 -I ledger-s10-axes.py OUT_DIR PRICES_JSON CLUSTER_LABEL MAP_CSV [PROJECTS_ROOT [MARVEL_LOG_DIR]]
# MAP_CSV columns: kind,match,value,note. Kinds, applied in this order for goal:
#   activity       match = activity name                 -> goal (applies to every repo)
#   activity_repo  match = "activity|repo"               -> goal
#   team_first     match = team                          -> goal (before repo: a team whose work is its goal wherever it runs)
#   repo           match = repo (owner/name)             -> goal
#   team           match = team                          -> goal
#   path           match = regex on the cwd, home as ~    -> repo (applied before git)
#   own            match = regex on the cwd, home as ~    -> operator own work (outside fleet); value unused
#   own_skill      match = skill name                      -> operator own work (outside fleet); value unused
#   orchestrator   match = regex on the cwd, home as ~    -> external orchestration (outside marvel); value = the
#                                                           orchestrator name the project dir is rolled up to
# Unmatched goal is "unmapped"; unmatched repo is "unknown". Both are reported as their own rows.
# git runs in every cwd that no path rule claims, so the map's path rules must claim any root git
# must not run in (quarantine and other read-only material). Git calls run with GIT_* cleared, so an
# inherited GIT_DIR cannot redirect them; a git call that hangs past its timeout maps that cwd to unknown.
# Seat attribution: the agent-name record in the transcript wins. When a session has none (a plain claude
# launch writes none), the seat comes from marvel's daemon log, where each launch is one line
# "session <workspace>/<seat> exec: ... '--session-id' '<uuid>'" (daemon.log and its rotated copies, gzip
# too, in MARVEL_LOG_DIR, default ~/.marvel/log). Each session is labelled with its method: agent-name,
# launch-log or none. A session with no seat is split by rule, in this order, and nothing is classed as
# operator work without a positive rule: own (kind own or own_skill), external orchestration (kind
# orchestrator), else "no seat name (unattributed)". A harness token (-claude, -codex, -opencode, -crush,
# -goose) ends a seat base before the role is matched. unattributed-sessions.csv rolls each project dir up to
# an orchestrator name, own, temp or home; it never prints a raw path. signin_hash in attribution-meta.txt is
# an unsalted 12-hex sha256 of the lowercased address: it tells two config dirs apart, and anyone who can
# guess the address can confirm it, so it is a pseudonym and not safe to publish. Writes aggregates only, no transcript text.
import json,glob,os,re,collections,csv,sys,gzip,hashlib
from datetime import datetime
out=sys.argv[1]; P=json.load(open(sys.argv[2])); CLUSTER=sys.argv[3]; MAPF=sys.argv[4]
root=os.path.expanduser(sys.argv[5] if len(sys.argv)>5 else '~/.claude/projects')
LOGDIR=os.path.expanduser(sys.argv[6] if len(sys.argv)>6 else '~/.marvel/log')
import subprocess
HOME=os.path.expanduser('~')
MAP=collections.defaultdict(list)
for row in csv.DictReader(open(MAPF)):
    MAP[row['kind'].strip()].append((row['match'].strip(),row['value'].strip()))
PATHR=[(re.compile(m),v) for m,v in MAP['path']]
OWNR=[re.compile(m) for m,v in MAP['own']]
OWNSKILL={m for m,v in MAP['own_skill']}
ORCHR=[(re.compile(m),v) for m,v in MAP['orchestrator']]
GOAL={k:dict(MAP[k]) for k in ('activity','activity_repo','team_first','repo','team')}
SEAT=re.compile(r'^([a-z0-9]+(?:-[a-z0-9]+)*?)-g(\d+)-(\d+)$')
WAIT={'mcp__director__wait_for_message','mcp__director__inbox_summary'}
ROLES=['research-supervisor','supervisor','builder','reviewer','test-architect','architect','envoy','author','critic']
HARNESS=('claude','codex','opencode','crush','goose')
LAUNCH=re.compile(r"session [^/\s]+/(\S+) exec: .*'--session-id' '([0-9a-fA-F-]{36})'")
def H(x): return hashlib.sha256((x or '').encode()).hexdigest()[:12]
def parse_label(n):
    # (base, team, role) for a seat label, or None when it is not one. One trailing harness token ends the
    # base first, so reviewer-reviewer-claude reads as team reviewer, role reviewer.
    mm=SEAT.match(n)
    if not mm: return None
    b=mm.group(1); sb=b
    for h in HARNESS:
        if sb.endswith('-'+h): sb=sb[:-len(h)-1]; break
    role=next((x for x in ROLES if sb.endswith(x)),sb.split('-')[-1])
    team=sb[:-len(role)-1] if len(sb)>len(role) else '-'
    if team.endswith('-'+role): team=team[:-len(role)-1]
    return (b,team,role)
launch={}
for lf in sorted(glob.glob(LOGDIR+'/daemon.log*')):
    try:
        with (gzip.open(lf,'rt',errors='replace') if lf.endswith('.gz') else open(lf,'r',errors='replace')) as fh:
            for line in fh:
                m=LAUNCH.search(line)
                if m: launch[m.group(2).lower()]=m.group(1)
    except Exception: continue
names={}; msgs={}; rid_n=set(); recs=0; skills=collections.defaultdict(set)
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
            for b in (m.get('content') or []):
                if isinstance(b,dict) and b.get('type')=='tool_use' and b.get('name')=='Skill' and isinstance(b.get('input'),dict) and b['input'].get('skill'): skills[r.get('sessionId')].add(str(b['input']['skill']))
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
    # (label, team, role, method, base)
    n=names.get(sid); method='agent-name'
    if not n and sid and sid.lower() in launch: n=launch[sid.lower()]; method='launch-log'
    if not n: return ('(no seat name)','-','-','none','(no seat name)')
    p=parse_label(n)
    if not p: return ('(named, not a seat label)','-','-',method,'(named, not a seat label)')
    return (n,p[1],p[2],method,p[0])
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
def act(e,role,cls):
    if e['model']=='<synthetic>': return 'synthetic'
    if e['err']: return 'api errors'
    if e['side']: return 'subagent work'
    if e['tools'] and e['tools']<=WAIT: return 'hub wait (bus polling)'
    if role=='-': return cls
    return {'builder':'building','reviewer':'review','research-supervisor':'research','supervisor':'supervision and relay','architect':'design','test-architect':'design','author':'design','envoy':'triage','critic':'review'}.get(role,'other seat roles')
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
C_OWN='operator own work (outside fleet)'; C_ORCH='external orchestration (outside marvel)'; C_NONE='no seat name (unattributed)'
def tilde(cwd): return cwd.replace(HOME,'~',1) if cwd.startswith(HOME) else cwd
first={}
for e in msgs.values():
    if e['model']=='<synthetic>': continue
    if e['sid'] not in first or e['ts']<first[e['sid']][0]: first[e['sid']]=(e['ts'],e['cwd'])
_cc={}
def rollup(k,orch,own):
    # A project dir is never printed raw: an own rule says 'own' (checked first, as uclass() does), an
    # orchestrator rule names it, a temp or scratch path says 'temp', anything else says 'home'.
    if own: return 'own'
    if orch is not None: return orch
    if re.match(r'^(/tmp/|/private/tmp/|/var/folders/|/private/var/folders/)',k) or 'scratchpad' in k: return 'temp'
    return 'home'
def uclass(sid):
    # class and rolled-up project dir of a session with no seat; one answer per session
    if sid in _cc: return _cc[sid]
    k=tilde(first.get(sid,('',''))[1])
    orch=next((v for rx,v in ORCHR if rx.search(k)),None)
    own=any(rx.search(k) for rx in OWNR)
    if own or (skills.get(sid,set())&OWNSKILL): c=C_OWN
    elif orch is not None: c=C_ORCH
    else: c=C_NONE
    _cc[sid]=(c,rollup(k,orch,own)); return _cc[sid]
rows=collections.defaultdict(lambda:collections.Counter())
seatrows=collections.defaultdict(lambda:collections.Counter())
daily=collections.defaultdict(lambda:collections.Counter())
sess=collections.defaultdict(lambda:collections.Counter()); sessmeta={}
bymethod=collections.Counter()
for e in msgs.values():
    if e['model']=='<synthetic>': continue
    lab,team,role,method,base=seat(e['sid'])
    cls=uclass(e['sid'])[0] if role=='-' else None
    a=act(e,role,cls); p=P.get(e['model']); repo=repo_of(e['cwd']); goal=goal_of(a,repo,team)
    usd=round((e['in']*p['in']+e['cw5v']*p['cw5']+e['cw1']*p['cw1']+e['cr']*p['cr']+e['out']*p['out'])) if p else 0
    k=(e['ts'][:10],repo,goal,a,team,role)
    c=rows[k]; c['requests']+=1; bymethod[method]+=1
    sk=(cls if cls else base,method,team,role,a); sc=seatrows[sk]; sc['requests']+=1
    dc=daily[(e['ts'][:10],e['model'])]; dc['requests']+=1
    if p: c['usd_micro']+=usd; sc['usd_micro']+=usd; dc['usd_micro']+=usd
    else: c['unpriced']+=1; sc['unpriced']+=1; dc['unpriced']+=1
    if cls:
        x=sess[e['sid']]; x['requests']+=1; x['usd_micro']+=usd
        if a=='hub wait (bus polling)': x['hub_micro']+=usd
        d=e['ts'][:10]; m=sessmeta.setdefault(e['sid'],[d,d]); m[0]=min(m[0],d); m[1]=max(m[1],d)
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
def wr(name,hdr,data):
    with open(out+'/'+name,'w',newline='') as fh:
        w=csv.writer(fh); w.writerow(hdr); w.writerows(data)
wr('by-seat-label.csv',['cluster','label_base','method','team','role','activity','requests','unpriced','list_usd'],
   [[CLUSTER,*k,c['requests'],c['unpriced'],round(c['usd_micro']/1e6,2)] for k,c in sorted(seatrows.items(),key=lambda kc:-kc[1]['usd_micro'])])
wr('unattributed-sessions.csv',['cluster','session_hash','class','project_dir','first_day','last_day','requests','list_usd','hub_wait_usd'],
   [[CLUSTER,H(sid),uclass(sid)[0],uclass(sid)[1],sessmeta[sid][0],sessmeta[sid][1],c['requests'],round(c['usd_micro']/1e6,2),round(c['hub_micro']/1e6,2)]
    for sid,c in sorted(sess.items(),key=lambda kc:-kc[1]['usd_micro'])])
wr('daily-by-model.csv',['cluster','day','model','requests','list_usd','unpriced'],
   [[CLUSTER,d,m,c['requests'],round(c['usd_micro']/1e6,2),c['unpriced']] for (d,m),c in sorted(daily.items())])
def signin():
    cfg=os.path.dirname(root.rstrip('/'))
    for f in (cfg+'/.claude.json',HOME+'/.claude.json' if cfg==HOME+'/.claude' else None):
        try:
            em=json.load(open(f))['oauthAccount']['emailAddress']
            if em: return H(em.strip().lower())
        except Exception: continue
    return 'none'
with open(out+'/attribution-meta.txt','w') as fh:
    for m in ('agent-name','launch-log','none'): fh.write('requests_%s=%d\n'%(m.replace('-','_'),bymethod[m]))
    fh.write('# signin_hash is an unsalted 12-hex pseudonym of the signed-in address, not safe to publish\n')
    fh.write('signin_hash=%s\n'%signin())
tot=collections.Counter()
for c in rows.values(): tot.update(c)
meta={'requests_priced_or_not':tot['requests'],'unpriced':tot['unpriced'],'list_usd':round(tot['usd_micro']/1e6,2),
 'unknown_repo_usd':round(sum(c['usd_micro'] for k,c in rows.items() if k[1]=='unknown')/1e6,2),
 'unmapped_goal_usd':round(sum(c['usd_micro'] for k,c in rows.items() if k[2]=='unmapped')/1e6,2),'distinct_cwds':len(_rc)}
json.dump(meta,open(out+'/axes-meta.json','w'),indent=1); print(json.dumps(meta,indent=1))

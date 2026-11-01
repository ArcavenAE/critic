#!/usr/bin/env python3
# I-85 transcript ledger, critic pilot. Reads Claude Code transcripts under ~/.claude/projects,
# dedupes by message.id, applies the marvel vsdd probe brief s10 cold-start and cache-death
# definitions, prices with a frozen table (s11), writes aggregate rows only. No transcript text out.
# Usage: python3 -I ledger-s10.py OUT_DIR PRICES_JSON CLUSTER_LABEL [PROJECTS_ROOT]
# PROJECTS_ROOT defaults to ~/.claude/projects; pass a seat config dir's projects folder to read it instead.
import json,glob,os,re,collections,csv,sys
from datetime import datetime
out=sys.argv[1]; P=json.load(open(sys.argv[2])); CLUSTER=sys.argv[3]
root=os.path.expanduser(sys.argv[4] if len(sys.argv)>4 else '~/.claude/projects')
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
                e=msgs[mid]={'ts':ts,'model':m.get('model'),'sid':r.get('sessionId'),'stream':f,'side':bool(r.get('isSidechain')) or sub,
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
agg=collections.defaultdict(lambda:collections.Counter())
for e in msgs.values():
    lab,team,role=seat(e['sid']); a=act(e,role); p=P.get(e['model'])
    k=(e['ts'][:10],e['model'],lab,team,role,a)
    c=agg[k]; c['requests']+=1; c['uncached_input']+=e['in']; c['write_5m']+=e['cw5v']; c['write_1h']+=e['cw1']; c['read']+=e['cr']; c['output']+=e['out']
    c['cold_starts']+=e['cold']; c['cache_deaths']+=e['death']; c['undetermined']+=e['undetermined']
    if p: c['usd_micro']+=round((e['in']*p['in']+e['cw5v']*p['cw5']+e['cw1']*p['cw1']+e['cr']*p['cr']+e['out']*p['out']))
    elif e['model']!='<synthetic>': c['unpriced']+=1
cols=['requests','uncached_input','write_5m','write_1h','read','output','cold_starts','cache_deaths','undetermined','unpriced']
with open(out+'/ledger-s10.csv','w',newline='') as fh:
    w=csv.writer(fh); w.writerow(['cluster','day','harness','model','seat_label','team','role','activity',*cols,'list_usd_s11'])
    for k in sorted(agg): w.writerow([CLUSTER,k[0],'claude-code',*k[1:],*[agg[k][c] for c in cols],round(agg[k]['usd_micro']/1e6,4)])
tot=collections.Counter()
for c in agg.values(): tot.update(c)
meta={'assistant_records':recs,'by_message_id':len(msgs),'by_request_id':len(rid_n),'copies_with_differing_usage':sum(e['usage_differs'] for e in msgs.values()),
 'streams':len(streams),**{k:tot[k] for k in cols},'list_usd_s11':round(tot['usd_micro']/1e6,2)}
json.dump(meta,open(out+'/ledger-s10-meta.json','w'),indent=1); print(json.dumps(meta,indent=1))

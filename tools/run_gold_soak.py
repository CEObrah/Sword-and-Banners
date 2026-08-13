#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,statistics,subprocess,time
from pathlib import Path
from sword_runtime.commands import CommandEnvelope
from sword_runtime.engine import SwordRuntime
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.store.root_hash import content_root

SOAK_TYPES = [
    "scene_consequence",
    "individual_training",
    "health_recovery",
    "relationship_change",
    "cohort_training",
    "formation_train",
    "house_action",
    "state_action",
    "enlisted_service_pay",
    "information_create",
    "information_deliver",
    "advance_time",
]
SLOTS=len(SOAK_TYPES)

def readj(p): return json.loads(Path(p).read_text())
def meta(root): return readj(Path(root)/'state/meta.json')

def command_for(root:Path,index:int,baseline_revision:int):
    m=meta(root); expected=baseline_revision+index
    if m['revision']!=expected: raise RuntimeError(f'revision mismatch at {index}: {m["revision"]} != {expected}')
    slot=index%SLOTS; cycle=index//SLOTS; now=m['time']
    if slot==0: t,p='scene_consequence',{'summary':f'Gold soak routine scene {cycle}'}
    elif slot==1: t,p='individual_training',{'focus':'Formation Command','hours':1}
    elif slot==2: t,p='health_recovery',{'hours':8}
    elif slot==3: t,p='relationship_change',{'target_ref':'char_shen_rui','kind':'trust','delta':1 if cycle%2==0 else -1}
    elif slot==4: t,p='cohort_training',{'cohort_ref':'junior_disciple','hours':1}
    elif slot==5: t,p='formation_train',{'formation_ref':'formation_tang_champions_first','hours':1}
    elif slot==6: t,p='house_action',{'house_ref':'house_tang','action':'assign_duty','subject_ref':'char_tang_kai','duty':'gold_soak_readiness_assistant'}
    elif slot==7: t,p='state_action',{'state':'qin','action':'strategic_goal','goal':f'maintain readiness soak {cycle}'}
    elif slot==8: t,p='enlisted_service_pay',{'state':'qin','amount_silver':7}
    elif slot==9: t,p='information_create',{'information_ref':f'info_gold_soak_{cycle:04d}','claim':f'Routine logistics report {cycle}','confidence':'0.8','knowers':['char_tang_wei']}
    elif slot==10: t,p='information_deliver',{'information_ref':f'info_gold_soak_{cycle:04d}','target_ref':'char_shen_rui'}
    else:
        t='advance_time'; p={'target_time':str(CampaignTime.parse(now).add_days(3))}
    internal=t in {'state_action','enlisted_service_pay'}
    actor='internal:sword-autonomy' if internal else 'char_tang_wei'
    mode='autonomous' if internal else 'gameplay'
    return CommandEnvelope(m['campaign_id'],f'gold-soak-{index:04d}',actor,t,expected,now,p,mode=mode)

def append_row(path:Path,row:dict):
    with path.open('a',encoding='utf-8') as f: f.write(json.dumps(row,sort_keys=True,separators=(',',':'))+'\n'); f.flush()

def run(root:Path, metrics:Path, count:int):
    rt=SwordRuntime(root); rt.recover(); baseline_path=metrics.with_suffix('.baseline.json')
    rows=[]
    if metrics.exists(): rows=[json.loads(x) for x in metrics.read_text().splitlines() if x.strip()]
    if baseline_path.exists(): baseline=readj(baseline_path)['baseline_revision']
    else:
        baseline=meta(root)['revision']-len(rows); baseline_path.write_text(json.dumps({'baseline_revision':baseline},sort_keys=True)+'\n')
    # A process can be killed after Git commit/receipt durability but before the
    # metrics row is flushed.  Backfill such rows from the immutable receipt;
    # never re-execute already committed gameplay.
    committed=max(0,meta(root)['revision']-baseline)
    while len(rows) < committed:
        index=len(rows); receipt=rt.coordinator.receipts.get(f'gold-soak-{index:04d}')
        if receipt is None: raise RuntimeError(f'missing durable receipt for committed soak request {index}')
        result=dict(receipt.result); slot=index%SLOTS
        row={'index':index,'request_id':receipt.request_id,'command_type':SOAK_TYPES[slot],'revision':receipt.committed_revision,'planning_reads':int(result.get('planning_reads',0)),'writes':int(result.get('writes',0)),'hosts_woken':int(result.get('hosts_woken',0)),'events_processed':int(result.get('events_processed',0)),'duration_seconds':None,'commit_hash':None,'backfilled_from_receipt':True}
        append_row(metrics,row); rows.append(row)
    start=len(rows)
    for index in range(start,min(1000,start+count)):
        cmd=command_for(root,index,baseline); started=time.perf_counter(); ex=rt.execute(cmd); elapsed=time.perf_counter()-started
        result=dict(ex.receipt.result)
        row={'index':index,'request_id':cmd.request_id,'command_type':cmd.command_type,'revision':ex.receipt.committed_revision,'planning_reads':int(result.get('planning_reads',0)),'writes':int(result.get('writes',0)),'hosts_woken':int(result.get('hosts_woken',0)),'events_processed':int(result.get('events_processed',0)),'duration_seconds':elapsed,'commit_hash':ex.commit_hash}
        append_row(metrics,row)
    print(json.dumps({'completed':min(1000,start+count),'revision':meta(root)['revision']},sort_keys=True))

def report(root:Path, metrics:Path, output:Path):
    rows=[json.loads(x) for x in metrics.read_text().splitlines() if x.strip()]
    if len(rows)!=1000: raise RuntimeError(f'need 1000 rows, have {len(rows)}')
    def pct(vals,p):
        s=sorted(vals); return s[min(len(s)-1,max(0,int((len(s)-1)*p)))]
    reads=[r['planning_reads'] for r in rows]; writes=[r['writes'] for r in rows]; durations=[r['duration_seconds'] for r in rows if r.get('duration_seconds') is not None]
    if len(durations)!=1000: raise RuntimeError('fresh Gold soak requires measured latency for all 1000 transactions')
    window_means=[statistics.fmean(durations[i:i+100]) for i in range(0,1000,100)]
    first_200=statistics.fmean(durations[:200]); last_200=statistics.fmean(durations[-200:])
    runtime=readj(root/'state/runtime.json'); scans={k:int(runtime.get('metrics',{}).get(k,0)) for k in ['global_person_scans','global_faction_scans','global_force_scans','global_house_scans']}
    git_count=int(subprocess.check_output(['git','-C',str(root),'rev-list','--count','HEAD'],text=True).strip())
    runtime_root=root/'.sword-runtime'
    out={'transactions':1000,'final_revision':meta(root)['revision'],'planning_reads':{'mean':statistics.fmean(reads),'p95':pct(reads,.95),'max':max(reads)},'writes':{'mean':statistics.fmean(writes),'p95':pct(writes,.95),'max':max(writes)},'duration_seconds':{'mean':statistics.fmean(durations),'p95':pct(durations,.95),'max':max(durations),'first_200_mean':first_200,'last_200_mean':last_200,'growth_ratio_last_200_vs_first_200':last_200/first_200,'window_100_means':window_means},'hosts_woken':sum(r['hosts_woken'] for r in rows),'events_processed':sum(r['events_processed'] for r in rows),'global_scans':scans,'git_commit_count_total':git_count,'wal':{'pending':len(tuple((runtime_root/'wal/pending').glob('*.json'))),'terminal':len(tuple((runtime_root/'wal/terminal').glob('*.json'))),'receipts':len(tuple((runtime_root/'receipts').glob('*.json')))},'failures':0,'final_root_hash':content_root(root,include_roots=('state',),tracked_only=True).root_sha256}
    output.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n'); print(json.dumps(out,sort_keys=True))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('root',type=Path); ap.add_argument('metrics',type=Path); ap.add_argument('--count',type=int,default=50); ap.add_argument('--report',type=Path)
    a=ap.parse_args(); root=a.root.resolve(); metrics=a.metrics.resolve()
    if a.report: report(root,metrics,a.report.resolve())
    else: run(root,metrics,a.count)
if __name__=='__main__': main()

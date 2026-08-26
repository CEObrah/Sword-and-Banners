import json, time
from conftest import meta

def preview_years(campaign,years):
    from sword_runtime.engine import RepositoryCommandPlanner
    from sword_runtime.commands import CommandEnvelope
    from sword_runtime.sim.calendar import CampaignTime
    m=meta(campaign); target=str(CampaignTime.parse(m['time']).add_years(years)); c=CommandEnvelope(m['campaign_id'],f'horizon-{years}','char_tang_wei','advance_time',m['revision'],m['time'],{'target_time':target}); t=time.perf_counter(); p=RepositoryCommandPlanner(campaign).preview(c); return p,time.perf_counter()-t

def test_horizons_are_bounded_and_alive(campaign):
    runtime=json.load(open(campaign/'state/runtime.json'))
    causal_host_bound=len(runtime['hosts'])
    results={}
    short_horizon_reads=None
    for y in (3,10,20,50):
        p,dt=preview_years(campaign,y); results[y]=(p.result,dt)
        assert p.result['hosts_woken']<=causal_host_bound
        if short_horizon_reads is None:
            # Ordinary host routing remains tightly bounded. Longer horizons may
            # lawfully touch additional exact formation/command/family owners when
            # deaths or succession occur, but that consequence fan-out is still
            # bounded by the fixed causal host set rather than elapsed years.
            assert p.result['planning_reads'] <= causal_host_bound + 128
            short_horizon_reads=int(p.result['planning_reads'])
        else:
            assert p.result['planning_reads'] <= short_horizon_reads + causal_host_bound
        # Exact named-person/family/interstate consequences may write owners
        # reached by the bounded causal read set. Long horizons also create new
        # immutable family/death event owners without reading those new paths first.
        # Keep total writes bounded by reads plus a fixed two-owner fan-out per
        # initial causal host, never by elapsed years.
        assert p.result['writes'] <= (2 * causal_host_bound) + p.result['planning_reads']
        # Structural work bounds above are authoritative. Keep only a loose
        # wall-clock smoke guard for catastrophic regressions on ordinary hosts.
        assert dt < 30.0
    assert results[50][0]['events_processed']>results[20][0]['events_processed']

def test_20_year_world_changes_without_global_scans(campaign):
    from sword_runtime.engine import SwordRuntime
    from sword_runtime.commands import CommandEnvelope
    from sword_runtime.sim.calendar import CampaignTime
    m=meta(campaign); target=str(CampaignTime.parse(m['time']).add_years(20)); c=CommandEnvelope(m['campaign_id'],'twenty-real','char_tang_wei','advance_time',m['revision'],m['time'],{'target_time':target}); x=SwordRuntime(campaign).execute(c)
    rt=json.load(open(campaign/'state/runtime.json')); assert x.status=='committed'; assert rt['metrics']['events_processed']>1000
    assert all(rt['metrics'][k]==0 for k in ('global_person_scans','global_faction_scans','global_force_scans','global_house_scans'))
    idx=json.load(open(campaign/'state/index/owner-index.json'))['owners']; current_qin_refs=['formation_high_guard_qin_a','formation_high_guard_qin_b']+[f'formation_black_banner_0{i}{suffix}' for i in range(1,5) for suffix in ('a','b')]; assert all(ref in idx for ref in current_qin_refs) and 'formation_zhao_border_line' in idx

def test_named_person_identity_survives_5_and_20_years(campaign):
    import json
    from sword_runtime.engine import SwordRuntime
    from sword_runtime.commands import CommandEnvelope
    from sword_runtime.sim.calendar import CampaignTime
    original=json.load(open(campaign/'state/char/ouki.json'))
    for years in (5,20):
        m=meta(campaign); target=str(CampaignTime.parse(m['time']).add_years(years if years==5 else 15)); c=CommandEnvelope(m['campaign_id'],f'person-{years}','char_tang_wei','advance_time',m['revision'],m['time'],{'target_time':target}); SwordRuntime(campaign).execute(c)
        after=json.load(open(campaign/'state/char/ouki.json'))
        assert after['owner_id']==original['owner_id']
        assert after['name']==original['name']
        assert after['birth_date']==original['birth_date']

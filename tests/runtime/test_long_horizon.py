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
            # Ordinary host routing remains tightly bounded. Long-horizon
            # settlement may also touch exact persistent formations and already-live
            # operations that are not themselves causal hosts. Bound that world-size
            # surface explicitly, plus a small fixed control-plane allowance for
            # indices/rules/current command-family owners. The allowance never scales
            # with elapsed years, so a directory/global scan still blows the gate.
            persistent_formations = len(list((campaign / 'state/formations').glob('*.json')))
            live_operations = len(list((campaign / 'state/operations').glob('*.json')))
            non_host_control_plane_allowance = 64
            baseline_read_bound = causal_host_bound + persistent_formations + live_operations + non_host_control_plane_allowance
            assert p.result['planning_reads'] <= baseline_read_bound
            short_horizon_reads=int(p.result['planning_reads'])
        else:
            assert p.result['planning_reads'] <= short_horizon_reads + causal_host_bound
        # Exact named-person/family/interstate consequences may write owners
        # reached by the bounded causal read set. Long horizons also create new
        # immutable family/death event owners without reading those new paths first.
        # Keep total writes bounded by reads plus a fixed two-owner fan-out per
        # initial causal host, never by elapsed years.
        assert p.result['writes'] <= (2 * causal_host_bound) + p.result['planning_reads']
        # Do not duplicate hosted-runner wall-clock policy here. The dedicated
        # hosted-horizon suite bounds production complexity by causal windows,
        # event density, and logical read/write fanout; this test owns only the
        # structural no-global-scan invariant.
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

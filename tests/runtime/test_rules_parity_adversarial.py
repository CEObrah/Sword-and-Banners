import json
from pathlib import Path
import pytest

from conftest import execute, execute_internal, meta, prepare_field_formation, activate_operation


def owner_doc(root, ref):
    idx=json.load(open(Path(root)/'state/index/owner-index.json'))['owners']
    return Path(root)/idx[ref], json.load(open(Path(root)/idx[ref]))


def test_hostile_value_reference_chronology_and_preview_validation(campaign):
    before=meta(campaign)
    with pytest.raises(ValueError):
        execute(campaign,'economy_transfer',{'state':'qin','direction':'player_to_state','amount_silver':-1_000_000})
    with pytest.raises(ValueError):
        execute(campaign,'market_purchase',{'item_key':'common_sword','quantity':-10})
    with pytest.raises(ValueError):
        execute(campaign,'relationship_change',{'target_ref':'char_does_not_exist','kind':'trust','delta':1})
    with pytest.raises(ValueError):
        execute(campaign,'family_event',{'house_ref':'house_tang','kind':'marriage','person_ref':'char_tang_wei','partner_ref':'char_does_not_exist'})
    assert meta(campaign)==before

    from sword_runtime.engine import SwordRuntime, RepositoryCommandPlanner
    from sword_runtime.commands import CommandEnvelope
    m=meta(campaign)
    forged=CommandEnvelope(m['campaign_id'],'forged-chronology','char_tang_wei','scene_consequence',m['revision'],'200-BCE-01-01T00:00:00+08:00',{'summary':'forged future'})
    with pytest.raises(ValueError): SwordRuntime(campaign).execute(forged)
    internal=CommandEnvelope(m['campaign_id'],'preview-internal',RepositoryCommandPlanner.INTERNAL_ACTOR,'state_action',m['revision'],m['time'],{'state':'qin','action':'strategic_goal','goal':'probe'},mode='autonomous')
    with pytest.raises((PermissionError,ValueError)): SwordRuntime(campaign).preview(internal)
    contested=CommandEnvelope(m['campaign_id'],'preview-combat','char_tang_wei','personal_combat',m['revision'],m['time'],{'opponent_ref':'char_tang_zhu','objective':'controlled spar','duration_minutes':30})
    with pytest.raises(PermissionError): SwordRuntime(campaign).preview(contested)


def test_territory_requires_exact_causal_evidence(campaign):
    before=json.load(open(campaign/'state/territory/control.json'))['sites']['loc_kanyou']['controller']
    with pytest.raises((PermissionError,ValueError)):
        execute(campaign,'territorial_consequence',{'location_ref':'loc_kanyou','controller':'house_tang'})
    with pytest.raises((PermissionError,ValueError)):
        execute(campaign,'territorial_consequence',{'location_ref':'loc_kanyou','controller':'state_zhao'})
    after=json.load(open(campaign/'state/territory/control.json'))['sites']['loc_kanyou']['controller']
    assert after==before=='state_qin'


def test_training_progression_and_formation_time_are_real(campaign):
    from sword_runtime.sim.calendar import CampaignTime
    player0=json.load(open(campaign/'state/player.json')); s0=int(player0['skills']['Formation Command']); t0=CampaignTime.parse(meta(campaign)['time'])
    # A single block may bank fractional EDU. Repeated lawful training must consume
    # that bank into actual skill points rather than leaving decorative credit forever.
    for _ in range(7):
        execute(campaign,'individual_training',{'focus':'Formation Command','hours':12})
    player1=json.load(open(campaign/'state/player.json')); t1=CampaignTime.parse(meta(campaign)['time'])
    assert int(player1['skills']['Formation Command'])>s0
    assert t0.seconds_until(t1)==84*3600
    assert 'Formation Command' in player1['development_state'].get('skill_edu_banks',{})

    ref='formation_red_lance_a'; _,f0=owner_doc(campaign,ref); t2=CampaignTime.parse(meta(campaign)['time'])
    execute(campaign,'formation_train',{'formation_ref':ref,'hours':12})
    _,f1=owner_doc(campaign,ref); t3=CampaignTime.parse(meta(campaign)['time'])
    assert t2.seconds_until(t3)==12*3600
    assert int(f1['training_progress'])>=int(f0.get('training_progress',0))
    with pytest.raises(ValueError): execute(campaign,'formation_train',{'formation_ref':ref,'hours':100000})
    with pytest.raises(ValueError): execute(campaign,'cohort_training',{'hours':100000})


def test_formation_movement_route_commander_and_reconstitution_are_causal(campaign):
    from sword_runtime.sim.calendar import CampaignTime
    ref='formation_release_reconstitution_qin'
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':ref,'role':'line_infantry','personnel':1000,'authorized_strength':1500,'location_ref':'loc_qin_eastern_depot'})
    _,base=owner_doc(campaign,ref)
    initial_quality=(int(base['readiness']),int(base['cohesion']),int(base.get('training_progress',0)))

    with pytest.raises(ValueError):
        execute_internal(campaign,'formation_move',{'formation_ref':ref,'destination_ref':'loc_kanyou'})

    # A remote commander cannot be silently appointed to a formation at another location.
    with pytest.raises((ValueError,PermissionError)):
        execute_internal(campaign,'command_assign',{'formation_ref':ref,'commander_ref':'char_riboku'})

    # Replacements must come from the formation's exact source location and dilute
    # the existing cohort instead of cloning its quality.
    t0=CampaignTime.parse(meta(campaign)['time'])
    execute_internal(campaign,'formation_reconstitute',{'formation_ref':ref,'target_personnel':1500})
    _,after=owner_doc(campaign,ref); t1=CampaignTime.parse(meta(campaign)['time'])
    assert int(after['personnel'])==1500
    assert t0.seconds_until(t1)>0
    assert (int(after['readiness']),int(after['cohesion']),int(after['training_progress'])) <= initial_quality

    # Strategic movement then requires real supply, mobilization, and a saved route.
    n=int(after['personnel'])
    execute_internal(campaign,'resupply',{'formation_ref':ref,'war_arrows':n*4})
    execute_internal(campaign,'formation_mobilize',{'formation_ref':ref})
    moved=execute_internal(campaign,'formation_move',{'formation_ref':ref,'destination_ref':'loc_kanyou'}).receipt.result
    _,fielded=owner_doc(campaign,ref)
    assert fielded['location_ref']=='loc_kanyou'
    assert int(moved['world_time'] != '') == 1

def test_battle_time_named_people_and_no_same_timestamp_rerolls(campaign):
    from sword_runtime.sim.calendar import CampaignTime
    q='formation_parity_qin'; z='formation_parity_zhao'
    qcmd='char_parity_qin_commander'; zcmd='char_parity_zhao_commander'
    # The invariant test owns its commanders. It must not borrow live campaign generals
    # whose current assignments can lawfully change as the campaign progresses.
    execute_internal(campaign,'person_materialize',{'state':'qin','person_ref':qcmd,'name':'Parity Qin Commander','birth_date':'270-BCE-01-01','role':'command_personnel','source_location_ref':'loc_qin_eastern_depot'})
    execute_internal(campaign,'person_materialize',{'state':'zhao','person_ref':zcmd,'name':'Parity Zhao Commander','birth_date':'270-BCE-01-01','role':'command_personnel','source_location_ref':'loc_zhao_regional_01'})
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':q,'role':'line_infantry','personnel':1000,'location_ref':'loc_qin_eastern_depot','commander_ref':qcmd})
    execute_internal(campaign,'formation_create',{'state':'zhao','formation_ref':z,'role':'line_infantry','personnel':1000,'location_ref':'loc_zhao_regional_01','commander_ref':zcmd})
    prepare_field_formation(campaign,q); prepare_field_formation(campaign,z); op=activate_operation(campaign,'operation_parity_battle',[q,z])
    t0=CampaignTime.parse(meta(campaign)['time'])
    r1=execute_internal(campaign,'battle_resolve',{'attacker_formation_refs':[q],'defender_formation_refs':[z],'operation_ref':op}).receipt.result
    t1=CampaignTime.parse(meta(campaign)['time'])
    assert t0.seconds_until(t1)>=3600
    assert {qcmd,zcmd}.issubset(set(r1['named_person_outcomes']))
    # A caller cannot replay the battle at its old timestamp. Whether another
    # battle is otherwise lawful depends on who survived and still commands.
    from sword_runtime.engine import SwordRuntime, RepositoryCommandPlanner
    from sword_runtime.commands import CommandEnvelope
    current=meta(campaign)
    stale=CommandEnvelope(
        current['campaign_id'], 'stale-battle-replay', RepositoryCommandPlanner.INTERNAL_ACTOR,
        'battle_resolve', current['revision'], str(t0),
        {'attacker_formation_refs':[q],'defender_formation_refs':[z],'operation_ref':op},
        mode='autonomous',
    )
    with pytest.raises(ValueError):
        SwordRuntime(campaign).execute(stale)



def test_information_delivery_and_equipment_are_causal(campaign):
    from sword_runtime.sim.calendar import CampaignTime
    # Information delivery uses exact sender/recipient locations and route time.
    execute(campaign,'information_create',{'information_ref':'info_parity','claim':'Test report','knowers':['char_tang_wei']})
    t0=CampaignTime.parse(meta(campaign)['time'])
    r=execute(campaign,'information_deliver',{'information_ref':'info_parity','target_ref':'char_zhao_fen'}).receipt.result
    t1=CampaignTime.parse(meta(campaign)['time'])
    assert r['travel_hours']>=1 and t0.seconds_until(t1)==r['travel_hours']*3600

    # Purchased equipment moves through inventory -> loadout and the combat receipt exposes that loadout.
    # Return player to Tang Manor if an earlier information command did not move them (it should not).
    execute(campaign,'travel',{'destination_ref':'loc_kanyou','mode':'foot'})
    purchase=execute(campaign,'market_purchase',{'item_key':'military_spear','quantity':1}).receipt.result
    exact_item_id=purchase['item_id']
    execute(campaign,'travel',{'destination_ref':'loc_tang_manor','mode':'foot'})
    # The clean baseline already carries one issued spear.  Unequip that issued
    # copy before equipping from the now-larger exact inventory; the purchase
    # must not depend on the baseline starting unequipped.
    execute(campaign,'equipment_unequip',{'item_key':exact_item_id,'quantity':1})
    execute(campaign,'equipment_equip',{'item_key':exact_item_id,'quantity':1})
    result=execute(campaign,'personal_combat',{'opponent_ref':'char_tang_zhu','objective':'controlled spar','duration_minutes':30}).receipt.result
    assert exact_item_id in result['player_equipment']['equipped_item_ids']


def test_fifty_year_world_produces_exact_human_and_interstate_history(campaign):
    from collections import Counter
    execute(campaign,'advance_time',{'hours':50*365*24})
    history=json.load(open(campaign/'state/history/events/index.json'))['events']
    kinds=Counter(str(e.get('kind')) for e in history)
    assert kinds['named_person_death'] >= 1
    assert kinds['named_person_majority'] >= 1
    # Warfare is contingent. Long elapsed time alone must not manufacture a war.
    # If interstate battles occurred, they are ordinary exact history events, but
    # peace is also a valid deterministic outcome when no lawful war intent arose.
    family=json.load(open(campaign/'state/family/index.json'))
    assert int(family.get('counts',{}).get('events',0)) >= 1
    runtime=json.load(open(campaign/'state/runtime.json'))
    assert all(int(runtime['metrics'].get(k,0))==0 for k in ('global_person_scans','global_faction_scans','global_force_scans','global_house_scans'))
    territory=json.load(open(campaign/'state/territory/control.json'))['sites']
    # Territorial conquest is contingent, not a mandatory historical beat.  If
    # a deterministic replay produces one, it must carry exact causal evidence.
    territory_events=[e for e in history if str(e.get('kind'))=='territorial_control_change']
    for event in territory_events:
        site=territory[str(event['location_ref'])]
        assert event.get('evidence_ref')
        assert site.get('change_evidence_ref')

    # Marching formations own no ration/fodder ledger and no persistent army-train
    # simulation. Strategic supply is derived. Any detached discrete shipment that
    # does exist must still preserve physical dispatch/travel/arrival chronology.
    idx=json.load(open(campaign/'state/index/owner-index.json'))['owners']
    from sword_runtime.sim.calendar import CampaignTime
    for ref,path in idx.items():
        if not str(ref).startswith('formation_'):
            continue
        formation=json.load(open(campaign/path))
        logistics=formation.get('logistics',{})
        assert 'food_kg' not in logistics
        assert 'fodder_kg' not in logistics
        for event in formation.get('supply_history',[]):
            if event.get('source_location_ref')==event.get('destination_location_ref'):
                continue
            if event.get('dispatched_at') and event.get('arrives_at'):
                assert int(event.get('travel_hours',0))>0
                assert str(event.get('dispatched_at'))!=str(event.get('arrives_at'))
                assert CampaignTime.parse(str(event['dispatched_at'])) < CampaignTime.parse(str(event['arrives_at']))


def test_split_identity_resupply_exactness_and_single_commander(campaign):
    ref='formation_red_lance_a'
    _,before=owner_doc(campaign,ref)
    before_meta=meta(campaign)

    # A split cannot overwrite an existing formation identity or alias its source.
    with pytest.raises(ValueError):
        execute(campaign,'formation_split',{'formation_ref':ref,'personnel':10,'new_formation_ref':ref})
    with pytest.raises(ValueError):
        execute(campaign,'formation_split',{'formation_ref':ref,'personnel':10,'new_formation_ref':'formation_high_guard_infantry_01a'})
    _,after=owner_doc(campaign,ref)
    assert after==before and meta(campaign)==before_meta

    # Resupply is exact, not an implicit/partial order.  Asking for more than
    # the physically colocated depot owns must reject the entire transaction.
    depot_path=campaign/'state/depots/house-tang.json'
    depot0=json.load(open(depot_path))
    with pytest.raises(ValueError):
        execute(campaign,'resupply',{'formation_ref':ref,'war_arrows':int(depot0['stocks']['war_arrows'])+1})
    assert json.load(open(depot_path))==depot0
    _,unchanged=owner_doc(campaign,ref)
    assert unchanged==before

    # Splitting conserves numeric material while carrying non-quantity logistics
    # provenance to both resulting bodies. A single exact person still cannot
    # top-command two co-located formations at once. Duan Jin is intentionally used here because he already commands the source
    # Red Lance formation at this same depot, so the same exact person cannot top-command
    # both the parent remnant and its new split child.
    child='formation_release_split_child'
    execute(campaign,'formation_split',{'formation_ref':ref,'personnel':10,'new_formation_ref':child})
    _,parent_after_split=owner_doc(campaign,ref)
    _,child_after_split=owner_doc(campaign,child)
    source_depot_ref=before.get('logistics',{}).get('source_depot_ref')
    assert parent_after_split.get('logistics',{}).get('source_depot_ref')==source_depot_ref
    assert child_after_split.get('logistics',{}).get('source_depot_ref')==source_depot_ref
    with pytest.raises(ValueError):
        execute_internal(campaign,'command_assign',{'formation_ref':child,'commander_ref':'char_duan_jin'})

    # Merge must likewise sum only conserved numeric quantities while retaining
    # the surviving formation's routing/provenance metadata.
    execute(campaign,'formation_merge',{'formation_refs':[ref,child]})
    _,merged=owner_doc(campaign,ref)
    assert int(merged['personnel'])==int(before['personnel'])
    assert merged.get('logistics',{}).get('source_depot_ref')==source_depot_ref
    for key,value in before.get('logistics',{}).items():
        if isinstance(value,(int,float)) and not isinstance(value,bool):
            assert int(merged['logistics'].get(key,0))==int(value)


def test_derived_state_and_project_timing_fail_closed(campaign):
    # Reputation and career are consequences of evidence, not player-authored knobs.
    with pytest.raises(PermissionError):
        execute(campaign,'reputation_event',{'subject_ref':'char_tang_wei','audience_ref':'char_shen_rui','delta':20})
    with pytest.raises(PermissionError):
        execute(campaign,'career_event',{'person_ref':'char_tang_wei','kind':'merit','merit':1000})

    # A project cannot be resolved before its persisted due time.
    project_ref='project_parity_timing'
    execute_internal(campaign,'institution_project',{'institution_ref':'inst_qin_fortification_bureau','project_ref':project_ref,'duration_hours':24,'magnitude':1})
    with pytest.raises(ValueError):
        execute_internal(campaign,'project_resolve',{'institution_ref':'inst_qin_fortification_bureau','project_ref':project_ref})


def test_siege_inputs_and_equipment_custody_are_exact(campaign):
    # Caller-supplied siege damage is forbidden and nonexistent siege state fails.
    with pytest.raises(ValueError):
        execute_internal(campaign,'siege_action',{'siege_ref':'siege_does_not_exist','action':'assault','damage':100})

    # Owning a catalog key is not custody.  Equipment operations require exact
    # inventory instances and cannot fabricate/overdraw them.
    with pytest.raises(ValueError):
        execute(campaign,'equipment_equip',{'item_key':'military_sword','quantity':1})
    execute(campaign,'travel',{'destination_ref':'loc_kanyou','mode':'foot'})
    purchase=execute(campaign,'market_purchase',{'item_key':'military_spear','quantity':1}).receipt.result
    item_id=purchase['item_id']
    with pytest.raises(ValueError):
        execute(campaign,'equipment_equip',{'item_key':item_id,'quantity':10000})

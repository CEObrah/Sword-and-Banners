import json
from pathlib import Path
import pytest

from conftest import execute, execute_internal, meta, prepare_field_formation, activate_operation


def owner_doc(root, ref):
    idx=json.load(open(Path(root)/'state/index/owner-index-gold.json'))['owners']
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
    contested=CommandEnvelope(m['campaign_id'],'preview-combat','char_tang_wei','personal_combat',m['revision'],m['time'],{'opponent_ref':'char_shen_rui','objective':'controlled spar','duration_minutes':30})
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
    assert float(player1['development_state'].get('training_credit',0))==0.0
    assert 'Formation Command' in player1['development_state'].get('skill_edu_banks',{})

    ref='formation_tang_champions_first'; _,f0=owner_doc(campaign,ref); t2=CampaignTime.parse(meta(campaign)['time'])
    execute(campaign,'formation_train',{'formation_ref':ref,'hours':12})
    _,f1=owner_doc(campaign,ref); t3=CampaignTime.parse(meta(campaign)['time'])
    assert t2.seconds_until(t3)==12*3600
    assert int(f1['training_progress'])>=int(f0.get('training_progress',0))
    with pytest.raises(ValueError): execute(campaign,'formation_train',{'formation_ref':ref,'hours':100000})
    with pytest.raises(ValueError): execute(campaign,'cohort_training',{'hours':100000})


def test_formation_movement_route_commander_and_reconstitution_are_causal(campaign):
    from sword_runtime.sim.calendar import CampaignTime
    ref='formation_tang_champions_first'
    _,champ0=owner_doc(campaign,ref); initial_n=int(champ0['personnel']); initial_quality=(int(champ0['readiness']),int(champ0['cohesion']),int(champ0.get('training_progress',0)))

    with pytest.raises(ValueError):
        execute(campaign,'formation_move',{'formation_ref':ref,'destination_ref':'loc_kanyou'})

    # Remote/non-subordinate commanders are invalid even if the formation itself is player-controlled.
    with pytest.raises((ValueError,PermissionError)):
        execute(campaign,'command_assign',{'formation_ref':ref,'commander_ref':'char_riboku'})

    execute(campaign,'formation_mobilize',{'formation_ref':ref})
    _,champ=owner_doc(campaign,ref); n=int(champ['personnel']); mounts=sum(int(v) for v in champ.get('mounts',{}).values())
    # Tang Manor has no strategic formation route to Kanyou, so a direct teleport must stay rejected.
    with pytest.raises(ValueError): execute(campaign,'formation_move',{'formation_ref':ref,'destination_ref':'loc_kanyou'})

    # Reconstitution is source-location bound and dilutes veteran quality instead of cloning it.
    # House Tang begins with a real local heavy-cavalry reserve at this exact location.
    t0=CampaignTime.parse(meta(campaign)['time'])
    execute(campaign,'formation_reconstitute',{'formation_ref':ref,'target_personnel':initial_n+500})
    _,after=owner_doc(campaign,ref); t1=CampaignTime.parse(meta(campaign)['time'])
    assert int(after['personnel'])==initial_n+500
    assert t0.seconds_until(t1)>0
    assert (int(after['readiness']),int(after['cohesion']),int(after['training_progress'])) < initial_quality


def test_battle_time_named_people_and_no_same_timestamp_rerolls(campaign):
    from sword_runtime.sim.calendar import CampaignTime
    q='formation_parity_qin'; z='formation_parity_zhao'
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':q,'role':'line_infantry','personnel':1000,'commander_ref':'char_heki'})
    execute_internal(campaign,'formation_create',{'state':'zhao','formation_ref':z,'role':'line_infantry','personnel':1000,'commander_ref':'char_riboku'})
    prepare_field_formation(campaign,q); prepare_field_formation(campaign,z); op=activate_operation(campaign,'operation_parity_battle',[q,z])
    t0=CampaignTime.parse(meta(campaign)['time'])
    r1=execute_internal(campaign,'battle_resolve',{'attacker_formation_refs':[q],'defender_formation_refs':[z],'operation_ref':op}).receipt.result
    t1=CampaignTime.parse(meta(campaign)['time'])
    assert t0.seconds_until(t1)>=3600
    assert {'char_heki','char_riboku'}.issubset(set(r1['named_person_outcomes']))
    # Same operation may continue only at the new authoritative time, never as an instant reroll.
    if owner_doc(campaign,q)[1]['personnel']>0 and owner_doc(campaign,z)[1]['personnel']>0:
        r2=execute_internal(campaign,'battle_resolve',{'attacker_formation_refs':[q],'defender_formation_refs':[z],'operation_ref':op}).receipt.result
        t2=CampaignTime.parse(meta(campaign)['time'])
        assert t1.seconds_until(t2)>=3600
        assert r2['battle_event']!=r1['battle_event']


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
    purchase=execute(campaign,'market_purchase',{'item_key':'military_sword','quantity':1}).receipt.result
    exact_item_id=purchase['item_id']
    execute(campaign,'travel',{'destination_ref':'loc_tang_manor_inner_citadel_family_hall','mode':'foot'})
    execute(campaign,'equipment_equip',{'item_key':exact_item_id,'quantity':1})
    result=execute(campaign,'personal_combat',{'opponent_ref':'char_shen_rui','objective':'controlled spar','duration_minutes':30}).receipt.result
    assert exact_item_id in result['player_equipment']['equipped_item_ids']
    assert result['player_equipment']['best_weapon'] is not None

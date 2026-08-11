import json
from pathlib import Path
import pytest
from conftest import execute, execute_internal, meta, prepare_field_formation, activate_operation


def test_player_identity_and_organizational_authority_are_fail_closed(campaign):
    start=meta(campaign)['revision']
    with pytest.raises(PermissionError):
        execute(campaign,'state_action',{'state':'zhao','action':'appointment','office':'supreme_commander','person_ref':'char_tang_wei','capabilities':['state_command']})
    with pytest.raises(PermissionError):
        execute(campaign,'recruitment',{'state':'zhao','personnel':1000,'source_stratum':'agricultural','role':'line_infantry'})
    with pytest.raises(PermissionError):
        execute(campaign,'scene_consequence',{'summary':'forged NPC actor'},actor='char_riboku')
    assert meta(campaign)['revision']==start
    execute(campaign,'formation_mobilize',{'formation_ref':'formation_tang_champions_first'})
    assert json.load(open(campaign/'state/formations/tang-champions-first.json'))['mobilized'] is True


def test_split_merge_dissolve_conserve_people_equipment_supplies_mounts_and_ammo(campaign):
    ref='formation_conservation_qin'
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':ref,'role':'line_infantry','personnel':1000,'commander_ref':'char_heki'})
    execute_internal(campaign,'resupply',{'formation_ref':ref,'food_kg':5000,'war_arrows':10000})
    idx=json.load(open(campaign/'state/index/owner-index-gold.json'))['owners']; path=campaign/idx[ref]
    before=json.load(open(path)); force0=json.load(open(campaign/'state/forces/state-qin.json')); depot0=json.load(open(campaign/'state/depots/qin.json'))
    before_equipment=sum(before['equipment_units_by_role'].values()); before_food=before['logistics']['food_kg']; before_arrows=before['logistics']['war_arrows']; before_mounts=sum(before['mounts'].values())

    child='formation_conservation_qin_child'
    execute_internal(campaign,'formation_split',{'formation_ref':ref,'new_formation_ref':child,'personnel':400})
    idx=json.load(open(campaign/'state/index/owner-index-gold.json'))['owners']; parent=json.load(open(campaign/idx[ref])); split=json.load(open(campaign/idx[child]))
    assert parent['personnel']+split['personnel']==1000
    assert sum(parent['equipment_units_by_role'].values())+sum(split['equipment_units_by_role'].values())==before_equipment
    assert parent['logistics']['food_kg']+split['logistics']['food_kg']==before_food
    assert parent['logistics']['war_arrows']+split['logistics']['war_arrows']==before_arrows
    assert sum(parent['mounts'].values())+sum(split['mounts'].values())==before_mounts

    execute_internal(campaign,'formation_merge',{'formation_refs':[ref,child]})
    merged=json.load(open(campaign/idx[ref]))
    assert merged['personnel']==1000
    assert sum(merged['equipment_units_by_role'].values())==before_equipment
    assert merged['logistics']['food_kg']==before_food and merged['logistics']['war_arrows']==before_arrows

    execute_internal(campaign,'formation_dissolve',{'formation_ref':ref})
    force1=json.load(open(campaign/'state/forces/state-qin.json')); depot1=json.load(open(campaign/'state/depots/qin.json'))
    assert force1['available_by_role']['line_infantry']==force0['available_by_role']['line_infantry']+1000
    assert force1['available_equipment_units_by_role']['line_infantry']==force0['available_equipment_units_by_role']['line_infantry']+before_equipment
    assert depot1['stocks']['grain_kg']==depot0['stocks']['grain_kg']+before_food
    assert depot1['stocks']['war_arrows']==depot0['stocks']['war_arrows']+before_arrows


def test_battle_requires_location_mobilization_and_active_operation_contact(campaign):
    q='formation_causal_qin'; z='formation_causal_zhao'
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':q,'role':'line_infantry','personnel':1000,'commander_ref':'char_heki'})
    execute_internal(campaign,'formation_create',{'state':'zhao','formation_ref':z,'role':'line_infantry','personnel':1000,'commander_ref':'char_bananji'})
    with pytest.raises(ValueError):
        execute_internal(campaign,'battle_resolve',{'attacker_formation_refs':[q],'defender_formation_refs':[z]})
    prepare_field_formation(campaign,q); prepare_field_formation(campaign,z)
    with pytest.raises(ValueError):
        execute_internal(campaign,'battle_resolve',{'attacker_formation_refs':[q],'defender_formation_refs':[z]})
    op=activate_operation(campaign,'operation_causal_test',[q,z])
    result=execute_internal(campaign,'battle_resolve',{'attacker_formation_refs':[q],'defender_formation_refs':[z],'operation_ref':op}).receipt.result
    assert result['battlefield_ref']=='loc_kankoku_pass' and result['contact_proof']==op


def test_personal_combat_training_and_recovery_use_exact_people_and_elapsed_time(campaign):
    from sword_runtime.sim.calendar import CampaignTime
    with pytest.raises(ValueError):
        execute(campaign,'personal_combat',{'opponent_ref':'char_does_not_exist','objective':'duel'})
    with pytest.raises(ValueError):
        execute(campaign,'individual_training',{'focus':'Formation Command','hours':10000})
    t0=CampaignTime.parse(meta(campaign)['time'])
    execute(campaign,'individual_training',{'focus':'Formation Command','hours':2})
    t1=CampaignTime.parse(meta(campaign)['time']); assert t0.seconds_until(t1)==7200
    execute(campaign,'health_injury',{'injury':'test injury','severity':'severe'})
    execute(campaign,'health_recovery',{'hours':8}); assert json.load(open(campaign/'state/player.json'))['health']=='injured'
    execute(campaign,'health_recovery',{'hours':64}); assert json.load(open(campaign/'state/player.json'))['health']=='healthy'
    before=CampaignTime.parse(meta(campaign)['time']); result=execute(campaign,'personal_combat',{'opponent_ref':'char_shen_rui','objective':'controlled spar','duration_minutes':30}).receipt.result; after=CampaignTime.parse(meta(campaign)['time'])
    assert result['opponent_ref']=='char_shen_rui' and before.seconds_until(after)==1800


def test_doctrine_supply_terrain_and_command_drive_battle_score(campaign):
    q='formation_score_qin'; z='formation_score_zhao'
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':q,'role':'line_infantry','personnel':2000,'commander_ref':'char_heki'})
    execute_internal(campaign,'formation_create',{'state':'zhao','formation_ref':z,'role':'line_infantry','personnel':2000,'commander_ref':'char_kaine'})
    execute_internal(campaign,'formation_doctrine_set',{'formation_ref':q,'doctrine_ref':'doc.external_state_force.standard','doctrine_behavior':{'reserve_commitment':100,'casualty_tolerance':'high'}})
    execute_internal(campaign,'formation_doctrine_set',{'formation_ref':z,'doctrine_ref':'doc.external_state_force.standard','doctrine_behavior':{'reserve_commitment':10,'casualty_tolerance':'low'}})
    # Zhao's six-leg 150h route consumes 10,002 kg for 2,000 soldiers because
    # each saved leg rounds consumption upward. 5.6 kg/person leaves lawful
    # battle food while still producing a materially worse supply factor.
    prepare_field_formation(campaign,q,food_per_person=7); prepare_field_formation(campaign,z,food_per_person=5.6)
    op=activate_operation(campaign,'operation_score_test',[q,z])
    r=execute_internal(campaign,'battle_resolve',{'attacker_formation_refs':[q],'defender_formation_refs':[z],'operation_ref':op}).receipt.result
    assert r['terrain_kind']=='pass'
    assert r['score_breakdown'][q]['doctrine'] != r['score_breakdown'][z]['doctrine']
    assert r['score_breakdown'][q]['supply'] > r['score_breakdown'][z]['supply']
    assert r['score_breakdown'][q]['command'] != r['score_breakdown'][z]['command']


def test_legacy_domains_have_one_active_authority_and_ci_uses_gold_gate(campaign):
    assert not (campaign/'state/rel').exists()
    assert (campaign/'archive/legacy-execution/relationships-pre-gold').is_dir()
    idx=json.load(open(campaign/'state/index/owner-index-gold.json'))['owners']
    for path in (campaign/'state').rglob('*.json'):
        doc=json.load(open(path))
        if isinstance(doc,dict) and isinstance(doc.get('owner_id'),str):
            assert idx.get(doc['owner_id'])==path.relative_to(campaign).as_posix()
    rt=json.load(open(campaign/'state/runtime.json'))
    assert sum(1 for h in rt['hosts'].values() if h.get('kind')=='mercenary')==60
    workflow=(campaign/'.github/workflows/audit.yml').read_text()
    assert 'tools/run_gold_suite.py' in workflow and 'tools/run_validators.py' not in workflow

import json
import subprocess
from pathlib import Path
import pytest
from conftest import execute, execute_internal, meta, prepare_field_formation, activate_operation


def _materialize_test_commander(campaign, *, state, person_ref, location_ref):
    execute_internal(campaign, 'person_materialize', {
        'state': state,
        'person_ref': person_ref,
        'name': f'Test {state.title()} Commander',
        'birth_date': '270-BCE-01-01',
        'role': 'command_personnel',
        'source_location_ref': location_ref,
    })



def test_player_identity_and_organizational_authority_are_fail_closed(campaign):
    start=meta(campaign)['revision']
    with pytest.raises(PermissionError):
        execute(campaign,'state_action',{'state':'zhao','action':'appointment','office':'supreme_commander','person_ref':'char_tang_wei','capabilities':['state_command']})
    with pytest.raises(PermissionError):
        execute(campaign,'recruitment',{'state':'zhao','personnel':1000,'source_stratum':'agricultural','role':'line_infantry'})
    with pytest.raises(PermissionError):
        execute(campaign,'scene_consequence',{'summary':'forged NPC actor'},actor='char_riboku')
    assert meta(campaign)['revision']==start
    champion = json.load(open(campaign/'state/formations/tang-champions-first.json'))
    assert champion['command_authority'] == 'char_tang_wei'
    assert champion['administrative_owner'] == 'house_tang'


def test_split_merge_dissolve_conserve_people_equipment_supplies_mounts_and_ammo(campaign):
    ref='formation_conservation_qin'
    qin_depot='loc_qin_eastern_depot'
    commander='char_test_conservation_qin_commander'
    _materialize_test_commander(campaign,state='qin',person_ref=commander,location_ref=qin_depot)
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':ref,'role':'line_infantry','personnel':1000,'location_ref':qin_depot,'commander_ref':commander})
    execute_internal(campaign,'resupply',{'formation_ref':ref,'food_kg':5000,'war_arrows':10000,'war_bolts':7000})
    idx=json.load(open(campaign/'state/index/owner-index.json'))['owners']; path=campaign/idx[ref]
    before=json.load(open(path)); force0=json.load(open(campaign/'state/forces/state-qin.json')); depot0=json.load(open(campaign/'state/depots/qin.json'))
    before_equipment=sum(before['equipment_units_by_role'].values()); before_food=before['logistics']['food_kg']; before_arrows=before['logistics']['war_arrows']; before_bolts=before['logistics']['war_bolts']; before_mounts=sum(before['mounts'].values())

    child='formation_conservation_qin_child'
    execute_internal(campaign,'formation_split',{'formation_ref':ref,'new_formation_ref':child,'personnel':400})
    idx=json.load(open(campaign/'state/index/owner-index.json'))['owners']; parent=json.load(open(campaign/idx[ref])); split=json.load(open(campaign/idx[child]))
    assert parent['personnel']+split['personnel']==1000
    assert sum(parent['equipment_units_by_role'].values())+sum(split['equipment_units_by_role'].values())==before_equipment
    assert parent['logistics']['food_kg']+split['logistics']['food_kg']==before_food
    assert parent['logistics']['war_arrows']+split['logistics']['war_arrows']==before_arrows
    assert parent['logistics']['war_bolts']+split['logistics']['war_bolts']==before_bolts
    assert sum(parent['mounts'].values())+sum(split['mounts'].values())==before_mounts

    execute_internal(campaign,'formation_merge',{'formation_refs':[ref,child]})
    merged=json.load(open(campaign/idx[ref]))
    assert merged['personnel']==1000
    assert sum(merged['equipment_units_by_role'].values())==before_equipment
    assert merged['logistics']['food_kg']==before_food and merged['logistics']['war_arrows']==before_arrows and merged['logistics']['war_bolts']==before_bolts

    execute_internal(campaign,'formation_dissolve',{'formation_ref':ref})
    force1=json.load(open(campaign/'state/forces/state-qin.json')); depot1=json.load(open(campaign/'state/depots/qin.json'))
    assert force1['available_by_role']['line_infantry']==force0['available_by_role']['line_infantry']+1000
    assert force1['available_equipment_units_by_role']['line_infantry']==force0['available_equipment_units_by_role']['line_infantry']+before_equipment
    assert depot1['stocks']['grain_kg']==depot0['stocks']['grain_kg']+before_food
    assert depot1['stocks']['war_arrows']==depot0['stocks']['war_arrows']+before_arrows
    assert depot1['stocks']['war_bolts']==depot0['stocks']['war_bolts']+before_bolts


def test_battle_requires_location_mobilization_and_active_operation_contact(campaign):
    q='formation_causal_qin'; z='formation_causal_zhao'
    qcmd='char_test_causal_qin_commander'; zcmd='char_test_causal_zhao_commander'
    _materialize_test_commander(campaign,state='qin',person_ref=qcmd,location_ref='loc_qin_eastern_depot')
    _materialize_test_commander(campaign,state='zhao',person_ref=zcmd,location_ref='loc_zhao_regional_01')
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':q,'role':'line_infantry','personnel':1000,'location_ref':'loc_qin_eastern_depot','commander_ref':qcmd})
    execute_internal(campaign,'formation_create',{'state':'zhao','formation_ref':z,'role':'line_infantry','personnel':1000,'location_ref':'loc_zhao_regional_01','commander_ref':zcmd})
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
    opponent='char_test_personal_combat_opponent'
    player_location=json.load(open(campaign/'state/player.json'))['location']
    _materialize_test_commander(campaign,state='qin',person_ref=opponent,location_ref=player_location)
    t0=CampaignTime.parse(meta(campaign)['time'])
    execute(campaign,'individual_training',{'focus':'Formation Command','hours':2})
    t1=CampaignTime.parse(meta(campaign)['time']); assert t0.seconds_until(t1)==7200
    execute(campaign,'health_injury',{'injury':'test injury','severity':'severe'})
    execute(campaign,'health_recovery',{'hours':8}); assert json.load(open(campaign/'state/player.json'))['health']=='injured'
    execute(campaign,'health_recovery',{'hours':64}); assert json.load(open(campaign/'state/player.json'))['health']=='healthy'
    before=CampaignTime.parse(meta(campaign)['time']); result=execute(campaign,'personal_combat',{'opponent_ref':opponent,'objective':'controlled spar','duration_minutes':30}).receipt.result; after=CampaignTime.parse(meta(campaign)['time'])
    assert result['opponent_ref']==opponent and before.seconds_until(after)==1800


def test_doctrine_supply_terrain_and_command_drive_battle_score(campaign):
    q='formation_score_qin'; z='formation_score_zhao'
    qcmd='char_test_score_qin_commander'; zcmd='char_test_score_zhao_commander'
    _materialize_test_commander(campaign,state='qin',person_ref=qcmd,location_ref='loc_qin_eastern_depot')
    _materialize_test_commander(campaign,state='zhao',person_ref=zcmd,location_ref='loc_zhao_regional_01')
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':q,'role':'line_infantry','personnel':2000,'location_ref':'loc_qin_eastern_depot','commander_ref':qcmd})
    execute_internal(campaign,'formation_create',{'state':'zhao','formation_ref':z,'role':'line_infantry','personnel':2000,'location_ref':'loc_zhao_regional_01','commander_ref':zcmd})
    execute_internal(campaign,'formation_doctrine_set',{'formation_ref':q,'doctrine_ref':'doc.external_state_force.standard','doctrine_behavior':{'reserve_commitment':100,'casualty_tolerance':'high'}})
    execute_internal(campaign,'formation_doctrine_set',{'formation_ref':z,'doctrine_ref':'doc.external_state_force.standard','doctrine_behavior':{'reserve_commitment':10,'casualty_tolerance':'low'}})
    prepare_field_formation(campaign,q,food_per_person=7); prepare_field_formation(campaign,z,food_per_person=7)
    # Establish an explicit contact-time supply contrast in the disposable
    # fixture. Route topology is allowed to change; this test owns the exact
    # food condition whose combat effect it is asserting. Both sides still
    # retain enough field food to pass battle admission.
    owners=json.load(open(campaign/'state/index/owner-index.json'))['owners']
    qpath=campaign/owners[q]; zpath=campaign/owners[z]
    qdoc=json.load(open(qpath)); zdoc=json.load(open(zpath))
    qdoc['logistics']['food_kg']=4000; zdoc['logistics']['food_kg']=1000
    qpath.write_text(json.dumps(qdoc,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
    zpath.write_text(json.dumps(zdoc,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
    qcmd_path=campaign/owners[qcmd]; zcmd_path=campaign/owners[zcmd]
    qcmd_doc=json.load(open(qcmd_path)); zcmd_doc=json.load(open(zcmd_path))
    for skill in ('Formation Command','Tactics','Leadership','Strategy','Mass Combat'):
        qcmd_doc['skills'][skill]=150
        zcmd_doc['skills'][skill]=0
    qcmd_path.write_text(json.dumps(qcmd_doc,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
    zcmd_path.write_text(json.dumps(zcmd_doc,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
    subprocess.run(['git','-C',str(campaign),'add',str(qpath.relative_to(campaign)),str(zpath.relative_to(campaign)),str(qcmd_path.relative_to(campaign)),str(zcmd_path.relative_to(campaign))],check=True)
    subprocess.run(['git','-C',str(campaign),'commit','--quiet','-m','test battle supply contrast'],check=True)
    op=activate_operation(campaign,'operation_score_test',[q,z])
    r=execute_internal(campaign,'battle_resolve',{'attacker_formation_refs':[q],'defender_formation_refs':[z],'operation_ref':op}).receipt.result
    assert r['terrain_kind']=='pass'
    assert r['score_breakdown'][q]['doctrine'] != r['score_breakdown'][z]['doctrine']
    assert r['score_breakdown'][q]['supply'] > r['score_breakdown'][z]['supply']
    assert r['score_breakdown'][q]['command'] != r['score_breakdown'][z]['command']


def test_release_has_one_current_authority_tree_and_local_release_gate(campaign):
    assert not (campaign/'archive').exists()
    assert not (campaign/'state/rel').exists()
    assert (campaign/'state/relationships.json').is_file()
    idx=json.load(open(campaign/'state/index/owner-index.json'))['owners']
    for path in (campaign/'state').rglob('*.json'):
        doc=json.load(open(path))
        if isinstance(doc,dict) and isinstance(doc.get('owner_id'),str):
            assert idx.get(doc['owner_id'])==path.relative_to(campaign).as_posix()
    rt=json.load(open(campaign/'state/runtime.json'))
    # The four former Tang defense companies are now permanent Bastion Corps
    # institutions and therefore no longer own mercenary causal hosts.
    assert sum(1 for h in rt['hosts'].values() if h.get('kind')=='mercenary')==120
    assert not (campaign/'.github/workflows').exists()
    assert (campaign/'tools/quick_check.py').is_file()
    assert (campaign/'tools/test_changed.py').is_file()
    assert (campaign/'tools/run_release_suite.py').is_file()


def test_mixed_role_formation_lifecycle_preserves_role_composition_and_cohorts(campaign):
    ref='formation_mixed_lifecycle_qin'
    execute_internal(campaign,'formation_create',{
        'state':'qin','formation_ref':ref,'personnel':1000,
        'composition':{'line_infantry':600,'missile_crossbow':400},
        'location_ref':'loc_qin_eastern_depot',
    })
    owners=json.load(open(campaign/'state/index/owner-index.json'))['owners']
    formation=json.load(open(campaign/owners[ref]))
    assert formation['composition']=={'line_infantry':600,'missile_crossbow':400}

    execute_internal(campaign,'formation_reconstitute',{'formation_ref':ref,'target_personnel':1200})
    formation=json.load(open(campaign/owners[ref]))
    assert formation['composition']=={'line_infantry':720,'missile_crossbow':480}
    assert formation['last_reconstitution_by_role']=={'line_infantry':120,'missile_crossbow':80}

    child='formation_mixed_lifecycle_qin_child'
    execute_internal(campaign,'formation_split',{'formation_ref':ref,'new_formation_ref':child,'personnel':300})
    owners=json.load(open(campaign/'state/index/owner-index.json'))['owners']
    parent=json.load(open(campaign/owners[ref])); split=json.load(open(campaign/owners[child]))
    assert parent['composition']=={'line_infantry':540,'missile_crossbow':360}
    assert split['composition']=={'line_infantry':180,'missile_crossbow':120}
    assert split.get('commander_ref') is None and split.get('deputy_ref') is None

    force=json.load(open(campaign/'state/forces/state-qin.json'))
    assert force['allocated_to_formations'][ref]['composition']==parent['composition']
    assert force['allocated_to_formations'][child]['composition']==split['composition']

    execute_internal(campaign,'formation_merge',{'formation_refs':[ref,child]})
    merged=json.load(open(campaign/owners[ref]))
    assert merged['personnel']==1200
    assert merged['composition']=={'line_infantry':720,'missile_crossbow':480}
    force=json.load(open(campaign/'state/forces/state-qin.json'))
    assert force['allocated_to_formations'][ref]['composition']==merged['composition']

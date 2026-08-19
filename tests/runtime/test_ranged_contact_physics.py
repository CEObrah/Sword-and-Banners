from __future__ import annotations

import json
import subprocess

from sword_runtime.anatomy import resolve_actual_contact_target
from sword_runtime.contact_physics import projectile_flight_resolution


def _commit(campaign, *paths: str) -> None:
    subprocess.run(['git','-C',str(campaign),'add',*paths],check=True)
    subprocess.run(['git','-C',str(campaign),'commit','--quiet','-m','test: ranged contact physics'],check=True)


def test_bow_launch_power_uses_draw_capability_but_crossbow_mechanism_does_not(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner
    planner=RepositoryCommandPlanner(campaign)
    arrow=planner._combat_weapon('ammo_arrow_war')
    bolt=planner._combat_weapon('ammo_bolt_war')
    bow=planner._combat_weapon('weapon_bow_great_war')
    crossbow=planner._combat_weapon('weapon_crossbow')

    weak=projectile_flight_resolution(bow,arrow,distance_m=100,weapon_skill=150,strength=60,coordination=150,awareness=150)
    strong=projectile_flight_resolution(bow,arrow,distance_m=100,weapon_skill=150,strength=140,coordination=150,awareness=150)
    assert strong['launch_power_index'] > weak['launch_power_index']
    assert strong['impact_index'] > weak['impact_index']
    assert strong['flight_time_seconds'] < weak['flight_time_seconds']
    assert strong['mechanism_sets_launch_power'] is False

    weak_crossbow=projectile_flight_resolution(crossbow,bolt,distance_m=100,weapon_skill=150,strength=20,coordination=150,awareness=150)
    strong_crossbow=projectile_flight_resolution(crossbow,bolt,distance_m=100,weapon_skill=150,strength=220,coordination=150,awareness=150)
    assert weak_crossbow['launch_power_index'] == strong_crossbow['launch_power_index']
    assert weak_crossbow['impact_index'] == strong_crossbow['impact_index']
    assert weak_crossbow['mechanism_sets_launch_power'] is True


def test_actual_contact_can_differ_from_aim_after_marginal_defense():
    clean=resolve_actual_contact_target(aim_zone='forearms_hands',aim_side='right',aim_structure='wrist',contact_grade='clean',defense_method='dodge',margin=30,seed=1)
    assert clean['structure']=='wrist' and clean['aim_preserved'] is True
    shifted=None
    for seed in range(100):
        row=resolve_actual_contact_target(aim_zone='forearms_hands',aim_side='right',aim_structure='wrist',contact_grade='solid',defense_method='dodge',margin=2,seed=seed)
        if not row['aim_preserved']:
            shifted=row; break
    assert shifted is not None
    assert shifted['structure'] in {'hand','forearm'}


def test_formation_ranged_profile_has_finite_shield_attrition_and_armor_penetration(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner
    planner=RepositoryCommandPlanner(campaign)
    attacker=[{
        'count':500,'ranged_score':130,'ranged_effective_range_m':145,'ranged_max_direct_range_m':270,
        'ranged_cycle_seconds':5.8,'ranged_power_index':82,'ranged_weapon_id':'weapon_bow_heavy_war',
        'ammunition_item':'ammo_arrow_war','ammunition_resource':'war_arrows','equipment_condition_pct':100,
        'ranged_strength':125,'ranged_coordination':130,'ranged_awareness':125,
    }]
    target=[{
        'count':500,'shield_structure':85,'shield_coverage_degrees':115,'shield_condition_pct':100,
        'armor_protection_index':55,'protection_index':70,'formation_cohesion':80,'formation_training':75,
    }]
    plan={'consumed_by_resource':{'war_arrows':1500}}
    profile=planner._combat_ranged_contact_profile(attacker,plan,target)
    assert profile['projectiles_fired']==1500
    assert profile['weighted_impact_index'] > 0
    assert profile['weighted_penetration_index'] > 0
    assert 0 < profile['shield_intercept_fraction'] < 1
    assert profile['shield_wear_pct'] > 0
    assert profile['armor_penetration_ratio'] > 0
    assert profile['projectile_recovery_base'] > 0


def test_personal_bow_trace_records_aim_flight_defense_and_actual_contact(campaign):
    from conftest import execute, execute_internal

    opponent='char_test_ranged_contact_target'
    player_path=campaign/'state/player.json'
    player=json.loads(player_path.read_text())
    location=player['location']
    execute_internal(campaign,'person_materialize',{
        'state':'qin','person_ref':opponent,'name':'Ranged Contact Target','birth_date':'270-BCE-01-01',
        'role':'command_personnel','source_location_ref':location,
    })
    owners=json.loads((campaign/'state/index/owner-index.json').read_text())['owners']
    op_path=campaign/owners[opponent]
    op=json.loads(op_path.read_text())
    op['equipment_loadout_id']='loadout_state_line_infantry'
    op.setdefault('attributes',{}).update({'Agility':70,'Coordination':70,'Awareness':70,'Composure':70,'Strength':80})
    op.setdefault('skills',{}).update({'Defense':70,'Shield':80,'Sword':60,'Spear':70})
    op_path.write_text(json.dumps(op,ensure_ascii=False,indent=2)+'\n')
    _commit(campaign,owners[opponent])

    manifest_path=campaign/'state/player-detail/equipment-manifest.json'
    manifest_before=json.loads(manifest_path.read_text())
    arrow_before=sum(int(row.get('quantity',0)) for row in manifest_before.get('equipment_manifest',[]) if row.get('item_id')=='ammo_arrow_war' and any(tok in str(row.get('current_state','')).lower() for tok in ('equipped','readied','quivered')))
    result=execute(campaign,'personal_combat',{
        'opponent_ref':opponent,'objective':'controlled spar','duration_minutes':5,'distance_m':80,
        'intent_sequence':['shoot an arrow at the right wrist'],
    }).receipt.result
    releases=[r for r in result['causal_trace'] if r.get('kind')=='projectile_release']
    contacts=[r for r in result['causal_trace'] if r.get('kind')=='contact' and r.get('projectile_item_id')]
    assert releases, result['causal_trace']
    assert releases[0]['aim_structure']=='wrist'
    assert float(releases[0]['flight_time_seconds']) > 0
    assert releases[0]['mechanism_sets_launch_power'] is False
    assert contacts, result['causal_trace']
    contact=contacts[0]
    assert contact['aim_structure']=='wrist'
    assert contact['actual_contact_structure']
    assert float(contact['projectile_flight']['penetration_index']) > 0
    assert float(contact['armor_resolution']['incoming_penetration_index']) >= 0
    manifest_after=json.loads(manifest_path.read_text())
    arrow_after=sum(int(row.get('quantity',0)) for row in manifest_after.get('equipment_manifest',[]) if row.get('item_id')=='ammo_arrow_war' and any(tok in str(row.get('current_state','')).lower() for tok in ('equipped','readied','quivered')))
    player_after=json.loads(player_path.read_text())
    carried_after=int(player_after.get('combat_state',{}).get('projectile_ammunition',{}).get('ammo_arrow_war',0))
    assert arrow_after == carried_after
    assert arrow_after == arrow_before-len(releases)

    # Personal combat must persist recoverable projectiles into the exact field
    # owner after the combat save, not merely return transient recovery candidates.
    import hashlib
    history=json.loads((campaign/'state/history/events/index.json').read_text())
    combat_event=next(row for row in reversed(history.get('events',[])) if row.get('kind')=='personal_combat')
    expected_field=0
    for row in result.get('projectile_recovery_candidates',[]):
        if row.get('actor_ref')!='char_tang_wei' or row.get('projectile_item_id')!='ammo_arrow_war':
            continue
        fraction=max(0.0,min(.95,float(row.get('recoverable_fraction',0) or 0)))
        token=(str(combat_event['event_id'])+'|'+str(row.get('release_event_id',''))+'|ammo_arrow_war').encode()
        roll=(int(hashlib.sha256(token).hexdigest()[:8],16)%1000000)/1000000.0
        if roll < fraction:
            expected_field += 1
    field_rows=[row for row in player_after.get('combat_state',{}).get('field_projectiles',[]) if row.get('projectile_item_id')=='ammo_arrow_war' and row.get('location_ref')==player_after['location']]
    assert sum(int(row.get('quantity',0)) for row in field_rows) == expected_field


def test_released_projectile_continues_when_shooter_collapses_before_contact(campaign):
    from conftest import execute, execute_internal

    opponent = 'char_test_released_projectile_target'
    player_path = campaign / 'state/player.json'
    player = json.loads(player_path.read_text())
    execute_internal(campaign, 'person_materialize', {
        'state': 'qin', 'person_ref': opponent, 'name': 'Released Projectile Target',
        'birth_date': '270-BCE-01-01', 'role': 'command_personnel',
        'source_location_ref': player['location'],
    })
    owners = json.loads((campaign / 'state/index/owner-index.json').read_text())['owners']
    op_path = campaign / owners[opponent]
    target = json.loads(op_path.read_text())
    target.setdefault('attributes', {}).update({'Agility': 35, 'Coordination': 35, 'Awareness': 35, 'Composure': 50})
    target.setdefault('skills', {}).update({'Defense': 25, 'Athletics': 25})
    op_path.write_text(json.dumps(target, ensure_ascii=False, indent=2) + '\n')

    wound = {
        'wound_id': 'test_bleeding_shooter', 'active': True, 'severity': 'minor', 'severity_index': 1,
        'body_zone': 'forearms_hands', 'side': 'left', 'contact_structure': 'superficial_vessel',
        'mechanism': 'cut', 'source_weapon': 'test', 'pain': 0,
        'bleeding': {'rate_units_per_minute': 10, 'controlled': False},
        'respiratory_compromise': 0, 'neurological_impairment': 0,
    }
    player['injuries'] = [dict(wound)]
    player['injury_state'] = dict(wound)
    player['physiology_state'] = {'blood_loss_units': '99.7'}
    player_path.write_text(json.dumps(player, ensure_ascii=False, indent=2) + '\n')
    _commit(campaign, owners[opponent], 'state/player.json')

    result = execute(campaign, 'personal_combat', {
        'opponent_ref': opponent, 'objective': 'controlled spar', 'duration_minutes': 5,
        'distance_m': 80, 'intent_sequence': ['shoot an arrow at the torso'],
    }).receipt.result
    release = next(row for row in result['causal_trace'] if row.get('kind') == 'projectile_release' and row.get('actor_ref') == 'char_tang_wei')
    contact = next(row for row in result['causal_trace'] if row.get('kind') == 'contact' and row.get('projectile_item_id') == 'ammo_arrow_war')
    collapse = next(row for row in result['causal_trace'] if row.get('kind') == 'physiology_state' and row.get('actor_ref') == 'char_tang_wei' and row.get('consciousness') == 'unconscious')
    assert float(release['release_at_s']) < float(contact['at_s'])
    assert float(release['release_at_s']) < float(collapse['at_s']) <= float(contact['at_s'])
    assert contact['projectile_item_id'] == 'ammo_arrow_war'
    assert json.loads(player_path.read_text()).get('combat_state', {}).get('incapacitated') is True

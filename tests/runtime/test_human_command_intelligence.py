from __future__ import annotations

from sword_runtime.commander_cognition import command_decision_policy, commander_cognition, state_military_identity
from sword_runtime.military_merit import battle_service_appraisal
from sword_runtime.morale import resolve_formation_morale
from sword_runtime.strategic_war_planning import build_interstate_strategic_plan


def planner_for(campaign):
    from sword_runtime.production_planner import ProductionCampaignPlanner
    p = ProductionCampaignPlanner(campaign)
    p._reset()
    return p


def test_commander_cognition_changes_decisions_not_combat_stats(campaign):
    p = planner_for(campaign)
    ousen = command_decision_policy(p, 'char_ousen', side_ref='qin')
    moubu = command_decision_policy(p, 'char_mou_bu', side_ref='qin')
    assert ousen['cognition']['archetype'] == 'contingency_preservation'
    assert moubu['cognition']['archetype'] == 'decisive_force'
    assert ousen['offensive_advantage_required_milli'] > moubu['offensive_advantage_required_milli']
    assert ousen['report_confidence_floor_milli'] > moubu['report_confidence_floor_milli']
    assert moubu['pursuit_limit_milli'] > ousen['pursuit_limit_milli']
    # The cognition result exposes no attack/damage/strength bonus.
    serialized = str(ousen).lower()
    assert 'combat_bonus' not in serialized and 'damage_bonus' not in serialized


def test_state_identity_is_structured_and_causal_policy_input(campaign):
    p = planner_for(campaign)
    qin = state_military_identity(p, 'qin')
    zhao = state_military_identity(p, 'zhao')
    han = state_military_identity(p, 'han')
    assert qin['operational_bias_milli']['logistics_discipline'] > zhao['operational_bias_milli']['logistics_discipline']
    assert zhao['operational_bias_milli']['mobile_emphasis'] > qin['operational_bias_milli']['mobile_emphasis']
    assert han['operational_bias_milli']['fortification_emphasis'] > qin['operational_bias_milli']['fortification_emphasis']


def test_strategic_plan_persists_compact_contingencies_not_cognition_blob(campaign):
    p = planner_for(campaign)
    at = str(p.read('state/meta.json')['time'])
    config = p._interstate_theater_config(p.read('game/data/world/autonomous-theaters.json'))
    theater = next(row for row in config['theaters'] if row['theater_ref'] == 'qin_zhao_gyou')
    plan = build_interstate_strategic_plan(
        p,
        theater_ref='test_cognition_plan', attacker='qin', defender='zhao', primary_target='loc_gyou',
        attacker_formation_refs=theater['formation_ref_lists']['qin'],
        defender_formation_refs=theater['formation_ref_lists']['zhao'], at=at,
    )
    assert plan['operational_contingencies']['qin']['replan_on_route_block'] is True
    assert plan['side_decision_policies']['qin']['lead_commander_ref']
    assert 'cognition' not in plan['side_decision_policies']['qin']
    assert 'reinforcement_admission_history' not in plan


def test_registered_morale_authority_uses_current_zero_to_one_hundred_scale(campaign):
    p = planner_for(campaign)
    steady = resolve_formation_morale(p, base_morale=78, cohesion=80)
    shocked = resolve_formation_morale(
        p, base_morale=78, cohesion=50, recent_casualty_fraction=0.20,
        cumulative_casualty_fraction=0.20, supply_condition='critical', registered_fear_pressure=6,
    )
    assert steady['effective_morale'] == 78
    assert 0 <= shocked['effective_morale'] < steady['effective_morale'] <= 100
    assert shocked['components']['casualty_pressure'] > 0
    assert shocked['components']['supply_pressure'] > 0
    assert shocked['rule_ref'] == 'game/data/mechanics/morale.json'


def test_merit_appraisal_rewards_result_adversity_and_stewardship_without_body_count(campaign):
    efficient = battle_service_appraisal(
        won=True, command_role='commander', own_personnel_before=10000, enemy_personnel_before=13000,
        own_casualties=500, battle_hours=8, operational_contact=True,
    )
    costly = battle_service_appraisal(
        won=True, command_role='commander', own_personnel_before=10000, enemy_personnel_before=13000,
        own_casualties=3500, battle_hours=8, operational_contact=True,
    )
    difficult_loss = battle_service_appraisal(
        won=False, command_role='commander', own_personnel_before=8000, enemy_personnel_before=16000,
        own_casualties=800, battle_hours=8, operational_contact=True,
    )
    assert efficient['adjudicated_merit'] > costly['adjudicated_merit']
    assert difficult_loss['adjudicated_merit'] >= 1
    assert efficient['relative_enemy_strength_milli'] == 1300
    assert efficient['casualty_stewardship'] == 'well_preserved'


def test_registered_morale_applies_command_loss_shock(campaign):
    p = planner_for(campaign)
    intact = resolve_formation_morale(p, base_morale=72, cohesion=60)
    shocked = resolve_formation_morale(
        p, base_morale=72, cohesion=60, commander_lost=True, key_staff_lost=True,
    )
    assert shocked['effective_morale'] < intact['effective_morale']
    assert shocked['components']['command_loss_pressure'] > 0


def test_obsolete_paper_career_formulas_and_role_templates_are_not_active_data(campaign):
    p = planner_for(campaign)
    career = p.read('game/data/mechanics/career.json')
    assert set(career) == {'schema', 'authority', 'promotion_rule', 'service_models'}
    assert set(career['service_models']) == {'army_model_mercenary'}
    serialized = str(career).lower()
    assert 'effective_command_capacity' not in serialized
    assert 'merit_final_value' not in serialized
    assert 'character_role_templates' not in serialized


def test_static_behavior_profile_is_demand_loaded_and_causally_bounded(campaign, monkeypatch):
    p = planner_for(campaign)
    with_profile = commander_cognition(p, 'char_heki', side_ref='qin')
    assert with_profile['behavior_profile_ref'] == 'game/data/people/behavior-profiles/char_heki.json'
    assert 'avoid unsupported improvisation' in with_profile['behavior_cues']

    original_read = p.read
    def no_profile(path):
        if path == 'game/data/people/behavior-profiles/char_heki.json':
            raise FileNotFoundError(path)
        return original_read(path)
    monkeypatch.setattr(p, 'read', no_profile)
    without_profile = commander_cognition(p, 'char_heki', side_ref='qin')
    assert without_profile['behavior_profile_ref'] is None
    assert with_profile['dimensions_milli'] != without_profile['dimensions_milli']
    # The static profile changes bounded decision cognition only, never capabilities.
    assert max(
        abs(with_profile['dimensions_milli'][key] - without_profile['dimensions_milli'][key])
        for key in with_profile['dimensions_milli']
    ) <= 150


def test_saved_operational_withdrawal_contingency_is_a_real_decision_boundary():
    from sword_runtime.strategic_war_planning import contingency_withdrawal_decision

    plan = {
        'operational_contingencies': {
            'qin': {'withdraw_if_local_ratio_below_milli': 700},
            'zhao': {'withdraw_if_local_ratio_below_milli': 600},
        }
    }
    decision = contingency_withdrawal_decision(
        plan, attacker='qin', defender='zhao', attacker_power=600, defender_power=1000,
        attacker_reserve_available=False, defender_reserve_available=False,
    )
    assert decision and decision['side'] == 'qin'
    assert decision['local_ratio_milli'] == 600
    assert decision['threshold_milli'] == 700
    # An intact reserve satisfies the planned fallback instead of forcing retreat.
    assert contingency_withdrawal_decision(
        plan, attacker='qin', defender='zhao', attacker_power=600, defender_power=1000,
        attacker_reserve_available=True, defender_reserve_available=False,
    ) is None
    # Siege/enclosure contacts are deliberately handled by siege physics/psychology.
    assert contingency_withdrawal_decision(
        plan, attacker='qin', defender='zhao', attacker_power=600, defender_power=1000,
        attacker_reserve_available=False, defender_reserve_available=False, fortified_contact=True,
    ) is None


def test_obsolete_unit_formation_paper_surface_is_removed_from_active_tree(campaign):
    import json

    dead_paths = [
        'game/data/organization/formation-templates.json',
        'game/data/organization/reconstitution-policies.json',
        'game/data/organization/standing-procedures.json',
        'game/data/organization/unit-model.json',
        'game/data/content/world-event-archetypes.json',
        'game/data/mechanics/world-representation-authority.json',
        'game/data/world/regional-lords.json',
        'game/schemas/formation.schema.json',
        'game/schemas/unit.schema.json',
    ]
    for rel in dead_paths:
        assert not (campaign / rel).exists(), rel

    registry = json.loads((campaign / 'game/schemas/registry.json').read_text(encoding='utf-8'))
    for schema_id in (
        'formation', 'unit', 'formation-library', 'unit-model',
        'reconstitution-policies', 'standing-procedures', 'sword-regional-lord-catalog',
    ):
        assert schema_id not in registry

    for path in (campaign / 'state/merc').rglob('*.json'):
        assert 'reconstitution_policy_ref' not in path.read_text(encoding='utf-8')

    org_rule = (campaign / 'game/rules/org.md').read_text(encoding='utf-8')
    assert 'state/formations/' in org_rule
    assert 'is an establishment class of a persistent formation' in org_rule
    assert 'formation is a temporary operational/battle arrangement' not in org_rule.lower()


def test_current_formation_doctrine_routes_resolve_to_valid_canonical_records(campaign):
    import json

    doctrines = json.loads((campaign / 'game/data/mil/doctrines.json').read_text(encoding='utf-8'))
    roles = json.loads((campaign / 'game/data/mil/doctrine-role-profiles.json').read_text(encoding='utf-8'))['profiles']
    overlays = json.loads((campaign / 'game/data/mil/institution-doctrine-overlays.json').read_text(encoding='utf-8'))['overlays']
    record_index = doctrines['record_index']

    for path in (campaign / 'state/formations').rglob('*.json'):
        row = json.loads(path.read_text(encoding='utf-8'))
        ref = row.get('doctrine_ref')
        if not ref:
            continue
        assert ref in record_index, (path.relative_to(campaign).as_posix(), ref)
        target = campaign / record_index[ref]
        assert target.exists(), (ref, record_index[ref])

    for ref, rel in record_index.items():
        record = json.loads((campaign / rel).read_text(encoding='utf-8'))
        doctrine = record['doctrine']
        role_ref = doctrine.get('role_profile_ref')
        if role_ref:
            role_key = role_ref.rsplit('#', 1)[-1]
            assert role_key in roles, (ref, role_key)
        overlay_ref = doctrine.get('institution_overlay_ref')
        if overlay_ref:
            overlay_key = overlay_ref.rsplit('#', 1)[-1]
            assert overlay_key in overlays, (ref, overlay_key)

    scout_rel = record_index['doc.merc_black_banner.scout']
    scout = json.loads((campaign / scout_rel).read_text(encoding='utf-8'))
    assert scout['doctrine']['role_profile_ref'].endswith('#reconnaissance')
    assert 'household_combined_arms' in record_index
    assert 'doc.house_tang.house_infantry' in record_index
    assert 'doc.house_tang.house_cavalry' in record_index
    assert 'doc.house_tang.home_defense' in record_index
    assert 'doc.state_qin.regular_combined_arms' in record_index

    for dead in ('_canonical.2a22ba6cd43b.json', '_canonical.33d72a8276b2.json'):
        assert not (campaign / 'game/data/mil/doctrine-records' / dead).exists()

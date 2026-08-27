from __future__ import annotations


def test_wei_saved_doctrine_prefers_function_denial_softspots(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    wei = planner.read('state/player.json')
    doctrine = planner.read('game/data/mil/doctrine-records/doc.tang_wei.personal_combat.json')['doctrine']['targeting']
    assert wei['combat_doctrine_ref'] == 'doc.tang_wei.personal_combat'
    assert doctrine['name'] == 'precision_function_denial'
    assert doctrine['movement_economy'].startswith('No wasted movement')

    target = {'anatomy_state': {'structures': {}}}
    aim = planner._personal_aim_plan(
        None, lethal_intent=False, seed=17, sequence=1,
        actor=wei, target_person=target, target_eq={'loadout': {}},
    )
    assert aim['selection_basis'] == 'registered_combat_doctrine'
    assert aim['structure'] == 'wrist'
    assert aim['purpose'] == 'disable_weapon_control'


def test_wei_doctrine_skips_destroyed_structure_and_explicit_aim_overrides(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    wei = planner.read('state/player.json')
    first = planner._personal_aim_plan(
        None, lethal_intent=False, seed=29, sequence=2,
        actor=wei, target_person={'anatomy_state': {'structures': {}}}, target_eq={'loadout': {}},
    )
    key = first['structure'] if first['side'] == 'midline' else f"{first['side']}_{first['structure']}"
    target = {'anatomy_state': {'structures': {key: {'status': 'destroyed', 'permanent': True}}}}
    second = planner._personal_aim_plan(
        None, lethal_intent=False, seed=29, sequence=2,
        actor=wei, target_person=target, target_eq={'loadout': {}},
    )
    assert second['structure'] != first['structure'] or second['side'] != first['side']

    explicit = planner._personal_aim_plan(
        'cut at the left ankle', lethal_intent=False, seed=29, sequence=3,
        actor=wei, target_person=target, target_eq={'loadout': {}},
    )
    assert explicit['selection_basis'] == 'declared_intent'
    assert explicit['body_zone'] == 'lower_legs_feet'
    assert explicit['side'] == 'left'
    assert explicit['structure'] == 'ankle'


def test_wei_lethal_doctrine_prefers_fast_vital_line_without_overriding_player_lethality(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    wei = planner.read('state/player.json')
    aim = planner._personal_aim_plan(
        None, lethal_intent=True, seed=7, sequence=1,
        actor=wei, target_person={'anatomy_state': {'structures': {}}}, target_eq={'loadout': {}},
    )
    assert aim['selection_basis'] == 'registered_combat_doctrine'
    assert aim['structure'] == 'neck'
    assert 'lethal' in aim['purpose']
    doctrine = planner.read('game/data/mil/doctrine-records/doc.tang_wei.personal_combat.json')['doctrine']['targeting']
    assert 'player decision' in doctrine['protected_lethality_rule']


def test_armpit_is_an_exact_aimed_structure(campaign):
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    wei = planner.read('state/player.json')
    aim = planner._personal_aim_plan(
        'thrust into the right armpit', lethal_intent=True, seed=3, sequence=1,
        actor=wei, target_person={'anatomy_state': {'structures': {}}}, target_eq={'loadout': {}},
    )
    assert aim['body_zone'] == 'upper_torso'
    assert aim['side'] == 'right'
    assert aim['structure'] == 'axilla'

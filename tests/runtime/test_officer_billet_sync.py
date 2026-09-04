from __future__ import annotations

import copy
from pathlib import Path

from sword_runtime.causal_living_world import CausalLivingWorldSwordPlanner
from sword_runtime.officer_personnel import sync_materialized_officer_billets
from sword_runtime.production_runtime_planner import ProductionCampaignPlanner


def test_top_formation_commander_metadata_stays_synchronized(campaign: Path) -> None:
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    formation_ref = 'formation_qin_kanki_raider_host'
    formation = copy.deepcopy(planner.read(planner.owner_path(formation_ref)))
    formation['personnel'] = int(formation['personnel']) + 500
    sync_materialized_officer_billets(planner, formation)

    person = planner.read(planner.owner_path(str(formation['commander_ref'])))
    expected = int(formation['personnel'])
    assert person['command_assignment']['current_command_span'] == expected
    assert person['career_state']['current_command_span'] == expected
    assert person['military_command']['level'] == f'{expected}_commander'
    assert person['role'].startswith(f'{expected}-man Commander, ')
    assert person['career_state']['office_or_command'].startswith(f'{expected}-man Commander, ')


def test_top_formation_commander_metadata_tracks_casualty_depleted_span(campaign: Path) -> None:
    planner = ProductionCampaignPlanner(campaign)
    planner._reset()
    formation_ref = 'formation_red_lance_a'
    formation = copy.deepcopy(planner.read(planner.owner_path(formation_ref)))
    formation['personnel'] = 487
    sync_materialized_officer_billets(planner, formation)

    person = planner.read(planner.owner_path(str(formation['commander_ref'])))
    assert person['command_assignment']['current_command_span'] == 487
    assert person['career_state']['current_command_span'] == 487
    assert person['military_command']['level'] == '487_commander'
    assert person['role'].startswith('487-man Commander, ')
    assert person['career_state']['office_or_command'].startswith('487-man Commander, ')


def test_autonomous_battle_casualties_sync_exact_commander_live_span(campaign: Path) -> None:
    planner = CausalLivingWorldSwordPlanner(campaign)
    planner.PLAYER_ACTOR = planner.read('state/meta.json')['player_id']
    planner._reset()
    formation_ref = 'formation_han_mobile_screen'
    formation_before = planner.read(planner.owner_path(formation_ref))
    commander_ref = str(formation_before['commander_ref'])
    commander_path = planner.owner_path(commander_ref)
    durable_grade = planner.read(commander_path)['military_rank']['grade']

    result = planner._autonomy_apply_battle_losses(
        formation_ref,
        1,
        str(planner.read('state/runtime.json')['world_time']),
        losing_side=False,
        opponent_state='qin',
        seed_material='test-autonomous-commander-live-span',
    )

    formation = planner.read(planner.owner_path(formation_ref))
    commander = planner.read(commander_path)
    expected = int(formation['personnel'])
    assert result['loss'] == 1
    assert expected == int(formation_before['personnel']) - 1
    assert commander['command_assignment']['current_command_span'] == expected
    assert commander['career_state']['current_command_span'] == expected
    assert commander['military_command']['level'] == f'{expected}_commander'
    assert commander['military_rank']['grade'] == durable_grade


def test_state_review_reconstitution_resyncs_exact_commander_live_span(campaign: Path) -> None:
    planner = CausalLivingWorldSwordPlanner(campaign)
    planner.PLAYER_ACTOR = planner.read('state/meta.json')['player_id']
    planner._reset()
    formation_ref = 'formation_han_mobile_screen'
    formation_path = planner.owner_path(formation_ref)
    formation_before = planner.read(formation_path)
    commander_ref = str(formation_before['commander_ref'])
    commander_path = planner.owner_path(commander_ref)
    durable_grade = planner.read(commander_path)['military_rank']['grade']
    at = str(planner.read('state/runtime.json')['world_time'])

    planner._autonomy_apply_battle_losses(
        formation_ref,
        301,
        at,
        losing_side=False,
        opponent_state='qin',
        seed_material='test-state-reconstitution-commander-span',
    )
    depleted = planner.read(formation_path)
    assert int(depleted['personnel']) == 2199

    host = next(
        row for row in planner.read('state/runtime.json')['hosts'].values()
        if row.get('kind') == 'state' and row.get('owner_ref') == 'state_han'
    )
    planner._autonomy_state(host, 1, at)

    formation = planner.read(formation_path)
    commander = planner.read(commander_path)
    expected = int(formation['personnel'])
    assert expected == 2200
    assert commander['command_assignment']['current_command_span'] == expected
    assert commander['career_state']['current_command_span'] == expected
    assert commander['military_command']['level'] == f'{expected}_commander'
    assert commander['military_rank']['grade'] == durable_grade

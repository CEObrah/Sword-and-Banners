from __future__ import annotations

import copy
from pathlib import Path

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

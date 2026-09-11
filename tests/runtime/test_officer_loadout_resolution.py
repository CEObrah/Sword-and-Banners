from pathlib import Path
import json

from sword_runtime.military_loadouts import (
    explicit_personal_loadout_id,
    officer_loadout_id,
)

ROOT = Path(__file__).resolve().parents[2]


def read_json(path: str):
    with (ROOT / path).open('r', encoding='utf-8') as fh:
        return json.load(fh)


def test_explicit_personal_loadout_wins_over_mixed_formation_roles():
    formation = {
        'owner_force_ref': 'force_state_qin',
        'composition': {
            'line_infantry': 1500,
            'archer': 300,
            'light_cavalry': 200,
            'heavy_cavalry': 100,
        },
        'registered_loadouts_by_role': {
            'line_infantry': 'loadout_state_line_infantry',
            'archer': 'loadout_state_archer',
            'light_cavalry': 'loadout_qin_cavalry',
            'heavy_cavalry': 'loadout_qin_heavy_cavalry',
        },
    }
    person = {
        'schema': 'sab_character',
        'personal_loadout_ref': 'loadout_tang_mounted',
        'equipment_loadout_id': 'loadout_named_sword',
    }
    assert explicit_personal_loadout_id(person) == 'loadout_tang_mounted'
    assert officer_loadout_id(read_json, person, formation) == 'loadout_tang_mounted'


def test_mixed_qin_formation_uses_officer_default_not_first_troop_arm():
    formation = {
        'owner_force_ref': 'force_state_qin',
        'composition': {
            'line_infantry': 1500,
            'archer': 300,
            'light_cavalry': 200,
            'heavy_cavalry': 100,
        },
        'registered_loadouts_by_role': {
            'line_infantry': 'loadout_state_line_infantry',
            'archer': 'loadout_state_archer',
            'light_cavalry': 'loadout_qin_cavalry',
            'heavy_cavalry': 'loadout_qin_heavy_cavalry',
        },
    }
    assert officer_loadout_id(read_json, {}, formation) == 'loadout_state_command_personnel'


def test_homogeneous_qin_cavalry_may_use_registered_cavalry_officer_profile():
    formation = {
        'owner_force_ref': 'force_state_qin',
        'composition': {'light_cavalry': 500},
    }
    assert officer_loadout_id(read_json, {}, formation) == 'loadout_qin_cavalry'


def test_house_tang_mixed_officer_without_explicit_personal_issue_uses_foot_command_default():
    formation = {
        'owner_force_ref': 'force_house_tang',
        'composition': {'house_guard': 500, 'tang_champion': 500},
    }
    assert officer_loadout_id(read_json, {}, formation) == 'loadout_tang_foot'

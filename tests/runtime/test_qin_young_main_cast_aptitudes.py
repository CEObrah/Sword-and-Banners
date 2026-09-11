import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _char(name: str):
    return json.loads((ROOT / 'state' / 'char' / name).read_text())


def test_qin_young_main_cast_has_role_specific_heroic_growth_potential():
    shin = _char('shin.json')['aptitude']
    ten = _char('karyoten.json')['aptitude']
    kyoukai = _char('kyoukai.json')['aptitude']
    mouten = _char('mou-ten.json')['aptitude']
    ouhon = _char('ou-hon.json')['aptitude']

    assert shin['physical_learning'] >= 190
    assert shin['tactical_learning'] >= 190
    assert ten['tactical_learning'] >= 190
    assert ten['academic_learning'] >= 190
    assert ten['technical_learning'] >= 175
    # Kyoukai is deliberately calibrated as an elite short-burst fighter with
    # low Endurance. Her physical-learning aptitude is intentionally capped so
    # ordinary training does not erase that stamina weakness; her tactical and
    # technical growth remain exceptional.
    assert kyoukai['physical_learning'] == 150
    assert kyoukai['tactical_learning'] >= 175
    assert kyoukai['technical_learning'] >= 175
    assert mouten['tactical_learning'] >= 190
    assert mouten['academic_learning'] >= 175
    assert mouten['social_learning'] >= 175
    assert ouhon['physical_learning'] >= 190
    assert ouhon['tactical_learning'] >= 190
    assert ouhon['technical_learning'] >= 175


def test_mou_ten_and_ou_hon_are_1000_man_commanders_of_1500_man_units_without_joining_wei():
    mouten = _char('mou-ten.json')
    ouhon = _char('ou-hon.json')
    assert mouten['military_rank']['grade'] == '1000_commander'
    assert ouhon['military_rank']['grade'] == '1000_commander'
    assert mouten['command_assignment']['current_command_span'] == 1500
    assert ouhon['command_assignment']['current_command_span'] == 1500
    assert mouten['command_assignment']['command_group_ref'] == 'cmdgrp.mou_ten.gaku_ka'
    assert ouhon['command_assignment']['command_group_ref'] == 'cmdgrp.ou_hon.gyoku_hou'

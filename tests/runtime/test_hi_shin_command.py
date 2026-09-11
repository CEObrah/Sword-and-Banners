import json
from pathlib import Path

from sword_runtime.cohort_personnel import validate_cohort_ledger
from sword_runtime.production_planner import ProductionCampaignPlanner

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str):
    return json.loads((ROOT / rel).read_text())


def test_hi_shin_is_independent_1000_man_current_command():
    field = _read('state/cmd/command-groups/cmdgrp.tang_wei.field_army.json')
    hi = _read('state/cmd/command-groups/cmdgrp.shin.hi_shin.json')
    assert not any(unit.get('ref') == 'cmdgrp.shin.hi_shin' for unit in field['units'])
    assert field['organizational_state']['current_recursive_strength'] == 9500
    assert hi['parent_command_group_ref'] is None
    assert hi['commander_ref'] == 'char_shin'
    assert hi['organizational_state']['current_recursive_strength'] == 1000
    assert hi['role_assignments']['char_karyoten'] == 'strategist'
    assert hi['standing_doctrine_ref'] == 'doc.hi_shin.command'
    assert hi['units'] == [
        {'kind': 'formation', 'ref': 'formation_qin_hi_shin_main'},
        {'kind': 'formation', 'ref': 'formation_qin_kyoukai_command'},
    ]

    main = _read('state/formations/qin-hi-shin-main.json')
    kyoukai = _read('state/formations/qin-kyoukai-command.json')
    assert main['commander_ref'] == 'char_so_sui'
    assert main['composition'] == {'line_infantry': 300, 'heavy_cavalry': 200}
    assert kyoukai['commander_ref'] == 'char_kyoukai'
    assert kyoukai['personnel'] == 500
    assert main['command_authority'] == kyoukai['command_authority'] == 'char_shin'
    assert _read('state/char/shin.json')['personal_loadout_ref'] == 'loadout_tang_mounted'
    assert _read('state/char/kyoukai.json')['personal_loadout_ref'] == 'loadout_tang_mounted'
    assert _read('state/char/karyoten.json')['personal_loadout_ref'] == 'loadout_tang_mounted'


def test_hi_shin_uses_exactly_1000_conserved_qin_bodies_and_current_mounts():
    force = _read('state/forces/state-qin.json')
    validate_cohort_ledger(force)
    refs = ('formation_qin_hi_shin_main', 'formation_qin_kyoukai_command')
    assert sum(force['allocated_to_formations'][ref]['personnel'] for ref in refs) == 1000
    for ref in refs:
        assert force['allocated_to_formations'][ref]['personnel'] == 500
    mounts = _read('state/mounts/qin.json')['allocated_to_formations']
    assert mounts['formation_qin_hi_shin_main'] == {'horse': 200}
    assert mounts['formation_qin_kyoukai_command'] == {'horse': 200}
    assert 'formation_qin_karyoten_command' not in force['allocated_to_formations']
    assert 'formation_qin_karyoten_command' not in mounts


def test_karyoten_strategist_authority_is_confined_to_independent_hi_shin_subtree(campaign: Path):
    planner = ProductionCampaignPlanner(campaign)
    for ref in ('formation_qin_hi_shin_main', 'formation_qin_kyoukai_command'):
        assert planner._has_formation_operational_authority('char_karyoten', ref)
    assert not planner._has_formation_operational_authority('char_karyoten', 'formation_black_banner_01a')
    karyoten = planner.read(planner.owner_path('char_karyoten'))
    assert karyoten['career_state']['current_command_span'] == 100
    assert karyoten['command_assignment']['command_group_ref'] == 'cmdgrp.shin.hi_shin'


def test_mou_ten_and_ou_hon_are_independent_1500_man_young_commands():
    mouten = _read('state/char/mou-ten.json')
    ouhon = _read('state/char/ou-hon.json')
    assert mouten['command_assignment']['command_group_ref'] == 'cmdgrp.mou_ten.gaku_ka'
    assert ouhon['command_assignment']['command_group_ref'] == 'cmdgrp.ou_hon.gyoku_hou'
    gaku = _read('state/cmd/command-groups/cmdgrp.mou_ten.gaku_ka.json')
    gyoku = _read('state/cmd/command-groups/cmdgrp.ou_hon.gyoku_hou.json')
    assert gaku['parent_command_group_ref'] is None
    assert gyoku['parent_command_group_ref'] is None
    assert gaku['organizational_state']['current_recursive_strength'] == 1500
    assert gyoku['organizational_state']['current_recursive_strength'] == 1500
    assert gaku['standing_doctrine_ref'] == 'doc.gaku_ka.command'
    assert gyoku['standing_doctrine_ref'] == 'doc.gyoku_hou.command'


def test_gaku_ka_and_gyoku_hou_use_two_real_500_house_cavalry_leaves_without_transferring_ownership():
    mou_force = _read('state/forces/house_mou_family.json')
    ou_force = _read('state/forces/house_ou_family.json')
    validate_cohort_ledger(mou_force)
    validate_cohort_ledger(ou_force)
    specs = [
        ('state/formations/gaku-ka-house-a.json', 'force_house_mou_family', 'house_mou_family', 'char_mou_ten', 'char_ko_zen'),
        ('state/formations/gaku-ka-house-b.json', 'force_house_mou_family', 'house_mou_family', 'char_mou_ten', 'char_kan_reki'),
        ('state/formations/gyoku-hou-house-a.json', 'force_house_ou_family', 'house_ou_family', 'char_ou_hon', 'char_ban_you'),
        ('state/formations/gyoku-hou-house-b.json', 'force_house_ou_family', 'house_ou_family', 'char_ou_hon', 'char_shou_taku'),
    ]
    for rel, owner, admin, authority, commander in specs:
        formation = _read(rel)
        assert formation['owner_force_ref'] == owner
        assert formation['administrative_owner'] == admin
        assert formation['command_authority'] == authority
        assert formation['commander_ref'] == commander
        assert formation['personnel'] == 500
        assert formation['composition'] == {'cavalry': 500}
    assert _read('state/formations/qin-gaku-ka-core.json')['commander_ref'] == 'char_ai_sen'
    assert _read('state/formations/qin-gyoku-hou-core.json')['commander_ref'] == 'char_a_ka_kin'
    mou_mounts = _read('state/mounts/house-mou-family.json')['allocated_to_formations']
    ou_mounts = _read('state/mounts/house-ou-family.json')['allocated_to_formations']
    assert mou_mounts['formation_gaku_ka_house_a'] == {'horse': 500}
    assert mou_mounts['formation_gaku_ka_house_b'] == {'horse': 500}
    assert ou_mounts['formation_gyoku_hou_house_a'] == {'horse': 500}
    assert ou_mounts['formation_gyoku_hou_house_b'] == {'horse': 500}

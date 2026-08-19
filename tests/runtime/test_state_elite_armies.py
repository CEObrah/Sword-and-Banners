import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def j(rel): return json.loads((ROOT/rel).read_text())

EXPECTED={
 'formation_qin_ouki_vanguard':'cmdgrp.ouki.field_army',
 'formation_qin_ousen_central':'cmdgrp.ousen.field_army',
 'formation_qin_kanki_raider_host':'cmdgrp.kanki.field_army',
 'formation_qin_tou_mobile_army':'cmdgrp.tou.field_army',
 'formation_qin_mou_gou_central':'cmdgrp.mou_gou.field_army',
 'formation_qin_mou_bu_shock_army':'cmdgrp.mou_bu.field_army',
 'formation_zhao_riboku_northern_army':'cmdgrp.riboku.field_army',
 'formation_zhao_seika_field_army':'cmdgrp.shibashou.field_army',
 'formation_zhao_retsubi_gate_command':'cmdgrp.retsubi.garrison',
 'formation_chu_karin_state_army':'cmdgrp.karin.field_army',
 'formation_chu_juuko_defense_army':'cmdgrp.juuko.defense',
 'formation_wei_go_hou_mei_state_army':'cmdgrp.go_hou_mei.field_army',
 'formation_han_nanyou_western_command':'cmdgrp.nanyou.western',
 'formation_yan_ordo_mountain_army':'cmdgrp.ordo.field_army',
 'formation_qi_rinshi_royal_guard':'cmdgrp.rinshi.royal_guard',
}

def formation_by_ref(ref):
    owner=j('state/index/owner-index.json')['owners'][ref]
    return j(owner)

def test_elite_state_formations_are_mixed_conserved_assignments_under_zero_body_commands():
    idx=j('state/cmd/command-groups/index.json')
    for ref,group in EXPECTED.items():
        f=formation_by_ref(ref)
        assert f['owner_force_ref'].startswith('force_state_')
        assert f['higher_command_ref']==group
        assert idx['primary_formation_group'][ref]==group
        assert sum(f['composition'].values())==f['personnel']
        assert len([n for n in f['composition'].values() if n>0])>=2
        assert f['commander_ref'] is None
        assert f['command_structure']['unit_command']['external_to_fighting_establishment'] is True
        assert f['formation_identity']['state_force_ownership_preserved'] is True
        assert sum(f.get('mounts',{}).values())==f['composition'].get('cavalry',0)


def test_named_generals_command_armies_not_their_direct_maneuver_formation_body_count():
    leaders={
      'cmdgrp.ouki.field_army':'char_ouki',
      'cmdgrp.ousen.field_army':'char_ousen',
      'cmdgrp.kanki.field_army':'char_kanki',
      'cmdgrp.tou.field_army':'char_tou',
      'cmdgrp.mou_gou.field_army':'char_mou_gou',
      'cmdgrp.mou_bu.field_army':'char_mou_bu',
      'cmdgrp.riboku.field_army':'char_riboku',
      'cmdgrp.shibashou.field_army':'char_shibashou',
      'cmdgrp.karin.field_army':'char_karin',
      'cmdgrp.go_hou_mei.field_army':'char_go_hou_mei',
      'cmdgrp.ordo.field_army':'char_ordo',
    }
    for group_ref,person_ref in leaders.items():
        g=j(f'state/cmd/command-groups/{group_ref}.json')
        assert g['commander_ref']==person_ref
        assert any(row['kind'] == 'formation' for row in g['units'])
        assert g['id']==group_ref


def test_seika_retsubi_nanyou_juuko_are_real_geographic_dispositions_not_spawned_force_owners():
    cases={
      'formation_zhao_seika_field_army':'loc_seika',
      'formation_zhao_retsubi_gate_command':'loc_retsubi',
      'formation_han_nanyou_western_command':'loc_nanyou',
      'formation_chu_juuko_defense_army':'loc_juuko',
    }
    for ref,loc in cases.items():
        f=formation_by_ref(ref)
        assert f['location_ref']==loc
        assert f['owner_force_ref'] in {'force_state_zhao','force_state_han','force_state_chu'}

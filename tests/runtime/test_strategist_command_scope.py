import json
from pathlib import Path

import pytest

from sword_runtime.production_planner import ProductionCampaignPlanner


def _set_role(campaign: Path, group_ref: str, person_ref: str, role: str) -> None:
    path = campaign / f"state/cmd/command-groups/{group_ref}.json"
    group = json.loads(path.read_text(encoding="utf-8"))
    group.setdefault("role_assignments", {})[person_ref] = role
    direct = group.setdefault("direct_person_refs", [])
    if person_ref not in direct:
        direct.append(person_ref)
        direct.sort()
    path.write_text(json.dumps(group, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_parent_strategist_operational_scope_reaches_recursive_descendants(campaign: Path) -> None:
    root = "cmdgrp.tang_wei.field_army"
    deep_child = "cmdgrp.tang_wei.black_banner.unit_1"
    sibling_branch = "cmdgrp.tang_wei.high_guard"
    strategist = "char_house_tang_house_infantry_operations_officer"
    _set_role(campaign, root, strategist, "Strategist")
    planner = ProductionCampaignPlanner(campaign)

    planner._require_command_group_authority(strategist, root, allow_strategist=True)
    planner._require_command_group_authority(strategist, deep_child, allow_strategist=True)
    planner._require_command_group_authority(strategist, sibling_branch, allow_strategist=True)
    assert planner._has_formation_operational_authority(strategist, "formation_black_banner_01a")
    assert planner._has_formation_operational_authority(strategist, "formation_high_guard_cavalry")

    with pytest.raises(PermissionError):
        planner._require_command_group_authority(strategist, root, allow_strategist=False)


def test_nested_strategist_is_confined_to_own_subtree(campaign: Path) -> None:
    nested = "cmdgrp.tang_wei.black_banner"
    own_child = "cmdgrp.tang_wei.black_banner.unit_1"
    sibling = "cmdgrp.tang_wei.high_guard"
    parent = "cmdgrp.tang_wei.field_army"
    strategist = "char_house_tang_house_infantry_operations_officer"
    _set_role(campaign, nested, strategist, "Strategist")
    planner = ProductionCampaignPlanner(campaign)

    planner._require_command_group_authority(strategist, nested, allow_strategist=True)
    planner._require_command_group_authority(strategist, own_child, allow_strategist=True)
    assert planner._has_formation_operational_authority(strategist, "formation_black_banner_01a")

    with pytest.raises(PermissionError):
        planner._require_command_group_authority(strategist, parent, allow_strategist=True)
    with pytest.raises(PermissionError):
        planner._require_command_group_authority(strategist, sibling, allow_strategist=True)
    assert not planner._has_formation_operational_authority(strategist, "formation_high_guard_cavalry")


def test_strategist_role_does_not_grant_organizational_authority(campaign: Path) -> None:
    nested = "cmdgrp.tang_wei.black_banner"
    strategist = "char_house_tang_house_infantry_operations_officer"
    _set_role(campaign, nested, strategist, "Strategist")
    planner = ProductionCampaignPlanner(campaign)

    planner._require_command_group_authority(strategist, nested, allow_strategist=True)
    with pytest.raises(PermissionError):
        planner._require_command_group_authority(strategist, nested, allow_strategist=False)


def test_missing_primary_group_index_cannot_suppress_exact_higher_command_authority(campaign: Path) -> None:
    nested = "cmdgrp.tang_wei.black_banner"
    formation_ref = "formation_black_banner_01a"
    strategist = "char_house_tang_house_infantry_operations_officer"
    _set_role(campaign, nested, strategist, "Strategist")

    index_path = campaign / "state/cmd/command-groups/index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index.setdefault("primary_formation_group", {}).pop(formation_ref, None)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    planner = ProductionCampaignPlanner(campaign)
    assert planner._has_formation_operational_authority(strategist, formation_ref)


def test_stale_primary_group_index_cannot_grant_wrong_strategist_authority(campaign: Path) -> None:
    wrong_group = "cmdgrp.tang_wei.high_guard"
    formation_ref = "formation_black_banner_01a"
    strategist = "char_house_tang_house_infantry_operations_officer"
    _set_role(campaign, wrong_group, strategist, "Strategist")

    # Remove the exact formation-side route so the test proves the routing index
    # itself cannot manufacture membership in an unrelated command subtree.
    owners = json.loads((campaign / "state/index/owner-index.json").read_text(encoding="utf-8"))["owners"]
    formation_path = campaign / owners[formation_ref]
    formation = json.loads(formation_path.read_text(encoding="utf-8"))
    formation["higher_command_ref"] = None
    formation_path.write_text(json.dumps(formation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    index_path = campaign / "state/cmd/command-groups/index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index.setdefault("primary_formation_group", {})[formation_ref] = wrong_group
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    planner = ProductionCampaignPlanner(campaign)
    assert not planner._has_formation_operational_authority(strategist, formation_ref)

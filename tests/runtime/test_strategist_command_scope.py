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

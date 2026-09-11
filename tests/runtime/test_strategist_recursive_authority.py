from __future__ import annotations

from sword_runtime.command_authority import person_order_authority, staff_routing_from_groups


def _reader(groups: dict[str, dict], policy: dict | None = None):
    policy = policy or {
        "roles": {
            "strategist": {
                "recursive_order_authority": True,
                "chain_of_command_default": True,
            }
        }
    }

    def read(path: str):
        if path == "game/data/mechanics/command-staff.json":
            return policy
        prefix = "state/cmd/command-groups/"
        if path.startswith(prefix) and path.endswith(".json"):
            ref = path[len(prefix):-5]
            return groups[ref]
        raise KeyError(path)

    return read


def _group(ref: str, commander: str, parent: str | None = None, roles: dict[str, str] | None = None) -> dict:
    return {
        "schema": "command-group",
        "id": ref,
        "commander_ref": commander,
        "authority_ref": commander,
        "parent_command_group_ref": parent,
        "direct_person_refs": sorted((roles or {}).keys()),
        "role_assignments": dict(roles or {}),
        "units": [],
    }


def test_supreme_strategist_has_recursive_scope_but_not_outside_army() -> None:
    groups = {
        "cmdgrp.root": _group("cmdgrp.root", "general.root", roles={"staff.root": "strategist"}),
        "cmdgrp.left": _group("cmdgrp.left", "general.left", "cmdgrp.root"),
        "cmdgrp.left.inner": _group("cmdgrp.left.inner", "general.inner", "cmdgrp.left"),
        "cmdgrp.other": _group("cmdgrp.other", "general.other"),
    }
    read = _reader(groups)

    for target in ("cmdgrp.root", "cmdgrp.left", "cmdgrp.left.inner"):
        authority = person_order_authority(read, person_ref="staff.root", target_group_ref=target)
        assert authority["allowed"] is True
        assert authority["role"] == "strategist"
        assert authority["scope_root_ref"] == "cmdgrp.root"

    assert person_order_authority(read, person_ref="staff.root", target_group_ref="cmdgrp.other")["allowed"] is False


def test_nested_army_strategist_cannot_reach_parent_or_sibling() -> None:
    groups = {
        "cmdgrp.root": _group("cmdgrp.root", "general.root"),
        "cmdgrp.left": _group("cmdgrp.left", "general.left", "cmdgrp.root", {"staff.left": "strategist"}),
        "cmdgrp.left.inner": _group("cmdgrp.left.inner", "general.inner", "cmdgrp.left"),
        "cmdgrp.right": _group("cmdgrp.right", "general.right", "cmdgrp.root"),
    }
    read = _reader(groups)

    assert person_order_authority(read, person_ref="staff.left", target_group_ref="cmdgrp.left")["allowed"] is True
    assert person_order_authority(read, person_ref="staff.left", target_group_ref="cmdgrp.left.inner")["allowed"] is True
    assert person_order_authority(read, person_ref="staff.left", target_group_ref="cmdgrp.root")["allowed"] is False
    assert person_order_authority(read, person_ref="staff.left", target_group_ref="cmdgrp.right")["allowed"] is False


def test_non_strategist_staff_does_not_gain_recursive_order_authority() -> None:
    groups = {
        "cmdgrp.root": _group("cmdgrp.root", "general.root", roles={"staff.ops": "operations_officer"}),
        "cmdgrp.child": _group("cmdgrp.child", "general.child", "cmdgrp.root"),
    }
    read = _reader(groups)
    assert person_order_authority(read, person_ref="staff.ops", target_group_ref="cmdgrp.child")["allowed"] is False


def test_staff_routing_is_additive_and_does_not_define_primary_command() -> None:
    groups = {
        "cmdgrp.root": _group("cmdgrp.root", "general.root", roles={"dual.role": "strategist"}),
        "cmdgrp.child": _group("cmdgrp.child", "dual.role", "cmdgrp.root"),
    }
    read = _reader(groups)
    routing = staff_routing_from_groups(read, list(groups))
    assert routing == {"dual.role": ["cmdgrp.root"]}
    assert groups["cmdgrp.child"]["commander_ref"] == "dual.role"

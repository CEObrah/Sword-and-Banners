from __future__ import annotations

import json
from pathlib import Path

from conftest import activate_operation, execute, execute_internal
from test_operational_battlefield import _co_locate_formations_direct, _operation
from sword_runtime.command_units import recursive_refs


def _group(root: Path, ref: str) -> dict:
    return json.loads((root / f"state/cmd/command-groups/{ref}.json").read_text())


def test_dynamic_battlefield_groups_tang_wei_9500_as_three_peer_commands(campaign):
    leaves, _groups = recursive_refs(lambda ref: _group(campaign, ref), "cmdgrp.tang_wei.field_army")
    tang_leaves = sorted(leaves)
    assert len(tang_leaves) == 19
    enemy = "formation_wei_reconstitution"
    location = "loc_wei_regional_02"
    _co_locate_formations_direct(campaign, [*tang_leaves, enemy], location)

    operation_ref = activate_operation(
        campaign,
        "operation_dynamic_peer_echelon_test",
        [*tang_leaves, enemy],
        location=location,
    )
    battlefield_ref = "battlefield_dynamic_peer_echelon_test"
    execute(campaign, "battlefield_control", {
        "action": "open",
        "operation_ref": operation_ref,
        "battlefield_ref": battlefield_ref,
        "name": "Wei Western Corridor Contact",
        # layout_ref intentionally omitted: dynamic is the production default.
    })

    battlefield = _operation(campaign, operation_ref)["battlefields"][battlefield_ref]
    geometry = battlefield["field_geometry"]
    assert geometry["generator"] == "terrain_force_v1"
    assert geometry["scale_band"] == "extended"
    assert geometry["terrain_archetype"] == "open_field"
    assert geometry["front_sector_count"] == 5
    assert geometry["estimated_span_m"] > 0
    assert geometry["estimated_depth_m"] > 0
    objectives = battlefield["objective_markers"]
    assert len(objectives) == geometry["front_sector_count"]
    center_sector = next(row for row in battlefield["sectors"].values() if row.get("role") == "front_center")
    assert center_sector["operational_objective"]["kind"] == "central_frontage"
    assert center_sector["operational_objective"]["importance"] == "key"

    qin = battlefield["operational_commands"]["state_qin"]
    assert len(qin) == 3
    by_name = {row["display_name"]: row for row in qin.values()}
    assert {name: by_name[name]["strength"] for name in ("High Guard", "Black Banner", "Red Lance")} == {
        "High Guard": 4500,
        "Black Banner": 4000,
        "Red Lance": 1000,
    }
    assert {name: by_name[name]["tactical_leaf_count"] for name in by_name} == {
        "High Guard": 9,
        "Black Banner": 8,
        "Red Lance": 2,
    }

    # The nineteen conserved leaf owners still exist, but opening deployment
    # keeps each primary command physically coherent instead of round-robin
    # scattering every 500-man leaf across the operational map.
    assignments = battlefield["assignments"]
    command_sectors: dict[str, set[str]] = {}
    for formation_ref in tang_leaves:
        row = assignments[formation_ref]
        command_sectors.setdefault(row["operational_command_ref"], set()).add(row["sector_ref"])
    assert len(command_sectors) == 3
    assert all(len(sectors) == 1 for sectors in command_sectors.values())
    assert len({next(iter(sectors)) for sectors in command_sectors.values()}) == 3

    wei = battlefield["operational_commands"]["state_wei"]
    assert len(wei) == 1
    only_wei = next(iter(wei.values()))
    assert only_wei["strength"] == 40000
    assert only_wei["tactical_leaf_count"] == 1

    # Wei is stored as one coarse 40,000-man exact formation, but an extended
    # five-sector battlefield must not pretend all 40,000 bodies stand in one
    # narrow sector. The same owner projects conserved frontage across the five
    # front sectors and its commitment shares still total exactly one formation.
    wei_assignment = assignments[enemy]
    wei_commitments = wei_assignment["sector_commitments_milli"]
    assert len(wei_commitments) == geometry["front_sector_count"]
    assert sum(wei_commitments.values()) == 1000
    assert set(wei_commitments) == {
        ref for ref, row in battlefield["sectors"].items() if row.get("frontage_slot")
    }
    assert all(enemy in battlefield["sectors"][sector_ref]["formation_refs"] for sector_ref in wei_commitments)
    assert sum(round(40000 * share / 1000) for share in wei_commitments.values()) == 40000
    for formation_ref in tang_leaves:
        local = assignments[formation_ref]["sector_commitments_milli"]
        assert sum(local.values()) == 1000
        assert len(local) == 1


def test_fractional_aggregate_frontage_scales_exact_local_contact(campaign):
    leaves, _groups = recursive_refs(lambda ref: _group(campaign, ref), "cmdgrp.tang_wei.field_army")
    tang_leaves = sorted(leaves)
    enemy = "formation_wei_reconstitution"
    location = "loc_wei_regional_02"
    _co_locate_formations_direct(campaign, [*tang_leaves, enemy], location)
    operation_ref = activate_operation(
        campaign, "operation_fractional_frontage_contact_test", [*tang_leaves, enemy], location=location,
    )
    battlefield_ref = "battlefield_fractional_frontage_contact_test"
    execute(campaign, "battlefield_control", {
        "action": "open", "operation_ref": operation_ref,
        "battlefield_ref": battlefield_ref, "name": "Fractional Frontage Contact Test",
    })
    battlefield = _operation(campaign, operation_ref)["battlefields"][battlefield_ref]
    assignments = battlefield["assignments"]
    # Pick one exact 500-man Tang leaf in a sector covered by the coarse Wei body.
    attacker = tang_leaves[0]
    sector_ref = assignments[attacker]["sector_ref"]
    share = assignments[enemy]["sector_commitments_milli"][sector_ref]
    assert share == 200

    result = execute_internal(campaign, "battle_resolve", {
        "attacker_formation_refs": [attacker],
        "defender_formation_refs": [enemy],
        "operation_ref": operation_ref,
        "battlefield_ref": battlefield_ref,
        "sector_ref": sector_ref,
        "objective": "prove conserved local frontage contact",
    }).receipt.result

    assert result["operational_contact"] is True
    assert result["represented_personnel"] == 500 + 8000
    assert result["casualties"][enemy] <= 8000
    # The exact Wei owner remains one formation; a local contact can debit its
    # bodies but never treats the other four sector shares as extra soldiers.
    owner_index = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    wei_after = json.loads((campaign / owner_index[enemy]).read_text())
    assert 32000 <= int(wei_after["personnel"]) <= 40000


def test_dynamic_kankoku_scale_creates_grand_fortified_pass_front(campaign):
    qin = [
        "formation_qin_mou_bu_shock_army",
        "formation_qin_ousen_central",
        "formation_qin_kanki_raider_host",
    ]
    zhao = [
        "formation_zhao_riboku_northern_army",
        "formation_zhao_seika_field_army",
        "formation_zhao_border_line",
    ]
    location = "loc_kankoku_pass"
    _co_locate_formations_direct(campaign, [*qin, *zhao], location)
    operation_ref = activate_operation(campaign, "operation_dynamic_kankoku_scale_test", [*qin, *zhao], location=location)
    battlefield_ref = "battlefield_dynamic_kankoku_scale_test"
    execute_internal(campaign, "battlefield_control", {
        "action": "open",
        "operation_ref": operation_ref,
        "battlefield_ref": battlefield_ref,
        "name": "Kankoku Pass Grand Front",
        "layout_ref": "battlefield.layout.dynamic",
    })

    battlefield = _operation(campaign, operation_ref)["battlefields"][battlefield_ref]
    geometry = battlefield["field_geometry"]
    assert geometry["scale_band"] == "grand"
    assert geometry["terrain_archetype"] == "fortified_pass"
    assert geometry["front_sector_count"] == 7
    assert geometry["reserve_sector_count"] == 2
    names = [row["name"] for row in battlefield["sectors"].values()]
    assert "Main Pass" in names
    assert "Western Mountain Front" in names
    assert "Eastern Mountain Front" in names
    assert any(row.get("role") == "command" for row in battlefield["sectors"].values())
    main_pass = next(row for row in battlefield["sectors"].values() if row.get("name") == "Main Pass")
    assert main_pass["operational_objective"]["kind"] == "fortified_choke_point"
    assert main_pass["operational_objective"]["importance"] == "decisive"
    marker = battlefield["objective_markers"][main_pass["operational_objective"]["objective_ref"]]
    assert marker["sector_ref"] == main_pass["sector_ref"]
    assert "main pass" in marker["mission"].lower()

    # The battlefield is a connected physical route graph, so a force can move
    # from either outer front to the command rear only by elapsed redeployment.
    from sword_runtime.engine import RepositoryCommandPlanner
    planner = RepositoryCommandPlanner(campaign)
    front_refs = [ref for ref, row in battlefield["sectors"].items() if row.get("role", "").startswith("front")]
    command_ref = next(ref for ref, row in battlefield["sectors"].items() if row.get("role") == "command")
    for outer in (front_refs[0], front_refs[-1]):
        path, distance = planner._battlefield_shortest_path(battlefield, outer, command_ref)
        assert path[0] == outer and path[-1] == command_ref
        assert distance > 0


def test_peer_operational_command_can_receive_one_order_without_leaf_micromanagement(campaign):
    leaves, _groups = recursive_refs(lambda ref: _group(campaign, ref), "cmdgrp.tang_wei.field_army")
    tang_leaves = sorted(leaves)
    enemy = "formation_wei_reconstitution"
    location = "loc_wei_regional_02"
    _co_locate_formations_direct(campaign, [*tang_leaves, enemy], location)
    operation_ref = activate_operation(
        campaign, "operation_dynamic_command_order_test", [*tang_leaves, enemy], location=location,
    )
    battlefield_ref = "battlefield_dynamic_command_order_test"
    execute(campaign, "battlefield_control", {
        "action": "open", "operation_ref": operation_ref,
        "battlefield_ref": battlefield_ref, "name": "Peer Command Order Test",
    })
    battlefield = _operation(campaign, operation_ref)["battlefields"][battlefield_ref]
    qin = battlefield["operational_commands"]["state_qin"]
    by_name = {row["display_name"]: row for row in qin.values()}

    high_guard = by_name["High Guard"]
    execute(campaign, "battlefield_control", {
        "action": "set_order", "operation_ref": operation_ref,
        "battlefield_ref": battlefield_ref,
        "operational_command_ref": high_guard["command_ref"], "order": "attack",
    })
    battlefield = _operation(campaign, operation_ref)["battlefields"][battlefield_ref]
    for formation_ref in high_guard["formation_refs"]:
        assignment = battlefield["assignments"][formation_ref]
        assert assignment.get("order") == "attack" or assignment.get("pending_order") == "attack"

    black_banner = by_name["Black Banner"]
    source_ref = battlefield["assignments"][black_banner["formation_refs"][0]]["sector_ref"]
    fronts = [ref for ref, row in battlefield["sectors"].items() if str(row.get("role", "")).startswith("front")]
    target_ref = next(ref for ref in fronts if ref != source_ref)
    execute(campaign, "battlefield_control", {
        "action": "redeploy", "operation_ref": operation_ref,
        "battlefield_ref": battlefield_ref,
        "operational_command_ref": black_banner["command_ref"],
        "target_sector_ref": target_ref, "pace": "standard", "order": "attack",
    })
    battlefield = _operation(campaign, operation_ref)["battlefields"][battlefield_ref]
    for formation_ref in black_banner["formation_refs"]:
        assignment = battlefield["assignments"][formation_ref]
        assert assignment["status"] == "redeploying"
        assert assignment["target_sector_ref"] == target_ref
        assert assignment["operational_command_ref"] == black_banner["command_ref"]


def test_battlefield_does_not_flatten_a_broken_saved_command_hierarchy(campaign):
    """A corrupt exact higher-command route is not an independent 500-man peer."""
    import pytest
    from sword_runtime.engine import RepositoryCommandPlanner

    leaves, _groups = recursive_refs(lambda ref: _group(campaign, ref), "cmdgrp.tang_wei.field_army")
    formation_ref = sorted(leaves)[0]
    owners = json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]
    path = campaign / owners[formation_ref]
    formation = json.loads(path.read_text())
    formation["higher_command_ref"] = "cmdgrp.missing.corrupt_parent"
    path.write_text(json.dumps(formation, ensure_ascii=False, indent=2) + "\n")
    # Remove the non-authoritative accelerator too so only the broken exact
    # saved route remains; this models index loss/corruption during recovery.
    index_path = campaign / "state/cmd/command-groups/index.json"
    index = json.loads(index_path.read_text())
    index.get("primary_formation_group", {}).pop(formation_ref, None)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n")

    planner = RepositoryCommandPlanner(campaign)
    with pytest.raises(ValueError, match="command hierarchy is invalid"):
        planner._battlefield_operational_command_ref(formation_ref, formation)

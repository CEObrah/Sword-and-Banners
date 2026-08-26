from __future__ import annotations

import json
import subprocess

from sword_runtime.commands import CommandEnvelope
from sword_runtime.service_runtime import ProductionSwordRuntime


def _write_json(path, document) -> None:
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _routed_person(campaign, person_ref: str):
    owners = json.loads((campaign / "state/index/owner-index.json").read_text(encoding="utf-8"))["owners"]
    route = str(owners[person_ref])
    rel_path, _, fragment = route.partition("#")
    document = json.loads((campaign / rel_path).read_text(encoding="utf-8"))
    if fragment:
        assert fragment == f"/records/{person_ref}"
        return rel_path, document, document["records"][person_ref]
    return rel_path, document, document


def _set_person_location(person: dict, location: str) -> None:
    if "location" in person:
        person["location"] = location
    else:
        person["current_location"] = location


def _person_location(person: dict) -> str:
    return str(person.get("location") or person.get("current_location") or "")


def test_whole_command_group_travel_moves_colocated_headquarters_people_only(campaign):
    origin = "loc_qin_eastern_depot"
    destination = "loc_kanyou"
    formation_refs = ["formation_red_lance_a", "formation_red_lance_b"]
    group_ref = "cmdgrp.tang_wei.red_lance"
    group_path = campaign / "state/cmd/command-groups" / f"{group_ref}.json"
    player_path = campaign / "state/player.json"

    group = json.loads(group_path.read_text(encoding="utf-8"))
    commander_ref = str(group["commander_ref"])
    detached_ref = "char_lin_zhen"
    group["location"] = origin
    group["successor_refs"] = [detached_ref]
    _write_json(group_path, group)

    player = json.loads(player_path.read_text(encoding="utf-8"))
    player["location"] = origin
    _write_json(player_path, player)

    touched = ["state/player.json", f"state/cmd/command-groups/{group_ref}.json"]
    for filename in ("state/formations/red-lance-a.json", "state/formations/red-lance-b.json"):
        path = campaign / filename
        formation = json.loads(path.read_text(encoding="utf-8"))
        formation["location_ref"] = origin
        _write_json(path, formation)
        touched.append(filename)

    commander_path, commander_doc, commander = _routed_person(campaign, commander_ref)
    _set_person_location(commander, origin)
    _write_json(campaign / commander_path, commander_doc)
    touched.append(commander_path)

    detached_path, detached_doc, detached = _routed_person(campaign, detached_ref)
    detached_location = "loc_tang_manor_garrison_yard"
    _set_person_location(detached, detached_location)
    _write_json(campaign / detached_path, detached_doc)
    touched.append(detached_path)

    subprocess.run(["git", "-C", str(campaign), "add", *sorted(set(touched))], check=True)
    subprocess.run(
        ["git", "-C", str(campaign), "commit", "--quiet", "-m", "Arrange command-group staff travel fixture"],
        check=True,
    )

    runtime = ProductionSwordRuntime(campaign, runtime_root=campaign.parent / "runtime-command-group-staff-travel")
    meta = runtime.store.read_json("state/meta.json")
    command = CommandEnvelope(
        campaign_id=meta["campaign_id"],
        request_id="test-command-group-staff-whole-tree-travel",
        actor_id=meta["player_id"],
        command_type="travel",
        expected_revision=meta["revision"],
        submitted_at=meta["time"],
        payload={"destination_ref": destination, "formation_refs": formation_refs, "mode": "foot"},
        mode="gameplay",
    )
    result = runtime.execute(command).receipt.result

    assert group_ref in result.get("command_groups_reconciled", [])
    assert commander_ref in result.get("command_group_staff_reconciled", [])
    assert detached_ref not in result.get("command_group_staff_reconciled", [])
    assert runtime.store.read_json(f"state/cmd/command-groups/{group_ref}.json")["location"] == destination
    assert runtime.store.read_json("state/cmd/command-groups/cmdgrp.tang_wei.field_army.json")["location"] != destination

    _, _, moved_commander = _routed_person(campaign, commander_ref)
    _, _, still_detached = _routed_person(campaign, detached_ref)
    assert _person_location(moved_commander) == destination
    assert _person_location(still_detached) == detached_location


def test_red_lance_remains_a_proper_organization_name(campaign):
    group = json.loads(
        (campaign / "state/cmd/command-groups/cmdgrp.tang_wei.red_lance.json").read_text(encoding="utf-8")
    )
    assert group["display_name"] == "Red Lance"
    assert group["id"] == "cmdgrp.tang_wei.red_lance"
    assert [row["ref"] for row in group["units"]] == ["formation_red_lance_a", "formation_red_lance_b"]

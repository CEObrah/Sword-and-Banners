from __future__ import annotations

import json
import subprocess

import pytest

from conftest import execute_production


PLAYER_PATH = "state/player.json"
MANIFEST_PATH = "state/player-detail/equipment-manifest.json"
FAMILY_HALL = "loc_tang_manor_inner_citadel_family_hall"


def _write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _place_wei_with_mount(campaign, mount_location: str) -> None:
    player_path = campaign / PLAYER_PATH
    player = json.loads(player_path.read_text())
    player["location"] = FAMILY_HALL
    compact = dict(player.get("current_equipment_state", {}))
    compact["mount_location"] = mount_location
    compact["mounted"] = False
    player["current_equipment_state"] = compact
    _write_json(player_path, player)

    manifest_path = campaign / MANIFEST_PATH
    manifest = json.loads(manifest_path.read_text())
    prepared = {
        "horse": f"equipped: assigned/prepared at {mount_location}",
        "tack_standard": f"equipped: fitted/prepared on assigned mount at {mount_location}",
        "horse_armor_heavy": f"equipped: fitted/prepared on assigned mount at {mount_location}",
    }
    for row in manifest.get("equipment_manifest", []):
        item_key = str(row.get("item_id", ""))
        if item_key in prepared and int(row.get("quantity", 0)) > 0:
            row["current_state"] = prepared[item_key]
    _write_json(manifest_path, manifest)

    subprocess.run(
        ["git", "-C", str(campaign), "add", PLAYER_PATH, MANIFEST_PATH],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(campaign), "commit", "--quiet", "-m", "test mount containment baseline"],
        check=True,
    )


def test_horse_travel_from_family_hall_resolves_to_local_mounting_point(campaign):
    _place_wei_with_mount(campaign, "loc_tang_manor")

    execute_production(
        campaign,
        "travel",
        {"destination_ref": "loc_kanyou", "mode": "horse"},
    )

    player = json.loads((campaign / PLAYER_PATH).read_text())
    assert player["location"] == "loc_kanyou"
    assert player["current_equipment_state"]["mounted"] is True
    assert player["current_equipment_state"]["mount_location"] == "loc_kanyou"


def test_remote_mount_is_still_inaccessible_from_family_hall(campaign):
    _place_wei_with_mount(campaign, "loc_kanyou")

    with pytest.raises(ValueError, match="mount is not physically accessible"):
        execute_production(
            campaign,
            "travel",
            {"destination_ref": "loc_qin_eastern_depot", "mode": "horse"},
        )

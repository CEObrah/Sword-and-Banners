from __future__ import annotations

import json
import subprocess


def _commit(campaign, *paths: str) -> None:
    subprocess.run(["git", "-C", str(campaign), "add", *paths], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", "test: personal projectile recovery"], check=True)


def test_recover_projectiles_consumes_field_candidates_and_restores_exact_ammunition(campaign):
    from conftest import execute

    player_path = campaign / "state/player.json"
    manifest_path = campaign / "state/player-detail/equipment-manifest.json"
    player = json.loads(player_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    location = player["location"]
    arrow = next(row for row in manifest["equipment_manifest"] if row.get("item_id") == "ammo_arrow")
    before = int(arrow["quantity"])
    player.setdefault("combat_state", {})["field_projectiles"] = [{
        "projectile_item_id": "ammo_arrow",
        "quantity": 3,
        "location_ref": location,
        "source_combat_ref": "personal_combat_test",
        "deposited_at": "250-BCE-01-01T00:00:00Z",
        "status": "recoverable_in_field",
    }]
    # Saved carried-ammunition state is the exact combat owner and must move in
    # lockstep with the manifest quantity.
    player["combat_state"].setdefault("projectile_ammunition", {})["ammo_arrow"] = before
    player_path.write_text(json.dumps(player, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, "state/player.json")

    result = execute(campaign, "recover_projectiles", {"minutes": 1}).receipt.result
    assert result["recovered_by_item"] == {"ammo_arrow": 3}
    assert result["recovered_total"] == 3

    player_after = json.loads(player_path.read_text())
    manifest_after = json.loads(manifest_path.read_text())
    arrow_after = next(row for row in manifest_after["equipment_manifest"] if row.get("item_id") == "ammo_arrow")
    assert int(arrow_after["quantity"]) == before + 3
    assert int(player_after["combat_state"]["projectile_ammunition"]["ammo_arrow"]) == before + 3
    assert not player_after["combat_state"].get("field_projectiles")

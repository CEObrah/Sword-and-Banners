from __future__ import annotations

import json
import subprocess


def _commit(campaign, *paths: str) -> None:
    subprocess.run(["git", "-C", str(campaign), "add", *paths], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "--quiet", "-m", "test: exact mount casualty"], check=True)


def test_personal_combat_mount_loss_persists_and_static_loadout_cannot_resurrect_it(campaign):
    from conftest import execute
    from sword_runtime.production_planner import ProductionCampaignPlanner

    player = json.loads((campaign / "state/player.json").read_text())
    zhu_path = campaign / "state/char/tang-zhu.json"
    zhu = json.loads(zhu_path.read_text())
    zhu["current_location"] = player["location"]
    zhu["life_status"] = "active"
    zhu["health_status"] = "healthy"
    zhu.setdefault("combat_state", {}).pop("incapacitated", None)
    # Make the regression about mount casualty persistence, not whether a senior
    # commander happened to win the defensive exchange in this fixture.
    for key in ("Agility", "Awareness", "Composure", "Coordination", "Endurance", "Strength", "Toughness"):
        zhu.setdefault("attributes", {})[key] = 1
    for key in list(zhu.setdefault("skills", {})):
        zhu["skills"][key] = 1
    zhu_path.write_text(json.dumps(zhu, ensure_ascii=False, indent=2) + "\n")

    player_path = campaign / "state/player.json"
    player.setdefault("attributes", {}).update({"Strength": 800, "Agility": 400, "Coordination": 500, "Awareness": 500, "Composure": 500})
    player.setdefault("skills", {}).update({"Polearms": 600, "Athletics": 400, "Riding": 300})
    player_path.write_text(json.dumps(player, ensure_ascii=False, indent=2) + "\n")
    _commit(campaign, "state/player.json", "state/char/tang-zhu.json")

    result = execute(campaign, "personal_combat", {
        "opponent_ref": "char_tang_zhu",
        "target_ref": "char_tang_zhu",
        "objective": "lethal combat; disable or kill his horse",
        "duration_minutes": 1,
        "intent_sequence": ["thrust the spear into the horse chest"],
        "participant_positions": {
            "char_tang_wei": {"x_m": 0, "y_m": 0, "facing_deg": 0},
            "char_tang_zhu": {"x_m": "1.7", "y_m": 0, "facing_deg": 180},
        },
    }).receipt.result

    assert result["mount_wounds"], result["causal_trace"]
    persisted = json.loads(zhu_path.read_text())
    mount_state = persisted["mount_combat_state"]
    assert mount_state["status"] in {"dead", "disabled"}
    assert mount_state["serviceable"] is False
    assert mount_state["service_loss_recorded"] is True
    assert mount_state["service_loss_pending"] is False

    profile = ProductionCampaignPlanner(campaign)._personal_equipment_profile("char_tang_zhu", persisted)
    assert profile["mount"] == {}
    assert profile["horse_armor"] == {}
    assert profile["tack"] == {}
    assert profile["loadout"].get("mount") is None

    mounted_events = [row for row in result["causal_trace"] if row.get("kind") == "mounted_state" and row.get("actor_ref") == "char_tang_zhu"]
    fall_events = [row for row in result["causal_trace"] if row.get("kind") == "posture_state" and row.get("actor_ref") == "char_tang_zhu" and row.get("action") == "fall_started"]
    assert mounted_events
    assert fall_events

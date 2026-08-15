from __future__ import annotations

import copy

from sword_runtime.causal_living_world import CausalLivingWorldSwordPlanner
from sword_runtime.commands import CommandEnvelope
from sword_runtime.production_planner import ProductionCampaignPlanner
from sword_runtime.service_runtime import ProductionSwordRuntime
from sword_runtime.sim.calendar import CampaignTime


def test_personal_travel_preview_is_execute_only() -> None:
    assert ProductionSwordRuntime._is_contested(
        "travel",
        {"destination_ref": "loc_kanyou", "mode": "foot"},
    ) is True


def test_personal_travel_commits_reached_wake_without_false_arrival(campaign, monkeypatch) -> None:
    planner = ProductionCampaignPlanner(campaign)
    meta = copy.deepcopy(planner.read("state/meta.json"))
    planner.PLAYER_ACTOR = str(meta["player_id"])
    planner._reset()

    origin = "loc_tang_manor_inner_citadel_family_hall"
    player = copy.deepcopy(planner.read("state/player.json"))
    player["location"] = origin
    compact = dict(player.get("current_equipment_state", {}))
    compact["mounted"] = False
    compact["mount_location"] = "House Tang cavalry stables"
    player["current_equipment_state"] = compact
    planner.put("state/player.json", player)

    runtime = copy.deepcopy(planner.read("state/runtime.json"))
    runtime.pop("pending_wake", None)
    meta["time"] = str(runtime["world_time"])
    planner.put("state/meta.json", meta)
    manifest_before = copy.deepcopy(planner.read("state/player-detail/equipment-manifest.json"))

    reached = CampaignTime.parse(str(runtime["world_time"])).add_seconds(20 * 60)
    wake = {
        "wake_ref": "wake.test.personal-travel",
        "kind": "campaign_event",
        "at": str(reached),
        "reason": "test causal boundary",
    }

    def fake_causal_advance(self, target_text: str):
        # The production adapter must give only the scheduler advance-time
        # authority while travel is settling, so the wake can become durable.
        assert self._active_command_type == "advance_time"
        current = copy.deepcopy(self.read("state/runtime.json"))
        current["world_time"] = str(reached)
        current["pending_wake"] = copy.deepcopy(wake)
        self.put("state/runtime.json", current)
        return {
            "hosts_woken": 1,
            "events_processed": 1,
            "battlefield_reports": [],
            "battlefield_reviews": 0,
            "battlefield_player_interrupt": False,
            "interrupted": True,
            "wake_required": True,
            "wake": copy.deepcopy(wake),
        }

    monkeypatch.setattr(CausalLivingWorldSwordPlanner, "_advance_runtime", fake_causal_advance)

    command = CommandEnvelope(
        meta["campaign_id"],
        "test-personal-travel-wake",
        planner.PLAYER_ACTOR,
        "travel",
        int(meta["revision"]),
        str(meta["time"]),
        {"destination_ref": "loc_kanyou", "mode": "foot"},
        mode="gameplay",
    )
    result = planner._dispatch(command, {"destination_ref": "loc_kanyou", "mode": "foot"})

    assert result["interrupted"] is True
    assert result["wake_required"] is True
    assert result["travel_completed"] is False
    assert result["world_time"] == str(reached)
    assert result["current_location"] == origin
    assert result["requested_arrival_time"] != str(reached)

    after_runtime = planner.read("state/runtime.json")
    assert after_runtime["world_time"] == str(reached)
    assert after_runtime["pending_wake"] == wake
    assert planner.read("state/player.json")["location"] == origin
    assert planner.read("state/player-detail/equipment-manifest.json") == manifest_before
    assert planner.read("state/meta.json")["time"] == str(reached)

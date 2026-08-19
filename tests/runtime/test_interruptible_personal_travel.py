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


def _personal_travel_planner(campaign):
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
    return planner, meta, origin, runtime


def test_personal_travel_uses_current_route_path_between_tang_garrison_and_family_hall(campaign, monkeypatch) -> None:
    planner, meta, _origin, runtime = _personal_travel_planner(campaign)
    origin = "loc_tang_manor_garrison_yard"
    destination = "loc_tang_manor_inner_citadel_family_hall"

    player = copy.deepcopy(planner.read("state/player.json"))
    player["location"] = origin
    if isinstance(player.get("health"), dict) and "fatigue" in player["health"]:
        player["health"]["fatigue"] = 0
    else:
        player["fatigue"] = 0
    player.setdefault("development_state", {})["fatigue_recovery_through"] = str(runtime["world_time"])
    planner.put("state/player.json", player)

    def fake_causal_advance(self, target_text: str):
        current = copy.deepcopy(self.read("state/runtime.json"))
        current["world_time"] = target_text
        current.pop("pending_wake", None)
        self.put("state/runtime.json", current)
        return {
            "hosts_woken": 0,
            "events_processed": 0,
            "battlefield_reports": [],
            "battlefield_reviews": 0,
            "battlefield_player_interrupt": False,
        }

    monkeypatch.setattr(CausalLivingWorldSwordPlanner, "_advance_runtime", fake_causal_advance)

    command = CommandEnvelope(
        meta["campaign_id"],
        "test-personal-manor-derived-route",
        planner.PLAYER_ACTOR,
        "travel",
        int(meta["revision"]),
        str(meta["time"]),
        {"destination_ref": destination, "mode": "foot"},
        mode="gameplay",
    )
    route = planner._find_route(origin, destination, mode="foot")
    expected_hours = int(route.get("duration_hours", route.get("hours", 24)))
    result = planner._dispatch(command, {"destination_ref": destination, "mode": "foot"})

    expected_arrival = CampaignTime.parse(str(runtime["world_time"])).add_seconds(expected_hours * 3600)
    assert result["route_ref"] == "route_path"
    assert result["route_refs"]
    assert result["route_path"][0] == origin
    assert result["route_path"][-1] == destination
    assert result["duration_hours"] == expected_hours
    assert result["travel_completed"] is True
    assert result["world_time"] == str(expected_arrival)
    saved_player = planner.read("state/player.json")
    assert saved_player["location"] == destination
    health = saved_player.get("health")
    saved_fatigue = health.get("fatigue", saved_player.get("fatigue", 0)) if isinstance(health, dict) else saved_player.get("fatigue", 0)
    assert int(saved_fatigue) == max(1, expected_hours // 12)
    assert saved_player["development_state"]["last_fatigue_activity"]["kind"] == "travel"
    assert saved_player["development_state"]["fatigue_recovery_through"] == str(expected_arrival)
    assert planner.read("state/meta.json")["time"] == str(expected_arrival)


def test_personal_travel_commits_reached_wake_without_false_arrival(campaign, monkeypatch) -> None:
    planner, meta, origin, runtime = _personal_travel_planner(campaign)
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


def test_personal_travel_preserves_arrival_when_wake_lands_at_endpoint(campaign, monkeypatch) -> None:
    planner, meta, origin, runtime = _personal_travel_planner(campaign)
    wake_holder: dict[str, object] = {}

    def fake_causal_advance(self, target_text: str):
        assert self._active_command_type == "advance_time"
        reached = CampaignTime.parse(target_text)
        wake = {
            "wake_ref": "wake.test.personal-travel-arrival",
            "kind": "campaign_event",
            "at": str(reached),
            "reason": "test causal boundary at arrival",
        }
        wake_holder.update(wake)
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
        "test-personal-travel-arrival-wake",
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
    assert result["travel_completed"] is True
    assert result["world_time"] == result["requested_arrival_time"]
    assert result["interrupted_at"] == result["requested_arrival_time"]
    assert planner.read("state/player.json")["location"] == "loc_kanyou"
    assert planner.read("state/player.json")["location"] != origin
    assert planner.read("state/runtime.json")["pending_wake"] == wake_holder
    assert planner.read("state/meta.json")["time"] == result["world_time"]

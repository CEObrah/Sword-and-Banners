from __future__ import annotations

from sword_runtime.api.equipment_operations import EquipmentAwareCampaignOperations
from sword_runtime.commands import CommandEnvelope
from sword_runtime.service_runtime import ProductionSwordRuntime


def test_registered_deputy_survives_player_surface_projection(campaign):
    runtime = ProductionSwordRuntime(
        campaign,
        runtime_root=campaign.parent / "runtime-command-staff-surface",
    )
    operations = EquipmentAwareCampaignOperations(runtime)
    context = operations.play_context()

    champions = next(
        row
        for row in context["controlled_formations"]
        if row["formation_ref"] == "formation_tang_champions_first"
    )
    assert champions["commander_ref"] == "char_duan_jin"
    assert champions["deputy_ref"] == "char_shen_rui"
    assert "char_duan_jin" in context["permitted_person_ids"]
    assert "char_shen_rui" in context["permitted_person_ids"]

    inspected = operations.inspect_game_object("formation_tang_champions_first")
    assert inspected["object"]["commander_ref"] == "char_duan_jin"
    assert inspected["object"]["deputy_ref"] == "char_shen_rui"

    page = operations.list_controlled_formations(limit=20)
    paged = next(
        row
        for row in page["formations"]
        if row["formation_ref"] == "formation_tang_champions_first"
    )
    assert paged["deputy_ref"] == "char_shen_rui"


def test_escorted_travel_reconciles_commander_and_deputy_people(campaign):
    runtime = ProductionSwordRuntime(
        campaign,
        runtime_root=campaign.parent / "runtime-command-staff-movement",
    )
    meta = runtime.store.read_json("state/meta.json")
    player = runtime.store.read_json("state/player.json")
    formation = runtime.store.read_json("state/formations/tang-champions-first.json")

    assert player["location"] == formation["location_ref"] == "loc_kanyou"
    assert runtime.store.read_json("state/char/duan-jin.json")["current_location"] == "loc_kanyou"
    assert runtime.store.read_json("state/char/shen-rui.json")["current_location"] == "loc_kanyou"

    command = CommandEnvelope(
        campaign_id=meta["campaign_id"],
        request_id="test-command-staff-escorted-travel",
        actor_id=meta["player_id"],
        command_type="travel",
        expected_revision=meta["revision"],
        submitted_at=meta["time"],
        payload={
            "destination_ref": "loc_tang_manor_garrison_yard",
            "formation_refs": ["formation_tang_champions_first"],
            "mode": "horse",
        },
        mode="gameplay",
    )
    execution = runtime.execute(command)
    assert execution.receipt.result["destination"] == "loc_tang_manor_garrison_yard"
    assert set(execution.receipt.result["command_staff_reconciled"]) == {
        "char_duan_jin",
        "char_shen_rui",
    }

    for path in ("state/char/duan-jin.json", "state/char/shen-rui.json"):
        person = runtime.store.read_json(path)
        assert person["current_location"] == "loc_tang_manor_garrison_yard"
        assert person["current_formation_id"] == "formation_tang_champions_first"

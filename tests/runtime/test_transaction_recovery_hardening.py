from __future__ import annotations

import hashlib
import json

import pytest


from conftest import meta


def _command_and_receipt(root):
    from sword_runtime.commands import CommandEnvelope
    from sword_runtime.tx.receipts import IdempotencyReceipt

    current = meta(root)
    command = CommandEnvelope(
        current["campaign_id"],
        "transaction-invalidation-regression-request",
        current["player_id"],
        "scene_consequence",
        current["revision"],
        current["time"],
        {"summary": "transaction used only for transaction-integrity regression coverage"},
        mode="gameplay",
    )
    transaction_id = "sword-" + hashlib.sha256(
        (command.digest + ":" + str(current["revision"])).encode("utf-8")
    ).hexdigest()[:24]
    receipt = IdempotencyReceipt.for_command(
        command,
        transaction_id=transaction_id,
        committed_revision=current["revision"] + 1,
        committed_at=current["time"],
        result={"test_only": True},
    )
    return current, command, receipt


def test_scene_projection_requires_revision_as_well_as_world_time(campaign):
    from sword_runtime.api.operations import CampaignOperations

    current = meta(campaign)
    player = json.load(open(campaign / "state/player.json"))
    scene = json.load(open(campaign / "state/scene.json"))
    packaged = CampaignOperations._safe_scene(current, player, scene)
    assert packaged["projection_status"] == "stale_after_state_change"
    assert packaged["unresolved_decision"] is None

    fresh_scene = dict(scene)
    fresh_scene["world_time"] = current["time"]
    fresh_scene["projection_revision"] = current["revision"]
    assert CampaignOperations._safe_scene(current, player, fresh_scene)["projection_status"] == "fresh"

    same_time_stale = dict(fresh_scene)
    same_time_stale["projection_revision"] = current["revision"] - 1
    stale = CampaignOperations._safe_scene(current, player, same_time_stale)
    assert stale["projection_status"] == "stale_after_state_change"
    assert stale["unresolved_decision"] is None
    assert stale["observable_pressures"] == []


def test_command_input_guidance_exposes_exact_player_safe_values(campaign, tmp_path):
    from sword_runtime.api.operations import CampaignOperations
    from sword_runtime.service_runtime import ProductionSwordRuntime

    context = CampaignOperations(ProductionSwordRuntime(campaign, tmp_path / "runtime")).play_context()
    commands = context["commands"]["command_types"]
    assert commands["travel"]["input_guidance"]["mode"]["allowed_values"] == ["foot", "horse"]
    assert commands["operation_transition"]["input_guidance"]["status"]["allowed_values"] == ["planned", "mobilizing", "active", "engaged", "occupied", "completed", "cancelled"]
    assert commands["siege_action"]["input_guidance"]["action"]["allowed_values"] == ["blockade", "build_work", "ram_gate", "repair", "assault", "withdraw", "settle", "relief"]
    assert commands["family_event"]["input_guidance"]["player_authored_kinds"] == ["proposal", "engagement", "marriage"]
    assert commands["relationship_change"]["input_guidance"]["delta"] == {"type": "integer", "minimum": -5, "maximum": 5, "forbidden_values": [0]}
    assert "never guess hidden IDs" in context["commands"]["input_guidance_policy"]


def test_production_player_surface_preserves_npc_family_and_house_agency(campaign, tmp_path):
    from sword_runtime.commands import CommandEnvelope
    from sword_runtime.service_runtime import ProductionSwordRuntime

    current = meta(campaign)
    runtime = ProductionSwordRuntime(campaign, tmp_path / "runtime")
    npc_marriage = CommandEnvelope(
        current["campaign_id"],
        "npc-marriage-agency-regression",
        current["player_id"],
        "family_event",
        current["revision"],
        current["time"],
        {"house_ref": "house_tang", "kind": "marriage", "person_ref": "char_tang_ling", "partner_ref": "char_tang_zhu"},
        mode="gameplay",
    )
    with pytest.raises(PermissionError, match="player actor"):
        runtime.preview_for_execution(npc_marriage)

    external_duty = CommandEnvelope(
        current["campaign_id"],
        "external-house-duty-regression",
        current["player_id"],
        "house_action",
        current["revision"],
        current["time"],
        {"house_ref": "house_tang", "action": "assign_duty", "subject_ref": "char_ouki", "duty": "Obey House Tang"},
        mode="gameplay",
    )
    with pytest.raises(PermissionError, match="House Tang duty assignment"):
        runtime.preview_for_execution(external_duty)



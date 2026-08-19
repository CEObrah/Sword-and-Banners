from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from sword_runtime.sim.calendar import CampaignTime

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


def test_empty_transaction_invalidation_registry_is_valid(campaign):
    from sword_runtime.store.repository import RepositoryStore
    from sword_runtime.tx.invalidations import load_transaction_invalidations

    assert load_transaction_invalidations(RepositoryStore(campaign)) == ()


def test_unexplained_future_receipt_fails_recovery(campaign, tmp_path):
    from sword_runtime.service_runtime import ProductionSwordRuntime
    from sword_runtime.tx.errors import RecoveryError

    _current, _command, receipt = _command_and_receipt(campaign)
    runtime = ProductionSwordRuntime(campaign, tmp_path / "runtime")
    runtime.coordinator.receipts.put(receipt)
    with pytest.raises(RecoveryError, match="future campaign revision"):
        runtime.recover()


def test_explicit_transaction_invalidation_allows_recovery_and_reserves_request_id(campaign, tmp_path):
    from sword_runtime.service_runtime import ProductionSwordRuntime
    from sword_runtime.tx.errors import IdempotencyConflictError

    current, command, receipt = _command_and_receipt(campaign)
    head = subprocess.check_output(["git", "-C", str(campaign), "rev-parse", "HEAD"], text=True).strip()
    registry = {
        "schema": "sword.transaction-invalidations",
        "version": 1,
        "records": [{
            "campaign_id": current["campaign_id"],
            "transaction_id": receipt.transaction_id,
            "request_id": receipt.request_id,
            "request_digest": receipt.request_digest,
            "invalidated_revision": receipt.committed_revision,
            "restored_revision": current["revision"],
            "bad_commit": "0" * 40,
            "repair_commit": head,
            "reason": "Disposable regression fixture for explicit invalidation semantics.",
        }],
    }
    path = campaign / "runtime/contracts/transaction-invalidations.json"
    path.write_text(json.dumps(registry, indent=2) + "\n")
    subprocess.run(["git", "-C", str(campaign), "add", "runtime/contracts/transaction-invalidations.json"], check=True)
    subprocess.run(["git", "-C", str(campaign), "commit", "-m", "Register disposable transaction invalidation"], check=True, stdout=subprocess.DEVNULL)

    runtime = ProductionSwordRuntime(campaign, tmp_path / "runtime")
    runtime.coordinator.receipts.put(receipt)
    assert runtime.recover() == ()
    with pytest.raises(IdempotencyConflictError, match="explicitly invalidated"):
        runtime.coordinator.lookup_receipt(command)


def test_play_context_exposes_only_co_located_or_controlled_escort_material_convoys(campaign, tmp_path):
    from sword_runtime.api.operations import CampaignOperations
    from sword_runtime.service_runtime import ProductionSwordRuntime

    runtime = ProductionSwordRuntime(campaign, tmp_path / "runtime-convoy-context")
    ops = CampaignOperations(runtime)
    base = ops.play_context()
    controlled = base["controlled_formations"]
    if not controlled:
        pytest.skip("current campaign has no controlled formation")
    formation_ref = str(controlled[0]["formation_ref"])
    location_ref = str(controlled[0]["location_ref"])
    convoy_ref = "merchant_convoy_context_visible"
    convoy_path = "state/economy/convoys/context-visible.json"
    meta = runtime.store.read_json("state/meta.json")
    convoy = {
        "schema": "sword-merchant-convoy",
        "owner_id": convoy_ref,
        "merchant_house_ref": "merchant_house_lu",
        "source_market_ref": "market_qin_kanyou",
        "destination_market_ref": "market_zhao_gyou",
        "source_state": "qin",
        "destination_state": "zhao",
        "cargo": {"grain_kg": 20},
        "status": "in_transit",
        "departed_at": meta["time"],
        "leg_departed_at": meta["time"],
        "arrives_at": str(CampaignTime.parse(meta["time"]).add_seconds(24 * 3600)),
        "route_refs": [],
        "route_path": [location_ref],
        "wagon_equivalents": 1,
        "escort_formation_refs": [formation_ref],
        "current_location_ref": location_ref,
    }
    (campaign / convoy_path).parent.mkdir(parents=True, exist_ok=True)
    (campaign / convoy_path).write_text(json.dumps(convoy, indent=2) + "\n")
    index_path = campaign / "state/economy/merchant-convoys.json"
    index = json.loads(index_path.read_text())
    index.setdefault("convoys", {})[convoy_ref] = convoy_path
    index.setdefault("active_refs", []).append(convoy_ref)
    index_path.write_text(json.dumps(index, indent=2) + "\n")
    owner_path = campaign / "state/index/owner-index.json"
    owners = json.loads(owner_path.read_text())
    owners.setdefault("owners", {})[convoy_ref] = convoy_path
    owner_path.write_text(json.dumps(owners, indent=2) + "\n")

    refreshed = CampaignOperations(ProductionSwordRuntime(campaign, tmp_path / "runtime-convoy-context-2")).play_context()
    rows = {row["convoy_ref"]: row for row in refreshed["observable_merchant_convoys"]}
    assert convoy_ref in rows
    assert rows[convoy_ref]["controlled_escort_refs"] == [formation_ref]
    assert rows[convoy_ref]["cargo"] == {"grain_kg": 20}
    assert convoy_ref in refreshed["permitted_object_refs"]

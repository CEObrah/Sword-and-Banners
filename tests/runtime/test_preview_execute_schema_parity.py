from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import meta


def _json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def test_campaign_subordinate_mission_packet_schema_is_registered():
    root = Path(__file__).resolve().parents[2]
    registry = json.load(open(root / "game/schemas/registry.json"))
    schema_id = "sword-campaign-subordinate-mission-packet-1.0"
    assert registry[schema_id] == "sword-campaign-subordinate-mission-packet.schema.json"

    schema = json.load(open(root / "game/schemas" / registry[schema_id]))
    assert schema["properties"]["schema"]["const"] == schema_id
    assert schema["properties"]["hostile_entry_authorized"]["const"] is True
    assert schema["properties"]["entry_status"]["const"] == "authorized"

    source = (root / "runtime/sword_runtime/campaign_subordinate_orders.py").read_text()
    assert f'"schema": "{schema_id}"' in source


def test_production_preview_rejects_invalid_staged_schema_before_ready(campaign, monkeypatch):
    from sword_runtime.commands import CommandEnvelope
    from sword_runtime.engine import CommandPlan
    from sword_runtime.service_runtime import ProductionSwordRuntime

    runtime = ProductionSwordRuntime(campaign)
    before = meta(campaign)
    command = CommandEnvelope(
        before["campaign_id"],
        "preview-schema-parity-probe",
        before["player_id"],
        "information_create",
        before["revision"],
        before["time"],
        {},
        mode="gameplay",
    )

    next_meta = json.loads((Path(campaign) / "state/meta.json").read_text())
    next_meta["revision"] = before["revision"] + 1
    writes = {
        "state/meta.json": _json_bytes(next_meta),
        "state/preview-schema-parity-probe.json": _json_bytes(
            {
                "schema": "generic-object",
                "nested": {"schema": "sword-preview-schema-probe-unregistered"},
            }
        ),
    }

    def validate(overlay, manifest):
        runtime.planner.schema_validator.validate_overlay(overlay, manifest.paths)

    plan = CommandPlan(
        "preview-schema-parity-probe",
        before["time"],
        writes,
        {},
        0,
        validate,
    )
    monkeypatch.setattr(runtime.planner, "preview", lambda _command: plan)

    with pytest.raises(ValueError, match="unregistered schema"):
        runtime.preview_for_execution(command)

    # Preview validation is read-only: it must not publish the proposed revision
    # or leave the synthetic staged owner behind.
    after = meta(campaign)
    assert after["revision"] == before["revision"]
    assert not (Path(campaign) / "state/preview-schema-parity-probe.json").exists()


def test_campaign_subordinate_packet_shape_validates_through_registered_schema(campaign):
    from sword_runtime.store.repository import RepositoryStore
    from sword_runtime.store.schema_validation import RegisteredSchemaValidator
    from sword_runtime.tx.manifest import TransactionPlanner
    from sword_runtime.store.overlay import StagedOverlay
    from sword_runtime.commands import CommandEnvelope

    root = Path(campaign)
    repository = RepositoryStore(root)
    before = meta(campaign)
    command = CommandEnvelope(
        before["campaign_id"],
        "campaign-subordinate-packet-schema-probe",
        before["player_id"],
        "information_create",
        before["revision"],
        before["time"],
        {},
        mode="gameplay",
    )
    next_meta = json.loads((root / "state/meta.json").read_text())
    next_meta["revision"] = before["revision"] + 1
    packet = {
        "schema": "sword-campaign-subordinate-mission-packet-1.0",
        "mission_phase": "campaign_advance",
        "phase_status": "ready_for_commander_execution",
        "destination_ref": "loc_sanyou",
        "strategic_target_ref": "loc_sanyou",
        "target_state_ref": "state_wei",
        "hostile_entry_authorized": True,
        "entry_status": "authorized",
        "campaign_arc_ref": "arc_ryo_fui_northern_wei_campaign",
        "source_campaign_cycle_ref": "campaign_command_cycle.schema_probe",
        "source_staff_command_ref": "cmdgrp.schema_probe",
        "success_condition": "every surviving formation reaches the exact destination",
        "next_phase_trigger": "arrival completes the march order",
        "authority_rule": "exact command adoption is required",
    }
    writes = {
        "state/meta.json": _json_bytes(next_meta),
        "state/campaign-subordinate-packet-schema-probe.json": _json_bytes(
            {"schema": "generic-object", "mission_packet": packet}
        ),
    }
    manifest = TransactionPlanner(repository).plan(
        command,
        transaction_id="campaign-subordinate-packet-schema-probe",
        created_at=before["time"],
        writes=writes,
    )
    overlay = StagedOverlay(repository, manifest)
    RegisteredSchemaValidator(repository).validate_overlay(overlay, manifest.paths)

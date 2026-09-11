from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import meta


def _json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _campaign_packet() -> dict:
    return {
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


def _validate_packet_variant(campaign, packet: dict, suffix: str) -> None:
    from sword_runtime.commands import CommandEnvelope
    from sword_runtime.store.overlay import StagedOverlay
    from sword_runtime.store.repository import RepositoryStore
    from sword_runtime.store.schema_validation import RegisteredSchemaValidator
    from sword_runtime.tx.manifest import TransactionPlanner

    root = Path(campaign)
    repository = RepositoryStore(root)
    before = meta(campaign)
    command = CommandEnvelope(
        before["campaign_id"],
        f"campaign-subordinate-packet-schema-{suffix}",
        before["player_id"],
        "information_create",
        before["revision"],
        before["time"],
        {},
        mode="gameplay",
    )
    next_meta = json.loads((root / "state/meta.json").read_text())
    next_meta["revision"] = before["revision"] + 1
    writes = {
        "state/meta.json": _json_bytes(next_meta),
        f"state/campaign-subordinate-packet-schema-{suffix}.json": _json_bytes(
            {"schema": "generic-object", "mission_packet": packet}
        ),
    }
    manifest = TransactionPlanner(repository).plan(
        command,
        transaction_id=f"campaign-subordinate-packet-schema-{suffix}",
        created_at=before["time"],
        writes=writes,
    )
    overlay = StagedOverlay(repository, manifest)
    RegisteredSchemaValidator(repository).validate_overlay(overlay, manifest.paths)


def test_campaign_subordinate_mission_packet_schema_is_registered():
    root = Path(__file__).resolve().parents[2]
    registry = json.load(open(root / "game/schemas/registry.json"))
    schema_id = "sword-campaign-subordinate-mission-packet-1.0"
    assert registry[schema_id] == "sword-campaign-subordinate-mission-packet.schema.json"

    schema = json.load(open(root / "game/schemas" / registry[schema_id]))
    assert schema["properties"]["schema"]["const"] == schema_id
    assert set(schema["properties"]["phase_status"]["enum"]) == {
        "ready_for_commander_execution",
        "executing",
        "completed",
        "blocked",
    }
    assert schema["properties"]["hostile_entry_authorized"]["const"] is True
    assert schema["properties"]["entry_status"]["const"] == "authorized"

    source = (root / "runtime/sword_runtime/campaign_subordinate_orders.py").read_text()
    lifecycle = (root / "runtime/sword_runtime/campaign_march_lifecycle.py").read_text()
    assert f'"schema": "{schema_id}"' in source
    for field in ("execution_started_at", "completed_at", "actual_arrival_ref", "blocked_at", "blocked_reason"):
        assert field in lifecycle
        assert field in schema["properties"]


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


def test_campaign_subordinate_packet_lifecycle_shapes_validate(campaign):
    ready = _campaign_packet()
    _validate_packet_variant(campaign, ready, "ready")

    executing = dict(ready)
    executing["phase_status"] = "executing"
    executing["execution_started_at"] = "244-BCE-10-14T18:00:00+08:00"
    _validate_packet_variant(campaign, executing, "executing")

    blocked = dict(executing)
    blocked["phase_status"] = "blocked"
    blocked["blocked_at"] = "244-BCE-10-14T18:00:00+08:00"
    blocked["blocked_reason"] = "canonical route requires transit authority"
    _validate_packet_variant(campaign, blocked, "blocked")

    completed = dict(executing)
    completed["phase_status"] = "completed"
    completed["completed_at"] = "244-BCE-10-16T18:00:00+08:00"
    completed["actual_arrival_ref"] = "loc_sanyou"
    _validate_packet_variant(campaign, completed, "completed")


def test_current_campaign_information_preview_survives_subordinate_march_reconcile(campaign):
    """Reproduce the live failure path without committing the report.

    The five-minute deterministic information preview crosses scheduler preparation,
    exact subordinate-order adoption, route registration, and Mou Bu's lawful
    blocked-transit branch. Every staged packet lifecycle state must validate before
    production preview can return ``ready``.
    """
    from sword_runtime.commands import CommandEnvelope
    from sword_runtime.service_runtime import ProductionSwordRuntime

    runtime = ProductionSwordRuntime(campaign)
    before = meta(campaign)
    command = CommandEnvelope(
        before["campaign_id"],
        "preview-live-junction-report-root-regression",
        before["player_id"],
        "information_create",
        before["revision"],
        before["time"],
        {
            "claim": (
                "Tang Wei Field Army remains in the Wei Western Corridor after holding as intended. "
                "Tang Wei requests General Mou Gou's exact present junction plan and the point at which "
                "Tang Wei's army is to join the main body; until a reply or another material development "
                "arrives, Tang Wei intends to remain in position."
            ),
            "epistemic_kind": "official_report",
            "information_ref": "information.preview_live_junction_report_root_regression",
            "knowers": [before["player_id"]],
            "location_ref": "loc_wei_regional_02",
            "provenance": "preview-only campaign command report regression",
            "subject_ref": "operation_arc_131572c4e8a2892bbc",
        },
        mode="gameplay",
    )

    result = runtime.preview_for_execution(command)
    assert result["status"] == "ready"
    assert result["target_revision"] == before["revision"] + 1

    # The regression uses the production preview boundary only. No report, order,
    # route, time, or campaign revision may become canonical here.
    after = meta(campaign)
    assert after["revision"] == before["revision"]
    assert after["time"] == before["time"]

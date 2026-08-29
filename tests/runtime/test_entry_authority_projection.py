from __future__ import annotations

from fastapi.testclient import TestClient

from sword_runtime.api.app import create_app


def test_authorized_entry_projection_removes_stale_gate_language(campaign) -> None:
    token = "e" * 48
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(create_app(campaign, token)) as client:
        response = client.get("/v1/play/context", headers=headers)
        assert response.status_code == 200
        context = response.json()

    operation = next(
        row for row in context["controlled_operations"]
        if row.get("operation_ref") == "operation_arc_131572c4e8a2892bbc"
    )
    assert operation["entry_status"] == "authorized"
    assert operation["entry_authority"]["authorized"] is True
    assert operation["campaign_phase"] == "awaiting_march_orders"
    assert operation["order_status"] == "awaiting_march_orders"

    order = operation["current_operational_order"]
    assert order["status"] == "completed_staging_entry_now_authorized"
    assert order["historical_staging_status"] == "staged_awaiting_entry_authority"
    assert order["follow_on_requirement_projection_only"] is True
    assert "already established" in order["follow_on_requirement"].lower()
    assert "requires a new exact war/entry authority" in order["historical_follow_on_requirement"].lower()

    packet = order["mission_packet"]
    assert packet["hostile_entry_authorized"] is True
    assert packet["entry_status"] == "authorized"
    assert packet["next_phase_trigger_projection_only"] is True
    assert "already established" in packet["next_phase_trigger"].lower()
    assert "requires lawful war/entry authority" in packet["historical_next_phase_trigger"].lower()

    campaign_command = operation["campaign_command"]
    directive = campaign_command["current_superior_directive"]
    assert directive["historical_status"] == "active"
    assert directive["status"] == "superseded_by_entry_authority"
    assert directive["status_projection_only"] is True
    assert directive["entry_hold_effective"] is False
    assert "no longer effective" in directive["effective_directive_rule"].lower()

    daily = campaign_command["daily_cycle"]
    assert daily["historical_paused_campaign_phase"] == "awaiting_entry_authority"
    assert daily["paused_campaign_phase"] == "awaiting_march_orders"
    assert daily["paused_campaign_phase_projection_only"] is True

    scheme = campaign_command["march_planning"]["campaign_scheme"]
    assert scheme["historical_status"] == "staff_plan_pending_exact_orders_and_entry_authority"
    assert scheme["status"] == "staff_plan_pending_exact_orders"
    assert scheme["status_projection_only"] is True

    campaign_context = operation["campaign_context"]
    assert campaign_context["campaign_commander_ref"] == "char_mou_gou"
    assert campaign_context["campaign_commander_name"] == "Mou Gou"
    assert campaign_context["campaign_commander_projection_only"] is True

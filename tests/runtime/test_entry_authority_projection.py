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
    assert operation["campaign_phase"] != "awaiting_entry_authority"
    assert operation["order_status"] != "awaiting_entry_authority"

    order = operation["current_operational_order"]
    packet = order["mission_packet"]
    assert packet["hostile_entry_authorized"] is True
    assert packet["entry_status"] == "authorized"

    # The adapter may expose either an older staging order with projection-only
    # overrides or a later exact actionable order after the campaign has advanced.
    # In both cases the effective player-facing order must not retain a legal-entry
    # blocker. Historical gate text, when retained for provenance, stays explicitly
    # historical and cannot control the effective status.
    assert order.get("status") != "staged_awaiting_entry_authority"
    assert "requires a new exact war/entry authority" not in str(order.get("follow_on_requirement", "")).lower()
    assert "requires lawful war/entry authority" not in str(packet.get("next_phase_trigger", "")).lower()
    if "historical_staging_status" in order:
        assert order["historical_staging_status"] == "staged_awaiting_entry_authority"
    if "historical_follow_on_requirement" in order:
        assert "requires a new exact war/entry authority" in order["historical_follow_on_requirement"].lower()
    if "historical_next_phase_trigger" in packet:
        assert "requires lawful war/entry authority" in packet["historical_next_phase_trigger"].lower()

    campaign_command = operation["campaign_command"]
    directive = campaign_command["current_superior_directive"]
    assert directive.get("entry_hold_effective", False) is False
    if directive.get("status_projection_only") is True:
        assert directive["status"] == "superseded_by_entry_authority"
        assert "no longer effective" in directive["effective_directive_rule"].lower()
    else:
        # A later exact directive may already replace the obsolete staging hold.
        assert directive["status"] == "active"
        assert directive.get("kind") != "hold_staging_and_report"

    daily = campaign_command["daily_cycle"]
    if daily.get("paused_campaign_phase_projection_only") is True:
        assert daily["historical_paused_campaign_phase"] == "awaiting_entry_authority"
        assert daily["paused_campaign_phase"] != "awaiting_entry_authority"
    elif daily.get("status") == "paused_until_field_operations":
        assert daily.get("paused_campaign_phase") != "awaiting_entry_authority"

    # Current staff planning may already have independently shed the obsolete
    # entry-authority suffix. The effective status cannot keep advertising the
    # cleared gate, and provenance is required only when the adapter rewrites it.
    scheme = campaign_command["march_planning"]["campaign_scheme"]
    assert scheme["status"] == "staff_plan_pending_exact_orders"
    if "historical_status" in scheme:
        assert scheme["historical_status"] == "staff_plan_pending_exact_orders_and_entry_authority"
        assert scheme["status_projection_only"] is True

    campaign_context = operation["campaign_context"]
    assert campaign_context["campaign_commander_ref"] == "char_mou_gou"
    assert campaign_context["campaign_commander_name"] == "Mou Gou"

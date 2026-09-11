from __future__ import annotations

import pytest

from sword_runtime.battle_command import _objective_posture
from sword_runtime.operation_routing import (
    append_operational_order,
    current_operational_order,
    current_operational_order_slot,
    operational_order_by_ref,
    operational_order_slot,
)
from sword_runtime.sovereign_campaign_authority_mixin import SovereignCampaignAuthorityMixin


def _operation() -> dict:
    return {
        "last_operational_order_ref": "order.current",
        "objective": "Develop contact and report.",
        "operational_orders": [
            {
                "order_ref": "order.current",
                "status": "staff_briefed_awaiting_commander_execution",
                "actionability_status": "actionable",
                "target_ref": "state_wei",
                "mission_packet": {
                    "mission_phase": "contact_development",
                    "operational_intent": "develop_contact",
                },
            },
            {
                "order_ref": "order.pending",
                "status": "issued_pending_delivery",
                "actionability_status": "pending_delivery",
                "target_ref": "state_zhao",
                "objective": "Attack Zhao immediately.",
                "mission_packet": {
                    "mission_phase": "campaign_advance",
                    "operational_intent": "attack",
                },
            },
        ],
    }


def test_current_order_identity_ignores_history_tail_and_reordering() -> None:
    operation = _operation()
    assert current_operational_order(operation)["order_ref"] == "order.current"
    operation["operational_orders"] = list(reversed(operation["operational_orders"]))
    assert current_operational_order(operation)["order_ref"] == "order.current"
    slot = current_operational_order_slot(operation)
    assert slot is not None
    rows, index = slot
    assert rows[index]["order_ref"] == "order.current"


def test_current_order_identity_fails_closed_without_unique_explicit_pointer() -> None:
    operation = _operation()
    operation.pop("last_operational_order_ref")
    assert current_operational_order(operation) is None

    operation = _operation()
    operation["last_operational_order_ref"] = "order.missing"
    assert current_operational_order(operation) is None

    operation = _operation()
    operation["operational_orders"].append(dict(operation["operational_orders"][0]))
    assert current_operational_order(operation) is None



def test_exact_order_lookup_is_reordering_safe_and_fails_closed_on_duplicate_identity() -> None:
    operation = _operation()
    assert operational_order_by_ref(operation, "order.pending")["target_ref"] == "state_zhao"
    slot = operational_order_slot(operation, "order.pending")
    assert slot is not None and slot[0][slot[1]]["order_ref"] == "order.pending"

    operation["operational_orders"] = list(reversed(operation["operational_orders"]))
    assert operational_order_by_ref(operation, "order.pending")["target_ref"] == "state_zhao"

    operation["operational_orders"].append(dict(operation["operational_orders"][0]))
    duplicated_ref = operation["operational_orders"][0]["order_ref"]
    assert operational_order_by_ref(operation, duplicated_ref) is None
    assert operational_order_slot(operation, duplicated_ref) is None

def test_battle_posture_uses_received_current_order_not_pending_history_tail() -> None:
    operation = _operation()
    assert _objective_posture(operation) == "neutral"
    operation["operational_orders"] = list(reversed(operation["operational_orders"]))
    assert _objective_posture(operation) == "neutral"


def test_sovereign_target_fallback_uses_current_order_not_pending_history_tail() -> None:
    operation = _operation()
    assert SovereignCampaignAuthorityMixin._operation_target_state(operation, "state_qin") == "state_wei"
    operation["operational_orders"] = list(reversed(operation["operational_orders"]))
    assert SovereignCampaignAuthorityMixin._operation_target_state(operation, "state_qin") == "state_wei"


def test_operational_order_history_append_is_lossless_and_identity_checked() -> None:
    operation = {
        "last_operational_order_ref": "order.000",
        "operational_orders": [
            {"order_ref": f"order.{index:03d}", "status": "completed"}
            for index in range(40)
        ],
    }
    before_refs = [row["order_ref"] for row in operation["operational_orders"]]
    append_operational_order(operation, {"order_ref": "order.040", "status": "issued_pending_delivery"})
    assert [row["order_ref"] for row in operation["operational_orders"][:-1]] == before_refs
    assert len(operation["operational_orders"]) == 41
    assert current_operational_order(operation)["order_ref"] == "order.000"


def test_operational_order_history_rejects_duplicate_identity() -> None:
    operation = _operation()
    try:
        append_operational_order(operation, {"order_ref": "order.current", "status": "completed"})
    except ValueError as exc:
        assert "duplicate operational order identity" in str(exc)
    else:
        raise AssertionError("duplicate order identity must fail closed")


def test_append_order_preserves_history_and_rejects_duplicate_identity() -> None:
    operation = _operation()
    original_refs = [row["order_ref"] for row in operation["operational_orders"]]
    for index in range(80):
        append_operational_order(operation, {"order_ref": f"order.history.{index:03d}"})
    refs = [row["order_ref"] for row in operation["operational_orders"]]
    assert refs[:2] == original_refs
    assert len(refs) == 82
    assert current_operational_order(operation)["order_ref"] == "order.current"
    with pytest.raises(ValueError, match="duplicate operational order identity"):
        append_operational_order(operation, {"order_ref": "order.history.079"})

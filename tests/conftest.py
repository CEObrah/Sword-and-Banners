from __future__ import annotations

import pytest


_OBSOLETE_INTEGRATION_EXPECTATIONS = {
    "test_local_wall_blocks_contact_path": (
        "Current exact visibility rejects a fully occluded target before attack scheduling. "
        "The old test expected a later obstructed attack trace and therefore contradicts "
        "the current LOS authority. Static wall blocking remains covered directly by "
        "test_combat_geometry_visibility.py."
    ),
    "test_bare_follow_on_request_cannot_create_superior_order": (
        "This pre-#186 test expects a generic follow-on response marker to stand in for "
        "physical headquarters receipt. Current campaign-command authority requires the "
        "request to arrive in the ordinary upward report before superior decision logic may use it."
    ),
    "test_follow_on_request_gets_delayed_causal_review_route": (
        "PR #186 retired the duplicate campaign_command_follow_on_review host. Current requests "
        "travel upward in campaign reports and any resulting order returns separately through "
        "campaign_command_superior_order delivery."
    ),
    "test_remote_follow_on_request_uses_round_trip_command_route_plus_staff_delay": (
        "The old round-trip review host is intentionally obsolete. Current command traffic is "
        "two causal one-way legs: upward report receipt, then separate superior-order delivery."
    ),
    "test_parallel_follow_on_requests_do_not_overwrite_each_other": (
        "This test counts obsolete parallel review hosts. Current request identity is conserved in "
        "upward report follow_on_request_refs and no duplicate review-host lifecycle is created."
    ),
    "test_reconciled_entry_gets_new_deliverable_follow_on_order_without_moving_army": (
        "The historical campaign_entry_follow_on_march_order lifecycle has been retired. "
        "Entry reconciliation now clears the exact hostile-entry authority gate only; later "
        "movement or mission orders belong to the campaign-command decision and physical-delivery chain."
    ),
    "test_project_cancellation_releases_workers_and_refunds_unused_inputs": (
        "This fixture seeds construction material only in the retired state-wide private-economy aggregate. "
        "Funded projects now reserve workers/materials from the institution's exact regional economy. "
        "Equivalent regional-owner coverage lives in test_project_regional_economy.py."
    ),
}


def pytest_collection_modifyitems(items):
    for item in items:
        reason = _OBSOLETE_INTEGRATION_EXPECTATIONS.get(item.name)
        if reason:
            item.add_marker(pytest.mark.xfail(reason=reason, strict=True))

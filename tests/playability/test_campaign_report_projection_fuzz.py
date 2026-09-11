from __future__ import annotations

import random

from sword_runtime.api.command_discovery import _compact_campaign_command
from sword_runtime.campaign_report_projection import (
    pending_upward_report_count,
    select_pending_upward_reports,
)

ROUTINE = {"dawn", "evening"}


def _expected(rows, maximum):
    pending = [(i, row) for i, row in enumerate(rows) if row["delivery_status"] != "delivered"]
    response = [(i, row) for i, row in pending if row.get("follow_on_request_refs")]
    material = [
        (i, row)
        for i, row in pending
        if not row.get("follow_on_request_refs") and row["phase"] not in ROUTINE
    ]
    routine = [
        (i, row)
        for i, row in pending
        if not row.get("follow_on_request_refs") and row["phase"] in ROUTINE
    ]
    chosen = []
    remaining = maximum
    for bucket in (response, material, routine):
        if remaining <= 0:
            break
        take = bucket[-remaining:]
        chosen.extend(take)
        remaining -= len(take)
    chosen.sort(key=lambda item: item[0])
    return [row["report_ref"] for _, row in chosen]


def _rows(seed: int, count: int):
    rng = random.Random(seed)
    rows = []
    for i in range(count):
        response = rng.random() < 0.22
        rows.append(
            {
                "report_ref": f"report.{seed}.{i}",
                "phase": rng.choice(("dawn", "evening", "material_intelligence", "casualty", "arrival")),
                "delivery_status": rng.choice(("delivered", "in_transit", "route_unresolved", "prepared")),
                "follow_on_request_refs": [f"request.{seed}.{i}"] if response else [],
            }
        )
    return rows


def test_pending_report_projection_fuzz_preserves_priority_and_never_resurrects_delivered_history():
    for seed in range(80):
        rows = _rows(seed, seed % 101)
        unresolved = [row for row in rows if row["delivery_status"] != "delivered"]
        assert pending_upward_report_count(rows) == len(unresolved)
        for maximum in (0, 1, 2, 4, 8, 16):
            selected = select_pending_upward_reports(rows, maximum=maximum)
            refs = [row["report_ref"] for row in selected]
            assert refs == _expected(rows, maximum)
            assert len(refs) <= maximum
            assert all(row["delivery_status"] != "delivered" for row in selected)
            # Recompacting an already bounded pending window must never create a
            # delivered row or reorder the retained causal work.
            assert [
                row["report_ref"]
                for row in select_pending_upward_reports(selected, maximum=maximum)
            ] == refs


def test_response_bearing_courier_wins_even_under_one_hundred_newer_routine_reports():
    rows = [
        {
            "report_ref": "response.old",
            "phase": "material_intelligence",
            "delivery_status": "in_transit",
            "follow_on_request_refs": ["request.old"],
        }
    ]
    rows.extend(
        {
            "report_ref": f"routine.{i}",
            "phase": "dawn" if i % 2 == 0 else "evening",
            "delivery_status": "in_transit",
            "follow_on_request_refs": [],
        }
        for i in range(100)
    )
    selected = select_pending_upward_reports(rows, maximum=4)
    assert "response.old" in {row["report_ref"] for row in selected}


def test_route_unresolved_is_pending_but_never_relabelled_as_physically_in_flight():
    command = {
        "cycle_ref": "cycle.torture",
        "superior_command_ref": "char_mou_gou",
        "upward_reports": [
            {
                "report_ref": "route.unresolved",
                "phase": "material_intelligence",
                "delivery_status": "route_unresolved",
                "follow_on_request_refs": ["request.route"],
            }
        ],
    }
    compact, _ = _compact_campaign_command(command, {"order_ref": "order.base"})
    handoff = compact["remote_command_handoff"]
    assert handoff["outbound_report_in_flight"] is False
    assert handoff["route_unresolved"] is True
    assert handoff["response_requested"] is True

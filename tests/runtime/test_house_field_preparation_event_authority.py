from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

import sword_runtime.house_field_preparation_issue as field_issue


ROOT = Path(__file__).resolve().parents[2]
EVENT_PATH = "state/event/events-messages-and-movement.json"
HOUSE_PATH = "state/houses/house_tang.json"
RULES_PATH = "game/data/mechanics/house-tang-field-service.json"
EVENT_REF = "event_house_field_preparation_fixture"
AT = "244-BCE-07-23T10:22:48+08:00"


class _MemoryPlanner:
    def __init__(self) -> None:
        self.docs = {
            HOUSE_PATH: {
                "administrative_programs": {
                    "wei_field_preparation": {
                        "principal_ref": "char_tang_wei",
                    }
                }
            },
            RULES_PATH: {
                "field_service_preparation": {
                    "reserve_days": 120,
                    "arrow_loads_total": 30,
                    "spare_equipment_basis_points": 5000,
                    "spare_loadout_fields": [],
                }
            },
            EVENT_PATH: {
                "schema": "event-registry",
                "name": "Fixture event registry",
                "owner_id": "events_messages_and_movement",
                "owner_type": "event_registry",
                "records": [],
                "causal_events": {
                    EVENT_REF: {
                        "event_ref": EVENT_REF,
                        "kind": "institutional_response",
                        "status": "triggered",
                        "due_at": AT,
                        "triggered_at": AT,
                        "actor_ref": "char_tang_ling",
                        "target_ref": "char_tang_wei",
                        "process_kind": "house_field_preparation",
                        "process_stage": "staging_and_shortfall_review",
                        "summary": "Field preparation is under review.",
                        "provenance": {
                            "kind": "causal_runtime_settlement",
                            "source_owner_ref": "house_tang",
                            "work_ref": EVENT_REF,
                            "late_catch_up": False,
                        },
                    }
                },
                "runtime": {"last_settled_at": AT},
            },
        }

    def read(self, path):
        return copy.deepcopy(self.docs[path])

    def put(self, path, document):
        self.docs[path] = copy.deepcopy(document)


def _event_schema():
    return json.loads(
        (ROOT / "game" / "schemas" / "event-registry.schema.json").read_text(
            encoding="utf-8"
        )
    )


def _material_stub(_planner, *, formation_ref, reserve_days, arrow_loads_total, at):
    assert reserve_days == 120
    assert arrow_loads_total == 30
    assert at == AT
    return {
        "formation_ref": formation_ref,
        "targets": {"food_kg": 1, "fodder_kg": 2, "war_arrows": 3},
        "issued": {"food_kg": 1, "fodder_kg": 2, "war_arrows": 3},
        "shortfalls": {},
    }


def _equipment_stub(_planner, *, formation_ref, spare_basis_points, eligible_fields, at):
    assert spare_basis_points == 5000
    assert eligible_fields == ()
    assert at == AT
    return {
        "formation_ref": formation_ref,
        "desired_each": 0,
        "issued": {},
        "shortfalls": {},
    }


def test_field_preparation_keeps_exact_issue_report_out_of_causal_event(monkeypatch) -> None:
    planner = _MemoryPlanner()
    monkeypatch.setattr(field_issue, "_issue_material_reserve", _material_stub)
    monkeypatch.setattr(field_issue, "_issue_spare_equipment", _equipment_stub)

    report = field_issue.issue_house_field_preparation_package(
        planner,
        request_id="fixture-field-prep-request",
        response_event_ref=EVENT_REF,
        at=AT,
    )

    prep = planner.docs[HOUSE_PATH]["administrative_programs"]["wei_field_preparation"]
    assert prep["material_issue_report"] == report
    assert prep["material_issue_request_id"] == "fixture-field-prep-request"
    assert prep["material_issued_at"] == AT

    event_owner = planner.docs[EVENT_PATH]
    event = event_owner["causal_events"][EVENT_REF]
    assert event["process_stage"] == "issued_for_departure"
    assert "material_issue" not in event
    assert "Tang Champions receive" in event["summary"]
    assert "House Guard receive" in event["summary"]
    Draft202012Validator(_event_schema()).validate(event_owner)


def test_event_schema_rejects_duplicate_material_issue_authority() -> None:
    planner = _MemoryPlanner()
    event_owner = planner.docs[EVENT_PATH]
    event_owner["causal_events"][EVENT_REF]["material_issue"] = {"formations": {}}

    with pytest.raises(ValidationError):
        Draft202012Validator(_event_schema()).validate(event_owner)

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]


def _event_validator() -> Draft202012Validator:
    document = json.loads((ROOT / "game/schemas/event-registry.schema.json").read_text(encoding="utf-8"))
    schema = document["properties"]["causal_events"]["additionalProperties"]
    return Draft202012Validator(schema)


def _qin_support_event() -> dict[str, object]:
    return {
        "event_ref": "event_qin_command_support_e19cba36828c45880e8f",
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": "244-BCE-09-09T20:22:48+08:00",
        "triggered_at": "244-BCE-09-09T20:22:48+08:00",
        "actor_ref": "inst_qin_military_bureau",
        "target_ref": "char_tang_wei",
        "basis_goal": "Settle Qin field-command support request wei-r5-full-field-army-commit-0826b",
        "process_kind": "qin_field_command_support",
        "process_stage": "march_support",
        "source_event_ref": "scene_e67617320aa8396b",
        "summary": "The Qin Military Bureau returns the current field-command support status.",
        "delivery": {
            "target_ref": "char_tang_wei",
            "location_ref": "loc_qin_eastern_depot",
            "route": "Qin field-command military dispatch channel",
        },
        "provenance": {
            "kind": "causal_runtime_settlement",
            "source_owner_ref": "inst_qin_military_bureau",
            "work_ref": "event_qin_command_support_e19cba36828c45880e8f",
            "late_catch_up": False,
            "source_work_ref": "wei-r5-full-field-army-commit-0826b",
        },
    }


def test_qin_command_support_event_accepts_exact_source_work_ref() -> None:
    _event_validator().validate(_qin_support_event())


def test_qin_command_support_provenance_remains_closed() -> None:
    event = _qin_support_event()
    provenance = dict(event["provenance"])
    provenance["unregistered_field"] = "must fail"
    event["provenance"] = provenance
    errors = list(_event_validator().iter_errors(event))
    assert errors

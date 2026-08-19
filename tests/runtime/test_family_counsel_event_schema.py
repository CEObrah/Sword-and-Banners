import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[2]
EVENT_SCHEMA_PATH = ROOT / "game/schemas/event-registry.schema.json"


def _causal_event_validator() -> Draft202012Validator:
    document = json.loads(EVENT_SCHEMA_PATH.read_text(encoding="utf-8"))
    causal_event_schema = document["properties"]["causal_events"]["additionalProperties"]
    Draft202012Validator.check_schema(causal_event_schema)
    return Draft202012Validator(causal_event_schema)


def _family_counsel_event() -> dict:
    return {
        "event_ref": "event_family_counsel_response_example",
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": "244-BCE-08-04T06:37:48+08:00",
        "triggered_at": "244-BCE-08-04T06:37:48+08:00",
        "actor_ref": "char_tang_ling",
        "target_ref": "char_tang_wei",
        "basis_goal": "Tang Ling responds to Tang Wei's request for counsel",
        "process_kind": "house_tang_family_counsel",
        "process_stage": "responded",
        "summary": "Tang Ling gives nonbinding advice.",
        "source_event_ref": "event_story_family_invitation_example",
        "advisory_record": {
            "schema": "sword-nonbinding-counsel.v1",
            "speaker_ref": "char_tang_ling",
            "audience_ref": "char_tang_wei",
            "request_id": "req_family_counsel_example",
            "process_ref": "event_story_family_invitation_example",
            "topics": ["sovereignty_and_diplomacy"],
            "positions": ["Preserve preparation and choice without creating a commitment."],
            "binding": False,
            "creates_policy": False,
            "creates_commitment": False,
            "creates_authority": False,
        },
        "delivery": {
            "target_ref": "char_tang_wei",
            "location_ref": "loc_qin_eastern_depot",
            "route": "House Tang family counsel",
        },
        "provenance": {
            "kind": "causal_runtime_settlement",
            "source_owner_ref": "char_tang_ling",
            "work_ref": "event_family_counsel_response_example",
            "late_catch_up": False,
        },
    }


def test_family_counsel_advisory_record_is_valid_closed_causal_event_data():
    validator = _causal_event_validator()
    validator.validate(_family_counsel_event())


def test_family_counsel_advisory_record_cannot_claim_binding_authority():
    validator = _causal_event_validator()
    event = _family_counsel_event()
    event["advisory_record"]["binding"] = True
    with pytest.raises(ValidationError):
        validator.validate(event)


def test_family_counsel_advisory_record_rejects_unregistered_fields():
    validator = _causal_event_validator()
    event = copy.deepcopy(_family_counsel_event())
    event["advisory_record"]["grants_command"] = True
    with pytest.raises(ValidationError):
        validator.validate(event)

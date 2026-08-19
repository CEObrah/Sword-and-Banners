from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


def test_sab_character_accepts_multifocus_training_history() -> None:
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / "game/schemas/sab-character.schema.json").read_text())
    record = {
        "schema": "sab_character",
        "owner_id": "char_test",
        "name": "Test",
        "birth_date": "261-BCE-12-02",
        "body": {
            "adult_height_cm": 167,
            "growth_end_age": 18,
            "current_weight_kg": 61,
            "frame": "athletic",
        },
        "appearance": 50,
        "training_history": [
            {
                "started_at": "245-BCE-12-07T12:05:48+08:00",
                "completed_at": "245-BCE-12-07T18:22:48+08:00",
                "hours": 1,
                "development": [
                    {"skill": "Formation Command", "skill_points_gained": 0},
                    {"skill": "Tactics", "skill_points_gained": 0},
                ],
            }
        ],
    }

    Draft202012Validator(schema).validate(record)

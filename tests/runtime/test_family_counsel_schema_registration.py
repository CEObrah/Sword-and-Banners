import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_nonbinding_family_counsel_nested_schema_marker_is_registered():
    registry = json.loads((ROOT / "game/schemas/registry.json").read_text(encoding="utf-8"))
    assert registry["sword-nonbinding-counsel.v1"] == "generic-object.schema.json"

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _literal_bracket_writes(variable: str) -> dict[str, set[str]]:
    pattern = re.compile(rf"\\b{re.escape(variable)}\\s*\\[\\s*['\"]([^'\"]+)['\"]\\s*\\]\\s*=")
    found: dict[str, set[str]] = {}
    for path in (ROOT / "runtime" / "sword_runtime").rglob("*.py"):
        text = path.read_text(errors="ignore")
        for match in pattern.finditer(text):
            found.setdefault(match.group(1), set()).add(str(path.relative_to(ROOT)))
    return found


def _schema_properties(filename: str) -> set[str]:
    return set(json.loads((ROOT / "game" / "schemas" / filename).read_text())["properties"])


def test_operation_literal_runtime_writes_are_registered_in_closed_schema():
    missing = set(_literal_bracket_writes("operation")) - _schema_properties("sword-operation.schema.json")
    assert not missing, f"runtime writes unregistered sword-operation keys: {sorted(missing)}"


def test_operational_battlefield_literal_runtime_writes_are_registered_in_closed_schema():
    missing = set(_literal_bracket_writes("battlefield")) - _schema_properties("sword-operational-battlefield.schema.json")
    assert not missing, f"runtime writes unregistered battlefield keys: {sorted(missing)}"


def test_formation_literal_runtime_writes_are_registered_in_closed_schema():
    missing = set(_literal_bracket_writes("formation")) - _schema_properties("sword-formation.schema.json")
    assert not missing, f"runtime writes unregistered formation keys: {sorted(missing)}"

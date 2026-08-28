from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from sword_runtime.static_records import load_doctrine_record

DOCTRINE_INDEX_PATH = "game/data/mil/doctrines.json"

def combat_doctrine_ref(person: Mapping[str, Any]) -> str:
    return str(person.get("combat_doctrine_ref", "") or "")

def load_personal_combat_doctrine(read_json: Callable[[str], Any], person: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve one current personal-combat doctrine by registered reference.

    Character state stores only the reference. Static tactics, targeting priorities
    and agency presentation rules live in game data and are not copied into every
    save record.
    """
    ref = combat_doctrine_ref(person)
    if not ref:
        return {}
    record = load_doctrine_record(read_json, ref)
    if not record:
        raise ValueError(f"unknown combat_doctrine_ref: {ref}")
    doctrine = record.get("doctrine", {})
    if not isinstance(doctrine, Mapping) or str(doctrine.get("domain", "")) != "personal_combat":
        raise ValueError(f"doctrine is not personal_combat: {ref}")
    return dict(doctrine)

__all__ = ["combat_doctrine_ref", "load_personal_combat_doctrine"]

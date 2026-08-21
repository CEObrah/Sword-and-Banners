from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Callable

LOADOUT_INDEX_PATH = "game/data/loadouts.json"
DOCTRINE_INDEX_PATH = "game/data/mil/doctrines.json"
TRAINING_INDEX_PATH = "game/data/mil/training.json"


def _route(index: Mapping[str, Any], ref: str, *, fallback_template_key: str | None = None) -> str | None:
    routes = index.get("record_index", {})
    if isinstance(routes, Mapping):
        path = routes.get(ref)
        if isinstance(path, str) and path:
            return path
    if fallback_template_key:
        template = index.get(fallback_template_key)
        if isinstance(template, str) and template:
            return template.replace("{loadout_id}", ref).replace("{doctrine_id}", ref).replace("{training_id}", ref)
    return None


def load_loadout(read_json: Callable[[str], Any], loadout_id: str) -> dict[str, Any]:
    """Resolve a logical loadout id through the canonical static routing index.

    Multiple logical role/faction loadout IDs may intentionally share one physical
    canonical record. The returned view keeps the caller's logical ID while the
    reusable equipment body exists only once on disk.
    """
    ref = str(loadout_id or "")
    if not ref:
        return {}
    index = read_json(LOADOUT_INDEX_PATH)
    if not isinstance(index, Mapping):
        return {}
    path = _route(index, ref, fallback_template_key="path_template")
    if not path:
        return {}
    record = read_json(path)
    row = record.get("loadout", {}) if isinstance(record, Mapping) else {}
    if not isinstance(row, Mapping):
        return {}
    out = copy.deepcopy(dict(row))
    out["id"] = ref
    return out


def load_doctrine_record(read_json: Callable[[str], Any], doctrine_ref: str) -> dict[str, Any]:
    ref = str(doctrine_ref or "")
    if not ref:
        return {}
    index = read_json(DOCTRINE_INDEX_PATH)
    if not isinstance(index, Mapping):
        return {}
    path = _route(index, ref)
    if not path:
        return {}
    record = read_json(path)
    if not isinstance(record, Mapping) or record.get("schema") != "doctrine-record":
        return {}
    out = copy.deepcopy(dict(record))
    out["id"] = ref
    return out


def load_training_record(read_json: Callable[[str], Any], training_ref: str) -> dict[str, Any]:
    ref = str(training_ref or "")
    if not ref:
        return {}
    index = read_json(TRAINING_INDEX_PATH)
    if not isinstance(index, Mapping):
        return {}
    path = _route(index, ref)
    if not path:
        return {}
    record = read_json(path)
    if not isinstance(record, Mapping) or record.get("schema") not in {"training-profile-record", "training-record"}:
        return {}
    out = copy.deepcopy(dict(record))
    out["id"] = ref
    profile = out.get("profile")
    if isinstance(profile, dict):
        profile["id"] = ref
    return out


__all__ = ["load_loadout", "load_doctrine_record", "load_training_record"]

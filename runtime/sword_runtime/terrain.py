"""Canonical layered terrain shared by travel, environment, battle, and battlefield."""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any, Callable

TERRAIN_RULES_PATH = "game/data/mechanics/terrain.json"
LOCATIONS_PATH = "game/data/world/locations.json"
_EFFECT_KEYS = (
    "travel_time_milli", "visibility_milli", "ranged_effectiveness_milli",
    "formation_mobility_milli", "mounted_mobility_milli", "chariot_mobility_milli",
    "frontage_milli", "concealment_milli", "scouting_milli", "pursuit_milli",
    "fatigue_milli", "defense_milli",
)

def _read(reader: Any, path: str) -> Mapping[str, Any]:
    # Terrain and static location blueprints are immutable game data. Cache them
    # per planner/read-owner so repeated pathfinding and battle-power evaluation
    # do not inflate long-horizon planning reads. Mutable geography remains under
    # its normal state owners and is never cached here.
    owner = getattr(reader, "__self__", reader)
    cache = getattr(owner, "_terrain_static_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        try:
            setattr(owner, "_terrain_static_cache", cache)
        except (AttributeError, TypeError):
            # Stateless/builtin readers may not permit cache attributes. This is
            # only an optimization boundary; real reader/data failures below
            # must still propagate instead of being swallowed.
            pass
    if path in cache:
        return cache[path]
    if hasattr(reader, "read_json"):
        value = reader.read_json(path)
    elif hasattr(reader, "read"):
        value = reader.read(path)
    elif callable(reader):
        value = reader(path)
    else:
        raise TypeError("terrain reader must provide read/read_json or be callable")
    if not isinstance(value, Mapping):
        raise ValueError(f"terrain source {path} must be an object")
    if path.startswith("game/"):
        cache[path] = value
    return value

def terrain_tags_for_label(reader: Any, label: str) -> tuple[str, ...]:
    rules = _read(reader, TERRAIN_RULES_PATH)
    aliases = rules.get("aliases") if isinstance(rules.get("aliases"), Mapping) else {}
    raw = aliases.get(str(label))
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"unregistered terrain label: {label}")
    return tuple(dict.fromkeys(str(x) for x in raw if isinstance(x, str) and x))

def _location_rows(reader: Any) -> dict[str, Mapping[str, Any]]:
    doc = _read(reader, LOCATIONS_PATH)
    rows = doc.get("locations", [])
    return {str(row.get("ref")): row for row in rows if isinstance(row, Mapping) and row.get("ref")}

def terrain_tags_for_location(reader: Any, location_ref: str) -> tuple[str, ...]:
    rows = _location_rows(reader)
    current = str(location_ref)
    seen: set[str] = set()
    row = rows.get(current, {})
    label = None
    while current in rows and current not in seen:
        seen.add(current); row = rows[current]
        if isinstance(row.get("terrain"), str) and row.get("terrain"):
            label = str(row["terrain"]); break
        parent = row.get("parent_ref")
        current = str(parent) if isinstance(parent, str) and parent.startswith("loc_") else ""
    tags = list(terrain_tags_for_label(reader, label or "default"))
    original = rows.get(str(location_ref), {})
    rules = _read(reader, TERRAIN_RULES_PATH)
    overlays = rules.get("location_kind_overlays") if isinstance(rules.get("location_kind_overlays"), Mapping) else {}
    kind = str(original.get("kind", ""))
    for tag in overlays.get(kind, []) if isinstance(overlays.get(kind), list) else []:
        if isinstance(tag, str) and tag not in tags: tags.append(tag)
    if bool(original.get("fortified")) and "fortified" not in tags:
        tags.append("fortified")
    for tag in original.get("terrain_overlays", []) if isinstance(original.get("terrain_overlays"), list) else []:
        if isinstance(tag, str) and tag not in tags: tags.append(tag)
    return tuple(tags)

def encode_terrain(tags: tuple[str, ...] | list[str]) -> str:
    values = [str(x) for x in tags if str(x)]
    return "+".join(dict.fromkeys(values)) or "plain"

def terrain_tokens(value: str | None) -> set[str]:
    if not value: return {"plain"}
    raw = {token for token in str(value).split("+") if token}
    mapped: set[str] = set()
    legacy = {
        "open":"plain", "field":"plain", "road":"plain",
        "forest":"woodland", "fort":"fortified", "fortress":"fortified",
        "city":"urban", "capital":"urban", "town":"urban", "estate":"urban", "hall":"urban",
    }
    for token in raw:
        mapped.add(legacy.get(token, token))
    return mapped or {"plain"}

def terrain_has(value: str | None, *tags: str) -> bool:
    tokens = terrain_tokens(value)
    return any(tag in tokens for tag in tags)


_PRIMARY_TERRAIN_PRIORITY = (
    "pass", "urban", "fortified", "mountain", "woodland", "marsh", "wetland",
    "hills", "floodplain", "steppe", "cultivated", "plain",
)

def primary_terrain_tag(value: str | tuple[str, ...] | list[str] | None) -> str:
    if isinstance(value, (tuple, list)):
        tokens = {str(x) for x in value if str(x)}
    else:
        tokens = terrain_tokens(value if isinstance(value, str) else None)
    for tag in _PRIMARY_TERRAIN_PRIORITY:
        if tag in tokens:
            return tag
    return sorted(tokens)[0] if tokens else "plain"

def terrain_effects_for_tags(reader: Any, tags: tuple[str, ...] | list[str]) -> dict[str, int]:
    # Terrain mechanics are immutable game data. Cache the fully-composed layered
    # profile per planner/read-owner rather than multiplying the same profiles for
    # every edge in every pathfinding query. Bare test/read callables remain
    # uncached, preserving overlay semantics.
    normalized = tuple(str(tag) for tag in tags)
    owner = getattr(reader, "__self__", None)
    cache = getattr(owner, "_terrain_effect_cache", None) if owner is not None else None
    if owner is not None and not isinstance(cache, dict):
        cache = {}
        setattr(owner, "_terrain_effect_cache", cache)
    if isinstance(cache, dict) and normalized in cache:
        return dict(cache[normalized])
    rules = _read(reader, TERRAIN_RULES_PATH)
    profiles = rules.get("profiles") if isinstance(rules.get("profiles"), Mapping) else {}
    result = {key: 1000 for key in _EFFECT_KEYS}
    for tag in tags:
        profile = profiles.get(str(tag))
        if not isinstance(profile, Mapping):
            raise ValueError(f"unregistered terrain profile: {tag}")
        for key in _EFFECT_KEYS:
            value = profile.get(key, 1000)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"invalid terrain effect {tag}.{key}")
            # Multiplicative stacking preserves layered terrain without arbitrary winner-take-all.
            result[key] = max(100, min(2500, result[key] * value // 1000))
    if isinstance(cache, dict):
        cache[normalized] = dict(result)
    return result

def terrain_context_for_location(reader: Any, location_ref: str) -> dict[str, Any]:
    tags = terrain_tags_for_location(reader, location_ref)
    return {"tags": list(tags), "primary": primary_terrain_tag(tags), "encoded": encode_terrain(tags), "mechanical_effects": terrain_effects_for_tags(reader, tags)}

def terrain_context_for_label(reader: Any, label: str) -> dict[str, Any]:
    owner = getattr(reader, "__self__", None)
    cache = getattr(owner, "_terrain_label_context_cache", None) if owner is not None else None
    if owner is not None and not isinstance(cache, dict):
        cache = {}
        setattr(owner, "_terrain_label_context_cache", cache)
    key = str(label)
    if isinstance(cache, dict) and key in cache:
        cached = cache[key]
        return {
            "tags": list(cached["tags"]),
            "primary": cached["primary"],
            "encoded": cached["encoded"],
            "mechanical_effects": dict(cached["mechanical_effects"]),
        }
    tags = terrain_tags_for_label(reader, key)
    result = {"tags": list(tags), "primary": primary_terrain_tag(tags), "encoded": encode_terrain(tags), "mechanical_effects": terrain_effects_for_tags(reader, tags)}
    if isinstance(cache, dict):
        cache[key] = {
            "tags": tuple(result["tags"]),
            "primary": result["primary"],
            "encoded": result["encoded"],
            "mechanical_effects": dict(result["mechanical_effects"]),
        }
    return result

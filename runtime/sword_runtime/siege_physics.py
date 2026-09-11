from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence


PHYSICAL_ASSAULT_METHODS = {
    "gate_entry",
    "breach_assault",
    "ladder_assault",
    "grapnel_swim_assault",
    "direct_assault_unfortified",
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _physical_baseline(profile: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = profile.get("physical_baseline")
    return raw if isinstance(raw, Mapping) else {}


def _outer_wall(profile: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = _physical_baseline(profile).get("outer_wall")
    return raw if isinstance(raw, Mapping) else {}


def physical_profile_enabled(profile: Mapping[str, Any]) -> bool:
    physics = profile.get("siege_physics")
    wall = _outer_wall(profile)
    return bool(isinstance(physics, Mapping) and physics) or bool(wall)


def _layer_geometry_from_enclosure(
    enclosure: Mapping[str, Any],
    *,
    integrity: int,
    fallback_wall: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    fort = enclosure.get("fortification") if isinstance(enclosure.get("fortification"), Mapping) else {}
    fallback = fallback_wall if isinstance(fallback_wall, Mapping) else {}
    perimeter_km = _number(
        fort.get("constructed_outer_perimeter_km", fort.get("outer_wall_length_built_cumulative_km")),
        _number(enclosure.get("constructed_wall_centerline_perimeter_km"), 0.0),
    )
    wall_height = _number(fort.get("wall_height_m"), _number(fallback.get("wall_height_m"), 0.0))
    moat_width = _number(fort.get("moat_width_m"), _number(fallback.get("moat_width_m"), 0.0))
    moat_depth = _number(fort.get("moat_depth_m"), _number(fallback.get("moat_depth_m"), 0.0))
    gate_count = max(0, int(fort.get("gate_count", fallback.get("external_strategic_gate_count", 0)) or 0))
    gate_station = _number(fallback.get("gate_station_m"), 0.0)
    if gate_station <= 0 and gate_count > 0 and perimeter_km > 0:
        gate_station = perimeter_km * 1000.0 / gate_count
    fixed_crossing = _number(fallback.get("fixed_crossing_length_m"), 0.0)
    moving_span = _number(fallback.get("lifting_drawbridge_span_m"), 0.0)
    total_crossing = _number(fallback.get("crossing_total_m"), fixed_crossing + moving_span)
    layer_ref = str(enclosure.get("enclosure_ref") or enclosure.get("layer_ref") or "outer_wall")
    gates: dict[str, Any] = {}
    if gate_count:
        # Gate count is physical capacity/geometry.  The resolver currently needs
        # only a strategic breach/entry target, so a representative main gate owns
        # the exact structural state while count remains explicit on the layer.
        gates["main_gate"] = {
            "gate_ref": "main_gate",
            "enclosure_ref": layer_ref,
            "gate_count": gate_count,
            "station_m": gate_station,
            "status": "closed",
            "structural_condition_percent": max(1, min(100, int(integrity))),
            "drawbridge_status": "raised" if moving_span > 0 else "not_applicable",
            "fixed_crossing_length_m": fixed_crossing,
            "lifting_span_m": moving_span,
            "crossing_total_m": total_crossing,
            "wheeled_engine_access": False if moving_span > 0 else moat_width <= 0,
            "personnel_access": False,
        }
    return {
        "enclosure_ref": layer_ref,
        "kind": str(enclosure.get("kind", "fortified_enclosure")),
        "nesting_depth": max(0, int(enclosure.get("nesting_depth", 0) or 0)),
        "area_km2": max(0.0, _number(enclosure.get("area_km2"), 0.0)),
        "protected_population_capacity": max(0, int(enclosure.get("protected_population_capacity", 0) or 0)),
        "secured_by_attacker": False,
        "perimeter": {
            "wall_ref": layer_ref,
            "centerline_perimeter_km": perimeter_km or None,
            "wall_height_m": wall_height or None,
            "base_thickness_m": _number(fort.get("wall_base_thickness_m"), _number(fallback.get("wall_base_thickness_m"), 0.0)) or None,
            "crown_thickness_m": _number(fort.get("wall_crown_thickness_m"), _number(fallback.get("wall_crown_thickness_m"), 0.0)) or None,
            "tower_count": max(0, int(fort.get("tower_count", fallback.get("tower_count", 0)) or 0)),
            "structural_condition_percent": max(1, min(100, int(integrity))),
        },
        "moat": {
            "width_m": moat_width,
            "depth_m": moat_depth,
            "crossings": [],
        },
        "gates": gates,
        "breaches": [],
        "attacker_footholds": [],
    }


def _project_active_layer(physical: dict[str, Any]) -> dict[str, Any]:
    layers = physical.get("enclosure_layers")
    if not isinstance(layers, list) or not layers:
        return physical
    idx = max(0, min(len(layers) - 1, int(physical.get("active_layer_index", 0) or 0)))
    layer = layers[idx]
    if not isinstance(layer, dict):
        return physical
    physical["active_layer_index"] = idx
    physical["active_layer_ref"] = str(layer.get("enclosure_ref", f"layer_{idx}"))
    for key in ("perimeter", "moat", "gates", "breaches", "attacker_footholds"):
        physical[key] = deepcopy(layer.get(key, {} if key in {"perimeter", "moat", "gates"} else []))
    return physical


def commit_active_layer_projection(physical: dict[str, Any]) -> dict[str, Any]:
    """Persist the backward-compatible active projection into its enclosure layer."""
    layers = physical.get("enclosure_layers")
    if not isinstance(layers, list) or not layers:
        return physical
    idx = max(0, min(len(layers) - 1, int(physical.get("active_layer_index", 0) or 0)))
    layer = layers[idx]
    if not isinstance(layer, dict):
        return physical
    for key in ("perimeter", "moat", "gates", "breaches", "attacker_footholds"):
        layer[key] = deepcopy(physical.get(key, {} if key in {"perimeter", "moat", "gates"} else []))
    layers[idx] = layer
    physical["enclosure_layers"] = layers
    return physical


def active_enclosure_ref(fort: Mapping[str, Any]) -> str:
    physical = ensure_physical_state(fort)
    return str(physical.get("active_layer_ref") or (physical.get("perimeter") or {}).get("wall_ref") or "outer_wall")


def advance_enclosure_layer(physical: dict[str, Any], *, at: str, battle_ref: str) -> dict[str, Any]:
    """Secure the current enclosure and expose the next nested defensive layer.

    A full-garrison assault victory may call this once.  It never skips a layer.
    Surviving defenders therefore remain available to defend the next enclosure.
    """
    commit_active_layer_projection(physical)
    layers = physical.get("enclosure_layers")
    if not isinstance(layers, list) or not layers:
        return {"advanced": False, "final_layer_secured": True, "active_layer_ref": physical.get("active_layer_ref")}
    idx = max(0, min(len(layers) - 1, int(physical.get("active_layer_index", 0) or 0)))
    layer = layers[idx]
    if isinstance(layer, dict):
        layer["secured_by_attacker"] = True
        layer["secured_at"] = at
        layer["secured_battle_ref"] = battle_ref
        layers[idx] = layer
    if idx + 1 >= len(layers):
        physical["enclosure_layers"] = layers
        return {
            "advanced": False,
            "final_layer_secured": True,
            "secured_layer_ref": str(layer.get("enclosure_ref", "")) if isinstance(layer, Mapping) else "",
            "active_layer_ref": physical.get("active_layer_ref"),
        }
    old_ref = str(layer.get("enclosure_ref", "")) if isinstance(layer, Mapping) else ""
    physical["enclosure_layers"] = layers
    physical["active_layer_index"] = idx + 1
    _project_active_layer(physical)
    return {
        "advanced": True,
        "final_layer_secured": False,
        "secured_layer_ref": old_ref,
        "active_layer_ref": str(physical.get("active_layer_ref", "")),
        "remaining_layers": len(layers) - (idx + 1),
    }


def materialize_physical_state(profile: Mapping[str, Any], *, integrity: int = 100) -> dict[str, Any]:
    """Build persistent physical siege state from a cold fortification blueprint.

    Nested enclosure geometry is materialized outer-to-inner.  Top-level perimeter,
    moat, gate, breach and foothold fields remain a projection of the active layer
    so older access code has one writable surface without flattening the fortress.
    """
    baseline = _physical_baseline(profile)
    wall = _outer_wall(profile)
    physics = profile.get("siege_physics") if isinstance(profile.get("siege_physics"), Mapping) else {}
    route_refs = [str(x) for x in profile.get("route_control_refs", []) if isinstance(x, str)]
    explicit = profile.get("current_enclosure_layers")
    layers: list[dict[str, Any]] = []
    if isinstance(explicit, Sequence) and not isinstance(explicit, (str, bytes)):
        raw_layers = [x for x in explicit if isinstance(x, Mapping) and bool((x.get("fortification") or {}).get("active", True))]
        raw_layers.sort(key=lambda x: (max(0, int(x.get("nesting_depth", 0) or 0)), str(x.get("enclosure_ref", ""))))
        for i, enclosure in enumerate(raw_layers):
            layers.append(_layer_geometry_from_enclosure(enclosure, integrity=integrity, fallback_wall=wall if i == 0 else None))
    if not layers:
        synthetic = {
            "enclosure_ref": "outer_wall",
            "kind": "outer_wall",
            "nesting_depth": 0,
            "area_km2": _number(baseline.get("enclosed_area_km2"), 0.0),
            "protected_population_capacity": 0,
            "fortification": {
                "constructed_outer_perimeter_km": _number(baseline.get("constructed_wall_centerline_perimeter_km"), 0.0),
                "wall_height_m": _number(wall.get("wall_height_m"), 0.0),
                "wall_base_thickness_m": _number(wall.get("wall_base_thickness_m"), 0.0),
                "wall_crown_thickness_m": _number(wall.get("wall_crown_thickness_m"), 0.0),
                "moat_width_m": _number(wall.get("moat_width_m"), 0.0),
                "moat_depth_m": _number(wall.get("moat_depth_m"), 0.0),
                "gate_count": max(0, int(wall.get("external_strategic_gate_count", 0) or 0)),
                "tower_count": max(0, int(wall.get("tower_count", 0) or 0)),
            },
        }
        layers = [_layer_geometry_from_enclosure(synthetic, integrity=integrity, fallback_wall=wall)]
    state = {
        "authority": True,
        "model": "nested_exact_enclosures" if len(layers) > 1 else ("exact_perimeter" if physical_profile_enabled(profile) else "qualitative_fortification"),
        "blueprint_profile_id": profile.get("profile_id"),
        "enclosure_layers": layers,
        "active_layer_index": 0,
        "active_layer_ref": str(layers[0].get("enclosure_ref", "outer_wall")),
        "route_control_refs": route_refs,
        "blocked_route_refs": [],
        "siege_physics": deepcopy(dict(physics)),
    }
    # Crossing requirements remain universal even when individual enclosure rows
    # do not duplicate the static rule flag.
    for layer in layers:
        if isinstance(layer.get("moat"), dict):
            layer["moat"]["required_for_wheeled_engines"] = bool(physics.get("moat_required_crossing_for_wheeled_engines", False))
    return _project_active_layer(state)


def ensure_physical_state(fort: Mapping[str, Any]) -> dict[str, Any]:
    state = fort.get("physical_state")
    if isinstance(state, Mapping):
        out = deepcopy(dict(state))
        # An already-layered owner keeps its current writable projection coherent.
        if isinstance(out.get("enclosure_layers"), list) and out.get("enclosure_layers"):
            commit_active_layer_projection(out)
            _project_active_layer(out)
        return out
    profile = fort.get("profile") if isinstance(fort.get("profile"), Mapping) else {}
    return materialize_physical_state(profile, integrity=int(fort.get("integrity", 100)))


def compatible_crossing(physical: Mapping[str, Any], crossing_ref: str | None, *, wheeled: bool) -> Mapping[str, Any] | None:
    if not crossing_ref:
        return None
    moat = physical.get("moat") if isinstance(physical.get("moat"), Mapping) else {}
    for raw in moat.get("crossings", []) if isinstance(moat.get("crossings"), Sequence) else []:
        if not isinstance(raw, Mapping) or str(raw.get("crossing_ref")) != str(crossing_ref):
            continue
        if str(raw.get("status", "usable")) != "usable":
            return None
        if wheeled and not bool(raw.get("wheeled_engine_access", False)):
            return None
        if not wheeled and not bool(raw.get("personnel_access", True)):
            return None
        return raw
    return None


def _main_gate(physical: Mapping[str, Any], target_ref: str | None) -> Mapping[str, Any] | None:
    gates = physical.get("gates") if isinstance(physical.get("gates"), Mapping) else {}
    if target_ref and str(target_ref) in gates:
        raw = gates[str(target_ref)]
        return raw if isinstance(raw, Mapping) else None
    if "main_gate" in gates and isinstance(gates["main_gate"], Mapping):
        return gates["main_gate"]
    return None


def _breach(physical: Mapping[str, Any], target_ref: str | None) -> Mapping[str, Any] | None:
    if not target_ref:
        return None
    for raw in physical.get("breaches", []) if isinstance(physical.get("breaches"), Sequence) else []:
        if isinstance(raw, Mapping) and str(raw.get("breach_ref")) == str(target_ref) and str(raw.get("status", "open")) == "open":
            return raw
    return None


def validate_assault_access(
    fort: Mapping[str, Any],
    *,
    method: str | None,
    target_ref: str | None = None,
    engineering_item: Mapping[str, Any] | None = None,
    crossing_ref: str | None = None,
) -> dict[str, Any]:
    """Validate physical access before a troop battle is allowed to resolve."""
    profile = fort.get("profile") if isinstance(fort.get("profile"), Mapping) else {}
    physical = ensure_physical_state(fort)
    physical_enabled = physical_profile_enabled(profile)
    chosen = str(method or "")
    if not chosen:
        if physical_enabled:
            raise ValueError("physical fortification assault requires an explicit assault_method")
        chosen = "direct_assault_unfortified"
    if chosen not in PHYSICAL_ASSAULT_METHODS:
        raise ValueError("unsupported physical siege assault method")
    if chosen == "direct_assault_unfortified":
        if physical_enabled:
            raise ValueError("direct unfortified assault cannot bypass an exact physical fortification profile")
        return {"method": chosen, "target_ref": target_ref, "entry_kind": "direct_contact", "physical_state": physical}

    moat = physical.get("moat") if isinstance(physical.get("moat"), Mapping) else {}
    physics = physical.get("siege_physics") if isinstance(physical.get("siege_physics"), Mapping) else {}
    moat_exists = _number(moat.get("width_m"), 0.0) > 0

    if chosen == "gate_entry":
        gate = _main_gate(physical, target_ref)
        if not gate:
            raise ValueError("gate assault target is not an exact materialized gate")
        if str(gate.get("status", "closed")) not in {"open", "breached", "destroyed"}:
            raise ValueError("physical access blocked: the target gate is closed and intact")
        if moat_exists:
            if not bool(gate.get("personnel_access", False)) and compatible_crossing(physical, crossing_ref, wheeled=False) is None:
                raise ValueError("physical access blocked: the moat has no usable personnel crossing to the gate")
        return {"method": chosen, "target_ref": str(gate.get("gate_ref", target_ref or "main_gate")), "entry_kind": "gate", "physical_state": physical}

    if chosen == "breach_assault":
        breach = _breach(physical, target_ref)
        if not breach:
            raise ValueError("physical access blocked: breach assault requires an exact persistent open breach")
        width = _number(breach.get("width_m"), 0.0)
        if width <= 0:
            raise ValueError("physical access blocked: breach has no usable width")
        if moat_exists and compatible_crossing(physical, crossing_ref, wheeled=False) is None and not bool(breach.get("moat_bypassed", False)):
            raise ValueError("physical access blocked: the wall breach is still separated by the moat")
        return {"method": chosen, "target_ref": str(breach.get("breach_ref")), "entry_kind": "breach", "entry_width_m": width, "physical_state": physical}

    if chosen == "ladder_assault":
        if not isinstance(engineering_item, Mapping):
            raise ValueError("ladder assault requires an exact registered engineering_item_ref")
        wall_height = _number((physical.get("perimeter") or {}).get("wall_height_m"), 0.0)
        ladder_reach = _number(engineering_item.get("wall_reach_m"), 0.0)
        if wall_height <= 0:
            raise ValueError("ladder assault requires exact wall height geometry")
        if ladder_reach < wall_height:
            raise ValueError(f"ladder cannot reach wall crest: {ladder_reach:g} m reach versus {wall_height:g} m wall")
        if moat_exists and bool(physics.get("wall_assault_requires_moat_crossing_or_waterborne_access", False)):
            if compatible_crossing(physical, crossing_ref, wheeled=False) is None:
                raise ValueError("physical access blocked: ladder assault has no personnel crossing over the moat")
        return {"method": chosen, "target_ref": target_ref or "outer_wall", "entry_kind": "ladder", "wall_height_m": wall_height, "ladder_reach_m": ladder_reach, "physical_state": physical}

    if chosen == "grapnel_swim_assault":
        if not bool(physics.get("grapnel_and_swim_access_possible", False)):
            raise ValueError("this fortification does not permit a registered grapnel/swim assault path")
        return {
            "method": chosen,
            "target_ref": target_ref or "outer_wall",
            "entry_kind": "grapnel_swim",
            "wheeled_engine_access_created": False,
            "physical_state": physical,
        }

    raise ValueError("unsupported physical siege assault method")


def register_attacker_foothold(physical: dict[str, Any], *, method: str, target_ref: str, at: str, battle_ref: str) -> dict[str, Any]:
    rows = physical.setdefault("attacker_footholds", [])
    ref = f"foothold:{battle_ref}"
    rows.append({
        "foothold_ref": ref,
        "method": method,
        "target_ref": target_ref,
        "established_at": at,
        "battle_ref": battle_ref,
        "status": "held",
        "wheeled_engine_access": False,
    })
    physical["attacker_footholds"] = rows[-64:]
    return physical


def blockade_coverage(fort: Mapping[str, Any], requested_route_refs: Sequence[str]) -> dict[str, Any]:
    physical = ensure_physical_state(fort)
    relevant = [str(x) for x in physical.get("route_control_refs", []) if isinstance(x, str)]
    requested = sorted({str(x) for x in requested_route_refs if isinstance(x, str)})
    unknown = [x for x in requested if x not in relevant]
    if unknown:
        raise ValueError("blockade route is not an exact access route controlled by this fortification")
    if relevant and not requested:
        raise ValueError("physical blockade requires explicit approach_route_refs")
    covered = [x for x in relevant if x in requested]
    fraction = 1.0 if not relevant else len(covered) / max(1, len(relevant))
    physical["blocked_route_refs"] = covered
    return {
        "physical_state": physical,
        "relevant_route_refs": relevant,
        "blocked_route_refs": covered,
        "open_route_refs": [x for x in relevant if x not in covered],
        "coverage_basis_points": int(round(fraction * 10000)),
        "fully_invested": bool(not relevant or len(covered) == len(relevant)),
    }

# ---------------------------------------------------------------------------
# Executable engineering-work helpers. These extend the surviving physical
# access model above without replacing its state contract.


def engineering_blueprints(read):
    doc = read("game/data/mechanics/siege-engineering-blueprints.json")
    rows = doc.get("blueprints", {}) if isinstance(doc, Mapping) else {}
    return rows if isinstance(rows, Mapping) else {}


def initial_physical_state(profile: Mapping[str, Any], integrity: int = 100) -> dict[str, Any]:
    return materialize_physical_state(profile, integrity=integrity)


def sync_integrity_projection(fort: dict[str, Any]) -> None:
    physical = fort.get("physical_state")
    if not isinstance(physical, Mapping):
        return
    values: list[float] = []
    perimeter = physical.get("perimeter") if isinstance(physical.get("perimeter"), Mapping) else {}
    if perimeter.get("structural_condition_percent") is not None:
        values.append(_number(perimeter.get("structural_condition_percent"), 100.0))
    gates = physical.get("gates") if isinstance(physical.get("gates"), Mapping) else {}
    for gate in gates.values():
        if isinstance(gate, Mapping) and gate.get("structural_condition_percent") is not None:
            values.append(_number(gate.get("structural_condition_percent"), 100.0))
    if values:
        fort["integrity"] = max(0, min(100, int(round(min(values)))))
        fort["integrity_projection_only"] = True


def _serviceable_works(
    siege: Mapping[str, Any],
    *,
    kind: str | None = None,
    target: str | None = None,
    enclosure_ref: str | None = None,
):
    rows = siege.get("engineering_works", []) if isinstance(siege.get("engineering_works"), Sequence) else []
    for work in rows:
        if not isinstance(work, Mapping) or str(work.get("status", "serviceable")) != "serviceable":
            continue
        if kind is not None and str(work.get("kind")) != kind:
            continue
        if target is not None and str(work.get("target")) != target:
            continue
        if enclosure_ref is not None:
            work_layer = str(work.get("enclosure_ref", ""))
            # Old/single-layer works without an explicit scope belong to the first
            # active enclosure only and cannot teleport through a captured wall.
            if work_layer and work_layer != str(enclosure_ref):
                continue
            if not work_layer and str(enclosure_ref) not in {"", "outer_wall"}:
                continue
        yield work


def completed_crossing_length(siege: Mapping[str, Any], target: str, *, enclosure_ref: str | None = None) -> float:
    return sum(
        max(0.0, _number(work.get("effective_length_m"), 0.0))
        for work in _serviceable_works(siege, kind="crossing", target=target, enclosure_ref=enclosure_ref)
    )


def required_crossing_length(fort: Mapping[str, Any], target: str) -> float:
    physical = ensure_physical_state(fort)
    moat = physical.get("moat") if isinstance(physical.get("moat"), Mapping) else {}
    moat_width = max(0.0, _number(moat.get("width_m"), 0.0))
    if target == "gate":
        gate = _main_gate(physical, "main_gate")
        if isinstance(gate, Mapping):
            moving = max(0.0, _number(gate.get("lifting_span_m"), 0.0))
            if moving > 0:
                return moving
    return moat_width


def _access_with_synthetic_crossing(fort: Mapping[str, Any], siege: Mapping[str, Any], target: str) -> tuple[dict[str, Any], str | None, float, float]:
    physical = ensure_physical_state(fort)
    required = required_crossing_length(fort, target)
    layer_ref = active_enclosure_ref(fort)
    completed = completed_crossing_length(siege, target, enclosure_ref=layer_ref)
    if required <= 0 or completed + 1e-9 >= required:
        crossing_ref = f"siege_crossing:{target}"
        moat = physical.setdefault("moat", {})
        crossings = list(moat.get("crossings", [])) if isinstance(moat.get("crossings"), Sequence) else []
        crossings = [x for x in crossings if not (isinstance(x, Mapping) and str(x.get("crossing_ref")) == crossing_ref)]
        crossings.append({
            "crossing_ref": crossing_ref,
            "status": "usable",
            "span_m": completed,
            "personnel_access": True,
            "wheeled_engine_access": True,
        })
        moat["crossings"] = crossings
        return physical, crossing_ref, required, completed
    return physical, None, required, completed


def assault_access(fort: Mapping[str, Any], siege: Mapping[str, Any], target: str, method: str) -> dict[str, Any]:
    profile = fort.get("profile") if isinstance(fort.get("profile"), Mapping) else {}
    if not physical_profile_enabled(profile):
        result = validate_assault_access(fort, method="direct_assault_unfortified", target_ref=target)
        return {"admissible": True, "access_class": "qualitative_existing_access", **result}

    physical, crossing_ref, required, completed = _access_with_synthetic_crossing(fort, siege, target)
    layer_ref = str(physical.get("active_layer_ref") or (physical.get("perimeter") or {}).get("wall_ref") or "outer_wall")
    probe_fort = dict(fort)
    probe_fort["physical_state"] = physical
    wall_height = _number((physical.get("perimeter") or {}).get("wall_height_m"), 0.0)

    if target == "gate":
        try:
            result = validate_assault_access(probe_fort, method="gate_entry", target_ref="main_gate", crossing_ref=crossing_ref)
        except ValueError as exc:
            return {"admissible": False, "reason": str(exc), "required_crossing_m": required, "completed_crossing_m": completed}
        gate = _main_gate(physical, "main_gate")
        access_class = "gate_breach" if isinstance(gate, Mapping) and str(gate.get("status")) in {"breached", "destroyed"} else "open_gate"
        return {"admissible": True, "access_class": access_class, "crossing_length_m": completed, **result}

    if method == "breach":
        breaches = [x for x in physical.get("breaches", []) if isinstance(x, Mapping) and str(x.get("status", "open")) == "open" and str(x.get("target_kind", "wall")) == "wall"]
        if not breaches:
            return {"admissible": False, "reason": "physical access blocked: no exact persistent wall breach exists"}
        breach = breaches[0]
        if required > 0 and crossing_ref is None and not bool(breach.get("moat_bypassed", False)):
            return {"admissible": False, "reason": "physical access blocked: the wall breach is still separated by the moat", "required_crossing_m": required, "completed_crossing_m": completed}
        result = validate_assault_access(probe_fort, method="breach_assault", target_ref=str(breach.get("breach_ref")), crossing_ref=crossing_ref)
        return {"admissible": True, "access_class": "wall_breach", "breach_width_m": _number(breach.get("width_m"), 0.0), "crossing_length_m": completed, **result}

    if method == "ladder":
        if required > 0 and crossing_ref is None:
            return {"admissible": False, "reason": "physical access blocked: ladder assault has no personnel crossing over the moat", "required_crossing_m": required, "completed_crossing_m": completed}
        ladders = [w for w in _serviceable_works(siege, kind="assault_ladder", target="wall", enclosure_ref=layer_ref) if _number(w.get("safe_wall_height_m"), 0.0) + 1e-9 >= wall_height]
        if not ladders:
            return {"admissible": False, "reason": f"no serviceable registered ladder can safely reach the {wall_height:g} m wall height", "wall_height_m": wall_height}
        best = max(ladders, key=lambda w: _number(w.get("safe_wall_height_m"), 0.0))
        result = validate_assault_access(probe_fort, method="ladder_assault", target_ref=layer_ref, engineering_item={"wall_reach_m": _number(best.get("safe_wall_height_m"), 0.0)}, crossing_ref=crossing_ref)
        return {"admissible": True, "access_class": "ladder_escalade", "work_refs": [str(w.get("work_ref")) for w in ladders], **result}

    if method == "siege_tower":
        if required > 0 and crossing_ref is None:
            return {"admissible": False, "reason": "physical access blocked: wheeled siege tower has no load-bearing crossing over the moat", "required_crossing_m": required, "completed_crossing_m": completed}
        towers = [w for w in _serviceable_works(siege, kind="siege_tower", target="wall", enclosure_ref=layer_ref) if _number(w.get("max_wall_height_m"), 0.0) + 1e-9 >= wall_height]
        if not towers:
            return {"admissible": False, "reason": f"no serviceable registered siege tower reaches the {wall_height:g} m wall", "wall_height_m": wall_height}
        return {"admissible": True, "access_class": "siege_tower_bridge", "work_refs": [str(w.get("work_ref")) for w in towers], "crossing_length_m": completed}

    if method == "swim_grapnel":
        hooks = [w for w in _serviceable_works(siege, kind="grapnel_rope", target="wall", enclosure_ref=layer_ref) if _number(w.get("rope_length_m"), 0.0) + 1e-9 >= wall_height]
        if not hooks:
            return {"admissible": False, "reason": f"swim/grapnel assault requires a serviceable registered rope long enough for the {wall_height:g} m wall", "wall_height_m": wall_height}
        result = validate_assault_access(probe_fort, method="grapnel_swim_assault", target_ref=layer_ref)
        return {"admissible": True, "access_class": "swim_grapnel_escalade", "wheeled_engine_access": False, "work_refs": [str(w.get("work_ref")) for w in hooks], **result}

    return {"admissible": False, "reason": "exact wall assault requires breach, ladder, siege tower, or swim/grapnel access"}


def ram_access(fort: Mapping[str, Any], siege: Mapping[str, Any]) -> dict[str, Any]:
    profile = fort.get("profile") if isinstance(fort.get("profile"), Mapping) else {}
    if not physical_profile_enabled(profile):
        return {"admissible": True, "access_class": "qualitative_gate_approach"}
    required = required_crossing_length(fort, "gate")
    layer_ref = active_enclosure_ref(fort)
    completed = completed_crossing_length(siege, "gate", enclosure_ref=layer_ref)
    if completed + 1e-9 < required:
        return {"admissible": False, "reason": "ram is wheeled and cannot reach gate across unresolved moat/drawbridge gap", "required_crossing_m": required, "completed_crossing_m": completed}
    rams = list(_serviceable_works(siege, kind="battering_ram", target="gate", enclosure_ref=layer_ref))
    if not rams:
        return {"admissible": False, "reason": "no serviceable registered battering ram exists at the gate approach"}
    return {"admissible": True, "access_class": "ram_gate_contact", "work_refs": [str(w.get("work_ref")) for w in rams], "crossing_length_m": completed}


def work_record(blueprint_ref: str, blueprint: Mapping[str, Any], *, work_ref: str, target: str, quantity: int, at: str, source_formation_ref: str, materials: Mapping[str, Any]) -> dict[str, Any]:
    record = {
        "work_ref": work_ref,
        "blueprint_ref": blueprint_ref,
        "kind": str(blueprint.get("kind", "work")),
        "target": target,
        "quantity": int(quantity),
        "status": "serviceable",
        "completed_at": at,
        "source_formation_ref": source_formation_ref,
        "materials_consumed": {str(k): float(v) for k, v in materials.items()},
    }
    for field in ("safe_wall_height_m", "rope_length_m", "max_wall_height_m", "base_impact_index", "base_cycle_seconds"):
        if field in blueprint:
            record[field] = _number(blueprint.get(field), 0.0)
    if record["kind"] == "crossing":
        record["effective_length_m"] = _number(blueprint.get("length_m"), 0.0) * int(quantity)
        record["usable_width_m"] = _number(blueprint.get("usable_width_m"), 0.0)
        record["load_class"] = str(blueprint.get("load_class", "foot"))
    return record


def work_materials(blueprint: Mapping[str, Any], quantity: int) -> dict[str, float]:
    raw = blueprint.get("materials") if isinstance(blueprint.get("materials"), Mapping) else {}
    return {str(k): max(0.0, _number(v, 0.0)) * int(quantity) for k, v in raw.items()}


def build_hours(
    blueprint: Mapping[str, Any],
    quantity: int,
    available_personnel: int,
    *,
    labor_efficiency: float = 1.0,
) -> int:
    import math
    labor = max(1.0, _number(blueprint.get("labor_hours"), 1.0)) * int(quantity)
    crew_min = max(1, int(blueprint.get("crew_min", 1)))
    crew_opt = max(crew_min, int(blueprint.get("crew_optimal", crew_min)))
    crew = min(max(0, int(available_personnel)), crew_opt)
    if crew < crew_min:
        raise ValueError(f"siege work requires at least {crew_min} available personnel; only {crew} supplied")
    efficiency = max(0.05, float(labor_efficiency))
    return max(1, int(math.ceil(labor / (crew * efficiency))))


def apply_ram_damage(fort: dict[str, Any], impact_index: float, cycles: int) -> dict[str, Any]:
    import math
    physical = ensure_physical_state(fort)
    gates = physical.get("gates") if isinstance(physical.get("gates"), Mapping) else {}
    gate = gates.get("main_gate") if isinstance(gates.get("main_gate"), Mapping) else None
    if not isinstance(gate, dict):
        damage = max(1.0, min(20.0, float(impact_index) * max(1, int(cycles)) / 120.0))
        fort["integrity"] = max(0, int(round(float(fort.get("integrity", 100)) - damage)))
        return {"target": "fortification_integrity", "integrity_loss_pct": damage, "breach_width_m": 0.0}
    perimeter = physical.get("perimeter") if isinstance(physical.get("perimeter"), Mapping) else {}
    crown = max(0.5, _number(perimeter.get("crown_thickness_m"), 1.0))
    protection = max(1.0, 55.0 * math.sqrt(crown * 0.35))
    ratio = max(0.0, float(impact_index)) / protection
    per_cycle = min(6.0, 1.35 * (ratio ** 1.25))
    before = _number(gate.get("structural_condition_percent"), 100.0)
    damage = min(before, per_cycle * max(1, int(cycles)))
    remaining = max(0.0, before - damage)
    gate["structural_condition_percent"] = remaining
    breach_width = _number(gate.get("breach_width_m"), 0.0)
    if remaining <= 20.0:
        breach_width = max(breach_width, min(8.0, 1.5 + (20.0 - remaining) * 0.325))
        gate["breach_width_m"] = breach_width
        gate["status"] = "breached"
        breach_ref = "breach:main_gate"
        breaches = [x for x in physical.get("breaches", []) if not (isinstance(x, Mapping) and str(x.get("breach_ref")) == breach_ref)]
        breaches.append({"breach_ref": breach_ref, "target_kind": "gate", "target_ref": "main_gate", "width_m": breach_width, "status": "open", "moat_bypassed": False})
        physical["breaches"] = breaches
    commit_active_layer_projection(physical)
    fort["physical_state"] = physical
    sync_integrity_projection(fort)
    return {"target": "gate", "integrity_loss_pct": round(damage, 3), "remaining_integrity_pct": round(remaining, 3), "breach_width_m": round(breach_width, 3)}

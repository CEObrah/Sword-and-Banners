"""Bounded operational bridges for multi-front interstate war.

This module does not own a second warfare simulation. It connects the existing
strategic-plan owner to exact route admission, fortified-site/siege owners, and
already-conserved formations. Strategic review may retask intact command groups,
but never creates manpower, bypasses physical fortifications, or settles a war
merely because one local battle ended.
"""
from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Mapping
from typing import Any

from sword_runtime.geography import enclosing_fortification_site, shortest_path
from sword_runtime.fortification_routing import iter_exact_fortification_records
from sword_runtime.siege_physics import (
    active_enclosure_ref,
    advance_enclosure_layer,
    apply_ram_damage,
    commit_active_layer_projection,
    engineering_blueprints,
    ensure_physical_state,
    initial_physical_state,
    register_attacker_foothold,
    ram_access,
    required_crossing_length,
    sync_integrity_projection,
    work_materials,
    work_record,
)
from sword_runtime.support_tasks import blueprint_difficulty, task_efficiency, temporary_duty_personnel


def _profile_for_site(planner: Any, site_ref: str) -> Mapping[str, Any] | None:
    doc = planner.read("game/data/world/fortification-profiles.json")
    for row in doc.get("profiles", []) if isinstance(doc, Mapping) else []:
        if isinstance(row, Mapping) and str(row.get("site_ref", "")) == str(site_ref):
            return row
    return None


def fortified_site_profile(planner: Any, site_ref: str) -> Mapping[str, Any] | None:
    """Return the registered physical fortification profile for an exact site."""
    return _profile_for_site(planner, str(site_ref))


def first_hostile_route_blocker(planner: Any, formation: Mapping[str, Any], destination_ref: str, at: str) -> dict[str, Any] | None:
    """Identify the first exact fort/pass/city preventing an otherwise physical route.

    This is called only after lawful formation routing failed. It intentionally
    plans one physical route without sovereignty admission, then asks the same
    transit validators which edge/node prevents movement. The returned site is an
    obstacle to reduce, screen, or route around; it is not automatically captured.
    """
    origin = str(formation.get("location_ref", ""))
    destination_ref = str(destination_ref)
    if not origin or not destination_ref or origin == destination_ref:
        return None
    try:
        plan = shortest_path(planner.read, origin, destination_ref, modes=("formation",))
    except ValueError:
        return None
    route_rows = {
        str(row.get("ref")): row
        for row in planner.read("game/data/world/routes.json").get("routes", [])
        if isinstance(row, Mapping) and row.get("ref")
    }
    path = [str(x) for x in plan.get("path", [])]
    refs = [str(x) for x in plan.get("route_refs", [])]
    for idx, route_ref in enumerate(refs):
        if idx + 1 >= len(path):
            break
        edge_origin, nxt = path[idx], path[idx + 1]
        route = route_rows.get(route_ref, {})
        try:
            if hasattr(planner, "_validate_formation_transit"):
                planner._validate_formation_transit(formation, nxt, at)
            if hasattr(planner, "_validate_formation_route_edge"):
                planner._validate_formation_route_edge(formation, edge_origin, nxt, route, at)
        except PermissionError as exc:
            blocker = str(route.get("control_site_ref", ""))
            if not blocker:
                candidate = enclosing_fortification_site(planner.read, nxt)
                blocker = str(candidate or nxt)
            profile = _profile_for_site(planner, blocker)
            return {
                "blocking_site_ref": blocker,
                "route_ref": route_ref,
                "edge_origin_ref": edge_origin,
                "edge_destination_ref": nxt,
                "fortified": bool(profile),
                "reason": str(exc),
            }
    return None


def _fortification_for_site(planner: Any, site_ref: str) -> tuple[str, str, dict[str, Any]] | None:
    for ref, path, row in iter_exact_fortification_records(planner):
        if str(row.get("site_ref") or row.get("location_ref") or "") == str(site_ref):
            return str(ref), path, copy.deepcopy(dict(row))
    return None


def _physical_formations_at_site(planner: Any, refs: list[str], site_ref: str) -> list[str]:
    out: list[str] = []
    for ref in refs:
        try:
            _path, formation = planner._load_formation(str(ref))
        except ValueError:
            continue
        if int(formation.get("personnel", 0)) <= 0:
            continue
        loc = str(formation.get("location_ref", ""))
        contact = enclosing_fortification_site(planner.read, loc) or loc
        if str(contact) == str(site_ref):
            out.append(str(ref))
    return sorted(set(out))


def ensure_autonomous_siege(
    planner: Any,
    *,
    theater_ref: str,
    front: dict[str, Any],
    site_ref: str,
    attacker_refs: list[str],
    defender_refs: list[str],
    attacker_side: str,
    defender_side: str,
    at: str,
) -> dict[str, Any] | None:
    """Materialize/reuse exact fortification and siege owners for a strategic front."""
    profile = _profile_for_site(planner, site_ref)
    if not isinstance(profile, Mapping):
        return None
    existing = _fortification_for_site(planner, site_ref)
    garrisons = _physical_formations_at_site(planner, defender_refs, site_ref)
    try:
        static = planner.read("state/fortifications/index.json").get("static_profiles", {}).get(site_ref, {})
        for ref in static.get("garrison_formation_refs", []) if isinstance(static, Mapping) else []:
            if str(ref) not in garrisons and _physical_formations_at_site(planner, [str(ref)], site_ref):
                garrisons.append(str(ref))
    except (KeyError, ValueError, FileNotFoundError):
        pass
    if existing is None:
        fort_ref = "fort_auto_" + hashlib.sha256(str(site_ref).encode()).hexdigest()[:18]
        fort_path = f"state/fortifications/{fort_ref}.json"
        depot_projection = None
        if hasattr(planner, "_fortified_site_runtime_records"):
            _dp, depot_projection, _ap, _art = planner._fortified_site_runtime_records(site_ref, at=at)
        projected_food = int(((depot_projection or {}).get("stocks") or {}).get("grain_kg", 0))
        fort = {
            "schema": "sword-fortification", "owner_id": fort_ref, "fortification_ref": fort_ref,
            "site_ref": site_ref, "location_ref": site_ref, "profile": copy.deepcopy(dict(profile)),
            "integrity": 100, "physical_state": initial_physical_state(profile, 100),
            "garrison_formation_refs": sorted(set(garrisons)), "food_kg": projected_food,
            "food_projection_only": True,
            "fortified_site_depot_ref": str((depot_projection or {}).get("owner_id", "")),
            "state": str(defender_side).removeprefix("state_"), "materialized_at": at,
            "materialization_basis": "autonomous_interstate_siege_contact",
        }
        sync_integrity_projection(fort)
        planner.put(fort_path, fort)
        idx = copy.deepcopy(planner.read("state/fortifications/index.json")); idx.setdefault("fortifications", {})[fort_ref] = fort_path; planner.put("state/fortifications/index.json", idx); planner._register_owner(fort_ref, fort_path)
    else:
        fort_ref, fort_path, fort = existing
        fort["garrison_formation_refs"] = sorted(set(garrisons))
        if not isinstance(fort.get("physical_state"), Mapping):
            fort["physical_state"] = initial_physical_state(profile, int(fort.get("integrity", 100)))
        sync_integrity_projection(fort); planner.put(fort_path, fort)

    siege_idx = copy.deepcopy(planner.read("state/sieges/index.json"))
    existing_ref = str(front.get("siege_ref", ""))
    if existing_ref and isinstance(siege_idx.get("sieges", {}).get(existing_ref), str):
        siege_path = str(siege_idx["sieges"][existing_ref]); siege = copy.deepcopy(planner.read(siege_path))
        if str(siege.get("status", "")) in {"active", "captured"}:
            return {"siege_ref": existing_ref, "siege_path": siege_path, "fortification_ref": fort_ref, "fortification_path": fort_path, "siege": siege, "fortification": fort}

    attackers_here = _physical_formations_at_site(planner, attacker_refs, site_ref)
    if not attackers_here:
        return None
    token = hashlib.sha256((str(theater_ref)+"|"+str(front.get("front_ref", ""))+"|"+site_ref).encode()).hexdigest()[:18]
    siege_ref = f"siege_auto_{token}"
    siege_path = f"state/sieges/{siege_ref}.json"
    registered_routes = [str(x) for x in profile.get("route_control_refs", []) if isinstance(x, str)]
    doc = {
        "schema":"sword-siege", "owner_id":siege_ref, "siege_ref":siege_ref, "fortification_ref":fort_ref,
        "attacker_formation_refs":attackers_here, "defender_formation_refs":sorted(set(garrisons)),
        "status":"active", "days":0, "casualties":{}, "started_at":at,
        "attacker_authorities":[str(attacker_side)], "defender_authorities":[str(defender_side)], "outcome":None,
        "engineering_works":[], "registered_approach_route_refs":registered_routes,
        "blockade":{"covered_route_refs":list(registered_routes),"fully_invested":bool(registered_routes)},
        "physical_access_model":str((fort.get("physical_state") or {}).get("model", "qualitative_fortification")),
        "active_enclosure_ref":active_enclosure_ref(fort), "fortified_site_depot_ref":fort.get("fortified_site_depot_ref"),
        "fortress_artillery_ref":None, "strategic_theater_ref":str(theater_ref), "strategic_front_ref":str(front.get("front_ref", "")),
        "autonomous":True,
    }
    if hasattr(planner, "_fortified_site_runtime_records"):
        _dp, _dd, _ap, _aa = planner._fortified_site_runtime_records(site_ref, at=at)
        doc["fortified_site_depot_ref"] = str(_dd.get("owner_id", "")); doc["fortress_artillery_ref"] = str(_aa.get("owner_id", ""))
    planner.put(siege_path, doc); siege_idx.setdefault("sieges", {})[siege_ref] = siege_path; planner.put("state/sieges/index.json", siege_idx); planner._register_owner(siege_ref, siege_path)
    front["siege_ref"] = siege_ref; front["fortification_ref"] = fort_ref; front["status"] = "besieging"; front["siege_started_at"] = at
    return {"siege_ref": siege_ref, "siege_path": siege_path, "fortification_ref": fort_ref, "fortification_path": fort_path, "siege": doc, "fortification": fort}


def _source_depot_for_formation(planner: Any, formation: Mapping[str, Any], side: str) -> tuple[str, Mapping[str, Any]] | None:
    core = str(side).removeprefix("state_")
    if core in {"qin", "zhao", "chu", "wei", "han", "yan", "qi"}:
        path = f"state/depots/{core}.json"
        row = planner.read_optional(path)
        if isinstance(row, Mapping) and int((row.get("stocks", {}) or {}).get("construction_material_units", 0)) > 0:
            return str(row.get("owner_id", f"state_depot_{core}")), row
    force_ref = str(formation.get("owner_force_ref", ""))
    slug = force_ref.replace("force_", "").replace("_", "-")
    if slug:
        row = planner.read_optional(f"state/depots/{slug}.json")
        if isinstance(row, Mapping) and int((row.get("stocks", {}) or {}).get("construction_material_units", 0)) > 0:
            return str(row.get("owner_id", "")), row
    return None


def _ensure_material_shipment(planner: Any, siege: Mapping[str, Any], site_ref: str, attacker_side: str, at: str, desired: int = 500) -> dict[str, Any] | None:
    if not hasattr(planner, "_fort_dispatch_field_siege_convoy"):
        return None
    for ref in siege.get("attacker_formation_refs", []) if isinstance(siege.get("attacker_formation_refs"), list) else []:
        try:
            _fp, formation = planner._load_formation(str(ref))
        except ValueError:
            continue
        carried = max(0, int((formation.get("logistics", {}) or {}).get("construction_material_units", 0)))
        if carried >= 200:
            return {"status":"material_available","formation_ref":str(ref),"construction_material_units":carried}
        if hasattr(planner, "_fort_active_field_siege_convoy") and planner._fort_active_field_siege_convoy(str(ref), site_ref):
            return {"status":"material_in_transit","formation_ref":str(ref)}
        source = _source_depot_for_formation(planner, formation, attacker_side)
        if source is None:
            continue
        source_ref, source_doc = source
        available = max(0, int((source_doc.get("stocks", {}) or {}).get("construction_material_units", 0)))
        qty = min(max(0, desired - carried), available)
        if qty <= 0:
            continue
        try:
            return planner._fort_dispatch_field_siege_convoy(
                formation_ref=str(ref), destination_site_ref=site_ref, source_depot_ref=source_ref,
                construction_material_units=qty, at=at,
            )
        except (ValueError, KeyError):
            continue
    return None


def _engineering_next_work(fort: Mapping[str, Any], siege: Mapping[str, Any]) -> tuple[str, str, int] | None:
    gate_access = ram_access(fort, siege)
    if not gate_access.get("admissible"):
        reason = str(gate_access.get("reason", ""))
        if "crossing" in reason or "moat" in reason or "drawbridge" in reason:
            required = max(0.0, required_crossing_length(fort, "gate"))
            quantity = max(1, int(math.ceil(required / 10.0)))
            return "siege_timber_earth_causeway_10m", "gate", quantity
        if "battering ram" in reason:
            return "siege_heavy_covered_ram", "gate", 1
    return None


def _complete_engineering_work(planner: Any, siege: dict[str, Any], fort: Mapping[str, Any], *, at: str, review_hours: int) -> dict[str, Any] | None:
    next_work = _engineering_next_work(fort, siege)
    if next_work is None:
        return None
    blueprint_ref, target, quantity = next_work
    blueprints = engineering_blueprints(planner.read); blueprint = blueprints.get(blueprint_ref)
    if not isinstance(blueprint, Mapping):
        return None
    materials = work_materials(blueprint, quantity)
    needed = max(0, int(math.ceil(float(materials.get("construction_material_units", 0)))))
    active = siege.get("autonomous_engineering_work") if isinstance(siege.get("autonomous_engineering_work"), Mapping) else None
    if not active or str(active.get("blueprint_ref", "")) != blueprint_ref or str(active.get("target", "")) != target:
        source_ref = None; source_path = None; source = None
        for ref in siege.get("attacker_formation_refs", []):
            try:
                fp, row = planner._load_formation(str(ref))
            except ValueError:
                continue
            if int((row.get("logistics", {}) or {}).get("construction_material_units", 0)) >= needed:
                source_ref, source_path, source = str(ref), fp, copy.deepcopy(row); break
        if source is None:
            return {"status":"awaiting_materials","blueprint_ref":blueprint_ref,"construction_material_units_required":needed}
        engineering_score = planner._formation_task_score(source, "engineering") if hasattr(planner, "_formation_task_score") else 50.0
        efficiency = task_efficiency(engineering_score, blueprint_difficulty(blueprint))
        crew = temporary_duty_personnel(int(source.get("personnel", 0)), "engineering", minimum=max(1, int(blueprint.get("crew_min", 1))))
        if crew < max(1, int(blueprint.get("crew_min", 1))):
            return {"status":"insufficient_engineering_labor","blueprint_ref":blueprint_ref}
        source.setdefault("logistics", {})["construction_material_units"] = int(source.get("logistics", {}).get("construction_material_units", 0)) - needed
        planner.put(source_path, source)
        active = {
            "blueprint_ref":blueprint_ref,"target":target,"quantity":quantity,"source_formation_ref":source_ref,
            "materials":materials,"labor_hours_required":float(blueprint.get("labor_hours", 1)) * quantity,
            "labor_hours_completed":0.0,"crew":crew,"engineering_score":round(float(engineering_score),3),
            "labor_efficiency":round(float(efficiency),4),"started_at":at,
        }
        siege["autonomous_engineering_work"] = active
    progress = max(0.0, float(active.get("crew", 0))) * max(0.05, float(active.get("labor_efficiency", 1.0))) * max(1, int(review_hours))
    active["labor_hours_completed"] = min(float(active.get("labor_hours_required", 1.0)), float(active.get("labor_hours_completed", 0.0)) + progress)
    if float(active["labor_hours_completed"]) + 1e-9 < float(active.get("labor_hours_required", 1.0)):
        return {"status":"construction_in_progress",**copy.deepcopy(dict(active))}
    work_ref = "siege_work_auto_" + hashlib.sha256((str(siege.get("siege_ref"))+"|"+blueprint_ref+"|"+target+"|"+str(len(siege.get("engineering_works", [])))).encode()).hexdigest()[:18]
    work = work_record(
        blueprint_ref, blueprint, work_ref=work_ref, target=target, quantity=quantity, at=at,
        source_formation_ref=str(active.get("source_formation_ref", "")), materials=active.get("materials", {}),
    )
    work["enclosure_ref"] = active_enclosure_ref(fort); work["labor_personnel_used"] = int(active.get("crew", 0)); work["engineering_leadership_score"] = float(active.get("engineering_score", 0)); work["labor_efficiency"] = float(active.get("labor_efficiency", 1.0)); work["construction_hours"] = int(math.ceil(float(active.get("labor_hours_required", 1.0)) / max(1.0, float(active.get("crew", 1)) * max(0.05, float(active.get("labor_efficiency", 1.0)))))); work["condition_pct"] = 100.0
    siege.setdefault("engineering_works", []).append(work); siege["engineering_works"] = siege["engineering_works"][-64:]; siege.pop("autonomous_engineering_work", None)
    return {"status":"completed","work_ref":work_ref,"blueprint_ref":blueprint_ref,"target":target}


def _derived_relief_prospect(planner: Any, siege: Mapping[str, Any], site_ref: str, *, at: str) -> dict[str, Any]:
    """Derive relief hope from exact friendly formations and real route time."""
    defender_authorities = {str(x) for x in siege.get("defender_authorities", []) if isinstance(x, str)}
    normalized = set(defender_authorities)
    for ref in list(defender_authorities):
        if ref.startswith("state_"):
            normalized.add(ref.removeprefix("state_"))
        elif ref and not ref.startswith(("house_", "polity_")):
            normalized.add(f"state_{ref}")
    inside = {str(x) for x in siege.get("defender_formation_refs", []) if isinstance(x, str)}
    attacker_refs = [str(x) for x in siege.get("attacker_formation_refs", []) if isinstance(x, str)]
    attacker_personnel = 0
    for ref in attacker_refs:
        try:
            _p, formation = planner._load_formation(ref)
        except (ValueError, KeyError, FileNotFoundError):
            continue
        attacker_personnel += max(0, int(formation.get("personnel", 0) or 0))

    try:
        owner_index = planner.read("state/index/owner-index.json")
    except (FileNotFoundError, KeyError, ValueError):
        owner_index = {}
    owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
    candidates: list[dict[str, Any]] = []
    iterable = owners.items() if isinstance(owners, Mapping) else []
    for formation_ref, path in iterable:
        if not isinstance(formation_ref, str) or not formation_ref.startswith("formation_") or formation_ref in inside:
            continue
        try:
            formation = planner.read(path) if isinstance(path, str) else None
        except (FileNotFoundError, KeyError, ValueError):
            continue
        if not isinstance(formation, Mapping):
            continue
        personnel = max(0, int(formation.get("personnel", 0) or 0))
        status = str(formation.get("status", ""))
        if (
            personnel <= 0
            or not bool(formation.get("mobilized", False))
            or status in {"destroyed", "dissolved", "forming", "recruiting", "arrived_forming", "contract_complete_withdrawing"}
        ):
            continue
        authorities = {str(formation.get("administrative_owner", "")), str(formation.get("command_authority", ""))}
        if not authorities.intersection(normalized):
            continue
        origin = str(formation.get("location_ref", ""))
        if not origin or origin == site_ref:
            continue
        try:
            route = shortest_path(planner.read, origin, site_ref, modes=("formation",))
        except ValueError:
            continue
        hours = max(0, int(route.get("duration_hours", 0) or 0))
        if hours <= 0 or hours > 24 * 14:
            continue
        candidates.append({"formation_ref": formation_ref, "personnel": personnel, "route_hours": hours})

    candidates.sort(key=lambda row: (int(row["route_hours"]), -int(row["personnel"]), str(row["formation_ref"])))
    # Relief hope is a mechanical consequence, not a UI window.  Every exact
    # mobilized friendly formation that can physically reach the site inside
    # the configured fourteen-day horizon contributes to the prospect.  Keep
    # only the diagnostic ref list bounded so a large field army cannot bloat
    # the hot siege owner; candidate_count and the personnel totals remain exact.
    weighted_personnel = 0.0
    for row in candidates:
        time_factor = max(0.10, 1.0 - int(row["route_hours"]) / float(24 * 16))
        weighted_personnel += int(row["personnel"]) * time_factor
    ratio = weighted_personnel / max(1.0, float(attacker_personnel or 1))
    nearest = min((int(row["route_hours"]) for row in candidates), default=None)
    proximity = 0.0 if nearest is None else max(0.15, 1.0 - nearest / float(24 * 14))
    score = int(round(max(0.0, min(100.0, 100.0 * min(1.0, ratio) * proximity))))
    evidence_limit = 16
    evidence_rows = candidates[:evidence_limit]
    return {
        "score": score,
        "candidate_count": len(candidates),
        "plausible_relief_formation_refs": [str(row["formation_ref"]) for row in evidence_rows],
        "plausible_relief_refs_truncated": len(candidates) > evidence_limit,
        "plausible_relief_personnel": sum(int(row["personnel"]) for row in candidates),
        "weighted_relief_personnel": int(round(weighted_personnel)),
        "nearest_route_hours": nearest,
        "attacker_personnel": attacker_personnel,
        "basis": "exact_friendly_formations_plus_route_time",
    }


def advance_autonomous_siege(
    planner: Any,
    *,
    siege_ref: str,
    at: str,
    review_days: int,
    attacker_side: str,
) -> dict[str, Any]:
    """Advance one exact autonomous siege review without recursively advancing time."""
    idx = planner.read("state/sieges/index.json"); path = idx.get("sieges", {}).get(str(siege_ref)) if isinstance(idx, Mapping) else None
    if not isinstance(path, str):
        raise ValueError("autonomous strategic siege route references an unknown siege")
    siege = copy.deepcopy(planner.read(path)); fort_path = planner.owner_path(str(siege.get("fortification_ref", ""))); fort = copy.deepcopy(planner.read(fort_path))
    if str(siege.get("status", "")) == "captured":
        return {"status":"captured","assault_ready":True}
    if str(siege.get("status", "")) != "active":
        return {"status":str(siege.get("status", "")),"assault_ready":False}
    def available_formation_refs(refs: Any) -> list[str]:
        out: list[str] = []
        for ref in refs if isinstance(refs, list) else []:
            if not isinstance(ref, str):
                continue
            try:
                _fp, formation = planner._load_formation(ref)
            except ValueError:
                # Preserve the pre-existing fail-tolerant siege contract. A
                # temporarily unresolved ref is not proof that a force withdrew.
                out.append(ref)
                continue
            if str(formation.get("status", "")) == "contract_complete_withdrawing":
                continue
            out.append(ref)
        return out
    siege["attacker_formation_refs"] = available_formation_refs(siege.get("attacker_formation_refs", []))
    siege["defender_formation_refs"] = available_formation_refs(siege.get("defender_formation_refs", []))
    fort["garrison_formation_refs"] = available_formation_refs(fort.get("garrison_formation_refs", []))
    if not siege["attacker_formation_refs"]:
        siege["status"] = "lifted"
        siege["lifted_at"] = at
        planner.put(path, siege)
        planner.put(fort_path, fort)
        return {"status":"lifted","assault_ready":False}
    planner.put(path, siege)
    planner.put(fort_path, fort)
    days = max(1, int(review_days)); site_ref = str(fort.get("site_ref") or fort.get("location_ref") or "")
    if hasattr(planner, "_fort_settle_due_campaign_convoys"):
        planner._fort_settle_due_campaign_convoys(at)
    shipment = _ensure_material_shipment(planner, siege, site_ref, attacker_side, at)
    registered = [str(x) for x in siege.get("registered_approach_route_refs", []) if isinstance(x, str)]
    siege.setdefault("blockade", {})["covered_route_refs"] = list(registered); siege["blockade"]["fully_invested"] = bool(registered)
    defenders = [str(x) for x in siege.get("defender_formation_refs", [])]
    defender_personnel = 0
    for ref in defenders:
        try: defender_personnel += max(0, int(planner._load_formation(ref)[1].get("personnel", 0)))
        except ValueError: continue
    reserve_draw = planner._siege_defender_reserve_draw(fort, days=days, defenders=defender_personnel, at=at) if hasattr(planner, "_siege_defender_reserve_draw") else {"shortfall":{}}
    siege["days"] = int(siege.get("days", 0)) + days
    shortfall = reserve_draw.get("shortfall", {}) if isinstance(reserve_draw, Mapping) else {}
    if any(max(0, int(v)) > 0 for v in shortfall.values() if isinstance(v, (int, float))):
        siege["deprivation_days"] = int(siege.get("deprivation_days", 0)) + days
    else:
        siege["deprivation_days"] = 0
    engineering = _complete_engineering_work(planner, siege, fort, at=at, review_hours=days * 24)
    gate = ram_access(fort, siege)
    ram_damage = None; artillery = None
    if gate.get("admissible"):
        works = [w for w in siege.get("engineering_works", []) if isinstance(w, Mapping) and str(w.get("kind", "")) == "battering_ram" and str(w.get("status", "serviceable")) == "serviceable"]
        if works:
            blueprints = engineering_blueprints(planner.read); bp = blueprints.get(str(works[-1].get("blueprint_ref", "")), {})
            impact = float(bp.get("base_impact_index", 95.0) or 95.0)
            cycles = max(1, min(7, days))
            if hasattr(planner, "_siege_prepare_fortress_artillery"):
                artillery = planner._siege_prepare_fortress_artillery(fort, defender_refs=defenders, battle_hours=max(1, min(8, days * 2)), at=at, attacker_refs=[str(x) for x in siege.get("attacker_formation_refs", [])])
            ram_damage = apply_ram_damage(fort, impact, cycles)
    gate_access = ram_access(fort, siege)
    gate_state = ((fort.get("physical_state", {}) or {}).get("gates", {}) or {}).get("main_gate", {})
    breached = str(gate_state.get("status", "")) in {"breached", "destroyed"} or float(gate_state.get("breach_width_m", 0.0) or 0.0) >= 1.5
    no_defenders = defender_personnel <= 0
    assault_ready = bool(breached and gate_access.get("admissible"))

    # Deprivation creates accumulating surrender pressure instead of a fixed
    # fourteen-day flip. Water failure is more urgent than food failure; saved
    # defender morale/leadership and any explicit relief prospect resist collapse.
    grain_need = max(0, int((reserve_draw.get("consumed", {}) or {}).get("grain_kg", 0))) + max(0, int(shortfall.get("grain_kg", 0)))
    water_need = max(0, int((reserve_draw.get("consumed", {}) or {}).get("water_person_days", 0))) + max(0, int(shortfall.get("water_person_days", 0)))
    grain_short_fraction = max(0.0, int(shortfall.get("grain_kg", 0)) / max(1, grain_need))
    water_short_fraction = max(0.0, int(shortfall.get("water_person_days", 0)) / max(1, water_need))
    morale_rows: list[int] = []; leadership_rows: list[int] = []
    for ref in defenders:
        try:
            _fp, formation = planner._load_formation(ref)
        except ValueError:
            continue
        if int(formation.get("personnel", 0)) <= 0:
            continue
        morale_rows.append(max(0, min(100, int(formation.get("morale", 50)))))
        commander_ref = formation.get("commander_ref")
        if isinstance(commander_ref, str) and commander_ref:
            try:
                commander = planner.read(planner.owner_path(commander_ref))
                skills = commander.get("skills", {}) if isinstance(commander, Mapping) else {}
                leadership_rows.append(max(0, min(200, int(skills.get("Leadership", 0)))))
            except (ValueError, KeyError, FileNotFoundError):
                pass
    average_morale = sum(morale_rows) / max(1, len(morale_rows)) if morale_rows else 50.0
    best_leadership = max(leadership_rows) if leadership_rows else 0
    relief_evidence = _derived_relief_prospect(planner, siege, site_ref, at=at)
    relief_prospect = max(0, min(100, int(relief_evidence.get("score", 0) or 0)))
    siege.pop("relief_prospect", None)
    civilian_ratio = 0.0
    if hasattr(planner, "_demographic_site"):
        try:
            _native, _pp, _pop, local_row, _anchor = planner._demographic_site(site_ref)
            civilian_ratio = max(0, int(local_row.get("civilian_population", 0))) / max(1, defender_personnel)
        except (ValueError, KeyError, FileNotFoundError):
            civilian_ratio = 0.0
    pressure_increment = days * (grain_short_fraction * 2.5 + water_short_fraction * 7.5)
    pressure_increment += max(0.0, 45.0 - average_morale) * 0.16 * days
    pressure_increment += min(12.0, math.log1p(civilian_ratio) * 2.0) * (1.0 if (grain_short_fraction or water_short_fraction) else 0.0)
    pressure_resistance = days * (min(12.0, best_leadership / 20.0) + relief_prospect * 0.06)
    if grain_short_fraction <= 0.0 and water_short_fraction <= 0.0:
        pressure_increment = -max(4.0 * days, pressure_resistance)
        pressure_resistance = 0.0
    surrender_pressure = max(0.0, min(200.0, float(siege.get("surrender_pressure", 0.0)) + pressure_increment - pressure_resistance))
    siege["surrender_pressure"] = round(surrender_pressure, 3)
    siege["surrender_evidence"] = {
        "grain_shortfall_fraction": round(grain_short_fraction, 6), "water_shortfall_fraction": round(water_short_fraction, 6),
        "deprivation_days": int(siege.get("deprivation_days", 0)), "average_defender_morale": round(average_morale, 3),
        "best_defender_leadership": best_leadership, "civilian_to_defender_ratio": round(civilian_ratio, 3),
        "relief_prospect": relief_prospect, "relief_evidence": relief_evidence, "pressure": round(surrender_pressure, 3),
    }
    deprivation_surrender = (defender_personnel > 0 and int(siege.get("deprivation_days", 0)) >= 3
                              and (grain_short_fraction > 0.0 or water_short_fraction > 0.0)
                              and surrender_pressure >= 100.0)
    enclosure_transition = None
    if deprivation_surrender:
        siege["status"] = "captured"; siege["outcome"] = "defender_surrender_under_siege_pressure"; siege["captured_at"] = at; siege["capture_basis"] = "stateful_deprivation_morale_relief_pressure"
        siege["terminal_evidence"] = copy.deepcopy(siege["surrender_evidence"])
    elif no_defenders and assault_ready:
        # Empty walls are still walls. Unopposed entry secures exactly one saved
        # enclosure per review and never skips nested inner defenses.
        physical = ensure_physical_state(fort)
        active_before = active_enclosure_ref(fort)
        register_attacker_foothold(physical, method="breach", target_ref="gate", at=at, battle_ref=f"auto_unopposed:{siege_ref}:{active_before}:{at}")
        commit_active_layer_projection(physical)
        enclosure_transition = advance_enclosure_layer(physical, at=at, battle_ref=f"auto_unopposed:{siege_ref}:{active_before}:{at}")
        fort["physical_state"] = physical; sync_integrity_projection(fort)
        siege["active_enclosure_ref"] = active_enclosure_ref(fort)
        if enclosure_transition.get("final_layer_secured"):
            siege["status"] = "captured"; siege["outcome"] = "unopposed_control_after_all_enclosures_secured"; siege["captured_at"] = at; siege["capture_basis"] = "physical_enclosure_control"
        else:
            assault_ready = False
    siege["last_autonomous_review"] = {
        "at":at,"days":days,"material_shipment":copy.deepcopy(shipment),"defender_reserve_draw":copy.deepcopy(reserve_draw),
        "engineering":copy.deepcopy(engineering),"ram_damage":copy.deepcopy(ram_damage),"fortress_artillery":copy.deepcopy(artillery),
        "assault_ready":assault_ready,"deprivation_days":int(siege.get("deprivation_days", 0)),
        "surrender_pressure":round(surrender_pressure,3),"surrender_evidence":copy.deepcopy(siege.get("surrender_evidence",{})),
        "enclosure_transition":copy.deepcopy(enclosure_transition),
    }
    sync_integrity_projection(fort); planner.put(fort_path, fort); planner.put(path, siege)
    return {"status":str(siege.get("status", "active")),"assault_ready":assault_ready,"starvation_surrender":deprivation_surrender,"deprivation_surrender":deprivation_surrender,"surrender_pressure":round(surrender_pressure,3),"defender_personnel":defender_personnel,"engineering":engineering,"ram_damage":ram_damage,"artillery":artillery,"enclosure_transition":copy.deepcopy(enclosure_transition)}


def commit_one_reserve_command(plan: dict[str, Any], *, side: str, front: dict[str, Any], at: str, reason: str) -> dict[str, Any] | None:
    """Commit one intact saved reserve command to an existing front."""
    reserves = plan.get("strategic_reserve_commands", {}) if isinstance(plan.get("strategic_reserve_commands"), Mapping) else {}
    rows = reserves.get(side, []) if isinstance(reserves.get(side), list) else []
    if not rows:
        return None
    command = copy.deepcopy(rows.pop(0))
    refs = [str(x) for x in command.get("formation_refs", []) if isinstance(x, str)]
    if not refs:
        return None
    key = "attacker_formation_refs" if str(side) == str(plan.get("attacker_side")) else "defender_formation_refs"
    cmd_key = "attacker_command_refs" if key.startswith("attacker") else "defender_command_refs"
    front[key] = sorted(set([str(x) for x in front.get(key, [])] + refs))
    command_ref = str(command.get("command_group_ref") or command.get("independent_formation_ref") or "")
    if command_ref:
        front[cmd_key] = sorted(set([str(x) for x in front.get(cmd_key, [])] + [command_ref]))
    objective = str(front.get("objective_ref", ""))
    plan.setdefault("formation_objectives", {}).setdefault(side, {}).update({ref: objective for ref in refs})
    reserve_refs = plan.setdefault("strategic_reserve_formation_refs", {}).setdefault(side, [])
    plan["strategic_reserve_formation_refs"][side] = [str(x) for x in reserve_refs if str(x) not in refs]
    return {"command_ref":command_ref,"formation_refs":refs,"front_ref":front.get("front_ref"),"reason":reason}


def redirect_blocked_front(planner: Any, plan: dict[str, Any], *, side: str, front: dict[str, Any], at: str) -> dict[str, Any] | None:
    """Move one blocked command axis onto another already-lawful campaign front.

    The formation set moves as a whole; this never splits or invents a command.
    If no existing front is reachable, the blocked axis is abandoned and its
    formations return to strategic unassignment for later withdrawal/review.
    """
    refs = [str(x) for x in front.get("attacker_formation_refs", []) if isinstance(x, str)]
    if not refs:
        front["status"] = "abandoned"
        return {"status":"abandoned","reason":"no surviving formation remains on blocked axis"}
    sample = None
    for ref in refs:
        try:
            _p, f = planner._load_formation(ref)
        except ValueError:
            continue
        if int(f.get("personnel", 0)) > 0:
            sample = (ref, f); break
    if sample is None:
        front["status"] = "abandoned"
        return {"status":"abandoned","reason":"no surviving formation remains on blocked axis"}
    candidates = [
        row for row in plan.get("fronts", [])
        if isinstance(row, dict) and row is not front and str(row.get("status", "")) not in {"occupied", "defender_holds", "abandoned", "withdrawn", "route_blocked"}
    ]
    candidates.sort(key=lambda row: (-int(row.get("priority", 0)), str(row.get("front_ref", ""))))
    for target in candidates:
        objective = str(target.get("blocking_site_ref") or target.get("objective_ref") or "")
        if not objective:
            continue
        try:
            planner._formation_route_next(str(sample[1].get("location_ref", "")), objective, formation=sample[1], at=at)
        except ValueError:
            continue
        old_refs = list(refs); old_cmds = [str(x) for x in front.get("attacker_command_refs", []) if isinstance(x, str)]
        target["attacker_formation_refs"] = sorted(set([str(x) for x in target.get("attacker_formation_refs", [])] + old_refs))
        target["attacker_command_refs"] = sorted(set([str(x) for x in target.get("attacker_command_refs", [])] + old_cmds))
        plan.setdefault("formation_objectives", {}).setdefault(side, {}).update({ref:str(target.get("objective_ref", "")) for ref in old_refs})
        front["former_attacker_formation_refs"] = old_refs; front["attacker_formation_refs"] = []; front["former_attacker_command_refs"] = old_cmds; front["attacker_command_refs"] = []
        front["status"] = "abandoned"; front["redirected_to_front_ref"] = str(target.get("front_ref", "")); front["redirected_at"] = at
        return {"status":"redirected","from_front_ref":front.get("front_ref"),"to_front_ref":target.get("front_ref"),"formation_refs":old_refs}
    plan.setdefault("unassigned_formation_refs", {}).setdefault(side, [])
    plan["unassigned_formation_refs"][side] = sorted(set([str(x) for x in plan["unassigned_formation_refs"][side]] + refs))
    for ref in refs:
        plan.setdefault("formation_objectives", {}).setdefault(side, {}).pop(ref, None)
    front["former_attacker_formation_refs"] = refs; front["attacker_formation_refs"] = []; front["status"] = "abandoned"; front["abandoned_at"] = at; front["abandonment_reason"] = "no lawful alternate campaign axis remained"
    return {"status":"abandoned","from_front_ref":front.get("front_ref"),"formation_refs":refs}

def war_fronts_resolved(fronts: list[Mapping[str, Any]]) -> bool:
    terminal = {"occupied", "defender_holds", "abandoned", "withdrawn"}
    return bool(fronts) and all(str(front.get("status", "")) in terminal for front in fronts if isinstance(front, Mapping))

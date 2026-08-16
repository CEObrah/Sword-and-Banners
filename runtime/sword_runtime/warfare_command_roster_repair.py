"""Composite v3 maintenance repair for GBG scale, Qin detachment, and officer rosters.

This recipe advances no campaign time. It wraps the historical GBG decimal-scale
repair, then reconciles the accepted four-unit Qin Border Detachment organization
and materializes only the officer identities explicitly required by that design.
All personnel are conserved from exact force/cohort owners. Internal commanders
remain inside formation fighting strength; Qin unit commanders/deputies come from
Qin's existing command-personnel reserve; support is allocated from existing Qin
reserve roles. No Sword Manor officer is silently transferred and no equipment is
created.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.cohort_personnel import validate_cohort_ledger
from sword_runtime.history_store import HISTORY_INDEX_PATH, write_history_index
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.warfare_depth import build_formation_command_structure
from sword_runtime.warfare_house_scale_repair import apply_warfare_house_scale_repair

_REPAIR_ID = "warfare_house_gbg_depth_v3"
_GBG_FORCE = "state/forces/tang-wei-personal.json"
_GBG_FORMATION = "state/formations/tang-wei-great-bow-guard-first.json"
_HOUSE = "state/houses/house_tang.json"
_QIN_FORCE = "state/forces/state-qin.json"
_QIN_STATE = "state/states/qin.json"
_PLAYER = "state/player.json"
_RULES = "game/data/mechanics/warfare-organization.json"
_COMMAND_PERSONNEL_INDEX = "state/cmd/command-personnel.json"
_QIN_OPERATION = "state/operations/operation_arc_131572c4e8a2892bbc.json"
_QIN_LEAD_PATH = "state/formations/qin-border-line.json"
_QIN_REFS = (
    "formation_qin_border_line",
    "formation_qin_border_line_second",
    "formation_qin_border_line_third",
    "formation_qin_border_line_fourth",
)
_QIN_PATHS = (
    "state/formations/qin-border-line.json",
    "state/formations/qin-border-line-second.json",
    "state/formations/qin-border-line-third.json",
    "state/formations/qin-border-line-fourth.json",
)
_QIN_LABELS = ("I", "II", "III", "IV")
_QIN_LOCATION = "loc_qin_eastern_depot"
_GBG_REF = "formation_tang_wei_great_bow_guard_first"


def _quarters(value: int) -> list[int]:
    total = max(0, int(value))
    base, remainder = divmod(total, 4)
    return [base + (1 if index < remainder else 0) for index in range(4)]


def _partition_mapping(values: Any) -> list[dict[str, int]]:
    out = [dict() for _ in range(4)]
    if not isinstance(values, Mapping):
        return out
    for key in sorted(str(k) for k in values):
        parts = _quarters(int(values.get(key, 0)))
        for index, count in enumerate(parts):
            if count:
                out[index][key] = count
    return out


def _person_slug(person_ref: str) -> str:
    return person_ref.removeprefix("char_").replace(".", "-").replace("_", "-")


def _person_path(person_ref: str, representation: str) -> str:
    if representation == "exact":
        return f"state/char/{_person_slug(person_ref)}.json"
    return f"state/person/retinue/{_person_slug(person_ref)}.json"


def _stable_birth_date(person_ref: str, at: str) -> str:
    now = CampaignTime.parse(at)
    seed = int(hashlib.sha256((person_ref + "|birth").encode("utf-8")).hexdigest()[:16], 16)
    age = 24 + seed % 17
    month = 1 + (seed // 17) % 12
    day = 1 + (seed // 211) % 28
    return f"{now.bce_year + age}-BCE-{month:02d}-{day:02d}"


def _seed_body(person_ref: str, person: MutableMapping[str, Any]) -> None:
    seed = int(hashlib.sha256((person_ref + "|body").encode("utf-8")).hexdigest()[:12], 16)
    person["body"] = {
        "adult_height_cm": round(160.0 + (seed % 211) / 10.0, 1),
        "growth_profile_id": "human_height_to_18",
        "growth_end_age": 18,
        "height_anchors": [],
        "current_weight_kg": round(52.0 + ((seed // 211) % 241) / 10.0, 1),
        "frame": "average",
        "source": "simulation_assigned",
    }
    person["appearance"] = int((seed // 509) % 101)
    person["appearance_source"] = "simulation_assigned"


def _role_loadout(planner: Any, role: str) -> str:
    if not hasattr(planner, "_combat_role_profile"):
        return ""
    profile = planner._combat_role_profile(role)
    return str(profile.get("loadout_id", "")) if isinstance(profile, Mapping) else ""


def _command_record(planner: Any, index: MutableMapping[str, Any], person_ref: str, formation_ref: str, role: str, representation: str) -> str:
    path = f"state/cmd/command-personnel/{person_ref}.json"
    planner.put(path, {
        "schema": "command-person.v1",
        "id": f"command_person.{person_ref}",
        "person_id": person_ref,
        "command": {
            "representation": "exact_named_person" if representation == "exact" else "individual_lite",
            "current_army_id": None,
            "role": role,
            "command_scope": "persistent_unit_command",
            "current_unit_ids": [formation_ref],
            "specialty_hint": "Qin Border Detachment senior command; capability comes from the conserved source cohort and subsequent saved service",
        },
    })
    records = index.setdefault("record_index", {})
    if not isinstance(records, MutableMapping):
        raise ValueError("command-personnel record index is invalid")
    records[person_ref] = path
    index["count"] = len(records)
    return path


def _base_person_lite(person_ref: str, name: str, force_ref: str, state: str, role: str, location: str, at: str) -> dict[str, Any]:
    return {
        "schema": "person-lite",
        "id": person_ref,
        "name": name,
        "resolution": "individual_lite",
        "birth_date": _stable_birth_date(person_ref, at),
        "birth_date_source": "simulation_assigned_stable_seed",
        "owner": force_ref,
        "origin": state,
        "rank": "materialized_officer",
        "role": role,
        "stats": {"attributes": {}, "skills": {}},
        "health": {"status": "healthy", "fatigue": 0},
        "loc": location,
        "current_location": location,
        "loyalty": "professional_or_institutional",
        "narration_priority": "role_until_relevant",
        "history": {"service": [], "promotion": []},
        "relationships": [],
        "background": "Persistent officer materialized from an already-conserved military body. Earlier biography is not reconstructed beyond saved cohort provenance.",
    }


def _base_exact_person(person_ref: str, name: str, state: str, role: str, location: str, at: str) -> dict[str, Any]:
    return {
        "schema": "sword-materialized-person",
        "owner_id": person_ref,
        "owner_type": "character",
        "id": person_ref,
        "name": name,
        "state": state,
        "birth_date": _stable_birth_date(person_ref, at),
        "birth_date_source": "simulation_assigned_stable_seed",
        "status": "alive",
        "life_status": "active",
        "health_status": "healthy",
        "current_location": location,
        "rank": "unit_commander",
        "role": role,
        "attributes": {},
        "skills": {},
        "aptitude": {
            "physical_learning": 100,
            "technical_learning": 100,
            "tactical_learning": 100,
            "academic_learning": 100,
            "social_learning": 100,
        },
        "development_state": {"completed_reviews": 0, "maintenance_credit": 0.0, "training_credit": 0.0},
        "background": "Qin standing command personnel materialized as an exact unit commander. Earlier biography is not reconstructed beyond saved cohort provenance.",
    }


def _convert_lite_sample(person: MutableMapping[str, Any]) -> None:
    attributes = person.pop("attributes", {})
    skills = person.pop("skills", {})
    person["stats"] = {"attributes": attributes, "skills": skills}


def _materialize_external_senior(
    planner: Any,
    force: MutableMapping[str, Any],
    command_index: MutableMapping[str, Any],
    *,
    formation_ref: str,
    person_ref: str,
    name: str,
    role_name: str,
    representation: str,
    at: str,
) -> str:
    path = _person_path(person_ref, representation)
    if planner.read_optional(path) is not None or planner.read("state/index/owner-index.json").get("owners", {}).get(person_ref):
        raise ValueError(f"v3 officer person_ref already exists: {person_ref}")
    person: MutableMapping[str, Any]
    if representation == "exact":
        person = _base_exact_person(person_ref, name, "qin", role_name, _QIN_LOCATION, at)
    else:
        person = _base_person_lite(person_ref, name, "force_state_qin", "qin", role_name, _QIN_LOCATION, at)

    planner._ct_materialize_from_cohort(force, "command_personnel", _QIN_LOCATION, person_ref, person)
    planner._take_force_personnel(force, "command_personnel", 1, _QIN_LOCATION)
    loadout_id = _role_loadout(planner, "command_personnel")
    equipped = 0
    if hasattr(planner, "_take_force_equipment"):
        equipped = int(planner._take_force_equipment(force, "command_personnel", 1, _QIN_LOCATION))
    if equipped and loadout_id:
        if representation == "exact":
            person["equipment_loadout_id"] = loadout_id
        else:
            person["equipment_standard"] = loadout_id
    person["equipment_custody"] = {
        "mode": "force_role_equipment_slot" if equipped else "unissued",
        "force_ref": "force_state_qin",
        "role": "command_personnel",
        "source_location_ref": _QIN_LOCATION,
        "physical_equipment_unit_debited": bool(equipped),
        "principle": "one existing force equipment unit is reserved to this external senior officer; no equipment is created",
    }
    person["current_formation_id"] = formation_ref
    _seed_body(person_ref, person)
    if representation == "person_lite":
        _convert_lite_sample(person)
    force.setdefault("materialized_people", {})[person_ref] = 1
    command_record_ref = _command_record(planner, command_index, person_ref, formation_ref, role_name, representation)
    person["command_record_ref"] = command_record_ref
    planner.put(path, person)
    planner._register_owner(person_ref, path)
    if representation == "exact":
        planner._ensure_person_life_host(person_ref, planner._world_time())
    return person_ref


def _internal_plan(kind: str) -> list[dict[str, int | None]]:
    if kind == "qin_2000":
        thousand, five_hundred, hundred = 2, 4, 20
    elif kind == "gbg_3000":
        thousand, five_hundred, hundred = 3, 6, 30
    else:
        raise ValueError("unknown internal command plan")
    rows: list[dict[str, int | None]] = []
    for ordinal in range(1, thousand + 1):
        rows.append({"scale": 1000, "ordinal": ordinal, "parent_scale": None, "parent_ordinal": None})
    for ordinal in range(1, five_hundred + 1):
        rows.append({"scale": 500, "ordinal": ordinal, "parent_scale": 1000, "parent_ordinal": (ordinal - 1) // 2 + 1})
    for ordinal in range(1, hundred + 1):
        rows.append({"scale": 100, "ordinal": ordinal, "parent_scale": 500, "parent_ordinal": (ordinal - 1) // 5 + 1})
    return rows


def _materialize_internal_roster(
    planner: Any,
    force: MutableMapping[str, Any],
    formation: MutableMapping[str, Any],
    *,
    role: str,
    prefix: str,
    kind: str,
    at: str,
) -> list[dict[str, Any]]:
    formation_ref = str(formation["formation_ref"])
    assignments: list[dict[str, Any]] = []
    embedded = formation.setdefault("embedded_person_refs", [])
    if not isinstance(embedded, list):
        raise ValueError("formation embedded person registry is invalid")
    for node in _internal_plan(kind):
        scale = int(node["scale"] or 0)
        ordinal = int(node["ordinal"] or 0)
        person_ref = f"char_{prefix}_cmd_{scale}_{ordinal:02d}"
        path = _person_path(person_ref, "person_lite")
        if planner.read_optional(path) is not None or planner.read("state/index/owner-index.json").get("owners", {}).get(person_ref):
            raise ValueError(f"v3 internal officer person_ref already exists: {person_ref}")
        person = _base_person_lite(
            person_ref,
            f"{formation.get('name', formation_ref)} {scale}-man Commander {ordinal}",
            str(formation.get("owner_force_ref", "")),
            "qin",
            f"internal_{scale}_commander",
            str(formation.get("location_ref", "")),
            at,
        )
        planner._ct_materialize_from_formation(
            force,
            formation,
            role=role,
            person_ref=person_ref,
            person=person,
        )
        loadout_id = _role_loadout(planner, role)
        if loadout_id:
            person["equipment_standard"] = loadout_id
        person["equipment_custody"] = {
            "mode": "formation_issue_slot",
            "formation_ref": formation_ref,
            "role": role,
            "principle": "view of one already-counted formation issue slot; materialization creates no additional equipment",
        }
        person["current_formation_id"] = formation_ref
        person["rank"] = f"internal_{scale}_commander"
        _seed_body(person_ref, person)
        _convert_lite_sample(person)
        force.setdefault("materialized_people", {})[person_ref] = 1
        force.setdefault("materialized_assignments", {})[person_ref] = {
            "formation_ref": formation_ref,
            "role": role,
            "personnel": 1,
            "command_scale": scale,
        }
        embedded.append(person_ref)
        planner.put(path, person)
        planner._register_owner(person_ref, path)
        assignments.append({
            "person_ref": person_ref,
            "scale": scale,
            "ordinal": ordinal,
            "parent_scale": node["parent_scale"],
            "parent_ordinal": node["parent_ordinal"],
            "representation": "person_lite",
            "inside_fighting_establishment": True,
        })
    formation["embedded_person_refs"] = list(dict.fromkeys(str(ref) for ref in embedded if ref))
    return assignments


def _split_qin_border_line(planner: Any, at: str) -> tuple[MutableMapping[str, Any], list[MutableMapping[str, Any]]]:
    try:
        planner._release_formation_external_personnel(_QIN_REFS[0])
    except (KeyError, ValueError, FileNotFoundError):
        pass
    original = copy.deepcopy(planner.read(_QIN_LEAD_PATH))
    if int(original.get("personnel", 0)) != 8000 or str(original.get("owner_force_ref", "")) != "force_state_qin":
        raise ValueError("v3 Qin split requires the exact unsplit 8,000-fighter Qin Border Line")
    if str(original.get("location_ref", "")) != _QIN_LOCATION:
        raise ValueError("v3 Qin split requires the Qin Border Line at the eastern depot")

    force = planner._ct_force(_QIN_FORCE)
    allocations = force.get("allocated_to_formations", {})
    current = allocations.get(_QIN_REFS[0]) if isinstance(allocations, Mapping) else None
    current_count = int(current.get("personnel", 0)) if isinstance(current, Mapping) else int(current or 0)
    if current_count != 8000:
        raise ValueError("v3 Qin split source-force allocation is not exactly 8,000")
    materialized_assignments = force.get("materialized_assignments", {})
    if isinstance(materialized_assignments, Mapping) and any(
        isinstance(row, Mapping) and str(row.get("formation_ref", "")) == _QIN_REFS[0]
        for row in materialized_assignments.values()
    ):
        raise ValueError("v3 Qin split refuses to move pre-existing represented fighters without explicit reassignment")

    composition_parts = _partition_mapping(original.get("composition", {}))
    logistics_parts = _partition_mapping(original.get("logistics", {}))
    mount_parts = _partition_mapping(original.get("mounts", {}))
    equipment_parts = _partition_mapping(planner._equipment_units(original))
    cohort_parts: list[list[dict[str, Any]]] = [[] for _ in range(4)]
    ledger = force.get("cohort_ledger", {}).get("cohorts", {})
    if not isinstance(ledger, MutableMapping):
        raise ValueError("v3 Qin split requires Qin cohort authority")
    for item in original.get("cohort_composition", []):
        if not isinstance(item, Mapping):
            continue
        cohort_id = str(item.get("cohort_id", ""))
        count = int(item.get("count", 0))
        cohort = ledger.get(cohort_id)
        if not isinstance(cohort, MutableMapping):
            raise ValueError("v3 Qin split references an unknown cohort")
        allocated = cohort.setdefault("allocated_by_formation", {})
        if int(allocated.get(_QIN_REFS[0], 0)) != count:
            raise ValueError("v3 Qin split cohort allocation mismatch")
        parts = _quarters(count)
        allocated.pop(_QIN_REFS[0], None)
        for index, part in enumerate(parts):
            if part:
                allocated[_QIN_REFS[index]] = int(allocated.get(_QIN_REFS[index], 0)) + part
                cohort_parts[index].append({"cohort_id": cohort_id, "count": part})

    role = str(next(iter(original.get("composition", {})), "line_infantry"))
    allocations.pop(_QIN_REFS[0], None)
    formations: list[MutableMapping[str, Any]] = []
    for index, (formation_ref, path, label) in enumerate(zip(_QIN_REFS, _QIN_PATHS, _QIN_LABELS)):
        formation = copy.deepcopy(original)
        formation["formation_ref"] = formation_ref
        formation["name"] = f"QIN Border Unit {label}"
        formation["personnel"] = 2000
        formation["composition"] = composition_parts[index]
        formation["logistics"] = logistics_parts[index]
        formation["mounts"] = mount_parts[index]
        formation["cohort_composition"] = cohort_parts[index]
        formation["commander_ref"] = None
        formation["deputy_ref"] = None
        formation["command_authority"] = "state_qin"
        formation["higher_command_appointment_ref"] = "field_command:formation_qin_border_line"
        formation["split_origin_ref"] = _QIN_REFS[0]
        formation["split_repair_id"] = _REPAIR_ID
        formation["split_at"] = at
        formation.pop("attached_unit_command_by_role", None)
        formation.pop("attached_support_by_role", None)
        formation.pop("command_attachment_source_force_ref", None)
        formation.pop("command_structure", None)
        planner._set_equipment_units(formation, equipment_parts[index])
        allocations[formation_ref] = {"personnel": 2000, "role": role}
        planner.put(path, formation)
        if index:
            planner._register_owner(formation_ref, path)
            planner._index_formation_location(formation_ref, None, _QIN_LOCATION)
        formations.append(formation)
    validate_cohort_ledger(force)
    return force, formations


def _update_operation_and_appointments(planner: Any, at: str) -> None:
    operation = copy.deepcopy(planner.read(_QIN_OPERATION))
    refs: list[str] = []
    for ref in operation.get("formation_refs", []) if isinstance(operation.get("formation_refs"), list) else []:
        if str(ref) == _QIN_REFS[0]:
            refs.extend(_QIN_REFS)
        elif isinstance(ref, str) and ref:
            refs.append(ref)
    if _QIN_REFS[0] not in refs:
        refs.extend(_QIN_REFS)
    operation["formation_refs"] = list(dict.fromkeys(refs))
    operation["formation_topology_repaired_at"] = at
    operation["formation_topology_repair_id"] = _REPAIR_ID
    planner.put(_QIN_OPERATION, operation)

    player = copy.deepcopy(planner.read(_PLAYER))
    appointments = player.setdefault("career_state", {}).setdefault("appointments", [])
    if isinstance(appointments, list):
        for row in appointments:
            if not isinstance(row, MutableMapping) or str(row.get("formation_ref", "")) != _QIN_REFS[0]:
                continue
            row["formation_refs"] = list(_QIN_REFS)
            row["formation_name"] = "Qin Border Detachment"
            row["command_scope"] = "multi_formation_detachment"
            row["personnel"] = 8000
            row["persistent_unit_slots"] = 4
            row["unit_command_bodies_total"] = 8
            row["external_support_target_total"] = 112
            row["fully_staffed_attached_personnel"] = 8120
            row["command_structure_status"] = "four_unit_detachment_registered_rebrief_required"
            row["staffing_request_status"] = "unit_command_materialized_support_reconciled"
            row["briefing_refresh_required"] = True
            row["topology_repair_id"] = _REPAIR_ID
    if any(isinstance(row, Mapping) and str(row.get("formation_ref", "")) == _QIN_REFS[0] and str(row.get("status", "")) == "awaiting_assumption" for row in appointments if isinstance(appointments, list)):
        player["authority"] = "House Tang heir; patron and commander of Tang Wei Personal Retinue; Qin field-command appointee to Qin Border Detachment, awaiting assumption"
    planner.put(_PLAYER, player)

    qin = copy.deepcopy(planner.read(_QIN_STATE))
    for row in qin.setdefault("appointments", {}).values():
        if not isinstance(row, MutableMapping) or str(row.get("formation_ref", "")) != _QIN_REFS[0]:
            continue
        row["formation_refs"] = list(_QIN_REFS)
        row["command_scope"] = "multi_formation_detachment"
        row["personnel"] = 8000
        row["persistent_unit_slots"] = 4
        row["unit_command_bodies_total"] = 8
        row["external_support_target_total"] = 112
        row["fully_staffed_attached_personnel"] = 8120
        row["command_structure_status"] = "four_unit_detachment_registered_rebrief_required"
        row["staffing_request_status"] = "unit_command_materialized_support_reconciled"
        row["briefing_refresh_required"] = True
        row["topology_repair_id"] = _REPAIR_ID
    military = qin.setdefault("military_administration", {})
    military["commander_vacancy_count"] = max(0, int(military.get("commander_vacancy_count", 0)) - 1)
    military["last_command_topology_repair_at"] = at
    planner.put(_QIN_STATE, qin)


def apply_warfare_house_gbg_depth_v3(planner: Any, command: Any, reason: str) -> dict[str, Any]:
    """Apply the full current warfare/GBG/Qin command repair in one transaction."""

    at = str(planner._world_time())
    current_gbg = planner.read(_GBG_FORMATION)
    if int(current_gbg.get("personnel", 0)) == 300:
        legacy = apply_warfare_house_scale_repair(planner, command, reason)
    elif int(current_gbg.get("personnel", 0)) == 3000:
        legacy = {"great_bow_guard_personnel": 3000, "legacy_scale_repair": "already_applied"}
    else:
        raise ValueError("v3 repair requires Great Bow Guard at either the pre-repair 300 or repaired 3000 scale")

    rules = planner.read(_RULES)
    command_index = copy.deepcopy(planner.read(_COMMAND_PERSONNEL_INDEX))
    qin_force, qin_formations = _split_qin_border_line(planner, at)

    senior_refs: list[str] = []
    for index, formation in enumerate(qin_formations):
        label = _QIN_LABELS[index]
        commander_ref = f"char_qin_border_unit_{label.lower()}_commander"
        deputy_ref = f"char_qin_border_unit_{label.lower()}_deputy"
        _materialize_external_senior(
            planner,
            qin_force,
            command_index,
            formation_ref=str(formation["formation_ref"]),
            person_ref=commander_ref,
            name=f"Qin Border Unit {label} Commander",
            role_name="unit_commander",
            representation="exact",
            at=at,
        )
        _materialize_external_senior(
            planner,
            qin_force,
            command_index,
            formation_ref=str(formation["formation_ref"]),
            person_ref=deputy_ref,
            name=f"Qin Border Unit {label} Deputy",
            role_name="unit_deputy",
            representation="person_lite",
            at=at,
        )
        formation["commander_ref"] = commander_ref
        formation["deputy_ref"] = deputy_ref
        planner._assign_commander_index(commander_ref, str(formation["formation_ref"]))
        senior_refs.extend([commander_ref, deputy_ref])

        internal = _materialize_internal_roster(
            planner,
            qin_force,
            formation,
            role="line_infantry",
            prefix=f"qin_border_{label.lower()}",
            kind="qin_2000",
            at=at,
        )
        formation["command_roster"] = {
            "schema": "formation-command-roster.v1",
            "formation_ref": formation["formation_ref"],
            "materialized_at": at,
            "repair_id": _REPAIR_ID,
            "unit_commander_ref": commander_ref,
            "unit_commander_representation": "full_character",
            "unit_deputy_ref": deputy_ref,
            "unit_deputy_representation": "person_lite",
            "internal_assignments": internal,
            "internal_assignment_count": len(internal),
            "internal_deputies": 0,
            "conservation_rule": "unit commander/deputy are conserved Qin command-personnel outside fighting strength; internal commanders are represented soldiers inside the same 2,000 fighting bodies",
        }
        formation["command_structure"] = build_formation_command_structure(formation, rules)
        planner.put(_QIN_PATHS[index], formation)

    validate_cohort_ledger(qin_force)
    planner.put(_QIN_FORCE, qin_force)
    planner.put(_COMMAND_PERSONNEL_INDEX, command_index)

    for formation_ref in _QIN_REFS:
        planner._reconcile_formation_external_personnel(formation_ref)
    qin_force = copy.deepcopy(planner.read(_QIN_FORCE))
    validate_cohort_ledger(qin_force)

    gbg_force = planner._ct_force(_GBG_FORCE)
    gbg = copy.deepcopy(planner.read(_GBG_FORMATION))
    gbg_internal = _materialize_internal_roster(
        planner,
        gbg_force,
        gbg,
        role="great_bow_guard",
        prefix="tang_wei_gbg",
        kind="gbg_3000",
        at=at,
    )
    gbg["command_roster"] = {
        "schema": "formation-command-roster.v1",
        "formation_ref": _GBG_REF,
        "materialized_at": at,
        "repair_id": _REPAIR_ID,
        "unit_commander_ref": None,
        "unit_commander_representation": "full_character_pending_conserved_external_source",
        "unit_deputy_ref": None,
        "unit_deputy_representation": "person_lite_pending_conserved_external_source",
        "internal_assignments": gbg_internal,
        "internal_assignment_count": len(gbg_internal),
        "internal_deputies": 0,
        "conservation_rule": "all 39 internal commanders are represented members of the existing 3,000 Great Bow Guard fighting body; no Sword Manor officer or extra body is created",
    }
    gbg["command_structure"] = build_formation_command_structure(gbg, rules)
    validate_cohort_ledger(gbg_force)
    planner.put(_GBG_FORCE, gbg_force)
    planner.put(_GBG_FORMATION, gbg)

    house = copy.deepcopy(planner.read(_HOUSE))
    program = house.setdefault("administrative_programs", {}).get("great_bow_guard")
    if isinstance(program, MutableMapping):
        program["internal_command_node_target"] = 39
        program["internal_command_person_refs"] = [row["person_ref"] for row in gbg_internal]
        program["internal_command_candidate_status"] = "materialized_persistent_roster_from_conserved_great_bow_guard_fighters"
        program["unit_command_staffing_status"] = "pending_lawful_conserved_external_commander_and_deputy"
        program["command_roster_repair_id"] = _REPAIR_ID
    planner.put(_HOUSE, house)

    _update_operation_and_appointments(planner, at)

    history = copy.deepcopy(planner.read(HISTORY_INDEX_PATH))
    events = history.setdefault("events", [])
    if not isinstance(events, list):
        raise ValueError("v3 repair history owner is invalid")
    event_id = "repair_bundle_v3_" + str(command.digest)[:16]
    events.append({
        "event_id": event_id,
        "kind": "explicit_repair_bundle",
        "at": at,
        "repair_id": _REPAIR_ID,
        "reason": reason,
        "summary": "Completed the warfare command repair: Great Bow Guard is 3,000 fighting troops with 39 conserved person-lite internal commanders; the Qin Border Line is conserved as four persistent 2,000-fighter units with four exact unit commanders, four person-lite deputies, 104 internal person-lite commanders, and 112 separately conserved support personnel. Tang Wei remains the awaiting higher detachment commander until he reports. No Sword Manor officer or free manpower/equipment was created.",
        "affected_owners": [
            _GBG_FORCE,
            _GBG_FORMATION,
            _HOUSE,
            _QIN_FORCE,
            _QIN_STATE,
            _PLAYER,
            _QIN_OPERATION,
            *_QIN_PATHS,
            _COMMAND_PERSONNEL_INDEX,
            "state/index/owner-index.json",
            "state/index/location-formation-index.json",
            "state/runtime.json",
        ],
        "materialized_counts": {
            "qin_external_senior_command": 8,
            "qin_internal_commanders": 104,
            "great_bow_guard_internal_commanders": 39,
        },
    })
    write_history_index(planner, history)

    return {
        "repair_event": event_id,
        "great_bow_guard_personnel": 3000,
        "great_bow_guard_internal_commanders": 39,
        "great_bow_guard_external_unit_command_materialized": 0,
        "qin_persistent_units": 4,
        "qin_fighting_personnel": 8000,
        "qin_external_senior_command_personnel": 8,
        "qin_internal_commanders": 104,
        "qin_external_support_personnel": 112,
        "qin_fully_staffed_attached_personnel": 8120,
        "qin_senior_person_refs": senior_refs,
        "legacy_scale_result": legacy,
        "sword_manor_officers_created_or_seconded": 0,
        "fighting_manpower_created": 0,
        "equipment_created": 0,
    }


__all__ = ["apply_warfare_house_gbg_depth_v3"]

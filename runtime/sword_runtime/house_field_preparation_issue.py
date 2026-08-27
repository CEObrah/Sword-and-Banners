"""Materialize House Tang field-preparation into conserved formation custody.

The family preparation workflow owns authorization and reporting. Ordinary army
field subsistence is derived strategic support rather than formation inventory. This module
therefore issues only discrete expedition assets: ammunition and exact spare
outfitting from existing House stock. Nothing is minted here.
"""
from __future__ import annotations

import copy
import math
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.causal_event_store import read_causal_event_owner, write_causal_event_owner
from sword_runtime.formation_armory_issue import (
    house_armory_reserve_available,
    issue_house_armory_to_formation,
)

_RULES_PATH = "game/data/mechanics/house-tang-field-service.json"
_DEPOT_PATH = "state/depots/house-tang.json"
_HOUSE_PATH = "state/houses/house_tang.json"
_LOADOUT_INDEX_PATH = "game/data/loadouts.json"
_PLAYER_FORCE_PATH = "state/pforce/wei.json"



def _current_house_field_formations(planner: Any) -> list[str]:
    """Resolve Wei's current House-owned field formations from exact saved custody."""
    pforce = planner.read(_PLAYER_FORCE_PATH)
    refs = pforce.get("assigned_formations", []) if isinstance(pforce, Mapping) else []
    out: list[str] = []
    for ref in refs if isinstance(refs, list) else []:
        if not isinstance(ref, str):
            continue
        try:
            _path, formation = planner._load_formation(ref)
        except (FileNotFoundError, KeyError, ValueError):
            continue
        if str(formation.get("administrative_owner", "")) == "house_tang":
            out.append(ref)
    return sorted(set(out))

def _field_policy(planner: Any) -> Mapping[str, Any]:
    rules = planner.read(_RULES_PATH)
    policy = rules.get("field_service_preparation") if isinstance(rules, Mapping) else None
    if not isinstance(policy, Mapping):
        raise ValueError("House Tang field-service preparation policy is missing")
    return policy


def _loadout(planner: Any, formation: Mapping[str, Any]) -> Mapping[str, Any]:
    loadout_id = formation.get("registered_loadout_ref") or formation.get("equipment_loadout_id")
    if not isinstance(loadout_id, str) or not loadout_id:
        return {}
    index = planner.read(_LOADOUT_INDEX_PATH)
    rel = None
    records = index.get("records") if isinstance(index, Mapping) else None
    if isinstance(records, Mapping):
        rel = records.get(loadout_id)
    if not isinstance(rel, str):
        ids = index.get("ids", []) if isinstance(index, Mapping) else []
        template = index.get("path_template") if isinstance(index, Mapping) else None
        if loadout_id in ids and isinstance(template, str):
            rel = template.format(loadout_id=loadout_id)
    if not isinstance(rel, str):
        return {}
    document = planner.read(rel)
    loadout = document.get("loadout") if isinstance(document, Mapping) else None
    return loadout if isinstance(loadout, Mapping) else {}


def _issue_material_reserve(
    planner: Any,
    *,
    formation_ref: str,
    arrow_loads_total: int,
    at: str,
) -> dict[str, Any]:
    formation_path, formation0 = planner._load_formation(formation_ref)
    formation = copy.deepcopy(formation0)
    if str(formation.get("administrative_owner", "")) != "house_tang":
        raise PermissionError("House field preparation requires House Tang administrative ownership")
    location_ref = str(formation.get("location_ref", ""))
    depot = copy.deepcopy(planner.read(_DEPOT_PATH))
    if str(depot.get("location_ref", "")) != location_ref:
        raise PermissionError("House field preparation requires formation and garrison depot co-location")

    personnel = max(0, int(formation.get("personnel", 0)))
    loadout = _loadout(planner, formation)
    carried_arrows = max(0, int(loadout.get("carried_ammunition", 0)))
    logistics = formation.setdefault("logistics", {})
    if not isinstance(logistics, MutableMapping):
        raise ValueError("formation logistics ledger is invalid")
    stocks = depot.setdefault("stocks", {})
    if not isinstance(stocks, MutableMapping):
        raise ValueError("House garrison depot stock ledger is invalid")

    targets = {
        "war_arrows": personnel * carried_arrows * arrow_loads_total,
    }
    stock_keys = {"war_arrows": "war_arrows"}
    issued: dict[str, int] = {}
    shortfalls: dict[str, int] = {}
    for key, target in targets.items():
        current = max(0, int(logistics.get(key, 0)))
        need = max(0, target - current)
        stock_key = stock_keys[key]
        available = max(0, int(stocks.get(stock_key, 0)))
        amount = min(need, available)
        if amount:
            stocks[stock_key] = available - amount
            logistics[key] = current + amount
        issued[key] = amount
        remaining = max(0, need - amount)
        if remaining:
            shortfalls[key] = remaining


    planner.put(_DEPOT_PATH, depot)
    planner.put(formation_path, formation)
    return {
        "formation_ref": formation_ref,
        "targets": targets,
        "issued": issued,
        "shortfalls": shortfalls,
    }


def _issue_spare_equipment(
    planner: Any,
    *,
    formation_ref: str,
    spare_basis_points: int,
    eligible_fields: tuple[str, ...],
    at: str,
) -> dict[str, Any]:
    _path, formation = planner._load_formation(formation_ref)
    personnel = max(0, int(formation.get("personnel", 0)))
    desired = int(math.ceil(personnel * spare_basis_points / 10000.0))
    issued: dict[str, int] = {}
    shortfalls: dict[str, int] = {}
    standard_key = "outfitting_role_set"
    available = house_armory_reserve_available(planner, standard_key)
    amount = min(desired, available)
    if amount:
        issue_house_armory_to_formation(planner, formation_ref=formation_ref, item_key=standard_key, quantity=amount, actor_ref="char_tang_wei", at=at)
    issued[standard_key] = amount
    if amount < desired: shortfalls[standard_key] = desired - amount
    mounts = sum(max(0, int(v)) for v in (formation.get("mounts", {}) or {}).values())
    if mounts:
        mounted_desired = int(math.ceil(mounts * spare_basis_points / 10000.0))
        mounted_key = "outfitting_mounted_harness_set"
        mounted_available = house_armory_reserve_available(planner, mounted_key)
        mounted_amount = min(mounted_desired, mounted_available)
        if mounted_amount:
            issue_house_armory_to_formation(planner, formation_ref=formation_ref, item_key=mounted_key, quantity=mounted_amount, actor_ref="char_tang_wei", at=at)
        issued[mounted_key] = mounted_amount
        if mounted_amount < mounted_desired: shortfalls[mounted_key] = mounted_desired - mounted_amount
    return {"formation_ref": formation_ref, "desired_each": desired, "issued": issued, "shortfalls": shortfalls}


def _format_issue_summary(report: Mapping[str, Any], planner: Any) -> str:
    parts: list[str] = []
    by_formation = report.get("formations", {})
    if isinstance(by_formation, Mapping):
        for formation_ref in sorted(by_formation):
            row = by_formation.get(formation_ref)
            if not isinstance(row, Mapping):
                continue
            try:
                _path, formation = planner._load_formation(formation_ref)
                label = str(formation.get("name") or formation_ref)
            except Exception:
                label = formation_ref
            material = row.get("material", {}) if isinstance(row.get("material"), Mapping) else {}
            supplies = material.get("issued", {}) if isinstance(material.get("issued"), Mapping) else {}
            equipment = row.get("equipment", {}) if isinstance(row.get("equipment"), Mapping) else {}
            kit = equipment.get("issued", {}) if isinstance(equipment.get("issued"), Mapping) else {}
            kit_count = sum(max(0, int(value)) for value in kit.values())
            parts.append(
                f"{label} receives {int(supplies.get('war_arrows', 0))} additional war arrows; "
                f"{kit_count} aggregate spare role-outfitting sets are transferred from House armory reserve into formation custody."
            )
    shortfalls = report.get("shortfalls", [])
    if isinstance(shortfalls, list) and shortfalls:
        parts.append("Unfilled reserve shortfalls remain recorded for later lawful issue or transport: " + "; ".join(str(value) for value in shortfalls[:12]) + ".")
    else:
        parts.append("The registered departure reserve is fully issued from existing House stock.")
    parts.append("Tang Kai remains at Tang Manor under the already-persisted age-appropriate training disposition. No replacement mounts are issued by this standing field-service package unless Tang Wei separately orders remounts.")
    return " ".join(parts)[:4000]


def issue_house_field_preparation_package(
    planner: Any,
    *,
    response_event_ref: str,
    at: str,
) -> dict[str, Any]:
    house = copy.deepcopy(planner.read(_HOUSE_PATH))
    programs = house.setdefault("administrative_programs", {})
    prep = programs.get("wei_field_preparation")
    if not isinstance(prep, MutableMapping):
        raise ValueError("House field-preparation authorization is missing")
    if str(prep.get("principal_ref", "")) != "char_tang_wei":
        raise PermissionError("House field-preparation principal is not Tang Wei")
    if prep.get("material_issue_ref") == response_event_ref and prep.get("material_issued_at"):
        return {
            "policy_ref": str(prep.get("policy_ref") or f"{_RULES_PATH}#field_service_preparation"),
            "formations": {},
            "shortfalls": copy.deepcopy(list(prep.get("shortfalls", []))) if isinstance(prep.get("shortfalls"), list) else [],
            "status": str(prep.get("status", "issued_for_departure")),
        }

    policy = _field_policy(planner)
    arrow_loads_total = max(1, int(policy.get("arrow_loads_total", 2)))
    spare_basis_points = max(0, min(10000, int(policy.get("spare_equipment_basis_points", 500))))
    raw_fields = policy.get("spare_loadout_fields", [])
    eligible_fields = tuple(str(value) for value in raw_fields if isinstance(value, str) and value)

    formations: dict[str, Any] = {}
    shortfalls: list[str] = []
    formation_refs = _current_house_field_formations(planner)
    if not formation_refs:
        raise ValueError("Tang Wei has no current House-owned assigned field formations to prepare")
    for formation_ref in formation_refs:
        material = _issue_material_reserve(
            planner,
            formation_ref=formation_ref,
            arrow_loads_total=arrow_loads_total,
            at=at,
        )
        equipment = _issue_spare_equipment(
            planner,
            formation_ref=formation_ref,
            spare_basis_points=spare_basis_points,
            eligible_fields=eligible_fields,
            at=at,
        )
        for key, amount in material["shortfalls"].items():
            shortfalls.append(f"{formation_ref}:{key}:{amount}")
        for key, amount in equipment["shortfalls"].items():
            shortfalls.append(f"{formation_ref}:{key}:{amount}")
        formations[formation_ref] = {"material": material, "equipment": equipment}

    report = {
        "policy_ref": f"{_RULES_PATH}#field_service_preparation",
        "arrow_loads_total": arrow_loads_total,
        "spare_equipment_basis_points": spare_basis_points,
        "formations": formations,
        "shortfalls": shortfalls,
    }
    status = "issued_for_departure" if not shortfalls else "partially_issued_with_shortfalls"

    house = copy.deepcopy(planner.read(_HOUSE_PATH))
    programs = house.setdefault("administrative_programs", {})
    prep = programs.setdefault("wei_field_preparation", {})
    prep["status"] = status
    prep["equipment_issue_status"] = status
    prep["material_issue_ref"] = response_event_ref
    prep["material_issued_at"] = at
    prep["shortfalls"] = copy.deepcopy(shortfalls)
    prep.pop("material_issue_request_id", None)
    prep.pop("material_issue_report", None)
    prep.pop("manufacturing_truth", None)
    programs["wei_field_preparation"] = prep
    planner.put(_HOUSE_PATH, house)

    _path, owner = read_causal_event_owner(planner)
    event = owner.get("causal_events", {}).get(response_event_ref)
    if isinstance(event, MutableMapping):
        event["process_stage"] = status
        # Exact material truth remains on the House preparation program and the
        # depot/formation owners. The causal event carries presentation only.
        event["summary"] = _format_issue_summary(report, planner)
        write_causal_event_owner(planner, owner)

    return report


class HouseFieldPreparationIssueMixin:
    """Settle House field preparation as material issue without a fake decision wake."""

    # Due-host settlement is centrally dispatched by time_integration.py.


__all__ = [
    "HouseFieldPreparationIssueMixin",
    "issue_house_field_preparation_package",
]

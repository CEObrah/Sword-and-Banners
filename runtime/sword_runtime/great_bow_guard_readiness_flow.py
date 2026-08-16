"""Finish Tang Wei's Great Bow Guard field-preparation lifecycle.

The recruitment lifecycle conserves and trains the fighters.  This layer acts only
after an explicit House field-preparation request has already settled.  It forms
the accepted personal-force cohort into one persistent formation, issues only
exact House stock that actually exists, stages bounded campaign food/fodder, and
reports exact cohort means plus any remaining equipment shortfall.  It never
mints equipment, manpower, officers, mounts, or manufacturing capacity.
"""
from __future__ import annotations

import copy
import hashlib
import math
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.cohort_personnel import role_count, take_reserve_slices, validate_cohort_ledger
from sword_runtime.great_bow_guard_personal_integrity import repair_great_bow_guard_personal_ownership
from sword_runtime.recruitment_campaigns import REGISTRY_PATH
from sword_runtime.sim.calendar import CampaignTime

_RUNTIME_PATH = "state/runtime.json"
_HOUSE_PATH = "state/houses/house_tang.json"
_PERSONAL_FORCE_PATH = "state/forces/tang-wei-personal.json"
_INVENTORY_PATH = "state/inv/inventories.json"
_TREASURY_PATH = "state/treasury/treasury-house-tang.json"
_CHAMPIONS_PATH = "state/formations/tang-champions-first.json"
_RULES_PATH = "game/data/mechanics/house-tang-programs.json"
_LOCATION = "loc_tang_manor_training_ground"
_ROLE = "great_bow_guard"
_FORMATION_REF = "formation_tang_wei_great_bow_guard_first"
_FORMATION_PATH = "state/formations/tang-wei-great-bow-guard-first.json"
_PRIORITY = 45

_ITEM_SOURCES: dict[str, tuple[str, tuple[str, ...]]] = {
    "armor_tang": ("tang_restricted_equipment", ("Tang Armor unissued reserve",)),
    "helmet_tang": ("tang_restricted_equipment", ("Tang Helmet unissued reserve",)),
    "shield_tang": ("tang_restricted_equipment", ("Tang Shield unissued reserve",)),
    "weapon_bow_great_war": ("bows", ("Great War Bow armory reserve",)),
    "weapon_spear_long": ("tang_restricted_equipment", ("Long Spear unissued reserve", "Long Spear reserve")),
    "weapon_sword_one_hand_long": ("tang_restricted_equipment", ("One-Handed Long Sword unissued reserve", "Long Sword unissued reserve", "Long Sword reserve")),
}


def _event_write(planner: Any, event_ref: str, row: Mapping[str, Any], at: str) -> None:
    if isinstance(get_causal_event(planner, event_ref), Mapping):
        return
    payload = copy.deepcopy(dict(row))
    payload["provenance"] = {
        "kind": "causal_runtime_settlement",
        "source_owner_ref": "house_tang",
        "work_ref": event_ref,
        "late_catch_up": False,
    }
    _path, owner = read_causal_event_owner(planner)
    owner["causal_events"][event_ref] = payload
    owner.setdefault("runtime", {})["last_settled_at"] = at
    write_causal_event_owner(planner, owner)


def _ids(request_id: str) -> tuple[str, str, str]:
    digest = hashlib.sha256(f"gbg-field-readiness|{request_id}".encode("utf-8")).hexdigest()[:20]
    return (
        f"host_gbg_field_readiness_{digest}",
        f"event_gbg_field_readiness_due_{digest}",
        f"event_gbg_field_readiness_{digest}",
    )


def _programs(planner: Any) -> tuple[dict[str, Any], MutableMapping[str, Any], MutableMapping[str, Any]]:
    house = copy.deepcopy(planner.read(_HOUSE_PATH))
    programs = house.setdefault("administrative_programs", {})
    prep = programs.get("wei_field_preparation")
    great = programs.get("great_bow_guard")
    if not isinstance(prep, MutableMapping) or not isinstance(great, MutableMapping):
        raise ValueError("Great Bow Guard readiness requires exact House preparation and recruitment programs")
    return house, prep, great


def sync_great_bow_guard_readiness(planner: Any, runtime: dict[str, Any]) -> None:
    """Install one readiness settlement only after Wei's explicit prep request."""
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    try:
        _house, prep, great = _programs(planner)
    except ValueError:
        return
    if str(prep.get("status", "")) not in {"staging_and_shortfall_review", "readiness_staging"}:
        return
    request_id = str(prep.get("request_id", ""))
    if not request_id or prep.get("readiness_event_ref"):
        return
    campaign_ref = str(great.get("candidate_campaign_ref", ""))
    registry = planner.read(REGISTRY_PATH)
    campaign = registry.get("campaigns", {}).get(campaign_ref) if isinstance(registry, Mapping) else None
    if not isinstance(campaign, Mapping) or max(0, int(campaign.get("accepted_count", 0))) <= 0:
        return
    host_id, scheduler_event_id, event_ref = _ids(request_id)
    if isinstance(get_causal_event(planner, event_ref), Mapping) or host_id in hosts:
        return
    requested_at = prep.get("requested_at")
    now = CampaignTime.parse(str(runtime["world_time"]))
    start = CampaignTime.parse(str(requested_at)) if isinstance(requested_at, str) and requested_at else now
    rules = planner.read(_RULES_PATH)
    field = rules.get("field_preparation", {}) if isinstance(rules, Mapping) else {}
    staging_hours = max(1, int(field.get("minimum_staging_hours", 2)))
    due_raw = start.add_seconds(staging_hours * 3600)
    due = due_raw if due_raw > now else now
    hosts[host_id] = {
        "host_id": host_id,
        "kind": "great_bow_guard_field_readiness",
        "owner_ref": "house_tang",
        "request_id": request_id,
        "readiness_event_ref": event_ref,
        "recurrence_seconds": 0,
        "next_due": str(due),
        "resolved_through": str(now if now < due else due.add_seconds(-1)),
        "safe_through": str(due.add_seconds(-1)),
    }
    events.append({
        "event_id": scheduler_event_id,
        "kind": "great_bow_guard_field_readiness",
        "priority": _PRIORITY,
        "target_host": host_id,
        "due_at": str(due),
    })


def _mutable_facts(inventory: MutableMapping[str, Any], record_id: str) -> MutableMapping[str, Any]:
    for row in inventory.get("records", []):
        if isinstance(row, MutableMapping) and row.get("record_id") == record_id:
            facts = row.setdefault("facts", {})
            if isinstance(facts, MutableMapping):
                return facts
    raise ValueError(f"missing exact inventory record: {record_id}")


def _take_fact(facts: MutableMapping[str, Any], aliases: tuple[str, ...], quantity: int) -> int:
    need = max(0, int(quantity))
    if need <= 0:
        return 0
    for key in aliases:
        if key not in facts:
            continue
        available = max(0, int(facts.get(key, 0)))
        take = min(need, available)
        facts[key] = available - take
        return take
    return 0


def _cohort_total(cohort: Mapping[str, Any]) -> int:
    return sum(max(0, int(value)) for value in cohort.get("reserve_by_location", {}).values()) + sum(
        max(0, int(value)) for value in cohort.get("allocated_by_formation", {}).values()
    )


def _weighted_map(rows: list[tuple[int, Mapping[str, Any]]], key: str) -> dict[str, float]:
    totals: dict[str, float] = {}
    weights: dict[str, int] = {}
    for count, cohort in rows:
        values = cohort.get(key)
        if not isinstance(values, Mapping) or count <= 0:
            continue
        for name, raw in values.items():
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                continue
            label = str(name)
            totals[label] = totals.get(label, 0.0) + float(raw) * count
            weights[label] = weights.get(label, 0) + count
    return {name: round(totals[name] / max(1, weights[name]), 3) for name in sorted(totals)}


def _cohort_stats(force: Mapping[str, Any]) -> dict[str, Any]:
    ledger = force.get("cohort_ledger")
    cohorts = ledger.get("cohorts", {}) if isinstance(ledger, Mapping) else {}
    rows: list[tuple[int, Mapping[str, Any]]] = []
    for cohort in cohorts.values() if isinstance(cohorts, Mapping) else []:
        if not isinstance(cohort, Mapping) or str(cohort.get("role", "")) != _ROLE:
            continue
        count = _cohort_total(cohort)
        if count > 0:
            rows.append((count, cohort))
    total = sum(count for count, _cohort in rows)
    if total <= 0:
        return {"personnel": 0, "attribute_means": {}, "skill_means": {}, "aptitude_means": {}}
    training = round(sum(float(row.get("verified_training_hours_per_person", 0.0) or 0.0) * count for count, row in rows) / total, 3)
    exposure = round(sum(float(row.get("verified_role_exposure_hours_per_person", 0.0) or 0.0) * count for count, row in rows) / total, 3)
    age_means = []
    age_mins = []
    age_maxs = []
    for count, row in rows:
        age = row.get("age_distribution") if isinstance(row.get("age_distribution"), Mapping) else {}
        if isinstance(age.get("mean"), (int, float)):
            age_means.append((count, float(age["mean"])))
        if isinstance(age.get("min"), (int, float)):
            age_mins.append(float(age["min"]))
        if isinstance(age.get("max"), (int, float)):
            age_maxs.append(float(age["max"]))
    return {
        "personnel": total,
        "age_distribution": {
            "mean": round(sum(c * value for c, value in age_means) / max(1, sum(c for c, _ in age_means)), 3) if age_means else None,
            "min": min(age_mins) if age_mins else None,
            "max": max(age_maxs) if age_maxs else None,
        },
        "aptitude_means": _weighted_map(rows, "aptitude_means"),
        "attribute_means": _weighted_map(rows, "attribute_means"),
        "skill_means": _weighted_map(rows, "skill_means"),
        "verified_training_hours_per_person": training,
        "verified_role_exposure_hours_per_person": exposure,
    }


def _format_map(values: Mapping[str, Any], names: tuple[str, ...] | None = None) -> str:
    keys = names if names is not None else tuple(sorted(str(key) for key in values))
    parts = []
    for name in keys:
        value = values.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parts.append(f"{name} {float(value):.1f}")
    return ", ".join(parts)


def _formation_or_create(planner: Any, force: MutableMapping[str, Any], n: int, at: str) -> tuple[str, MutableMapping[str, Any], bool]:
    owner_index = planner.read("state/index/owner-index.json")
    existing_path = owner_index.get("owners", {}).get(_FORMATION_REF) if isinstance(owner_index, Mapping) else None
    if isinstance(existing_path, str):
        formation = copy.deepcopy(planner.read(existing_path))
        return existing_path, formation, False
    local = force.get("available_by_location", {}).get(_LOCATION, {})
    if not isinstance(local, Mapping) or int(local.get(_ROLE, 0)) < n or role_count(force, _ROLE) < n:
        raise ValueError("Great Bow Guard readiness cannot find all accepted personal-force fighters at Sword Manor")
    planner._take_force_personnel(force, _ROLE, n, _LOCATION)
    force.setdefault("allocated_to_formations", {})[_FORMATION_REF] = {"personnel": n, "role": _ROLE}
    cohort_slices = take_reserve_slices(force, role=_ROLE, count=n, location_ref=_LOCATION, formation_ref=_FORMATION_REF)
    admin_owner = str(force.get("administrative_owner", "char_tang_wei"))
    formation: MutableMapping[str, Any] = {
        "schema": "sword-formation",
        "formation_ref": _FORMATION_REF,
        "name": "Tang Wei's Great Bow Guard",
        "owner_force_ref": "force_tang_wei_personal",
        "administrative_owner": admin_owner,
        "command_authority": "char_tang_wei",
        "commander_ref": None,
        "personnel": n,
        "composition": {_ROLE: n},
        "cohort_composition": cohort_slices,
        "location_ref": _LOCATION,
        "doctrine_ref": None,
        "training_ref": None,
        "doctrine_behavior": {"casualty_tolerance": "moderate", "reserve_commitment": 50},
        "training_progress": 0,
        "readiness": 40,
        "morale": 60,
        "cohesion": 35,
        "fatigue": 0,
        "experience": "new",
        "mobilized": False,
        "status": "forming",
        "logistics": {"food_kg": 0, "fodder_kg": 0, "war_arrows": 0, "war_bolts": 0},
        "mounts": {},
        "created_at": at,
        "formation_origin": "Great Bow Guard accepted personal-force cohort materialized for Wei's explicit Qin campaign preparation",
    }
    planner._set_equipment_units(formation, {_ROLE: 0})
    planner.put(_FORMATION_PATH, formation)
    planner._register_owner(_FORMATION_REF, _FORMATION_PATH)
    planner._index_formation_location(_FORMATION_REF, None, _LOCATION)
    validate_cohort_ledger(force)
    return _FORMATION_PATH, formation, True


def settle_great_bow_guard_readiness(planner: Any, host: Mapping[str, Any], at: str) -> dict[str, Any] | None:
    event_ref = str(host.get("readiness_event_ref", ""))
    if not event_ref or isinstance(get_causal_event(planner, event_ref), Mapping):
        return None

    repair_great_bow_guard_personal_ownership(planner, at=at)
    house, prep, great = _programs(planner)
    personal_force = copy.deepcopy(planner.read(_PERSONAL_FORCE_PATH))
    n = role_count(personal_force, _ROLE)
    allocated = personal_force.get("allocated_to_formations", {}).get(_FORMATION_REF)
    if isinstance(allocated, Mapping):
        n = int(allocated.get("personnel", n))
    if n <= 0:
        n = max(0, int(great.get("accepted_fighters", 0)))
    if n <= 0:
        raise ValueError("Great Bow Guard readiness has no conserved accepted fighters")
    stats = _cohort_stats(personal_force)

    formation_path, formation, created = _formation_or_create(planner, personal_force, n, at)
    # Recompute after formation allocation because cohort totals are invariant but
    # reserve/allocated custody has changed.
    stats = _cohort_stats(personal_force)

    inventory = copy.deepcopy(planner.read(_INVENTORY_PATH))
    facts_by_record: dict[str, MutableMapping[str, Any]] = {}
    issued: dict[str, int] = {}
    shortfalls: dict[str, int] = {}
    for item_key, (record_id, aliases) in _ITEM_SOURCES.items():
        facts = facts_by_record.setdefault(record_id, _mutable_facts(inventory, record_id))
        take = _take_fact(facts, aliases, n)
        issued[item_key] = take
        if take < n:
            shortfalls[item_key] = n - take

    rules = planner.read(_RULES_PATH)
    great_rules = rules.get("great_bow_guard", {}) if isinstance(rules, Mapping) else {}
    field_rules = rules.get("field_preparation", {}) if isinstance(rules, Mapping) else {}
    arrow_min = max(0, int(great_rules.get("initial_field_war_arrows_minimum", 0)))
    ammunition = facts_by_record.setdefault("ammunition", _mutable_facts(inventory, "ammunition"))
    arrows = _take_fact(ammunition, ("War Arrows strategic reserve",), arrow_min)
    if arrows < arrow_min:
        shortfalls["ammo_arrow_war"] = arrow_min - arrows

    required_items = len(_ITEM_SOURCES)
    issued_item_units = sum(issued.values())
    item_completeness = issued_item_units / max(1, n * required_items)
    equivalent_units = max(0, min(n, int(math.floor(item_completeness * n + 1e-9))))
    planner._set_equipment_units(formation, {_ROLE: equivalent_units})
    formation["equipment_completeness"] = f"{min(1.0, item_completeness):.4f}"
    formation["issued_loadout_items"] = issued
    formation["registered_loadout_ref"] = "loadout_tang_great_bow_guard"
    formation["logistics"]["war_arrows"] = int(formation.get("logistics", {}).get("war_arrows", 0)) + arrows

    treasury = copy.deepcopy(planner.read(_TREASURY_PATH))
    days = max(1, int(field_rules.get("departure_reserve_days", 7)))
    food_rate = max(0.0, float(field_rules.get("food_kg_per_person_day", 1.5)))
    fodder_rate = max(0.0, float(field_rules.get("fodder_kg_per_mount_day", 4.0)))
    gbg_food_need = int(math.ceil(n * food_rate * days - 1e-9))
    gbg_food = min(gbg_food_need, max(0, int(treasury.get("food_kg", 0))))
    treasury["food_kg"] = int(treasury.get("food_kg", 0)) - gbg_food
    formation["logistics"]["food_kg"] = int(formation.get("logistics", {}).get("food_kg", 0)) + gbg_food
    if gbg_food < gbg_food_need:
        shortfalls["gbg_food_kg"] = gbg_food_need - gbg_food

    champions = copy.deepcopy(planner.read(_CHAMPIONS_PATH))
    champions_n = max(0, int(champions.get("personnel", 0)))
    champions_food_target = int(math.ceil(champions_n * food_rate * days - 1e-9))
    champions_food_need = max(0, champions_food_target - int(champions.get("logistics", {}).get("food_kg", 0)))
    champions_food = min(champions_food_need, max(0, int(treasury.get("food_kg", 0))))
    treasury["food_kg"] = int(treasury.get("food_kg", 0)) - champions_food
    champions.setdefault("logistics", {})["food_kg"] = int(champions.get("logistics", {}).get("food_kg", 0)) + champions_food
    champion_mounts = sum(max(0, int(value)) for value in champions.get("mounts", {}).values()) if isinstance(champions.get("mounts"), Mapping) else 0
    champions_fodder_target = int(math.ceil(champion_mounts * fodder_rate * days - 1e-9))
    champions_fodder_need = max(0, champions_fodder_target - int(champions.get("logistics", {}).get("fodder_kg", 0)))
    champions_fodder = min(champions_fodder_need, max(0, int(treasury.get("fodder_kg", 0))))
    treasury["fodder_kg"] = int(treasury.get("fodder_kg", 0)) - champions_fodder
    champions["logistics"]["fodder_kg"] = int(champions.get("logistics", {}).get("fodder_kg", 0)) + champions_fodder
    if champions_food < champions_food_need:
        shortfalls["champions_food_kg"] = champions_food_need - champions_food
    if champions_fodder < champions_fodder_need:
        shortfalls["champions_fodder_kg"] = champions_fodder_need - champions_fodder

    formation["status"] = "forming" if shortfalls else "deployed"
    formation["field_preparation"] = {
        "at": at,
        "departure_reserve_days": days,
        "equipment_shortfalls": copy.deepcopy(shortfalls),
        "house_support_ref": "house_tang",
    }
    planner.put(_PERSONAL_FORCE_PATH, personal_force)
    planner.put(formation_path, formation)
    planner.put(_INVENTORY_PATH, inventory)
    planner.put(_TREASURY_PATH, treasury)
    planner.put(_CHAMPIONS_PATH, champions)

    campaign_ref = str(great.get("candidate_campaign_ref", ""))
    registry = copy.deepcopy(planner.read(REGISTRY_PATH))
    campaign = registry.get("campaigns", {}).get(campaign_ref) if isinstance(registry, Mapping) else None
    if isinstance(campaign, MutableMapping):
        campaign["formation_ref"] = _FORMATION_REF
        campaign["equipment_issue_status"] = "complete" if not shortfalls else "partial_shortfall"
        campaign["issued_loadout_items"] = copy.deepcopy(issued)
        campaign["field_war_arrows"] = arrows
        campaign["status"] = "accepted_formed" if not shortfalls else "accepted_formation_staged"
        planner.put(REGISTRY_PATH, registry)

    prep["status"] = "prepared" if not shortfalls else "ready_with_shortfalls"
    prep["readiness_event_ref"] = event_ref
    prep["great_bow_guard_formation_ref"] = _FORMATION_REF
    prep["equipment_issue_status"] = "complete" if not shortfalls else "partial_shortfall"
    prep["issued_loadout_items"] = copy.deepcopy(issued)
    prep["field_war_arrows"] = arrows
    prep["supply_staging"] = {
        "departure_reserve_days": days,
        "great_bow_guard_food_kg": gbg_food,
        "champions_food_kg": champions_food,
        "champions_fodder_kg": champions_fodder,
    }
    prep["remaining_shortfalls"] = copy.deepcopy(shortfalls)
    prep["great_bow_guard_stats"] = copy.deepcopy(stats)
    great["formation_ref"] = _FORMATION_REF
    great["field_readiness_status"] = prep["status"]
    great["player_visible_stats"] = copy.deepcopy(stats)
    house["administrative_programs"]["wei_field_preparation"] = prep
    house["administrative_programs"]["great_bow_guard"] = great
    planner.put(_HOUSE_PATH, house)

    attrs = _format_map(stats.get("attribute_means", {}), ("Strength", "Agility", "Endurance", "Toughness", "Coordination", "Awareness", "Composure", "Intelligence", "Presence"))
    skills = _format_map(stats.get("skill_means", {}), ("Bow", "Formation Fighting", "Shield", "Defense", "Spear", "Sword", "Athletics", "Leadership", "Mass Combat", "Tactics"))
    shortfall_text = ", ".join(f"{key} {value}" for key, value in sorted(shortfalls.items())) if shortfalls else "none"
    summary = (
        f"House Tang completes the next field-preparation stage for Tang Wei. The {n} Great Bow Guard are now conserved in {_FORMATION_REF} under Tang Wei's personal force; House Tang remains sponsor and supplier, not troop owner. "
        f"Their exact cohort profile is based on {float(stats.get('verified_training_hours_per_person', 0.0)):.1f} verified training hours per fighter. Mean attributes: {attrs}. Mean combat skills: {skills}. "
        f"Exact House stock issued into their staging formation: " + ", ".join(f"{key} {value}" for key, value in sorted(issued.items())) + f"; field war arrows {arrows}. "
        f"Campaign food staged for {days} days: Great Bow Guard {gbg_food} kg, Tang Champions {champions_food} kg; Champions fodder {champions_fodder} kg based on their exact registered mounts. Remaining shortfalls: {shortfall_text}. "
        + ("The Great Bow Guard are not fully field-ready until those shortfalls are lawfully procured or Wei deliberately accepts a partial loadout." if shortfalls else "The registered Great Bow Guard loadout and bounded departure supply are complete; no extra officers, mounts or manufacturing output were invented.")
    )[:4000]

    _event_write(planner, event_ref, {
        "event_ref": event_ref,
        "kind": "institutional_response",
        "status": "triggered",
        "due_at": at,
        "triggered_at": at,
        "actor_ref": "char_tang_zhu",
        "target_ref": "char_tang_wei",
        "basis_goal": "Complete Tang Wei's explicitly requested Great Bow Guard and Champions field preparation from exact conserved manpower, stock and House stores",
        "process_kind": "great_bow_guard_field_readiness",
        "process_stage": prep["status"],
        "formation_ref": _FORMATION_REF,
        "great_bow_guard_stats": copy.deepcopy(stats),
        "issued_loadout_items": copy.deepcopy(issued),
        "remaining_shortfalls": copy.deepcopy(shortfalls),
        "summary": summary,
        "delivery": {
            "target_ref": "char_tang_wei",
            "location_ref": str(planner.read("state/player.json").get("location", "")),
            "route": "House Tang field quartermaster and family counsel",
        },
    }, at)
    digest = hashlib.sha256(f"{event_ref}|{at}".encode("utf-8")).hexdigest()[:20]
    return {
        "wake_ref": f"wake.house.gbg_readiness.{digest}",
        "kind": "campaign_event",
        "at": at,
        "campaign_event_ref": event_ref,
        "formation_ref": _FORMATION_REF,
        "reason": summary,
    }


class GreatBowGuardReadinessFlowMixin:
    """Schedule and settle explicit Great Bow Guard campaign preparation."""

    def _advance_runtime(self, target_text: str) -> dict[str, Any]:
        runtime = copy.deepcopy(self.read(_RUNTIME_PATH))
        sync_great_bow_guard_readiness(self, runtime)
        self.put(_RUNTIME_PATH, runtime)
        return super()._advance_runtime(target_text)

    def _run_due_host(self, host: Mapping[str, Any], due_text: str) -> None:
        if host.get("kind") != "great_bow_guard_field_readiness":
            return super()._run_due_host(host, due_text)
        wake = settle_great_bow_guard_readiness(self, host, due_text)
        if isinstance(wake, dict):
            wake["target_host"] = self._active_host_id
            wake["event_id"] = self._active_event_id
        self._pending_wake_created = wake


__all__ = ["GreatBowGuardReadinessFlowMixin", "settle_great_bow_guard_readiness", "sync_great_bow_guard_readiness"]

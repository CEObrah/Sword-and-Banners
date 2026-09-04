"""Population-backed aggregate House lineage representation.

House lineage cohorts are kinship classifications over bodies already counted by
an exact state population owner. State demography owns births and deaths. House
settlement may classify only a bounded share of those already-settled events.
Materialization turns one anonymous House member into one exact person without
changing either House headcount or parent population.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping, MutableMapping
from typing import Any

from sword_runtime.development import age_years
from sword_runtime.history_store import write_history_index
from sword_runtime.sim.calendar import CampaignTime

INDEX_PATH = "state/index/house-lineage-index.json"
RULES_PATH = "game/data/mechanics/house-lineage.json"
HISTORY_PATH = "state/history/events/index.json"
_AGE_BANDS = ("children", "adults", "elders")


def _state_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("state_", "")


def _take_with_credit(count: int, rate_bp: int, years: int, credit: int) -> tuple[int, int]:
    raw = max(0, int(count)) * max(0, int(rate_bp)) * max(0, int(years)) + max(0, int(credit))
    return raw // 10000, raw % 10000


def _person_living(person: Mapping[str, Any]) -> bool:
    return str(person.get("life_status", person.get("status", "active"))).lower() not in {"dead", "deceased"}


def _age_band(person: Mapping[str, Any], at: CampaignTime) -> str:
    age = age_years(person, at)
    if age < 16:
        return "children"
    if age < 60:
        return "adults"
    return "elders"


def _exact_counts(planner: Any, refs: list[str], at: str) -> tuple[dict[str, int], list[str]]:
    counts = {key: 0 for key in _AGE_BANDS}
    living: list[str] = []
    review = CampaignTime.parse(str(at))
    for ref in sorted(set(str(value) for value in refs if isinstance(value, str) and value)):
        try:
            person = planner.read(planner.owner_path(ref))
        except (KeyError, ValueError, FileNotFoundError):
            continue
        if not isinstance(person, Mapping) or not _person_living(person):
            continue
        living.append(ref)
        counts[_age_band(person, review)] += 1
    return counts, living


def register_house_lineage_route(planner: Any, *, house_ref: str, house_path: str, state: str) -> None:
    idx = copy.deepcopy(planner.read(INDEX_PATH))
    rows = idx.setdefault("by_state", {}).setdefault(_state_key(state), {})
    rows[str(house_ref)] = str(house_path)
    idx["house_count"] = sum(len(value) for value in idx.get("by_state", {}).values() if isinstance(value, Mapping))
    planner.put(INDEX_PATH, idx)


def ensure_house_lineage_representation(planner: Any, house: MutableMapping[str, Any], *, at: str) -> None:
    """Normalize current lineage totals into exact + anonymous members backed by population."""
    cohort = house.setdefault("lineage_cohort", {})
    if not isinstance(cohort, MutableMapping):
        raise ValueError("House lineage_cohort must be an object")
    state = _state_key(house.get("state"))
    if not state:
        raise ValueError("House lineage requires state")

    refs = [str(value) for value in cohort.get("exact_member_refs", []) if isinstance(value, str) and value] if isinstance(cohort.get("exact_member_refs"), list) else []
    exact_counts, living_refs = _exact_counts(planner, refs, at)
    raw_unmat = cohort.get("unmaterialized_members")
    if isinstance(raw_unmat, Mapping):
        unmat = {key: max(0, int(raw_unmat.get(key, 0))) for key in _AGE_BANDS}
    else:
        unmat = {key: max(0, int(cohort.get(key, 0)) - exact_counts[key]) for key in _AGE_BANDS}

    leader_ref = house.get("leader_ref")
    if isinstance(leader_ref, str) and leader_ref and leader_ref not in living_refs:
        try:
            leader = planner.read(planner.owner_path(leader_ref))
        except (KeyError, ValueError, FileNotFoundError):
            leader = None
        if isinstance(leader, Mapping) and _person_living(leader):
            band = _age_band(leader, CampaignTime.parse(str(at)))
            if unmat[band] > 0:
                unmat[band] -= 1
            living_refs.append(leader_ref)
            exact_counts[band] += 1

    cohort["exact_member_refs"] = sorted(set(living_refs))
    cohort["unmaterialized_members"] = unmat
    cohort["population_ref"] = f"population_{state}"
    cohort["aggregate_marriages"] = max(0, int(cohort.get("aggregate_marriages", 0)))
    for key in _AGE_BANDS:
        cohort[key] = unmat[key] + exact_counts[key]


def recompute_house_lineage(planner: Any, house: MutableMapping[str, Any], *, at: str) -> None:
    cohort = house.setdefault("lineage_cohort", {})
    unmat = cohort.get("unmaterialized_members") if isinstance(cohort.get("unmaterialized_members"), Mapping) else {}
    anonymous = {key: max(0, int(unmat.get(key, 0))) for key in _AGE_BANDS}
    exact_counts, living_refs = _exact_counts(
        planner,
        [str(value) for value in cohort.get("exact_member_refs", []) if isinstance(value, str)] if isinstance(cohort.get("exact_member_refs"), list) else [],
        at,
    )
    cohort["exact_member_refs"] = living_refs
    cohort["unmaterialized_members"] = anonymous
    for key in _AGE_BANDS:
        cohort[key] = anonymous[key] + exact_counts[key]



def register_exact_house_lineage_member(
    planner: Any,
    house: MutableMapping[str, Any],
    *,
    person_ref: str,
    at: str,
) -> None:
    """Register an already-exact living person in one House lineage.

    This changes classification only. It never creates an anonymous body or
    changes the parent population owner.
    """
    ensure_house_lineage_representation(planner, house, at=at)
    cohort = house["lineage_cohort"]
    refs = [str(value) for value in cohort.get("exact_member_refs", []) if isinstance(value, str) and value]
    if person_ref not in refs:
        refs.append(person_ref)
    cohort["exact_member_refs"] = sorted(set(refs))
    recompute_house_lineage(planner, house, at=at)

def settle_state_house_lineages(
    planner: Any,
    *,
    state: str,
    at: str,
    years: int,
    parent_births: int,
    parent_deaths: int,
) -> dict[str, int]:
    """Allocate only already-created/removed parent demographic bodies to Houses."""
    years = max(0, int(years))
    if years <= 0:
        return {"births": 0, "deaths": 0, "matured": 0, "aged_to_elder": 0}
    state_key = _state_key(state)
    idx = copy.deepcopy(planner.read(INDEX_PATH))
    if not isinstance(idx, Mapping):
        return {"births": 0, "deaths": 0, "matured": 0, "aged_to_elder": 0}

    # The lineage index is only a route cache. Recover this state's lineage
    # Houses from the bounded authoritative owner index so losing one cache row
    # cannot permanently freeze that House's anonymous demography.
    owners_doc = planner.read("state/index/owner-index.json")
    owners = owners_doc.get("owners", {}) if isinstance(owners_doc, Mapping) else {}
    exact_routes: dict[str, str] = {}
    for house_ref, house_path in sorted(owners.items()) if isinstance(owners, Mapping) else ():
        if not isinstance(house_ref, str) or not isinstance(house_path, str) or not house_path.startswith("state/houses/"):
            continue
        house = planner.read_optional(house_path) if hasattr(planner, "read_optional") else None
        if house is None:
            try:
                house = planner.read(house_path)
            except (KeyError, ValueError, FileNotFoundError):
                continue
        if not isinstance(house, Mapping) or not isinstance(house.get("lineage_cohort"), Mapping):
            continue
        if _state_key(house.get("state")) != state_key:
            continue
        exact_routes[house_ref] = house_path

    by_state = idx.setdefault("by_state", {})
    prior_routes = by_state.get(state_key, {}) if isinstance(by_state.get(state_key), Mapping) else {}
    if dict(prior_routes) != exact_routes:
        by_state[state_key] = dict(exact_routes)
        idx["house_count"] = sum(len(value) for value in by_state.values() if isinstance(value, Mapping))
        planner.put(INDEX_PATH, idx)
    routes: Mapping[str, Any] = exact_routes
    rules = planner.read(RULES_PATH).get("aggregate_lineage", {})
    birth_bp = max(0, int(rules.get("births_per_marriage_basis_points_per_year", 1800)))
    mature_bp = max(0, int(rules.get("child_maturation_basis_points_per_year", 625)))
    elder_bp = max(0, int(rules.get("adult_to_elder_basis_points_per_year", 227)))
    child_death_bp = max(0, int(rules.get("child_mortality_basis_points_per_year", 120)))
    adult_death_bp = max(0, int(rules.get("adult_mortality_basis_points_per_year", 50)))
    elder_death_bp = max(0, int(rules.get("elder_mortality_basis_points_per_year", 667)))
    remaining_births = max(0, int(parent_births))
    remaining_deaths = max(0, int(parent_deaths))
    totals = {"births": 0, "deaths": 0, "matured": 0, "aged_to_elder": 0}

    for house_ref, house_path in sorted((str(key), str(value)) for key, value in routes.items()):
        # The lineage index is authority:false routing only.  Revalidate both
        # the exact owner route and the House's actual state before consuming
        # this state's already-settled demographic births/deaths.  A stale
        # cross-state bucket must never reclassify Qin bodies into a Chu House.
        try:
            exact_path = str(planner.owner_path(house_ref))
        except (KeyError, ValueError, FileNotFoundError):
            continue
        if exact_path != house_path:
            continue
        house = copy.deepcopy(planner.read(exact_path))
        if not isinstance(house, Mapping) or _state_key(house.get("state")) != state_key:
            continue
        ensure_house_lineage_representation(planner, house, at=at)
        cohort = house["lineage_cohort"]
        unmat = cohort["unmaterialized_members"]
        runtime = house.setdefault("lineage_runtime", {})
        credit = runtime.setdefault("demography_credit_bp", {})
        if sum(max(0, int(value)) for value in unmat.values()) <= 0:
            if not credit:
                house.pop("lineage_runtime", None)
            planner.put(exact_path, house)
            continue

        children = max(0, int(unmat.get("children", 0)))
        adults = max(0, int(unmat.get("adults", 0)))
        elders = max(0, int(unmat.get("elders", 0)))
        marriages = min(max(0, int(cohort.get("aggregate_marriages", 0))), adults // 2)

        births, credit["birth"] = _take_with_credit(marriages, birth_bp, years, int(credit.get("birth", 0)))
        births = min(births, remaining_births)
        children += births
        remaining_births -= births

        mature, credit["mature"] = _take_with_credit(children, mature_bp, years, int(credit.get("mature", 0)))
        mature = min(children, mature)
        children -= mature
        adults += mature

        aged, credit["elder"] = _take_with_credit(adults, elder_bp, years, int(credit.get("elder", 0)))
        aged = min(adults, aged)
        adults -= aged
        elders += aged

        child_deaths, credit["child_death"] = _take_with_credit(children, child_death_bp, years, int(credit.get("child_death", 0)))
        adult_deaths, credit["adult_death"] = _take_with_credit(adults, adult_death_bp, years, int(credit.get("adult_death", 0)))
        elder_deaths, credit["elder_death"] = _take_with_credit(elders, elder_death_bp, years, int(credit.get("elder_death", 0)))
        desired = min(children, child_deaths) + min(adults, adult_deaths) + min(elders, elder_deaths)
        deaths = min(desired, remaining_deaths)
        dead_elders = min(elders, min(deaths, elder_deaths))
        left = deaths - dead_elders
        dead_children = min(children, min(left, child_deaths))
        left -= dead_children
        dead_adults = min(adults, left)
        elders -= dead_elders
        children -= dead_children
        adults -= dead_adults
        applied_deaths = dead_elders + dead_children + dead_adults
        remaining_deaths -= applied_deaths

        unmat.update({"children": children, "adults": adults, "elders": elders})
        # Anonymous marriages are a compact demographic proxy, not exact unions.
        cohort["aggregate_marriages"] = min(adults // 2, max(0, marriages + mature // 4 - dead_adults // 2))
        recompute_house_lineage(planner, house, at=at)
        planner.put(exact_path, house)
        totals["births"] += births
        totals["deaths"] += applied_deaths
        totals["matured"] += mature
        totals["aged_to_elder"] += aged

    return totals


def materialize_house_lineage_member(
    planner: Any,
    *,
    house_ref: str,
    person_ref: str,
    name: str,
    age_band: str,
    at: str,
) -> dict[str, Any]:
    """Reclassify one anonymous lineage body into one exact named person."""
    if age_band not in _AGE_BANDS:
        raise ValueError("age_band must be children, adults, or elders")
    house_path = planner.owner_path(house_ref)
    house = copy.deepcopy(planner.read(house_path))
    ensure_house_lineage_representation(planner, house, at=at)
    cohort = house["lineage_cohort"]
    unmat = cohort["unmaterialized_members"]
    if max(0, int(unmat.get(age_band, 0))) <= 0:
        raise ValueError("House lineage has no anonymous conserved body in requested age band")
    if person_ref in planner.read("state/index/owner-index.json").get("owners", {}):
        raise ValueError("person_ref already exists")

    state = _state_key(house.get("state"))
    now = CampaignTime.parse(str(at))
    seed = hashlib.sha256(f"{house_ref}|{person_ref}|{age_band}|{at}".encode()).hexdigest()
    age = (8 + int(seed[:2], 16) % 8) if age_band == "children" else ((18 + int(seed[:2], 16) % 38) if age_band == "adults" else (60 + int(seed[:2], 16) % 21))
    birth_year = now.bce_year + age
    location = house.get("location_ref")
    if not isinstance(location, str) or not location:
        leader_ref = house.get("leader_ref")
        leader = None
        if isinstance(leader_ref, str):
            try:
                leader = planner.read(planner.owner_path(leader_ref))
            except (KeyError, ValueError, FileNotFoundError):
                pass
        if isinstance(leader, Mapping):
            location = leader.get("current_location") or leader.get("location_ref")
    if not isinstance(location, str) or not location:
        location = f"loc_{state}"

    person_path = f"state/char/{person_ref.replace('char_', '').replace('_', '-')}.json"
    person = {
        "schema": "sword-materialized-person",
        "owner_id": person_ref,
        "owner_type": "character",
        "id": person_ref,
        "name": str(name),
        "state": state,
        "birth_date": f"{birth_year}-BCE-{now.month:02d}-{now.day:02d}",
        "status": "alive",
        "life_status": "active",
        "health_status": "healthy",
        "current_location": str(location),
        "house_ref": house_ref,
        "attributes": {},
        "skills": {},
        "aptitude": {"physical_learning": 100, "technical_learning": 100, "tactical_learning": 100, "academic_learning": 100, "social_learning": 100},
        "development_state": {},
        "lineage_provenance": {"house_ref": house_ref, "population_ref": f"population_{state}", "source_representation": "aggregate_population_subset", "age_band": age_band, "materialized_at": str(at)},
    }
    total_before = sum(max(0, int(cohort.get(key, 0))) for key in _AGE_BANDS)
    unmat[age_band] = int(unmat.get(age_band, 0)) - 1
    refs = [str(value) for value in cohort.get("exact_member_refs", []) if isinstance(value, str)]
    refs.append(person_ref)
    cohort["exact_member_refs"] = sorted(set(refs))
    planner.put(person_path, person)
    planner._register_owner(person_ref, person_path)
    planner._ensure_person_life_host(person_ref, now)
    recompute_house_lineage(planner, house, at=at)
    if sum(max(0, int(cohort.get(key, 0))) for key in _AGE_BANDS) != total_before:
        raise ValueError("House lineage materialization changed conserved headcount")
    planner.put(house_path, house)
    history = copy.deepcopy(planner.read(HISTORY_PATH))
    event_id = "lineage_materialization_" + seed[:16]
    history.setdefault("events", []).append({
        "event_id": event_id,
        "kind": "house_lineage_materialization",
        "at": str(at),
        "house_ref": house_ref,
        "person_ref": person_ref,
        "age_band": age_band,
        "population_ref": f"population_{state}",
        "population_delta": 0,
        "house_headcount_delta": 0,
    })
    write_history_index(planner, history)
    return {"house_ref": house_ref, "person_ref": person_ref, "age_band": age_band, "population_delta": 0, "house_headcount_delta": 0, "event_id": event_id}


__all__ = [
    "INDEX_PATH",
    "RULES_PATH",
    "register_house_lineage_route",
    "ensure_house_lineage_representation",
    "recompute_house_lineage",
    "register_exact_house_lineage_member",
    "settle_state_house_lineages",
    "materialize_house_lineage_member",
]

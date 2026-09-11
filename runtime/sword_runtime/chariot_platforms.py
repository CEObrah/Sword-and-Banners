"""Physical chariot platform and horse-team support.

A chariot combat role represents trained crew personnel.  It never implies a
vehicle.  Operational chariot capacity is bounded by three separately conserved
facts: crew bodies in the formation, physical platforms in formation custody,
and ordinary horses allocated from the same conserved mount pool used by cavalry.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, MutableMapping
from typing import Any

FORMATION_RULES_PATH = "game/data/mechanics/formation.json"
OWNER_INDEX_PATH = "state/index/owner-index.json"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def chariot_rules(read) -> Mapping[str, Any]:
    rules = read(FORMATION_RULES_PATH)
    row = rules.get("chariot_platforms", {}) if isinstance(rules, Mapping) else {}
    return row if isinstance(row, Mapping) else {}


def _direct_rider_horse_demand(formation: Mapping[str, Any]) -> int:
    composition = formation.get("composition", {}) if isinstance(formation.get("composition"), Mapping) else {}
    return sum(
        max(0, int(count or 0))
        for role, count in composition.items()
        if "chariot" not in str(role).lower() and any(token in str(role).lower() for token in ("cavalry", "mounted"))
    )


def operational_chariot_capacity(formation: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, int | float]:
    crew_per = max(1, int(rules.get("crew_personnel_per_platform", 3) or 3))
    horses_per = max(1, int(rules.get("horses_per_platform", 3) or 3))
    crew = max(0, int((formation.get("composition", {}) or {}).get("chariot", 0) or 0))
    platforms = max(0, int((formation.get("platforms", {}) or {}).get("chariot", 0) or 0))
    horses = max(0, int((formation.get("mounts", {}) or {}).get("horse", 0) or 0))
    direct_rider_horses = min(horses, _direct_rider_horse_demand(formation))
    chariot_horses_available = max(0, horses - direct_rider_horses)
    condition = max(0.0, min(100.0, _num(formation.get("chariot_platform_condition_pct", 100.0), 100.0)))
    minimum_condition = max(0.0, min(100.0, _num(rules.get("minimum_platform_condition_pct", 20.0), 20.0)))
    serviceable_platforms = platforms if condition >= minimum_condition else 0
    operational = min(serviceable_platforms, crew // crew_per, chariot_horses_available // horses_per)
    operational_crew = min(crew, operational * crew_per)
    return {
        "crew_personnel": crew,
        "physical_platforms": platforms,
        "serviceable_platforms": serviceable_platforms,
        "horses_total": horses,
        "direct_rider_horses": direct_rider_horses,
        "chariot_horses": chariot_horses_available,
        "operational_platforms": operational,
        "operational_crew": operational_crew,
        "crew_per_platform": crew_per,
        "horses_per_platform": horses_per,
        "platform_condition_pct": round(condition, 3),
    }


def _state_formation_rows(planner, state: str) -> list[tuple[str, dict[str, Any]]]:
    index = planner.read(OWNER_INDEX_PATH)
    owners = index.get("owners", {}) if isinstance(index, Mapping) else {}
    rows: list[tuple[str, dict[str, Any]]] = []
    for _owner_id, path in sorted(owners.items() if isinstance(owners, Mapping) else []):
        if not isinstance(path, str) or not path.startswith("state/formations/"):
            continue
        try:
            formation = copy.deepcopy(planner.read(path))
        except (FileNotFoundError, KeyError, ValueError):
            continue
        if not isinstance(formation, MutableMapping):
            continue
        if str(formation.get("owner_force_ref", "")) != f"force_state_{state}" and str(formation.get("administrative_owner", "")) != f"state_{state}":
            continue
        if max(0, int((formation.get("composition", {}) or {}).get("chariot", 0) or 0)) <= 0:
            continue
        rows.append((path, formation))
    return rows


def review_state_chariot_support(planner, *, state: str, at: str, occurrences: int = 1) -> dict[str, Any]:
    """Procure platforms and allocate local horses for existing chariot crews.

    New platforms are paid for from the sovereign treasury, consume actual local
    construction-material stock, and pay the local private economy.  Horse teams
    transfer only from the exact regional reserve at the formation's current
    location.  No horse is created or teleported between regions.
    """
    state = str(state).removeprefix("state_")
    rules = chariot_rules(planner.read)
    crew_per = max(1, int(rules.get("crew_personnel_per_platform", 3) or 3))
    horses_per = max(1, int(rules.get("horses_per_platform", 3) or 3))
    material_per = max(0, int(rules.get("construction_material_units_per_platform", 2) or 0))
    price = max(0, int(rules.get("procurement_silver_per_platform", 140) or 0))
    monthly_cap = max(0, int(rules.get("monthly_procurement_cap_per_state", 120) or 0)) * max(1, int(occurrences))
    remaining_cap = monthly_cap

    state_path = f"state/states/{state}.json"
    mount_path = f"state/mounts/{state}.json"
    try:
        state_doc = copy.deepcopy(planner.read(state_path))
        mounts = copy.deepcopy(planner.read(mount_path))
    except (FileNotFoundError, KeyError):
        return {"changed": False, "reason": "state_or_mount_authority_missing"}

    expense_reserve = max(0, int(state_doc.get("normal_monthly_expense_silver", 0) or 0)) * 3
    total_procured = 0
    total_horses_allocated = 0
    formation_results: list[dict[str, Any]] = []

    for path, formation in _state_formation_rows(planner, state):
        crew = max(0, int((formation.get("composition", {}) or {}).get("chariot", 0) or 0))
        target_platforms = crew // crew_per
        platforms = formation.setdefault("platforms", {})
        if not isinstance(platforms, MutableMapping):
            raise ValueError(f"{formation.get('formation_ref', path)}: invalid platform custody")
        current_platforms = max(0, int(platforms.get("chariot", 0) or 0))
        formation.setdefault("chariot_platform_condition_pct", 100.0)
        procured = 0

        if current_platforms < target_platforms and remaining_cap > 0:
            location_ref = str(formation.get("location_ref", ""))
            try:
                economy_path, economy = planner._private_economy(state)
                _region_ref, local = planner._local_economy_region(state, economy, location_ref)
            except (KeyError, ValueError, FileNotFoundError):
                economy_path = ""
                economy = None
                local = None
            if isinstance(local, MutableMapping) and isinstance(economy, MutableMapping):
                commodities = local.setdefault("commodity_stock", {})
                if not isinstance(commodities, MutableMapping):
                    raise ValueError("local private-economy commodity stock is invalid")
                available_material = max(0, int(commodities.get("construction_material_units", 0) or 0))
                spendable = max(0, int(state_doc.get("treasury_silver", 0) or 0) - expense_reserve)
                affordable = target_platforms - current_platforms
                if material_per > 0:
                    affordable = min(affordable, available_material // material_per)
                if price > 0:
                    affordable = min(affordable, spendable // price)
                procured = max(0, min(affordable, remaining_cap))
                if procured > 0:
                    silver = procured * price
                    materials = procured * material_per
                    state_doc["treasury_silver"] = int(state_doc.get("treasury_silver", 0) or 0) - silver
                    local["cash_silver"] = int(local.get("cash_silver", 0) or 0) + silver
                    commodities["construction_material_units"] = available_material - materials
                    if hasattr(planner, "_record_private_realized_sale"):
                        planner._record_private_realized_sale(local, amount_silver=silver, at=at, kind="chariot_platform_contract", resource="construction_material_units", quantity=materials)
                    planner._sync_local_economy_aggregate(economy)
                    planner._write_private_economy(economy_path, economy)
                    platforms["chariot"] = current_platforms + procured
                    current_platforms += procured
                    remaining_cap -= procured
                    total_procured += procured

        # Allocate ordinary conserved horses from this exact location's regional reserve. Existing formation allocation remains in
        # formation custody and is not counted again.
        desired_horses = _direct_rider_horse_demand(formation) + current_platforms * horses_per
        formation_mounts = formation.setdefault("mounts", {})
        if not isinstance(formation_mounts, MutableMapping):
            raise ValueError(f"{formation.get('formation_ref', path)}: invalid mount custody")
        current_horses = max(0, int(formation_mounts.get("horse", 0) or 0))
        need_horses = max(0, desired_horses - current_horses)
        regional = mounts.get("regional_reserve", {}) if isinstance(mounts.get("regional_reserve"), MutableMapping) else {}
        location_ref = str(formation.get("location_ref", ""))
        local_mounts = regional.get(location_ref) if isinstance(regional, MutableMapping) else None
        allocated = mounts.setdefault("allocated_to_formations", {})
        if not isinstance(allocated, MutableMapping):
            raise ValueError("state mount allocation registry is invalid")
        formation_ref = str(formation.get("formation_ref", ""))
        if need_horses > 0 and isinstance(local_mounts, MutableMapping):
            available_horses = max(0, int(local_mounts.get("horse", 0) or 0))
            moved = min(need_horses, available_horses)
            if moved > 0:
                local_mounts["horse"] = available_horses - moved
                row = allocated.setdefault(formation_ref, {})
                if not isinstance(row, MutableMapping):
                    raise ValueError("formation mount allocation row is invalid")
                row["horse"] = max(0, int(row.get("horse", 0) or 0)) + moved
                formation_mounts["horse"] = current_horses + moved
                current_horses += moved
                total_horses_allocated += moved

        planner.put(path, formation)
        cap = operational_chariot_capacity(formation, rules)
        formation_results.append({"formation_ref": formation_ref, "platforms_procured": procured, **cap})

    if total_procured:
        planner.put(state_path, state_doc)
    if total_horses_allocated:
        planner.put(mount_path, mounts)
    return {
        "changed": bool(total_procured or total_horses_allocated),
        "platforms_procured": total_procured,
        "horses_allocated": total_horses_allocated,
        "formations": formation_results,
    }


class ChariotPlatformMixin:
    def _autonomy_state(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_state(host, occurrences, at)
        if int(occurrences) <= 0:
            return
        state = self._state_key(str(host.get("owner_ref", "")))
        review_state_chariot_support(self, state=state, at=at, occurrences=occurrences)


__all__ = ["ChariotPlatformMixin", "chariot_rules", "operational_chariot_capacity", "review_state_chariot_support"]

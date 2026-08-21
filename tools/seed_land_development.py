#!/usr/bin/env python3
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]


def load(rel: str) -> Any:
    return json.loads((ROOT / rel).read_text())


def dump(rel: str, value: Any) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def rounded_partition(total: float, fractions: Mapping[str, Any]) -> dict[str, float]:
    keys = list(fractions)
    if total <= 0 or not keys:
        return {str(k): 0.0 for k in keys}
    vals: dict[str, float] = {}
    used = 0.0
    for key in keys[:-1]:
        value = round(total * max(0.0, f(fractions[key])), 6)
        vals[str(key)] = value
        used += value
    vals[str(keys[-1])] = round(max(0.0, total - used), 6)
    return vals


def population_by_site() -> dict[str, int]:
    out: dict[str, int] = {}
    for p in sorted((ROOT / "state/population").glob("*.json")):
        data = json.loads(p.read_text())
        sites = data.get("local_population", {}).get("sites", {}) if isinstance(data.get("local_population"), Mapping) else {}
        if not isinstance(sites, Mapping):
            continue
        for ref, row in sites.items():
            if not isinstance(row, Mapping):
                continue
            n = max(0, int(row.get("civilian_population", 0))) + max(0, int(row.get("service_population", 0)))
            out[str(ref)] = max(out.get(str(ref), 0), n)
    return out


def profile_map() -> dict[str, Mapping[str, Any]]:
    doc = load("game/data/world/fortification-profiles.json")
    return {str(row.get("site_ref")): row for row in doc.get("profiles", []) if isinstance(row, Mapping) and row.get("site_ref")}


def rectangle_from_perimeter(perimeter_km: float, aspect: float) -> tuple[float, float, float]:
    r = max(1.0, aspect)
    short = perimeter_km / (2.0 * (r + 1.0))
    long = short * r
    return round(long, 6), round(short, 6), round(long * short, 6)


def site_use_profile(kind: str) -> str:
    if kind in {"capital", "city"}:
        return "urban"
    if kind in {"town", "fortified_settlement"}:
        return "small_urban"
    if kind in {"fort", "fortress", "pass"}:
        return "fort"
    return "village"


def terrain_use_profile(terrain: str) -> str:
    t = terrain.lower()
    if "mountain" in t or "hill" in t or "pass" in t:
        return "mountain"
    if "steppe" in t:
        return "steppe"
    if any(x in t for x in ("river", "plain", "coastal", "basin")):
        return "fertile"
    return "mixed"


def external_use_profile(terrain: str) -> str:
    p = terrain_use_profile(terrain)
    return "mountain" if p == "mountain" else "steppe" if p == "steppe" else "default"


def tang_exact_site(ref: str, master: Mapping[str, Any]) -> dict[str, Any] | None:
    if ref == "loc_tang_manor":
        lb = master["land_budget_km2"]
        enclosed = {
            "agriculture": round(f(lb["staple_food_agriculture"]) + f(lb["specialty_fiber_oil_medicinal_crops"]) + f(lb["harvested_fodder_agriculture"]), 6),
            "pasture": f(lb["pasture_remount_grazing"]),
            "woodland": f(lb["managed_timber_fuel_woodland"]),
            "water": f(lb["reservoirs_canals_waterworks"]),
            "extraction": f(lb["mines_quarries_clay_lime_resource_works"]),
            "residential": f(lb["residential_civic_districts"]),
            "industry": f(lb["workshops_industry_districts"]),
            "civic_storage": 0.0,
            "military": f(lb["military_grounds_depots_barracks"]),
            "training": f(lb["sword_manor_including_inner_citadel"]),
            "transport": f(lb["trunk_roads_logistics_corridors_firebreaks"]),
            "fortification": 0.0,
            "open_developable": 0.0,
            "unsuitable": 0.0,
        }
        g = master["survey_geometry"]
        return {
            "parcel_area_km2": 2000.0,
            "enclosed_area_km2": 2000.0,
            "geometry": {"shape": "stadium", "radius_km": round(f(g["semicircle_radius_km"]), 6), "straight_length_km": round(f(g["straight_section_length_km"]), 6)},
            "enclosed_land_use_km2": enclosed,
            "external_land_use_km2": {},
        }
    if ref == "loc_sword_manor":
        b = master["sword_manor_land_budget_km2"]
        enclosed = {
            "agriculture": 0.0, "pasture": 0.0, "woodland": 0.0, "water": f(b["water_and_sanitation"]), "extraction": 0.0,
            "residential": f(b["barracks_and_residential"]), "industry": f(b["workshops_armory_and_maintenance"]),
            "civic_storage": f(b["medical_and_recovery"]) + f(b["food_storage_and_supply"]),
            "military": f(b["stables_and_mounted_training"]) + f(b["inner_citadel_nested_footprint"]),
            "training": f(b["training_grounds_and_ranges"]), "transport": f(b["roads_courtyards_and_muster_space"]),
            "fortification": f(b["wall_towers_gate_and_internal_defense_space"]), "open_developable": 0.0, "unsuitable": 0.0,
        }
        return {"parcel_area_km2": 60.0, "enclosed_area_km2": 60.0, "geometry": {"shape": "rectangle", "length_km": 10.0, "width_km": 6.0, "aspect_ratio": 10.0/6.0}, "enclosed_land_use_km2": enclosed, "external_land_use_km2": {}}
    if ref == "loc_tang_inner_citadel":
        b = master["inner_citadel_land_budget_km2"]
        enclosed = {
            "agriculture": 0.0, "pasture": 0.0, "woodland": 0.0, "water": f(b["water_and_sanitation"]), "extraction": 0.0,
            "residential": f(b["family_residence_and_household"]), "industry": 0.0,
            "civic_storage": f(b["command_and_administration"]) + f(b["storage_and_medical"]),
            "military": f(b["guard_and_military_space"]), "training": 0.0, "transport": f(b["roads_courtyards_and_open_space"]),
            "fortification": f(b["wall_towers_and_gate_space"]), "open_developable": 0.0, "unsuitable": 0.0,
        }
        return {"parcel_area_km2": 10.0, "enclosed_area_km2": 10.0, "geometry": {"shape": "rectangle", "length_km": 4.0, "width_km": 2.5, "aspect_ratio": 1.6}, "enclosed_land_use_km2": enclosed, "external_land_use_km2": {}}
    return None


def main() -> None:
    rules = load("game/data/mechanics/land-development.json")
    locdoc = load("game/data/world/locations.json")
    locations = locdoc["locations"]
    locs = {str(r["ref"]): r for r in locations if isinstance(r, Mapping) and r.get("ref")}
    pops = population_by_site()
    profiles = profile_map()
    master = load("game/data/world/tang-manor-master-plan.json")
    site_kinds = {"capital", "city", "town", "village", "fort", "fortress", "pass", "fortified_settlement", "estate"}
    defaults = rules["site_geometry_defaults"]
    sites: dict[str, Any] = {}

    for ref, loc in sorted(locs.items()):
        kind = str(loc.get("kind", ""))
        if kind not in site_kinds:
            continue
        exact = tang_exact_site(ref, master)
        profile = profiles.get(ref, {})
        base = profile.get("physical_baseline", {}) if isinstance(profile, Mapping) and isinstance(profile.get("physical_baseline"), Mapping) else {}
        fortified = bool(loc.get("fortified")) or bool(profile)
        cfg = defaults.get(kind, defaults.get("town", {}))
        aspect = max(1.0, f(cfg.get("aspect_ratio"), 1.5))
        if exact:
            site = dict(exact)
        else:
            enclosed = max(0.0, f(base.get("enclosed_area_km2")))
            per = max(0.0, f(base.get("constructed_wall_centerline_perimeter_km")))
            geometry: dict[str, Any]
            if enclosed <= 0 and fortified and per > 0:
                long, short, enclosed = rectangle_from_perimeter(per, aspect)
                geometry = {"shape": "rectangle", "length_km": long, "width_km": short, "aspect_ratio": aspect}
            elif enclosed > 0:
                plan = base.get("plan_rectangle_m", {}) if isinstance(base.get("plan_rectangle_m"), Mapping) else {}
                if plan:
                    long = f(plan.get("length")) / 1000.0; short = f(plan.get("width")) / 1000.0
                    geometry = {"shape": "rectangle", "length_km": round(long, 6), "width_km": round(short, 6), "aspect_ratio": round(max(long, short) / max(1e-9, min(long, short)), 6)}
                else:
                    long = math.sqrt(enclosed * aspect); short = enclosed / max(long, 1e-9)
                    geometry = {"shape": "rectangle", "length_km": round(long, 6), "width_km": round(short, 6), "aspect_ratio": aspect}
            else:
                geometry = {"shape": "rectangle", "aspect_ratio": aspect}

            residents = pops.get(ref, 0)
            density = max(1.0, f(cfg.get("unwalled_population_density"), 8000))
            population_land = residents / density if residents else 0.0
            explicit_area = max(0.0, f(loc.get("area_km2")))
            if fortified:
                parcel = max(explicit_area, enclosed * max(1.0, f(cfg.get("parcel_multiplier_over_enclosure"), 1.5)), enclosed)
            else:
                minimum = {"village": 1.0, "town": 2.0, "city": 4.0, "capital": 8.0, "estate": 2.0}.get(kind, 1.0)
                parcel = max(explicit_area, population_land, minimum)
                enclosed = 0.0
                if "length_km" not in geometry:
                    long = math.sqrt(parcel * aspect); short = parcel / max(long, 1e-9)
                    geometry = {"shape": "rectangle", "length_km": round(long, 6), "width_km": round(short, 6), "aspect_ratio": aspect}
            inside_profile = rules["enclosed_initial_use_fractions"][site_use_profile(kind)]
            outside_area = max(0.0, parcel - enclosed)
            if fortified:
                inside = rounded_partition(enclosed, inside_profile)
                outside = rounded_partition(outside_area, rules["external_initial_use_fractions"][external_use_profile(str(loc.get("terrain", "")))]) if outside_area > 0 else {}
            else:
                inside = {}
                outside = rounded_partition(parcel, inside_profile)
            site = {"parcel_area_km2": round(parcel, 6), "enclosed_area_km2": round(enclosed, 6), "geometry": geometry, "enclosed_land_use_km2": inside, "external_land_use_km2": outside}

        fort = base.get("outer_wall", {}) if isinstance(base, Mapping) and isinstance(base.get("outer_wall"), Mapping) else {}
        site.update({
            "site_ref": ref,
            "name": str(loc.get("name", ref)),
            "kind": kind,
            "state": str(loc.get("state", "")),
            "region_ref": str(loc.get("region_ref") or loc.get("parent_ref") or ""),
            "parent_site_ref": str(loc.get("parent_ref")) if str(loc.get("parent_ref", "")) in sites or str(loc.get("parent_ref", "")) in {"loc_tang_manor", "loc_sword_manor"} else None,
            "private_owner_ref": loc.get("private_owner_ref"),
            "terrain": str(loc.get("terrain", "default")),
            "reserved_land_km2": {},
            "fortification": {
                "active": bool(fortified and site["enclosed_area_km2"] > 0),
                "constructed_outer_perimeter_km": round(max(0.0, f(base.get("constructed_wall_centerline_perimeter_km"))), 6),
                "wall_height_m": f(fort.get("wall_height_m")),
                "wall_base_thickness_m": f(fort.get("wall_base_thickness_m")),
                "wall_crown_thickness_m": f(fort.get("wall_crown_thickness_m")),
                "moat_width_m": f(fort.get("moat_width_m")),
                "moat_depth_m": f(fort.get("moat_depth_m")),
                "tower_count": max(0, int(fort.get("tower_count", 0) or 0)),
                "gate_count": max(0, int(fort.get("external_strategic_gate_count", 0) or 0)),
                "outer_wall_length_built_cumulative_km": round(max(0.0, f(base.get("constructed_wall_centerline_perimeter_km"))), 6),
                "internal_absorbed_wall_km": 0.0,
            },
        })
        sites[ref] = site

    # Parent-site links must be resolved after all sites exist.
    for ref, site in sites.items():
        parent = str(locs[ref].get("parent_ref", ""))
        site["parent_site_ref"] = parent if parent in sites else None

    # Top-level site parcels consume physical area inside their containing territorial region.
    top_site_area: dict[str, float] = {}
    for ref, site in sites.items():
        if site.get("parent_site_ref"):
            continue
        region = str(locs[ref].get("region_ref") or locs[ref].get("parent_ref") or "")
        if region in locs and str(locs[region].get("kind")) == "region":
            top_site_area[region] = top_site_area.get(region, 0.0) + f(site.get("parcel_area_km2"))

    regions: dict[str, Any] = {}
    for ref, loc in sorted(locs.items()):
        if str(loc.get("kind")) != "region":
            continue
        terrain = str(loc.get("terrain", "default"))
        density = max(1.0, f(rules["region_population_density_people_per_km2"].get(terrain, rules["region_population_density_people_per_km2"]["default"])))
        rural_pop = pops.get(ref, 0)
        rural_area = max(25.0, rural_pop / density if rural_pop else 25.0)
        nested = round(top_site_area.get(ref, 0.0), 6)
        area = round(rural_area + nested, 6)
        profile = terrain_use_profile(terrain)
        uses = rounded_partition(round(area - nested, 6), rules["region_initial_use_fractions"][profile])
        regions[ref] = {
            "region_ref": ref,
            "name": str(loc.get("name", ref)),
            "state": str(loc.get("state", "")),
            "polity_ref": loc.get("polity_ref"),
            "terrain": terrain,
            "area_km2": area,
            "nested_site_parcels_km2": nested,
            "land_use_km2": uses,
            "area_basis": {"rural_population": rural_pop, "density_people_per_km2": density, "nested_top_level_site_area_km2": nested},
        }

    holdings: dict[str, Any] = {
        "holding_house_tang_tang_manor": {
            "holding_ref": "holding_house_tang_tang_manor",
            "owner_ref": "house_tang",
            "region_ref": "loc_qin_regional_01",
            "area_km2": 2000.0,
            "site_ref": "loc_tang_manor",
            "grant_refs": ["baseline_house_tang_tang_manor"],
            "status": "held",
        }
    }
    registry = {"schema": "land-development-registry", "owner_id": "land_development", "authority": True, "regions": regions, "sites": sites, "holdings": holdings}

    # The private Tang Manor parcel is already represented in Qin region site parcels;
    # property ownership is not a second territorial-area partition.
    from sys import path as syspath
    syspath.insert(0, str(ROOT / "runtime"))
    from sword_runtime.land_development import require_valid_land_registry
    require_valid_land_registry(registry)
    dump("state/development/land.json", registry)
    print(f"seeded {len(regions)} regions, {len(sites)} physical sites, {len(holdings)} private holdings")
    jo = sites.get("loc_jo_city", {})
    print("Jo city", jo.get("parcel_area_km2"), jo.get("enclosed_area_km2"), jo.get("fortification", {}).get("constructed_outer_perimeter_km"))
    print("Tang Manor", sites["loc_tang_manor"]["parcel_area_km2"], sites["loc_tang_manor"]["enclosed_area_km2"])


if __name__ == "__main__":
    main()

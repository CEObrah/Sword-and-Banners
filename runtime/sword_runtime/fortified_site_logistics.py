from __future__ import annotations

from typing import Any, Mapping


def build_logistics_blueprint(profile: Mapping[str, Any], rules: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the exact static storage/installation plan from a fort profile.

    This is a deterministic projection from saved geometry plus one saved storage
    class. It never inspects current garrison size, so casualties cannot silently
    shrink a fortress's physical capacity or installed fixtures.
    """
    physical = profile.get("physical_baseline", {}) if isinstance(profile.get("physical_baseline"), Mapping) else {}
    storage_class = str(physical.get("storage_class", "regional_garrison_reserve"))
    cls = rules.get("storage_classes", {}).get(storage_class)
    if not isinstance(cls, Mapping):
        raise ValueError(f"unknown fortified-site storage class: {storage_class}")
    perimeter_km = float(physical.get("constructed_wall_centerline_perimeter_km", 1.0) or 1.0)
    outer = physical.get("outer_wall", {}) if isinstance(physical.get("outer_wall"), Mapping) else {}
    depth = physical.get("defensive_depth", {}) if isinstance(physical.get("defensive_depth"), Mapping) else {}
    towers = max(0, int(outer.get("tower_count", 0) or 0))
    gates = max(1, int(outer.get("external_strategic_gate_count", 1) or 1))
    platforms = max(0, int(depth.get("artillery_platforms", 0) or 0))
    supply_yards = max(1, int(depth.get("main_supply_yards", 1) or 1))
    field_hospitals = max(1, int(depth.get("field_hospitals", max(1, round(perimeter_km / 6.0))) or 1))
    reserve_days = max(1, int(cls.get("reserve_days", 45)))
    density = max(0.1, float(cls.get("fixed_emplacement_density", 1.0)))
    nominal = max(1000, int(round(perimeter_km * int(cls.get("nominal_garrison_per_perimeter_km", 1800)))))
    # Existing Tang Manor fixture authorities already own the exact installed
    # systems. Nested Tang profiles reference that authority rather than cloning it.
    tang_nested = str(profile.get("site_ref", "")) in {"loc_tang_manor", "loc_sword_manor", "loc_tang_inner_citadel"}
    if tang_nested:
        fixtures: dict[str, Any] = {
            "authority_ref": "state/art/tang-manor-artillery.json",
            "mode": "reference_existing_exact_fixture_authority"
        }
    else:
        fixtures = {
            "authority_ref": None,
            "mode": "static_installed_blueprint",
            "bed_crossbows": max(4, int(round(towers * 1.5 * density + platforms * 3))),
            "counterweight_trebuchets": max(2, int(round(platforms if platforms else towers * density / 12.0))),
            "stone_drop_cranes": max(4, int(round(towers * 0.60 * density))),
            "firepot_systems": max(4, int(round(towers * 0.60 * density))),
            "gate_mechanism_sets": gates,
            "signal_tower_sets": max(0, int(depth.get("signal_towers", 0) or 0)),
        }
    return {
        "authority": True,
        "derivation": "deterministic from exact physical_baseline plus game/data/mechanics/fortified-site-logistics.json storage class; independent of current troop headcount",
        "storage_class": storage_class,
        "reserve_days": reserve_days,
        "nominal_garrison_capacity": nominal,
        "storage_capacity": {
            "grain_kg": int(nominal * reserve_days * 2.0 * 1.25),
            "fodder_kg": int(nominal * 0.35 * reserve_days * 10.0 * 1.25),
            "war_arrows": int(nominal * 0.30 * 420),
            "war_bolts": int(nominal * 0.30 * 420),
            "timber_tonnes": max(100, int(round(perimeter_km * 120))),
            "iron_tonnes": max(25, int(round(perimeter_km * 24))),
            "construction_material_units": max(500, int(round(perimeter_km * 550))),
            "medicine_lots": max(500, int(round(nominal * 1.5))),
            "carts": max(100, int(round(nominal / 8.0)))
        },
        "water_system": {
            "reserve_capacity_person_days": int(nominal * max(15, min(reserve_days, 60))),
            "initial_hot_fill_fraction_milli": 800,
            "rule": "local wells/cisterns and stored water are a site physical reserve, not national depot commodity stock"
        },
        "medical_system": {
            "field_hospital_sites": field_hospitals,
            "bed_capacity": max(50, int(round(nominal * 0.025))),
            "supply_yards": supply_yards
        },
        "wagon_staging": {
            "yard_count": supply_yards,
            "covered_cart_capacity": max(100, int(round(nominal / 8.0)))
        },
        "installed_equipment": fixtures
    }


def current_garrison_requirements(
    *,
    personnel: int,
    mounts: int,
    bow_personnel: int,
    crossbow_personnel: int,
    blueprint: Mapping[str, Any],
) -> dict[str, int]:
    """Target hot-site stock for the currently saved garrison, capped by capacity."""
    days = max(1, int(blueprint.get("reserve_days", 45)))
    cap = blueprint.get("storage_capacity", {}) if isinstance(blueprint.get("storage_capacity"), Mapping) else {}
    desired = {
        "grain_kg": int(max(0, personnel) * 2.0 * days),
        "fodder_kg": int(max(0, mounts) * 10.0 * days),
        "war_arrows": int(max(0, bow_personnel) * 300),
        "war_bolts": int(max(0, crossbow_personnel) * 300),
        "timber_tonnes": max(10, int(round(max(0, personnel) * 0.012))),
        "iron_tonnes": max(3, int(round(max(0, personnel) * 0.0025))),
        "medicine_lots": max(50, int(round(max(0, personnel) * 0.35))),
        "carts": max(20, int(round(max(0, personnel) / 20.0))),
    }
    return {key: min(max(0, int(value)), max(0, int(cap.get(key, value)))) for key, value in desired.items()}

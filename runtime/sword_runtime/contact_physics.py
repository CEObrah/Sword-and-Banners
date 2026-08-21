from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


def num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def condition_factor(condition_pct: float) -> float:
    return 0.55 + 0.45 * clamp(condition_pct / 100.0, 0.0, 1.0)


def contact_grade_multiplier(margin: float) -> tuple[str, float]:
    if margin <= -25:
        return "denied", 0.0
    if margin <= 0:
        return "glancing", 0.45
    if margin <= 15:
        return "solid", 0.80
    if margin <= 40:
        return "clean", 1.0
    return "exceptional", 1.15


def weapon_penetration_factor(weapon: Mapping[str, Any] | None, mode: str) -> float:
    """Return a geometry/material penetration factor separate from raw impact.

    The catalog historically stored force and penetration as one broad concept for
    melee weapons.  This function deliberately separates them without inventing a
    second power stat: point/edge geometry and weapon family determine how much of
    the already-computed contact impulse is concentrated into penetration.

    An explicit ``armor_penetration`` field remains authoritative when present
    (projectiles already use it).  Otherwise conservative family defaults are used.
    Values are multipliers, not caps, so stronger/faster attacks keep scaling.
    """
    if not isinstance(weapon, Mapping) or not weapon:
        return 0.30 if mode == "blunt" else 0.70
    explicit = num(weapon.get("armor_penetration"), 0.0)
    if explicit > 0:
        return max(0.05, explicit)
    family = str(weapon.get("family", "")).lower()
    variant = str(weapon.get("variant", "")).lower()
    if mode == "thrust":
        base = {
            "spear": 1.18,
            "lance": 1.22,
            "sword": 0.96,
            "glaive": 0.86,
            "dagger": 1.02,
            "axe": 0.62,
            "mace": 0.42,
            "staff": 0.35,
        }.get(family, 0.78)
        if "lance" in variant:
            base *= 1.08
    elif mode == "cut":
        base = {
            "sword": 1.02,
            "glaive": 0.96,
            "axe": 1.06,
            "dagger": 0.86,
            "spear": 0.42,
            "lance": 0.32,
            "mace": 0.18,
            "staff": 0.08,
        }.get(family, 0.70)
    else:
        # Blunt trauma primarily defeats protection by transmitted impulse rather
        # than by perforation.  A small penetration component still represents
        # concentrated hammer/mace faces and hard edges.
        base = {
            "mace": 0.48,
            "hammer": 0.52,
            "axe": 0.34,
            "glaive": 0.28,
            "sword": 0.22,
            "spear": 0.20,
            "staff": 0.18,
        }.get(family, 0.24)
    mass = max(0.1, num(weapon.get("mass_kg"), 1.0))
    handling = clamp(num(weapon.get("handling"), 0.8), 0.35, 1.20)
    geometry_mass = clamp(0.88 + math.sqrt(mass) / 12.0, 0.88, 1.12)
    geometry_control = clamp(0.88 + 0.12 * handling, 0.90, 1.04)
    return max(0.05, base * geometry_mass * geometry_control)


def weapon_penetration_index(
    weapon: Mapping[str, Any] | None,
    *,
    mode: str,
    impact_index: float,
) -> float:
    """Concentrated penetration carried by a physical contact.

    ``impact_index`` already contains strength, speed/motion, contact quality and
    weapon condition.  Penetration therefore scales from that same physical event
    instead of being an unrelated special-attack number.
    """
    return max(0.0, num(impact_index)) * weapon_penetration_factor(weapon, mode)


def angle_from_margin(margin: float) -> tuple[str, float]:
    # A barely successful contact tends to glance; a very clean attack is more
    # likely to find a weak line rather than receiving a magical damage bonus.
    if margin < 8:
        return "oblique", 1.20
    if margin >= 45:
        return "weak_line", 0.75
    return "direct", 1.0


def _channel_values(item: Mapping[str, Any], mode: str, structure: str | None = None) -> list[float]:
    suffix = {"cut": "cut_resistance", "thrust": "thrust_resistance", "blunt": "blunt_resistance"}.get(mode, "blunt_resistance")
    schema = str(item.get("schema", "")).lower()
    structure = str(structure or "").lower()

    # Pick the resistance channel that physically covers the contacted structure
    # before falling back to broad armor values. This prevents a wrist, eye or
    # articulation-gap hit from automatically receiving the strongest torso plate.
    if schema == "helmet":
        if structure == "eye":
            explicit = [f"eye_lens_{suffix}", f"shell_{suffix}"]
        elif structure in {"face", "jaw", "throat"}:
            explicit = [f"breathing_channel_{suffix}", f"shell_{suffix}"]
        else:
            explicit = [f"shell_{suffix}", f"breathing_channel_{suffix}", f"eye_lens_{suffix}"]
    elif schema == "human_armor":
        if structure in {"hand", "foot", "wrist", "ankle"}:
            explicit = [f"hand_and_foot_{suffix}", f"articulated_joint_{suffix}", f"primary_plate_{suffix}"]
        elif structure in {"elbow", "knee", "shoulder", "hip", "axilla"}:
            explicit = [f"articulated_joint_{suffix}", f"primary_plate_{suffix}", f"hand_and_foot_{suffix}"]
        else:
            explicit = [f"primary_plate_{suffix}", f"articulated_joint_{suffix}", f"hand_and_foot_{suffix}"]
    elif schema == "horse_armor":
        if structure in {"leg", "upper_leg", "joint"}:
            explicit = [f"articulated_{suffix}", f"primary_{suffix}"]
        else:
            explicit = [f"primary_{suffix}", f"articulated_{suffix}"]
    else:
        explicit = [
            suffix, f"primary_plate_{suffix}", f"shell_{suffix}", f"articulated_joint_{suffix}",
            f"hand_and_foot_{suffix}", f"eye_lens_{suffix}", f"breathing_channel_{suffix}",
            f"primary_{suffix}", f"articulated_{suffix}",
        ]

    vals: list[float] = []
    for key in explicit:
        v = num(item.get(key))
        if v > 0:
            vals.append(v)
    if not vals:
        for key, raw in item.items():
            if str(key).endswith(suffix):
                v = num(raw)
                if v > 0:
                    vals.append(v)
    return vals


def armor_channel_protection(
    item: Mapping[str, Any],
    mode: str,
    *,
    condition_pct: float = 100.0,
    fit_factor: float = 1.0,
    angle_factor: float = 1.0,
    structure: str | None = None,
) -> float:
    vals = _channel_values(item, mode, structure)
    if not vals:
        return 0.0
    weights = (1.0, 0.35, 0.15)
    base = sum(v * weights[i] for i, v in enumerate(vals[: len(weights)]))
    return base * condition_factor(condition_pct) * max(0.5, fit_factor) * max(0.5, angle_factor)


def armor_contact_resolution(
    item: Mapping[str, Any] | None,
    *,
    mode: str,
    impact_index: float,
    penetration_index: float | None = None,
    condition_pct: float = 100.0,
    fit_factor: float = 1.0,
    angle_factor: float = 1.0,
    structure: str | None = None,
) -> dict[str, Any]:
    transfer = {"cut": 0.35, "thrust": 0.25, "blunt": 1.0}.get(mode, 1.0)
    uncovered = {"cut": 30.0, "thrust": 28.0, "blunt": 35.0}.get(mode, 35.0)
    if not isinstance(item, Mapping) or not item:
        protection = uncovered
        blunt_protection = uncovered
        covered = False
    else:
        protection = armor_channel_protection(
            item, mode, condition_pct=condition_pct, fit_factor=fit_factor, angle_factor=angle_factor, structure=structure
        )
        blunt_protection = armor_channel_protection(
            item, "blunt", condition_pct=condition_pct, fit_factor=fit_factor, angle_factor=angle_factor, structure=structure
        )
        if protection <= 0:
            protection = uncovered
        if blunt_protection <= 0:
            blunt_protection = uncovered
        covered = True
    raw_impact = max(0.0, num(impact_index))
    raw_penetration = raw_impact if penetration_index is None else max(0.0, num(penetration_index))
    penetration_ratio = raw_penetration / max(0.001, protection)
    impact_ratio = raw_impact * transfer / max(0.001, blunt_protection)

    # Armor is a physical layer, not a binary damage multiplier.  If it is
    # perforated, only penetration/impulse left after that layer reaches the body.
    # If it is not perforated, cut/thrust can still transmit blunt trauma.
    if covered:
        residual_penetration = max(0.0, raw_penetration - protection)
        absorbed_impulse = min(raw_impact, blunt_protection * (0.62 if mode == "blunt" else 0.48))
        transmitted_floor = raw_impact * transfer * 0.22
        residual_impact = max(transmitted_floor, raw_impact - absorbed_impulse) if raw_impact > 0 else 0.0
        if residual_penetration <= 0 and mode in {"cut", "thrust"}:
            residual_impact = min(residual_impact, raw_impact * transfer)
    else:
        # No armor layer exists.  The uncovered resistance above is only the
        # tissue reference used for severity, not an imaginary armor plate.
        residual_penetration = raw_penetration
        residual_impact = raw_impact

    tissue_penetration_ratio = residual_penetration / max(0.001, uncovered)
    tissue_impact_ratio = residual_impact / max(0.001, uncovered if mode != "blunt" else 35.0)
    ratio = max(tissue_penetration_ratio, tissue_impact_ratio)
    if ratio < 0.50:
        severity = 0
    elif ratio < 0.90:
        severity = 1
    elif ratio < 1.30:
        severity = 2
    elif ratio < 2.0:
        severity = 3
    else:
        severity = 4
    severity_name = {0: "none", 1: "minor", 2: "moderate", 3: "serious", 4: "critical"}[severity]
    wear = 0.0
    if covered:
        severity_mult = (0.7, 1.0, 1.35, 1.8, 2.4)[severity]
        wear = min(18.0, max(0.2, 2.5 * ratio) * severity_mult)
    return {
        "covered": covered,
        "contact_structure": str(structure or ""),
        "channel_protection": round(protection, 3),
        "blunt_protection": round(blunt_protection, 3),
        "incoming_penetration_index": round(raw_penetration, 3),
        "penetration_ratio": round(penetration_ratio, 5),
        "transmitted_impact_ratio": round(impact_ratio, 5),
        "penetrated": bool(penetration_ratio >= 1.0),
        "residual_penetration_index": round(residual_penetration, 3),
        "residual_impact_index": round(residual_impact, 3),
        "post_defense_tissue_penetration_ratio": round(tissue_penetration_ratio, 5),
        "post_defense_tissue_impact_ratio": round(tissue_impact_ratio, 5),
        "maximum_ratio": round(ratio, 5),
        "severity": severity_name,
        "armor_wear_pct": round(wear, 3),
    }


def weapon_contact_wear(
    weapon: Mapping[str, Any] | None,
    *,
    transmitted_impact_index: float,
    condition_pct: float = 100.0,
    hard_contact: bool = True,
) -> dict[str, Any]:
    if not isinstance(weapon, Mapping) or not weapon:
        return {"condition_loss_pct": 0.0, "overload_ratio": 0.0, "failed": False}
    structural = num(weapon.get("structural_capacity"), 50.0)
    current_capacity = max(1.0, structural * condition_factor(condition_pct))
    overload = max(0.0, transmitted_impact_index) / current_capacity
    ordinary = 0.6 if hard_contact else 0.2
    if overload < 0.90:
        extra = 0.0
    elif overload < 1.20:
        extra = 1.0 + (overload - 0.90) / 0.30 * 2.0
    elif overload < 1.60:
        extra = 4.0 + (overload - 1.20) / 0.40 * 6.0
    else:
        extra = min(30.0, 10.0 + 20.0 * (overload - 1.60) / 0.80)
    loss = ordinary + extra
    remaining = max(0.0, condition_pct - loss)
    threshold = 0.85 + 0.65 * clamp(condition_pct / 100.0, 0.0, 1.0)
    failed = overload >= 2.0 or (overload >= threshold and remaining <= 8.0)
    if failed:
        remaining = 0.0
    return {
        "condition_loss_pct": round(condition_pct - remaining, 3),
        "remaining_condition_pct": round(remaining, 3),
        "overload_ratio": round(overload, 5),
        "failed": bool(failed),
    }


def projectile_weapon_deflection_resolution(
    weapon: Mapping[str, Any] | None,
    *,
    projectile_speed_mps: float,
    impact_index: float,
    penetration_index: float,
    attack_margin: float,
    timing_factor: float,
    saturation_factor: float,
    balance_factor: float,
    detection_quality: float,
    incoming_arc_delta_deg: float,
    condition_pct: float = 100.0,
) -> dict[str, Any]:
    """Resolve a weapon interception against an incoming arrow/bolt.

    This is deliberately not a generic parry bonus. The projectile already owns
    a fixed physical lane; the defender must put a serviceable melee weapon into
    that lane before contact. Speed, warning/visual quality, current guard arc,
    body commitment and weapon handling all matter. A successful interception
    can cleanly redirect the projectile, while a narrowly beaten interception
    can still alter its line and shed energy before body contact.
    """
    weapon = weapon if isinstance(weapon, Mapping) else {}
    family = str(weapon.get("family", "")).lower()
    schema = str(weapon.get("schema", "")).lower()
    if not weapon or family == "unarmed" or schema == "projectile":
        return {
            "available": False,
            "intercepted": False,
            "outcome": "unavailable",
            "residual_impact_index": round(max(0.0, num(impact_index)), 3),
            "residual_penetration_index": round(max(0.0, num(penetration_index)), 3),
        }

    speed = max(1.0, num(projectile_speed_mps, 1.0))
    handling = clamp(num(weapon.get("handling"), 0.8), 0.30, 1.20)
    reach = clamp(num(weapon.get("reach_m"), 0.65), 0.20, 2.50)
    condition = condition_factor(condition_pct)
    timing = clamp(timing_factor, 0.05, 1.0)
    saturation = clamp(saturation_factor, 0.05, 1.0)
    balance = clamp(balance_factor, 0.05, 1.0)
    detection = clamp(detection_quality, 0.0, 1.0)
    arc_delta = clamp(abs(num(incoming_arc_delta_deg)), 0.0, 180.0)

    # Long, unwieldy weapons offer reach but take more path to redirect. Short
    # weapons are quick but present less intercepting length. The middle ground
    # is best without creating a special weapon class purely for arrows.
    reach_factor = clamp(0.82 + 0.16 * min(reach, 1.35) / 1.35, 0.78, 0.98)
    if reach > 1.35:
        reach_factor *= clamp(1.0 - (reach - 1.35) * 0.10, 0.82, 1.0)
    arc_factor = clamp(1.0 - arc_delta / 205.0, 0.12, 1.0)
    speed_factor = clamp(1.10 - max(0.0, speed - 32.0) / 125.0, 0.30, 1.05)
    control_factor = clamp(
        handling * condition * reach_factor * timing * saturation * balance
        * max(0.15, detection) * arc_factor * speed_factor,
        0.02,
        1.05,
    )

    # attack_margin is attacker control minus already-timed defender control.
    # Positive values mean the projectile line beat the active defense. The
    # physical interception factors add a further projectile-specific difficulty
    # without mutating either combatant's underlying stats.
    effective_margin = num(attack_margin) + (1.0 - control_factor) * 18.0
    if effective_margin <= 0.0:
        outcome = "clean_deflection"
        intercepted = True
        # Better interceptions turn the projectile farther off its original line.
        deflection_angle = clamp(30.0 + min(48.0, abs(effective_margin) * 1.15) + 10.0 * handling, 30.0, 82.0)
        impact_retention = clamp(0.42 + 0.22 * speed_factor, 0.38, 0.68)
        penetration_retention = clamp(0.30 + 0.20 * speed_factor, 0.26, 0.55)
    elif effective_margin <= 14.0:
        outcome = "partial_deflection"
        intercepted = True
        fraction = clamp(effective_margin / 14.0, 0.0, 1.0)
        deflection_angle = clamp(24.0 - 15.0 * fraction + 6.0 * handling, 8.0, 30.0)
        impact_retention = clamp(0.58 + 0.28 * fraction, 0.55, 0.88)
        penetration_retention = clamp(0.42 + 0.40 * fraction, 0.38, 0.84)
    else:
        outcome = "missed_intercept"
        intercepted = False
        deflection_angle = 0.0
        impact_retention = 1.0
        penetration_retention = 1.0

    return {
        "available": True,
        "intercepted": bool(intercepted),
        "outcome": outcome,
        "projectile_speed_mps": round(speed, 3),
        "control_factor": round(control_factor, 6),
        "effective_margin": round(effective_margin, 6),
        "incoming_arc_delta_deg": round(arc_delta, 3),
        "deflection_angle_deg": round(deflection_angle, 3),
        "impact_retention": round(impact_retention, 6),
        "penetration_retention": round(penetration_retention, 6),
        "residual_impact_index": round(max(0.0, num(impact_index)) * impact_retention, 3),
        "residual_penetration_index": round(max(0.0, num(penetration_index)) * penetration_retention, 3),
    }


def shield_contact_resolution(
    shield: Mapping[str, Any] | None,
    *,
    impact_index: float,
    penetration_index: float | None = None,
    mode: str = "blunt",
    condition_pct: float = 100.0,
    timing_factor: float = 1.0,
    block_control_ratio: float = 1.0,
    interception_angle_deg: float | None = None,
) -> dict[str, Any]:
    incoming_penetration = max(0.0, num(impact_index if penetration_index is None else penetration_index))
    if not isinstance(shield, Mapping) or not shield:
        return {
            "intercepted": False,
            "absorbed_impact": 0.0,
            "residual_impact": max(0.0, impact_index),
            "residual_penetration_index": incoming_penetration,
            "penetrated": False,
            "condition_loss_pct": 0.0,
            "remaining_condition_pct": condition_pct,
            "failed": False,
        }
    structure = max(1.0, num(shield.get("structural_resistance"), 50.0) * condition_factor(condition_pct))
    coverage = clamp(num(shield.get("coverage_arc_degrees"), 90.0) / 135.0, 0.20, 1.0)
    handling = clamp(num(shield.get("handling"), 1.0), 0.45, 1.15)
    control = clamp(block_control_ratio, 0.25, 1.35)
    intercept = clamp(coverage * handling * clamp(timing_factor, 0.1, 1.0) * control, 0.08, 0.97)
    # Incidence is measured away from the shield normal: 0 degrees is a square
    # collision, larger angles are increasingly glancing. Better timing/control
    # can deliberately present an oblique face, but the caller may provide exact
    # geometry when it is known. Obliquity increases the path through the shield
    # and sheds tangential impulse instead of magically increasing shield HP.
    if interception_angle_deg is None:
        # Callers without known geometry retain a conservative square-impact
        # assumption. Exact combat passes its resolved defensive presentation.
        interception_angle = 0.0
    else:
        interception_angle = clamp(interception_angle_deg, 0.0, 82.0)
    angle_rad = math.radians(interception_angle)
    normal_fraction = max(0.12, math.cos(angle_rad))
    path_factor = min(2.25, 1.0 / normal_fraction)
    deflection_factor = 1.0 - normal_fraction
    absorbed_capacity = structure * (0.65 + 0.35 * intercept) * (0.88 + 0.12 * path_factor)
    normal_impact = max(0.0, impact_index) * normal_fraction
    absorbed = min(normal_impact * intercept, absorbed_capacity)
    # Tangential energy mostly deflects rather than disappearing into the shield.
    residual = max(0.0, max(0.0, impact_index) * (1.0 - intercept) + normal_impact * intercept - absorbed)
    overload = normal_impact / structure
    penetration_capacity = structure * {"cut": 0.92, "thrust": 0.78, "blunt": 1.30}.get(mode, 1.0) * min(1.85, path_factor)
    intercepted_penetration = incoming_penetration * intercept * (1.0 - 0.62 * deflection_factor)
    penetration_overload = intercepted_penetration / max(0.001, penetration_capacity)
    perforation_excess = max(0.0, intercepted_penetration - penetration_capacity)
    residual_penetration = incoming_penetration * (1.0 - intercept) + perforation_excess
    penetrated = penetration_overload >= 1.0
    base = 0.35
    effective_overload = max(overload, penetration_overload)
    if effective_overload <= 0.75:
        wear = base + effective_overload * 0.35
    elif effective_overload <= 1.25:
        wear = 0.65 + (effective_overload - 0.75) * 3.4
    else:
        wear = 2.35 + (effective_overload - 1.25) * 8.0
    wear = min(35.0, max(0.2, wear))
    remaining = max(0.0, condition_pct - wear)
    failed = overload >= 2.0 or remaining <= 0.0
    if failed:
        remaining = 0.0
        # A catastrophic failure cannot absorb all of the excess impulse.
        residual = max(residual, max(0.0, impact_index - structure * 0.75))
        residual_penetration = max(residual_penetration, max(0.0, incoming_penetration - penetration_capacity * 0.55))
    elif penetrated:
        # A point/edge can perforate a shield without the entire shield ceasing to
        # exist.  The shield remains usable but that contact passes residual force.
        residual = max(residual, max(0.0, impact_index) * (0.24 + 0.28 * clamp(penetration_overload - 1.0, 0.0, 1.0)))
    return {
        "intercepted": True,
        "structural_capacity": round(structure, 3),
        "interception_angle_deg": round(interception_angle, 3),
        "normal_impact_fraction": round(normal_fraction, 5),
        "effective_path_factor": round(path_factor, 5),
        "overload_ratio": round(overload, 5),
        "penetration_capacity": round(penetration_capacity, 3),
        "penetration_overload_ratio": round(penetration_overload, 5),
        "penetrated": bool(penetrated),
        "absorbed_impact": round(absorbed, 3),
        "residual_impact": round(residual, 3),
        "residual_penetration_index": round(max(0.0, residual_penetration), 3),
        "condition_loss_pct": round(condition_pct - remaining, 3),
        "remaining_condition_pct": round(remaining, 3),
        "failed": bool(failed),
    }


def mount_effective_speed_mps(
    mount: Mapping[str, Any] | None,
    *,
    barding: Mapping[str, Any] | None = None,
    rider_mass_kg: float = 75.0,
    rider_equipment_kg: float = 0.0,
    tack_mass_kg: float = 0.0,
    cargo_mass_kg: float = 0.0,
    terrain_factor: float = 1.0,
    horse_fatigue: float = 0.0,
) -> dict[str, Any]:
    if not isinstance(mount, Mapping) or not mount:
        return {"mounted": False, "effective_speed_mps": 0.0, "load_ratio": 0.0, "total_mass_kg": 0.0}
    speed_stat = max(0.0, num(mount.get("speed", mount.get("Speed", 0.0))))
    strength = max(1.0, num(mount.get("strength", mount.get("Strength", 50.0)), 50.0))
    endurance = max(1.0, num(mount.get("endurance", mount.get("Endurance", 50.0)), 50.0))
    agility = max(1.0, num(mount.get("agility", mount.get("Agility", 50.0)), 50.0))
    comfortable = max(35.0, num(mount.get("comfortable_load_kg"), 20.0 + 0.55 * strength + 0.30 * endurance))
    barding_mass = max(0.0, num(barding.get("mass_kg")) if isinstance(barding, Mapping) else 0.0)
    carried = max(0.0, rider_mass_kg + rider_equipment_kg + tack_mass_kg + barding_mass + cargo_mass_kg)
    load_ratio = carried / comfortable
    if load_ratio <= 0.75:
        load_speed = 1.0
    elif load_ratio <= 0.90:
        load_speed = 0.97
    elif load_ratio <= 1.0:
        load_speed = 0.91
    elif load_ratio <= 1.10:
        load_speed = 0.80
    else:
        load_speed = max(0.45, 0.80 - (load_ratio - 1.10) * 0.75)
    articulation = clamp(num(barding.get("articulation_factor"), 1.0) if isinstance(barding, Mapping) else 1.0, 0.65, 1.05)
    heat = max(1.0, num(barding.get("heat_modifier"), 1.0) if isinstance(barding, Mapping) else 1.0)
    barding_factor = clamp(1.0 - max(0.0, barding_mass / comfortable - 0.35) * (0.20 + max(0.0, 100.0 - agility) / 500.0), 0.70, 1.0)
    barding_factor *= articulation / max(1.0, heat ** 0.08)
    fatigue_factor = max(0.35, 1.0 - max(0.0, horse_fatigue) / 130.0)
    # The catalog Speed stat is an abstract athletic capability. Root scaling
    # converts it to plausible battlefield m/s while preserving >200 growth.
    base_speed_mps = max(2.0, 2.0 + math.sqrt(speed_stat) * 1.18)
    effective = base_speed_mps * load_speed * barding_factor * fatigue_factor * clamp(terrain_factor, 0.35, 1.15)
    return {
        "mounted": True,
        "effective_speed_mps": round(effective, 4),
        "base_speed_mps": round(base_speed_mps, 4),
        "load_ratio": round(load_ratio, 5),
        "load_speed_factor": round(load_speed, 5),
        "barding_factor": round(barding_factor, 5),
        "total_mass_kg": round(max(0.0, num(mount.get("mass_kg"))) + carried, 3),
        "mount_mass_kg": round(max(0.0, num(mount.get("mass_kg"))), 3),
        "charge_legal": bool(load_ratio <= 1.10 and mount.get("charge_training")),
    }


def mounted_charge_resolution(
    mount_profile: Mapping[str, Any],
    *,
    riding: float,
    coordination: float,
    awareness: float,
    composure: float,
    horse_training: float,
    relative_speed_mps: float,
    weapon: Mapping[str, Any] | None = None,
    bracing_factor: float = 1.0,
    target_mass_kg: float = 85.0,
) -> dict[str, Any]:
    if not mount_profile.get("mounted") or not mount_profile.get("charge_legal"):
        return {"charge_legal": False, "alignment": 0.0, "collision_index": 0.0, "weapon_motion_multiplier": 1.0}
    control = 0.35 * riding + 0.20 * coordination + 0.15 * awareness + 0.10 * composure + 0.10 * horse_training + 0.10 * 100.0
    alignment = clamp(control / 150.0, 0.25, 1.35)
    total_mass = max(1.0, num(mount_profile.get("total_mass_kg")))
    speed = max(0.0, relative_speed_mps)
    brace = clamp(bracing_factor, 0.35, 1.35)
    collision = total_mass * speed * speed / 100.0 * alignment * brace
    target_mass = max(1.0, num(target_mass_kg, 85.0))
    reduced_mass = total_mass * target_mass / max(1.0, total_mass + target_mass)
    collision_energy_j = 0.5 * reduced_mass * speed * speed
    body_collision_impact = math.sqrt(max(0.0, collision_energy_j)) * alignment * brace
    weapon_multiplier = 1.0
    if isinstance(weapon, Mapping):
        family = str(weapon.get("family", "")).lower()
        variant = str(weapon.get("variant", "")).lower()
        if family == "spear" and ("lance" in variant or "cavalry" in variant):
            # A couched lance can transfer part of the horse+rider momentum through
            # the weapon. Horse/rider mass therefore matters as well as speed, but
            # the multiplier remains bounded by physical alignment/grip rather than
            # becoming a magical cavalry bonus.
            momentum_drive = clamp(1.0 + math.sqrt(max(0.0, collision)) / 55.0, 1.0, 2.15)
            weapon_multiplier = clamp(num(weapon.get("couched_grip_force_factor"), 1.18) * (1.0 + speed / 24.0) * momentum_drive, 1.0, 3.0)
        elif str(weapon.get("mounted_compatibility", "")).lower() in {"excellent", "good"}:
            weapon_multiplier = clamp(1.0 + speed / 45.0, 1.0, 1.45)
    return {
        "charge_legal": True,
        "alignment": round(alignment, 5),
        "collision_index": round(collision, 3),
        "collision_energy_j": round(collision_energy_j, 3),
        "body_collision_impact_index": round(body_collision_impact, 3),
        "total_mass_kg": round(total_mass, 3),
        "reduced_mass_kg": round(reduced_mass, 3),
        "weapon_motion_multiplier": round(weapon_multiplier, 5),
        "relative_speed_mps": round(speed, 4),
    }


def projectile_operating_envelope(weapon: Mapping[str, Any] | None, *, weapon_skill: float = 0.0, strength: float = 0.0, coordination: float = 0.0, awareness: float = 0.0, weapon_condition_pct: float = 100.0) -> dict[str, float]:
    """Derive practical missile range/cadence from one canonical weapon plus current capability."""
    w = weapon if isinstance(weapon, Mapping) else {}
    if not w:
        return {"effective_range_m": 0.0, "maximum_direct_range_m": 0.0, "cycle_seconds": 0.0, "launch_power_index": 0.0}
    family = str(w.get("family", w.get("schema", ""))).lower()
    base_eff=max(1.0,num(w.get("effective_range_m"),100.0)); base_max=max(base_eff,num(w.get("maximum_direct_range_m"),base_eff*2.0))
    skill=max(0.0,num(weapon_skill)); coord=max(0.0,num(coordination)); aware=max(0.0,num(awareness)); cond=condition_factor(weapon_condition_pct)
    if family == "crossbow" or str(w.get("schema","")).lower()=="crossbow":
        control=0.72 + 0.38*(skill/(100.0+skill)) + 0.10*(coord/(100.0+coord)) + 0.08*(aware/(100.0+aware))
        power=max(1.0,num(w.get("launch_power_index",w.get("draw_power_index",60.0))))*cond
    else:
        draw=max(1.0,num(w.get("draw_power_index"),60.0)); strength_factor=max(0.55,min(1.12,max(0.0,num(strength))/draw))
        control=0.48 + 0.72*(skill/(100.0+skill)) + 0.18*(coord/(100.0+coord)) + 0.12*(aware/(100.0+aware))
        power=draw*strength_factor*(0.78+0.34*(skill/(100.0+skill)))*cond
    eff=base_eff*control*cond
    mx=base_max*(0.78+0.22*control)*cond
    base_cycle=max(0.8,num(w.get("base_shot_cycle_seconds",w.get("base_reload_cycle_seconds",6.0)),6.0))
    cycle=max(0.8,base_cycle/(0.70+0.55*(skill/(100.0+skill))+0.18*(coord/(100.0+coord))))
    return {"effective_range_m":round(eff,3),"maximum_direct_range_m":round(max(eff,mx),3),"cycle_seconds":round(cycle,3),"launch_power_index":round(power,3)}


def projectile_flight_resolution(
    weapon: Mapping[str, Any] | None,
    projectile: Mapping[str, Any] | None,
    *,
    distance_m: float,
    weapon_skill: float = 0.0,
    strength: float = 0.0,
    coordination: float = 0.0,
    awareness: float = 0.0,
    weapon_condition_pct: float = 100.0,
    projectile_condition_pct: float = 100.0,
    wind_cross_mps: float = 0.0,
) -> dict[str, Any]:
    """Resolve one bow/crossbow projectile from launch through target arrival.

    Bow launch energy depends on whether the archer can physically draw and
    release the bow cleanly. Crossbow launch energy is stored in the spanned
    mechanism: shooter skill affects aim/ranging/timing, never the latched power.
    The returned impact/penetration are the physical values that continue into
    shield -> armor -> anatomy.
    """
    weapon = weapon if isinstance(weapon, Mapping) else {}
    projectile = projectile if isinstance(projectile, Mapping) else {}
    family = str(weapon.get("family", weapon.get("schema", ""))).lower()
    distance = max(0.0, num(distance_m))
    condition = condition_factor(weapon_condition_pct)
    projectile_condition = condition_factor(projectile_condition_pct)
    nominal_power = max(1.0, num(weapon.get("draw_power_index", weapon.get("launch_power_index", 50.0)), 50.0))
    handling = clamp(num(weapon.get("handling"), 0.8), 0.35, 1.20)
    skill = max(0.0, num(weapon_skill))
    strength = max(0.0, num(strength))
    coordination = max(0.0, num(coordination))
    awareness = max(0.0, num(awareness))

    if family == "crossbow" or str(weapon.get("schema", "")).lower() == "crossbow":
        # Once fully spanned and latched the mechanism, not the shooter's body,
        # determines launch energy. Skill still matters enormously for pointing,
        # range estimation and release timing.
        draw_fraction = 1.0
        release_efficiency = 1.0
        launch_power = nominal_power * condition
        mechanism_power = True
    else:
        minimum = clamp(num(weapon.get("minimum_stable_draw_fraction"), 0.60), 0.35, 1.0)
        strength_ratio = strength / max(1.0, nominal_power)
        draw_fraction = clamp(strength_ratio, minimum, 1.08)
        release_efficiency = clamp(0.78 + 0.00125 * skill + 0.00075 * coordination, 0.72, 1.08)
        launch_power = nominal_power * draw_fraction * release_efficiency * condition
        mechanism_power = False

    projectile_profile = max(0.25, num(projectile.get("projectile_profile"), 1.0))
    projectile_mass = max(0.02, num(projectile.get("mass_kg"), 0.065))
    # Index-to-speed map is deliberately monotonic rather than a second power
    # system. It gives believable flight times while preserving the catalog's
    # authoritative launch-power ordering.
    launch_velocity = (27.0 + 0.39 * launch_power) * clamp((projectile_mass / 0.065) ** -0.08, 0.88, 1.12)
    envelope = projectile_operating_envelope(weapon, weapon_skill=skill, strength=strength, coordination=coordination, awareness=awareness, weapon_condition_pct=weapon_condition_pct)
    effective_range = max(20.0, num(envelope.get("effective_range_m"), 100.0))
    range_ratio = distance / effective_range
    drag_retention = math.exp(-0.24 * max(0.0, range_ratio))
    velocity_at_contact = max(8.0, launch_velocity * math.sqrt(drag_retention))
    arc_factor = 1.0 + 0.10 * range_ratio * range_ratio
    flight_time = 0.0 if distance <= 0 else (distance / max(1.0, (launch_velocity + velocity_at_contact) * 0.5)) * arc_factor
    impact = launch_power * projectile_profile * drag_retention * projectile_condition
    penetration = impact * max(0.05, num(projectile.get("armor_penetration"), 1.0))

    range_difficulty = 18.0 * range_ratio + 11.0 * range_ratio * range_ratio
    wind_difficulty = abs(num(wind_cross_mps)) * max(0.0, flight_time) * 2.1
    aim_control = (0.56 * skill + 0.24 * coordination + 0.20 * awareness) * handling - range_difficulty - wind_difficulty
    dispersion_m = max(0.02, distance * (0.014 + 0.00010 * max(0.0, 120.0 - aim_control)))
    return {
        "weapon_family": family or "bow",
        "mechanism_sets_launch_power": mechanism_power,
        "nominal_power_index": round(nominal_power, 3),
        "draw_fraction": round(draw_fraction, 5),
        "release_efficiency": round(release_efficiency, 5),
        "launch_power_index": round(launch_power, 3),
        "launch_velocity_mps": round(launch_velocity, 3),
        "contact_velocity_mps": round(velocity_at_contact, 3),
        "distance_m": round(distance, 3),
        "flight_time_seconds": round(flight_time, 4),
        "drag_retention": round(drag_retention, 5),
        "impact_index": round(max(0.0, impact), 3),
        "penetration_index": round(max(0.0, penetration), 3),
        "aim_control": round(aim_control, 3),
        "dispersion_m": round(dispersion_m, 4),
        "projectile_recovery_base": clamp(num(projectile.get("recovery_base"), 0.0), 0.0, 0.95),
    }

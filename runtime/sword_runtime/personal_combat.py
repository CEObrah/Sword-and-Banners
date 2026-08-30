from __future__ import annotations

import copy
import math
from typing import Any, Mapping

from sword_runtime.anatomy import (
    anatomical_target,
    anatomy_function_factors,
    anatomy_function_profile,
    apply_irreversible_anatomy,
    apply_structural_injury_state,
    resolve_anatomical_contact,
    resolve_actual_contact_target,
    resolve_structural_injury,
)
from sword_runtime.combat_doctrine import load_personal_combat_doctrine
from sword_runtime.combat_geometry import (
    body_intersections_on_segment,
    first_static_obstacle_on_segment,
    line_of_sight_query,
    line_of_sight_to_point,
    members_in_cone,
    members_in_lane,
    members_in_radius,
    normalize_position,
    safest_escape_vector,
    surrounding_pressure,
    surface_gap,
)
from sword_runtime.combat_objectives import evaluate_objective, objective_model
from sword_runtime.fatigue import endurance_fatigue_rate_factor, person_fatigue_factors

from sword_runtime.combat_tactics import (
    attack_detection_assessment,
    build_team_plan,
    choose_tactical_target,
    flank_vector,
    physical_defense_preferences,
)

from sword_runtime.contact_physics import (
    angle_from_margin,
    armor_contact_resolution,
    clamp as physics_clamp,
    condition_factor as physics_condition_factor,
    contact_grade_multiplier,
    mount_effective_speed_mps,
    projectile_flight_resolution,
    projectile_operating_envelope,
    projectile_weapon_deflection_resolution,
    mounted_charge_resolution,
    shield_contact_resolution,
    weapon_contact_wear,
    weapon_penetration_factor,
    weapon_penetration_index,
)


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _unarmed_method_profile(intent: Any) -> dict[str, Any]:
    """Return explicit body reach/timing for ordinary unarmed methods.

    Surface gap is measured from the attacker's body center to the target's
    occupied body radius, so these values describe usable limb extension beyond
    the defender's surface rather than a generic weapon-like reach band.  The
    profile is intentionally small and deterministic; grappling has its own
    engagement-distance authority and is not routed through this table.
    """
    low = str(intent or "").lower()
    if any(token in low for token in ("headbutt", "head butt")):
        return {"method": "headbutt", "reach_m": 0.16, "startup_factor": 0.90, "recovery_factor": 1.00, "force_factor": 1.05}
    if any(token in low for token in ("elbow", "forearm smash")):
        return {"method": "elbow", "reach_m": 0.24, "startup_factor": 0.82, "recovery_factor": 0.92, "force_factor": 1.08}
    if any(token in low for token in ("knee", "kneestrike", "knee strike")):
        return {"method": "knee", "reach_m": 0.30, "startup_factor": 0.88, "recovery_factor": 1.02, "force_factor": 1.12}
    if any(token in low for token in ("kick", "roundhouse", "side kick", "front kick", "teep")):
        return {"method": "kick", "reach_m": 0.78, "startup_factor": 1.15, "recovery_factor": 1.22, "force_factor": 1.24}
    # Punch/hand strike is the ordinary fallback.  This deliberately replaces
    # the former 0.65 m generic pseudo-weapon that made every unarmed method
    # inherit the same physical range.
    return {"method": "punch", "reach_m": 0.44, "startup_factor": 0.92, "recovery_factor": 0.92, "force_factor": 1.00}


def _stats(person: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    skills = person.get("skills", {}) if isinstance(person.get("skills"), Mapping) else {}
    attrs = person.get("attributes", {}) if isinstance(person.get("attributes"), Mapping) else {}
    if str(person.get("schema")) == "person-lite" and isinstance(person.get("stats"), Mapping):
        stats = person.get("stats", {})
        skills = stats.get("skills", {}) if isinstance(stats.get("skills"), Mapping) else {}
        attrs = stats.get("attributes", {}) if isinstance(stats.get("attributes"), Mapping) else {}
    return skills, attrs


def _fatigue(person: Mapping[str, Any]) -> int:
    health = person.get("health")
    if isinstance(health, Mapping):
        return max(0, int(health.get("fatigue", person.get("fatigue", 0)) or 0))
    return max(0, int(person.get("fatigue", 0) or 0))


def _set_fatigue(person: dict[str, Any], value: int) -> None:
    value = max(0, min(100, int(value)))
    if isinstance(person.get("health"), dict):
        person["health"]["fatigue"] = value
    else:
        person["fatigue"] = value


def _injury_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    injury_id = str(row.get("injury_id", ""))
    if injury_id:
        return ("id", injury_id)
    return (
        "legacy",
        str(row.get("inflicted_at", "")),
        str(row.get("inflicted_at_offset_s", "")),
        str(row.get("body_zone", "")),
        str(row.get("side", "")),
        str(row.get("contact_structure", "")),
        str(row.get("mechanism", "")),
        str(row.get("source_weapon", "")),
        str(row.get("label", "")),
    )


def active_injury_rows(person: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return unique active wounds, including the mirrored primary injury."""
    rows: list[Mapping[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    raw = person.get("injuries")
    if isinstance(raw, list):
        for row in raw:
            if not isinstance(row, Mapping) or not bool(row.get("active", True)):
                continue
            key = _injury_key(row)
            if key not in seen:
                rows.append(row)
                seen.add(key)
    primary = person.get("injury_state")
    if isinstance(primary, Mapping) and bool(primary.get("active", True)):
        key = _injury_key(primary)
        if key not in seen:
            rows.append(primary)
    return rows


def sync_injury_record(person: dict[str, Any], updated: Mapping[str, Any]) -> None:
    """Keep the primary injury mirror and injury ledger causally identical."""
    row = dict(updated)
    person["injury_state"] = row
    key = _injury_key(row)
    injuries = person.get("injuries")
    if not isinstance(injuries, list):
        injuries = []
        person["injuries"] = injuries
    replaced = False
    for index, existing in enumerate(injuries):
        if isinstance(existing, Mapping) and _injury_key(existing) == key:
            injuries[index] = dict(row)
            replaced = True
            break
    if not replaced:
        injuries.append(dict(row))


def settle_injury_recovery_hours(person: dict[str, Any], *, elapsed_hours: int, resolved_at: str) -> dict[str, Any]:
    """Advance every active wound's closure clock without changing anatomy.

    The old recovery reducer advanced only ``injury_state``.  In a multi-wound
    fight that allowed older ledger wounds to remain active forever while the
    mirrored primary wound healed.  Recovery is now a set operation over unique
    injury identities; anatomy remains a separate permanent authority.
    """
    hours = max(0, int(elapsed_hours))
    primary = person.get("injury_state") if isinstance(person.get("injury_state"), Mapping) else None
    primary_key = _injury_key(primary) if isinstance(primary, Mapping) else None
    raw = person.get("injuries") if isinstance(person.get("injuries"), list) else []
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for source in list(raw) + ([primary] if isinstance(primary, Mapping) else []):
        if not isinstance(source, Mapping):
            continue
        key = _injury_key(source)
        if key in seen:
            continue
        seen.add(key)
        rows.append(dict(source))

    anatomy = person.get("anatomy_state") if isinstance(person.get("anatomy_state"), Mapping) else {}
    structural = anatomy.get("structural_damage") if isinstance(anatomy.get("structural_damage"), Mapping) else {}
    resolved_ids: list[str] = []
    still_active: list[str] = []
    for row in rows:
        if not bool(row.get("active", True)):
            continue
        row["recovered_hours"] = max(0, int(row.get("recovered_hours", 0) or 0)) + hours
        minimum = max(0, int(row.get("minimum_recovery_hours", 0) or 0))
        if row["recovered_hours"] < minimum:
            still_active.append(str(row.get("injury_id") or row.get("label") or "injury"))
            continue
        row["active"] = False
        row["resolved_at"] = str(resolved_at)
        bleeding = row.get("bleeding") if isinstance(row.get("bleeding"), dict) else None
        if bleeding is not None:
            bleeding["controlled"] = True
            bleeding["rate_units_per_minute"] = 0.0
            bleeding["internal_rate_units_per_minute"] = 0.0
        row["bleeding_units_per_minute"] = 0.0
        row["internal_bleeding_units_per_minute"] = 0.0
        permanent = bool(row.get("permanent_anatomy"))
        for key in row.get("structural_state_changes", []) if isinstance(row.get("structural_state_changes"), list) else []:
            srow = structural.get(str(key)) if isinstance(structural, Mapping) else None
            if isinstance(srow, Mapping) and bool(srow.get("permanent_sequela")):
                permanent = True
                break
        if permanent:
            row["healed_with_permanent_sequelae"] = True
            row["recovery_rule"] = "soft-tissue recovery does not regenerate absent/destroyed anatomy or permanent structural loss"
        resolved_ids.append(str(row.get("injury_id") or row.get("label") or "injury"))

    person["injuries"] = rows
    if primary_key is not None:
        mirrored = next((dict(row) for row in rows if _injury_key(row) == primary_key), None)
        if mirrored is not None:
            person["injury_state"] = mirrored
    elif rows:
        active_rows = [row for row in rows if bool(row.get("active", True))]
        person["injury_state"] = dict(active_rows[-1] if active_rows else rows[-1])
    return {
        "resolved_injury_refs": resolved_ids,
        "active_injury_refs": still_active,
        "active_count": sum(1 for row in rows if bool(row.get("active", True))),
    }


def injury_physiology_snapshot(person: Mapping[str, Any]) -> dict[str, float]:
    """Compute current wound-driven physiology without advancing time.

    Multiple injuries accumulate.  Respiratory compromise combines by remaining
    functional capacity rather than taking only the single worst wound, and extra
    wounds add shock burden instead of disappearing behind the maximum severity.
    """
    bleeding = 0.0
    pain_sq = 0.0
    respiratory_survival = 1.0
    neuro = 0.0
    severity_index = 0
    severity_sum = 0.0
    for row in active_injury_rows(person):
        bleed = row.get("bleeding") if isinstance(row.get("bleeding"), Mapping) else {}
        if not bool(bleed.get("controlled", False)):
            bleeding += max(0.0, _num(bleed.get("rate_units_per_minute"), row.get("bleeding_units_per_minute", 0.0)))
        row_pain = max(0.0, _num(row.get("pain")))
        pain_sq += row_pain * row_pain
        row_severity = int(_num(row.get("severity_index"), {"minor": 1, "moderate": 2, "serious": 3, "severe": 3, "critical": 4}.get(str(row.get("severity", "")).lower(), 0)))
        severity_index = max(severity_index, row_severity)
        severity_sum += max(0, row_severity)
        row_respiratory = _clamp(_num(row.get("respiratory_compromise")), 0.0, 100.0)
        respiratory_survival *= max(0.0, 1.0 - row_respiratory / 100.0)
        neuro = max(neuro, _clamp(_num(row.get("neurological_impairment")), 0.0, 100.0))
    pain = min(100.0, math.sqrt(max(0.0, pain_sq)))
    respiratory = 100.0 * (1.0 - respiratory_survival)
    _, attrs = _stats(person)
    reserve = (
        0.35 * _num(attrs.get("Toughness"))
        + 0.35 * _num(attrs.get("Composure"))
        + 0.20 * _num(attrs.get("Endurance"))
        + 0.10 * _num(attrs.get("Coordination"))
    )
    phys = person.get("physiology_state") if isinstance(person.get("physiology_state"), Mapping) else {}
    blood = max(0.0, _num(phys.get("blood_loss_units")))
    extra_wound_burden = max(0.0, severity_sum - severity_index) * 6.0
    shock = severity_index * 18.0 + extra_wound_burden + bleeding + blood / 2.0 + pain / 5.0
    return {
        "bleeding": bleeding,
        "pain": pain,
        "severity_index": float(severity_index),
        "severity_sum": float(severity_sum),
        "respiratory": respiratory,
        "neurological": neuro,
        "reserve": max(1.0, reserve),
        "blood": blood,
        "shock": shock,
    }


def advance_injury_physiology(
    person: dict[str, Any],
    injury_mechanics: Mapping[str, Any],
    *,
    elapsed_seconds: float,
) -> dict[str, Any]:
    """Advance exact blood/shock/respiratory state by real elapsed seconds.

    This helper deliberately does not set the runtime's health/life authority;
    callers own those state transitions. It returns the physically implied state
    so personal combat, treatment, or another exact-person owner can apply it.
    """
    elapsed = max(0.0, float(elapsed_seconds))
    before = injury_physiology_snapshot(person)
    phys = person.setdefault("physiology_state", {})
    phys["blood_loss_units"] = round(before["blood"] + before["bleeding"] * elapsed / 60.0, 6)
    physiology = injury_mechanics.get("physiology", {}) if isinstance(injury_mechanics, Mapping) else {}
    respiratory_thresholds = physiology.get("respiratory_failure_thresholds", {}) if isinstance(physiology, Mapping) else {}
    compensated_respiratory = _clamp(_num(respiratory_thresholds.get("compensated_compromise_percent"), 35.0), 0.0, 95.0)
    respiratory_failure_fraction = _clamp(
        (before["respiratory"] - compensated_respiratory) / max(1.0, 100.0 - compensated_respiratory),
        0.0,
        1.0,
    )
    phys["respiratory_failure_equivalent_seconds"] = round(
        max(0.0, _num(phys.get("respiratory_failure_equivalent_seconds")))
        + respiratory_failure_fraction * elapsed,
        6,
    )
    after = injury_physiology_snapshot(person)
    blood_thresholds = physiology.get("blood_loss_thresholds", {}) if isinstance(physiology, Mapping) else {}
    blood_degraded = _num(blood_thresholds.get("degraded"), 35.0)
    blood_critical = _num(blood_thresholds.get("critical"), 80.0)
    blood_unconscious = _num(blood_thresholds.get("unconscious"), 100.0)
    blood_death = _num(blood_thresholds.get("irreversible_circulatory_collapse"), 140.0)
    respiratory_unconscious = _num(respiratory_thresholds.get("unconscious_equivalent_seconds_at_full_compromise"), 90.0)
    respiratory_death = _num(respiratory_thresholds.get("irreversible_equivalent_seconds_at_full_compromise"), 240.0)
    blood = after["blood"]
    respiratory_failure = max(0.0, _num(phys.get("respiratory_failure_equivalent_seconds")))
    shock = after["shock"]
    reserve = after["reserve"]
    if blood >= blood_death or respiratory_failure >= respiratory_death:
        state = "dead"
        consciousness = "absent"
        circulation = "irreversible_collapse" if blood >= blood_death else "respiratory_arrest"
    elif blood >= blood_unconscious or respiratory_failure >= respiratory_unconscious or shock > reserve or after["neurological"] >= 96.0:
        state = "incapacitated"
        consciousness = "unconscious"
        circulation = "critical" if blood >= blood_critical or shock > reserve else "compromised"
    else:
        state = "degraded" if blood >= blood_degraded or shock >= reserve - 15.0 else "alert"
        consciousness = state
        circulation = "critical" if blood >= blood_critical else ("compromised" if blood >= blood_degraded else "stable")
    phys["bleeding_units_per_minute"] = round(after["bleeding"], 5)
    phys["shock_index"] = round(shock, 5)
    phys["control_reserve"] = round(reserve, 5)
    phys["shock_ratio"] = round(shock / max(1.0, reserve), 6)
    phys["respiratory_compromise"] = round(after["respiratory"], 5)
    phys["neurological_impairment"] = round(after["neurological"], 5)
    phys["consciousness"] = consciousness
    phys["circulation_state"] = circulation
    return {
        **after,
        "state": state,
        "consciousness": consciousness,
        "circulation_state": circulation,
        "respiratory_failure_equivalent_seconds": respiratory_failure,
    }


def recover_injury_physiology(
    person: dict[str, Any],
    injury_mechanics: Mapping[str, Any],
    *,
    elapsed_hours: float,
) -> dict[str, Any]:
    """Restore systemic reserve during stable recovery without healing anatomy."""
    hours = max(0.0, float(elapsed_hours))
    physiology = injury_mechanics.get("physiology", {}) if isinstance(injury_mechanics, Mapping) else {}
    respiratory_thresholds = physiology.get("respiratory_failure_thresholds", {}) if isinstance(physiology, Mapping) else {}
    compensated = _clamp(_num(respiratory_thresholds.get("compensated_compromise_percent"), 35.0), 0.0, 95.0)
    phys = person.setdefault("physiology_state", {})
    blood_recovery = max(0.0, _num(physiology.get("blood_volume_recovery_units_per_hour"), 2.0)) * hours
    phys["blood_loss_units"] = round(max(0.0, _num(phys.get("blood_loss_units")) - blood_recovery), 6)
    current = injury_physiology_snapshot(person)
    if current["respiratory"] <= compensated + 1e-9:
        debt_recovery = max(0.0, _num(physiology.get("respiratory_failure_recovery_equivalent_seconds_per_hour"), 1800.0)) * hours
        phys["respiratory_failure_equivalent_seconds"] = round(
            max(0.0, _num(phys.get("respiratory_failure_equivalent_seconds")) - debt_recovery),
            6,
        )
    return advance_injury_physiology(person, injury_mechanics, elapsed_seconds=0.0)


def committed_action_survives_incapacitation(action: Mapping[str, Any], *, incapacitated_at_s: float, resolve_at_s: float, simultaneous_window_s: float) -> bool:
    """Whether physical momentum/release survives the actor becoming inactive.

    Unreleased/uncontacted ordinary melee collapses with the body.  A projectile
    already released remains a physical object.  A committed mounted collision
    retains momentum.  A weapon contact already inside the simultaneous-contact
    interval may still land rather than receiving retroactive cancellation.
    """
    kind=str(action.get("kind", ""))
    incap=float(incapacitated_at_s)
    resolve=float(resolve_at_s)
    simultaneous=max(0.0,float(simultaneous_window_s))
    start=_num(action.get("start_at_s"),resolve)
    if kind=="projectile_contact":
        release=_num(action.get("release_at_s"),1e18)
        return release <= incap + 1e-9 if incap > -900.0 else True
    if kind=="attack" and action.get("mounted_body_collision"):
        # Momentum survives only if the collision was actually committed before a known
        # incapacitation.  A body already inactive before the scene cannot acquire a
        # fresh mounted-collision entitlement merely because an action was queued.
        return incap > -900.0 and start <= incap + 1e-9
    if kind=="attack" and incap > -900.0 and start <= incap + 1e-9 and resolve-incap <= simultaneous+1e-9:
        return True
    return False


def active_defense_recovery_window_seconds(
    timing_profile: Mapping[str, Any],
    saturation_mechanics: Mapping[str, Any] | None = None,
) -> float:
    """Whole-body reaction-load recovery window for exact personal combat.

    This is intentionally separate from weapon/shield-specific guard readiness.
    A defender can regain gross body reaction bandwidth before a displaced blade
    or shield has fully returned to its preferred line, and vice versa.
    """
    cfg = saturation_mechanics if isinstance(saturation_mechanics, Mapping) else {}
    reaction = max(0.01, _num(timing_profile.get("reaction_seconds"), 0.10))
    multiplier = max(0.05, _num(cfg.get("recovery_reaction_multiplier"), 1.35))
    minimum = max(0.01, _num(cfg.get("recovery_min_seconds"), 0.10))
    maximum = max(minimum, _num(cfg.get("recovery_max_seconds"), 0.90))
    return _clamp(reaction * multiplier, minimum, maximum)


def decayed_active_defense_load(
    load: float,
    *,
    last_update_s: float,
    at_s: float,
    recovery_window_s: float,
) -> float:
    """Linearly recover short-lived whole-body defense commitment."""
    current = _clamp(float(load), 0.0, 1.0)
    elapsed = max(0.0, float(at_s) - float(last_update_s))
    if current <= 0.0 or elapsed <= 0.0:
        return current
    return max(0.0, current - elapsed / max(0.01, float(recovery_window_s)))


def active_defense_commitment_fraction(
    *,
    attacker_timing: Mapping[str, Any],
    defender_timing: Mapping[str, Any],
    positive_control_pressure: float,
    new_source: bool,
    saturation_mechanics: Mapping[str, Any] | None = None,
) -> float:
    """Return how much ordinary active-defense bandwidth one response consumes.

    Faster threats relative to the defender's reaction, difficult control
    pressure, and a newly conflicting attacker consume more bandwidth. Passive
    armor and material interception never call this helper.
    """
    cfg = saturation_mechanics if isinstance(saturation_mechanics, Mapping) else {}
    base = _clamp(_num(cfg.get("base_commitment"), 0.18), 0.01, 1.0)
    max_commit = _clamp(_num(cfg.get("max_commitment_per_response"), 0.90), base, 1.0)
    attacker_startup = max(0.04, _num(attacker_timing.get("attack_startup_seconds"), 0.20))
    defender_reaction = max(0.01, _num(defender_timing.get("reaction_seconds"), 0.10))
    speed_ratio = _clamp(defender_reaction / attacker_startup, 0.0, 2.6)
    speed_weight = max(0.0, _num(cfg.get("speed_ratio_weight"), 0.24))
    pressure_scale = max(1.0, _num(cfg.get("pressure_margin_scale"), 120.0))
    pressure_cap = max(0.0, _num(cfg.get("pressure_commitment_max"), 0.18))
    pressure = min(pressure_cap, max(0.0, float(positive_control_pressure)) / pressure_scale * pressure_cap)
    source_extra = max(0.0, _num(cfg.get("new_source_commitment"), 0.08)) if new_source else 0.0
    return _clamp(base + speed_weight * speed_ratio + pressure + source_extra, base, max_commit)


class PersonalCombatMixin:
    """Deterministic, narratable exact-person combat slices.

    The mixin deliberately stops exact combat at the first material decision
    boundary instead of converting an entire duel into one opaque score.  It
    reuses the same item/loadout/stat-derived burden authorities as formation
    combat and returns only player-visible physical causality.
    """

    _PERSONAL_BODY_ZONES = (
        "head",
        "neck",
        "upper_torso",
        "lower_torso",
        "upper_arms",
        "forearms_hands",
        "thighs",
        "lower_legs_feet",
    )

    _PERSONAL_FAMILY_SKILL = {
        "sword": "Sword",
        "spear": "Polearms",
        "glaive": "Polearms",
        "axe": "Heavy Weapons",
        "mace": "Heavy Weapons",
        "staff": "Polearms",
        "dagger": "Sword",
        "bow": "Bow",
        "crossbow": "Crossbow",
    }

    def _personal_manifest_items(self, person_ref: str, person: Mapping[str, Any]) -> list[dict[str, Any]]:
        manifest: Mapping[str, Any] | None = None
        if person_ref == self.PLAYER_ACTOR:
            manifest = self.read("state/player-detail/equipment-manifest.json")
        else:
            manifest_ref = person.get("equipment_manifest_ref")
            if isinstance(manifest_ref, str):
                candidate = self.read_optional(manifest_ref)
                if isinstance(candidate, Mapping):
                    manifest = candidate
        equipped: list[dict[str, Any]] = []
        if isinstance(manifest, Mapping):
            for raw in manifest.get("equipment_manifest", []):
                if not isinstance(raw, Mapping):
                    continue
                state = str(raw.get("current_state", "")).lower()
                if any(token in state for token in ("equipped", "worn", "readied", "quivered", "mounted")):
                    equipped.append(dict(raw))
        return equipped

    @staticmethod
    def _personal_item_slot(item: Mapping[str, Any]) -> str | None:
        schema = str(item.get("schema", ""))
        family = str(item.get("family", "")).lower()
        category = str(item.get("equipment_category", "")).lower()
        if schema == "melee_weapon":
            return "primary_melee_weapon"
        if schema in {"bow", "crossbow"} or family in {"bow", "crossbow"}:
            return "ranged_weapon"
        if schema == "projectile" or family in {"arrow", "bolt"}:
            return "ammunition_item"
        if schema == "human_armor" or category == "armor":
            return "body_armor"
        if schema == "helmet":
            return "helmet"
        if schema == "shield":
            return "shield"
        if schema == "mount" or schema.startswith("mount_") or schema.startswith("mount_v"):
            return "mount"
        if schema == "horse_armor":
            return "horse_armor"
        if schema.startswith("tack_") or "tack" in schema:
            return "tack"
        return None

    def _personal_improvised_prop_profile(self, fact_ref: str) -> dict[str, Any]:
        """Promote one exact active-scene mundane prop into transient combat physics.

        Scene history establishes only that the mundane prop is present/handled.
        All combat values below are server-owned conservative category values.
        No inventory, market value, equipment condition, or durable item identity
        is created by this bridge.
        """
        from sword_runtime.scene_sessions import ACTIVE_SESSION_PATH, active_scene_session, scene_history_record

        player = self.read("state/player.json")
        player_location = self._person_location(player)
        active = active_scene_session(self)
        continuation_state = None
        session = active
        if not isinstance(session, Mapping):
            raw_session = self.read_optional(ACTIVE_SESSION_PATH)
            local_state = player.get("combat_state", {}).get("local_combat_state", {}) if isinstance(player.get("combat_state"), Mapping) else {}
            saved_prop = local_state.get("improvised_prop_state") if isinstance(local_state, Mapping) and isinstance(local_state.get("improvised_prop_state"), Mapping) else None
            if (
                isinstance(raw_session, Mapping)
                and raw_session.get("schema") == "sword-scene-session"
                and raw_session.get("status") == "closed"
                and raw_session.get("close_reason") == "hard_interruption"
                and isinstance(saved_prop, Mapping)
                and str(saved_prop.get("fact_ref") or "") == str(fact_ref)
                and str(saved_prop.get("status") or "held") == "held"
                and _num(saved_prop.get("condition_pct"), 0.0) > 0.0
                and str(saved_prop.get("source_session_ref") or "") == str(raw_session.get("session_ref") or "")
            ):
                session = raw_session
                continuation_state = saved_prop
        if not isinstance(session, Mapping):
            raise ValueError("improvised personal-combat prop requires the active scene or its immediate combat continuation")
        session_ref = str(session.get("session_ref") or "")
        row = scene_history_record(self, fact_ref, session_ref=session_ref)
        if not isinstance(row, Mapping):
            raise ValueError("improvised personal-combat prop fact is not available in the active scene")
        if row.get("fact_kind") != "object_state" or row.get("actor_ref") != self.PLAYER_ACTOR:
            raise ValueError("improvised personal-combat prop must be Wei's active-scene object_state fact")
        prop = row.get("improvised_prop") if isinstance(row.get("improvised_prop"), Mapping) else None
        if not isinstance(prop, Mapping) or prop.get("kind") != "mundane_improvised_prop":
            raise ValueError("scene fact is not a typed mundane improvised prop")
        source_object_fact_ref = str(row.get("source_object_fact_ref") or "")
        basis_refs = {
            ref for ref in row.get("basis_refs", []) if isinstance(ref, str)
        } if isinstance(row.get("basis_refs"), list) else set()
        source_object_fact = (
            scene_history_record(self, source_object_fact_ref, session_ref=session_ref)
            if source_object_fact_ref and source_object_fact_ref in basis_refs
            else None
        )
        if not (
            isinstance(source_object_fact, Mapping)
            and source_object_fact.get("fact_kind") == "object_state"
            and source_object_fact.get("truth_status") == "observed_reversible_scene_fact"
            and source_object_fact.get("mechanical_consequence_authority") is False
            and isinstance(source_object_fact.get("improvised_prop"), Mapping)
            and dict(source_object_fact.get("improvised_prop")) == dict(prop)
        ):
            source_object_fact = None
        if not isinstance(source_object_fact, Mapping):
            raise ValueError("improvised personal-combat prop lacks prior scene-object provenance")
        if not player_location or str(session.get("location_ref") or "") != str(player_location):
            raise ValueError("improvised personal-combat prop is not established at Wei's exact current location")

        form = str(prop.get("form") or "")
        material = str(prop.get("material") or "")
        condition = str(prop.get("condition") or "intact")
        base = {
            "small_rigid": {"family": "mace", "reach_m": 0.38, "minimum_range_m": 0.0, "handling": 0.92, "base_force_blunt": 0.42, "recovery_class": "quick", "skill_name": "Unarmed"},
            "short_rigid": {"family": "mace", "reach_m": 0.72, "minimum_range_m": 0.0, "handling": 0.80, "base_force_blunt": 0.56, "recovery_class": "standard", "skill_name": "Heavy Weapons"},
            "long_rigid": {"family": "staff", "reach_m": 1.45, "minimum_range_m": 0.12, "handling": 0.72, "base_force_blunt": 0.52, "recovery_class": "standard", "skill_name": "Polearms"},
            "heavy_rigid": {"family": "mace", "reach_m": 0.62, "minimum_range_m": 0.0, "handling": 0.56, "base_force_blunt": 0.72, "recovery_class": "slow", "skill_name": "Heavy Weapons"},
            "sharp_fragment": {"family": "dagger", "reach_m": 0.34, "minimum_range_m": 0.0, "handling": 0.84, "base_force_cut": 0.38, "base_force_thrust": 0.34, "base_force_blunt": 0.18, "recovery_class": "quick", "skill_name": "Sword"},
        }.get(form)
        if base is None:
            raise ValueError("improvised personal-combat prop form is unsupported")
        material_factor = {"bamboo": 0.82, "wood": 0.88, "bone": 0.86, "ceramic": 0.90, "metal": 1.00, "stone": 1.04}.get(material)
        condition_factor = {"intact": 1.00, "worn": 0.95, "cracked": 0.82, "broken_piece": 0.80}.get(condition)
        if material_factor is None or condition_factor is None:
            raise ValueError("improvised personal-combat prop material/condition is unsupported")
        form_mass_kg = {"small_rigid": 0.42, "short_rigid": 0.90, "long_rigid": 1.55, "heavy_rigid": 2.60, "sharp_fragment": 0.18}[form]
        material_mass_factor = {"bamboo": 0.62, "wood": 0.78, "bone": 0.72, "ceramic": 0.88, "metal": 1.18, "stone": 1.35}[material]
        material_structure = {"bamboo": 26.0, "wood": 34.0, "bone": 29.0, "ceramic": 15.0, "metal": 62.0, "stone": 43.0}[material]
        form_structure_factor = {"small_rigid": 0.82, "short_rigid": 1.00, "long_rigid": 0.86, "heavy_rigid": 1.18, "sharp_fragment": 0.48}[form]
        starting_condition_pct = {"intact": 100.0, "worn": 78.0, "cracked": 46.0, "broken_piece": 35.0}[condition]
        if isinstance(continuation_state, Mapping):
            starting_condition_pct = _clamp(_num(continuation_state.get("condition_pct"), starting_condition_pct), 0.0, 100.0)
        weapon = {key: value for key, value in base.items() if key != "skill_name"}
        for key in ("base_force_cut", "base_force_thrust", "base_force_blunt"):
            if key in weapon:
                weapon[key] = round(float(weapon[key]) * material_factor * condition_factor, 5)
        weapon.update({
            "id": str(fact_ref),
            "combat_identity_kind": "scene_improvised_prop",
            "source_scene_fact_ref": str(fact_ref),
            "material": material,
            "condition": condition,
            "mass_kg": round(form_mass_kg * material_mass_factor, 4),
            "structural_capacity": round(material_structure * form_structure_factor, 4),
        })
        return {
            "fact_ref": str(fact_ref),
            "source_object_fact_ref": source_object_fact_ref,
            "source_session_ref": session_ref,
            "source_location_ref": str(player_location),
            "summary": str(row.get("summary") or "mundane improvised prop"),
            "form": form, "material": material, "condition": condition,
            "condition_pct": starting_condition_pct,
            "status": "held",
            "skill_name": str(base["skill_name"]),
            "weapon": weapon,
            "authority": "transient_profile_from_active_scene_fact",
            "durable_item_created": False,
        }

    def _personal_equipment_profile(self, person_ref: str, person: Mapping[str, Any]) -> dict[str, Any]:
        skills, attrs = _stats(person)
        equipped = self._personal_manifest_items(person_ref, person)
        condition_by_item: dict[str, float] = {}
        for entry in equipped:
            item_id = str(entry.get("item_id", ""))
            if item_id:
                condition_by_item[item_id] = _clamp(_num(entry.get("condition_pct"), 100.0), 0.0, 100.0)
        saved_condition = person.get("equipment_condition", {}) if isinstance(person.get("equipment_condition"), Mapping) else {}
        for item_id, raw in saved_condition.items():
            if isinstance(item_id, str):
                condition_by_item[item_id] = _clamp(_num(raw, 100.0), 0.0, 100.0)
        combat_state = person.get("combat_state", {}) if isinstance(person.get("combat_state"), Mapping) else {}
        disarmed_item = str(combat_state.get("disarmed_weapon_id", ""))
        embedded_state = combat_state.get("embedded_weapon") if isinstance(combat_state.get("embedded_weapon"), Mapping) else {}
        embedded_item = str(embedded_state.get("item_id", "")) if embedded_state else ""
        unavailable_weapon_ids = {item_id for item_id in (disarmed_item, embedded_item) if item_id}
        if unavailable_weapon_ids:
            equipped = [row for row in equipped if str(row.get("item_id", "")) not in unavailable_weapon_ids]
        loadout: dict[str, Any] = {}
        item_ids: list[str] = []
        melee_candidates: list[tuple[float, str, Mapping[str, Any]]] = []
        ranged_candidates: list[tuple[float, str, Mapping[str, Any]]] = []

        for entry in equipped:
            item_id = str(entry.get("item_id", ""))
            if not item_id:
                continue
            try:
                item = self._item_record(item_id)
            except (ValueError, KeyError, FileNotFoundError):
                continue
            item_ids.append(item_id)
            # Condition zero is a durable unusable state.  The item may still be
            # physically present in custody (and therefore remain in the manifest),
            # but it cannot silently re-enter the combat loadout merely because the
            # saved equipment template still names it.
            if condition_by_item.get(item_id, 100.0) <= 0.0:
                continue
            slot = self._personal_item_slot(item)
            if slot == "primary_melee_weapon":
                force = max(_num(item.get("base_force_cut")), _num(item.get("base_force_thrust")), _num(item.get("base_force_blunt")))
                utility = force * 8.0 + _num(item.get("handling"), 0.8) * 5.0 + min(4.0, _num(item.get("reach_m"), 0.75)) * 1.5
                melee_candidates.append((utility, item_id, item))
            elif slot == "ranged_weapon":
                force = max(_num(item.get("base_force_cut")), _num(item.get("base_force_thrust")), _num(item.get("base_force_blunt")), _num(item.get("projectile_profile")))
                ranged_candidates.append((force, item_id, item))
            elif slot == "ammunition_item":
                loadout["ammunition_item"] = item_id
                loadout["carried_ammunition"] = max(0, int(entry.get("quantity", 0) or 0))
            elif slot and slot not in loadout:
                loadout[slot] = item_id

        if not equipped and hasattr(self, "_combat_person_loadout"):
            saved = self._combat_person_loadout(person)
            if isinstance(saved, Mapping):
                loadout.update({str(k): v for k, v in saved.items() if isinstance(v, str) and v})
                # A fallback loadout has no exact manifest row from which to read
                # quiver quantity. Preserve its registered initial carried amount
                # only for first initialization; the persistent combat-state
                # projectile ledger becomes authority after the first scene.
                if saved.get("ammunition_item"):
                    loadout["carried_ammunition"] = max(0, int(saved.get("carried_ammunition", 0) or 0))
                for slot_key, item_id in list(loadout.items()):
                    if isinstance(item_id, str) and condition_by_item.get(item_id, 100.0) <= 0.0:
                        loadout.pop(slot_key, None)
                for key in ("primary_melee_weapon", "sidearm"):
                    item_id = loadout.get(key)
                    if not isinstance(item_id, str):
                        continue
                    item = self._combat_weapon(item_id)
                    if not item:
                        continue
                    force = max(_num(item.get("base_force_cut")), _num(item.get("base_force_thrust")), _num(item.get("base_force_blunt")))
                    utility = force * 8.0 + _num(item.get("handling"), 0.8) * 5.0 + min(4.0, _num(item.get("reach_m"), 0.75)) * 1.5
                    melee_candidates.append((utility, item_id, item))
                ranged_id = loadout.get("ranged_weapon")
                if isinstance(ranged_id, str):
                    item = self._combat_weapon(ranged_id)
                    if item:
                        ranged_candidates.append((1.0, ranged_id, item))
                item_ids.extend(str(v) for v in loadout.values() if isinstance(v, str) and v and v not in item_ids)

        # A mount lost in exact combat is persistent body/equipment state, not a
        # one-exchange animation.  Static role loadouts may still say that this
        # person is normally mounted; that must not resurrect a horse which the
        # exact combat state already records as dead or combat-disabled.  Tack
        # and barding remain in custody but provide no live combat benefit once
        # the horse itself is unavailable.
        mount_state = person.get("mount_combat_state") if isinstance(person.get("mount_combat_state"), Mapping) else {}
        mount_status = str(mount_state.get("status", "active")).lower() if isinstance(mount_state, Mapping) else "active"
        if mount_status in {"dead", "disabled", "lost"} or bool(mount_state.get("serviceable") is False):
            loadout.pop("mount", None)
            loadout.pop("horse_armor", None)
            loadout.pop("tack", None)

        # Exact readied melee equipment controls the immediate duel. A bow in
        # the same saved loadout does not silently replace a readied spear.
        melee_candidates.sort(key=lambda row: row[0], reverse=True)
        ranged_candidates.sort(key=lambda row: row[0], reverse=True)

        # Permanent anatomy constrains what can physically be readied.  The item
        # remains in custody, but a fighter with one functional hand cannot use a
        # two-handed bow/glaive or simultaneously occupy that hand with both a
        # weapon and shield.  This is derived every combat slice from the saved
        # body state rather than persisted as a second disability flag.
        body_function = anatomy_function_profile(person)
        usable_hands = max(0, min(2, int(body_function.get("usable_hands", 2))))
        def grip_legal(row: tuple[float, str, Mapping[str, Any]]) -> bool:
            item = row[2]
            required = max(1, int(_num(item.get("hands_required", 1), 1)))
            return required <= usable_hands
        melee_candidates = [row for row in melee_candidates if grip_legal(row)]
        ranged_candidates = [row for row in ranged_candidates if grip_legal(row)]
        if usable_hands <= 0:
            loadout.pop("shield", None)
            loadout.pop("primary_melee_weapon", None)
            loadout.pop("sidearm", None)
            loadout.pop("ranged_weapon", None)
        elif usable_hands == 1:
            # Prefer an actual offensive weapon over carrying a shield in the
            # same only functional hand.  If no legal weapon exists the shield
            # may still be used while other unarmed body weapons remain possible.
            if melee_candidates:
                loadout.pop("shield", None)
            loadout.pop("ranged_weapon", None)

        best_melee_id: str | None = melee_candidates[0][1] if melee_candidates else None
        best_melee_weapon: Mapping[str, Any] = melee_candidates[0][2] if melee_candidates else {}
        best_ranged_id: str | None = ranged_candidates[0][1] if ranged_candidates else None
        best_ranged_weapon: Mapping[str, Any] = ranged_candidates[0][2] if ranged_candidates else {}
        # Preserve every exact readied combat channel in the returned loadout.
        # Immediate personal combat may still choose the melee weapon as its
        # currently readied primary, but formation hero windows must be able to
        # see a carried/readied bow or crossbow at the same time.  Omitting the
        # ranged slot here previously made exact named archers silently become
        # melee-only whenever they also had a sword, spear, or lance.
        if best_melee_id:
            loadout["primary_melee_weapon"] = best_melee_id
        if best_ranged_id:
            loadout["ranged_weapon"] = best_ranged_id
        weapon_id: str | None = None
        weapon: Mapping[str, Any] = {}
        if melee_candidates:
            _, weapon_id, weapon = melee_candidates[0]
        elif ranged_candidates:
            _, weapon_id, weapon = ranged_candidates[0]
        else:
            weapon = {"id": "unarmed", "family": "unarmed", "reach_m": 0.44, "minimum_range_m": 0.0, "handling": 1.0, "base_force_blunt": 0.35, "recovery_class": "quick"}

        family = str(weapon.get("family", weapon.get("combat_profile", ""))).lower()
        if weapon_id is None:
            skill_name = "Grappling" if _num(skills.get("Grappling")) >= _num(skills.get("Unarmed")) else "Unarmed"
        else:
            skill_name = self._PERSONAL_FAMILY_SKILL.get(family, "Unarmed")

        burden = self._combat_load_burden(loadout, attrs) if hasattr(self, "_combat_load_burden") else {
            "movement_factor": 1.0, "fatigue_multiplier": 1.0, "recovery_factor": 1.0,
            "articulation_factor": 1.0, "vision_factor": 1.0, "hearing_factor": 1.0,
            "total_load_kg": 0.0, "comfortable_load_kg": 1.0, "load_ratio": 0.0,
        }
        protection = self._combat_protection_index(loadout) if hasattr(self, "_combat_protection_index") else 0.0
        mount_record = self._combat_weapon(loadout.get("mount")) if hasattr(self, "_combat_weapon") else {}
        horse_armor_record = self._combat_weapon(loadout.get("horse_armor")) if hasattr(self, "_combat_weapon") else {}
        tack_record = self._combat_weapon(loadout.get("tack")) if hasattr(self, "_combat_weapon") else {}
        return {
            "best_weapon": weapon_id,
            "weapon": dict(weapon),
            "melee_weapon_id": best_melee_id,
            "melee_weapon": dict(best_melee_weapon) if isinstance(best_melee_weapon, Mapping) else {},
            "ranged_weapon_id": best_ranged_id,
            "ranged_weapon": dict(best_ranged_weapon) if isinstance(best_ranged_weapon, Mapping) else {},
            "ammunition_item_id": str(loadout.get("ammunition_item", "")),
            "ammunition_item": dict(self._combat_weapon(loadout.get("ammunition_item"))) if hasattr(self, "_combat_weapon") and loadout.get("ammunition_item") else {},
            "skill_name": skill_name,
            "equipped_item_ids": item_ids,
            "loadout": loadout,
            "burden": burden,
            "protection_index": protection,
            "condition_by_item": condition_by_item,
            "bodily_function": dict(body_function),
            "mount": dict(mount_record) if isinstance(mount_record, Mapping) else {},
            "horse_armor": dict(horse_armor_record) if isinstance(horse_armor_record, Mapping) else {},
            "tack": dict(tack_record) if isinstance(tack_record, Mapping) else {},
        }

    def _personal_controls(self, person: Mapping[str, Any], eq: Mapping[str, Any], environment_effects: Mapping[str, Any]) -> dict[str, float]:
        skills, attrs = _stats(person)
        burden = eq.get("burden", {}) if isinstance(eq.get("burden"), Mapping) else {}
        weapon = eq.get("weapon", {}) if isinstance(eq.get("weapon"), Mapping) else {}
        weapon_skill = _num(skills.get(str(eq.get("skill_name", "Unarmed"))))
        shield = _num(skills.get("Shield"))
        athletics = _num(skills.get("Athletics"))
        coord = _num(attrs.get("Coordination"))
        agility = _num(attrs.get("Agility")) * _num(burden.get("movement_factor"), 1.0)
        awareness = _num(attrs.get("Awareness")) * min(_num(burden.get("vision_factor"), 1.0), _num(burden.get("hearing_factor"), 1.0))
        composure = _num(attrs.get("Composure"))
        strength = _num(attrs.get("Strength"))
        fatigue = _fatigue(person)
        endurance = max(0.0, _num(attrs.get("Endurance")))
        fatigue_perf = person_fatigue_factors(fatigue=fatigue, endurance=endurance)
        handling = _num(weapon.get("handling"), 1.0)
        articulation = _num(burden.get("articulation_factor"), 1.0)
        recovery = _num(burden.get("recovery_factor"), 1.0)
        footing = max(0.45, int(environment_effects.get("formation_mobility_milli", 1000)) / 1000.0)
        anatomy = anatomy_function_factors(person)
        injury = self._personal_transient_injury_factors(person)
        awareness *= _num(anatomy.get("awareness_factor"), 1.0) * _num(injury.get("awareness_factor"), 1.0)
        handling_adj = (handling - 0.8) * 25.0
        attack = 0.45 * weapon_skill + 0.20 * coord + 0.15 * agility + 0.10 * awareness + 0.10 * composure + handling_adj
        parry = 0.48 * weapon_skill + 0.20 * coord + 0.14 * awareness + 0.10 * agility + 0.08 * composure + handling_adj
        dodge = 0.36 * agility + 0.22 * awareness + 0.18 * athletics + 0.14 * coord + 0.10 * composure
        block = 0.42 * shield + 0.18 * coord + 0.15 * strength + 0.15 * awareness + 0.10 * composure
        fatigue_control = _num(fatigue_perf.get("control_factor"), 1.0)
        fatigue_movement = _num(fatigue_perf.get("movement_factor"), 1.0)
        attack *= max(0.45, articulation * recovery) * _num(anatomy.get("attack_factor"), 1.0) * _num(injury.get("attack_factor"), 1.0) * fatigue_control
        parry *= max(0.45, articulation * recovery) * _num(anatomy.get("parry_factor"), 1.0) * _num(injury.get("parry_factor"), 1.0) * fatigue_control
        dodge *= max(0.35, footing * _num(burden.get("movement_factor"), 1.0)) * _num(anatomy.get("movement_factor"), 1.0) * _num(injury.get("movement_factor"), 1.0) * fatigue_control * fatigue_movement
        block *= max(0.45, articulation) * _num(anatomy.get("block_factor"), 1.0) * _num(injury.get("block_factor"), 1.0) * fatigue_control
        return {
            "attack": max(1.0, attack),
            "parry": max(1.0, parry),
            "dodge": max(1.0, dodge),
            "block": max(1.0, block),
            "weapon_skill": weapon_skill,
            "strength": strength,
            "agility": agility,
            "coordination": coord,
            "awareness": awareness,
            "composure": composure,
            "vision_factor": _num(anatomy.get("vision_factor"), 1.0),
            "visual_detection_factor": _num(anatomy.get("visual_detection_factor"), 1.0),
            "depth_perception_factor": _num(anatomy.get("depth_perception_factor"), 1.0),
            "peripheral_vision_factor": _num(anatomy.get("peripheral_vision_factor"), 1.0),
            "ranged_targeting_factor": _num(anatomy.get("ranged_targeting_factor"), 1.0),
        }

    @staticmethod
    def _personal_zone_covered(zone: str, armor: Mapping[str, Any], helmet: Mapping[str, Any], structure: str | None = None) -> tuple[bool, Mapping[str, Any]]:
        text = str(armor.get("coverage", "")).lower()
        htext = str(helmet.get("coverage", "")).lower()
        structure = str(structure or "").lower()
        if zone == "head" and structure == "eye":
            return (True, helmet) if htext and any(token in htext for token in ("face", "eye", "lens", "visor")) else (False, {})
        if zone == "head" and htext:
            return True, helmet
        if zone == "neck" and ("neck" in htext or "neck" in text or "throat" in htext):
            return True, helmet if ("neck" in htext or "throat" in htext) else armor
        needles = {
            "upper_torso": ("torso", "chest", "shoulders"),
            "lower_torso": ("torso", "hips", "groin"),
            "upper_arms": ("upper arms", "full arms", "arms"),
            "forearms_hands": ("forearms", "hands", "full arms", "arms"),
            "thighs": ("upper legs", "full legs", "legs", "thigh"),
            "lower_legs_feet": ("lower legs", "feet", "full legs", "legs"),
        }
        if any(n in text for n in needles.get(zone, ())):
            return True, armor
        return False, {}

    def _personal_aim_plan(
        self,
        intent: str | None,
        *,
        lethal_intent: bool,
        seed: int,
        sequence: int,
        actor: Mapping[str, Any] | None = None,
        target_person: Mapping[str, Any] | None = None,
        target_eq: Mapping[str, Any] | None = None,
        recent_actions: list[Mapping[str, Any]] | None = None,
        target_last_defense: str | None = None,
    ) -> dict[str, str]:
        text = str(intent or "").lower()
        explicit = True
        if any(token in text for token in ("horse", "mount")):
            zone = "mount"
            purpose = "disable_mount_or_break_mounted_mobility"
            if any(token in text for token in ("horse eye", "mount eye", "eye of the horse", "eye of the mount")):
                mount_structure = "eye"
            elif any(token in text for token in ("horse neck", "mount neck", "horse throat", "mount throat")):
                mount_structure = "neck"
            elif any(token in text for token in ("horse chest", "mount chest", "horse heart", "mount heart", "horse ribs", "mount ribs", "horse torso", "mount torso")):
                mount_structure = "chest"
            elif any(token in text for token in ("foreleg", "front leg", "front knee", "front fetlock")):
                mount_structure = "foreleg"
            elif any(token in text for token in ("hindleg", "hind leg", "rear leg", "back leg", "rear hock", "hind hock")):
                mount_structure = "hindleg"
            else:
                mount_structure = "mount"
        elif any(token in text for token in ("weapon arm", "weapon hand", "wrist", "forearm", "hand")):
            zone = "forearms_hands"
            purpose = "disable_weapon_control"
        elif any(token in text for token in ("elbow", "upper arm", "shoulder")):
            zone = "upper_arms"
            purpose = "disable_weapon_or_guarding_limb"
        elif any(token in text for token in ("knee", "thigh", "upper leg", "hip")):
            zone = "thighs"
            purpose = "degrade_mobility_and_base"
        elif any(token in text for token in ("shin", "lower leg", "ankle", "foot")):
            zone = "lower_legs_feet"
            purpose = "degrade_mobility_and_footing"
        elif any(token in text for token in ("armpit", "axilla", "underarm")):
            zone = "upper_torso"
            purpose = "attack_exposed_soft_tissue_and_arm_control"
        elif any(token in text for token in ("neck", "throat")):
            zone = "neck"
            purpose = "lethal_incapacitation" if lethal_intent else "threaten_vital_line"
        elif any(token in text for token in ("head", "face", "eye")):
            zone = "head"
            purpose = "lethal_incapacitation" if lethal_intent else "disrupt_vision_and_orientation"
        elif any(token in text for token in ("belly", "abdomen", "lower torso", "groin")):
            zone = "lower_torso"
            purpose = "disable_core_and_breathing"
        elif any(token in text for token in ("chest", "upper torso", "ribs", "heart")):
            zone = "upper_torso"
            purpose = "lethal_incapacitation" if lethal_intent else "disable_core_and_breathing"
        else:
            explicit = False
            zone = ""
            purpose = ""

        if explicit:
            target = anatomical_target(zone if zone != "mount" else "lower_torso", intent, seed + sequence * 13)
            return {
                "body_zone": zone,
                "side": target.get("side", "midline") if zone != "mount" else "mount",
                "structure": target.get("structure", zone) if zone != "mount" else mount_structure,
                "purpose": purpose,
                "selection_basis": "declared_intent",
            }

        combat_doctrine = load_personal_combat_doctrine(self.read, actor) if isinstance(actor, Mapping) else {}
        targeting = combat_doctrine.get("targeting", {}) if isinstance(combat_doctrine.get("targeting"), Mapping) else {}
        priorities = targeting.get("lethal_priority" if lethal_intent else "disable_priority", []) if targeting else []
        if isinstance(priorities, list) and priorities:
            loadout = target_eq.get("loadout", {}) if isinstance(target_eq, Mapping) and isinstance(target_eq.get("loadout"), Mapping) else {}
            armor = self._combat_weapon(loadout.get("body_armor")) if hasattr(self, "_combat_weapon") else {}
            helmet = self._combat_weapon(loadout.get("helmet")) if hasattr(self, "_combat_weapon") else {}
            anatomy = target_person.get("anatomy_state", {}) if isinstance(target_person, Mapping) and isinstance(target_person.get("anatomy_state"), Mapping) else {}
            structures = anatomy.get("structures", {}) if isinstance(anatomy.get("structures"), Mapping) else {}
            candidates: list[tuple[float, int, dict[str, str]]] = []
            recent = list(recent_actions or [])[-5:]
            for index, raw in enumerate(priorities):
                if not isinstance(raw, Mapping):
                    continue
                candidate_zone = str(raw.get("zone", "")).strip()
                candidate_structure = str(raw.get("structure", "")).strip()
                candidate_target = str(raw.get("target", candidate_structure or candidate_zone)).strip()
                candidate_purpose = str(raw.get("purpose", "efficient_function_denial")).strip()
                if not candidate_zone or not candidate_structure:
                    continue
                synthetic_intent = f"aim at {candidate_target}"
                exact = anatomical_target(candidate_zone, synthetic_intent, seed + sequence * 13 + index)
                side = str(exact.get("side", "midline"))
                structure = candidate_structure or str(exact.get("structure", candidate_zone))
                key = structure if side == "midline" else f"{side}_{structure}"
                state = structures.get(key, {}) if isinstance(structures.get(key), Mapping) else {}
                if str(state.get("status", "")).lower() in {"severed", "destroyed", "absent", "amputated"}:
                    continue
                covered, _cover = self._personal_zone_covered(candidate_zone, armor, helmet, structure)
                coverage_penalty = 0.0
                if covered:
                    # Axillae and other articulation gaps remain attractive even
                    # against torso armor, but a fully covered target is still
                    # less efficient than a genuinely exposed functional line.
                    coverage_penalty = 8.0 if structure == "axilla" else 18.0
                softspot_bonus = 5.0 if structure in {"wrist", "ankle", "knee", "eye", "axilla", "neck"} else 0.0
                score = 100.0 - index * 11.0 - coverage_penalty + softspot_bonus
                same_structure = sum(1 for row in recent[-3:] if str(row.get("aim_structure", "")) == structure)
                denied_same = sum(
                    1 for row in recent
                    if str(row.get("aim_structure", "")) == structure
                    and str(row.get("result", "")) in {"denied", "blocked", "parried", "dodged", "no_contact"}
                )
                score -= same_structure * 6.0 + denied_same * 7.0
                if target_last_defense == "block" and structure in {"wrist", "forearm", "hand", "ankle", "knee", "lower_leg"}:
                    score += 8.0
                elif target_last_defense == "parry" and structure in {"wrist", "forearm", "hand"}:
                    score += 9.0
                elif target_last_defense == "dodge" and structure in {"ankle", "knee", "lower_leg", "thigh"}:
                    score += 7.0
                candidates.append((score, -index, {
                    "body_zone": candidate_zone,
                    "side": side,
                    "structure": structure,
                    "purpose": candidate_purpose,
                    "selection_basis": "registered_combat_doctrine",
                }))
            if candidates:
                candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
                return candidates[0][2]

        pool = (
            (("neck", "lethal_incapacitation"), ("upper_torso", "lethal_incapacitation"), ("head", "lethal_incapacitation"), ("lower_torso", "disable_core_and_breathing"))
            if lethal_intent
            else (("forearms_hands", "disable_weapon_control"), ("thighs", "degrade_mobility_and_base"), ("upper_arms", "disable_weapon_or_guarding_limb"), ("lower_legs_feet", "degrade_mobility_and_footing"), ("upper_torso", "disable_core_and_breathing"))
        )
        recent = list(recent_actions or [])[-4:]
        ranked = []
        for index, (candidate_zone, candidate_purpose) in enumerate(pool):
            target = anatomical_target(candidate_zone, intent, seed + sequence * 13 + index)
            structure = str(target.get("structure", candidate_zone))
            score = 30.0 - index * 1.5
            score -= 5.0 * sum(1 for row in recent[-2:] if str(row.get("aim_structure", "")) == structure)
            score -= 6.0 * sum(1 for row in recent if str(row.get("aim_structure", "")) == structure and str(row.get("result", "")) in {"denied", "blocked", "parried", "dodged", "no_contact"})
            if target_last_defense == "block" and candidate_zone in {"forearms_hands", "lower_legs_feet", "thighs"}: score += 4.0
            if target_last_defense == "parry" and candidate_zone == "forearms_hands": score += 5.0
            if target_last_defense == "dodge" and candidate_zone in {"lower_legs_feet", "thighs"}: score += 4.0
            ranked.append((score, -index, candidate_zone, candidate_purpose, target))
        ranked.sort(reverse=True)
        _, _, zone, purpose, target = ranked[0]
        return {
            "body_zone": zone,
            "side": target.get("side", "midline"),
            "structure": target.get("structure", zone),
            "purpose": purpose,
            "selection_basis": "generic_combat_fallback",
        }

    @staticmethod
    def _personal_resistance(item: Mapping[str, Any], mode: str) -> float:
        keys = {
            "cut": ("cut_resistance", "primary_plate_cut_resistance", "shell_cut_resistance", "articulated_joint_cut_resistance"),
            "thrust": ("thrust_resistance", "primary_plate_thrust_resistance", "shell_thrust_resistance", "articulated_joint_thrust_resistance"),
            "blunt": ("blunt_resistance", "primary_plate_blunt_resistance", "shell_blunt_resistance", "articulated_joint_blunt_resistance"),
        }
        values = [_num(item.get(k)) for k in keys.get(mode, ()) if _num(item.get(k)) > 0]
        return max(values) if values else 0.0

    @staticmethod
    def _personal_attack_mode(weapon: Mapping[str, Any]) -> tuple[str, float]:
        choices = [
            ("cut", _num(weapon.get("base_force_cut"))),
            ("thrust", _num(weapon.get("base_force_thrust"))),
            ("blunt", _num(weapon.get("base_force_blunt"))),
        ]
        choices.sort(key=lambda x: x[1], reverse=True)
        return choices[0] if choices and choices[0][1] > 0 else ("blunt", 0.35)

    def _personal_attack_mode_plan(
        self,
        weapon: Mapping[str, Any],
        *,
        aim_zone: str,
        aim_structure: str,
        declared_intent: str | None,
        target_eq: Mapping[str, Any],
        recent_actions: list[Mapping[str, Any]],
        target_last_defense: str | None,
    ) -> dict[str, Any]:
        """Choose a physical attack method without static best-action spam.

        Explicit player wording always wins. Otherwise the decision scores every
        physically supported attack mode against the current target structure,
        actual covering armor, recent failed/repeated actions and the defender's
        last successful response. This is deterministic tactical adaptation, not
        random move rotation.
        """
        intent = str(declared_intent or "").lower()
        explicit_mode = None
        if any(token in intent for token in ("thrust", "stab", "pierce")):
            explicit_mode = "thrust"
        elif any(token in intent for token in ("cut", "slash", "slice", "chop")):
            explicit_mode = "cut"
        elif any(token in intent for token in ("smash", "bash", "blunt", "pommel")):
            explicit_mode = "blunt"

        choices = {
            "cut": _num(weapon.get("base_force_cut")),
            "thrust": _num(weapon.get("base_force_thrust")),
            "blunt": _num(weapon.get("base_force_blunt")),
        }
        choices = {mode: force for mode, force in choices.items() if force > 0.01}
        if not choices:
            choices = {"blunt": 0.35}
        if explicit_mode in choices:
            return {
                "mode": explicit_mode,
                "force": choices[explicit_mode],
                "selection_basis": "declared_intent",
                "decision_reason": f"explicit_{explicit_mode}_method",
            }

        d_loadout = target_eq.get("loadout", {}) if isinstance(target_eq.get("loadout"), Mapping) else {}
        armor = self._combat_weapon(d_loadout.get("body_armor")) if hasattr(self, "_combat_weapon") else {}
        helmet = self._combat_weapon(d_loadout.get("helmet")) if hasattr(self, "_combat_weapon") else {}
        covered, covering_item = self._personal_zone_covered(aim_zone, armor, helmet, aim_structure)

        recent = list(recent_actions[-5:])
        repeated_modes = [str(row.get("mode", "")) for row in recent[-3:]]
        repeated_structures = [str(row.get("aim_structure", "")) for row in recent[-3:]]
        failed_modes = [str(row.get("mode", "")) for row in recent if str(row.get("result")) in {"denied", "blocked", "parried", "dodged", "no_contact"}]

        structure = str(aim_structure or "")
        scores: list[tuple[float, str, float, list[str]]] = []
        for mode, force in choices.items():
            reasons: list[str] = []
            score = force * 42.0
            pen_factor = weapon_penetration_factor(weapon, mode)
            score += pen_factor * (18.0 if covered else 8.0)
            if covered:
                # Concentrated thrusts are usually preferable against armor gaps;
                # blunt attacks remain useful when penetration is unlikely.
                if mode == "thrust":
                    score += 8.0
                    reasons.append("armor_gap_penetration")
                elif mode == "blunt":
                    score += 5.0
                    reasons.append("transmitted_impact_through_armor")
            if structure in {"eye", "neck", "axilla"} and mode == "thrust":
                score += 12.0; reasons.append("soft_vital_line")
            if structure in {"wrist", "forearm", "hand", "ankle", "knee", "neck"} and mode == "cut":
                score += 10.0; reasons.append("functional_cut_line")
            if structure in {"head", "knee", "elbow", "shoulder", "hip"} and mode == "blunt":
                score += 7.0; reasons.append("joint_or_bone_impact")

            repeat_count = repeated_modes.count(mode)
            if repeat_count:
                score -= 8.0 * repeat_count
                reasons.append("repeat_penalty")
            if mode in failed_modes:
                score -= 7.0
                reasons.append("recent_failure_penalty")
            if repeated_structures.count(structure) >= 2:
                score -= 5.0
                reasons.append("target_line_adaptation")

            # Adapt to what the defender just demonstrated rather than blindly
            # reissuing the same high-score action.
            if target_last_defense == "block":
                if mode == "thrust": score += 5.0
                if structure in {"lower_leg", "ankle", "knee", "wrist", "forearm", "hand"}: score += 6.0
                reasons.append("adapt_to_shield_block")
            elif target_last_defense == "parry":
                if mode in {"cut", "blunt"}: score += 4.0
                if structure in {"wrist", "forearm", "hand"}: score += 7.0
                reasons.append("attack_weapon_control_after_parry")
            elif target_last_defense == "dodge":
                if mode == "cut": score += 5.0
                if structure in {"lower_leg", "ankle", "knee", "thigh"}: score += 5.0
                reasons.append("track_mobility_after_dodge")

            # Armor values are not used as a hidden pass/fail threshold here. They
            # only influence method selection; actual penetration remains resolved
            # later by the physical contact layer.
            if covered and isinstance(covering_item, Mapping):
                channel = self._personal_resistance(covering_item, mode)
                score += max(-8.0, min(8.0, (pen_factor * 70.0 - channel) / 12.0))
            scores.append((score, mode, force, reasons))

        scores.sort(key=lambda row: (row[0], row[1]), reverse=True)
        score, mode, force, reasons = scores[0]
        return {
            "mode": mode,
            "force": force,
            "selection_basis": "adaptive_physical_sequence",
            "decision_reason": "+".join(reasons) if reasons else "best_current_physical_line",
            "decision_score": round(score, 4),
        }

    @staticmethod
    def _personal_defense_method(eq: Mapping[str, Any], controls: Mapping[str, float], distance: float) -> tuple[str, float]:
        loadout = eq.get("loadout", {}) if isinstance(eq.get("loadout"), Mapping) else {}
        weapon = eq.get("weapon", {}) if isinstance(eq.get("weapon"), Mapping) else {}
        options: list[tuple[str, float]] = [("dodge", _num(controls.get("dodge")))]
        if loadout.get("shield"):
            options.append(("block", _num(controls.get("block"))))
        reach = _num(weapon.get("reach_m"), 0.44)
        minimum = _num(weapon.get("minimum_range_m"), 0.0)
        if minimum <= distance <= reach + 0.35:
            options.append(("parry", _num(controls.get("parry"))))
        return max(options, key=lambda row: row[1])

    @staticmethod
    def _personal_transient_injury_factors(person: Mapping[str, Any]) -> dict[str, float]:
        """Map saved active wounds to temporary combat-function penalties.

        Permanent anatomical loss is resolved separately by
        anatomy_function_factors(). This layer is intentionally location-aware:
        a damaged wrist degrades weapon handling while a damaged leg degrades
        movement, instead of treating every wound as the same generic HP loss.
        """
        rows = active_injury_rows(person)

        if not rows:
            return {
                "attack_factor": 1.0,
                "parry_factor": 1.0,
                "block_factor": 1.0,
                "movement_factor": 1.0,
                "awareness_factor": 1.0,
            }

        defaults = {"minor": 8.0, "moderate": 22.0, "serious": 45.0, "severe": 45.0, "critical": 70.0}
        upper = lower = head = torso = general = 0.0
        exact = {"attack_factor": 1.0, "parry_factor": 1.0, "block_factor": 1.0, "movement_factor": 1.0, "awareness_factor": 1.0}
        for row in rows:
            severity = str(row.get("severity", "moderate")).lower()
            impairment = max(0.0, min(100.0, _num(row.get("functional_impairment"), defaults.get(severity, 22.0))))
            saved_effects = row.get("functional_effects") if isinstance(row.get("functional_effects"), Mapping) else {}
            for key in exact:
                if key in saved_effects:
                    exact[key] = min(exact[key], _clamp(_num(saved_effects.get(key), 1.0), 0.02, 1.0))
            zone = str(row.get("body_zone", ""))
            general += impairment * 0.18
            if zone in {"forearms_hands", "upper_arms"}:
                upper += impairment
            elif zone in {"lower_legs_feet", "thighs"}:
                lower += impairment
            elif zone in {"head", "neck"}:
                head += impairment
            elif zone in {"upper_torso", "lower_torso"}:
                torso += impairment
            else:
                general += impairment * 0.35

        upper = min(92.0, upper + torso * 0.20)
        lower = min(94.0, lower + torso * 0.25)
        head = min(90.0, head + torso * 0.15)
        general = min(75.0, general + torso * 0.35)
        physiology = person.get("physiology_state") if isinstance(person.get("physiology_state"), Mapping) else {}
        shock_ratio = _clamp(_num(physiology.get("shock_ratio")), 0.0, 2.5)
        systemic_factor = max(0.18, 1.0 - max(0.0, shock_ratio - 0.55) * 0.50)
        respiratory = _clamp(_num(physiology.get("respiratory_compromise")), 0.0, 100.0)
        respiratory_factor = max(0.15, 1.0 - respiratory / 135.0)
        return {
            "attack_factor": max(0.04, exact["attack_factor"] * (1.0 - upper / 125.0) * (1.0 - general / 140.0) * systemic_factor),
            "parry_factor": max(0.03, exact["parry_factor"] * (1.0 - upper / 112.0) * (1.0 - general / 135.0) * systemic_factor),
            "block_factor": max(0.03, exact["block_factor"] * (1.0 - upper / 105.0) * (1.0 - general / 130.0) * systemic_factor),
            "movement_factor": max(0.03, exact["movement_factor"] * (1.0 - lower / 105.0) * (1.0 - general / 135.0) * systemic_factor * respiratory_factor),
            "awareness_factor": max(0.08, exact["awareness_factor"] * (1.0 - head / 120.0) * (1.0 - general / 160.0) * systemic_factor * max(0.35, respiratory_factor)),
        }

    def _personal_apply_wound(
        self,
        target: dict[str, Any],
        *,
        zone: str,
        severity: str,
        mode: str,
        source_weapon: str | None,
        at: str,
        side: str | None = None,
        structure: str | None = None,
        structural_resolution: Mapping[str, Any] | None = None,
        local_at_s: float | None = None,
    ) -> dict[str, Any]:
        recovery = {"minor": 8, "moderate": 24, "serious": 72, "critical": 168}.get(severity, 24)
        severity_index = {"none": 0, "minor": 1, "moderate": 2, "serious": 3, "severe": 3, "critical": 4}.get(str(severity).lower(), 2)
        mechanics = self.read("game/data/mechanics/injury.json") if hasattr(self, "read") else {}
        base_impairment = mechanics.get("base_impairment", {}) if isinstance(mechanics, Mapping) else {}
        impairment = _num(base_impairment.get(str(severity_index)), {1: 10, 2: 30, 3: 60, 4: 90}.get(severity_index, 30))
        bleed_table = mechanics.get("bleeding_units_per_minute", {}) if isinstance(mechanics, Mapping) else {}
        mode_bleeding = bleed_table.get(str(mode), []) if isinstance(bleed_table, Mapping) else []
        bleeding_rate = _num(mode_bleeding[severity_index] if isinstance(mode_bleeding, list) and len(mode_bleeding) > severity_index else 0.0)
        pain_table = mechanics.get("pain_by_severity", {}) if isinstance(mechanics, Mapping) else {}
        pain = _num(pain_table.get(str(severity_index)), {1: 12, 2: 30, 3: 55, 4: 80}.get(severity_index, 30))
        structural = dict(structural_resolution or {})
        damaged = structural.get("damaged_structures", []) if isinstance(structural.get("damaged_structures"), list) else []
        structural_bleeding = max(0.0, _num(structural.get("bleeding_units_per_minute")))
        internal_bleeding = max(0.0, _num(structural.get("internal_bleeding_units_per_minute")))
        # The base wound rate represents ordinary soft-tissue bleeding. Exact
        # vessel/organ/bone sources are additive, so a severed artery is not
        # flattened back into the same generic serious-cut rate as muscle injury.
        bleeding_rate = max(0.0, bleeding_rate) + structural_bleeding
        functional = structural.get("functional_effects", {}) if isinstance(structural.get("functional_effects"), Mapping) else {}
        respiratory = _clamp(_num(structural.get("respiratory_compromise")), 0.0, 100.0)
        neurological = _clamp(_num(structural.get("neurological_impairment")), 0.0, 100.0)
        existing = target.get("injuries")
        if not isinstance(existing, list):
            existing = []
            target["injuries"] = existing
        wound_sequence = len(existing) + 1
        local_stamp = "na" if local_at_s is None else str(int(round(float(local_at_s) * 1_000_000)))
        injury = {
            "injury_id": f"combat:{at}:{local_stamp}:{wound_sequence}",
            "label": f"{severity} {mode} wound to {zone.replace('_', ' ')}",
            "severity": severity,
            "severity_index": severity_index,
            "body_zone": zone,
            "side": side,
            "contact_structure": structure,
            "mechanism": mode,
            "source_weapon": source_weapon,
            "functional_impairment": round(impairment, 3),
            "functional_effects": {str(k): round(_num(v, 1.0), 5) for k, v in functional.items()},
            "damaged_structures": damaged,
            "bleeding_units_per_minute": round(max(0.0, bleeding_rate), 4),
            "internal_bleeding_units_per_minute": round(internal_bleeding, 4),
            "bleeding_sources": list(structural.get("bleeding_sources", [])) if isinstance(structural.get("bleeding_sources"), list) else [],
            "bleeding": {"rate_units_per_minute": round(max(0.0, bleeding_rate), 4), "internal_rate_units_per_minute": round(internal_bleeding, 4), "controlled": False},
            "pain": round(max(0.0, pain), 3),
            "structural_stability": round(max(0.0, 100.0 - impairment - 0.25 * neurological), 3),
            "respiratory_compromise": round(respiratory, 3),
            "neurological_impairment": round(neurological, 3),
            "contamination_pressure": 0.0,
            "systemic_stress": 0.0,
            "recovery_stage": "unstable" if severity_index >= 2 else "stabilized",
            "inflicted_at": at,
            "inflicted_at_offset_s": None if local_at_s is None else round(float(local_at_s), 6),
            "minimum_recovery_hours": recovery,
            "recovered_hours": 0,
            "active": True,
        }
        existing.append(injury)
        target["injury_state"] = injury
        if severity in {"moderate", "serious", "critical"}:
            self._set_person_health(target, "injured")
        physiology = target.setdefault("physiology_state", {})
        physiology.setdefault("blood_loss_units", 0.0)
        physiology.setdefault("respiratory_failure_equivalent_seconds", 0.0)
        physiology.setdefault("consciousness", "alert")
        physiology.setdefault("circulation_state", "stable")
        physiology.setdefault("last_combat_update_offset_s", 0.0)
        return injury

    def _personal_apply_mount_wound(
        self,
        target: dict[str, Any],
        *,
        severity: str,
        mode: str,
        source_weapon: str | None,
        at: str,
        seed: int = 0,
        structure: str | None = None,
    ) -> dict[str, Any]:
        """Apply a restrained but causal mount-anatomy result.

        Mounts do not receive a veterinary character sheet.  The combat state
        distinguishes only the structures that materially change mounted combat:
        fore/hind legs, chest, neck and eye.  Catastrophic leg/neck/chest damage
        can collapse the mount; an eye wound instead degrades control/awareness.
        """
        recovery = {"minor": 12, "moderate": 36, "serious": 96, "critical": 240}.get(severity, 36)
        state = target.setdefault("mount_combat_state", {})
        injuries = state.setdefault("injuries", [])
        severity_rank = {"minor": 1, "moderate": 2, "serious": 3, "critical": 4}.get(str(severity), 2)
        mount_structures = {"foreleg", "hindleg", "chest", "neck", "eye"}
        structures = ("foreleg", "hindleg", "chest", "neck", "eye")
        # Thrusts are more likely to find torso/neck; blunt collision favors legs.
        if str(mode) == "thrust":
            structures = ("chest", "neck", "foreleg", "hindleg", "eye")
        elif str(mode) == "blunt":
            structures = ("foreleg", "hindleg", "chest", "neck", "eye")
        requested_structure = str(structure or "").lower()
        structure = requested_structure if requested_structure in mount_structures else structures[abs(int(seed)) % len(structures)]
        mobility_table = {
            "foreleg": {1: .90, 2: .58, 3: .16, 4: 0.0},
            "hindleg": {1: .92, 2: .62, 3: .20, 4: 0.0},
            "chest": {1: .94, 2: .76, 3: .42, 4: 0.0},
            "neck": {1: .92, 2: .70, 3: .28, 4: 0.0},
            "eye": {1: .96, 2: .90, 3: .82, 4: .72},
        }
        mobility = mobility_table[structure][severity_rank]
        collapse = bool(
            (structure in {"foreleg", "hindleg"} and severity_rank >= 3)
            or (structure in {"chest", "neck"} and severity_rank >= 4)
        )
        # Keep a compact deterministic local condition ledger so repeated exact
        # contacts can kill a horse rather than producing an endless series of
        # independent wounds.  Critical chest/neck trauma is immediately fatal;
        # catastrophic leg trauma disables the mount without pretending that a
        # broken leg itself equals instant death.
        condition_before = max(0, min(1000, int(state.get("condition_milli", 1000))))
        severity_damage = {1: 90, 2: 230, 3: 430, 4: 680}[severity_rank]
        structure_multiplier = {"foreleg": 1.0, "hindleg": 1.0, "chest": 1.18, "neck": 1.22, "eye": 0.62}[structure]
        condition_damage = max(1, int(round(severity_damage * structure_multiplier)))
        condition_after = max(0, condition_before - condition_damage)
        fatal = bool(
            (structure in {"chest", "neck"} and severity_rank >= 4)
            or condition_after <= 0
        )
        disabled = bool(not fatal and (collapse or condition_after < 260))
        status = "dead" if fatal else ("disabled" if disabled else ("injured" if severity_rank >= 2 else "active"))
        injury = {
            "label": f"{severity} {mode} injury to mount {structure}",
            "severity": severity,
            "mechanism": mode,
            "structure": structure,
            "source_weapon": source_weapon,
            "inflicted_at": at,
            "minimum_recovery_hours": recovery,
            "recovered_hours": 0,
            "active": True,
            "mobility_factor": mobility,
            "collapse": collapse,
            "condition_before_milli": condition_before,
            "condition_after_milli": condition_after,
            "condition_damage_milli": condition_damage,
            "mount_status_after": status,
        }
        injuries.append(injury)
        state["health"] = "dead" if fatal else ("critical" if severity == "critical" else ("injured" if severity in {"moderate", "serious"} else state.get("health", "healthy")))
        state["mobility_factor"] = min(float(state.get("mobility_factor", 1.0)), mobility)
        state["condition_milli"] = condition_after
        previous_status = str(state.get("status", "active")).lower()
        # Never downgrade a previously terminal mount state if a near-simultaneous
        # projectile/contact is processed later on the same shared clock.
        if previous_status == "dead":
            status = "dead"
        elif previous_status == "disabled" and status not in {"dead"}:
            status = "disabled"
        state["status"] = status
        state["serviceable"] = status not in {"dead", "disabled"}
        if structure == "eye":
            state["awareness_factor"] = min(float(state.get("awareness_factor", 1.0)), {1: .94, 2: .82, 3: .66, 4: .50}[severity_rank])
        if collapse or status in {"dead", "disabled"}:
            state["collapsed"] = True
            state["collapsed_at"] = at
        if status == "dead":
            state.setdefault("died_at", at)
        elif status == "disabled":
            state.setdefault("disabled_at", at)
        if status in {"dead", "disabled"} and not bool(state.get("service_loss_recorded", False)):
            state["service_loss_pending"] = True
        return injury

    def _personal_tempo(self, person: Mapping[str, Any], eq: Mapping[str, Any]) -> float:
        """Uncapped local action tempo from the combat authority formula.

        Permanent stats may exceed 200. Tempo therefore has a physical lower
        bound on action interval, but never an upper-stat clamp or a turn quota.
        """
        skills, attrs = _stats(person)
        relevant = _num(skills.get(str(eq.get("skill_name", "Unarmed"))))
        mass_combat = _num(skills.get("Formation Fighting", 0))
        return max(
            0.0,
            0.25 * _num(attrs.get("Agility"))
            + 0.20 * _num(attrs.get("Coordination"))
            + 0.20 * relevant
            + 0.15 * _num(attrs.get("Awareness"))
            + 0.10 * mass_combat
            + 0.10 * _num(attrs.get("Endurance")),
        )

    def _personal_timing_profile(
        self,
        person: Mapping[str, Any],
        eq: Mapping[str, Any],
        controls: Mapping[str, float],
        environment_effects: Mapping[str, Any],
    ) -> dict[str, float]:
        """Derive continuous-time startup, reaction, movement and recovery.

        `minimum_action_interval_seconds` is a start-to-next-start floor, not a
        turn duration. Movement/contact can complete sooner; recovery determines
        when that actor can initiate another action. Nothing here clamps a stat
        to 200.
        """
        skills, attrs = _stats(person)
        burden = eq.get("burden", {}) if isinstance(eq.get("burden"), Mapping) else {}
        weapon = eq.get("weapon", {}) if isinstance(eq.get("weapon"), Mapping) else {}
        tempo = self._personal_tempo(person, eq)
        minimum_interval = max(0.40, 360.0 / (tempo + 60.0))
        recovery_class = str(weapon.get("recovery_class", "standard")).lower()
        recovery_class_factor = {
            "quick": 0.78,
            "standard": 1.0,
            "slow": 1.25,
            "very_slow": 1.55,
        }.get(recovery_class, 1.0)
        handling = max(0.35, _num(weapon.get("handling"), 1.0))
        load_recovery = max(0.35, _num(burden.get("recovery_factor"), 1.0))
        movement_factor = max(0.25, _num(burden.get("movement_factor"), 1.0))
        body_function = eq.get("bodily_function", {}) if isinstance(eq.get("bodily_function"), Mapping) else anatomy_function_profile(person)
        anatomy_locomotion = _clamp(_num(body_function.get("locomotion_factor"), 1.0), 0.0, 1.0)
        anatomy_riding = _clamp(_num(body_function.get("riding_factor"), 1.0), 0.0, 1.0)
        anatomy_manual = _clamp(_num(body_function.get("manual_factor"), 1.0), 0.0, 1.0)
        anatomy_awareness = _clamp(_num(body_function.get("awareness_factor"), 1.0), 0.0, 1.0)
        footing = max(0.35, int(environment_effects.get("formation_mobility_milli", 1000)) / 1000.0)
        agility = max(0.0, _num(attrs.get("Agility")))
        athletics = max(0.0, _num(skills.get("Athletics")))
        awareness = max(0.0, _num(attrs.get("Awareness"))) * anatomy_awareness

        # Root growth prevents absurd linear sprint speed while still allowing
        # exceptional >200 stats to keep producing a real advantage. Permanent
        # lower-body loss scales the physical translation speed itself, not just
        # dodge quality; otherwise an amputee could still sprint at the old floor.
        foot_movement_speed = max(
            0.12,
            (1.15 + math.sqrt(agility) * 0.18 + math.sqrt(athletics) * 0.05)
            * movement_factor
            * footing
            * max(0.02, anatomy_locomotion),
        )
        body = person.get("body", {}) if isinstance(person.get("body"), Mapping) else {}
        rider_mass = max(35.0, _num(body.get("current_weight_kg"), 75.0))
        tack = eq.get("tack", {}) if isinstance(eq.get("tack"), Mapping) else {}
        mount_profile = mount_effective_speed_mps(
            eq.get("mount") if isinstance(eq.get("mount"), Mapping) else {},
            barding=eq.get("horse_armor") if isinstance(eq.get("horse_armor"), Mapping) else {},
            rider_mass_kg=rider_mass,
            rider_equipment_kg=max(0.0, _num(burden.get("total_load_kg"), 0.0)),
            tack_mass_kg=max(0.0, _num(tack.get("mass_kg"), 0.0)),
            terrain_factor=footing,
            horse_fatigue=_num((person.get("mount_combat_state") or {}).get("fatigue", 0)) if isinstance(person.get("mount_combat_state"), Mapping) else 0.0,
        )
        mount_state = person.get("mount_combat_state") if isinstance(person.get("mount_combat_state"), Mapping) else {}
        mount_mobility = _clamp(_num(mount_state.get("mobility_factor"), 1.0), 0.0, 1.0) if isinstance(mount_state, Mapping) else 1.0
        mount_awareness = _clamp(_num(mount_state.get("awareness_factor"), 1.0), 0.0, 1.0) if isinstance(mount_state, Mapping) else 1.0
        mounted_speed = _num(mount_profile.get("effective_speed_mps"), 0.0) * 0.55 * max(0.08, anatomy_riding) * mount_mobility
        movement_speed = max(foot_movement_speed, mounted_speed) if mount_profile.get("mounted") else foot_movement_speed
        handling_factor = max(0.22, math.sqrt(handling) * max(0.20, 0.55 + 0.45 * anatomy_manual))
        attack_startup = max(0.12, minimum_interval * 0.38 * recovery_class_factor / handling_factor)
        attack_recovery = max(0.16, minimum_interval * 0.62 * recovery_class_factor / (load_recovery * max(0.25, .55 + .45 * anatomy_manual)))
        defense_recovery = max(0.12, minimum_interval * 0.38 * recovery_class_factor / load_recovery)
        reaction = max(
            0.08,
            minimum_interval * 0.34 * (120.0 / (120.0 + awareness * (mount_awareness if mount_profile.get("mounted") else 1.0))),
        )
        movement_recovery = max(0.06, minimum_interval * 0.12 / load_recovery)
        initiative = (
            0.35 * _num(controls.get("awareness"))
            + 0.25 * _num(controls.get("agility"))
            + 0.20 * _num(controls.get("coordination"))
            + 0.10 * _num(controls.get("composure"))
            + 0.10 * _num(controls.get("weapon_skill"))
        )
        return {
            "tempo": tempo,
            "minimum_action_interval_seconds": minimum_interval,
            "movement_speed_mps": movement_speed,
            "attack_startup_seconds": attack_startup,
            "attack_recovery_seconds": attack_recovery,
            "defense_recovery_seconds": defense_recovery,
            "reaction_seconds": reaction,
            "movement_recovery_seconds": movement_recovery,
            "initiative": initiative,
            "mounted": bool(mount_profile.get("mounted")),
            "mount_effective_speed_mps": _num(mount_profile.get("effective_speed_mps"), 0.0),
            "mount_profile": dict(mount_profile),
        }

    def _personal_combat_slice(
        self,
        command: Any,
        payload: Mapping[str, Any],
        player: dict[str, Any],
        opponent_ref: str,
        opponent: dict[str, Any],
        environment: Mapping[str, Any] | None,
        *,
        opponent_people: Mapping[str, dict[str, Any]] | None = None,
        ally_people: Mapping[str, dict[str, Any]] | None = None,
        player_improvised_prop: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        objective = str(payload.get("objective", "combat"))
        spar = "spar" in objective.lower() or "controlled" in objective.lower()
        lethal_intent = any(token in objective.lower() for token in ("kill", "lethal", "execute"))
        requested_minutes = int(payload.get("duration_minutes", 60))
        requested_seconds = float(requested_minutes * 60)
        planned_intents = [str(step).strip() for step in payload.get("intent_sequence", []) if str(step).strip()]
        stop_on_decision = bool(payload.get("stop_on_decision", True))
        combo_links = [
            {"index": i, "intent": text, "status": "pending", "cause_event_id": None}
            for i, text in enumerate(planned_intents)
        ]
        combo_cursor = 0
        effects = environment.get("mechanical_effects", {}) if isinstance(environment, Mapping) and isinstance(environment.get("mechanical_effects"), Mapping) else {}
        opponents: dict[str, dict[str, Any]] = {
            str(ref): person for ref, person in (opponent_people or {opponent_ref: opponent}).items()
        }
        if opponent_ref not in opponents:
            opponents[opponent_ref] = opponent
        allies: dict[str, dict[str, Any]] = {
            str(ref): person for ref, person in (ally_people or {}).items()
        }
        player_side = {self.PLAYER_ACTOR, *allies.keys()}
        hostile_side = set(opponents.keys())
        actors = tuple([self.PLAYER_ACTOR] + sorted(allies) + sorted(opponents))
        people: dict[str, dict[str, Any]] = {self.PLAYER_ACTOR: player, **allies, **opponents}
        # Snapshot presentation-relevant starting condition before any combat
        # mutation.  The GM-private director packet may use this exact before/after
        # state to stage causality, but it never becomes player knowledge merely
        # because the director can see it.
        initial_participant_health = {ref: self._person_health(people[ref]) for ref in actors}
        initial_participant_fatigue = {ref: _fatigue(people[ref]) for ref in actors}
        objective_spec = objective_model(
            objective,
            sorted(hostile_side),
            sorted(player_side) if any(token in objective.lower() for token in ("protect", "guard", "escort", "defend")) else (),
            actor_refs=sorted(player_side),
            objective_position=(payload.get("objective_position") if isinstance(payload.get("objective_position"), Mapping) else None),
            objective_radius_m=max(0.25, _num(payload.get("objective_radius_m"), 1.5)),
            escape_distance_m=max(0.5, _num(payload.get("escape_distance_m"), 8.0)),
            hold_seconds=max(0.0, _num(payload.get("objective_hold_seconds"), 10.0)),
        )
        encounter_id = objective_spec["objective_id"] + "__" + "__".join(sorted(actors))
        equipment = {ref: self._personal_equipment_profile(ref, people[ref]) for ref in actors}
        transient_player_prop_state = copy.deepcopy(dict(player_improvised_prop)) if isinstance(player_improvised_prop, Mapping) else None

        def apply_transient_player_prop(ref: str) -> None:
            if ref != self.PLAYER_ACTOR or not isinstance(transient_player_prop_state, Mapping):
                return
            if str(transient_player_prop_state.get("status", "held")) != "held" or _num(transient_player_prop_state.get("condition_pct"), 100.0) <= 0.0:
                return
            transient_weapon = transient_player_prop_state.get("weapon") if isinstance(transient_player_prop_state.get("weapon"), Mapping) else None
            if not isinstance(transient_weapon, Mapping):
                raise ValueError("improvised personal-combat prop profile is invalid")
            player_eq = equipment[self.PLAYER_ACTOR]
            fact_ref = str(transient_player_prop_state.get("fact_ref") or "")
            if not fact_ref:
                raise ValueError("improvised personal-combat prop profile lacks fact_ref")
            player_eq["best_weapon"] = fact_ref
            player_eq["weapon"] = dict(transient_weapon)
            player_eq["melee_weapon_id"] = fact_ref
            player_eq["melee_weapon"] = dict(transient_weapon)
            player_eq["ranged_weapon_id"] = None
            player_eq["ranged_weapon"] = {}
            player_eq["ammunition_item_id"] = ""
            player_eq["ammunition_item"] = {}
            player_eq["skill_name"] = str(transient_player_prop_state.get("skill_name") or "Unarmed")
            player_eq.setdefault("condition_by_item", {})[fact_ref] = _clamp(_num(transient_player_prop_state.get("condition_pct"), 100.0), 0.0, 100.0)
            player_eq["transient_improvised_prop"] = transient_player_prop_state

        apply_transient_player_prop(self.PLAYER_ACTOR)
        controls = {ref: self._personal_controls(people[ref], equipment[ref], effects) for ref in actors}
        timing = {ref: self._personal_timing_profile(people[ref], equipment[ref], controls[ref], effects) for ref in actors}
        doctrines: dict[str, dict[str, Any]] = {}
        for ref in actors:
            try:
                doctrines[ref] = load_personal_combat_doctrine(self.read, people[ref])
            except (ValueError, KeyError, TypeError):
                # Missing/invalid optional doctrine cannot fabricate a fallback
                # policy. The actor simply uses capability/geometry defaults.
                doctrines[ref] = {}
        p_eq = equipment[self.PLAYER_ACTOR]
        o_eq = equipment[opponent_ref]
        p_ctrl = controls[self.PLAYER_ACTOR]
        o_ctrl = controls[opponent_ref]
        p_timing = timing[self.PLAYER_ACTOR]
        o_timing = timing[opponent_ref]

        p_weapon = p_eq.get("weapon", {}) if isinstance(p_eq.get("weapon"), Mapping) else {}
        o_weapon = o_eq.get("weapon", {}) if isinstance(o_eq.get("weapon"), Mapping) else {}
        p_reach = max(0.20, _num(p_weapon.get("reach_m"), 0.44))
        o_reach = max(0.20, _num(o_weapon.get("reach_m"), 0.44))
        start_distance = _clamp(_num(payload.get("distance_m"), max(p_reach, o_reach) * 0.90), 0.35, 400.0)
        seed = int(self._causal_seed(command, payload, "personal_combat_slice"))
        trace: list[dict[str, Any]] = []
        must_render: list[str] = []
        may_compress: list[str] = []
        team_plan_history: list[dict[str, Any]] = []
        last_team_plan_id_by_side: dict[str, str] = {}
        boundary: dict[str, Any] | None = None
        pending_boundary: dict[str, Any] | None = None
        outcome = "engaged"
        wound: dict[str, Any] | None = None
        winner_ref: str | None = None
        disarmed_ref: str | None = None
        ready_at = {ref: 0.0 for ref in actors}
        pending: dict[str, dict[str, Any]] = {}
        active_guard: dict[str, str] = {}
        action_serial = 0
        resolved_time = 0.0
        equipment_condition_changes: dict[str, dict[str, dict[str, Any]]] = {ref: {} for ref in actors}
        mount_wounds: list[dict[str, Any]] = []
        action_memory: dict[str, list[dict[str, Any]]] = {ref: [] for ref in actors}
        last_defense_method: dict[str, str | None] = {ref: None for ref in actors}
        defense_ready_at: dict[str, float] = {ref: 0.0 for ref in actors}
        weapon_guard_ready_at: dict[str, float] = {ref: 0.0 for ref in actors}
        shield_guard_ready_at: dict[str, float] = {ref: 0.0 for ref in actors}
        defense_serial: dict[str, int] = {ref: 0 for ref in actors}
        action_exertion: dict[str, float] = {ref: 0.0 for ref in actors}
        projectile_ammunition: dict[str, dict[str, int]] = {}
        fired_projectiles: list[dict[str, Any]] = []
        injury_mechanics = self.read("game/data/mechanics/injury.json")
        combat_mechanics = self.read("game/data/mechanics/combat.json")
        posture_timing = combat_mechanics.get("posture_timing", {}) if isinstance(combat_mechanics.get("posture_timing"), Mapping) else {}
        grapple_model = combat_mechanics.get("grapple_model", {}) if isinstance(combat_mechanics.get("grapple_model"), Mapping) else {}
        local_obstacle_model = combat_mechanics.get("local_obstacle_model", {}) if isinstance(combat_mechanics.get("local_obstacle_model"), Mapping) else {}
        embedded_weapon_model = combat_mechanics.get("embedded_weapon_model", {}) if isinstance(combat_mechanics.get("embedded_weapon_model"), Mapping) else {}
        active_defense_model = combat_mechanics.get("active_defense_saturation", {}) if isinstance(combat_mechanics.get("active_defense_saturation"), Mapping) else {}
        local_obstacles: list[dict[str, Any]] = []
        for index, row in enumerate(payload.get("local_obstacles", []) if isinstance(payload.get("local_obstacles"), list) else []):
            if not isinstance(row, Mapping):
                continue
            kind = str(row.get("kind", ""))
            normalized = {"kind": kind, "label": str(row.get("label", f"obstacle_{index+1}"))}
            if kind == "circle":
                normalized.update({"x_m": _num(row.get("x_m")), "y_m": _num(row.get("y_m")), "radius_m": max(0.01, _num(row.get("radius_m"), 0.1))})
            elif kind == "segment":
                normalized.update({
                    "x1_m": _num(row.get("x1_m")), "y1_m": _num(row.get("y1_m")),
                    "x2_m": _num(row.get("x2_m")), "y2_m": _num(row.get("y2_m")),
                    "clearance_m": max(0.0, _num(row.get("clearance_m"), 0.0)),
                })
            if "base_elevation_m" in row or "height_m" in row:
                normalized["base_elevation_m"] = _num(row.get("base_elevation_m"), 0.0)
                normalized["height_m"] = max(0.01, _num(row.get("height_m"), 0.01))
                if "vertical_clearance_m" in row:
                    normalized["vertical_clearance_m"] = max(0.0, _num(row.get("vertical_clearance_m"), 0.0))
            # Obstacles without explicit vertical data remain valid 2D blockers.
            # Height/elevation only refines whether a trajectory can clear them.
            local_obstacles.append(normalized)

        # Exact multi-person combat uses a small local 2D plane.  This is not a
        # world map; it exists only for the materialized scene and makes attack
        # angle, retreat lanes, shield arcs and shared body commitment causal.
        supplied_positions = payload.get("participant_positions", {}) if isinstance(payload.get("participant_positions"), Mapping) else {}
        positions: dict[str, dict[str, float]] = {}
        restored_local_state: dict[str, Mapping[str, Any]] = {}
        for ref in actors:
            cstate = people[ref].get("combat_state", {}) if isinstance(people[ref].get("combat_state"), Mapping) else {}
            saved_local = cstate.get("local_combat_state") if isinstance(cstate.get("local_combat_state"), Mapping) else None
            if isinstance(saved_local, Mapping) and str(saved_local.get("encounter_id")) == encounter_id:
                restored_local_state[ref] = saved_local
            row = supplied_positions.get(ref) if isinstance(supplied_positions, Mapping) else None
            if not isinstance(row, Mapping) and isinstance(saved_local, Mapping) and str(saved_local.get("encounter_id")) == encounter_id:
                row = saved_local.get("position") if isinstance(saved_local.get("position"), Mapping) else None
            if isinstance(row, Mapping):
                default_radius = 0.75 if bool(timing.get(ref, {}).get("mounted")) else 0.28
                positions[ref] = normalize_position(row, radius_m=default_radius)
        positions.setdefault(self.PLAYER_ACTOR, normalize_position({"x_m": 0.0, "y_m": 0.0, "elevation_m": 0.0, "facing_deg": 0.0}, radius_m=0.28))
        hostile_order = sorted(hostile_side)
        for index, ref in enumerate(hostile_order):
            if ref in positions:
                continue
            if len(hostile_order) == 1:
                angle = 0.0
            else:
                angle = (360.0 * index / len(hostile_order)) % 360.0
            radius = start_distance + 0.10 * (index % 2)
            rad = math.radians(angle)
            positions[ref] = {
                "x_m": round(math.cos(rad) * radius, 6),
                "y_m": round(math.sin(rad) * radius, 6),
                "elevation_m": 0.0,
                "facing_deg": (angle + 180.0) % 360.0,
                "radius_m": 0.75 if bool(timing.get(ref, {}).get("mounted")) else 0.28,
            }
        for index, ref in enumerate(sorted(allies)):
            if ref in positions:
                continue
            angle = 180.0 + (index - max(0, len(allies) - 1) / 2.0) * 35.0
            rad = math.radians(angle)
            positions[ref] = {
                "x_m": round(math.cos(rad) * 0.85, 6),
                "y_m": round(math.sin(rad) * 0.85, 6),
                "elevation_m": 0.0,
                "facing_deg": 0.0,
                "radius_m": 0.75 if bool(timing.get(ref, {}).get("mounted")) else 0.28,
            }
        body_state: dict[str, dict[str, Any]] = {
            ref: {
                "facing_deg": float(positions[ref]["facing_deg"]),
                "guard_center_deg": float(positions[ref]["facing_deg"]),
                "weapon_center_deg": float(positions[ref]["facing_deg"]),
                "shield_center_deg": float(positions[ref]["facing_deg"]),
                "balance": 1.0,
                "foot_commit_until_s": 0.0,
                "last_defense_at_s": -999.0,
                "last_defense_angle_deg": None,
                "last_defense_method": None,
                "active_defense_load": 0.0,
                "active_defense_last_update_s": 0.0,
                "active_defense_recent_sources": {},
                "last_dodge_vector": (0.0, 0.0),
                "movement_velocity_xy_mps": (0.0, 0.0),
                "movement_velocity_until_s": 0.0,
                "posture": str(people[ref].get("combat_state", {}).get("posture", "standing")) if isinstance(people[ref].get("combat_state"), Mapping) else "standing",
                "grappled_with": (str(people[ref].get("combat_state", {}).get("grappled_with")) if isinstance(people[ref].get("combat_state"), Mapping) and people[ref].get("combat_state", {}).get("grappled_with") else None),
                "grapple_role": (str(people[ref].get("combat_state", {}).get("grapple_role")) if isinstance(people[ref].get("combat_state"), Mapping) and people[ref].get("combat_state", {}).get("grapple_role") else None),
            }
            for ref in actors
        }
        for ref in actors:
            partner = body_state[ref].get("grappled_with")
            if partner and partner not in actors:
                body_state[ref]["grappled_with"] = None; body_state[ref]["grapple_role"] = None
                people[ref].setdefault("combat_state", {}).pop("grappled_with", None); people[ref].setdefault("combat_state", {}).pop("grapple_role", None)
            saved = restored_local_state.get(ref)
            if isinstance(saved, Mapping):
                ready_at[ref] = max(0.0, _num(saved.get("action_recovery_remaining_s"), 0.0))
                defense_ready_at[ref] = max(0.0, _num(saved.get("defense_recovery_remaining_s"), 0.0))
                weapon_guard_ready_at[ref] = max(0.0, _num(saved.get("weapon_recovery_remaining_s"), 0.0))
                shield_guard_ready_at[ref] = max(0.0, _num(saved.get("shield_recovery_remaining_s"), 0.0))
                body_state[ref]["active_defense_load"] = _clamp(_num(saved.get("active_defense_load"), 0.0), 0.0, 1.0)
                body_state[ref]["active_defense_last_update_s"] = 0.0
                body_state[ref]["guard_center_deg"] = _num(saved.get("guard_center_deg"), body_state[ref]["guard_center_deg"]) % 360.0
                body_state[ref]["weapon_center_deg"] = _num(saved.get("weapon_center_deg"), body_state[ref]["weapon_center_deg"]) % 360.0
                body_state[ref]["shield_center_deg"] = _num(saved.get("shield_center_deg"), body_state[ref]["shield_center_deg"]) % 360.0
                body_state[ref]["balance"] = _clamp(_num(saved.get("balance"), body_state[ref]["balance"]), 0.0, 1.0)
                body_state[ref]["last_defense_angle_deg"] = saved.get("last_defense_angle_deg")
                body_state[ref]["last_defense_method"] = saved.get("last_defense_method")
                body_state[ref]["last_dodge_vector"] = tuple(saved.get("last_dodge_vector", body_state[ref]["last_dodge_vector"]))
                body_state[ref]["movement_velocity_xy_mps"] = tuple(saved.get("movement_velocity_xy_mps", body_state[ref]["movement_velocity_xy_mps"]))
                body_state[ref]["movement_velocity_until_s"] = max(0.0, _num(saved.get("movement_velocity_remaining_s"), 0.0))
                body_state[ref]["active_defense_recent_sources"] = dict(saved.get("active_defense_recent_sources", {})) if isinstance(saved.get("active_defense_recent_sources"), Mapping) else {}

        start_positions = {
            ref: {
                "x_m": round(float(row["x_m"]), 6),
                "y_m": round(float(row["y_m"]), 6),
                "elevation_m": round(float(row.get("elevation_m", 0.0)), 6),
                "facing_deg": round(float(row["facing_deg"]), 6),
                "radius_m": round(float(row.get("radius_m", 0.28)), 6),
            }
            for ref, row in positions.items()
        }
        for ref in actors:
            person_state = people[ref].setdefault("combat_state", {})
            saved_ammo = person_state.setdefault("projectile_ammunition", {})
            eq = equipment[ref]
            ammo_id = str(eq.get("ammunition_item_id", ""))
            if ammo_id:
                loadout = eq.get("loadout", {}) if isinstance(eq.get("loadout"), Mapping) else {}
                initial = max(0, int(loadout.get("carried_ammunition", 0) or 0))
                if ammo_id not in saved_ammo:
                    saved_ammo[ammo_id] = initial
                projectile_ammunition[ref] = {ammo_id: max(0, int(saved_ammo.get(ammo_id, 0) or 0))}
            else:
                projectile_ammunition[ref] = {}

        physiology_last_at: dict[str, float] = {ref: 0.0 for ref in actors}

        def physiology_snapshot(ref: str) -> dict[str, float]:
            return injury_physiology_snapshot(people[ref])

        def advance_physiology(at_s: float, *, force_event: bool = False) -> None:
            for ref in actors:
                dt = max(0.0, float(at_s) - float(physiology_last_at.get(ref, 0.0)))
                phys = people[ref].setdefault("physiology_state", {})
                prior_consciousness = str(phys.get("consciousness", "alert"))
                prior_circulation = str(phys.get("circulation_state", "stable"))
                prior_life = str(people[ref].get("life_status", people[ref].get("status", "active"))).lower()
                after = advance_injury_physiology(people[ref], injury_mechanics, elapsed_seconds=dt)
                physiology_last_at[ref] = float(at_s)
                blood = after["blood"]
                shock = after["shock"]
                reserve = after["reserve"]
                if after["state"] == "dead":
                    people[ref]["life_status"] = "dead"
                    self._set_person_health(people[ref], "dead")
                    cstate = people[ref].setdefault("combat_state", {})
                    cstate["incapacitated"] = True
                    cstate["incapacitated_reason"] = "physiological_collapse"
                    cstate["incapacitated_at_s"] = round(float(at_s), 6)
                elif after["state"] == "incapacitated":
                    cstate = people[ref].setdefault("combat_state", {})
                    if not bool(cstate.get("incapacitated")):
                        cstate["incapacitated"] = True
                        cstate["incapacitated_reason"] = "shock_or_physiological_failure"
                        cstate["incapacitated_at_s"] = round(float(at_s), 6)
                elif after["state"] == "degraded":
                    ready_at[ref] = max(float(ready_at[ref]), float(at_s) + timing[ref]["defense_recovery_seconds"])
                    body_state[ref]["balance"] = min(_num(body_state[ref].get("balance"), 1.0), 0.72)
                changed = (
                    prior_consciousness != str(phys.get("consciousness"))
                    or prior_circulation != str(phys.get("circulation_state"))
                    or (prior_life not in {"dead", "deceased"} and str(people[ref].get("life_status", "")).lower() in {"dead", "deceased"})
                )
                if changed or force_event:
                    event = {
                        "id": f"physiology_{ref}_{int(round(float(at_s)*1000)):08d}", "kind": "physiology_state", "actor_ref": ref,
                        "blood_loss_units": round(blood, 4), "bleeding_units_per_minute": round(after["bleeding"], 4),
                        "shock_index": round(shock, 4), "control_reserve": round(reserve, 4),
                        "respiratory_compromise": round(after["respiratory"], 4), "consciousness": phys.get("consciousness"),
                        "circulation_state": phys.get("circulation_state"), "at_s": round(float(at_s), 3),
                    }
                    trace.append(event)
                    (must_render if changed else may_compress).append(event["id"])

        def current_condition(ref: str, item_id: str | None) -> float:
            if not item_id:
                return 100.0
            eq = equipment[ref]
            table = eq.setdefault("condition_by_item", {})
            return _clamp(_num(table.get(str(item_id)), 100.0), 0.0, 100.0)

        def transient_exertion_factor(ref: str) -> float:
            """Immediate within-slice performance left after physical effort.

            Saved fatigue is already represented in the actor controls/timing built
            at slice start.  This factor only represents effort accumulated since
            this continuous combat slice began, so repeated explosive actions can
            degrade later reactions before the command settles durable fatigue.
            """
            _, attrs_now = _stats(people[ref])
            endurance = max(0.0, _num(attrs_now.get("Endurance")))
            burden_now = equipment[ref].get("burden", {}) if isinstance(equipment[ref].get("burden"), Mapping) else {}
            burden_factor = max(0.55, _num(burden_now.get("fatigue_multiplier"), 1.0))
            saved = person_fatigue_factors(fatigue=_fatigue(people[ref]), endurance=endurance)
            # Endurance controls the amount of explosive work available in this
            # continuous slice. Saved fatigue then reduces what remains. The
            # roughly linear reserve makes 200 Endurance materially longer-lived
            # than 40 without granting infinite action.
            reserve = (8.0 + 0.12 * endurance) * _num(saved.get("exertion_capacity_factor"), 1.0)
            spent = max(0.0, action_exertion[ref]) * burden_factor
            return _clamp(1.0 / (1.0 + spent / max(1.0, reserve)), 0.25, 1.0)

        def set_condition(ref: str, item_id: str | None, after: float, *, reason: str, event_id: str) -> None:
            if not item_id:
                return
            iid = str(item_id)
            eq = equipment[ref]
            table = eq.setdefault("condition_by_item", {})
            before_now = _clamp(_num(table.get(iid), 100.0), 0.0, 100.0)
            after = _clamp(after, 0.0, 100.0)
            table[iid] = after
            transient = eq.get("transient_improvised_prop") if isinstance(eq.get("transient_improvised_prop"), Mapping) else None
            is_transient = bool(transient and str(transient.get("fact_ref") or "") == iid)
            if is_transient:
                transient_player_prop_state["condition_pct"] = round(after, 3)
                if after <= 0.0:
                    transient_player_prop_state["status"] = "broken"
            else:
                person_state = people[ref].setdefault("equipment_condition", {})
                person_state[iid] = round(after, 3)
            saved = equipment_condition_changes[ref].get(iid)
            original = _num(saved.get("before_condition_pct"), before_now) if isinstance(saved, Mapping) else before_now
            equipment_condition_changes[ref][iid] = {
                "item_id": iid,
                "before_condition_pct": round(original, 3),
                "after_condition_pct": round(after, 3),
                "condition_loss_pct": round(max(0.0, original - after), 3),
                "failed": bool(after <= 0.0),
                "last_reason": reason,
                "last_event_id": event_id,
            }

        def jitter(index: int, side: int = 0) -> float:
            shifted = (seed >> ((index * 7 + side * 3) % 48)) & 0x7FF
            return (shifted / 2047.0 - 0.5) * 8.0

        def current_intent() -> str | None:
            return planned_intents[combo_cursor] if combo_cursor < len(planned_intents) else None

        def settle_combo_link(status: str, cause_event_id: str | None) -> None:
            nonlocal combo_cursor
            if combo_cursor >= len(combo_links):
                return
            combo_links[combo_cursor]["status"] = status
            combo_links[combo_cursor]["cause_event_id"] = cause_event_id
            combo_cursor += 1
            if status == "failed":
                for row in combo_links[combo_cursor:]:
                    if row["status"] == "pending":
                        row["status"] = "cancelled_dependency_failed"
                        row["cause_event_id"] = cause_event_id
                combo_cursor = len(combo_links)

        def defensive_intent(text: str | None) -> bool:
            low = (text or "").lower()
            return any(token in low for token in (
                "parry", "deflect", "block", "brace", "dodge", "evade",
                "reposition", "guard", "intercept", "counter",
            ))

        def pure_move_intent(text: str | None) -> bool:
            low = (text or "").lower()
            return bool(text) and any(token in low for token in ("close", "advance", "step inside", "move inside", "step back", "withdraw", "retreat")) and not any(token in low for token in ("cut", "slash", "thrust", "stab", "strike", "attack", "smash", "grapple"))

        def angle_delta(a: float, b: float) -> float:
            return abs(((float(a) - float(b) + 180.0) % 360.0) - 180.0)

        def position_at(ref: str, at_s: float) -> tuple[float, float]:
            base = positions[ref]
            x = float(base["x_m"]); y = float(base["y_m"])
            row = pending.get(ref)
            if isinstance(row, Mapping) and row.get("kind") == "movement":
                start = _num(row.get("start_at_s")); end = _num(row.get("resolve_at_s"))
                if at_s > start:
                    progress = 1.0 if end <= start else _clamp((at_s - start) / (end - start), 0.0, 1.0)
                    x0 = _num(row.get("from_x_m"), x); y0 = _num(row.get("from_y_m"), y)
                    x1 = _num(row.get("to_x_m"), x0); y1 = _num(row.get("to_y_m"), y0)
                    x = x0 + (x1 - x0) * progress; y = y0 + (y1 - y0) * progress
            return x, y

        def distance_between(ref: str, target_ref: str, at_s: float) -> float:
            ax, ay = position_at(ref, at_s); bx, by = position_at(target_ref, at_s)
            az = _num(positions[ref].get("elevation_m"), 0.0); bz = _num(positions[target_ref].get("elevation_m"), 0.0)
            return _clamp(math.sqrt((bx - ax) ** 2 + (by - ay) ** 2 + (bz - az) ** 2), 0.05, 400.0)

        def melee_surface_gap(ref: str, target_ref: str, at_s: float) -> float:
            poses = geometry_positions(at_s)
            return surface_gap(poses[ref], poses[target_ref])

        def geometry_positions(at_s: float) -> dict[str, dict[str, float]]:
            out: dict[str, dict[str, float]] = {}
            for actor in actors:
                x, y = position_at(actor, at_s)
                posture = str(body_state.get(actor, {}).get("posture", "standing")) if "body_state" in locals() else "standing"
                height_m = 0.45 if posture in {"prone","falling","knocked_down"} else (1.15 if posture == "kneeling" else (2.35 if bool(timing.get(actor,{}).get("mounted")) else 1.75))
                out[actor] = {
                    "x_m": x, "y_m": y,
                    "elevation_m": _num(positions[actor].get("elevation_m"), 0.0),
                    "height_m": height_m,
                    "facing_deg": _num(body_state.get(actor, {}).get("facing_deg"), positions[actor].get("facing_deg", 0.0)) % 360.0,
                    "radius_m": actor_clearance_radius(actor) if "body_state" in locals() else _num(positions[actor].get("radius_m"), 0.28),
                }
            return out

        def bearing(ref: str, target_ref: str, at_s: float) -> float:
            ax, ay = position_at(ref, at_s); bx, by = position_at(target_ref, at_s)
            return math.degrees(math.atan2(by - ay, bx - ax)) % 360.0

        def _point_segment_distance(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
            vx=x2-x1; vy=y2-y1; denom=vx*vx+vy*vy
            if denom<=1e-12:
                return math.hypot(px-x1,py-y1)
            t=_clamp(((px-x1)*vx+(py-y1)*vy)/denom,0.0,1.0)
            return math.hypot(px-(x1+t*vx),py-(y1+t*vy))

        def static_obstacle_at(x: float, y: float, *, radius_m: float = 0.0) -> dict[str, Any] | None:
            margin=max(0.0,_num(local_obstacle_model.get("clearance_margin_m"),0.08))+max(0.0,radius_m)
            for obstacle in local_obstacles:
                if obstacle.get("kind")=="circle":
                    limit=max(0.01,_num(obstacle.get("radius_m")))+margin
                    if math.hypot(x-_num(obstacle.get("x_m")),y-_num(obstacle.get("y_m"))) < limit:
                        return obstacle
                elif obstacle.get("kind")=="segment":
                    limit=max(0.0,_num(obstacle.get("clearance_m")))+margin
                    if _point_segment_distance(x,y,_num(obstacle.get("x1_m")),_num(obstacle.get("y1_m")),_num(obstacle.get("x2_m")),_num(obstacle.get("y2_m"))) < limit:
                        return obstacle
            return None

        def obstacle_on_path(x0: float, y0: float, x1: float, y1: float, *, radius_m: float = 0.0) -> dict[str, Any] | None:
            """Use the shared local-geometry obstruction authority."""
            return first_static_obstacle_on_segment(
                {"x_m": x0, "y_m": y0},
                {"x_m": x1, "y_m": y1},
                local_obstacles,
                clearance_m=max(0.0, radius_m) + max(0.0, _num(local_obstacle_model.get("clearance_margin_m"), 0.08)),
            )

        def actor_clearance_radius(ref: str) -> float:
            if bool(timing.get(ref,{}).get("mounted")):
                return max(0.35,_num(local_obstacle_model.get("mounted_body_radius_m"),0.75))
            if str(body_state.get(ref,{}).get("posture","standing")) in {"prone","falling","knocked_down"}:
                return max(0.20,_num(local_obstacle_model.get("fallen_body_radius_m"),0.38))
            return max(0.18,_num(local_obstacle_model.get("human_body_radius_m"),0.28))

        def clamp_local_movement(ref: str, target_ref: str, x0: float, y0: float, x1: float, y1: float, at_s: float) -> tuple[float,float,dict[str,Any] | None]:
            distance=math.hypot(x1-x0,y1-y0)
            steps=max(2,min(120,int(math.ceil(distance/0.04))))
            self_radius=actor_clearance_radius(ref)
            last_x,last_y=x0,y0; blocker=None
            for step in range(1,steps+1):
                t=step/steps; nx=x0+(x1-x0)*t; ny=y0+(y1-y0)*t
                blocker=static_obstacle_at(nx,ny,radius_m=self_radius)
                if blocker is None:
                    for other in actors:
                        if other == ref:
                            continue
                        ox,oy=position_at(other,at_s)
                        other_radius=actor_clearance_radius(other)
                        margin=max(0.0,_num(local_obstacle_model.get("clearance_margin_m"),0.08))
                        # The intended opponent may be entered to contact range,
                        # but even a grapple does not allow two body centers to
                        # occupy the same coordinates. Incapacitated/fallen bodies
                        # remain physical blockers instead of disappearing.
                        required=(max(0.30,self_radius+other_radius-0.18) if other==target_ref else self_radius+other_radius+margin)
                        current_sep=math.hypot(nx-ox,ny-oy); start_sep=math.hypot(x0-ox,y0-oy)
                        # Existing crowded geometry may already place bodies inside
                        # ideal clearance. Preserve that established scene, but do
                        # not allow the mover to compress the overlap further.
                        if current_sep<required and current_sep<start_sep-0.01:
                            blocker={"kind":"body","label":other}; break
                if blocker is not None:
                    break
                last_x,last_y=nx,ny
            return last_x,last_y,blocker

        def active(ref: str) -> bool:
            person = people[ref]
            life = str(person.get("life_status", person.get("status", "active"))).lower()
            if life in {"dead", "deceased", "destroyed", "killed"}:
                return False
            if self._person_health(person).lower() in {"dead", "deceased", "incapacitated"}:
                return False
            state = person.get("combat_state") if isinstance(person.get("combat_state"), Mapping) else {}
            return not bool(state.get("incapacitated"))

        def status_constraints(ref: str, at_s: float) -> dict[str, Any]:
            cstate = people[ref].get("combat_state", {}) if isinstance(people[ref].get("combat_state"), Mapping) else {}
            anatomy = anatomy_function_factors(people[ref])
            stunned_until = max(0.0, _num(cstate.get("stunned_until_s"), 0.0))
            restrained = bool(cstate.get("restrained") or cstate.get("restrained_by"))
            immobilized = bool(cstate.get("immobilized") or _num(cstate.get("immobilized_until_s"), 0.0) > at_s)
            entangled = bool(cstate.get("entangled") or cstate.get("entangled_by"))
            transient_blind = bool(cstate.get("blinded") or cstate.get("vision_disabled"))
            anatomy_blind = _num(anatomy.get("vision_factor"), 1.0) <= 0.05
            blinded = transient_blind or anatomy_blind
            visual_detection = 0.0 if transient_blind else _clamp(_num(anatomy.get("visual_detection_factor"), 1.0), 0.0, 1.0)
            ranged_targeting = 0.0 if transient_blind else _clamp(_num(anatomy.get("ranged_targeting_factor"), 1.0), 0.0, 1.0)
            return {
                "stunned": stunned_until > at_s,
                "stunned_until_s": stunned_until,
                "restrained": restrained,
                "immobilized": immobilized,
                "entangled": entangled,
                "blinded": blinded,
                "movement_factor": 0.0 if restrained or immobilized else (0.45 if entangled else 1.0),
                "attack_factor": (0.35 if restrained else 1.0) * (0.34 if transient_blind else 1.0),
                "defense_factor": 0.45 if restrained else (0.65 if entangled else 1.0),
                "awareness_factor": 0.45 if transient_blind else 1.0,
                "visual_detection_factor": visual_detection,
                "ranged_targeting_factor": ranged_targeting,
            }

        def physically_present(ref: str) -> bool:
            return ref in people and ref in positions

        def grapple_score(ref: str) -> float:
            skills_now, attrs_now = _stats(people[ref])
            grappling = max(0.0, _num(skills_now.get("Grappling"), _num(skills_now.get("Wrestling"), 0.0)))
            athletics = max(0.0, _num(skills_now.get("Athletics"), 0.0))
            return (
                0.34 * grappling
                + 0.18 * athletics
                + 0.20 * _num(attrs_now.get("Strength"))
                + 0.14 * _num(attrs_now.get("Coordination"))
                + 0.10 * _num(attrs_now.get("Agility"))
                + 0.04 * _num(attrs_now.get("Composure"))
            )

        def grapple_intent(text: str | None) -> str | None:
            low = (text or "").lower()
            if not low:
                return None
            if any(token in low for token in ("release clinch", "release grapple", "let go", "break clinch voluntarily")):
                return "release"
            if any(token in low for token in ("throw", "trip", "takedown", "slam")) and any(token in low for token in ("grapple", "clinch", "wrestl", "throw", "takedown", "trip", "slam")):
                return "throw"
            if any(token in low for token in ("grapple", "clinch", "wrestl", "grab", "tackle")):
                return "attempt"
            return None

        def clear_grapple(a: str, b: str | None = None) -> None:
            partner = b or body_state.get(a, {}).get("grappled_with")
            for ref, other in ((a, partner), (partner, a)):
                if not ref or ref not in body_state:
                    continue
                if other is None or body_state[ref].get("grappled_with") == other:
                    body_state[ref]["grappled_with"] = None
                    body_state[ref]["grapple_role"] = None
                    cstate = people[ref].setdefault("combat_state", {})
                    cstate.pop("grappled_with", None); cstate.pop("grapple_role", None); cstate.pop("grapple_started_at_s", None)

        def bind_grapple(controller: str, controlled: str, at_s: float) -> None:
            for ref, partner, role in ((controller, controlled, "controller"), (controlled, controller, "controlled")):
                body_state[ref]["grappled_with"] = partner
                body_state[ref]["grapple_role"] = role
                cstate = people[ref].setdefault("combat_state", {})
                cstate["grappled_with"] = partner; cstate["grapple_role"] = role; cstate["grapple_started_at_s"] = round(at_s, 6)

        def begin_fall(ref: str, *, severity: str, at_s: float, reason: str, source_event_id: str) -> dict[str, Any]:
            fall_map = posture_timing.get("fall_seconds_by_severity", {}) if isinstance(posture_timing.get("fall_seconds_by_severity"), Mapping) else {}
            prone_map = posture_timing.get("prone_minimum_seconds_by_severity", {}) if isinstance(posture_timing.get("prone_minimum_seconds_by_severity"), Mapping) else {}
            defaults_fall = {"minor":0.35,"moderate":0.55,"serious":0.85,"critical":1.15}
            defaults_prone = {"minor":0.45,"moderate":0.8,"serious":1.4,"critical":2.4}
            severity = severity if severity in defaults_fall else "moderate"
            fall_seconds=max(0.12,_num(fall_map.get(severity),defaults_fall[severity])); prone_seconds=max(0.20,_num(prone_map.get(severity),defaults_prone[severity]))
            ground_at=at_s+fall_seconds; earliest=ground_at+prone_seconds
            clear_grapple(ref)
            cstate=people[ref].setdefault("combat_state", {}); cstate["posture"]="falling"; cstate["fall_started_at_s"]=round(at_s,6); cstate["ground_contact_at_s"]=round(ground_at,6); cstate["earliest_get_up_at_s"]=round(earliest,6); cstate["fall_reason"]=reason
            body_state[ref]["posture"]="falling"; body_state[ref]["fall_started_at_s"]=at_s; body_state[ref]["fall_complete_at_s"]=ground_at; body_state[ref]["earliest_get_up_at_s"]=earliest; body_state[ref]["balance"]=min(_num(body_state[ref].get("balance"),1.0),0.25)
            ready_at[ref]=max(float(ready_at.get(ref,0.0)),ground_at)
            event={"id":source_event_id+"_fall","kind":"posture_state","actor_ref":ref,"action":"fall_started","reason":reason,"severity":severity,"fall_seconds":round(fall_seconds,3),"ground_contact_at_s":round(ground_at,3),"earliest_get_up_at_s":round(earliest,3),"at_s":round(at_s,3)}
            trace.append(event); must_render.append(event["id"]); return event

        requested_target = str(payload.get("target_ref", ""))

        def current_team_plan(ref: str, at_s: float) -> dict[str, Any]:
            side = sorted(player_side if ref in player_side else hostile_side)
            enemies = sorted(hostile_side if ref in player_side else player_side)
            side_key = "player_side" if ref in player_side else "hostile_side"
            poses = geometry_positions(at_s)
            knowledge_by_actor: dict[str, list[str]] = {}
            for ally in side:
                known: list[str] = []
                for enemy in enemies:
                    if ally not in poses or enemy not in poses:
                        continue
                    los = line_of_sight_query(ally, enemy, poses, local_obstacles)
                    distance = distance_between(ally, enemy, at_s)
                    # Direct visual evidence or unmistakable close physical
                    # presence is enough for the actor to know the threat exists.
                    if _num(los.get("visibility_factor"), 0.0) >= 0.22 or distance <= 2.0:
                        known.append(enemy)
                knowledge_by_actor[ally] = known
            recent_failures = {
                ally: sum(
                    1 for row in action_memory.get(ally, [])[-4:]
                    if str(row.get("kind")) == "attack"
                    and str(row.get("result")) in {"dodged", "blocked", "parried", "deflected", "counter_intercepted", "denied"}
                )
                for ally in side
            }
            plan = build_team_plan(
                side, enemies, people=people, equipment=equipment, controls=controls,
                positions=poses, objective=objective, at_s=at_s,
                doctrines=doctrines,
                knowledge_by_actor=knowledge_by_actor,
                recent_failures=recent_failures,
                protected_refs=objective_spec.get("protected_refs", []),
            )
            plan_id = str(plan.get("plan_id", "none"))
            if plan_id != last_team_plan_id_by_side.get(side_key):
                last_team_plan_id_by_side[side_key] = plan_id
                team_plan_history.append({"side": side_key, **plan})
            return plan

        def choose_target(ref: str, at_s: float) -> str | None:
            candidates = hostile_side if ref in player_side else player_side
            alive = [other for other in candidates if other != ref and active(other)]
            partner = body_state.get(ref, {}).get("grappled_with")
            if partner in alive:
                return str(partner)
            if partner and partner not in alive:
                clear_grapple(ref, str(partner))
            if ref == self.PLAYER_ACTOR and requested_target in alive:
                return requested_target
            if not alive:
                return None
            plan = current_team_plan(ref, at_s)
            chosen = choose_tactical_target(ref, alive, plan=plan, people=people, positions=geometry_positions(at_s))
            return chosen or min(alive, key=lambda other: (distance_between(ref, other, at_s), other))

        def unsafe_projectile_lane(ref: str, target_ref: str, at_s: float) -> dict[str, Any] | None:
            poses = geometry_positions(at_s)
            if ref not in poses or target_ref not in poses:
                return None
            start = dict(poses[ref]); end = dict(poses[target_ref])
            start["elevation_m"] = _num(start.get("elevation_m"), 0.0) + 1.35
            end["elevation_m"] = _num(end.get("elevation_m"), 0.0) + 1.05
            hits = body_intersections_on_segment(
                start, end, poses, exclude_refs=(ref, target_ref),
                half_width_m=0.02,
                elevation_start_m=start["elevation_m"], elevation_end_m=end["elevation_m"],
                vertical_tolerance_m=0.08,
            )
            if not hits:
                return None
            first = dict(hits[0])
            screen_ref = str(first.get("ref", ""))
            same_side = (screen_ref in player_side) == (ref in player_side)
            if same_side:
                first["unsafe_reason"] = "friendly_body_in_projectile_lane"
                return first
            return None

        def movement_reversal_factor(ref: str, x0: float, y0: float, x1: float, y1: float, at_s: float) -> float:
            if at_s >= _num(body_state.get(ref, {}).get("movement_velocity_until_s"), 0.0):
                return 1.0
            prior = body_state.get(ref, {}).get("movement_velocity_xy_mps", (0.0, 0.0))
            try:
                pvx, pvy = float(prior[0]), float(prior[1])
            except (TypeError, ValueError, IndexError):
                return 1.0
            ndx, ndy = x1-x0, y1-y0
            pmag, nmag = math.hypot(pvx,pvy), math.hypot(ndx,ndy)
            if pmag <= 1e-6 or nmag <= 1e-6:
                return 1.0
            alignment = (pvx*ndx+pvy*ndy)/(pmag*nmag)
            # Reversing an already committed body vector costs acceleration and
            # deceleration time. Same-direction continuation receives no bonus.
            return 1.0 + 0.32 * max(0.0, -alignment)

        def projected_step(ref: str, target_ref: str, delta_distance_m: float, at_s: float) -> tuple[float, float, float, float, dict[str, Any] | None]:
            """Return start/end XY for a relative close/open movement.

            Negative delta closes range, positive delta opens range.  The target
            is sampled at action start; later target motion still changes the
            actual contact geometry rather than teleporting this mover.
            """
            x0, y0 = position_at(ref, at_s); tx, ty = position_at(target_ref, at_s)
            dx = tx - x0; dy = ty - y0; mag = max(1e-6, math.hypot(dx, dy))
            ux = dx / mag; uy = dy / mag
            travel = -float(delta_distance_m)
            proposed_x=x0+ux*travel; proposed_y=y0+uy*travel
            x1,y1,blocker=clamp_local_movement(ref,target_ref,x0,y0,proposed_x,proposed_y,at_s)
            return x0,y0,x1,y1,blocker

        first_text = planned_intents[0] if planned_intents else None
        first_is_defensive = defensive_intent(first_text)
        if first_is_defensive:
            active_guard[self.PLAYER_ACTOR] = str(first_text)
        else:
            highest_initiative = max([timing[ref]["initiative"] for ref in actors] + [1.0])
            for ref in actors:
                gap = max(0.0, highest_initiative - timing[ref]["initiative"])
                ready_at[ref] = (gap / (highest_initiative + 60.0)) * 0.45

        # A combat slice is bounded by physical time, not an exchange count.
        # Faster actors therefore receive more action opportunities inside the
        # same tactical phase. A live fight still stops at the first material
        # decision boundary; a non-decisive phase ends at separation/stalemate.
        phase_horizon_seconds = min(
            requested_seconds,
            max(
                6.0,
                4.0 * (
                    p_timing["minimum_action_interval_seconds"]
                    + min(timing[ref]["minimum_action_interval_seconds"] for ref in hostile_side)
                ),
            ),
        )

        def schedule(ref: str) -> None:
            nonlocal action_serial
            if ref in pending or ref in active_guard or boundary is not None or not active(ref):
                return
            # Explicit player intent owns voluntary action selection for this
            # combat slice.  Once that declared sequence has been consumed, do
            # not let actor/team AI invent a fresh attack or reposition for
            # Tang Wei.  Involuntary/reactive defenses against later incoming
            # contacts are still resolved physically by the defender pipeline.
            # This preserves player agency and, critically, preserves the exact
            # geometry created by the player's last declared movement until a
            # later physical event changes it.
            if ref == self.PLAYER_ACTOR and planned_intents and current_intent() is None:
                return
            start_at = max(0.0, float(ready_at[ref]))
            constraints = status_constraints(ref, start_at)
            if constraints["stunned"]:
                recover_at = min(phase_horizon_seconds, max(start_at + 0.01, _num(constraints.get("stunned_until_s"), start_at)))
                if recover_at <= start_at + 1e-9:
                    return
                action_serial += 1
                pending[ref] = {
                    "id": f"action_{action_serial:04d}", "sequence": action_serial,
                    "kind": "status_recovery", "actor_ref": ref, "target_ref": ref,
                    "status": "stunned", "start_at_s": start_at, "resolve_at_s": recover_at,
                    "recovery_complete_at_s": recover_at, "decision_source": "status_constraint",
                }
                return
            posture = str(body_state[ref].get("posture", "standing"))
            if posture == "falling":
                ground_at = max(0.0, _num(body_state[ref].get("fall_complete_at_s"), start_at))
                if ground_at >= phase_horizon_seconds:
                    return
                eq = equipment[ref]
                ctrl = controls[ref]
                profile = timing[ref]
                exertion_factor = transient_exertion_factor(ref)
                action_serial += 1
                action_id = f"action_{action_serial:04d}"
                pending[ref] = {
                    "id": action_id, "sequence": action_serial, "kind": "posture_fall",
                    "actor_ref": ref, "target_ref": ref, "from_posture": "falling",
                    "to_posture": "prone", "start_at_s": _num(body_state[ref].get("fall_started_at_s"), start_at),
                    "resolve_at_s": ground_at,
                    "earliest_recovery_at_s": max(ground_at, _num(body_state[ref].get("earliest_get_up_at_s"), ground_at)),
                }
                return
            if start_at >= phase_horizon_seconds:
                return
            eq = equipment[ref]
            ctrl = controls[ref]
            profile = timing[ref]
            exertion_factor = transient_exertion_factor(ref)
            embedded = people[ref].get("combat_state", {}).get("embedded_weapon") if isinstance(people[ref].get("combat_state"), Mapping) else None
            if isinstance(embedded, Mapping) and embedded.get("item_id") and pending_boundary is None:
                embedded_target=str(embedded.get("target_ref", ""))
                if embedded_target in actors:
                    action_serial += 1
                    action_id=f"action_{action_serial:04d}"
                    extraction=max(0.12,_num(embedded.get("extraction_seconds"),_num(embedded_weapon_model.get("base_extraction_seconds"),0.42)))/exertion_factor
                    pending[ref]={"id":action_id,"sequence":action_serial,"kind":"weapon_extraction","actor_ref":ref,"target_ref":embedded_target,"item_id":str(embedded.get("item_id")),"target_structure":embedded.get("target_structure"),"start_at_s":start_at,"resolve_at_s":start_at+extraction,"recovery_complete_at_s":start_at+extraction+0.12/exertion_factor,"scheduled_exertion_factor":round(exertion_factor,6)}
                    return
            target_ref = choose_target(ref, start_at)
            if target_ref is None:
                return
            team_plan = current_team_plan(ref, start_at)
            assignment = team_plan.get("assignments", {}).get(ref, {}) if isinstance(team_plan.get("assignments"), Mapping) else {}
            team_role = str(assignment.get("role", "support"))
            decision_source = "player_intent" if ref == self.PLAYER_ACTOR and current_intent() else ("team_ai" if team_plan.get("plan_id") != "none" else "actor_ai")
            current_posture = str(body_state[ref].get("posture", "standing"))
            if current_posture in {"prone", "knocked_down", "kneeling"}:
                actor_skills_now, actor_attrs_now = _stats(people[ref])
                athletics = max(0.0, _num(actor_skills_now.get("Athletics")))
                grappling = max(0.0, _num(actor_skills_now.get("Grappling")))
                agility = max(0.0, _num(actor_attrs_now.get("Agility")))
                movement_factor = max(0.35, _num(eq.get("burden", {}).get("movement_factor"), 1.0)) if isinstance(eq.get("burden"), Mapping) else 1.0
                posture_base = (
                    _num(posture_timing.get("kneel_transition_seconds"), 0.35)
                    if current_posture == "kneeling"
                    else _num(posture_timing.get("get_up_base_seconds"), 1.15)
                )
                skill_factor = _clamp(1.12 - 0.0017 * athletics - 0.0012 * grappling - 0.0011 * agility, 0.50, 1.12)
                duration = _clamp(posture_base * skill_factor / (movement_factor * exertion_factor), 0.30, 3.60)
                resolve_at = start_at + duration
                recovery_complete = resolve_at + 0.18 / exertion_factor
                action_serial += 1
                action_id = f"action_{action_serial:04d}"
                pending[ref] = {
                    "id": action_id,
                    "sequence": action_serial,
                    "kind": "posture_recovery",
                    "actor_ref": ref,
                    "target_ref": ref,
                    "from_posture": current_posture,
                    "to_posture": "standing",
                    "start_at_s": start_at,
                    "resolve_at_s": resolve_at,
                    "recovery_complete_at_s": recovery_complete,
                    "scheduled_exertion_factor": round(exertion_factor, 6),
                }
                return
            weapon = eq.get("weapon", {}) if isinstance(eq.get("weapon"), Mapping) else {}
            melee_weapon = eq.get("melee_weapon", {}) if isinstance(eq.get("melee_weapon"), Mapping) else {}
            ranged_weapon = eq.get("ranged_weapon", {}) if isinstance(eq.get("ranged_weapon"), Mapping) else {}
            if not melee_weapon and str(weapon.get("schema", "")) == "melee_weapon": melee_weapon = weapon
            declared = current_intent() if ref == self.PLAYER_ACTOR else None
            unarmed_profile = None
            weapon_family = str((melee_weapon or weapon).get("family", "")).lower()
            if weapon_family == "unarmed" or str((melee_weapon or weapon).get("id", "")).lower() == "unarmed":
                unarmed_profile = _unarmed_method_profile(declared)
                reach = float(unarmed_profile["reach_m"])
                minimum = 0.0
            else:
                reach = max(0.12, _num(melee_weapon.get("reach_m"), _num(weapon.get("reach_m"), 0.44)))
                minimum = max(0.0, _num(melee_weapon.get("minimum_range_m"), _num(weapon.get("minimum_range_m"), 0.0)))
            if ref == self.PLAYER_ACTOR and defensive_intent(declared):
                active_guard[ref] = str(declared)
                return
            grapple_kind = grapple_intent(declared) if ref == self.PLAYER_ACTOR else None
            partner = body_state[ref].get("grappled_with")
            if partner and partner in actors and active(str(partner)):
                target_ref = str(partner)
                role = str(body_state[ref].get("grapple_role") or "controlled")
                if grapple_kind == "release" and role == "controller":
                    scheduled_grapple_kind = "grapple_release"
                elif role == "controlled":
                    scheduled_grapple_kind = "grapple_escape"
                elif grapple_kind == "throw":
                    scheduled_grapple_kind = "grapple_throw"
                else:
                    scheduled_grapple_kind = "grapple_hold"
                action_serial += 1; action_id=f"action_{action_serial:04d}"
                recovery = {"grapple_release":0.20,"grapple_escape":_num(grapple_model.get("escape_recovery_seconds"),0.75),"grapple_throw":_num(grapple_model.get("throw_recovery_seconds"),0.95),"grapple_hold":_num(grapple_model.get("hold_recovery_seconds"),0.55)}[scheduled_grapple_kind]
                resolve_at = start_at + max(0.10, 0.34 * profile["minimum_action_interval_seconds"] / exertion_factor)
                pending[ref] = {"id":action_id,"sequence":action_serial,"kind":scheduled_grapple_kind,"actor_ref":ref,"target_ref":target_ref,"declared_intent":declared,"start_at_s":start_at,"resolve_at_s":resolve_at,"recovery_complete_at_s":resolve_at+max(0.10,recovery/exertion_factor),"scheduled_exertion_factor":round(exertion_factor,6)}
                return
            action_serial += 1
            action_id = f"action_{action_serial:04d}"
            start_dist = distance_between(ref, target_ref, start_at)
            start_gap = melee_surface_gap(ref, target_ref, start_at)
            if grapple_kind in {"attempt", "throw"}:
                engage=max(0.35,_num(grapple_model.get("engagement_distance_m"),0.9))
                if start_dist <= engage:
                    resolve_at=start_at+max(0.12,0.42*profile["minimum_action_interval_seconds"]/exertion_factor)
                    pending[ref]={"id":action_id,"sequence":action_serial,"kind":"grapple_attempt","actor_ref":ref,"target_ref":target_ref,"declared_intent":declared,"follow_throw":grapple_kind=="throw","start_at_s":start_at,"resolve_at_s":resolve_at,"recovery_complete_at_s":resolve_at+max(0.12,_num(grapple_model.get("hold_recovery_seconds"),0.55)/exertion_factor),"scheduled_exertion_factor":round(exertion_factor,6)}
                    return
            move_only = ref == self.PLAYER_ACTOR and pure_move_intent(declared)
            declared_lower = str(declared or "").lower()
            ammo_id = str(eq.get("ammunition_item_id", ""))
            ammo_left = max(0, int(projectile_ammunition.get(ref, {}).get(ammo_id, 0))) if ammo_id else 0
            explicit_ranged = any(token in declared_lower for token in ("shoot", "fire", "arrow", "bolt", "bow", "crossbow"))
            ranged_skills, ranged_attrs = _stats(people[ref])
            ranged_family = str(ranged_weapon.get("family", ranged_weapon.get("schema", ""))).lower() if ranged_weapon else ""
            ranged_skill_name = "Crossbow" if ranged_family == "crossbow" else "Bow"
            ranged_envelope = projectile_operating_envelope(ranged_weapon, weapon_skill=_num(ranged_skills.get(ranged_skill_name,0)), strength=_num(ranged_attrs.get("Strength",0)), coordination=_num(ranged_attrs.get("Coordination",0)), awareness=_num(ranged_attrs.get("Awareness",0))) if ranged_weapon else {}
            ranged_max = max(0.0, _num(ranged_envelope.get("maximum_direct_range_m"), 0.0))
            visual_ranged_factor = _clamp(_num(constraints.get("ranged_targeting_factor"), 1.0), 0.0, 1.0)
            use_ranged = bool(ranged_weapon) and ammo_left > 0 and visual_ranged_factor > 0.05 and not move_only and (
                explicit_ranged
                or not melee_weapon
                # A readied missile weapon remains a lawful option once the
                # opponent is materially outside the readied melee weapon's
                # usable contact envelope.  The former +0.75 m buffer made
                # archers at short tactical range abandon a nocked/readied shot
                # and walk into melee for no physical reason.
                or start_gap > reach + 0.25
            )
            unsafe_lane = unsafe_projectile_lane(ref, target_ref, start_at) if use_ranged else None
            # Autonomous/team AI never chooses a shot whose current physical
            # lane first intersects a friendly body. A player may deliberately
            # order the risky shot; the release is marked and the fixed-lane
            # contact resolver can then hit the screening ally.
            if unsafe_lane is not None and not (ref == self.PLAYER_ACTOR and explicit_ranged):
                use_ranged = False

            if use_ranged and 0.75 <= start_dist <= max(0.75, ranged_max):
                aim = self._personal_aim_plan(
                    declared, lethal_intent=lethal_intent, seed=seed, sequence=action_serial,
                    actor=people.get(ref), target_person=people.get(target_ref), target_eq=equipment.get(target_ref),
                    recent_actions=action_memory[ref], target_last_defense=last_defense_method.get(target_ref),
                )
                actor_skills_now, actor_attrs_now = _stats(people[ref])
                family = str(ranged_weapon.get("family", ranged_weapon.get("schema", ""))).lower()
                ranged_skill_name = "Crossbow" if family == "crossbow" else "Bow"
                projectile = eq.get("ammunition_item", {}) if isinstance(eq.get("ammunition_item"), Mapping) else {}
                flight = projectile_flight_resolution(
                    ranged_weapon, projectile, distance_m=start_dist,
                    weapon_skill=_num(actor_skills_now.get(ranged_skill_name)),
                    strength=_num(actor_attrs_now.get("Strength")),
                    coordination=_num(actor_attrs_now.get("Coordination")),
                    awareness=_num(actor_attrs_now.get("Awareness")),
                    weapon_condition_pct=current_condition(ref, str(eq.get("ranged_weapon_id") or "")),
                )
                flight["aim_control"] = round(_num(flight.get("aim_control"), 0.0) * visual_ranged_factor, 6)
                flight["visual_targeting_factor"] = round(visual_ranged_factor, 6)
                cycle = max(0.6, _num(ranged_weapon.get("base_shot_cycle_seconds", ranged_weapon.get("base_reload_cycle_seconds", 6.0)), 6.0))
                if family == "crossbow":
                    execution = max(0.55, 1.0 + (_num(actor_skills_now.get("Crossbow")) + _num(actor_attrs_now.get("Coordination")) - 120.0) / 700.0)
                    cycle = cycle / execution
                    cycle = cycle / exertion_factor
                    release_delay = max(0.16, min(1.25 / exertion_factor, 0.20 * cycle))
                else:
                    endurance = _num(actor_attrs_now.get("Endurance"))
                    execution = max(0.60, 1.0 + (_num(actor_skills_now.get("Bow")) + endurance - 120.0) / 650.0)
                    cycle = cycle / execution
                    cycle = cycle / exertion_factor
                    release_delay = max(0.18, min(1.60 / exertion_factor, 0.30 * cycle))
                release_at = start_at + release_delay
                recovery_complete = max(start_at + profile["minimum_action_interval_seconds"] / exertion_factor, start_at + cycle)
                pending[ref] = {
                    "id": action_id, "sequence": action_serial, "kind": "projectile_release",
                    "actor_ref": ref, "target_ref": target_ref, "declared_intent": declared,
                    "aim_zone": aim["body_zone"], "aim_side": aim["side"], "aim_structure": aim["structure"],
                    "aim_purpose": aim["purpose"], "aim_selection_basis": aim.get("selection_basis"),
                    "attack_mode": "thrust", "start_at_s": start_at, "resolve_at_s": release_at,
                    "recovery_complete_at_s": recovery_complete, "projectile_flight": flight,
                    "ranged_weapon_id": str(eq.get("ranged_weapon_id") or ranged_weapon.get("id", "")),
                    "ammunition_item_id": ammo_id, "release_distance_m": start_dist,
                    "unsafe_lane_at_schedule": (dict(unsafe_lane) if isinstance(unsafe_lane, Mapping) else None),
                    "decision_source": decision_source, "team_role": team_role, "team_plan_id": team_plan.get("plan_id"),
                    "scheduled_exertion_factor": round(exertion_factor, 6),
                }
                return

            if start_gap > reach + 0.10 and _num(constraints.get("movement_factor"), 1.0) <= 1e-9:
                # Immobilized/restrained actors do not receive a magical melee
                # attack from outside reach. They remain present and consume time
                # while searching for a lawful opportunity.
                pending[ref] = {
                    "id": action_id, "sequence": action_serial, "kind": "guard_wait",
                    "actor_ref": ref, "target_ref": target_ref,
                    "reason": "melee_target_out_of_reach_while_movement_illegal",
                    "start_at_s": start_at, "resolve_at_s": start_at + 0.25,
                    "recovery_complete_at_s": start_at + 0.25,
                    "decision_source": "actor_ai_legality",
                }
                return

            if not declared and team_role == "shape" and _num(constraints.get("movement_factor"), 1.0) > 0.0:
                target_facing = _num(body_state[target_ref].get("facing_deg"), positions[target_ref].get("facing_deg", 0.0))
                relative = angle_delta(bearing(target_ref, ref, start_at), target_facing)
                # A rear or rear-flank position is already valuable shaping; do
                # not waste the opening by orbiting merely because the bearing is
                # far from the target's front. Reposition only from a strongly
                # frontal lane where another angle would add pressure.
                team_pressure = surrounding_pressure(
                    target_ref,
                    [r for r in (player_side if ref in player_side else hostile_side) if r != target_ref and active(r)],
                    geometry_positions(start_at),
                )
                # If the side already occupies a strong cross-angle, shaping has
                # succeeded; do not sacrifice simultaneous pressure by orbiting
                # one attacker just because their own lane is frontal.
                if relative < 62.0 and _num(team_pressure.get("covered_arc_deg"), 0.0) < 120.0:
                    clockwise = (sum(ord(ch) for ch in ref) % 2) == 0
                    vx, vy = flank_vector(ref, target_ref, geometry_positions(start_at), clockwise=clockwise)
                    step = min(0.45, max(0.22, profile["movement_speed_mps"] * 0.16))
                    x0, y0 = position_at(ref, start_at)
                    px, py = x0 + vx * step, y0 + vy * step
                    x1, y1, movement_blocker = clamp_local_movement(ref, target_ref, x0, y0, px, py, start_at)
                    moved = math.hypot(x1 - x0, y1 - y0)
                    if moved > 0.04:
                        duration = max(0.08, moved / max(0.1, profile["movement_speed_mps"] * exertion_factor)) * movement_reversal_factor(ref, x0, y0, x1, y1, start_at)
                        resolve_at = start_at + duration
                        pending[ref] = {
                            "id": action_id, "sequence": action_serial, "kind": "movement",
                            "actor_ref": ref, "target_ref": target_ref, "action": "team_shape_flank",
                            "declared_intent": None, "consume_intent": False,
                            "start_at_s": start_at, "resolve_at_s": resolve_at,
                            "recovery_complete_at_s": resolve_at + profile["movement_recovery_seconds"] / exertion_factor,
                            "from_distance_m": start_dist, "distance_delta_m": 0.0,
                            "from_x_m": x0, "from_y_m": y0, "to_x_m": x1, "to_y_m": y1,
                            "movement_blocked_by": (dict(movement_blocker) if isinstance(movement_blocker, Mapping) else None),
                            "decision_source": decision_source, "team_role": team_role, "team_plan_id": team_plan.get("plan_id"),
                            "scheduled_exertion_factor": round(exertion_factor, 6),
                        }
                        return

            delta = 0.0
            movement_action = False
            movement_label = ""
            if move_only:
                low = (declared or "").lower()
                if any(token in low for token in ("step back", "withdraw", "retreat")):
                    delta = min(0.55, max(0.12, 3.0 - start_dist))
                    movement_label = "opens_distance"
                else:
                    delta = -min(0.55, max(0.12, start_dist - max(0.40, minimum + 0.08)))
                    movement_label = "closes_distance"
                movement_action = abs(delta) > 1e-6
            elif grapple_kind in {"attempt", "throw"} and start_dist > max(0.35,_num(grapple_model.get("engagement_distance_m"),0.9)):
                engage=max(0.35,_num(grapple_model.get("engagement_distance_m"),0.9))
                delta=-max(0.0,start_dist-max(0.28,engage*0.88)); movement_label="closes_to_grapple"; movement_action=abs(delta)>1e-6
            elif start_gap > reach:
                target_radius = actor_clearance_radius(target_ref)
                desired_gap = max(minimum + 0.08, min(reach * 0.88, 1.25))
                desired = target_radius + desired_gap
                delta = -max(0.0, start_dist - desired)
                movement_label = "closes_distance"
                movement_action = abs(delta) > 1e-6
            elif start_gap < minimum:
                delta = min(max(0.0, minimum + 0.12 - start_gap), 0.75)
                movement_label = "recovers_weapon_space"
                movement_action = abs(delta) > 1e-6

            if movement_action:
                legal_movement_factor = _clamp(_num(constraints.get("movement_factor"), 1.0), 0.0, 1.0)
                x0, y0, x1, y1, movement_blocker = projected_step(ref, target_ref, delta, start_at)
                actual_travel = math.hypot(x1-x0, y1-y0)
                duration = max(0.08, actual_travel / max(0.1, profile["movement_speed_mps"] * exertion_factor * max(0.05, legal_movement_factor)))
                duration *= movement_reversal_factor(ref, x0, y0, x1, y1, start_at)
                resolve_at = start_at + duration
                recovery_complete = max(
                    start_at + profile["minimum_action_interval_seconds"] / exertion_factor,
                    resolve_at + profile["movement_recovery_seconds"] / exertion_factor,
                )
                pending[ref] = {
                    "id": action_id,
                    "sequence": action_serial,
                    "kind": "movement",
                    "actor_ref": ref,
                    "target_ref": target_ref,
                    "action": movement_label,
                    "declared_intent": declared,
                    "consume_intent": bool(move_only),
                    "start_at_s": start_at,
                    "resolve_at_s": resolve_at,
                    "recovery_complete_at_s": recovery_complete,
                    "from_distance_m": start_dist,
                    "distance_delta_m": delta,
                    "from_x_m": x0,
                    "from_y_m": y0,
                    "to_x_m": x1,
                    "to_y_m": y1,
                    "movement_blocked_by": (dict(movement_blocker) if isinstance(movement_blocker, Mapping) else None),
                    "decision_source": decision_source, "team_role": team_role, "team_plan_id": team_plan.get("plan_id"),
                    "scheduled_exertion_factor": round(exertion_factor, 6),
                }
                return

            startup_factor = _num(unarmed_profile.get("startup_factor"), 1.0) if isinstance(unarmed_profile, Mapping) else 1.0
            recovery_factor = _num(unarmed_profile.get("recovery_factor"), 1.0) if isinstance(unarmed_profile, Mapping) else 1.0
            contact_at = start_at + profile["attack_startup_seconds"] * startup_factor / exertion_factor
            recovery_complete = max(
                start_at + profile["minimum_action_interval_seconds"] / exertion_factor,
                contact_at + profile["attack_recovery_seconds"] * recovery_factor / exertion_factor,
            )
            aim = self._personal_aim_plan(
                declared, lethal_intent=lethal_intent, seed=seed, sequence=action_serial,
                actor=people.get(ref), target_person=people.get(target_ref), target_eq=equipment.get(target_ref),
                recent_actions=action_memory[ref], target_last_defense=last_defense_method.get(target_ref),
            )
            method_plan = self._personal_attack_mode_plan(
                weapon,
                aim_zone=aim["body_zone"],
                aim_structure=aim["structure"],
                declared_intent=declared,
                target_eq=equipment.get(target_ref, {}),
                recent_actions=action_memory[ref],
                target_last_defense=last_defense_method.get(target_ref),
            )
            declared_lower = str(declared or "").lower()
            mounted_body_collision = bool(
                profile.get("mounted")
                and any(token in declared_lower for token in ("ride down", "ride-down", "trample"))
            )
            if mounted_body_collision:
                method_plan = {
                    "mode": "blunt",
                    "force": 0.35,
                    "selection_basis": "declared_mounted_collision",
                    "decision_reason": "horse_and_rider_body_collision",
                }
            if isinstance(unarmed_profile, Mapping):
                method_plan = dict(method_plan)
                method_plan["force"] = _num(method_plan.get("force"), 0.35) * _num(unarmed_profile.get("force_factor"), 1.0)
            commitment_fraction = {
                "thrust": 0.60,
                "cut": 0.50,
                "blunt": 0.46,
            }.get(str(method_plan.get("mode", "")).lower(), 0.52)
            commit_at = start_at + max(0.0, contact_at - start_at) * commitment_fraction
            pending[ref] = {
                "id": action_id,
                "sequence": action_serial,
                "kind": "attack",
                "actor_ref": ref,
                "target_ref": target_ref,
                "declared_intent": declared,
                "aim_zone": aim["body_zone"],
                "aim_side": aim["side"],
                "aim_structure": aim["structure"],
                "aim_purpose": aim["purpose"],
                "aim_selection_basis": aim.get("selection_basis"),
                "attack_mode": method_plan["mode"],
                "attack_force": method_plan["force"],
                "attack_method_selection_basis": method_plan.get("selection_basis"),
                "attack_decision_reason": method_plan.get("decision_reason"),
                "unarmed_method": (unarmed_profile.get("method") if isinstance(unarmed_profile, Mapping) else None),
                "committed_reach_m": round(reach, 6),
                "committed_minimum_range_m": round(minimum, 6),
                "mounted_body_collision": mounted_body_collision,
                "start_at_s": start_at,
                "resolve_at_s": contact_at,
                "recovery_complete_at_s": recovery_complete,
                "decision_source": decision_source, "team_role": team_role, "team_plan_id": team_plan.get("plan_id"),
                "committed_actor_x_m": position_at(ref, start_at)[0],
                "committed_actor_y_m": position_at(ref, start_at)[1],
                "committed_target_x_m": position_at(target_ref, start_at)[0],
                "committed_target_y_m": position_at(target_ref, start_at)[1],
                "committed_target_elevation_m": _num(positions[target_ref].get("elevation_m"), 0.0),
                "commit_at_s": round(commit_at, 6),
                "scheduled_exertion_factor": round(exertion_factor, 6),
            }

        for ref in actors:
            schedule(ref)
        # A deliberately defensive opening leaves the player waiting for a
        # stimulus; make sure the opponent has an active action to resolve.
        if first_is_defensive:
            for ref in sorted(hostile_side):
                schedule(ref)

        simultaneous_window_s = 0.080
        contact_group_serial = 0
        contact_group_anchor = -999.0
        contact_group_positions: dict[str, tuple[float, float]] = {}
        contact_group_body: dict[str, dict[str, Any]] = {}

        while pending and boundary is None:
            pending_key, action = min(
                pending.items(),
                key=lambda item: (
                    _num(item[1].get("resolve_at_s")),
                    -timing[item[0]]["initiative"] if item[0] in timing else 0.0,
                    item[0],
                ),
            )
            resolve_at = _num(action.get("resolve_at_s"))
            committed_after_boundary = False
            if pending_boundary is not None and resolve_at > _num(pending_boundary.get("at_s"), resolve_at) + simultaneous_window_s:
                boundary_at = _num(pending_boundary.get("at_s"), resolve_at)
                committed_candidates = []
                for candidate_key, candidate in pending.items():
                    candidate_kind = str(candidate.get("kind", ""))
                    projectile_committed = bool(
                        candidate_kind == "projectile_contact"
                        and _num(candidate.get("release_at_s"), 1e18) <= boundary_at + 1e-9
                    )
                    mounted_committed = bool(
                        candidate_kind == "attack"
                        and candidate.get("mounted_body_collision")
                        and _num(candidate.get("start_at_s"), 1e18) <= boundary_at + 1e-9
                    )
                    if projectile_committed or mounted_committed:
                        committed_candidates.append((candidate_key, candidate))
                if committed_candidates:
                    pending_key, action = min(
                        committed_candidates,
                        key=lambda item: (
                            _num(item[1].get("resolve_at_s")),
                            -timing[item[0]]["initiative"] if item[0] in timing else 0.0,
                            item[0],
                        ),
                    )
                    resolve_at = _num(action.get("resolve_at_s"))
                    committed_after_boundary = True
                else:
                    boundary = pending_boundary
                    break
            committed_projectile = bool(
                str(action.get("kind", "")) == "projectile_contact"
                and _num(action.get("release_at_s"), 1e18) <= phase_horizon_seconds + 1e-9
            )
            committed_momentum = bool(
                str(action.get("kind", "")) == "attack"
                and action.get("mounted_body_collision")
                and _num(action.get("start_at_s"), 1e18) <= phase_horizon_seconds + 1e-9
            )
            if resolve_at > phase_horizon_seconds and not committed_projectile and not committed_momentum:
                break
            advance_physiology(resolve_at)
            pending.pop(pending_key, None)
            actor_ref = str(action.get("actor_ref", pending_key))
            resolved_time = max(resolved_time, resolve_at)
            target_ref = str(action.get("target_ref"))
            if target_ref not in people:
                continue
            # Committed projectiles remain physical after release even if their
            # shooter is subsequently incapacitated.  Actions that have not yet
            # reached release/contact collapse with the actor instead.
            actor_combat_state = people[actor_ref].get("combat_state") if isinstance(people[actor_ref].get("combat_state"), Mapping) else {}
            incapacitated_at_s = _num(actor_combat_state.get("incapacitated_at_s"), -999.0)
            survives_incapacitation = committed_action_survives_incapacitation(
                action, incapacitated_at_s=incapacitated_at_s, resolve_at_s=resolve_at, simultaneous_window_s=simultaneous_window_s
            )
            simultaneous_committed_attack = bool(action.get("kind") == "attack" and not action.get("mounted_body_collision") and survives_incapacitation)
            committed_mounted_momentum = bool(action.get("kind") == "attack" and action.get("mounted_body_collision") and survives_incapacitation)
            actor_posture = str(body_state.get(actor_ref, {}).get("posture", "standing"))
            fall_started_at = _num(body_state.get(actor_ref, {}).get("fall_started_at_s"), -999.0)
            fall_interrupt = bool(
                action.get("kind") in {"attack", "movement", "grapple_attempt", "grapple_hold", "grapple_escape", "grapple_throw"}
                and actor_posture in {"falling", "prone", "knocked_down"}
                and fall_started_at > -900.0
                and resolve_at - fall_started_at > simultaneous_window_s
            )
            if fall_interrupt:
                trace.append({
                    "id": action["id"] + "_collapsed", "kind": "action_interrupted",
                    "actor_ref": actor_ref, "target_ref": target_ref, "action_kind": action.get("kind"),
                    "reason": "balance lost before physical contact; fall/ground state occupies the body",
                    "at_s": round(resolve_at, 3),
                })
                must_render.append(action["id"] + "_collapsed")
                ready_at[actor_ref] = max(float(ready_at.get(actor_ref, 0.0)), _num(body_state[actor_ref].get("earliest_get_up_at_s"), resolve_at))
                schedule(actor_ref)
                continue
            if not active(actor_ref) and not survives_incapacitation:
                trace.append({
                    "id": action["id"] + "_collapsed",
                    "kind": "action_interrupted",
                    "actor_ref": actor_ref,
                    "target_ref": target_ref,
                    "action_kind": action.get("kind"),
                    "reason": "actor incapacitated before physical release/contact",
                    "at_s": round(resolve_at, 3),
                })
                must_render.append(action["id"] + "_collapsed")
                continue
            if action.get("kind") == "projectile_contact":
                intended_target_ref = str(action.get("intended_target_ref", target_ref))
                ox = _num(action.get("trajectory_origin_x_m")); oy = _num(action.get("trajectory_origin_y_m"))
                ux = _num(action.get("trajectory_direction_x"), 1.0); uy = _num(action.get("trajectory_direction_y"), 0.0)
                length = max(0.01, _num(action.get("trajectory_length_m"), _num(action.get("release_distance_m"), 1.0)))
                end_x, end_y = ox + ux * length, oy + uy * length
                obstacle = obstacle_on_path(ox, oy, end_x, end_y, radius_m=max(0.0, _num(action.get("trajectory_lane_half_width_m"), 0.01)))
                projectile_exclusions = [actor_ref]
                extra_exclusions = action.get("trajectory_exclude_refs", [])
                if isinstance(extra_exclusions, (list, tuple, set)):
                    projectile_exclusions.extend(str(ref) for ref in extra_exclusions if str(ref))
                body_hits = body_intersections_on_segment(
                    (ox, oy), (end_x, end_y), geometry_positions(resolve_at),
                    exclude_refs=tuple(dict.fromkeys(projectile_exclusions)),
                    half_width_m=max(0.0, _num(action.get("trajectory_lane_half_width_m"), 0.01)),
                    elevation_start_m=_num(action.get("trajectory_origin_elevation_m"), 1.35),
                    elevation_end_m=_num(action.get("trajectory_target_elevation_m"), 1.05),
                    vertical_tolerance_m=0.12,
                )
                first_body_t = float(body_hits[0].get("t", 1.0)) if body_hits else None
                obstacle_t = float(obstacle.get("path_t", 1.0)) if isinstance(obstacle, Mapping) else None
                if obstacle is not None and (first_body_t is None or obstacle_t <= first_body_t + 1e-9):
                    # A released projectile is still a real attack even when a
                    # wall ends its lane before any body contact. A wall behind
                    # the first contacted body is not allowed to block backward
                    # in time.
                    attack_event = {
                        "id": action["id"] + "_attack", "kind": "attack",
                        "actor_ref": actor_ref, "target_ref": intended_target_ref,
                        "weapon_id": action.get("ranged_weapon_id"),
                        "projectile_item_id": action.get("ammunition_item_id"),
                        "projectile_flight": dict(action.get("projectile_flight", {})) if isinstance(action.get("projectile_flight"), Mapping) else None,
                        "range_legal": False, "path_blocked_by": dict(obstacle),
                        "contact_at_s": round(resolve_at, 3),
                        "contact_at_ms": int(round(resolve_at * 1000)),
                        "result": "obstructed_before_body_contact",
                    }
                    trace.append(attack_event); must_render.append(attack_event["id"])
                    event = {
                        "id": action["id"] + "_obstructed", "kind": "projectile_obstruction",
                        "actor_ref": actor_ref, "target_ref": intended_target_ref,
                        "projectile_item_id": action.get("ammunition_item_id"),
                        "obstacle": dict(obstacle),
                        "trajectory_origin": {"x_m": round(ox, 4), "y_m": round(oy, 4)},
                        "trajectory_end": {"x_m": round(end_x, 4), "y_m": round(end_y, 4)},
                        "at_s": round(resolve_at, 3),
                    }
                    trace.append(event); must_render.append(event["id"])
                    continue
                if not body_hits:
                    event = {
                        "id": action["id"] + "_lane_miss", "kind": "projectile_miss",
                        "actor_ref": actor_ref, "target_ref": intended_target_ref,
                        "projectile_item_id": action.get("ammunition_item_id"),
                        "reason": "no combatant occupied the fixed post-release trajectory",
                        "trajectory_origin": {"x_m": round(ox, 4), "y_m": round(oy, 4)},
                        "trajectory_end": {"x_m": round(end_x, 4), "y_m": round(end_y, 4)},
                        "at_s": round(resolve_at, 3),
                    }
                    trace.append(event); must_render.append(event["id"])
                    continue
                first_hit = body_hits[0]
                target_ref = str(first_hit["ref"])
                action["target_ref"] = target_ref
                action["trajectory_first_body"] = dict(first_hit)
                action["intended_target_ref"] = intended_target_ref
                if target_ref != intended_target_ref:
                    event = {
                        "id": action["id"] + "_intercepted", "kind": "projectile_lane_interception",
                        "actor_ref": actor_ref, "intended_target_ref": intended_target_ref,
                        "target_ref": target_ref, "friendly_fire": (target_ref in (player_side if actor_ref in player_side else hostile_side)),
                        "centerline_offset_m": first_hit.get("centerline_offset_m"),
                        "distance_along_m": first_hit.get("distance_along_m"),
                        "at_s": round(resolve_at, 3),
                    }
                    trace.append(event); must_render.append(event["id"])

            actor_eq = equipment[actor_ref]
            target_eq = equipment[target_ref]
            actor_ctrl = controls[actor_ref]
            target_ctrl = controls[target_ref]
            actor_profile = timing[actor_ref]
            target_profile = timing[target_ref]

            if action["kind"] == "guard_wait":
                event = {
                    "id": action["id"] + "_wait", "kind": "action_wait",
                    "actor_ref": actor_ref, "target_ref": target_ref,
                    "reason": str(action.get("reason", "no_lawful_action")),
                    "start_at_s": round(_num(action.get("start_at_s")), 3),
                    "complete_at_s": round(resolve_at, 3),
                }
                trace.append(event); may_compress.append(event["id"])
                ready_at[actor_ref] = _num(action.get("recovery_complete_at_s"), resolve_at)
                schedule(actor_ref)
                continue

            if action["kind"] == "status_recovery":
                status = str(action.get("status", "status"))
                cstate = people[actor_ref].setdefault("combat_state", {})
                if status == "stunned" and _num(cstate.get("stunned_until_s"), 0.0) <= resolve_at + 1e-9:
                    cstate.pop("stunned_until_s", None)
                event = {
                    "id": action["id"] + "_status_recovery", "kind": "status_state",
                    "actor_ref": actor_ref, "status": status, "action": "recovered",
                    "start_at_s": round(_num(action.get("start_at_s")), 3),
                    "complete_at_s": round(resolve_at, 3),
                }
                trace.append(event); may_compress.append(event["id"])
                ready_at[actor_ref] = resolve_at
                schedule(actor_ref)
                continue

            if action["kind"] == "weapon_extraction":
                cstate=people[actor_ref].setdefault("combat_state", {})
                embedded=cstate.get("embedded_weapon") if isinstance(cstate.get("embedded_weapon"), Mapping) else {}
                item_id=str(action.get("item_id", ""))
                if embedded and str(embedded.get("item_id", ""))==item_id:
                    cstate.pop("embedded_weapon", None); body_state[actor_ref].pop("embedded_weapon", None)
                    equipment[actor_ref]=self._personal_equipment_profile(actor_ref, people[actor_ref])
                    apply_transient_player_prop(actor_ref)
                    controls[actor_ref]=self._personal_controls(people[actor_ref], equipment[actor_ref], effects)
                    timing[actor_ref]=self._personal_timing_profile(people[actor_ref], equipment[actor_ref], controls[actor_ref], effects)
                action_exertion[actor_ref]+=0.22
                extraction_event={"id":action["id"]+"_extraction","kind":"equipment_state","actor_ref":actor_ref,"target_ref":target_ref,"action":"weapon_extracted","item_id":item_id,"target_structure":action.get("target_structure"),"start_at_s":round(_num(action.get("start_at_s")),3),"complete_at_s":round(resolve_at,3),"recovery_complete_at_s":round(_num(action.get("recovery_complete_at_s"),resolve_at),3)}
                trace.append(extraction_event); must_render.append(extraction_event["id"])
                ready_at[actor_ref]=_num(action.get("recovery_complete_at_s"),resolve_at)
                for ref in actors: schedule(ref)
                continue

            if action["kind"] == "posture_fall":
                ground_at = resolve_at
                body_state[actor_ref]["posture"] = "prone"
                body_state[actor_ref]["balance"] = min(_num(body_state[actor_ref].get("balance"), 1.0), 0.38)
                earliest = max(ground_at, _num(action.get("earliest_recovery_at_s"), ground_at))
                body_state[actor_ref]["foot_commit_until_s"] = max(_num(body_state[actor_ref].get("foot_commit_until_s"), 0.0), earliest)
                cstate = people[actor_ref].setdefault("combat_state", {})
                cstate["posture"] = "prone"
                cstate["ground_contact_at_s"] = round(ground_at, 6)
                cstate["earliest_get_up_at_s"] = round(earliest, 6)
                event = {
                    "id": action["id"] + "_ground", "kind": "posture_state",
                    "actor_ref": actor_ref, "action": "ground_contact",
                    "from_posture": "falling", "to_posture": "prone",
                    "fall_started_at_s": round(_num(action.get("start_at_s")), 3),
                    "ground_contact_at_s": round(ground_at, 3),
                    "earliest_get_up_at_s": round(earliest, 3),
                }
                trace.append(event); must_render.append(event["id"])
                ready_at[actor_ref] = earliest
                schedule(actor_ref)
                continue

            if action["kind"] == "posture_recovery":
                from_posture = str(action.get("from_posture", body_state[actor_ref].get("posture", "knocked_down")))
                body_state[actor_ref]["posture"] = "standing"
                body_state[actor_ref]["balance"] = max(0.75, _num(body_state[actor_ref].get("balance"), 1.0))
                body_state[actor_ref]["foot_commit_until_s"] = max(
                    _num(body_state[actor_ref].get("foot_commit_until_s"), 0.0),
                    _num(action.get("recovery_complete_at_s"), resolve_at),
                )
                people[actor_ref].setdefault("combat_state", {})["posture"] = "standing"
                posture_exertion = _num(posture_timing.get("get_up_exertion"), 0.55)
                action_exertion[actor_ref] += posture_exertion * (0.55 if from_posture == "kneeling" else 1.0)
                posture_event = {
                    "id": action["id"] + "_posture",
                    "kind": "posture_recovery",
                    "actor_ref": actor_ref,
                    "action": "recover_to_standing",
                    "from_posture": from_posture,
                    "to_posture": "standing",
                    "start_at_s": round(_num(action.get("start_at_s")), 3),
                    "complete_at_s": round(resolve_at, 3),
                    "recovery_complete_at_s": round(_num(action.get("recovery_complete_at_s")), 3),
                    "exertion_factor": action.get("scheduled_exertion_factor"),
                }
                trace.append(posture_event)
                must_render.append(posture_event["id"])
                ready_at[actor_ref] = _num(action.get("recovery_complete_at_s"), resolve_at)
                schedule(actor_ref)
                continue

            if action["kind"] in {"grapple_attempt","grapple_hold","grapple_escape","grapple_throw","grapple_release"}:
                kind=str(action["kind"]); partner=target_ref
                a_score=grapple_score(actor_ref); d_score=grapple_score(partner)
                margin=a_score-d_score+jitter(int(action.get("sequence",0)),3)
                result="failed"; changed=False
                if kind=="grapple_release":
                    clear_grapple(actor_ref,partner); result="released"; changed=True
                elif kind=="grapple_attempt":
                    threshold=_num(grapple_model.get("control_margin_for_hold"),4.0)
                    if margin>=threshold:
                        bind_grapple(actor_ref,partner,resolve_at); result="hold_established"; changed=True
                        if bool(action.get("follow_throw")) and margin>=_num(grapple_model.get("control_margin_for_throw"),16.0):
                            result="throw_established"
                            # Carry the controlled body away from the controller's center line, then start a real fall.
                            ax,ay=position_at(actor_ref,resolve_at); tx,ty=position_at(partner,resolve_at); dx=tx-ax; dy=ty-ay; mag=max(1e-6,math.hypot(dx,dy)); disp=max(0.25,_num(grapple_model.get("throw_displacement_m"),0.75)); positions[partner]["x_m"]=tx+dx/mag*disp; positions[partner]["y_m"]=ty+dy/mag*disp; clear_grapple(actor_ref,partner); begin_fall(partner,severity="moderate",at_s=resolve_at,reason="grapple_throw",source_event_id=action["id"])
                elif kind=="grapple_escape":
                    controller=partner; escape_margin=_num(grapple_model.get("escape_margin"),2.0)
                    if margin>=escape_margin:
                        clear_grapple(actor_ref,controller); result="escaped"; changed=True
                    else:
                        result="held"
                elif kind=="grapple_throw":
                    if body_state[actor_ref].get("grapple_role")=="controller" and body_state[actor_ref].get("grappled_with")==partner and margin>=_num(grapple_model.get("control_margin_for_throw"),16.0):
                        ax,ay=position_at(actor_ref,resolve_at); tx,ty=position_at(partner,resolve_at); dx=tx-ax; dy=ty-ay; mag=max(1e-6,math.hypot(dx,dy)); disp=max(0.25,_num(grapple_model.get("throw_displacement_m"),0.75)); positions[partner]["x_m"]=tx+dx/mag*disp; positions[partner]["y_m"]=ty+dy/mag*disp; clear_grapple(actor_ref,partner); begin_fall(partner,severity="moderate",at_s=resolve_at,reason="grapple_throw",source_event_id=action["id"]); result="thrown"; changed=True
                    else:
                        result="throw_resisted"
                else:
                    if body_state[actor_ref].get("grapple_role")=="controller" and body_state[actor_ref].get("grappled_with")==partner:
                        result="hold_maintained"; changed=True
                    else:
                        result="hold_lost"; clear_grapple(actor_ref,partner)
                occupied_until=_num(action.get("recovery_complete_at_s"),resolve_at)
                defense_ready_at[actor_ref]=max(defense_ready_at[actor_ref],occupied_until); weapon_guard_ready_at[actor_ref]=max(weapon_guard_ready_at[actor_ref],occupied_until); shield_guard_ready_at[actor_ref]=max(shield_guard_ready_at[actor_ref],occupied_until)
                if partner in defense_ready_at and body_state.get(actor_ref,{}).get("grappled_with")==partner:
                    defense_ready_at[partner]=max(defense_ready_at[partner],occupied_until); weapon_guard_ready_at[partner]=max(weapon_guard_ready_at[partner],occupied_until); shield_guard_ready_at[partner]=max(shield_guard_ready_at[partner],occupied_until)
                action_exertion[actor_ref]+=0.48 if kind in {"grapple_attempt","grapple_escape","grapple_throw"} else 0.24
                event={"id":action["id"]+"_grapple","kind":"grapple_state","actor_ref":actor_ref,"target_ref":partner,"action":kind,"result":result,"control_margin":round(margin,3),"body_occupied":bool(body_state.get(actor_ref,{}).get("grappled_with")),"start_at_s":round(_num(action.get("start_at_s")),3),"at_s":round(resolve_at,3),"recovery_complete_at_s":round(occupied_until,3)}
                trace.append(event); must_render.append(event["id"]); ready_at[actor_ref]=occupied_until
                if actor_ref==self.PLAYER_ACTOR and action.get("declared_intent"):
                    settle_combo_link("completed" if result not in {"failed","throw_resisted","held"} else "failed",event["id"])
                for ref in actors: schedule(ref)
                continue

            if action["kind"] == "projectile_release":
                ammo_id = str(action.get("ammunition_item_id", ""))
                if not ammo_id or projectile_ammunition.get(actor_ref, {}).get(ammo_id, 0) <= 0:
                    ready_at[actor_ref] = _num(action.get("recovery_complete_at_s"), resolve_at)
                    schedule(actor_ref)
                    continue
                projectile_ammunition[actor_ref][ammo_id] -= 1
                release_exertion_factor = transient_exertion_factor(actor_ref)
                family = str((actor_eq.get("ranged_weapon", {}) if isinstance(actor_eq.get("ranged_weapon"), Mapping) else {}).get("family", "")).lower()
                action_exertion[actor_ref] += 0.55 if family == "bow" else 0.32
                people[actor_ref].setdefault("combat_state", {}).setdefault("projectile_ammunition", {})[ammo_id] = projectile_ammunition[actor_ref][ammo_id]
                flight = dict(action.get("projectile_flight", {}))
                contact_at = resolve_at + max(0.0, _num(flight.get("flight_time_seconds"), 0.0))
                release_x, release_y = position_at(actor_ref, resolve_at)
                target_x, target_y = position_at(target_ref, resolve_at)
                traj_dx, traj_dy = target_x - release_x, target_y - release_y
                traj_mag = max(1e-6, math.hypot(traj_dx, traj_dy))
                traj_ux, traj_uy = traj_dx / traj_mag, traj_dy / traj_mag
                projectile_width = max(0.01, _num((actor_eq.get("ammunition_item", {}) if isinstance(actor_eq.get("ammunition_item"), Mapping) else {}).get("diameter_m"), 0.02))
                release_event = {
                    "id": action["id"] + "_release", "kind": "projectile_release",
                    "actor_ref": actor_ref, "target_ref": target_ref,
                    "weapon_id": action.get("ranged_weapon_id"), "projectile_item_id": ammo_id,
                    "aim_zone": action.get("aim_zone"), "aim_side": action.get("aim_side"),
                    "aim_structure": action.get("aim_structure"), "aim_purpose": action.get("aim_purpose"),
                    "distance_m": round(_num(action.get("release_distance_m")), 3),
                    "launch_power_index": flight.get("launch_power_index"),
                    "launch_velocity_mps": flight.get("launch_velocity_mps"),
                    "flight_time_seconds": flight.get("flight_time_seconds"),
                    "mechanism_sets_launch_power": flight.get("mechanism_sets_launch_power"),
                    "release_at_s": round(resolve_at, 3), "expected_contact_at_s": round(contact_at, 3),
                    "trajectory_origin": {"x_m": round(release_x, 4), "y_m": round(release_y, 4), "elevation_m": round(_num(positions[actor_ref].get("elevation_m"), 0.0) + 1.35, 4)},
                    "trajectory_target_at_release": {"x_m": round(target_x, 4), "y_m": round(target_y, 4), "elevation_m": round(_num(positions[target_ref].get("elevation_m"), 0.0) + 1.05, 4)},
                    "trajectory_direction_xy": {"x": round(traj_ux, 6), "y": round(traj_uy, 6)},
                    "trajectory_lane_width_m": round(projectile_width, 4),
                    "unsafe_lane_at_schedule": action.get("unsafe_lane_at_schedule"),
                }
                trace.append(release_event); must_render.append(release_event["id"])
                fired_projectiles.append({"actor_ref": actor_ref, "projectile_item_id": ammo_id, "recovery_base": flight.get("projectile_recovery_base", 0.0), "release_event_id": release_event["id"]})
                flight_key = "flight:" + str(action["id"])
                pending[flight_key] = dict(
                    action,
                    kind="projectile_contact",
                    resolve_at_s=contact_at,
                    release_at_s=resolve_at,
                    release_exertion_factor=round(release_exertion_factor, 6),
                    intended_target_ref=target_ref,
                    trajectory_origin_x_m=release_x,
                    trajectory_origin_y_m=release_y,
                    trajectory_origin_elevation_m=_num(positions[actor_ref].get("elevation_m"), 0.0) + 1.35,
                    trajectory_direction_x=traj_ux,
                    trajectory_direction_y=traj_uy,
                    trajectory_length_m=traj_mag + max(0.35, actor_clearance_radius(target_ref)),
                    trajectory_target_elevation_m=_num(positions[target_ref].get("elevation_m"), 0.0) + 1.05,
                    trajectory_lane_half_width_m=projectile_width / 2.0,
                )
                ready_at[actor_ref] = _num(action.get("recovery_complete_at_s"), resolve_at)
                schedule(actor_ref)
                continue

            if action["kind"] == "movement":
                before = distance_between(actor_ref, target_ref, _num(action.get("start_at_s")))
                from_x = _num(action.get("from_x_m"), positions[actor_ref]["x_m"])
                from_y = _num(action.get("from_y_m"), positions[actor_ref]["y_m"])
                positions[actor_ref]["x_m"] = _num(action.get("to_x_m"), positions[actor_ref]["x_m"])
                positions[actor_ref]["y_m"] = _num(action.get("to_y_m"), positions[actor_ref]["y_m"])
                movement_dt = max(0.01, resolve_at - _num(action.get("start_at_s"), resolve_at))
                body_state[actor_ref]["movement_velocity_xy_mps"] = (
                    round((positions[actor_ref]["x_m"] - from_x) / movement_dt, 6),
                    round((positions[actor_ref]["y_m"] - from_y) / movement_dt, 6),
                )
                body_state[actor_ref]["movement_velocity_until_s"] = resolve_at + min(0.60, max(0.12, timing[actor_ref]["movement_recovery_seconds"]))
                positions[actor_ref]["facing_deg"] = bearing(actor_ref, target_ref, resolve_at)
                body_state[actor_ref]["facing_deg"] = positions[actor_ref]["facing_deg"]
                body_state[actor_ref]["guard_center_deg"] = positions[actor_ref]["facing_deg"]
                body_state[actor_ref]["weapon_center_deg"] = positions[actor_ref]["facing_deg"]
                body_state[actor_ref]["shield_center_deg"] = positions[actor_ref]["facing_deg"]
                body_state[actor_ref]["foot_commit_until_s"] = max(
                    _num(body_state[actor_ref].get("foot_commit_until_s")),
                    _num(action.get("recovery_complete_at_s")),
                )
                burden_now = equipment[actor_ref].get("burden", {}) if isinstance(equipment[actor_ref].get("burden"), Mapping) else {}
                action_exertion[actor_ref] += max(0.08, abs(_num(action.get("distance_delta_m"))) * 1.35) * _num(burden_now.get("fatigue_multiplier"), 1.0)
                after = distance_between(actor_ref, target_ref, resolve_at)
                event = {
                    "id": action["id"] + "_movement",
                    "kind": "movement",
                    "actor_ref": actor_ref,
                    "action": action.get("action"),
                    "declared_intent": action.get("declared_intent"),
                    "from_distance_m": round(_num(action.get("from_distance_m"), before), 2),
                    "to_distance_m": round(after, 2),
                    "from_position": {"x_m": round(_num(action.get("from_x_m")), 3), "y_m": round(_num(action.get("from_y_m")), 3)},
                    "to_position": {"x_m": round(positions[actor_ref]["x_m"], 3), "y_m": round(positions[actor_ref]["y_m"], 3)},
                    "movement_blocked_by": action.get("movement_blocked_by"),
                    "start_at_s": round(_num(action.get("start_at_s")), 3),
                    "complete_at_s": round(resolve_at, 3),
                    "recovery_complete_at_s": round(_num(action.get("recovery_complete_at_s")), 3),
                }
                trace.append(event)
                must_render.append(event["id"])
                ready_at[actor_ref] = _num(action.get("recovery_complete_at_s"))
                if actor_ref == self.PLAYER_ACTOR and action.get("consume_intent"):
                    settle_combo_link("completed", event["id"])
                for ref in actors:
                    schedule(ref)
                continue

            is_projectile = action.get("kind") == "projectile_contact"
            if resolve_at - contact_group_anchor > simultaneous_window_s:
                contact_group_serial += 1
                contact_group_anchor = resolve_at
                contact_group_positions = {ref: position_at(ref, resolve_at) for ref in actors}
                contact_group_body = {ref: dict(body_state[ref]) for ref in actors}

            contact_group_id = f"contact_group_{contact_group_serial:04d}"

            def group_distance(ref_a: str, ref_b: str) -> float:
                ax, ay = contact_group_positions.get(ref_a, position_at(ref_a, resolve_at))
                bx, by = contact_group_positions.get(ref_b, position_at(ref_b, resolve_at))
                return _clamp(math.hypot(bx - ax, by - ay), 0.05, 400.0)

            def group_bearing(ref_a: str, ref_b: str) -> float:
                ax, ay = contact_group_positions.get(ref_a, position_at(ref_a, resolve_at))
                bx, by = contact_group_positions.get(ref_b, position_at(ref_b, resolve_at))
                return math.degrees(math.atan2(by - ay, bx - ax)) % 360.0

            actor_weapon = (actor_eq.get("ranged_weapon", {}) if is_projectile else actor_eq.get("weapon", {}))
            actor_weapon = actor_weapon if isinstance(actor_weapon, Mapping) else {}
            target_weapon = target_eq.get("weapon", {}) if isinstance(target_eq.get("weapon"), Mapping) else {}
            a_reach = max(0.08, _num(action.get("committed_reach_m"), _num(actor_weapon.get("reach_m"), 0.44)))
            a_min = max(0.0, _num(action.get("committed_minimum_range_m"), _num(actor_weapon.get("minimum_range_m"), 0.0)))
            d_reach = max(0.08, _num(target_weapon.get("reach_m"), 0.44))
            combat_distance = group_distance(actor_ref, target_ref)
            target_radius_at_contact = actor_clearance_radius(target_ref)
            combat_gap = max(0.0, combat_distance - target_radius_at_contact)
            declared_intent = action.get("declared_intent") if actor_ref == self.PLAYER_ACTOR else None
            intent_lower = str(declared_intent or "").lower()
            if is_projectile:
                # After release the projectile owns a fixed physical lane. The
                # shooter's later position is irrelevant to contact distance or
                # incoming direction.
                lane_hit = action.get("trajectory_first_body", {}) if isinstance(action.get("trajectory_first_body"), Mapping) else {}
                combat_distance = max(0.0, _num(lane_hit.get("distance_along_m"), _num(action.get("release_distance_m"), combat_distance)))
                combat_gap = max(0.0, combat_distance - target_radius_at_contact)
                direction_deg = math.degrees(math.atan2(_num(action.get("trajectory_direction_y"), 0.0), _num(action.get("trajectory_direction_x"), 1.0))) % 360.0
                incoming_bearing = (direction_deg + 180.0) % 360.0
            else:
                incoming_bearing = group_bearing(target_ref, actor_ref)
            defense_method, defense_control = self._personal_defense_method(target_eq, target_ctrl, combat_gap)
            pre_body = contact_group_body.get(target_ref, body_state[target_ref])
            defender_facing = _num(pre_body.get("facing_deg"), positions[target_ref].get("facing_deg", 0.0)) % 360.0
            facing_delta = angle_delta(incoming_bearing, defender_facing)
            awareness_arc_factor = 1.0 if facing_delta <= 80.0 else (0.86 if facing_delta <= 125.0 else (0.67 if facing_delta <= 160.0 else 0.52))
            shield_geometry_reachable = False
            shield_arc_delta = 180.0
            if target_eq.get("loadout", {}).get("shield"):
                sid = target_eq.get("loadout", {}).get("shield")
                srec = self._combat_weapon(sid) if sid and hasattr(self, "_combat_weapon") else {}
                scenter = _num(pre_body.get("shield_center_deg"), defender_facing) % 360.0
                shield_arc_delta = angle_delta(incoming_bearing, scenter)
                sarc = max(35.0, _num(srec.get("coverage_arc_degrees"), 90.0))
                shield_geometry_reachable = shield_arc_delta <= min(150.0, sarc * 0.5 + 34.0)
            weapon_center = _num(pre_body.get("weapon_center_deg"), defender_facing) % 360.0
            weapon_arc_delta = angle_delta(incoming_bearing, weapon_center)
            parry_geometry_reachable = weapon_arc_delta <= 150.0

            actor_constraints = status_constraints(actor_ref, resolve_at)
            target_constraints = status_constraints(target_ref, resolve_at)
            detection_positions = geometry_positions(resolve_at)
            if is_projectile:
                attack_origin = {
                    "x_m": _num(action.get("trajectory_origin_x_m"), detection_positions.get(actor_ref, {}).get("x_m", 0.0)),
                    "y_m": _num(action.get("trajectory_origin_y_m"), detection_positions.get(actor_ref, {}).get("y_m", 0.0)),
                    "elevation_m": _num(action.get("trajectory_origin_elevation_m"), detection_positions.get(actor_ref, {}).get("elevation_m", 0.0)),
                }
                los = line_of_sight_to_point(target_ref, attack_origin, detection_positions, local_obstacles, exclude_refs=(actor_ref,))
                # Detection bearing must also use the release origin, not where
                # the shooter happens to stand later in the flight.
                detection_positions = dict(detection_positions)
                detection_positions[actor_ref] = {**detection_positions.get(actor_ref, {}), **attack_origin}
            else:
                los = line_of_sight_query(target_ref, actor_ref, detection_positions, local_obstacles)
            detection = attack_detection_assessment(
                target_ref, actor_ref, controls=controls, positions=detection_positions,
                facing_deg=defender_facing, reaction_seconds=target_profile["reaction_seconds"],
                contact_at_s=resolve_at, attack_start_at_s=_num(action.get("start_at_s"), resolve_at),
                awareness_factor=_num(target_constraints.get("awareness_factor"), 1.0),
                visual_factor=_num(target_constraints.get("visual_detection_factor"), 1.0) * _num(los.get("visibility_factor"), 1.0),
                concealment_factor=0.72 if bool(action.get("concealed_start")) else 1.0,
                attention_factor=max(0.25, 1.0 - 0.34 * _clamp(_num(body_state[target_ref].get("active_defense_load"), 0.0), 0.0, 1.0)),
            )
            detection_event = {
                "id": action["id"] + "_detection",
                "kind": "attack_detection",
                "actor_ref": target_ref,
                "target_ref": actor_ref,
                "detected": bool(detection.get("detected")),
                "meaningful_reaction": bool(detection.get("meaningful_reaction")),
                "quality": detection.get("quality"),
                "incoming_bearing_deg": detection.get("incoming_bearing_deg"),
                "facing_delta_deg": detection.get("facing_delta_deg"),
                "available_warning_seconds": detection.get("available_warning_seconds"),
                "reaction_seconds": detection.get("reaction_seconds"),
                "line_of_sight_clear": bool(los.get("clear")),
                "line_of_sight_reason": los.get("reason"),
                "body_screen_refs": list(los.get("body_screen_refs", [])) if isinstance(los.get("body_screen_refs"), list) else [],
                "static_blocker": los.get("static_blocker"),
                "at_s": round(resolve_at, 3),
            }
            trace.append(detection_event)
            if not detection.get("detected") or facing_delta > 125.0:
                must_render.append(detection_event["id"])
            else:
                may_compress.append(detection_event["id"])

            defensive_plan = active_guard.get(target_ref)
            if defensive_plan is None and target_ref == self.PLAYER_ACTOR and defensive_intent(current_intent()):
                defensive_plan = current_intent()
                if defensive_plan:
                    active_guard[target_ref] = defensive_plan
            defensive_lower = str(defensive_plan or "").lower()

            # Build only physically lawful responses from the current exact body
            # state. A pre-declared guard can remain meaningful even when a new
            # attack was not freshly perceived; otherwise insufficient detection
            # suppresses active evasions/parries rather than granting a generic
            # defense score.
            legal_methods: list[str] = []
            if detection.get("meaningful_reaction") or defensive_plan:
                if _num(target_constraints.get("movement_factor"), 1.0) > 0.05:
                    legal_methods.extend(["dodge", "reposition"])
                if target_eq.get("loadout", {}).get("shield") and shield_geometry_reachable:
                    legal_methods.append("block")
                target_weapon_id_for_defense = str(target_eq.get("best_weapon") or "")
                target_weapon_family = str(target_weapon.get("family", "")).lower()
                weapon_intercept_capable = bool(target_weapon_id_for_defense) and target_weapon_family != "unarmed" and parry_geometry_reachable
                if is_projectile and weapon_intercept_capable:
                    # A projectile already owns a fixed lane. A melee weapon may
                    # intercept that lane without the shooter's body being inside
                    # melee reach, but only through the projectile-specific timing,
                    # speed, guard-arc and handling resolution below.
                    legal_methods.append("deflect")
                elif (not is_projectile) and parry_geometry_reachable and _num(target_weapon.get("minimum_range_m"), 0.0) <= combat_gap <= d_reach + 0.35:
                    legal_methods.extend(["parry", "deflect"])
                    # Counter-interception is a timing/geometry defense: the
                    # defender must actually be able to reach the incoming body
                    # or weapon path before contact.
                    if combat_gap <= d_reach + 0.12 and not target_constraints.get("restrained"):
                        legal_methods.append("counter_intercept")
                legal_methods.append("brace")
            elif defensive_plan:
                legal_methods.append("brace")

            if not legal_methods:
                defense_method = "none"
                defense_control = 0.0
            else:
                pressure = surrounding_pressure(
                    target_ref,
                    [r for r in (hostile_side if target_ref in player_side else player_side) if active(r)],
                    geometry_positions(resolve_at),
                )
                preferences = physical_defense_preferences(
                    target_ref, actor_ref, people=people, equipment=equipment, controls=controls,
                    positions=geometry_positions(resolve_at), legal_methods=legal_methods,
                    detection_quality=_num(detection.get("quality"), 0.0),
                    surrounded=bool(pressure.get("surrounded")),
                    incoming_angle_from_facing_deg=facing_delta, projectile=is_projectile,
                )
                recent_target = action_memory[target_ref][-4:]
                adjusted_defenses: list[tuple[str, float]] = []
                for method in legal_methods:
                    base_control = _num(preferences.get(method), 0.0)
                    repeated = sum(1 for row in recent_target[-2:] if str(row.get("defense_method", "")) == method)
                    failed = sum(
                        1 for row in recent_target
                        if str(row.get("defense_method", "")) == method
                        and str(row.get("defense_result", "")) in {"late_or_beaten", "penetrated", "failed"}
                    )
                    directional_factor = awareness_arc_factor
                    if method == "block":
                        shield_delta = angle_delta(incoming_bearing, _num(pre_body.get("shield_center_deg"), defender_facing) % 360.0)
                        directional_factor *= 1.0 if shield_delta <= 58.0 else max(0.12, 1.0 - (shield_delta - 58.0) / 135.0)
                    elif method in {"parry", "deflect", "counter_intercept"}:
                        weapon_delta = angle_delta(incoming_bearing, _num(pre_body.get("weapon_center_deg"), defender_facing) % 360.0)
                        directional_factor *= 1.0 if weapon_delta <= 88.0 else max(0.18, 1.0 - (weapon_delta - 88.0) / 150.0)
                    elif method in {"dodge", "reposition"} and resolve_at < _num(body_state[target_ref].get("foot_commit_until_s"), 0.0):
                        directional_factor *= 0.62
                    adjusted_defenses.append((method, (base_control - 4.0 * repeated - 6.0 * failed) * directional_factor))
                defense_method, defense_control = max(adjusted_defenses, key=lambda row: row[1])

            if defensive_plan:
                requested_method = None
                for token, method in (
                    ("counter", "counter_intercept"), ("intercept", "counter_intercept"),
                    ("deflect", "deflect"), ("brace", "brace"),
                    ("parry", "parry"), ("block", "block"),
                    ("reposition", "reposition"), ("dodge", "dodge"), ("evade", "dodge"),
                ):
                    if token in defensive_lower:
                        requested_method = method
                        break
                if requested_method in legal_methods:
                    defense_method = requested_method
                    if requested_method in {"parry", "deflect"}:
                        defense_control = _num(target_ctrl.get("parry"), defense_control)
                    elif requested_method == "counter_intercept":
                        defense_control = max(defense_control, _num(target_ctrl.get("attack"), defense_control) * 0.92)
                    elif requested_method in {"dodge", "reposition"}:
                        defense_control = _num(target_ctrl.get("dodge"), defense_control)
                    elif requested_method == "block":
                        defense_control = _num(target_ctrl.get("block"), defense_control)

            grapple_partner_ref = body_state[target_ref].get("grappled_with")
            if grapple_partner_ref:
                if str(grapple_partner_ref) == actor_ref:
                    defense_control *= _clamp(_num(grapple_model.get("attack_defense_factor_when_grappled"),0.48),0.05,1.0)
                else:
                    third_party_key={"parry":"third_party_parry_factor","deflect":"third_party_parry_factor","counter_intercept":"third_party_parry_factor","block":"third_party_block_factor","dodge":"third_party_dodge_factor","reposition":"third_party_dodge_factor","brace":"third_party_block_factor"}.get(defense_method,"third_party_dodge_factor")
                    defense_control *= _clamp(_num(grapple_model.get(third_party_key),0.25),0.02,1.0)
            target_pending = pending.get(target_ref)
            commitment_factor = 1.0
            if isinstance(target_pending, Mapping) and _num(target_pending.get("start_at_s")) <= resolve_at < _num(target_pending.get("resolve_at_s")):
                commitment_factor = 1.35 if target_pending.get("kind") == "attack" else 1.10
            if defensive_plan:
                commitment_factor *= 0.65
            resource_ready = max(0.0, float(defense_ready_at[target_ref]))
            if defense_method in {"parry", "deflect", "counter_intercept"}:
                resource_ready = max(resource_ready, float(weapon_guard_ready_at[target_ref]))
            elif defense_method == "block":
                resource_ready = max(resource_ready, float(shield_guard_ready_at[target_ref]))
            reaction_origin = resource_ready
            if isinstance(target_pending, Mapping):
                # A committed attack/move does not erase defensive ability, but
                # it means the body must redirect from the already-started task.
                reaction_origin = max(reaction_origin, _num(target_pending.get("start_at_s"), reaction_origin))
            last_at = _num(body_state[target_ref].get("last_defense_at_s"), -999.0)
            last_angle = body_state[target_ref].get("last_defense_angle_deg")
            since_last = max(0.0, resolve_at - last_at)
            conflict_angle = angle_delta(incoming_bearing, _num(last_angle, incoming_bearing)) if last_angle is not None else 0.0

            # Cumulative whole-body active-defense load expressed through Sword's
            # continuous-time weapon/shield/body authorities. Each actual dodge,
            # parry or block consumes shared reaction bandwidth. Load decays on
            # the combat-local clock, while distinct attackers inside the same
            # recovery window add conflicting-source pressure.
            active_recovery_s = active_defense_recovery_window_seconds(target_profile, active_defense_model)
            load_last_update = _num(body_state[target_ref].get("active_defense_last_update_s"), 0.0)
            active_load = _clamp(_num(body_state[target_ref].get("active_defense_load"), 0.0), 0.0, 1.0)
            active_load = decayed_active_defense_load(
                active_load, last_update_s=load_last_update, at_s=resolve_at,
                recovery_window_s=active_recovery_s,
            )
            body_state[target_ref]["active_defense_load"] = active_load
            body_state[target_ref]["active_defense_last_update_s"] = resolve_at
            recent_sources = body_state[target_ref].get("active_defense_recent_sources")
            if not isinstance(recent_sources, dict):
                recent_sources = {}
            cutoff = resolve_at - active_recovery_s
            recent_sources = {
                str(ref): _num(seen_at)
                for ref, seen_at in recent_sources.items()
                if _num(seen_at, -999.0) >= cutoff
            }
            if active_load <= 1e-9:
                recent_sources = {}
            current_source_was_new = actor_ref not in recent_sources
            source_count = len(set(recent_sources) | {actor_ref})
            distinct_pressure = min(
                max(0.0, _num(active_defense_model.get("max_distinct_source_penalty"), 0.36)),
                max(0, source_count - 1) * max(0.0, _num(active_defense_model.get("distinct_source_penalty"), 0.12)),
            )
            minimum_available = _clamp(_num(active_defense_model.get("minimum_available_factor"), 0.08), 0.01, 1.0)
            load_factor = max(minimum_available, 1.0 - active_load - distinct_pressure)

            angle_window = max(0.01, _num(active_defense_model.get("angle_window_seconds"), 0.48))
            angle_factor = 1.0
            if since_last < angle_window:
                recovery_pressure = 1.0 - since_last / angle_window
                angular_pressure = conflict_angle / 180.0
                angle_factor = max(
                    minimum_available,
                    1.0 - recovery_pressure * (
                        max(0.0, _num(active_defense_model.get("angle_base_penalty"), 0.30))
                        + max(0.0, _num(active_defense_model.get("angle_conflict_penalty"), 0.58)) * angular_pressure
                    ),
                )
            saturation_factor = max(minimum_available, load_factor * angle_factor)
            body_state[target_ref]["active_defense_recent_sources"] = recent_sources
            balance_factor = 0.70 if resolve_at < _num(body_state[target_ref].get("foot_commit_until_s"), 0.0) else 1.0
            target_posture = str(body_state[target_ref].get("posture", "standing"))
            if target_posture == "prone":
                balance_factor *= _clamp(_num(posture_timing.get("prone_defense_factor"), 0.48), 0.05, 1.0)
            elif target_posture == "kneeling":
                balance_factor *= _clamp(_num(posture_timing.get("kneeling_defense_factor"), 0.72), 0.05, 1.0)
            elif target_posture == "knocked_down":
                balance_factor *= _clamp(_num(posture_timing.get("knocked_down_defense_factor"), 0.42), 0.05, 1.0)
            elif target_posture == "falling":
                balance_factor *= min(0.30, _clamp(_num(posture_timing.get("knocked_down_defense_factor"), 0.42), 0.05, 1.0))
            actor_exertion_factor = (
                _clamp(_num(action.get("release_exertion_factor"), 1.0), 0.52, 1.0)
                if is_projectile
                else transient_exertion_factor(actor_ref)
            )
            defender_exertion_factor = transient_exertion_factor(target_ref)
            reaction_ready = reaction_origin + (target_profile["reaction_seconds"] / defender_exertion_factor) * commitment_factor
            lateness = max(0.0, reaction_ready - resolve_at)
            reaction_window = max(0.05, (target_profile["reaction_seconds"] / defender_exertion_factor) * 2.0)
            timing_factor = 1.0 if lateness <= 1e-9 else max(0.10, 1.0 - lateness / reaction_window)
            defense_control_before_timing = defense_control
            defense_control *= (
                timing_factor * saturation_factor * balance_factor * defender_exertion_factor
                * _clamp(_num(target_constraints.get("defense_factor"), 1.0), 0.0, 1.0)
            )
            defense_attempted = defense_method != "none" and (timing_factor > 0.10 or bool(defensive_plan))

            mounted_body_collision = bool(action.get("mounted_body_collision"))
            if is_projectile:
                path_ax = _num(action.get("trajectory_origin_x_m"), 0.0)
                path_ay = _num(action.get("trajectory_origin_y_m"), 0.0)
                lane_hit = action.get("trajectory_first_body", {}) if isinstance(action.get("trajectory_first_body"), Mapping) else {}
                path_tx = _num(lane_hit.get("x_m"), contact_group_positions.get(target_ref, position_at(target_ref, resolve_at))[0])
                path_ty = _num(lane_hit.get("y_m"), contact_group_positions.get(target_ref, position_at(target_ref, resolve_at))[1])
                path_obstacle = None  # already resolved against the fixed release lane above
            else:
                path_ax,path_ay=contact_group_positions.get(actor_ref,position_at(actor_ref,resolve_at)); path_tx,path_ty=contact_group_positions.get(target_ref,position_at(target_ref,resolve_at))
                path_obstacle=obstacle_on_path(path_ax,path_ay,path_tx,path_ty,radius_m=0.025)
            reach_advantage = (a_reach - d_reach) * 5.0
            legal_range = (path_obstacle is None) and a_min <= combat_gap <= a_reach + 0.10
            melee_tracking_factor = 1.0
            melee_commitment_arc_deg = None
            melee_commitment_delta_deg = None
            melee_target_displacement_after_commit_m = None
            if (not is_projectile) and (not mounted_body_collision):
                commit_at = _clamp(_num(action.get("commit_at_s"), _num(action.get("start_at_s"), resolve_at)), _num(action.get("start_at_s"), 0.0), resolve_at)
                acx, acy = position_at(actor_ref, commit_at)
                tcx, tcy = position_at(target_ref, commit_at)
                rtx, rty = contact_group_positions.get(target_ref, position_at(target_ref, resolve_at))
                committed_bearing = math.degrees(math.atan2(tcy - acy, tcx - acx)) % 360.0
                actual_bearing = math.degrees(math.atan2(rty - acy, rtx - acx)) % 360.0
                melee_commitment_delta_deg = angle_delta(actual_bearing, committed_bearing)
                _, actor_attrs_now = _stats(people[actor_ref])
                handling = max(0.35, _num(actor_weapon.get("handling"), 1.0))
                mode_now = str(action.get("attack_mode", "")).lower()
                base_arc = {"thrust": 10.0, "cut": 24.0, "blunt": 18.0}.get(mode_now, 16.0)
                melee_commitment_arc_deg = _clamp(
                    base_arc + math.sqrt(max(0.0, _num(actor_attrs_now.get("Coordination")))) * 0.75 + (handling - 0.35) * 7.0,
                    10.0,
                    38.0,
                )
                melee_target_displacement_after_commit_m = math.hypot(rtx - tcx, rty - tcy)
                if melee_commitment_delta_deg > melee_commitment_arc_deg:
                    overflow = melee_commitment_delta_deg - melee_commitment_arc_deg
                    melee_tracking_factor = max(0.0, 1.0 - overflow / max(8.0, melee_commitment_arc_deg * 0.65))
                    if melee_tracking_factor <= 0.15:
                        legal_range = False
            status_attack_factor = _clamp(_num(actor_constraints.get("attack_factor"), 1.0), 0.0, 1.0)
            attack_control = (actor_ctrl["attack"] + reach_advantage) * actor_exertion_factor * status_attack_factor * melee_tracking_factor + jitter(int(action.get("sequence", 0)) + len(trace), 0)
            if is_projectile:
                flight = action.get("projectile_flight", {}) if isinstance(action.get("projectile_flight"), Mapping) else {}
                attack_control = _num(flight.get("aim_control"), actor_ctrl["attack"]) * actor_exertion_factor * status_attack_factor + jitter(int(action.get("sequence", 0)) + len(trace), 0)
                # Range legality was established at release; post-release contact
                # depends only on whether the fixed lane actually intersects the
                # body before an obstacle.
                max_direct = max(1.0, _num(actor_weapon.get("maximum_direct_range_m"), _num(actor_weapon.get("effective_range_m"), 0.0)))
                legal_range = bool(action.get("trajectory_first_body")) and _num(action.get("release_distance_m"), combat_distance) <= max_direct + 1e-9
                reach_advantage = 0.0
            if mounted_body_collision:
                # A ride-down/trample is a horse+rider trajectory, not a lance
                # minimum-range check.  Control comes from riding the mass onto
                # the target line; the later contact layer still resolves the
                # actual horse mass, speed, barding and body collision impact.
                actor_skills_now, actor_attrs_now = _stats(people[actor_ref])
                riding = _num(actor_skills_now.get("Riding"))
                attack_control = (
                    0.42 * riding
                    + 0.20 * _num(actor_attrs_now.get("Coordination"))
                    + 0.16 * _num(actor_attrs_now.get("Awareness"))
                    + 0.12 * _num(actor_attrs_now.get("Composure"))
                    + 0.10 * _num(actor_attrs_now.get("Agility"))
                ) * actor_exertion_factor * status_attack_factor + jitter(int(action.get("sequence", 0)) + len(trace), 0)
                reach_advantage = 0.0
                legal_range = (path_obstacle is None) and 0.25 <= combat_distance <= 1.65
            raw_margin = attack_control - defense_control if legal_range else -40.0
            projectile_deflection_preview: dict[str, Any] | None = None
            margin = raw_margin
            if is_projectile and defense_method == "deflect" and defense_attempted and legal_range:
                flight = action.get("projectile_flight", {}) if isinstance(action.get("projectile_flight"), Mapping) else {}
                target_weapon_id_for_deflection = str(target_eq.get("best_weapon") or "") or None
                target_weapon_condition_for_deflection = current_condition(target_ref, target_weapon_id_for_deflection)
                projectile_deflection_preview = projectile_weapon_deflection_resolution(
                    target_weapon,
                    projectile_speed_mps=_num(flight.get("contact_velocity_mps"), _num(flight.get("launch_velocity_mps"), 1.0)),
                    impact_index=0.0,
                    penetration_index=0.0,
                    attack_margin=raw_margin,
                    timing_factor=timing_factor,
                    saturation_factor=saturation_factor,
                    balance_factor=balance_factor,
                    detection_quality=_num(detection.get("quality"), 0.0),
                    incoming_arc_delta_deg=weapon_arc_delta,
                    condition_pct=target_weapon_condition_for_deflection,
                )
                margin = _num(projectile_deflection_preview.get("effective_margin"), raw_margin)
            attack_event = {
                "id": action["id"] + "_attack",
                "kind": "attack",
                "actor_ref": actor_ref,
                "target_ref": target_ref,
                "weapon_id": action.get("ranged_weapon_id") if is_projectile else actor_eq.get("best_weapon"),
                "weapon_identity_ref": (action.get("ranged_weapon_id") if is_projectile else (actor_eq.get("best_weapon") or (actor_eq.get("transient_improvised_prop") or {}).get("fact_ref"))),
                "weapon_identity_kind": ("durable_projectile_weapon" if is_projectile else ("scene_improvised_prop" if actor_eq.get("transient_improvised_prop") else "durable_melee_weapon" if actor_eq.get("best_weapon") else "unarmed")),
                "projectile_item_id": action.get("ammunition_item_id") if is_projectile else None,
                "projectile_flight": dict(action.get("projectile_flight", {})) if is_projectile else None,
                "declared_intent": declared_intent,
                "aim_zone": action.get("aim_zone"),
                "aim_side": action.get("aim_side"),
                "aim_structure": action.get("aim_structure"),
                "aim_purpose": action.get("aim_purpose"),
                "aim_selection_basis": action.get("aim_selection_basis"),
                "attack_mode": action.get("attack_mode"),
                "attack_method_selection_basis": action.get("attack_method_selection_basis"),
                "attack_decision_reason": action.get("attack_decision_reason"),
                "unarmed_method": action.get("unarmed_method"),
                "distance_m": round(combat_distance, 2),
                "surface_gap_m": round(combat_gap, 3),
                "attacker_position_at_contact": {"x_m": round(path_ax, 4), "y_m": round(path_ay, 4)},
                "defender_position_at_contact": {"x_m": round(path_tx, 4), "y_m": round(path_ty, 4)},
                "contact_group_id": contact_group_id,
                "incoming_bearing_deg": round(incoming_bearing, 3),
                "defender_facing_deg": round(defender_facing, 3),
                "incoming_angle_from_facing_deg": round(facing_delta, 3),
                "melee_commitment_arc_deg": None if melee_commitment_arc_deg is None else round(melee_commitment_arc_deg, 3),
                "melee_commitment_delta_deg": None if melee_commitment_delta_deg is None else round(melee_commitment_delta_deg, 3),
                "melee_tracking_factor": round(melee_tracking_factor, 5),
                "target_displacement_after_commit_m": None if melee_target_displacement_after_commit_m is None else round(melee_target_displacement_after_commit_m, 4),
                "defense_method": defense_method,
                "attack_detected": bool(detection.get("detected")),
                "detection_quality": round(_num(detection.get("quality"), 0.0), 5),
                "meaningful_reaction_detected": bool(detection.get("meaningful_reaction")),
                "defense_timing": "ready" if lateness <= 1e-9 else "late",
                "defense_saturation_factor": round(saturation_factor, 5),
                "defense_angle_factor": round(angle_factor, 5),
                "active_defense_load_before": round(active_load, 5),
                "active_defense_load_after": round(active_load, 5),
                "active_defense_recovery_seconds": round(active_recovery_s, 5),
                "defense_pressure_sources": int(source_count),
                "defense_distinct_source_penalty": round(distinct_pressure, 5),
                "defense_balance_factor": round(balance_factor, 5),
                "attacker_exertion_factor": round(actor_exertion_factor, 5),
                "defender_exertion_factor": round(defender_exertion_factor, 5),
                "attacker_status_constraints": {k: actor_constraints[k] for k in ("stunned","restrained","immobilized","entangled","blinded","attack_factor","movement_factor","ranged_targeting_factor") if k in actor_constraints},
                "defender_status_constraints": {k: target_constraints[k] for k in ("stunned","restrained","immobilized","entangled","blinded","defense_factor","movement_factor","awareness_factor","visual_detection_factor") if k in target_constraints},
                "defense_resource_ready_at_s": round(resource_ready, 3),
                "range_legal": legal_range,
                "path_blocked_by": (dict(path_obstacle) if isinstance(path_obstacle, Mapping) else None),
                "start_at_s": round(_num(action.get("start_at_s")), 3),
                "contact_at_s": round(resolve_at, 3),
                "recovery_complete_at_s": round(_num(action.get("recovery_complete_at_s")), 3),
            }
            if projectile_deflection_preview is not None:
                attack_event["projectile_weapon_interception"] = {
                    "control_factor": projectile_deflection_preview.get("control_factor"),
                    "effective_margin": projectile_deflection_preview.get("effective_margin"),
                    "projectile_speed_mps": projectile_deflection_preview.get("projectile_speed_mps"),
                    "incoming_arc_delta_deg": projectile_deflection_preview.get("incoming_arc_delta_deg"),
                }
            trace.append(attack_event)
            must_render.append(attack_event["id"])
            ready_at[actor_ref] = _num(action.get("recovery_complete_at_s"))

            defense_event: dict[str, Any] | None = None
            if defense_attempted:
                defense_event = {
                    "id": action["id"] + "_defense",
                    "kind": "weapon_interaction",
                    "actor_ref": target_ref,
                    "target_ref": actor_ref,
                    "action": defense_method,
                    "declared_intent": defensive_plan,
                    "detection_quality": round(_num(detection.get("quality"), 0.0), 5),
                    "attack_detected": bool(detection.get("detected")),
                    "result": "stopped" if margin <= 0 and margin > -12 else ("cleanly_denied" if margin <= -12 else "late_or_beaten"),
                    "distance_m": round(combat_distance, 2),
                    "surface_gap_m": round(combat_gap, 3),
                    "contact_group_id": contact_group_id,
                    "incoming_bearing_deg": round(incoming_bearing, 3),
                    "incoming_angle_from_facing_deg": round(facing_delta, 3),
                    "saturation_factor": round(saturation_factor, 5),
                    "angle_factor": round(angle_factor, 5),
                    "active_defense_load_before": round(active_load, 5),
                    "active_defense_load_after": round(active_load, 5),
                    "active_defense_recovery_seconds": round(active_recovery_s, 5),
                    "defense_pressure_sources": int(source_count),
                    "distinct_source_penalty": round(distinct_pressure, 5),
                    "balance_factor": round(balance_factor, 5),
                    "defender_exertion_factor": round(defender_exertion_factor, 5),
                    "prior_defense_at_s": None if last_at < -900.0 else round(last_at, 3),
                    "prior_defense_angle_delta_deg": round(conflict_angle, 3),
                    "reaction_ready_at_s": round(reaction_ready, 3),
                    "contact_at_s": round(resolve_at, 3),
                }
                trace.append(defense_event)
                last_defense_method[target_ref] = defense_method
                if defensive_plan or abs(margin) <= 12:
                    must_render.append(defense_event["id"])
                else:
                    may_compress.append(defense_event["id"])
                # A real defensive response consumes readiness and aborts any
                # simultaneously committed action by that defender.
                if timing_factor > 0.10:
                    action_exertion[target_ref] += {"dodge":0.72,"reposition":0.78,"block":0.48,"parry":0.42,"deflect":0.39,"brace":0.34,"counter_intercept":0.62}.get(defense_method,0.35) * (1.0 + (1.0 - saturation_factor) * 0.55)
                    defense_serial[target_ref] += 1
                    recovery = (target_profile["defense_recovery_seconds"] / defender_exertion_factor) * (1.0 + (1.0 - saturation_factor) * 0.40)
                    positive_control_pressure = max(0.0, attack_control - defense_control_before_timing)
                    active_commitment = active_defense_commitment_fraction(
                        attacker_timing=actor_profile,
                        defender_timing=target_profile,
                        positive_control_pressure=positive_control_pressure,
                        new_source=current_source_was_new,
                        saturation_mechanics=active_defense_model,
                    )
                    updated_load = min(1.0, active_load + active_commitment)
                    body_state[target_ref]["active_defense_load"] = updated_load
                    body_state[target_ref]["active_defense_last_update_s"] = resolve_at
                    recent_sources[actor_ref] = resolve_at
                    body_state[target_ref]["active_defense_recent_sources"] = recent_sources
                    attack_event["active_defense_load_after"] = round(updated_load, 5)
                    attack_event["active_defense_commitment"] = round(active_commitment, 5)
                    defense_event["active_defense_load_after"] = round(updated_load, 5)
                    defense_event["active_defense_commitment"] = round(active_commitment, 5)
                    defense_ready_at[target_ref] = max(defense_ready_at[target_ref], resolve_at + recovery * 0.55)
                    if defense_method in {"parry", "deflect", "counter_intercept"}:
                        weapon_guard_ready_at[target_ref] = max(weapon_guard_ready_at[target_ref], resolve_at + recovery)
                        # A parry/intercept physically carries the weapon out of
                        # neutral guard; a deflection carries it farther across
                        # the attack line.
                        offset = 38.0 if defense_method == "deflect" else (22.0 if defense_method == "counter_intercept" else 0.0)
                        body_state[target_ref]["weapon_center_deg"] = (incoming_bearing + offset) % 360.0
                        if defense_method == "counter_intercept" and margin <= 0:
                            ready_at[actor_ref] = max(float(ready_at.get(actor_ref, 0.0)), resolve_at + recovery * 0.55)
                    elif defense_method == "block":
                        shield_guard_ready_at[target_ref] = max(shield_guard_ready_at[target_ref], resolve_at + recovery)
                        body_state[target_ref]["shield_center_deg"] = incoming_bearing
                    elif defense_method == "dodge":
                        body_state[target_ref]["foot_commit_until_s"] = max(
                            _num(body_state[target_ref].get("foot_commit_until_s"), 0.0),
                            resolve_at + recovery,
                        )
                        body_state[target_ref]["balance"] = max(0.45, 0.78 * saturation_factor)
                    body_state[target_ref]["last_defense_at_s"] = resolve_at
                    body_state[target_ref]["last_defense_angle_deg"] = incoming_bearing
                    body_state[target_ref]["last_defense_method"] = defense_method
                    # The torso can turn toward a threat, but not instantaneously
                    # through a full rear-to-front rotation during the contact.
                    turn = ((incoming_bearing - _num(body_state[target_ref].get("facing_deg"), defender_facing) + 180.0) % 360.0) - 180.0
                    new_facing = (_num(body_state[target_ref].get("facing_deg"), defender_facing) + _clamp(turn, -42.0, 42.0)) % 360.0
                    body_state[target_ref]["facing_deg"] = new_facing
                    positions[target_ref]["facing_deg"] = new_facing
                    defender_pending = pending.get(target_ref)
                    preserve_committed_contact = bool(
                        isinstance(defender_pending, Mapping)
                        and defender_pending.get("kind") == "attack"
                        and _num(defender_pending.get("start_at_s"), resolve_at) <= resolve_at
                        and _num(defender_pending.get("resolve_at_s"), resolve_at + 999.0) <= resolve_at + simultaneous_window_s
                    )
                    if preserve_committed_contact:
                        defender_pending["committed_through_simultaneous_contact"] = True
                    else:
                        interrupted = pending.pop(target_ref, None)
                        if isinstance(interrupted, Mapping):
                            interrupt_event = {
                                "id": action["id"] + "_defender_action_interrupted",
                                "kind": "action_interrupted",
                                "actor_ref": target_ref,
                                "target_ref": str(interrupted.get("target_ref") or ""),
                                "interrupted_action_id": str(interrupted.get("id") or ""),
                                "interrupted_action_kind": str(interrupted.get("kind") or ""),
                                "interrupted_by_actor_ref": actor_ref,
                                "cause": "active_defense_redirected_shared_body_weapon_or_foot_commitment",
                                "defense_method": defense_method,
                                "at_s": round(resolve_at, 3),
                            }
                            trace.append(interrupt_event)
                            if str(interrupted.get("kind")) == "attack":
                                must_render.append(interrupt_event["id"])
                            else:
                                may_compress.append(interrupt_event["id"])
                    ready_at[target_ref] = max(
                        resolve_at + recovery,
                        float(ready_at[target_ref]),
                    )

            if defense_attempted and defense_method == "counter_intercept":
                intercept_event = {
                    "id": action["id"] + "_counter_intercept",
                    "kind": "counter_intercept_contact",
                    "actor_ref": target_ref,
                    "target_ref": actor_ref,
                    "target_path": "attacking_weapon_or_limb_path",
                    "result": "attack_interrupted" if margin <= 0 else "intercept_beaten",
                    "startup_window_legal": bool(legal_range and detection.get("meaningful_reaction")),
                    "contact_group_id": contact_group_id,
                    "at_s": round(resolve_at, 3),
                }
                trace.append(intercept_event)
                must_render.append(intercept_event["id"])

            # Resolve the physical contact independently from the control contest.
            # A successful dodge can avoid contact entirely; parries and blocks still
            # transmit real force into weapons/shields and can damage or fail them.
            mode = str(action.get("attack_mode") or self._personal_attack_mode(actor_weapon)[0])
            force = _num(action.get("attack_force"), self._personal_attack_mode(actor_weapon)[1])
            action_exertion[actor_ref] += 0.52 + 0.28 * max(0.0, force)

            weapon_id = str(actor_eq.get("best_weapon") or "") or None
            weapon_condition = current_condition(actor_ref, weapon_id)
            grade, grade_multiplier = contact_grade_multiplier(margin)
            projectile_incoming_impact = 0.0
            projectile_incoming_penetration = 0.0
            actor_skills, actor_attrs = _stats(people[actor_ref])
            technique = 0.85 + math.sqrt(max(0.0, _num(actor_ctrl.get("weapon_skill")))) / 50.0
            grip_factor = max(0.65, min(1.20, 0.85 + 0.15 * _num(actor_weapon.get("handling"), 1.0)))
            motion_multiplier = 1.0
            charge = {}
            mounted = bool(actor_profile.get("mounted"))
            charge_intent = any(token in intent_lower for token in ("charge", "couch", "ride down", "ride-down", "trample"))
            if mounted:
                mount = actor_eq.get("mount", {}) if isinstance(actor_eq.get("mount"), Mapping) else {}
                riding = _num(actor_skills.get("Riding"))
                horse_training = _num(mount.get("training_score"), _num(mount.get("training"), 0.0))
                relative_speed = _num(actor_profile.get("mount_effective_speed_mps"), 0.0)
                # Close mounted melee carries some platform motion; a declared
                # charge/couched attack uses the actual charge alignment model.
                if charge_intent or (str(actor_weapon.get("variant", "")).lower().find("lance") >= 0 and combat_distance >= 1.45):
                    charge = mounted_charge_resolution(
                        actor_profile.get("mount_profile", {}),
                        riding=riding,
                        coordination=_num(actor_attrs.get("Coordination")),
                        awareness=_num(actor_attrs.get("Awareness")),
                        composure=_num(actor_attrs.get("Composure")),
                        horse_training=horse_training,
                        relative_speed_mps=relative_speed,
                        weapon=actor_weapon,
                    )
                    motion_multiplier = _num(charge.get("weapon_motion_multiplier"), 1.0)
                elif str(actor_weapon.get("mounted_compatibility", "")).lower() in {"excellent", "good"}:
                    motion_multiplier = 1.0 + math.sqrt(max(0.0, relative_speed)) / 18.0

            # The rules authority defines attack force as usable Strength times
            # catalog force and physical multipliers. Stat growth is uncapped;
            # technique uses root scaling rather than a hidden 200 ceiling.
            if is_projectile:
                flight = action.get("projectile_flight", {}) if isinstance(action.get("projectile_flight"), Mapping) else {}
                projectile_incoming_impact = max(0.0, _num(flight.get("impact_index"), 0.0))
                projectile_incoming_penetration = max(0.0, _num(flight.get("penetration_index"), projectile_incoming_impact))
                impact = projectile_incoming_impact * max(0.0, grade_multiplier)
                penetration = projectile_incoming_penetration * max(0.0, grade_multiplier)
                weapon_id = str(action.get("ranged_weapon_id") or "") or None
                weapon_condition = current_condition(actor_ref, weapon_id)
            elif action.get("mounted_body_collision") and charge:
                # A ride-down/trample is horse+rider collision physics, not a
                # magically strengthened sword swing. The charge model already
                # contains total mass, relative speed and alignment.
                impact = (
                    max(0.0, _num(charge.get("body_collision_impact_index"), 0.0))
                    * max(0.0, grade_multiplier)
                    * max(0.70, min(1.18, 0.88 + _num(actor_ctrl.get("coordination")) / 900.0))
                )
                penetration = impact * 0.18
                weapon_id = None
                weapon_condition = 100.0
            else:
                impact = (
                    max(1.0, _num(actor_ctrl.get("strength")))
                    * max(0.05, force)
                    * max(0.0, grade_multiplier)
                    * max(0.35, motion_multiplier)
                    * max(0.45, technique)
                    * physics_condition_factor(weapon_condition)
                    * grip_factor
                )
                penetration = weapon_penetration_index(actor_weapon, mode=mode, impact_index=impact)

            # Hard defensive contacts can exist even when the attack is fully
            # denied. They wear the contacting equipment without becoming a wound.
            hard_defensive_contact = defense_attempted and defense_method in {"parry", "deflect", "counter_intercept", "block"}
            if is_projectile and hard_defensive_contact:
                # The active defense meets the projectile before any body-contact
                # grade can reduce its energy. Shield/blade wear therefore uses
                # the projectile's actual incoming physical impulse.
                clash_impact = max(projectile_incoming_impact, impact)
            else:
                clash_impact = max(impact, max(1.0, _num(actor_ctrl.get("strength"))) * max(0.05, force) * 0.28) if hard_defensive_contact else impact
            residual_impact = impact
            residual_penetration = penetration
            shield_result: dict[str, Any] | None = None
            armor_result: dict[str, Any] | None = None
            weapon_wear_result: dict[str, Any] | None = None
            target_parry_wear: dict[str, Any] | None = None
            projectile_deflection_result: dict[str, Any] | None = None
            deflected_projectile_action: dict[str, Any] | None = None

            if is_projectile and defense_method == "deflect" and defense_attempted:
                flight = action.get("projectile_flight", {}) if isinstance(action.get("projectile_flight"), Mapping) else {}
                target_weapon_id_for_deflection = str(target_eq.get("best_weapon") or "") or None
                target_weapon_condition_for_deflection = current_condition(target_ref, target_weapon_id_for_deflection)
                projectile_deflection_result = projectile_weapon_deflection_resolution(
                    target_weapon,
                    projectile_speed_mps=_num(flight.get("contact_velocity_mps"), _num(flight.get("launch_velocity_mps"), 1.0)),
                    impact_index=projectile_incoming_impact,
                    penetration_index=projectile_incoming_penetration,
                    attack_margin=raw_margin,
                    timing_factor=timing_factor,
                    saturation_factor=saturation_factor,
                    balance_factor=balance_factor,
                    detection_quality=_num(detection.get("quality"), 0.0),
                    incoming_arc_delta_deg=weapon_arc_delta,
                    condition_pct=target_weapon_condition_for_deflection,
                )
                deflection_outcome = str(projectile_deflection_result.get("outcome", ""))
                raw_deflected_impact = _num(projectile_deflection_result.get("residual_impact_index"), projectile_incoming_impact)
                raw_deflected_penetration = _num(projectile_deflection_result.get("residual_penetration_index"), projectile_incoming_penetration)
                if deflection_outcome == "clean_deflection":
                    residual_impact = raw_deflected_impact
                    residual_penetration = raw_deflected_penetration
                elif deflection_outcome == "partial_deflection":
                    residual_impact = raw_deflected_impact * max(0.0, grade_multiplier)
                    residual_penetration = raw_deflected_penetration * max(0.0, grade_multiplier)
                else:
                    residual_impact = impact
                    residual_penetration = penetration
                deflection_event = {
                    "id": action["id"] + "_projectile_deflection",
                    "kind": "projectile_weapon_interception",
                    "actor_ref": target_ref,
                    "target_ref": actor_ref,
                    "projectile_item_id": action.get("ammunition_item_id"),
                    "weapon_id": target_weapon_id_for_deflection,
                    "outcome": projectile_deflection_result.get("outcome"),
                    "projectile_speed_mps": projectile_deflection_result.get("projectile_speed_mps"),
                    "control_factor": projectile_deflection_result.get("control_factor"),
                    "effective_margin": projectile_deflection_result.get("effective_margin"),
                    "incoming_arc_delta_deg": projectile_deflection_result.get("incoming_arc_delta_deg"),
                    "deflection_angle_deg": projectile_deflection_result.get("deflection_angle_deg"),
                    "residual_impact_index": projectile_deflection_result.get("residual_impact_index"),
                    "residual_penetration_index": projectile_deflection_result.get("residual_penetration_index"),
                    "at_s": round(resolve_at, 3),
                }
                trace.append(deflection_event)
                must_render.append(deflection_event["id"])
                if defense_event is not None:
                    defense_event["result"] = str(projectile_deflection_result.get("outcome") or defense_event.get("result"))
                    defense_event["projectile_weapon_interception"] = {
                        "control_factor": projectile_deflection_result.get("control_factor"),
                        "effective_margin": projectile_deflection_result.get("effective_margin"),
                        "deflection_angle_deg": projectile_deflection_result.get("deflection_angle_deg"),
                    }

                if projectile_deflection_result.get("outcome") == "clean_deflection":
                    # A clean weapon interception redirects the already-released
                    # projectile rather than deleting it. Continue a bounded local
                    # physical segment so another body or obstacle may intercept it.
                    deflection_count = max(0, int(action.get("deflection_count", 0) or 0))
                    if deflection_count < 2:
                        incoming_deg = math.degrees(math.atan2(_num(action.get("trajectory_direction_y"), 0.0), _num(action.get("trajectory_direction_x"), 1.0)))
                        stable_side = (int(action.get("sequence", 0)) + sum(ord(ch) for ch in str(target_ref))) % 2
                        signed_angle = _num(projectile_deflection_result.get("deflection_angle_deg"), 35.0) * (-1.0 if stable_side else 1.0)
                        outgoing_deg = math.radians(incoming_deg + signed_angle)
                        out_ux, out_uy = math.cos(outgoing_deg), math.sin(outgoing_deg)
                        lane_hit = action.get("trajectory_first_body", {}) if isinstance(action.get("trajectory_first_body"), Mapping) else {}
                        origin_x = _num(lane_hit.get("x_m"), contact_group_positions.get(target_ref, position_at(target_ref, resolve_at))[0])
                        origin_y = _num(lane_hit.get("y_m"), contact_group_positions.get(target_ref, position_at(target_ref, resolve_at))[1])
                        remaining_length = max(2.0, _num(action.get("trajectory_length_m"), 8.0) - _num(lane_hit.get("distance_along_m"), combat_distance))
                        remaining_length = min(18.0, remaining_length)
                        retained_speed = max(6.0, _num(projectile_deflection_result.get("projectile_speed_mps"), 10.0) * math.sqrt(max(0.08, _num(projectile_deflection_result.get("impact_retention"), 0.5))))
                        residual_flight = remaining_length / retained_speed
                        new_flight = dict(flight)
                        new_flight["impact_index"] = round(residual_impact, 3)
                        new_flight["penetration_index"] = round(residual_penetration, 3)
                        new_flight["launch_velocity_mps"] = round(retained_speed, 3)
                        new_flight["contact_velocity_mps"] = round(retained_speed, 3)
                        new_flight["flight_time_seconds"] = round(residual_flight, 4)
                        deflected_projectile_action = dict(
                            action,
                            id=action["id"] + f"_deflect_{deflection_count + 1}",
                            kind="projectile_contact",
                            resolve_at_s=resolve_at + residual_flight,
                            start_at_s=resolve_at,
                            release_at_s=_num(action.get("release_at_s"), resolve_at),
                            projectile_flight=new_flight,
                            trajectory_origin_x_m=origin_x,
                            trajectory_origin_y_m=origin_y,
                            trajectory_origin_elevation_m=_num(action.get("trajectory_target_elevation_m"), 1.05),
                            trajectory_direction_x=out_ux,
                            trajectory_direction_y=out_uy,
                            trajectory_length_m=remaining_length,
                            trajectory_target_elevation_m=_num(action.get("trajectory_target_elevation_m"), 1.05),
                            trajectory_exclude_refs=list(dict.fromkeys([target_ref] + list(action.get("trajectory_exclude_refs", []) if isinstance(action.get("trajectory_exclude_refs"), list) else []))),
                            deflection_count=deflection_count + 1,
                        )
                        deflection_event["outgoing_bearing_deg"] = round((math.degrees(outgoing_deg) % 360.0), 3)
                        deflection_event["continued_projectile_segment"] = True
                        deflection_event["remaining_local_trajectory_m"] = round(remaining_length, 3)
                    else:
                        deflection_event["continued_projectile_segment"] = False
                        deflection_event["continuation_reason"] = "local_deflection_chain_limit"

            if defense_method == "block" and defense_attempted:
                shield_id = target_eq.get("loadout", {}).get("shield") if isinstance(target_eq.get("loadout"), Mapping) else None
                shield = self._combat_weapon(shield_id) if shield_id and hasattr(self, "_combat_weapon") else {}
                shield_condition = current_condition(target_ref, str(shield_id) if shield_id else None)
                shield_center = _num(pre_body.get("shield_center_deg"), defender_facing) % 360.0
                shield_delta = angle_delta(incoming_bearing, shield_center)
                shield_arc = max(35.0, _num(shield.get("coverage_arc_degrees"), 90.0))
                shield_reachable = shield_delta <= min(150.0, shield_arc * 0.5 + 34.0)
                block_ratio = max(0.05, defense_control) / max(1.0, attack_control)
                if shield_reachable:
                    presentation = max(0.0,min(72.0,8.0+46.0*max(0.0,min(1.0,(block_ratio*.52+timing_factor*.48)/1.30))))
                    shield_result = shield_contact_resolution(
                        shield,
                        impact_index=clash_impact,
                        penetration_index=(projectile_incoming_penetration if is_projectile else penetration),
                        mode=mode,
                        condition_pct=shield_condition,
                        timing_factor=timing_factor * saturation_factor * balance_factor,
                        block_control_ratio=block_ratio,
                        interception_angle_deg=presentation,
                    )
                    shield_result["incoming_arc_delta_deg"] = round(shield_delta, 3)
                    shield_result["coverage_arc_degrees"] = round(shield_arc, 3)
                    shield_result["reachable_from_current_orientation"] = True
                else:
                    shield_result = {
                        "intercepted": False,
                        "reason": "incoming_attack_outside_current_shield_arc",
                        "incoming_arc_delta_deg": round(shield_delta, 3),
                        "coverage_arc_degrees": round(shield_arc, 3),
                        "reachable_from_current_orientation": False,
                        "absorbed_impact": 0.0,
                        "residual_impact": max(0.0, clash_impact),
                        "residual_penetration_index": max(0.0, penetration),
                        "penetrated": False,
                        "condition_loss_pct": 0.0,
                        "remaining_condition_pct": shield_condition,
                        "failed": False,
                    }
                residual_impact = _num(shield_result.get("residual_impact"), residual_impact)
                residual_penetration = _num(shield_result.get("residual_penetration_index"), residual_penetration)
                if shield_id and shield_result.get("intercepted"):
                    set_condition(target_ref, str(shield_id), _num(shield_result.get("remaining_condition_pct"), shield_condition), reason="shield_contact", event_id=action["id"] + "_contact")
                    if shield_result.get("failed"):
                        target_eq.get("loadout", {}).pop("shield", None)
                        fail_event = {
                            "id": action["id"] + "_shield_failure",
                            "kind": "equipment_state",
                            "actor_ref": target_ref,
                            "action": "shield_structural_failure",
                            "item_id": shield_id,
                            "impact_index": round(clash_impact, 3),
                            "at_s": round(resolve_at, 3),
                        }
                        trace.append(fail_event); must_render.append(fail_event["id"])

            if (
                defense_method in {"parry", "deflect", "counter_intercept"}
                and defense_attempted
                and (
                    not is_projectile
                    or defense_method != "deflect"
                    or bool(projectile_deflection_result and projectile_deflection_result.get("intercepted"))
                )
            ):
                target_weapon_id = str(target_eq.get("best_weapon") or "") or None
                target_weapon_condition = current_condition(target_ref, target_weapon_id)
                target_parry_wear = weapon_contact_wear(
                    target_weapon,
                    transmitted_impact_index=clash_impact * max(0.35, timing_factor),
                    condition_pct=target_weapon_condition,
                    hard_contact=True,
                )
                if target_weapon_id:
                    set_condition(target_ref, target_weapon_id, _num(target_parry_wear.get("remaining_condition_pct"), target_weapon_condition), reason=("weapon_parry" if defense_method == "parry" else "weapon_deflection_or_intercept"), event_id=action["id"] + "_defense")
                    if target_parry_wear.get("failed"):
                        if target_ref == self.PLAYER_ACTOR and isinstance(target_eq.get("transient_improvised_prop"), Mapping):
                            transient_player_prop_state["status"] = "broken"
                        target_eq["best_weapon"] = None
                        target_eq["weapon"] = {"id": "unarmed", "family": "unarmed", "reach_m": 0.44, "minimum_range_m": 0.0, "handling": 1.0, "base_force_blunt": 0.35, "recovery_class": "quick"}
                        target_eq.setdefault("loadout", {}).pop("primary_melee_weapon", None)
                        fail_event = {
                            "id": action["id"] + "_parry_weapon_failure",
                            "kind": "equipment_state",
                            "actor_ref": target_ref,
                            "action": "weapon_structural_failure_on_parry",
                            "item_id": target_weapon_id,
                            "at_s": round(resolve_at, 3),
                        }
                        trace.append(fail_event); must_render.append(fail_event["id"])

            weapon_wear_result = ({"condition_loss_pct": 0.0, "remaining_condition_pct": weapon_condition, "overload_ratio": 0.0, "failed": False} if is_projectile else weapon_contact_wear(
                actor_weapon,
                transmitted_impact_index=clash_impact if hard_defensive_contact else max(impact, 1.0),
                condition_pct=weapon_condition,
                hard_contact=hard_defensive_contact or margin > 0,
            ))
            if weapon_id and not is_projectile:
                set_condition(actor_ref, weapon_id, _num(weapon_wear_result.get("remaining_condition_pct"), weapon_condition), reason="attack_contact", event_id=action["id"] + "_contact")
                if weapon_wear_result.get("failed"):
                    if actor_ref == self.PLAYER_ACTOR and isinstance(actor_eq.get("transient_improvised_prop"), Mapping):
                        transient_player_prop_state["status"] = "broken"
                    actor_eq["best_weapon"] = None
                    actor_eq["weapon"] = {"id": "unarmed", "family": "unarmed", "reach_m": 0.44, "minimum_range_m": 0.0, "handling": 1.0, "base_force_blunt": 0.35, "recovery_class": "quick"}
                    actor_eq.setdefault("loadout", {}).pop("primary_melee_weapon", None)
                    fail_event = {
                        "id": action["id"] + "_weapon_failure",
                        "kind": "equipment_state",
                        "actor_ref": actor_ref,
                        "action": "weapon_structural_failure",
                        "item_id": weapon_id,
                        "overload_ratio": weapon_wear_result.get("overload_ratio"),
                        "at_s": round(resolve_at, 3),
                    }
                    trace.append(fail_event); must_render.append(fail_event["id"])

            # A clean dodge has no body contact. A stopped parry/block can still
            # damage equipment, but only residual force from a failed/overloaded
            # block can continue into the body.
            # Bracing deliberately accepts contact; it reduces transmitted
            # impact/displacement rather than pretending the attack missed.
            if defense_method == "brace" and defense_attempted:
                brace_ratio = max(0.05, defense_control) / max(1.0, attack_control)
                brace_impact_factor = _clamp(0.88 - 0.28 * brace_ratio, 0.54, 0.90)
                residual_impact *= brace_impact_factor
                residual_penetration *= _clamp(0.98 - 0.05 * brace_ratio, 0.90, 0.98)
            body_contact = defense_method == "brace" or margin > 0 or (
                defense_method == "block"
                and bool(shield_result)
                and (
                    bool(shield_result.get("failed"))
                    or bool(shield_result.get("penetrated"))
                )
                and (residual_impact > 0 or residual_penetration > 0)
            )
            if not body_contact:
                denial_result = (
                    "dodged" if defense_method in {"dodge", "reposition"}
                    else "blocked" if defense_method == "block"
                    else "parried" if defense_method == "parry"
                    else "deflected" if defense_method == "deflect"
                    else "counter_intercepted" if defense_method == "counter_intercept"
                    else "denied"
                )
                action_memory[actor_ref].append({
                    "kind": "attack",
                    "mode": mode,
                    "aim_structure": action.get("aim_structure"),
                    "aim_zone": action.get("aim_zone"),
                    "result": denial_result,
                    "defense_method": defense_method,
                    "at_s": round(resolve_at, 3),
                })
                action_memory[actor_ref] = action_memory[actor_ref][-8:]
                action_memory[target_ref].append({
                    "kind": "defense",
                    "defense_method": defense_method,
                    "defense_result": "successful",
                    "against_mode": mode,
                    "at_s": round(resolve_at, 3),
                })
                action_memory[target_ref] = action_memory[target_ref][-8:]
                if defense_method in {"dodge", "reposition"}:
                    tx, ty = positions[target_ref]["x_m"], positions[target_ref]["y_m"]
                    ax, ay = contact_group_positions.get(actor_ref, position_at(actor_ref, resolve_at))
                    dx = tx - ax; dy = ty - ay; mag = max(1e-6, math.hypot(dx, dy))
                    # Evasion can be a short contact dodge or a tactical
                    # reposition.  Repositioning uses the shared battlefield
                    # geometry to seek the safest available escape arc; ordinary
                    # dodge favors the shortest perpendicular line.
                    threat_refs = [r for r in (hostile_side if target_ref in player_side else player_side) if active(r)]
                    if defense_method == "reposition":
                        escape = safest_escape_vector(
                            target_ref, threat_refs, geometry_positions(resolve_at),
                            preferred_distance_m=1.0, obstacles=local_obstacles,
                            clearance_radius_m=actor_clearance_radius(target_ref),
                        )
                        candidates = [escape, (-dy / mag, dx / mag), (dy / mag, -dx / mag)]
                    else:
                        candidates = [(-dy / mag, dx / mag), (dy / mag, -dx / mag)]
                    step = _clamp((0.24 if defense_method == "reposition" else 0.13) + 0.18 * timing_factor * saturation_factor, 0.10, 0.46)
                    def clearance(vec: tuple[float,float]) -> float:
                        nx = tx + vec[0] * step + (dx / mag) * step * 0.18
                        ny = ty + vec[1] * step + (dy / mag) * step * 0.18
                        if static_obstacle_at(nx,ny,radius_m=actor_clearance_radius(target_ref)) is not None:
                            return -999.0
                        vals=[]
                        for threat in threat_refs:
                            hx,hy = contact_group_positions.get(threat, position_at(threat, resolve_at))
                            vals.append(math.hypot(nx-hx,ny-hy))
                        return min(vals) if vals else 999.0
                    chosen = max(candidates, key=lambda vec:(clearance(vec),vec[0],vec[1]))
                    proposed_x = tx + chosen[0] * step + (dx / mag) * step * 0.18
                    proposed_y = ty + chosen[1] * step + (dy / mag) * step * 0.18
                    nx,ny,dodge_blocker=clamp_local_movement(target_ref,actor_ref,tx,ty,proposed_x,proposed_y,resolve_at)
                    positions[target_ref]["x_m"] = nx; positions[target_ref]["y_m"] = ny
                    if defense_attempted and dodge_blocker is not None:
                        defense_event["dodge_blocked_by"] = dict(dodge_blocker)
                    body_state[target_ref]["last_dodge_vector"] = (round(nx-tx,6),round(ny-ty,6))
                    dodge_dt = max(0.08, target_profile["reaction_seconds"] / max(0.52, defender_exertion_factor))
                    body_state[target_ref]["movement_velocity_xy_mps"] = (round((nx-tx)/dodge_dt,6), round((ny-ty)/dodge_dt,6))
                    body_state[target_ref]["movement_velocity_until_s"] = resolve_at + min(0.45, max(0.10, target_profile["movement_recovery_seconds"]))
                    if defense_attempted:
                        defense_event["physical_response"] = defense_method
                        defense_event["body_displacement_m"] = round(math.hypot(nx-tx,ny-ty), 4)
                        defense_event["dodge_from_position"] = {"x_m":round(tx,3),"y_m":round(ty,3)}
                        defense_event["dodge_to_position"] = {"x_m":round(nx,3),"y_m":round(ny,3)}
                elif (not is_projectile) and defense_method in {"parry", "deflect", "counter_intercept"} and margin < -18:
                    # A dominant melee parry can carry the attacker's weapon/body
                    # line inward. Deflecting a released projectile cannot reach
                    # backward through the lane and unbalance the distant shooter.
                    body_state[actor_ref]["balance"] = min(_num(body_state[actor_ref].get("balance"),1.0),0.82)
                    body_state[actor_ref]["foot_commit_until_s"] = max(_num(body_state[actor_ref].get("foot_commit_until_s"),0.0),resolve_at+0.12)
                if target_ref == self.PLAYER_ACTOR and defensive_plan:
                    active_guard.pop(target_ref, None)
                    settle_combo_link("completed", defense_event["id"] if defense_attempted else attack_event["id"])
                elif actor_ref == self.PLAYER_ACTOR and declared_intent:
                    settle_combo_link("failed", defense_event["id"] if defense_attempted else attack_event["id"])
                    pending_boundary = {
                        "kind": "combo_interrupted",
                        "player_decision_required": True,
                        "reason": "a declared linked action was physically denied, so dependent later links were cancelled",
                        "at_s": round(resolve_at, 3),
                    }
                    if not stop_on_decision or spar:
                        pending_boundary = None
                if deflected_projectile_action is not None:
                    pending["flight:" + str(deflected_projectile_action["id"])] = deflected_projectile_action
                for ref in actors:
                    schedule(ref)
                continue

            if target_ref == self.PLAYER_ACTOR and defensive_plan:
                active_guard.pop(target_ref, None)
                settle_combo_link("failed", defense_event["id"] if defense_attempted else attack_event["id"])

            aimed_zone = str(action.get("aim_zone") or "upper_torso")
            aimed_side = str(action.get("aim_side") or "midline")
            aimed_structure = str(action.get("aim_structure") or aimed_zone)
            if aimed_zone == "mount":
                mount_structure = aimed_structure if aimed_structure in {"foreleg", "hindleg", "chest", "neck", "eye"} else "mount"
                actual_target = {"body_zone": "mount", "side": "mount", "structure": mount_structure, "deviation": "none", "aim_preserved": True}
            else:
                actual_target = resolve_actual_contact_target(
                    aim_zone=aimed_zone, aim_side=aimed_side, aim_structure=aimed_structure,
                    contact_grade=grade, defense_method=defense_method, margin=margin,
                    seed=seed + int(action.get("sequence", 0)) * 29,
                )
            zone = str(actual_target.get("body_zone", aimed_zone))
            actual_side = str(actual_target.get("side", aimed_side))
            actual_structure = str(actual_target.get("structure", aimed_structure))

            if zone == "mount":
                covering_item = target_eq.get("horse_armor", {}) if isinstance(target_eq.get("horse_armor"), Mapping) else {}
                armor_item_id = target_eq.get("loadout", {}).get("horse_armor") if isinstance(target_eq.get("loadout"), Mapping) else None
                covered = bool(covering_item)
            else:
                d_loadout = target_eq.get("loadout", {}) if isinstance(target_eq.get("loadout"), Mapping) else {}
                armor = self._combat_weapon(d_loadout.get("body_armor")) if hasattr(self, "_combat_weapon") else {}
                helmet = self._combat_weapon(d_loadout.get("helmet")) if hasattr(self, "_combat_weapon") else {}
                covered, covering_item = self._personal_zone_covered(zone, armor, helmet, actual_structure)
                armor_item_id = covering_item.get("id") if isinstance(covering_item, Mapping) else None

            armor_condition = current_condition(target_ref, str(armor_item_id) if armor_item_id else None)
            angle_name, angle_factor = angle_from_margin(margin)
            armor_result = armor_contact_resolution(
                covering_item if covered else None,
                mode=mode,
                impact_index=max(0.0, residual_impact),
                penetration_index=max(0.0, residual_penetration),
                condition_pct=armor_condition,
                fit_factor=1.0,
                angle_factor=angle_factor,
                structure=actual_structure,
            )
            severity = str(armor_result.get("severity", "none"))
            if spar and severity not in {"none", "minor"}:
                severity = "minor"
            if armor_item_id and covered:
                after_armor = max(0.0, armor_condition - _num(armor_result.get("armor_wear_pct"), 0.0))
                set_condition(target_ref, str(armor_item_id), after_armor, reason="armor_contact", event_id=action["id"] + "_contact")

            anatomical_resolution = resolve_anatomical_contact(
                zone=zone,
                mode=mode,
                impact_index=max(0.0, _num(armor_result.get("residual_impact_index"), residual_impact)),
                penetration_index=max(0.0, _num(armor_result.get("residual_penetration_index"), residual_penetration)),
                # At this point armor/shield layers have already been resolved.
                # Anatomy therefore receives a tissue/structure reference rather
                # than counting the armor channel a second time.
                channel_protection=30.0,
                contact_grade=grade,
                declared_intent=declared_intent,
                seed=seed + int(action.get("sequence", 0)),
                lethal_intent=lethal_intent,
                aim_side=actual_side or None,
                aim_structure=actual_structure or None,
            )
            structural_resolution = resolve_structural_injury(
                zone=zone,
                structure=actual_structure,
                side=actual_side,
                mode=mode,
                severity=severity,
                impact_index=max(0.0, _num(armor_result.get("residual_impact_index"), residual_impact)),
                penetration_index=max(0.0, _num(armor_result.get("residual_penetration_index"), residual_penetration)),
                contact_grade=grade,
                seed=seed + int(action.get("sequence", 0)) * 31,
            )

            contact = {
                "id": action["id"] + "_contact",
                "kind": "contact",
                "actor_ref": actor_ref,
                "target_ref": target_ref,
                "weapon_id": weapon_id,
                "weapon_identity_ref": weapon_id or (actor_eq.get("transient_improvised_prop") or {}).get("fact_ref"),
                "weapon_identity_kind": "scene_improvised_prop" if actor_eq.get("transient_improvised_prop") else "durable_melee_weapon" if weapon_id else "unarmed",
                "declared_intent": declared_intent,
                "aim_zone": action.get("aim_zone"),
                "aim_side": action.get("aim_side"),
                "aim_structure": action.get("aim_structure"),
                "aim_purpose": action.get("aim_purpose"),
                "actual_contact_zone": zone,
                "actual_contact_side": actual_side,
                "actual_contact_structure": actual_structure,
                "contact_deviation": actual_target.get("deviation"),
                "aim_preserved": bool(actual_target.get("aim_preserved", False)),
                "attack_mode": mode,
                "projectile_item_id": action.get("ammunition_item_id") if is_projectile else None,
                "projectile_flight": dict(action.get("projectile_flight", {})) if is_projectile else None,
                "body_zone": zone,
                "contact_grade": grade,
                "impact_index": round(impact, 3),
                "penetration_index": round(penetration, 3),
                "residual_impact_index": round(max(0.0, residual_impact), 3),
                "residual_penetration_index_before_armor": round(max(0.0, residual_penetration), 3),
                "post_armor_impact_index": armor_result.get("residual_impact_index"),
                "post_armor_penetration_index": armor_result.get("residual_penetration_index"),
                "motion_multiplier": round(motion_multiplier, 4),
                "armor_intercepted": bool(covered),
                "armor_item_id": armor_item_id,
                "armor_resolution": armor_result,
                "shield_resolution": shield_result,
                "weapon_wear": weapon_wear_result,
                "parry_weapon_wear": target_parry_wear,
                "mounted_charge": charge if charge else None,
                "mounted_body_collision": bool(action.get("mounted_body_collision")),
                "impact_angle": angle_name,
                "anatomical_resolution": anatomical_resolution,
                "structural_injury": structural_resolution,
                "physical_result": (
                    str(anatomical_resolution.get("outcome"))
                    if anatomical_resolution.get("irreversible")
                    else ("no_material_injury" if severity == "none" else f"{severity}_injury")
                ),
                "at_s": round(resolve_at, 3),
            }
            # A deep sharp melee contact can physically bind/lodge the weapon.
            # This occupies the weapon and extends recovery rather than granting an
            # instant clean reset after a deep thrust/cut through armor/tissue.
            if (not is_projectile) and weapon_id and mode in {"cut","thrust"} and severity in {"moderate","serious","critical"}:
                embed_ratio=max(_num(armor_result.get("post_defense_tissue_penetration_ratio"),0.0),_num(armor_result.get("maximum_ratio"),0.0))
                threshold=max(1.0,_num(embedded_weapon_model.get("minimum_penetration_ratio"),1.18))
                family=str(actor_weapon.get("family",actor_weapon.get("variant",""))).lower()
                if embed_ratio>=threshold and any(token in family for token in ("spear","sword","axe","glaive","polearm","blade")):
                    base=max(0.12,_num(embedded_weapon_model.get("base_extraction_seconds"),0.42))
                    if any(token in str(actual_structure).lower() for token in ("bone","radius","ulna","femur","tibia","humerus","rib","skull","spine")):
                        base+=max(0.0,_num(embedded_weapon_model.get("bone_extra_seconds"),0.55))
                    if covered:
                        base+=max(0.0,_num(embedded_weapon_model.get("armor_extra_seconds"),0.28))
                    multiplier=1.0
                    if "spear" in family or "glaive" in family or "polearm" in family: multiplier=_num(embedded_weapon_model.get("spear_multiplier"),1.25)
                    elif "axe" in family: multiplier=_num(embedded_weapon_model.get("axe_multiplier"),1.2)
                    elif "sword" in family or "blade" in family: multiplier=_num(embedded_weapon_model.get("sword_multiplier"),1.0)
                    deep=max(threshold,_num(embedded_weapon_model.get("deep_penetration_ratio"),1.65))
                    depth_factor=1.0+0.30*_clamp((embed_ratio-threshold)/max(0.01,deep-threshold),0.0,1.0)
                    extraction_seconds=max(0.12,base*max(0.5,multiplier)*depth_factor/transient_exertion_factor(actor_ref))
                    embedded={"item_id":weapon_id,"target_ref":target_ref,"target_structure":actual_structure,"target_zone":zone,"embedded_at_s":round(resolve_at,6),"extraction_seconds":round(extraction_seconds,6),"source_contact_id":contact["id"]}
                    people[actor_ref].setdefault("combat_state",{})["embedded_weapon"]=embedded
                    body_state[actor_ref]["embedded_weapon"]=dict(embedded)
                    actor_eq["best_weapon"]=None; actor_eq["weapon"]={"id":"unarmed","family":"unarmed","reach_m":0.44,"minimum_range_m":0.0,"handling":1.0,"base_force_blunt":0.35,"recovery_class":"quick"}; actor_eq.setdefault("loadout",{}).pop("primary_melee_weapon",None)
                    ready_at[actor_ref]=max(float(ready_at.get(actor_ref,0.0)),resolve_at)
                    contact["embedded_weapon"]={**embedded,"penetration_ratio":round(embed_ratio,5)}
                    embed_event={"id":action["id"]+"_embedded","kind":"equipment_state","actor_ref":actor_ref,"target_ref":target_ref,"action":"weapon_embedded","item_id":weapon_id,"target_structure":actual_structure,"penetration_ratio":round(embed_ratio,5),"earliest_extraction_complete_at_s":round(resolve_at+extraction_seconds,3),"at_s":round(resolve_at,3)}
                    trace.append(embed_event); must_render.append(embed_event["id"])
            trace.append(contact)
            must_render.append(contact["id"])
            sequence_result = (
                "critical_contact" if severity == "critical"
                else "material_contact" if severity not in {"none", "minor"}
                else "minor_contact" if severity == "minor"
                else "contact_no_injury"
            )
            if defense_method == "block" and shield_result and shield_result.get("penetrated"):
                sequence_result = "penetrated_block"
            action_memory[actor_ref].append({
                "kind": "attack",
                "mode": mode,
                "aim_structure": action.get("aim_structure"),
                "aim_zone": action.get("aim_zone"),
                "result": sequence_result,
                "defense_method": defense_method,
                "severity": severity,
                "at_s": round(resolve_at, 3),
            })
            action_memory[actor_ref] = action_memory[actor_ref][-8:]
            if defense_attempted:
                action_memory[target_ref].append({
                    "kind": "defense",
                    "defense_method": defense_method,
                    "defense_result": "penetrated" if (shield_result and shield_result.get("penetrated")) else "late_or_beaten",
                    "against_mode": mode,
                    "at_s": round(resolve_at, 3),
                })
                action_memory[target_ref] = action_memory[target_ref][-8:]
            if actor_ref == self.PLAYER_ACTOR and declared_intent:
                settle_combo_link("completed", contact["id"])

            if severity != "none":
                target = people[target_ref]
                if zone == "mount":
                    wound = self._personal_apply_mount_wound(
                        target, severity=severity, mode=mode,
                        source_weapon=weapon_id, at=str(self._world_time()),
                        seed=seed + int(action.get("sequence", 0)) * 43,
                        structure=actual_structure,
                    )
                    mount_wounds.append({"target_ref": target_ref, **wound})
                    mount_status = str((target.get("mount_combat_state") or {}).get("status", "active")).lower() if isinstance(target.get("mount_combat_state"), Mapping) else "active"
                    mount_lost = bool(wound.get("collapse")) or mount_status in {"dead", "disabled", "lost"}
                    if mount_lost:
                        target_eq["mount"] = {}
                        target_profile["mounted"] = False
                        target_profile["mount_effective_speed_mps"] = 0.0
                        target_profile["movement_speed_mps"] = max(0.75, target_profile["movement_speed_mps"] * 0.55)
                        mounted_event = {
                            "id": action["id"] + "_mount_disabled",
                            "kind": "mounted_state",
                            "actor_ref": target_ref,
                            "action": "mount_killed_or_disabled_rider_unhorsed" if mount_status == "dead" else "mount_disabled_rider_unhorsed",
                            "mount_status": mount_status,
                            "severity": severity,
                            "at_s": round(resolve_at, 3),
                        }
                        trace.append(mounted_event); must_render.append(mounted_event["id"])
                        # A collapsing horse is a physical fall, not an abstract
                        # loss of the mounted flag.  The rider occupies the same
                        # shared combat clock while falling/grounding and cannot
                        # immediately perform a pristine foot defense.
                        if str(body_state[target_ref].get("posture", "standing")) not in {"falling", "prone", "knocked_down"}:
                            begin_fall(
                                target_ref,
                                severity="critical" if mount_status == "dead" else (severity if severity in {"moderate", "serious", "critical"} else "moderate"),
                                at_s=resolve_at,
                                reason="mount_killed" if mount_status == "dead" else "mount_collapsed",
                                source_event_id=action["id"] + "_mount",
                            )
                else:
                    wound = self._personal_apply_wound(
                        target,
                        zone=zone,
                        severity=severity,
                        mode=mode,
                        source_weapon=weapon_id,
                        at=str(self._world_time()),
                        side=actual_side,
                        structure=actual_structure,
                        structural_resolution=structural_resolution,
                        local_at_s=resolve_at,
                    )
                    structural_state_changes = apply_structural_injury_state(
                        target, structural_resolution, at=str(self._world_time()), source_weapon=weapon_id
                    )
                    wound["structural_state_changes"] = structural_state_changes
                    # New exact structural injury changes the actor's physical
                    # capabilities immediately for every later action in this
                    # same shared timeline.
                    equipment[target_ref] = self._personal_equipment_profile(target_ref, target)
                    apply_transient_player_prop(target_ref)
                    controls[target_ref] = self._personal_controls(target, equipment[target_ref], effects)
                    timing[target_ref] = self._personal_timing_profile(target, equipment[target_ref], controls[target_ref], effects)
                    advance_physiology(resolve_at)
                    if anatomical_resolution.get("irreversible"):
                        changed_structures = apply_irreversible_anatomy(
                            target, anatomical_resolution,
                            at=str(self._world_time()), source_weapon=weapon_id,
                        )
                        wound["permanent_anatomy"] = True
                        wound["anatomical_outcome"] = str(anatomical_resolution.get("outcome"))
                        wound["permanent_structure_changes"] = changed_structures
                        wound["recovery_rule"] = "ordinary recovery can heal the wound but cannot regenerate absent/destroyed anatomy"
                        if str(target.get("life_status", target.get("status", "active"))).lower() in {"dead", "deceased"}:
                            self._set_person_health(target, "dead")
                            target.setdefault("combat_state", {})["incapacitated"] = True
                            target["combat_state"]["incapacitated_reason"] = str(anatomical_resolution.get("outcome"))
                            target["combat_state"]["incapacitated_at_s"] = round(resolve_at, 6)
                        anatomy_event = {
                            "id": action["id"] + "_anatomy",
                            "kind": "anatomical_state",
                            "actor_ref": target_ref,
                            "action": str(anatomical_resolution.get("outcome")),
                            "side": anatomical_resolution.get("side"),
                            "structure": anatomical_resolution.get("structure"),
                            "changed_structures": changed_structures,
                            "permanent": True,
                            "at_s": round(resolve_at, 3),
                        }
                        trace.append(anatomy_event); must_render.append(anatomy_event["id"])
                    if action.get("mounted_body_collision") and severity in {"moderate", "serious", "critical"}:
                        target.setdefault("combat_state", {})["knocked_down_at"] = str(self._world_time())
                        begin_fall(target_ref, severity=severity, at_s=resolve_at, reason="mounted_collision", source_event_id=action["id"])
                fatal_anatomy = str(target.get("life_status", target.get("status", "active"))).lower() in {"dead", "deceased"}
                if zone == "forearms_hands" and severity in {"moderate", "serious", "critical"}:
                    disarmed_ref = target_ref
                    target_state = target.setdefault("combat_state", {})
                    target_state.update({
                        "disarmed_weapon_id": target_eq.get("best_weapon"),
                        "at": str(self._world_time()),
                        "location_ref": self._person_location(target),
                        "reason": "grip impairment from personal combat",
                    })
                    if target_ref == self.PLAYER_ACTOR and isinstance(target_eq.get("transient_improvised_prop"), Mapping):
                        transient_player_prop_state["status"] = "dropped"
                    disarm_event = {
                        "id": action["id"] + "_disarm",
                        "kind": "equipment_state",
                        "actor_ref": target_ref,
                        "action": "weapon_dropped_from_impaired_grip",
                        "weapon_id": target_eq.get("best_weapon"),
                        "at_s": round(resolve_at, 3),
                    }
                    trace.append(disarm_event)
                    must_render.append(disarm_event["id"])

                # A material hit decides a 1v1 slice the same way it always did,
                # but in a multi-person scene one wounded participant is not the
                # same thing as the whole opposing side being defeated.
                if target_ref == self.PLAYER_ACTOR:
                    winner_ref = actor_ref
                    outcome = "loss"
                elif target_ref in hostile_side:
                    if not any(active(ref) for ref in hostile_side):
                        winner_ref = actor_ref
                        outcome = "win" if actor_ref in player_side else "loss"
                    elif len(hostile_side) == 1:
                        winner_ref = actor_ref
                        outcome = "win" if actor_ref in player_side else "loss"
                    else:
                        winner_ref = None
                        outcome = "engaged"
                else:
                    winner_ref = None
                    outcome = "engaged"
                if not spar:
                    boundary_kind = "opponent_wounded" if target_ref in hostile_side else ("player_wounded" if target_ref == self.PLAYER_ACTOR else "ally_wounded")
                    if disarmed_ref:
                        boundary_kind = "opponent_disarmed" if disarmed_ref in hostile_side else ("player_disarmed" if disarmed_ref == self.PLAYER_ACTOR else "ally_disarmed")
                    candidate_boundary = {
                        "kind": boundary_kind,
                        "player_decision_required": target_ref in hostile_side,
                        "reason": "material combat state changed",
                        "at_s": round(resolve_at, 3),
                    }
                    if fatal_anatomy:
                        candidate_boundary["kind"] = "opponent_dead" if target_ref in hostile_side else ("player_dead" if target_ref == self.PLAYER_ACTOR else "ally_dead")
                        candidate_boundary["player_decision_required"] = False
                        candidate_boundary["reason"] = "the resolved anatomical contact established an immediately terminal physical state"
                    elif severity == "critical" and lethal_intent and target_ref in hostile_side:
                        candidate_boundary["kind"] = "lethal_follow_through_available"
                        candidate_boundary["player_decision_required"] = True
                    # Player death always stops after the current simultaneous
                    # contact group. Other material changes stop only when the
                    # caller requested a protected decision boundary.
                    if target_ref == self.PLAYER_ACTOR and fatal_anatomy:
                        pending_boundary = candidate_boundary
                    elif stop_on_decision:
                        pending_boundary = candidate_boundary

            for ref in actors:
                schedule(ref)

        if boundary is None and pending_boundary is not None:
            boundary = pending_boundary

        if boundary is None:
            if spar:
                outcome = "draw"
                boundary = {
                    "kind": "spar_complete",
                    "player_decision_required": False,
                    "reason": "controlled training continued for the requested interval after the narrated action-ready sample",
                }
            else:
                outcome = "engaged"
                boundary = {
                    "kind": "separation_or_stalemate",
                    "player_decision_required": True,
                    "reason": "the current continuous-time tactical phase ended without a decisive material injury",
                    "at_s": round(phase_horizon_seconds, 3),
                }

        if spar:
            exact_elapsed_seconds = requested_seconds
        else:
            boundary_time = _num(boundary.get("at_s")) if isinstance(boundary, Mapping) else 0.0
            exact_elapsed_seconds = min(requested_seconds, max(0.1, resolved_time, boundary_time))

        # Objective identity and progress survive every internal processing
        # segment.  Multi-target objectives therefore cannot reset when one
        # target falls, and incapacitated bodies remain part of the objective
        # roster even though they no longer schedule actions.
        objective_state = evaluate_objective(
            objective_spec, people, active,
            positions=geometry_positions(exact_elapsed_seconds),
            elapsed_seconds=exact_elapsed_seconds,
        )
        if objective_state.get("completed") and not spar:
            outcome = "win"
            winner_ref = self.PLAYER_ACTOR
            if not boundary or str(boundary.get("kind")) == "separation_or_stalemate":
                boundary = {
                    "kind": "objective_completed",
                    "player_decision_required": False,
                    "reason": "all required exact-combat objective targets satisfied the registered objective rule",
                    "at_s": round(exact_elapsed_seconds, 3),
                }
        elif objective_state.get("failed") and not spar:
            outcome = "loss"
            if not boundary or str(boundary.get("kind")) == "separation_or_stalemate":
                boundary = {
                    "kind": "objective_failed",
                    "player_decision_required": False,
                    "reason": "a protected exact-combat objective condition failed",
                    "at_s": round(exact_elapsed_seconds, 3),
                }

        # Persist the local physical scene in each exact participant. Timers are
        # stored as *remaining* duration so the next combat segment starts from
        # the same body/weapon/defense commitment rather than receiving a free
        # reset at the transaction boundary.
        for ref in actors:
            x_now, y_now = position_at(ref, exact_elapsed_seconds)
            state = people[ref].setdefault("combat_state", {})
            state["local_combat_state"] = {
                "encounter_id": encounter_id,
                "objective_id": objective_spec["objective_id"],
                "position": {
                    "x_m": round(x_now, 6),
                    "y_m": round(y_now, 6),
                    "elevation_m": round(_num(positions[ref].get("elevation_m"), 0.0), 6),
                    "facing_deg": round(_num(body_state[ref].get("facing_deg"), positions[ref].get("facing_deg", 0.0)) % 360.0, 6),
                    "radius_m": round(actor_clearance_radius(ref), 6),
                },
                "action_recovery_remaining_s": round(max(0.0, _num(ready_at.get(ref), 0.0) - exact_elapsed_seconds), 6),
                "defense_recovery_remaining_s": round(max(0.0, _num(defense_ready_at.get(ref), 0.0) - exact_elapsed_seconds), 6),
                "weapon_recovery_remaining_s": round(max(0.0, _num(weapon_guard_ready_at.get(ref), 0.0) - exact_elapsed_seconds), 6),
                "shield_recovery_remaining_s": round(max(0.0, _num(shield_guard_ready_at.get(ref), 0.0) - exact_elapsed_seconds), 6),
                "active_defense_load": round(decayed_active_defense_load(
                    _num(body_state[ref].get("active_defense_load"), 0.0),
                    last_update_s=_num(body_state[ref].get("active_defense_last_update_s"), 0.0),
                    at_s=exact_elapsed_seconds,
                    recovery_window_s=active_defense_recovery_window_seconds(timing[ref], active_defense_model),
                ), 6),
                "active_defense_recent_sources": dict(body_state[ref].get("active_defense_recent_sources", {})),
                "guard_center_deg": round(_num(body_state[ref].get("guard_center_deg"), 0.0) % 360.0, 6),
                "weapon_center_deg": round(_num(body_state[ref].get("weapon_center_deg"), 0.0) % 360.0, 6),
                "shield_center_deg": round(_num(body_state[ref].get("shield_center_deg"), 0.0) % 360.0, 6),
                "balance": round(_clamp(_num(body_state[ref].get("balance"), 1.0), 0.0, 1.0), 6),
                "last_defense_angle_deg": body_state[ref].get("last_defense_angle_deg"),
                "last_defense_method": body_state[ref].get("last_defense_method"),
                "last_dodge_vector": list(body_state[ref].get("last_dodge_vector", (0.0, 0.0))),
                "movement_velocity_xy_mps": list(body_state[ref].get("movement_velocity_xy_mps", (0.0, 0.0))) if _num(body_state[ref].get("movement_velocity_until_s"), 0.0) > exact_elapsed_seconds else [0.0, 0.0],
                "movement_velocity_remaining_s": round(max(0.0, _num(body_state[ref].get("movement_velocity_until_s"), 0.0) - exact_elapsed_seconds), 6),
                "posture": str(body_state[ref].get("posture", "standing")),
                "saved_at_segment_s": round(exact_elapsed_seconds, 6),
            }
            if ref == self.PLAYER_ACTOR and isinstance(transient_player_prop_state, Mapping):
                state["local_combat_state"]["improvised_prop_state"] = {
                    key: transient_player_prop_state.get(key)
                    for key in ("fact_ref", "source_session_ref", "source_location_ref", "form", "material", "condition", "condition_pct", "status", "skill_name")
                    if transient_player_prop_state.get(key) is not None
                }
            state["combat_objective_state"] = {
                "objective_id": objective_state["objective_id"],
                "mode": objective_state["mode"],
                "required_target_refs": list(objective_state["required_target_refs"]),
                "progress_milli": int(objective_state["progress_milli"]),
                "completed": bool(objective_state["completed"]),
                "failed": bool(objective_state["failed"]),
            }
        elapsed_milliseconds = max(1, int(round(exact_elapsed_seconds * 1000.0)))
        elapsed_seconds = max(1, int(math.ceil(exact_elapsed_seconds)))
        # Preserve exact sub-second event timing with canonical integer milliseconds
        # in receipts; *_s fields remain narration-friendly decimal projections.
        for event in trace:
            for seconds_key, millis_key in (
                ("start_at_s", "start_at_ms"),
                ("complete_at_s", "complete_at_ms"),
                ("contact_at_s", "contact_at_ms"),
                ("recovery_complete_at_s", "recovery_complete_at_ms"),
                ("reaction_ready_at_s", "reaction_ready_at_ms"),
                ("at_s", "at_ms"),
            ):
                if seconds_key in event:
                    event[millis_key] = int(round(_num(event.get(seconds_key)) * 1000.0))
        exertion_minutes = max(1.0 / 60.0, exact_elapsed_seconds / 60.0)
        p_burden = p_eq.get("burden", {}) if isinstance(p_eq.get("burden"), Mapping) else {}
        o_burden = o_eq.get("burden", {}) if isinstance(o_eq.get("burden"), Mapping) else {}
        fatigue_gained: dict[str, int] = {}
        for ref in actors:
            eq_now = equipment[ref]
            burden_now = eq_now.get("burden", {}) if isinstance(eq_now.get("burden"), Mapping) else {}
            _, attrs_now = _stats(people[ref])
            endurance = max(0.0, _num(attrs_now.get("Endurance")))
            burden_factor = max(0.55, _num(burden_now.get("fatigue_multiplier"), 1.0))
            rate = endurance_fatigue_rate_factor(endurance)
            baseline = exertion_minutes * 0.45 * burden_factor
            action_cost = action_exertion[ref] * burden_factor * 0.45
            gain = max(0, int(math.ceil((baseline + action_cost) * rate - 1e-9)))
            fatigue_gained[ref] = gain
            _set_fatigue(people[ref], _fatigue(people[ref]) + gain)

        p_score = (p_ctrl["attack"] + max(p_ctrl["parry"], p_ctrl["block"], p_ctrl["dodge"])) / 2.0
        o_score = (o_ctrl["attack"] + max(o_ctrl["parry"], o_ctrl["block"], o_ctrl["dodge"])) / 2.0
        start_state = {
            "distance_m": round(start_distance, 2),
            "participant_positions": start_positions,
            "local_obstacles": [dict(row) for row in local_obstacles],
            "player_side_refs": sorted(player_side),
            "hostile_side_refs": sorted(hostile_side),
            "participant_health": dict(initial_participant_health),
            "participant_fatigue": dict(initial_participant_fatigue),
            "player_weapon_id": p_eq.get("best_weapon"),
            "player_ranged_weapon_id": p_eq.get("ranged_weapon_id"),
            "opponent_weapon_id": o_eq.get("best_weapon"),
            "opponent_ranged_weapon_id": o_eq.get("ranged_weapon_id"),
            "player_weapon_reach_m": round(p_reach, 2),
            "opponent_weapon_reach_m": round(o_reach, 2),
        }
        end_state = {
            "distance_m": round(distance_between(self.PLAYER_ACTOR, opponent_ref, exact_elapsed_seconds), 2),
            "participant_positions": {
                ref: {
                    "x_m": round(position_at(ref, exact_elapsed_seconds)[0], 4),
                    "y_m": round(position_at(ref, exact_elapsed_seconds)[1], 4),
                    "elevation_m": round(_num(positions[ref].get("elevation_m"), 0.0), 4),
                    "facing_deg": round(_num(body_state[ref].get("facing_deg"), positions[ref].get("facing_deg", 0.0)) % 360.0, 3),
                    "radius_m": round(actor_clearance_radius(ref), 4),
                    "posture": str(body_state[ref].get("posture", "standing")),
                }
                for ref in actors
            },
            "player_health": self._person_health(player),
            "opponent_health": self._person_health(opponent),
            "participant_health": {ref: self._person_health(people[ref]) for ref in actors},
            "participant_fatigue": {ref: _fatigue(people[ref]) for ref in actors},
            "active_defense_load_by_actor": {
                ref: round(
                    decayed_active_defense_load(
                        _num(body_state[ref].get("active_defense_load"), 0.0),
                        last_update_s=_num(body_state[ref].get("active_defense_last_update_s"), 0.0),
                        at_s=exact_elapsed_seconds,
                        recovery_window_s=active_defense_recovery_window_seconds(timing[ref], active_defense_model),
                    ),
                    5,
                )
                for ref in actors
            },
            "active_participant_refs": [ref for ref in actors if active(ref)],
            "disarmed_ref": disarmed_ref,
            "material_wound": wound,
            "projectile_ammunition_remaining": {ref: dict(values) for ref, values in projectile_ammunition.items()},
            "fatigue_gained": fatigue_gained,
            "action_exertion": {ref: round(value, 4) for ref, value in action_exertion.items()},
            "transient_exertion_factor_by_actor": {
                ref: round(transient_exertion_factor(ref), 5) for ref in actors
            },
        }
        p_eq_final = equipment[self.PLAYER_ACTOR]
        p_burden_final = p_eq_final.get("burden", {}) if isinstance(p_eq_final.get("burden"), Mapping) else {}
        player_equipment = {
            "best_weapon": p_eq_final.get("best_weapon"),
            "skill_name": p_eq_final.get("skill_name"),
            "equipped_item_ids": p_eq_final.get("equipped_item_ids", []),
            "total_load_kg": round(_num(p_burden_final.get("total_load_kg")), 2),
            "load_ratio": round(_num(p_burden_final.get("load_ratio")), 4),
            "movement_factor": round(_num(p_burden_final.get("movement_factor"), 1.0), 4),
            "fatigue_multiplier": round(_num(p_burden_final.get("fatigue_multiplier"), 1.0), 4),
            "improvised_prop": dict(transient_player_prop_state) if isinstance(transient_player_prop_state, Mapping) else None,
        }
        opponent_equipment = {
            "best_weapon": o_eq.get("best_weapon"),
            "skill_name": o_eq.get("skill_name"),
            "equipped_item_ids": o_eq.get("equipped_item_ids", []),
        }
        participant_equipment = {
            ref: {
                "best_weapon": equipment[ref].get("best_weapon"),
                "ranged_weapon_id": equipment[ref].get("ranged_weapon_id"),
                "skill_name": equipment[ref].get("skill_name"),
                "equipped_item_ids": list(equipment[ref].get("equipped_item_ids", [])),
                "improvised_prop_fact_ref": (equipment[ref].get("transient_improvised_prop") or {}).get("fact_ref"),
            }
            for ref in actors
        }
        for row in combo_links:
            if row["status"] == "pending":
                row["status"] = "not_reached_in_slice"
        narration_contract = {
            "must_render": must_render,
            "may_compress": [x for x in may_compress if x not in must_render],
            "gm_private_director_use": [
                "start_state and end_state exact geometry",
                "full causal_trace including simultaneous contacts and defensive commitment",
                "team_tactical_plans and intent_sequence",
                "participant health, fatigue, equipment, readiness and actual contact results",
            ],
            "player_output_must_not_state_without_lawful_observation": [
                "hidden opponent numeric stats or control scores",
                "causal seed or deterministic jitter",
                "unseen intent, hidden tactical reasoning, or actors Wei has not detected",
            ],
            "do_not_reveal": [
                "hidden opponent numeric stats or control scores",
                "causal seed or deterministic jitter",
                "unseen intent, hidden tactical reasoning, or actors Wei has not detected",
            ],
            "director_rule": "The AI GM may use the complete resolved combat packet as omniscient director context so hidden causes and simultaneous actors remain coherent. That private access does not make hidden facts Wei's knowledge; reveal them only through what Wei can perceive, infer from visible effects, remember, or lawfully learn.",
            "rule": "Render the timestamped physical chain that caused every material result. In multi-person scenes preserve local positions, incoming attack angles, cumulative active-defense load, distinct-attacker pressure, shared defensive recovery, shield/weapon orientation, dodge displacement and simultaneous contact-group causality; never narrate sequential fresh-neutral defenses when the trace shows saturation or body commitment. State intended aim separately from actual contact location; include projectile release/flight when relevant, defense/evasion/interception, shield then armor penetration/deflection, confirmed anatomy and equipment failure. Never narrate the intended body part as the confirmed hit unless actual_contact_* establishes it, and do not replace causality with a score summary or turn order.",
        }
        gm_private_director_context = {
            "privacy": "gm_private_scene_bounded_omniscient_truth_not_player_knowledge",
            "participant_identities": {
                ref: {
                    key: people[ref].get(key)
                    for key in ("name", "role", "rank", "military_rank", "family", "affiliation", "life_status")
                    if people[ref].get(key) not in (None, "", [], {})
                }
                for ref in actors
            },
            "participant_capability_and_condition": {
                ref: {
                    "alignment": "player" if ref == self.PLAYER_ACTOR else ("opponent" if ref in hostile_side else "ally"),
                    "attributes": dict(people[ref].get("attributes", {})) if isinstance(people[ref].get("attributes"), Mapping) else {},
                    "skills": dict(people[ref].get("skills", {})) if isinstance(people[ref].get("skills"), Mapping) else {},
                    "health": people[ref].get("health_status", people[ref].get("health")),
                    "fatigue": _fatigue(people[ref]),
                    "combat_doctrine_ref": people[ref].get("combat_doctrine_ref"),
                    "equipment": participant_equipment.get(ref, {}),
                    "start_state": {
                        "position": start_state.get("participant_positions", {}).get(ref),
                        "health": start_state.get("participant_health", {}).get(ref),
                        "fatigue": start_state.get("participant_fatigue", {}).get(ref),
                    },
                    "end_state": {
                        "position": end_state.get("participant_positions", {}).get(ref),
                        "health": end_state.get("participant_health", {}).get(ref),
                        "fatigue": end_state.get("participant_fatigue", {}).get(ref),
                        "active_defense_load": end_state.get("active_defense_load_by_actor", {}).get(ref),
                        "action_exertion": end_state.get("action_exertion", {}).get(ref),
                    },
                }
                for ref in actors
            },
            "use_sources": ["start_state", "causal_trace", "end_state", "team_tactical_plans", "intent_sequence"],
            "disclosure_rule": "Use all resolved scene truth to direct coherent prose, distinct combat behavior and simultaneous causality, but disclose only what Tang Wei could perceive, infer, remember, hear, or lawfully learn. Mechanical outcomes are fixed by the resolver and cannot be changed by narration.",
        }
        return {
            "outcome": outcome,
            "spar": spar,
            "winner_ref": winner_ref,
            "start_state": start_state,
            "causal_trace": trace,
            "end_state": end_state,
            "objective_state": objective_state,
            "team_tactical_plans": team_plan_history,
            "decision_boundary": boundary,
            "narration_contract": narration_contract,
            "gm_private_director_context": gm_private_director_context,
            "intent_sequence": combo_links,
            "elapsed_seconds": elapsed_seconds,
            "elapsed_milliseconds": elapsed_milliseconds,
            "requested_duration_minutes": requested_minutes,
            "timing_model": {
                "mode": "continuous_action_ready",
                "spatial_mode": "local_2_5d_shared_body_state",
                "simultaneous_contact_window_ms": int(round(simultaneous_window_s * 1000.0)),
                "trace_window_milliseconds": int(round(phase_horizon_seconds * 1000.0)),
                "trace_window_seconds": round(phase_horizon_seconds, 3),
                "rule": "all exact participants on both sides share one local timeline; allies and enemies continue scheduling while any one fighter attacks; being forced to defend consumes that defender's shared body/weapon/foot commitment and interrupts a pending action unless its contact is already inside the simultaneous-contact window; ordinary dodge/parry/block consume cumulative whole-body active-defense load that decays continuously while weapon/shield readiness remains separate; distinct attackers inside the recovery window add conflicting-source pressure; near-simultaneous contacts share one pre-contact geometry snapshot instead of resetting the defender",
            },
            "sequencing_model": {
                "mode": "adaptive_physical_sequence",
                "rule": "undeclared actions are selected from current distance, target structure/coverage, recent failures/repetitions and the defender's demonstrated response; explicit player method/target wording always overrides automation",
                "recent_action_memory": {ref: list(rows) for ref, rows in action_memory.items()},
            },
            "player_score": int(round(p_score * 100)),
            "opponent_score": int(round(o_score * 100)),
            "player_equipment": player_equipment,
            "opponent_equipment": opponent_equipment,
            "participant_equipment": participant_equipment,
            "participant_refs": list(actors),
            "participant_positions": end_state["participant_positions"],
            "local_obstacles": [dict(row) for row in local_obstacles],
            "player_side_refs": sorted(player_side),
            "hostile_side_refs": sorted(hostile_side),
            "equipment_condition_changes": {
                ref: changes for ref, changes in equipment_condition_changes.items() if changes
            },
            "fired_projectiles": fired_projectiles,
            "projectile_recovery_candidates": [
                {**row, "recoverable_fraction": round(_clamp(_num(row.get("recovery_base"),0.0) * (0.90 if spar else 0.55), 0.0, 0.95), 5)}
                for row in fired_projectiles
            ],
            "mount_wounds": mount_wounds,
        }

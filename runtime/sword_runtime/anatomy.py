from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _side(intent: str, seed: int) -> str:
    text = intent.lower()
    if "right" in text:
        return "right"
    if "left" in text:
        return "left"
    return "right" if seed & 1 else "left"


def _target_structure(zone: str, intent: str, seed: int) -> tuple[str, str]:
    text = intent.lower()
    side = _side(text, seed)
    if zone == "forearms_hands":
        if "wrist" in text:
            return side, "wrist"
        if "hand" in text:
            return side, "hand"
        if "elbow" in text:
            return side, "elbow"
        return side, "forearm"
    if zone == "upper_arms":
        if "elbow" in text:
            return side, "elbow"
        if "shoulder" in text:
            return side, "shoulder"
        return side, "upper_arm"
    if zone == "lower_legs_feet":
        if "foot" in text:
            return side, "foot"
        if "ankle" in text:
            return side, "ankle"
        if "knee" in text:
            return side, "knee"
        return side, "lower_leg"
    if zone == "thighs":
        if "knee" in text:
            return side, "knee"
        if "hip" in text:
            return side, "hip"
        return side, "thigh"
    if zone == "head":
        if "eye" in text:
            return side, "eye"
        return side, "head"
    if zone == "neck":
        return "midline", "neck"
    if zone == "upper_torso":
        if "armpit" in text or "axilla" in text or "underarm" in text:
            return side, "axilla"
        return "midline", "upper_torso"
    if zone == "lower_torso":
        return "midline", "lower_torso"
    return "midline", zone


def anatomical_target(zone: str, declared_intent: str | None, seed: int) -> dict[str, str]:
    side, structure = _target_structure(zone, str(declared_intent or ""), seed)
    return {"side": side, "structure": structure}


# Multipliers are applied to the exact contacted channel protection already used
# by armor resolution.  Thus a bare wrist, a mail-covered wrist, and a plated
# wrist have different required impact indexes; this is not a second armor roll.
_COMPLETE_SEVERANCE_MULTIPLIER = {
    "hand": 2.45,
    "wrist": 3.05,
    "forearm": 3.80,
    "elbow": 4.30,
    "upper_arm": 4.85,
    "shoulder": 5.60,
    "foot": 2.80,
    "ankle": 3.30,
    "lower_leg": 4.20,
    "knee": 4.70,
    "thigh": 5.35,
    "hip": 6.00,
    "neck": 6.10,
}

_EYE_DESTRUCTION_MULTIPLIER = 1.45
_JOINT_DESTRUCTION_MULTIPLIER = {
    "wrist": 2.35,
    "elbow": 3.25,
    "shoulder": 4.15,
    "ankle": 2.70,
    "knee": 3.55,
    "hip": 4.60,
}


# Exact soft-tissue / internal-structure candidates behind each contacted
# external structure. The personal-combat resolver has already established the
# actual body contact before this table is consulted. These are therefore not
# hit-location odds; they are structures physically available to that contact.
_SUBSTRUCTURES: dict[str, tuple[tuple[str, str], ...]] = {
    "hand": (("flexor_tendons", "tendon"), ("extensor_tendons", "tendon"), ("digital_vessels", "vessel"), ("digital_nerves", "nerve"), ("metacarpals", "bone")),
    "wrist": (("flexor_tendons", "tendon"), ("extensor_tendons", "tendon"), ("radial_artery", "major_vessel"), ("ulnar_artery", "major_vessel"), ("median_nerve", "nerve"), ("ulnar_nerve", "nerve"), ("distal_radius", "bone"), ("distal_ulna", "bone"), ("wrist_joint", "joint")),
    "forearm": (("forearm_flexors", "muscle"), ("forearm_extensors", "muscle"), ("radial_artery", "major_vessel"), ("ulnar_artery", "major_vessel"), ("median_nerve", "nerve"), ("ulnar_nerve", "nerve"), ("radial_nerve", "nerve"), ("radius", "bone"), ("ulna", "bone")),
    "elbow": (("elbow_joint", "joint"), ("distal_humerus", "bone"), ("proximal_radius", "bone"), ("proximal_ulna", "bone"), ("ulnar_nerve", "nerve"), ("brachial_artery", "major_vessel"), ("triceps_tendon", "tendon")),
    "upper_arm": (("biceps", "muscle"), ("triceps", "muscle"), ("brachial_artery", "major_vessel"), ("brachial_veins", "major_vessel"), ("median_nerve", "nerve"), ("radial_nerve", "nerve"), ("ulnar_nerve", "nerve"), ("humerus", "bone")),
    "shoulder": (("shoulder_joint", "joint"), ("rotator_cuff", "tendon"), ("brachial_plexus", "nerve"), ("axillary_artery", "major_vessel"), ("humeral_head", "bone"), ("clavicle", "bone")),
    "axilla": (("axillary_artery", "major_vessel"), ("axillary_vein", "major_vessel"), ("brachial_plexus", "nerve"), ("lung_apex", "lung"), ("shoulder_capsule", "joint")),
    "neck": (("carotid_artery", "major_vessel"), ("jugular_vein", "major_vessel"), ("trachea", "airway"), ("cervical_spine", "spine"), ("spinal_cord", "spine"), ("esophagus", "organ")),
    "head": (("skull", "bone"), ("brain", "brain"), ("jaw", "bone"), ("facial_vessels", "vessel")),
    "face": (("facial_bones", "bone"), ("jaw", "bone"), ("facial_vessels", "vessel"), ("facial_nerves", "nerve")),
    "upper_torso": (("ribs", "bone"), ("lung", "lung"), ("heart", "organ"), ("thoracic_aorta", "major_vessel"), ("subclavian_vessels", "major_vessel"), ("thoracic_spine", "spine")),
    "lower_torso": (("liver", "organ"), ("spleen", "organ"), ("kidney", "organ"), ("bowel", "organ"), ("abdominal_aorta", "major_vessel"), ("lumbar_spine", "spine"), ("pelvis", "bone")),
    "hip": (("hip_joint", "joint"), ("femoral_neck", "bone"), ("femoral_artery", "major_vessel"), ("sciatic_nerve", "nerve")),
    "thigh": (("quadriceps", "muscle"), ("hamstrings", "muscle"), ("femoral_artery", "major_vessel"), ("femoral_vein", "major_vessel"), ("sciatic_nerve", "nerve"), ("femur", "bone")),
    "knee": (("patellar_tendon", "tendon"), ("cruciate_ligaments", "tendon"), ("knee_joint", "joint"), ("distal_femur", "bone"), ("proximal_tibia", "bone"), ("popliteal_artery", "major_vessel"), ("common_peroneal_nerve", "nerve")),
    "lower_leg": (("tibia", "bone"), ("fibula", "bone"), ("calf_muscles", "muscle"), ("posterior_tibial_artery", "major_vessel"), ("peroneal_artery", "vessel"), ("common_peroneal_nerve", "nerve")),
    "ankle": (("ankle_joint", "joint"), ("achilles_tendon", "tendon"), ("distal_tibia", "bone"), ("distal_fibula", "bone"), ("posterior_tibial_artery", "major_vessel")),
    "foot": (("metatarsals", "bone"), ("foot_tendons", "tendon"), ("plantar_vessels", "vessel"), ("plantar_nerves", "nerve")),
    "eye": (("eye", "eye"),),
}

_MODE_CATEGORY_PRIORITY = {
    "cut": ("major_vessel", "vessel", "tendon", "nerve", "muscle", "joint", "bone", "organ", "lung", "airway", "spine", "brain", "eye"),
    "thrust": ("major_vessel", "organ", "lung", "airway", "spine", "brain", "nerve", "bone", "joint", "muscle", "vessel", "tendon", "eye"),
    "blunt": ("bone", "joint", "brain", "spine", "organ", "lung", "muscle", "nerve", "major_vessel", "vessel", "tendon", "airway", "eye"),
}


def _damage_status(category: str, mode: str, severity: int) -> str:
    severity = max(1, min(4, int(severity)))
    if category in {"major_vessel", "vessel"}:
        return (("contused", "lacerated", "major_laceration", "transected") if mode != "blunt" else ("contused", "wall_injury", "ruptured", "catastrophic_rupture"))[severity - 1]
    if category == "tendon": return ("strained", "damaged", "partially_severed", "severed")[severity - 1]
    if category == "nerve": return ("irritated", "damaged", "major_injury", "severed")[severity - 1]
    if category == "bone":
        return (("bruised", "fractured", "displaced_fracture", "comminuted_fracture") if mode == "blunt" else ("scored", "notched_or_perforated", "deeply_cut_or_perforated", "transected_or_shattered"))[severity - 1]
    if category == "joint": return ("sprained", "damaged", "unstable", "destroyed")[severity - 1]
    if category == "muscle":
        return (("bruised", "lacerated", "deep_laceration", "near_complete_disruption") if mode != "blunt" else ("bruised", "contused", "crushed", "major_crush"))[severity - 1]
    if category == "lung": return ("contused", "penetrated", "major_penetration", "collapsed_or_destroyed")[severity - 1]
    if category == "airway": return ("contused", "damaged", "opened", "transected_or_collapsed")[severity - 1]
    if category == "spine": return ("contused", "fractured_or_damaged", "unstable_or_cord_injury", "catastrophic_disruption")[severity - 1]
    if category == "brain": return ("concussion", "contusion", "severe_brain_injury", "catastrophic_brain_injury")[severity - 1]
    if category == "organ": return ("contused", "lacerated_or_penetrated", "major_laceration_or_penetration", "catastrophic_disruption")[severity - 1]
    if category == "eye": return ("injured", "damaged", "severely_damaged", "destroyed")[severity - 1]
    return ("injured", "damaged", "severely_damaged", "destroyed")[severity - 1]


_PERMANENT_STRUCTURAL_STATUSES = {
    ("tendon", "severed"),
    ("nerve", "severed"),
    ("joint", "destroyed"),
    ("bone", "transected_or_shattered"),
    ("lung", "collapsed_or_destroyed"),
    ("spine", "catastrophic_disruption"),
    ("brain", "catastrophic_brain_injury"),
    ("eye", "destroyed"),
}


def _structural_bleeding_source(name: str, category: str, severity: int) -> tuple[float, bool]:
    """Return blood-loss units/minute and whether the source is predominantly internal."""
    severity = max(1, min(4, int(severity)))
    if category == "major_vessel":
        rates = (4.0, 15.0, 38.0, 78.0)
        internal = any(token in name for token in ("aorta", "subclavian", "axillary", "popliteal"))
        return rates[severity - 1], internal
    if category == "vessel":
        return (1.0, 4.0, 10.0, 18.0)[severity - 1], False
    if category == "organ":
        if name == "heart":
            return (3.0, 14.0, 42.0, 82.0)[severity - 1], True
        if name in {"liver", "spleen"}:
            return (2.0, 8.0, 22.0, 42.0)[severity - 1], True
        if name == "kidney":
            return (1.0, 6.0, 15.0, 28.0)[severity - 1], True
        return (0.5, 2.0, 6.0, 12.0)[severity - 1], True
    if category == "lung":
        return (1.0, 4.0, 11.0, 24.0)[severity - 1], True
    if category == "bone":
        return (0.2, 1.0, 3.0, 7.0)[severity - 1], True
    if category == "muscle":
        return (0.4, 1.5, 4.0, 8.0)[severity - 1], False
    return 0.0, False


def resolve_structural_injury(*, zone: str, structure: str, side: str, mode: str, severity: str, impact_index: float, penetration_index: float, contact_grade: str, seed: int) -> dict[str, Any]:
    """Resolve exact tissue/internal structures after body contact is proven."""
    severity_index = {"none": 0, "minor": 1, "moderate": 2, "serious": 3, "severe": 3, "critical": 4}.get(str(severity).lower(), 0)
    result: dict[str, Any] = {
        "external_zone": str(zone), "external_structure": str(structure), "side": str(side), "mode": str(mode),
        "severity_index": severity_index, "damaged_structures": [], "major_vessel_damage": False,
        "bleeding_sources": [], "bleeding_units_per_minute": 0.0, "internal_bleeding_units_per_minute": 0.0,
        "respiratory_compromise": 0.0, "neurological_impairment": 0.0,
        "functional_effects": {"attack_factor": 1.0, "parry_factor": 1.0, "block_factor": 1.0, "movement_factor": 1.0, "awareness_factor": 1.0},
    }
    if severity_index <= 0:
        return result
    candidates = list(_SUBSTRUCTURES.get(str(structure), _SUBSTRUCTURES.get(str(zone), ((str(structure), "ordinary_zone"),))))
    priority = _MODE_CATEGORY_PRIORITY.get(str(mode), _MODE_CATEGORY_PRIORITY["blunt"])
    rank = {category: index for index, category in enumerate(priority)}
    # Mode biases which structures are more vulnerable, but it does not make a
    # named artery or organ inevitable on every contact.  Seeded local geometry
    # can move the actual line among the physically available structures.
    candidates.sort(key=lambda row: (
        # Technique/mode creates a vulnerability bias, while seeded local
        # geometry remains strong enough that an artery or organ is never an
        # automatic consequence merely because that category ranks first.
        rank.get(row[1], 99) + (abs(int(seed)) * 11 + sum((i + 1) * ord(c) for i, c in enumerate(row[0]))) % 37,
        row[0],
    ))
    count = 1 if severity_index <= 2 else (2 if severity_index == 3 else 3)
    if str(contact_grade) == "exceptional" and severity_index >= 3:
        count += 1
    selected: list[tuple[str, str]] = []
    used_categories: set[str] = set()
    for candidate in candidates:
        # Multi-structure wounds usually cross different tissue classes before
        # duplicating the same class. Critical/exceptional contacts may still
        # reach a second vessel, bone, etc. after the diverse pass.
        if candidate[1] not in used_categories:
            selected.append(candidate)
            used_categories.add(candidate[1])
            if len(selected) >= count:
                break
    if len(selected) < count:
        for candidate in candidates:
            if candidate in selected:
                continue
            selected.append(candidate)
            if len(selected) >= count:
                break
    function = dict(result["functional_effects"]); respiratory = 0.0; neuro = 0.0
    for name, category in selected:
        status = _damage_status(category, str(mode), severity_index)
        permanent = (category, status) in _PERMANENT_STRUCTURAL_STATUSES
        result["damaged_structures"].append({"structure": name, "category": category, "status": status, "severity_index": severity_index, "permanent_sequela": permanent})
        bleed_rate, internal_bleed = _structural_bleeding_source(name, category, severity_index)
        if bleed_rate > 0:
            result["bleeding_sources"].append({"structure": name, "category": category, "rate_units_per_minute": round(bleed_rate, 4), "internal": internal_bleed})
        if category == "major_vessel" and severity_index >= 2: result["major_vessel_damage"] = True
        if category == "tendon":
            factor = {1: .90, 2: .68, 3: .30, 4: .08}[severity_index]
            if str(structure) in {"hand", "wrist", "forearm", "elbow", "upper_arm", "shoulder"}:
                function["attack_factor"] = min(function["attack_factor"], factor); function["parry_factor"] = min(function["parry_factor"], factor); function["block_factor"] = min(function["block_factor"], max(.05, factor * .90))
            else: function["movement_factor"] = min(function["movement_factor"], factor)
        elif category == "nerve":
            factor = {1: .92, 2: .72, 3: .38, 4: .10}[severity_index]
            if str(structure) in {"hand", "wrist", "forearm", "elbow", "upper_arm", "shoulder", "axilla"}:
                function["attack_factor"] = min(function["attack_factor"], factor); function["parry_factor"] = min(function["parry_factor"], factor); function["block_factor"] = min(function["block_factor"], factor)
            else: function["movement_factor"] = min(function["movement_factor"], factor)
            neuro = max(neuro, (1.0 - factor) * 100.0)
        elif category in {"bone", "joint"}:
            factor = {1: .90, 2: .62, 3: .28, 4: .06}[severity_index]
            if str(structure) in {"hip", "thigh", "knee", "lower_leg", "ankle", "foot"}: function["movement_factor"] = min(function["movement_factor"], factor)
            elif str(structure) in {"hand", "wrist", "forearm", "elbow", "upper_arm", "shoulder"}:
                function["attack_factor"] = min(function["attack_factor"], factor); function["parry_factor"] = min(function["parry_factor"], factor); function["block_factor"] = min(function["block_factor"], factor)
        elif category == "lung": respiratory = max(respiratory, {1: 12.0, 2: 32.0, 3: 58.0, 4: 90.0}[severity_index])
        elif category == "airway": respiratory = max(respiratory, {1: 18.0, 2: 45.0, 3: 78.0, 4: 100.0}[severity_index])
        elif category == "brain":
            factor = {1: .82, 2: .58, 3: .28, 4: .05}[severity_index]; function["awareness_factor"] = min(function["awareness_factor"], factor); neuro = max(neuro, (1.0 - factor) * 100.0)
        elif category == "spine":
            factor = {1: .88, 2: .60, 3: .22, 4: .02}[severity_index]; function["movement_factor"] = min(function["movement_factor"], factor); neuro = max(neuro, (1.0 - factor) * 100.0)
    total_bleeding = sum(_num(x.get("rate_units_per_minute")) for x in result.get("bleeding_sources", []) if isinstance(x, Mapping))
    internal_bleeding = sum(_num(x.get("rate_units_per_minute")) for x in result.get("bleeding_sources", []) if isinstance(x, Mapping) and bool(x.get("internal")))
    result["bleeding_units_per_minute"] = round(total_bleeding, 4)
    result["internal_bleeding_units_per_minute"] = round(internal_bleeding, 4)
    result["respiratory_compromise"] = round(respiratory, 3); result["neurological_impairment"] = round(neuro, 3)
    result["functional_effects"] = {key: round(float(value), 5) for key, value in function.items()}
    result["impact_index"] = round(max(0.0, _num(impact_index)), 3); result["penetration_index"] = round(max(0.0, _num(penetration_index)), 3)
    return result


def resolve_anatomical_contact(
    *,
    zone: str,
    mode: str,
    impact_index: float,
    penetration_index: float | None = None,
    channel_protection: float,
    contact_grade: str,
    declared_intent: str | None,
    seed: int,
    lethal_intent: bool = False,
    aim_side: str | None = None,
    aim_structure: str | None = None,
) -> dict[str, Any]:
    """Resolve irreversible anatomy from an already-established body contact.

    `impact_index` is the physical attack index that reached armor/body contact.
    `channel_protection` is the exact armor/uncovered resistance used by the
    existing contact resolver.  Irreversible outcomes require both enough impact
    and a geometrically clean contact; a large but glancing blow does not sever a
    limb merely because its abstract force number is high.
    """
    intent = str(declared_intent or "")
    derived_side, derived_structure = _target_structure(zone, intent, seed)
    side = str(aim_side or derived_side)
    structure = str(aim_structure or derived_structure)
    available_impact = max(0.0, _num(impact_index))
    available_penetration = max(0.0, _num(impact_index if penetration_index is None else penetration_index))
    protection = max(1.0, _num(channel_protection, 30.0))
    grade = str(contact_grade or "solid")
    clean = grade in {"clean", "exceptional"}
    exceptional = grade == "exceptional"
    result: dict[str, Any] = {
        "side": side,
        "structure": structure,
        "available_impact_index": round(available_impact, 3),
        "available_penetration_index": round(available_penetration, 3),
        "contacted_channel_protection": round(protection, 3),
        "irreversible": False,
        "outcome": "no_irreversible_anatomy",
    }

    if structure == "eye" and mode in {"cut", "thrust", "blunt"}:
        threshold = protection * _EYE_DESTRUCTION_MULTIPLIER
        result["required_impact_index"] = round(threshold, 3)
        available = available_impact if mode == "blunt" else max(available_penetration, available_impact * 0.35)
        if available >= threshold and grade not in {"denied", "glancing"}:
            result.update({"irreversible": True, "outcome": "eye_destroyed"})
        return result

    if mode == "cut" and structure in _COMPLETE_SEVERANCE_MULTIPLIER:
        threshold = protection * _COMPLETE_SEVERANCE_MULTIPLIER[structure]
        result["required_impact_index"] = round(threshold, 3)
        # Neck separation requires a deliberately lethal, exceptionally clean
        # line. Limb separation requires a clean line but not narrative fiat.
        legal_geometry = exceptional and lethal_intent if structure == "neck" else clean
        if legal_geometry and available_penetration >= threshold:
            result.update({
                "irreversible": True,
                "outcome": "complete_severance",
                "severance_level": structure,
            })
            return result

    if structure in _JOINT_DESTRUCTION_MULTIPLIER and mode in {"blunt", "cut"}:
        threshold = protection * _JOINT_DESTRUCTION_MULTIPLIER[structure]
        result.setdefault("required_impact_index", round(threshold, 3))
        available = available_impact if mode == "blunt" else max(available_penetration, available_impact * 0.40)
        if available >= threshold and clean:
            result.update({"irreversible": True, "outcome": "joint_destroyed"})
    return result


def _mark_structure(
    anatomy: MutableMapping[str, Any],
    key: str,
    *,
    status: str,
    at: str,
    source_weapon: str | None,
    cause: str,
) -> None:
    structures = anatomy.setdefault("structures", {})
    prior = structures.get(key) if isinstance(structures, Mapping) else None
    first_at = prior.get("first_destroyed_at") if isinstance(prior, Mapping) else None
    structures[key] = {
        "status": status,
        "permanent": True,
        "reversible_by_normal_recovery": False,
        "first_destroyed_at": first_at or at,
        "last_changed_at": at,
        "source_weapon": source_weapon,
        "cause": cause,
    }


def apply_structural_injury_state(
    person: MutableMapping[str, Any],
    resolution: Mapping[str, Any],
    *,
    at: str,
    source_weapon: str | None,
) -> list[str]:
    """Persist exact damaged substructures and durable sequelae.

    Ordinary soft-tissue recovery may resolve a wound record, but a structure
    explicitly established as severed/destroyed remains part of anatomy until a
    lawful treatment path changes it.  This prevents recovery-hours from silently
    restoring a severed tendon or destroyed joint.
    """
    damaged = resolution.get("damaged_structures") if isinstance(resolution.get("damaged_structures"), list) else []
    if not damaged:
        return []
    anatomy = person.setdefault("anatomy_state", {})
    state = anatomy.setdefault("structural_damage", {})
    side = str(resolution.get("side", "midline"))
    changed: list[str] = []
    for row in damaged:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("structure", "unknown"))
        category = str(row.get("category", "ordinary_zone"))
        status = str(row.get("status", "damaged"))
        key = f"{side}:{name}"
        prior = state.get(key) if isinstance(state.get(key), Mapping) else {}
        permanent = bool(row.get("permanent_sequela")) or (category, status) in _PERMANENT_STRUCTURAL_STATUSES
        state[key] = {
            "side": side, "structure": name, "category": category, "status": status,
            "severity_index": int(_num(row.get("severity_index"), _num(resolution.get("severity_index"), 0))),
            "permanent_sequela": permanent,
            "reversible_by_ordinary_recovery": not permanent,
            "first_damaged_at": str(prior.get("first_damaged_at") or at),
            "last_changed_at": at, "source_weapon": source_weapon,
        }
        changed.append(key)
    if changed:
        history = anatomy.setdefault("structural_damage_history", [])
        history.append({"at": at, "side": side, "external_structure": resolution.get("external_structure"), "changed_structures": changed, "source_weapon": source_weapon})
        anatomy["structural_damage_history"] = history[-96:]
    return changed


def apply_irreversible_anatomy(
    person: MutableMapping[str, Any],
    resolution: Mapping[str, Any],
    *,
    at: str,
    source_weapon: str | None,
) -> list[str]:
    if not bool(resolution.get("irreversible")):
        return []
    anatomy = person.setdefault("anatomy_state", {})
    anatomy.setdefault(
        "rule",
        "Absent or destroyed anatomy is permanent. Ordinary recovery/treatment may heal the wound or stabilize the person but never regenerates an absent/destroyed structure.",
    )
    side = str(resolution.get("side", "midline"))
    structure = str(resolution.get("structure", "unknown"))
    outcome = str(resolution.get("outcome", "irreversible_damage"))
    changed: list[str] = []

    def mark(name: str, status: str) -> None:
        _mark_structure(anatomy, name, status=status, at=at, source_weapon=source_weapon, cause=outcome)
        changed.append(name)

    if outcome == "eye_destroyed":
        mark(f"{side}_eye", "destroyed")
    elif outcome == "joint_destroyed":
        mark(f"{side}_{structure}", "destroyed")
    elif outcome == "complete_severance":
        if side == "midline" and structure == "neck":
            mark("neck", "severed")
            mark("head", "absent")
            person["life_status"] = "dead"
        else:
            distal: dict[str, tuple[str, ...]] = {
                "hand": ("hand",),
                "wrist": ("wrist", "hand"),
                "forearm": ("forearm", "wrist", "hand"),
                "elbow": ("elbow", "forearm", "wrist", "hand"),
                "upper_arm": ("upper_arm", "elbow", "forearm", "wrist", "hand"),
                "shoulder": ("shoulder", "upper_arm", "elbow", "forearm", "wrist", "hand"),
                "foot": ("foot",),
                "ankle": ("ankle", "foot"),
                "lower_leg": ("lower_leg", "ankle", "foot"),
                "knee": ("knee", "lower_leg", "ankle", "foot"),
                "thigh": ("thigh", "knee", "lower_leg", "ankle", "foot"),
                "hip": ("hip", "thigh", "knee", "lower_leg", "ankle", "foot"),
            }
            parts = distal.get(structure, (structure,))
            for index, part in enumerate(parts):
                mark(f"{side}_{part}", "severed" if index == 0 else "absent")

    impairments = anatomy.setdefault("permanent_impairments", [])
    entry = {
        "at": at,
        "outcome": outcome,
        "side": side,
        "structure": structure,
        "changed_structures": changed,
        "source_weapon": source_weapon,
        "permanent": True,
    }
    if entry not in impairments:
        impairments.append(entry)
    anatomy["permanent_impairments"] = impairments[-64:]
    return changed


def anatomy_function_factors(person: Mapping[str, Any]) -> dict[str, float]:
    anatomy = person.get("anatomy_state") if isinstance(person.get("anatomy_state"), Mapping) else {}
    structures = anatomy.get("structures") if isinstance(anatomy.get("structures"), Mapping) else {}

    def unavailable(key: str) -> bool:
        row = structures.get(key)
        return isinstance(row, Mapping) and str(row.get("status")) in {"absent", "severed", "destroyed"}

    upper_losses = 0
    hand_losses = 0
    lower_losses = 0
    eye_losses = 0
    for side in ("left", "right"):
        if unavailable(f"{side}_hand") or unavailable(f"{side}_wrist"):
            hand_losses += 1
        if any(unavailable(f"{side}_{part}") for part in ("shoulder", "upper_arm", "elbow", "forearm")):
            upper_losses += 1
        if any(unavailable(f"{side}_{part}") for part in ("hip", "thigh", "knee", "lower_leg", "ankle", "foot")):
            lower_losses += 1
        if unavailable(f"{side}_eye"):
            eye_losses += 1

    if hand_losses >= 2 or upper_losses >= 2:
        hand_factor = 0.08
        block_factor = 0.05
    elif hand_losses == 1 or upper_losses == 1:
        hand_factor = 0.82
        block_factor = 0.62
    else:
        hand_factor = 1.0
        block_factor = 1.0

    if lower_losses >= 2:
        movement_factor = 0.06
    elif lower_losses == 1:
        movement_factor = 0.28
    else:
        movement_factor = 1.0

    awareness_factor = 0.60 if eye_losses >= 2 else (0.84 if eye_losses == 1 else 1.0)

    # Durable substructure sequelae survive ordinary wound closure.  Active,
    # reversible structural damage is already represented by the live injury;
    # only rows explicitly established as permanent are applied here.
    structural = anatomy.get("structural_damage") if isinstance(anatomy.get("structural_damage"), Mapping) else {}
    permanent_attack = permanent_parry = permanent_block = permanent_move = permanent_awareness = 1.0
    upper_tokens = ("flexor", "extensor", "median_nerve", "ulnar_nerve", "radial_nerve", "brachial_plexus", "humer", "radius", "ulna", "wrist", "elbow", "shoulder")
    lower_tokens = ("patellar", "cruciate", "achilles", "sciatic", "peroneal", "tibia", "fibula", "femur", "ankle", "knee", "hip", "foot")
    for row in structural.values() if isinstance(structural, Mapping) else ():
        if not isinstance(row, Mapping) or not bool(row.get("permanent_sequela")):
            continue
        name = str(row.get("structure", "")); category = str(row.get("category", "")); status = str(row.get("status", ""))
        severity = max(1, min(4, int(_num(row.get("severity_index"), 4))))
        severe_factor = {1: .85, 2: .62, 3: .32, 4: .10}[severity]
        if any(token in name for token in upper_tokens):
            permanent_attack = min(permanent_attack, severe_factor); permanent_parry = min(permanent_parry, severe_factor); permanent_block = min(permanent_block, max(.05, severe_factor * .90))
        if any(token in name for token in lower_tokens):
            permanent_move = min(permanent_move, severe_factor)
        if category == "spine" or "spinal_cord" in name:
            permanent_move = min(permanent_move, .04 if "catastrophic" in status else severe_factor)
        if category == "brain":
            permanent_awareness = min(permanent_awareness, .08 if "catastrophic" in status else severe_factor)
        if category == "lung" and "destroyed" in status:
            permanent_move = min(permanent_move, .58)

    return {
        "attack_factor": min(hand_factor, permanent_attack),
        "parry_factor": min(hand_factor, permanent_parry),
        "block_factor": min(block_factor, permanent_block),
        "movement_factor": min(movement_factor, permanent_move),
        "awareness_factor": min(awareness_factor, permanent_awareness),
    }


_CONTACT_NEIGHBORS: dict[str, tuple[tuple[str, str], ...]] = {
    "eye": (("head", "face"), ("head", "head")),
    "wrist": (("forearms_hands", "hand"), ("forearms_hands", "forearm")),
    "hand": (("forearms_hands", "wrist"), ("forearms_hands", "forearm")),
    "forearm": (("forearms_hands", "wrist"), ("upper_arms", "elbow")),
    "elbow": (("forearms_hands", "forearm"), ("upper_arms", "upper_arm")),
    "shoulder": (("upper_arms", "upper_arm"), ("upper_torso", "upper_torso")),
    "axilla": (("upper_arms", "upper_arm"), ("upper_torso", "upper_torso")),
    "neck": (("head", "head"), ("upper_torso", "upper_torso")),
    "knee": (("thighs", "thigh"), ("lower_legs_feet", "lower_leg")),
    "ankle": (("lower_legs_feet", "foot"), ("lower_legs_feet", "lower_leg")),
    "foot": (("lower_legs_feet", "ankle"), ("lower_legs_feet", "lower_leg")),
    "lower_leg": (("lower_legs_feet", "ankle"), ("thighs", "knee")),
    "thigh": (("thighs", "knee"), ("thighs", "hip")),
    "hip": (("thighs", "thigh"), ("lower_torso", "lower_torso")),
    "upper_torso": (("upper_torso", "axilla"), ("lower_torso", "lower_torso")),
    "lower_torso": (("upper_torso", "upper_torso"), ("thighs", "hip")),
}

def resolve_actual_contact_target(
    *,
    aim_zone: str,
    aim_side: str,
    aim_structure: str,
    contact_grade: str,
    defense_method: str | None,
    margin: float,
    seed: int,
) -> dict[str, Any]:
    """Convert intended aim into the body structure actually contacted.

    Exceptional/clean contacts normally preserve the intended line. Marginal
    contacts can be displaced to an adjacent structure by the defender's motion.
    The function never invents contact after a denied attack; callers invoke it
    only after physical body contact has already been established.
    """
    zone = str(aim_zone or "upper_torso")
    side = str(aim_side or "midline")
    structure = str(aim_structure or zone)
    grade = str(contact_grade or "solid")
    if grade in {"exceptional", "clean"} or float(margin) >= 22.0:
        return {"body_zone": zone, "side": side, "structure": structure, "deviation": "none", "aim_preserved": True}
    neighbors = _CONTACT_NEIGHBORS.get(structure, ())
    if not neighbors:
        return {"body_zone": zone, "side": side, "structure": structure, "deviation": "none", "aim_preserved": True}
    # A solid hit often still lands on the intended structure. Glancing / barely
    # beaten defenses are much more likely to shift the contact line.
    preserve_threshold = 55 if grade == "solid" else 20
    roll = (abs(int(seed)) + int(abs(float(margin)) * 17.0) + len(str(defense_method or "")) * 13) % 100
    if roll < preserve_threshold:
        return {"body_zone": zone, "side": side, "structure": structure, "deviation": "none", "aim_preserved": True}
    nz, ns = neighbors[roll % len(neighbors)]
    return {
        "body_zone": nz,
        "side": side if ns not in {"neck", "upper_torso", "lower_torso", "head", "face"} else ("midline" if ns in {"neck", "upper_torso", "lower_torso"} else side),
        "structure": ns,
        "deviation": "defense_or_contact_geometry",
        "aim_preserved": False,
    }

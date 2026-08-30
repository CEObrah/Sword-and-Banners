"""Finite deterministic training-program resolver and settlement helpers.

Training narration is not mechanical authority. Every gain-bearing training hour must
resolve to one registered program and one registered drill in
``game/data/mil/deterministic-training-programs.json``. The helpers in this module
allocate verified hours by fixed basis-point weights and route them through the same
EDU/cost law used elsewhere for exact people and aggregate cohorts.
"""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from copy import deepcopy
from typing import Any

from sword_runtime.cohort_personnel import ATTRIBUTE_ORDER, SKILL_ORDER, advance_cohort_training, cohort_merged_skill_means
from sword_runtime.training_session import settle_training_session
from sword_runtime.sim.calendar import CampaignTime
from sword_runtime.training_time import reserve_person_training_time
from sword_runtime.training_facilities import program_facility_access
from sword_runtime.stat_access import core_skill_map, merged_skill_map, professional_skill_map
from sword_runtime.military_loadouts import institutional_role_loadout_id
from sword_runtime.static_records import load_loadout
from sword_runtime.mount_custody import regional_horses

REGISTRY_PATH = "game/data/mil/deterministic-training-programs.json"


def _program_ref_exists(registry: Mapping[str, Any], ref: str) -> bool:
    programs = registry.get("programs", {}) if isinstance(registry, Mapping) else {}
    return isinstance(programs, Mapping) and ref in programs



def formation_training_ref_for_role(formation: Mapping[str, Any], role: str) -> str:
    """Return the saved training profile for one physical role in a formation."""
    per_role = formation.get("training_refs_by_role") if isinstance(formation.get("training_refs_by_role"), Mapping) else {}
    value = per_role.get(str(role)) if isinstance(per_role, Mapping) else None
    if isinstance(value, str) and value:
        return value
    value = formation.get("training_ref")
    return str(value) if isinstance(value, str) else ""


def _loadout_satisfies_drill_requirement(loadout: Mapping[str, Any], requirement: str) -> bool | None:
    req=str(requirement)
    ranged=str(loadout.get("ranged_weapon") or "")
    melee=" ".join(str(loadout.get(key) or "") for key in ("primary_melee_weapon","sidearm"))
    ammo=str(loadout.get("ammunition_item") or "")
    if req=="mount": return bool(loadout.get("mount"))
    if req=="tack": return bool(loadout.get("tack"))
    if req=="shield": return bool(loadout.get("shield"))
    if req=="bow": return "bow" in ranged and "crossbow" not in ranged
    if req=="crossbow": return "crossbow" in ranged
    if req=="arrows": return ammo=="ammo_arrow"
    if req=="bolts": return ammo=="ammo_bolt"
    if req=="lance": return any(token in melee for token in ("lance","spear"))
    if req=="spear": return any(token in melee for token in ("spear","lance","glaive","polearm"))
    if req=="sword": return "sword" in melee
    return None

def resolve_program_ref(
    registry: Mapping[str, Any],
    *,
    role: str | None = None,
    training_ref: str | None = None,
    person: Mapping[str, Any] | None = None,
    explicit_program_ref: str | None = None,
) -> str:
    """Resolve one registered program from saved facts only.

    A command billet never erases branch competence. When a saved officer is tied
    to a formation program/role, the registry deterministically maps that branch
    program to the corresponding command-and-branch program. Otherwise the saved
    billet falls back to the generic combined-arms command program. No current
    stat ranking, prose, randomness, or model choice participates.
    """
    if explicit_program_ref:
        if _program_ref_exists(registry, explicit_program_ref):
            return explicit_program_ref
        raise ValueError(f"unknown explicit deterministic training program: {explicit_program_ref}")

    direct_person_program = ""
    billet_program = ""
    role_text = ""
    if isinstance(person, Mapping):
        contract = person.get("activity_contract") if isinstance(person.get("activity_contract"), Mapping) else {}
        direct_person_program = str(contract.get("training_program_ref", "")).strip()
        if direct_person_program:
            if _program_ref_exists(registry, direct_person_program):
                return direct_person_program
            raise ValueError(f"unknown saved deterministic training program: {direct_person_program}")
        direct_person_program = str(person.get("training_program_ref", "")).strip()
        if direct_person_program:
            if _program_ref_exists(registry, direct_person_program):
                return direct_person_program
            raise ValueError(f"unknown saved deterministic training program: {direct_person_program}")
        career = person.get("career_state") if isinstance(person.get("career_state"), Mapping) else {}
        assignment = person.get("command_assignment") if isinstance(person.get("command_assignment"), Mapping) else {}
        billet = str(assignment.get("billet") or career.get("current_billet") or "").strip()
        billet_map = registry.get("exact_billet_programs", {})
        if billet and isinstance(billet_map, Mapping):
            candidate = str(billet_map.get(billet, ""))
            if candidate and _program_ref_exists(registry, candidate):
                billet_program = candidate
        role_text = " ".join(
            str(person.get(key, ""))
            for key in ("role", "rank", "role_archetype")
        ).lower()

    # Resolve the physical/service branch independently from command status.
    branch_program = ""
    tref = str(training_ref or "").strip()
    tref_map = registry.get("training_ref_programs", {})
    if tref and isinstance(tref_map, Mapping):
        candidate = str(tref_map.get(tref, ""))
        if candidate and _program_ref_exists(registry, candidate):
            branch_program = candidate

    rtext = str(role or "").strip()
    role_map = registry.get("role_programs", {})
    if not branch_program and rtext and isinstance(role_map, Mapping):
        candidate = str(role_map.get(rtext, ""))
        if candidate and _program_ref_exists(registry, candidate):
            branch_program = candidate

    if not branch_program and role_text:
        rules = registry.get("role_keyword_programs", [])
        if isinstance(rules, Sequence) and not isinstance(rules, (str, bytes, bytearray)):
            for row in rules:
                if not isinstance(row, Mapping):
                    continue
                tokens = row.get("contains", [])
                if not isinstance(tokens, Sequence) or isinstance(tokens, (str, bytes, bytearray)):
                    continue
                if any(str(token).lower() in role_text for token in tokens):
                    candidate = str(row.get("program_ref", ""))
                    if candidate and _program_ref_exists(registry, candidate):
                        branch_program = candidate
                        break

    if billet_program:
        specializations = registry.get("command_specialization_programs", {})
        if branch_program and isinstance(specializations, Mapping):
            specialized = str(specializations.get(branch_program, ""))
            if specialized and _program_ref_exists(registry, specialized):
                return specialized
        return billet_program

    command_role = bool(role_text and any(token in role_text for token in ("commander", "general", "marshal", "strategist", "officer")))
    if branch_program:
        # Legacy or compact person-lite records may encode command status in role/rank
        # rather than a registered billet string. Preserve branch competence while
        # adding command development instead of silently training them as rank-and-file.
        if command_role:
            specializations = registry.get("command_specialization_programs", {})
            specialized = str(specializations.get(branch_program, "")) if isinstance(specializations, Mapping) else ""
            if specialized and _program_ref_exists(registry, specialized):
                return specialized
        return branch_program

    # Saved role/rank labels can prove command status when no billet is present.
    if command_role:
        generic = "program.commander_combined_arms"
        if _program_ref_exists(registry, generic):
            return generic

    fallback = str(registry.get("fallback_program_ref", "program.general_military"))
    if not _program_ref_exists(registry, fallback):
        raise ValueError("deterministic training registry fallback program is missing")
    return fallback


def program_record(registry: Mapping[str, Any], program_ref: str) -> Mapping[str, Any]:
    programs = registry.get("programs", {}) if isinstance(registry, Mapping) else {}
    row = programs.get(program_ref) if isinstance(programs, Mapping) else None
    if not isinstance(row, Mapping):
        raise ValueError(f"unknown deterministic training program: {program_ref}")
    rotation = row.get("rotation")
    if not isinstance(rotation, Sequence) or isinstance(rotation, (str, bytes, bytearray)) or not rotation:
        raise ValueError(f"training program {program_ref} has no rotation")
    total = sum(max(0, int(item.get("weight_bp", 0))) for item in rotation if isinstance(item, Mapping))
    if total != 10000:
        raise ValueError(f"training program {program_ref} weights must sum to 10000 basis points")
    return row


def drill_record(registry: Mapping[str, Any], drill_ref: str) -> Mapping[str, Any]:
    drills = registry.get("drills", {}) if isinstance(registry, Mapping) else {}
    row = drills.get(drill_ref) if isinstance(drills, Mapping) else None
    if not isinstance(row, Mapping):
        raise ValueError(f"unknown deterministic training drill: {drill_ref}")
    return row


def _integer_weight_allocation(total_hours: int, rows: Sequence[Mapping[str, Any]], cursor: int) -> list[int]:
    total = max(0, int(total_hours))
    if total <= 0:
        return [0] * len(rows)
    raw = [total * max(0, int(row.get("weight_bp", 0))) / 10000.0 for row in rows]
    base = [int(value) for value in raw]
    remaining = total - sum(base)
    if remaining > 0:
        # Largest remainders first; the saved cursor only breaks exact ties, making
        # long-run distribution stable while avoiding a permanent first-row bias.
        n = max(1, len(rows))
        order = sorted(
            range(len(rows)),
            key=lambda i: (-(raw[i] - base[i]), (i - max(0, int(cursor))) % n, i),
        )
        for i in order[:remaining]:
            base[i] += 1
    return base


def _promotion_thresholds(promotion_facts: Mapping[str, Any] | None) -> tuple[dict[str, float], dict[str, float]]:
    facts = promotion_facts if isinstance(promotion_facts, Mapping) else {}
    raw_skills = facts.get("minimum_skill_values")
    raw_attrs = facts.get("minimum_attribute_values")
    skill_targets: dict[str, float] = {}
    attr_targets: dict[str, float] = {}
    if isinstance(raw_skills, Mapping):
        for name in SKILL_ORDER:
            if name not in raw_skills:
                continue
            try: skill_targets[name] = max(0.0, float(raw_skills[name]))
            except (TypeError, ValueError): pass
    elif isinstance(raw_skills, Sequence) and not isinstance(raw_skills, (str, bytes, bytearray)):
        for name, value in zip(SKILL_ORDER, raw_skills):
            try: skill_targets[name] = max(0.0, float(value))
            except (TypeError, ValueError): pass
    if isinstance(raw_attrs, Mapping):
        for name in ATTRIBUTE_ORDER:
            if name not in raw_attrs:
                continue
            try: attr_targets[name] = max(0.0, float(raw_attrs[name]))
            except (TypeError, ValueError): pass
    elif isinstance(raw_attrs, Sequence) and not isinstance(raw_attrs, (str, bytes, bytearray)):
        for name, value in zip(ATTRIBUTE_ORDER, raw_attrs):
            try: attr_targets[name] = max(0.0, float(value))
            except (TypeError, ValueError): pass
    return skill_targets, attr_targets


def _normalized_adaptive_rotation(
    registry: Mapping[str, Any],
    program_ref: str,
    *,
    skill_values: Mapping[str, Any] | None = None,
    attribute_values: Mapping[str, Any] | None = None,
    promotion_facts: Mapping[str, Any] | None = None,
    cursor: int = 0,
) -> list[dict[str, Any]]:
    """Return one closed-program rotation with deterministic adaptive weights.

    The catalog remains finite: adaptation may only redistribute emphasis among
    drills already registered in the selected program. Real promotion thresholds
    outrank weak-useful-stat balancing. No prose, RNG, or unregistered focus can
    create a drill or gain target.
    """
    program = program_record(registry, program_ref)
    rows = [dict(row) for row in program.get("rotation", []) if isinstance(row, Mapping)]
    skills = skill_values if isinstance(skill_values, Mapping) else {}
    attrs = attribute_values if isinstance(attribute_values, Mapping) else {}
    skill_targets, attr_targets = _promotion_thresholds(promotion_facts)
    cfg = registry.get("adaptive_priority", {}) if isinstance(registry, Mapping) else {}
    promotion_weight = max(0.0, float(cfg.get("promotion_deficit_weight", 3.0))) if isinstance(cfg, Mapping) else 3.0
    weak_weight = max(0.0, float(cfg.get("weak_useful_weight", 0.8))) if isinstance(cfg, Mapping) else 0.8
    maximum_multiplier = max(1.0, float(cfg.get("maximum_module_multiplier", 4.0))) if isinstance(cfg, Mapping) else 4.0

    # Weakness is relative only to the other useful targets inside this exact
    # registered program. This prevents high absolute stat scales from disabling
    # adaptation and prevents irrelevant weapon families from entering the plan.
    relevant_values: list[float] = []
    for row in rows:
        drill = drill_record(registry, str(row.get("drill_ref", "")))
        for name in drill.get("skills", []) if isinstance(drill.get("skills"), Sequence) else []:
            if str(name) in skills:
                try: relevant_values.append(max(0.0, float(skills[str(name)])))
                except (TypeError, ValueError): pass
        for name in drill.get("attributes", []) if isinstance(drill.get("attributes"), Sequence) else []:
            if str(name) in attrs:
                try: relevant_values.append(max(0.0, float(attrs[str(name)])))
                except (TypeError, ValueError): pass
    if relevant_values:
        ordered = sorted(relevant_values)
        mid = len(ordered) // 2
        reference = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0
    else:
        reference = 0.0

    scored: list[tuple[dict[str, Any], float]] = []
    for row in rows:
        dref = str(row.get("drill_ref", ""))
        drill = drill_record(registry, dref)
        deficits: list[float] = []
        weak: list[float] = []
        for name in drill.get("skills", []) if isinstance(drill.get("skills"), Sequence) else []:
            key = str(name)
            try: current = max(0.0, float(skills.get(key, 0.0)))
            except (TypeError, ValueError): current = 0.0
            threshold = skill_targets.get(key)
            if threshold and threshold > 0:
                deficits.append(max(0.0, min(1.0, (threshold - current) / threshold)))
            if reference > 0 and key in skills:
                weak.append(max(0.0, min(1.0, (reference - current) / max(1.0, reference))))
        for name in drill.get("attributes", []) if isinstance(drill.get("attributes"), Sequence) else []:
            key = str(name)
            try: current = max(0.0, float(attrs.get(key, 0.0)))
            except (TypeError, ValueError): current = 0.0
            threshold = attr_targets.get(key)
            if threshold and threshold > 0:
                deficits.append(max(0.0, min(1.0, (threshold - current) / threshold)))
            if reference > 0 and key in attrs:
                weak.append(max(0.0, min(1.0, (reference - current) / max(1.0, reference))))
        promotion_need = (sum(deficits) / len(deficits)) if deficits else 0.0
        weak_need = (sum(weak) / len(weak)) if weak else 0.0
        multiplier = min(maximum_multiplier, 1.0 + promotion_weight * promotion_need + weak_weight * weak_need)
        base = max(0, int(row.get("weight_bp", 0)))
        scored.append((row, base * multiplier))

    total_score = sum(score for _row, score in scored)
    if total_score <= 0:
        return rows
    raw_bp = [10000.0 * score / total_score for _row, score in scored]
    bp = [int(value) for value in raw_bp]
    remaining = 10000 - sum(bp)
    n = max(1, len(bp))
    order = sorted(range(len(bp)), key=lambda i: (-(raw_bp[i] - bp[i]), (i - max(0, int(cursor))) % n, i))
    for i in order[:remaining]:
        bp[i] += 1
    out: list[dict[str, Any]] = []
    for (row, _score), weight in zip(scored, bp):
        updated = dict(row)
        updated["weight_bp"] = int(weight)
        out.append(updated)
    return out


def module_allocations(
    registry: Mapping[str, Any],
    program_ref: str,
    total_hours: float,
    *,
    integer_hours: bool,
    cursor: int = 0,
    skill_values: Mapping[str, Any] | None = None,
    attribute_values: Mapping[str, Any] | None = None,
    promotion_facts: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows = _normalized_adaptive_rotation(
        registry, program_ref, skill_values=skill_values, attribute_values=attribute_values,
        promotion_facts=promotion_facts, cursor=cursor,
    )
    if integer_hours:
        allocations = _integer_weight_allocation(max(0, int(total_hours)), rows, cursor)
    else:
        allocations = [max(0.0, float(total_hours)) * max(0, int(row.get("weight_bp", 0))) / 10000.0 for row in rows]
    out: list[dict[str, Any]] = []
    for row, hours in zip(rows, allocations):
        if float(hours) <= 1e-12:
            continue
        dref = str(row.get("drill_ref", ""))
        drill = drill_record(registry, dref)
        out.append({"drill_ref": dref, "hours": hours, "drill": drill, "adaptive_weight_bp": int(row.get("weight_bp", 0))})
    return out

def _split_exact_skill_hours(hours: int, skills: Sequence[str], cursor: int) -> list[tuple[str, int]]:
    names = [str(name) for name in skills if str(name)]
    if not names or hours <= 0:
        return []
    base, rem = divmod(int(hours), len(names))
    out: list[tuple[str, int]] = []
    n = len(names)
    for offset in range(n):
        i = (max(0, int(cursor)) + offset) % n
        count = base + (1 if offset < rem else 0)
        if count > 0:
            out.append((names[i], count))
    return out


def instructor_quality_factor(
    training_rules: Mapping[str, Any],
    *,
    instructor_teaching: float,
    instructor_domain_skill: float,
    trainee_skill: float,
) -> float:
    """Registered deterministic instructor-quality formula.

    Teaching capability and actual domain mastery both matter. The formula is data-owned
    in training.json and deliberately bounded so a great instructor improves verified
    EDU without bypassing time, aptitude, equipment, recovery, or diminishing returns.
    """
    base = 0.78
    teaching_term = min(0.32, max(0.0, float(instructor_teaching)) / 300.0)
    domain_term = min(0.25, max(0.0, float(instructor_domain_skill) - float(trainee_skill)) / 320.0)
    return max(0.75, min(1.35, base + teaching_term + domain_term))


def instructor_capacity_factor(
    training_rules: Mapping[str, Any],
    *,
    practice_mode: str,
    student_count: int,
    instructor_count: int,
) -> float:
    rules = training_rules.get("instructor", {}) if isinstance(training_rules, Mapping) else {}
    spans = rules.get("ordinary_spans", {}) if isinstance(rules, Mapping) else {}
    span = max(1, int(spans.get(str(practice_mode), spans.get("drill", 12)) or 1)) if isinstance(spans, Mapping) else 12
    students = max(0, int(student_count))
    instructors = max(0, int(instructor_count))
    if students <= 0:
        return 1.0
    if instructors <= 0:
        return 0.0
    return max(0.0, min(1.0, (instructors * span) / float(students)))


def combat_skill_weights(registry: Mapping[str, Any], program_ref: str) -> dict[str, float]:
    """Derive deterministic combat-learning weights from the registered program.

    The battle layer may only award skills already present in the participant's
    registered branch/billet program. Drill weights are divided across that drill's
    skills, then normalized. No current-stat ranking or narration can introduce a
    skill family. Pure teaching skill is never minted by battle participation.
    """
    weights: dict[str, float] = {}
    program = program_record(registry, program_ref)
    for row in program.get("rotation", []):
        if not isinstance(row, Mapping):
            continue
        drill = drill_record(registry, str(row.get("drill_ref", "")))
        skills = [str(x) for x in drill.get("skills", []) if str(x)]
        if not skills:
            continue
        share = max(0.0, float(row.get("weight_bp", 0))) / len(skills)
        for skill in skills:
            weights[skill] = weights.get(skill, 0.0) + share
    total = sum(weights.values())
    if total <= 0:
        return {}
    return {skill: value / total for skill, value in sorted(weights.items())}


_COMBAT_COMMAND_LEARNING_SKILLS = {
    "Formation Command", "Leadership", "Tactics", "Strategy", "Logistics",
}
_COMBAT_COMMAND_ROLES = {
    "commander", "higher_commander",
    "internal_100_commander", "internal_500_commander", "internal_1000_commander",
}


def combat_skill_weights_for_participant(
    registry: Mapping[str, Any],
    program_ref: str,
    participant_role: str,
) -> dict[str, float]:
    """Apply actual battle responsibility to registered combat-learning weights.

    Saved rank/billet determines the lawful program, but it cannot prove the person
    exercised command in this engagement. Formation-command, leadership, tactics,
    strategy and logistics EDU therefore survive only for explicit command roles in
    the battle participant record. Ordinary embedded/notable/specialist/staff combat
    remains eligible for the program's physical/weapon/Formation Fighting domains.
    """
    weights = combat_skill_weights(registry, program_ref)
    if str(participant_role) not in _COMBAT_COMMAND_ROLES:
        weights = {k: v for k, v in weights.items() if k not in _COMBAT_COMMAND_LEARNING_SKILLS}
    total = sum(weights.values())
    if total <= 0:
        return {}
    return {skill: value / total for skill, value in sorted(weights.items())}

def settle_exact_program(
    person: dict[str, Any],
    *,
    registry: Mapping[str, Any],
    program_ref: str,
    hours: int,
    at: CampaignTime,
    training_rules: Mapping[str, Any],
    session_rules: Mapping[str, Any],
    facility_grade: str,
    equipment_grade: str,
    recovery_grade: str,
    feedback_grade: str,
    cursor_key: str = "deterministic_training_cursor",
    promotion_facts: Mapping[str, Any] | None = None,
    instructor_context_by_drill: Mapping[str, Mapping[str, Any]] | None = None,
    drill_access: Mapping[str, float] | None = None,
    time_window_start: str | CampaignTime | None = None,
    time_window_end: str | CampaignTime | None = None,
    time_evidence_ref: str | None = None,
) -> dict[str, Any]:
    """Settle whole verified hours through one fixed registered program.

    ``drill_access`` is the exact-person physical resource gate. A registered drill
    can be part of a lawful program yet still grant no EDU when the person lacks
    the weapon, shield, mount, ammunition, or supervised resource required to do it.
    """
    requested_whole = max(0, int(hours))
    whole = requested_whole
    time_reservation: dict[str, Any] | None = None
    if time_window_start is not None and time_window_end is not None and time_evidence_ref:
        time_reservation = reserve_person_training_time(
            person, requested_hours=float(requested_whole),
            window_start=time_window_start, window_end=time_window_end,
            reservation_ref=f"{time_evidence_ref}:personal_training",
            kind="personal_training", training_rules=training_rules,
            metadata={"program_ref": program_ref}, whole_hours=True,
        )
        whole = max(0, int(float(time_reservation.get("reserved_hours", 0.0) or 0.0)))
    ds = person.setdefault("development_state", {})
    cursor = max(0, int(ds.get(cursor_key, 0)))
    available = merged_skill_map(person)
    results: list[dict[str, Any]] = []
    used = 0
    module_trace: list[dict[str, Any]] = []
    for module_index, allocation in enumerate(module_allocations(registry, program_ref, whole, integer_hours=True, cursor=cursor, skill_values=available, attribute_values=(person.get("attributes") if isinstance(person.get("attributes"), Mapping) else {}), promotion_facts=promotion_facts)):
        drill = allocation["drill"]
        allocated_hours = int(allocation["hours"])
        dref = str(allocation["drill_ref"])
        access = max(0.0, min(1.0, float((drill_access or {}).get(dref, 1.0))))
        # Exact-character settlement is whole-hour authoritative. Fractional physical
        # access is converted deterministically by floor; the blocked remainder grants
        # no EDU and is preserved in trace instead of being reassigned to another drill.
        module_hours = int(allocated_hours * access + 1e-9)
        skill_names = [str(name) for name in drill.get("skills", []) if str(name) in available]
        skill_rows = _split_exact_skill_hours(module_hours, skill_names, cursor + module_index)
        module_used = 0
        ictx = (instructor_context_by_drill or {}).get(dref, {}) if isinstance(instructor_context_by_drill, Mapping) else {}
        quality = max(0.0, min(1.35, float(ictx.get("quality_factor", 1.0) or 0.0))) if isinstance(ictx, Mapping) else 1.0
        capacity = max(0.0, min(1.0, float(ictx.get("capacity_factor", 1.0) or 0.0))) if isinstance(ictx, Mapping) else 1.0
        instructor_ref = str(ictx.get("instructor_ref", "") or "") if isinstance(ictx, Mapping) else ""
        for skill, skill_hours in skill_rows:
            results.append(
                settle_training_session(
                    person,
                    skill,
                    skill_hours,
                    at,
                    training_rules,
                    session_rules,
                    facility_grade=facility_grade,
                    equipment_grade=equipment_grade,
                    recovery_grade=recovery_grade,
                    practice_mode=str(drill.get("practice_mode", "drill")),
                    intensity=str(drill.get("intensity", "standard")),
                    feedback_grade=feedback_grade,
                    attribute_targets=[str(name) for name in drill.get("attributes", [])],
                    instruction_factor=quality,
                    instructor_capacity_factor=capacity,
                    instructor_ref=instructor_ref or None,
                )
            )
            module_used += skill_hours
        used += module_used
        module_trace.append({"drill_ref": dref, "allocated_hours": allocated_hours, "access_factor": round(access, 6), "blocked_hours": max(0, allocated_hours - module_hours), "settled_skill_hours": module_used, "instructor_ref": instructor_ref or None, "instruction_factor": round(quality, 6), "instructor_capacity_factor": round(capacity, 6)})
    ds[cursor_key] = cursor + whole
    ds["last_training_program_ref"] = program_ref
    return {
        "program_ref": program_ref,
        "requested_hours": requested_whole,
        "verified_hours": whole,
        "time_reservation": deepcopy(time_reservation) if time_reservation is not None else None,
        "settled_skill_hours": used,
        "modules": module_trace,
        "development": results,
    }




def registered_focus_drill_ref(registry: Mapping[str, Any], program_ref: str, skill: str) -> str:
    """Map a player training intent to one existing registered drill.

    The caller may choose a lawful skill intent, but cannot author exercise mechanics.
    If several program drills train that skill, the highest standing rotation weight
    wins deterministically, then drill ref breaks ties.
    """
    target = str(skill)
    candidates: list[tuple[int, str]] = []
    for row in program_record(registry, program_ref).get("rotation", []):
        if not isinstance(row, Mapping):
            continue
        dref = str(row.get("drill_ref", ""))
        drill = drill_record(registry, dref)
        if target in {str(x) for x in drill.get("skills", [])}:
            candidates.append((max(0, int(row.get("weight_bp", 0) or 0)), dref))
    if not candidates:
        raise ValueError("training focus is outside the registered program")
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][1]


def settle_exact_registered_focus(
    person: dict[str, Any],
    *,
    registry: Mapping[str, Any],
    program_ref: str,
    focus_skill: str,
    hours: int,
    at: CampaignTime,
    training_rules: Mapping[str, Any],
    session_rules: Mapping[str, Any],
    facility_grade: str,
    equipment_grade: str,
    recovery_grade: str,
    feedback_grade: str,
    instructor_context_by_drill: Mapping[str, Mapping[str, Any]] | None = None,
    drill_access: Mapping[str, float] | None = None,
    time_window_start: str | CampaignTime | None = None,
    time_window_end: str | CampaignTime | None = None,
    time_evidence_ref: str | None = None,
) -> dict[str, Any]:
    """Settle an explicit training intent through one registered program drill."""
    dref = registered_focus_drill_ref(registry, program_ref, focus_skill)
    drill = drill_record(registry, dref)
    requested_whole = max(0, int(hours))
    whole = requested_whole
    time_reservation: dict[str, Any] | None = None
    if time_window_start is not None and time_window_end is not None and time_evidence_ref:
        time_reservation = reserve_person_training_time(
            person, requested_hours=float(requested_whole), window_start=time_window_start,
            window_end=time_window_end, reservation_ref=f"{time_evidence_ref}:personal_training",
            kind="personal_training", training_rules=training_rules,
            metadata={"program_ref": program_ref, "drill_ref": dref, "focus_skill": str(focus_skill)},
            whole_hours=True,
        )
        whole = max(0, int(float(time_reservation.get("reserved_hours", 0.0) or 0.0)))
    access = max(0.0, min(1.0, float((drill_access or {}).get(dref, 1.0))))
    usable_hours = int(whole * access + 1e-9)
    available = merged_skill_map(person)
    skill_names = [str(name) for name in drill.get("skills", []) if str(name) in available]
    cursor = max(0, int(person.setdefault("development_state", {}).get("focused_training_cursor", 0) or 0))
    skill_rows = _split_exact_skill_hours(usable_hours, skill_names, cursor)
    ictx = (instructor_context_by_drill or {}).get(dref, {}) if isinstance(instructor_context_by_drill, Mapping) else {}
    quality = max(0.0, min(1.35, float(ictx.get("quality_factor", 1.0) or 0.0))) if isinstance(ictx, Mapping) else 1.0
    capacity = max(0.0, min(1.0, float(ictx.get("capacity_factor", 1.0) or 0.0))) if isinstance(ictx, Mapping) else 1.0
    instructor_ref = str(ictx.get("instructor_ref", "") or "") if isinstance(ictx, Mapping) else ""
    results: list[dict[str, Any]] = []
    settled = 0
    for skill, skill_hours in skill_rows:
        results.append(settle_training_session(
            person, skill, skill_hours, at, training_rules, session_rules,
            facility_grade=facility_grade, equipment_grade=equipment_grade, recovery_grade=recovery_grade,
            practice_mode=str(drill.get("practice_mode", "drill")), intensity=str(drill.get("intensity", "standard")),
            feedback_grade=feedback_grade, attribute_targets=[str(name) for name in drill.get("attributes", [])],
            instruction_factor=quality, instructor_capacity_factor=capacity, instructor_ref=instructor_ref or None,
        ))
        settled += skill_hours
    ds = person.setdefault("development_state", {})
    ds["focused_training_cursor"] = cursor + whole
    ds["last_training_program_ref"] = program_ref
    ds["last_training_drill_ref"] = dref
    return {
        "program_ref": program_ref, "drill_ref": dref, "focus_skill": str(focus_skill),
        "requested_hours": requested_whole, "verified_hours": whole,
        "settled_skill_hours": settled, "access_factor": round(access, 6),
        "blocked_hours": max(0, whole - usable_hours),
        "instructor_ref": instructor_ref or None, "instruction_factor": round(quality, 6),
        "instructor_capacity_factor": round(capacity, 6),
        "time_reservation": deepcopy(time_reservation) if time_reservation is not None else None,
        "development": results,
    }

def _formation_mounted_training_need(registry: Mapping[str, Any], formation: Mapping[str, Any]) -> tuple[int, int]:
    """Return (bodies needing mounted modules, formation-owned serviceable mounts)."""
    composition = formation.get("composition", {}) if isinstance(formation.get("composition"), Mapping) else {}
    mounted_required = 0
    for other_role, count in composition.items():
        n = max(0, int(count or 0))
        if n <= 0:
            continue
        try:
            other_program = resolve_program_ref(
                registry,
                role=str(other_role),
                training_ref=formation_training_ref_for_role(formation, str(other_role)),
            )
        except ValueError:
            continue
        needs_mount = False
        for allocation in module_allocations(registry, other_program, 1.0, integer_hours=False):
            reqs = {str(x) for x in allocation["drill"].get("equipment_requirements", [])}
            if "mount" in reqs or "tack" in reqs:
                needs_mount = True
                break
        if needs_mount:
            mounted_required += n
    mounts = formation.get("mounts", {}) if isinstance(formation.get("mounts"), Mapping) else {}
    physical_mounts = sum(max(0, int(v or 0)) for v in mounts.values())
    return mounted_required, physical_mounts


def _shared_regional_training_mounts(
    runtime: Any,
    registry: Mapping[str, Any],
    formation: Mapping[str, Any],
    *,
    own_unmet: int,
) -> float:
    """Allocate local unassigned horses as shared training assets without duplication.

    Regional-reserve horses remain in the mount-pool conservation ledger. They may
    support drills at their exact location, but are apportioned across every same-force
    formation with unmet mounted-training demand at that location. The calculation is
    read-only: training access never transfers custody or creates a combat mount.
    """
    if own_unmet <= 0 or runtime is None or not hasattr(runtime, "read"):
        return 0.0
    location_ref = str(formation.get("location_ref", "") or "")
    force_ref = str(formation.get("owner_force_ref", "") or "")
    if not location_ref or not force_ref:
        return 0.0
    try:
        mount_path = runtime._mount_pool_path_for_formation(formation) if hasattr(runtime, "_mount_pool_path_for_formation") else None
        pool = runtime.read(mount_path) if mount_path else {}
        reserve = regional_horses(pool, location_ref) if isinstance(pool, Mapping) else 0
    except Exception:
        return 0.0
    if reserve <= 0:
        return 0.0

    refs: list[str] = []
    try:
        index = runtime.read("state/index/location-formation-index.json")
        locations = index.get("locations", {}) if isinstance(index, Mapping) else {}
        raw = locations.get(location_ref, []) if isinstance(locations, Mapping) else []
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            refs = [str(ref) for ref in raw if isinstance(ref, str)]
    except Exception:
        refs = []
    own_ref = str(formation.get("formation_ref", "") or "")
    if own_ref and own_ref not in refs:
        refs.append(own_ref)

    total_unmet = 0
    seen: set[str] = set()
    for ref in refs:
        if not ref or ref in seen:
            continue
        seen.add(ref)
        if ref == own_ref:
            other = formation
        else:
            try:
                path = runtime.owner_path(ref) if hasattr(runtime, "owner_path") else None
                other = runtime.read(path) if path else {}
            except Exception:
                continue
        if (
            not isinstance(other, Mapping)
            or str(other.get("owner_force_ref", "") or "") != force_ref
            # The location index is routing-only.  A stale entry for a remote
            # same-force formation must not dilute this formation's share of
            # local reserve horses or grant remote mounts as training access.
            or str(other.get("location_ref", "") or "") != location_ref
        ):
            continue
        required, owned = _formation_mounted_training_need(registry, other)
        total_unmet += max(0, required - owned)
    if total_unmet <= 0:
        return 0.0
    return min(float(own_unmet), float(reserve) * float(own_unmet) / float(total_unmet))


def formation_drill_access(
    registry: Mapping[str, Any],
    program_ref: str,
    formation: Mapping[str, Any],
    *,
    role: str,
    runtime: Any | None = None,
) -> dict[str, float]:
    """Return deterministic physical access factors for formation drill modules.

    Formation training must not grant weapon, shield, mounted, or specialist-site
    practice to more bodies than can physically do it. ``equipment_units_by_role``
    represents complete role loadouts; shields and mounts are separately conserved
    because they can be destroyed or remounted independently. When ``runtime`` is
    supplied, every registered ``facility_tag`` is also checked against the saved
    formation location. Facility quality remains represented by the regimen grade.
    """
    composition = formation.get("composition", {}) if isinstance(formation.get("composition"), Mapping) else {}
    role_count = max(0, int(composition.get(role, 0) or 0))
    if role_count <= 0:
        return {row["drill_ref"]: 0.0 for row in module_allocations(registry, program_ref, 1.0, integer_hours=False)}

    equipment_units = formation.get("equipment_units_by_role", {}) if isinstance(formation.get("equipment_units_by_role"), Mapping) else {}
    if role in equipment_units:
        equipped = max(0, min(role_count, int(equipment_units.get(role, 0) or 0)))
        equipment_share = equipped / float(role_count)
    else:
        raw = float(formation.get("equipment_completeness", 100.0) or 0.0)
        equipment_share = max(0.0, min(1.0, raw / 100.0 if raw > 1.0 else raw))

    condition_by_role = formation.get("equipment_condition_by_role", {}) if isinstance(formation.get("equipment_condition_by_role"), Mapping) else {}
    condition = max(0.0, min(100.0, float(condition_by_role.get(role, 100.0) or 0.0)))
    if condition <= 5.0:
        equipment_share = 0.0

    # ``equipment_units_by_role`` means complete issued role loadouts. If a role's
    # canonical loadout includes a shield and no separate shield ledger has yet been
    # materialized, the complete-loadout count is the physical shield count. Once a
    # separate shield ledger exists, it becomes authoritative so battle loss/wear can
    # reduce later shield drill access without destroying the rest of the loadout.
    raw_shields = formation.get("shield_units_by_role")
    if isinstance(raw_shields, Mapping) and role in raw_shields:
        shield_share = max(0.0, min(1.0, int(raw_shields.get(role, 0) or 0) / float(role_count)))
    else:
        shield_share = equipment_share
    shield_conditions = formation.get("shield_condition_by_role", {}) if isinstance(formation.get("shield_condition_by_role"), Mapping) else {}
    if float(shield_conditions.get(role, 100.0) or 0.0) <= 8.0:
        shield_share = 0.0

    # Formation-owned mounts provide direct access. Unassigned horses in the same
    # force's exact local mount pool may be shared for training, but their capacity
    # is apportioned across all unmet same-force demand at that location so one
    # regional horse cannot be counted by several formations at once.
    mounted_required, physical_mounts = _formation_mounted_training_need(registry, formation)
    own_unmet = max(0, mounted_required - physical_mounts)
    shared_training_mounts = _shared_regional_training_mounts(
        runtime, registry, formation, own_unmet=own_unmet
    ) if runtime is not None else 0.0
    effective_mounts = min(float(mounted_required), float(physical_mounts) + float(shared_training_mounts))
    mount_share = max(0.0, min(1.0, effective_mounts / float(max(1, mounted_required)))) if mounted_required > 0 else 0.0

    facility_access: Mapping[str, float] = {}
    if runtime is not None:
        facility_access = program_facility_access(
            runtime, registry=registry, program_ref=program_ref,
            location_ref=str(formation.get("location_ref", "")),
        )

    role_loadout: Mapping[str, Any] = {}
    if runtime is not None and hasattr(runtime, "read"):
        try:
            loadout_ref = institutional_role_loadout_id(runtime.read, formation, role)
            loadout_record = load_loadout(runtime.read, loadout_ref) if loadout_ref else {}
            role_loadout = loadout_record.get("loadout", {}) if isinstance(loadout_record, Mapping) else {}
            if not isinstance(role_loadout, Mapping):
                role_loadout = {}
        except Exception:
            role_loadout = {}

    out: dict[str, float] = {}
    for allocation in module_allocations(registry, program_ref, 1.0, integer_hours=False):
        dref = str(allocation["drill_ref"])
        reqs = {str(x) for x in allocation["drill"].get("equipment_requirements", [])}
        if role_loadout:
            # Mounts/tack are shared physical training assets, not permanently
            # welded to a troop role's canonical field loadout. A foot House Guard
            # may therefore cross-train for Guardian Cavalry when the formation
            # actually has serviceable horses. ``mount_share`` below remains the
            # hard physical capacity gate, so this cannot invent mounted practice.
            proven_missing = [
                req for req in reqs
                if req not in {"mount", "tack"}
                and _loadout_satisfies_drill_requirement(role_loadout, req) is False
            ]
            if proven_missing:
                out[dref] = 0.0
                continue
        factors: list[float] = []
        if reqs - {"mount", "tack", "shield"}:
            factors.append(equipment_share)
        if "shield" in reqs:
            factors.append(shield_share)
        if "mount" in reqs or "tack" in reqs:
            factors.append(mount_share)
        physical_access = max(0.0, min(1.0, min(factors) if factors else 1.0))
        site_access = max(0.0, min(1.0, float(facility_access.get(dref, 1.0))))
        out[dref] = min(physical_access, site_access)
    return out

def settle_cohort_program(
    cohort: MutableMapping[str, Any],
    *,
    registry: Mapping[str, Any],
    program_ref: str,
    deliberate_hours: float,
    role_exposure_hours: float,
    training_rules: Mapping[str, Any],
    facility_grade: str,
    equipment_grade: str,
    recovery_grade: str,
    evidence_ref: str,
    drill_access: Mapping[str, float] | None = None,
    promotion_facts: Mapping[str, Any] | None = None,
    instructor_context_by_drill: Mapping[str, Mapping[str, Any]] | None = None,
    allow_exposure_attribute_stimulus: bool = True,
) -> dict[str, Any]:
    """Settle aggregate training through fixed registered drill weights.

    ``drill_access`` is a deterministic physical availability factor per registered
    drill. Blocked hours do not become verified training and therefore cannot grant
    EDU merely because a formation is nominally assigned to a program.
    """
    deliberate = max(0.0, float(deliberate_hours))
    exposure = max(0.0, float(role_exposure_hours))
    trace: list[dict[str, Any]] = []
    # Each stream is allocated by the same program weights; each drill then uses
    # the shared aggregate EDU law for its registered skill and attribute targets.
    d_alloc = {row["drill_ref"]: row for row in module_allocations(registry, program_ref, deliberate, integer_hours=False, skill_values=cohort_merged_skill_means(cohort), attribute_values=(cohort.get("attribute_means") if isinstance(cohort.get("attribute_means"), Mapping) else {}), promotion_facts=promotion_facts, cursor=int(cohort.get("smart_training_cursor", 0) or 0))}
    e_alloc = {row["drill_ref"]: row for row in module_allocations(registry, program_ref, exposure, integer_hours=False, skill_values=cohort_merged_skill_means(cohort), attribute_values=(cohort.get("attribute_means") if isinstance(cohort.get("attribute_means"), Mapping) else {}), promotion_facts=promotion_facts, cursor=int(cohort.get("smart_training_cursor", 0) or 0))}
    rotation = program_record(registry, program_ref).get("rotation", [])
    for row in rotation:
        if not isinstance(row, Mapping):
            continue
        dref = str(row.get("drill_ref", ""))
        drill = drill_record(registry, dref)
        allocated_dh = float(d_alloc.get(dref, {}).get("hours", 0.0))
        allocated_eh = float(e_alloc.get(dref, {}).get("hours", 0.0))
        access = max(0.0, min(1.0, float((drill_access or {}).get(dref, 1.0))))
        dh = allocated_dh * access
        eh = allocated_eh * access
        if allocated_dh <= 1e-12 and allocated_eh <= 1e-12:
            continue
        ictx = (instructor_context_by_drill or {}).get(dref, {}) if isinstance(instructor_context_by_drill, Mapping) else {}
        quality = max(0.0, min(1.35, float(ictx.get("quality_factor", 1.0) or 0.0))) if isinstance(ictx, Mapping) else 1.0
        capacity = max(0.0, min(1.0, float(ictx.get("capacity_factor", 1.0) or 0.0))) if isinstance(ictx, Mapping) else 1.0
        instructor_ref = str(ictx.get("instructor_ref", "") or "") if isinstance(ictx, Mapping) else ""
        if dh > 1e-12 or eh > 1e-12:
            advance_cohort_training(
                cohort,
                deliberate_hours=dh,
                role_exposure_hours=eh,
                skill_focuses=[str(x) for x in drill.get("skills", [])],
                attribute_focuses=([str(x) for x in drill.get("attributes", [])] if (allow_exposure_attribute_stimulus or dh > 1e-12) else []),
                training_rules=training_rules,
                facility_grade=facility_grade,
                equipment_grade=equipment_grade,
                recovery_grade=recovery_grade,
                practice_mode=str(drill.get("practice_mode", "drill")),
                evidence_ref=f"{evidence_ref}:{dref}",
                instruction_factor=quality,
                instructor_capacity_factor=capacity,
                instructor_ref=instructor_ref or None,
            )
        trace.append({
            "drill_ref": dref,
            "allocated_deliberate_hours": round(allocated_dh, 3),
            "allocated_role_exposure_hours": round(allocated_eh, 3),
            "access_factor": round(access, 6),
            "deliberate_hours": round(dh, 3),
            "role_exposure_hours": round(eh, 3),
            "blocked_hours": round((allocated_dh - dh) + (allocated_eh - eh), 3),
            "facility_tag": str(drill.get("facility_tag", "")),
            "instructor_role": str(drill.get("instructor_role", "")),
            "instructor_ref": instructor_ref or None,
            "instruction_factor": round(quality, 6),
            "instructor_capacity_factor": round(capacity, 6),
            "equipment_requirements": [str(x) for x in drill.get("equipment_requirements", [])],
        })
    cohort["last_training_program_ref"] = program_ref
    cohort["smart_training_cursor"] = max(0, int(cohort.get("smart_training_cursor", 0) or 0)) + 1
    cohort["last_training"] = {
        "evidence_ref": evidence_ref,
        "program_ref": program_ref,
        "deliberate_hours": round(deliberate, 3),
        "role_exposure_hours": round(exposure, 3),
    }
    return {"program_ref": program_ref, "modules": trace, "deliberate_hours": round(deliberate, 3), "role_exposure_hours": round(exposure, 3)}


def settle_person_lite_program(
    person: MutableMapping[str, Any],
    *,
    registry: Mapping[str, Any],
    program_ref: str,
    deliberate_hours: float,
    role_exposure_hours: float,
    training_rules: Mapping[str, Any],
    facility_grade: str,
    equipment_grade: str,
    recovery_grade: str,
    evidence_ref: str,
    promotion_facts: Mapping[str, Any] | None = None,
    instructor_context_by_drill: Mapping[str, Mapping[str, Any]] | None = None,
    drill_access: Mapping[str, float] | None = None,
    time_window_start: str | CampaignTime | None = None,
    time_window_end: str | CampaignTime | None = None,
) -> dict[str, Any]:
    stats = person.get("stats") if isinstance(person.get("stats"), Mapping) else {}
    skills = core_skill_map(person)
    professional_skills = professional_skill_map(person)
    attrs = stats.get("attributes") if isinstance(stats.get("attributes"), Mapping) else {}
    if not skills or not attrs:
        return {"trained": False, "reason": "missing_person_lite_stats", "program_ref": program_ref}
    dev = person.setdefault("development_state", {})
    requested_deliberate = max(0.0, float(deliberate_hours))
    actual_deliberate = requested_deliberate
    time_reservation: dict[str, Any] | None = None
    if time_window_start is not None and time_window_end is not None:
        time_reservation = reserve_person_training_time(
            person, requested_hours=requested_deliberate,
            window_start=time_window_start, window_end=time_window_end,
            reservation_ref=f"{evidence_ref}:personal_training", kind="personal_training",
            training_rules=training_rules, metadata={"program_ref": program_ref},
        )
        actual_deliberate = max(0.0, float(time_reservation.get("reserved_hours", 0.0) or 0.0))
    pseudo: dict[str, Any] = {
        "skill_means": deepcopy(dict(skills)),
        "professional_skill_means": deepcopy(dict(professional_skills)),
        "attribute_means": deepcopy(dict(attrs)),
        "skill_edu_banks": deepcopy(dev.get("skill_edu_banks", {})) if isinstance(dev.get("skill_edu_banks"), Mapping) else {},
        "attribute_edu_banks": deepcopy(dev.get("attribute_edu_banks", {})) if isinstance(dev.get("attribute_edu_banks"), Mapping) else {},
        "aptitude_means": deepcopy(person.get("aptitude", {})) if isinstance(person.get("aptitude"), Mapping) else {},
        "age_distribution": {"mean": 28.0},
        "smart_training_cursor": max(0, int(dev.get("smart_training_cursor", 0) or 0)),
    }
    result = settle_cohort_program(
        pseudo,
        registry=registry,
        program_ref=program_ref,
        deliberate_hours=actual_deliberate,
        role_exposure_hours=role_exposure_hours,
        training_rules=training_rules,
        facility_grade=facility_grade,
        equipment_grade=equipment_grade,
        recovery_grade=recovery_grade,
        evidence_ref=evidence_ref,
        promotion_facts=promotion_facts,
        instructor_context_by_drill=instructor_context_by_drill,
        drill_access=drill_access,
    )
    stats = person.setdefault("stats", {})
    stats["skills"] = dict(pseudo["skill_means"])
    professional = {str(k): v for k, v in pseudo.get("professional_skill_means", {}).items() if float(v) != 0.0}
    if professional:
        person["professional_skills"] = professional
    else:
        person.pop("professional_skills", None)
    stats["attributes"] = dict(pseudo["attribute_means"])
    dev["skill_edu_banks"] = dict(pseudo["skill_edu_banks"])
    dev["attribute_edu_banks"] = dict(pseudo["attribute_edu_banks"])
    dev["last_training_program_ref"] = program_ref
    dev["smart_training_cursor"] = max(0, int(pseudo.get("smart_training_cursor", 0) or 0))
    dev["verified_training_hours"] = round(float(dev.get("verified_training_hours", 0.0)) + actual_deliberate, 3)
    dev["verified_role_exposure_hours"] = round(float(dev.get("verified_role_exposure_hours", 0.0)) + max(0.0, float(role_exposure_hours)), 3)
    dev["last_training"] = {
        "evidence_ref": evidence_ref,
        "program_ref": program_ref,
        "deliberate_hours": round(actual_deliberate, 3),
        "role_exposure_hours": round(float(role_exposure_hours), 3),
    }
    return {"trained": True, **result}


__all__ = [
    "REGISTRY_PATH",
    "resolve_program_ref",
    "program_record",
    "drill_record",
    "module_allocations",
    "instructor_quality_factor",
    "instructor_capacity_factor",
    "combat_skill_weights",
    "combat_skill_weights_for_participant",
    "registered_focus_drill_ref",
    "settle_exact_registered_focus",
    "settle_exact_program",
    "settle_cohort_program",
    "settle_person_lite_program",
]

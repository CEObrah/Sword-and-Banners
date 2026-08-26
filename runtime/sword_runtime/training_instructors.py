"""Deterministic instructor selection and distributed drill-delivery helpers.

Instructor identity is mechanical evidence, not narration. Exact people are selected
only from registered pools or the trainee formation's lawful command chain. Large-unit
training is delivered through the existing internal command/drill-leader network; a
senior exact instructor can set/correct the standard without being counted as thousands
of simultaneous one-to-one instructors.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sword_runtime.static_records import load_loadout
from sword_runtime.military_loadouts import explicit_personal_loadout_id
from sword_runtime.officer_cadre import officer_cadre_summary
from sword_runtime.training_programs import drill_record, instructor_quality_factor, module_allocations
from sword_runtime.unit_establishment import authorized_strength_for, formation_class_for, hierarchy_counts
from sword_runtime.training_time import reserve_person_training_time, reserved_training_time_hours, training_window_budget_hours
from sword_runtime.training_facilities import program_facility_access, shared_training_resources
from sword_runtime.stat_access import merged_skill_map




def _copy_person_for_training_time(person: Mapping[str, Any]) -> dict[str, Any]:
    """Copy only the mutable branch owned by the training-time reservation.

    Instructor selection can reserve thousands of drill windows in a long-horizon
    preview. Deep-copying an entire character sheet, including histories, skills,
    equipment and unrelated state, for every reservation made runtime cost grow
    with document size rather than with the small ledger branch actually changed.
    """
    out = dict(person)
    raw_dev = person.get("development_state")
    if isinstance(raw_dev, Mapping):
        dev = dict(raw_dev)
        raw_ledger = raw_dev.get("training_time_ledger")
        if isinstance(raw_ledger, Mapping):
            ledger = dict(raw_ledger)
            for list_key in ("active_entries", "active_windows"):
                raw_entries = raw_ledger.get(list_key)
                if isinstance(raw_entries, list):
                    ledger[list_key] = [dict(row) if isinstance(row, Mapping) else row for row in raw_entries]
            dev["training_time_ledger"] = ledger
        out["development_state"] = dev
    return out

def _skills(person: Mapping[str, Any]) -> Mapping[str, Any]:
    return merged_skill_map(person)

def _attributes(person: Mapping[str, Any]) -> Mapping[str, Any]:
    if str(person.get("schema", "")) == "person-lite":
        stats = person.get("stats") if isinstance(person.get("stats"), Mapping) else {}
        return stats.get("attributes", {}) if isinstance(stats.get("attributes"), Mapping) else {}
    return person.get("attributes", {}) if isinstance(person.get("attributes"), Mapping) else {}


def _teaching_capability(person: Mapping[str, Any], domains: Sequence[str]) -> float:
    """Derive teaching capability from current expertise and command/cognition.

    Teaching is not a universal standalone skill. Subject mastery sets the practical
    ceiling while Leadership, Intelligence and Presence determine how effectively
    the instructor can communicate, diagnose and correct performance.
    """
    skills = _skills(person)
    attrs = _attributes(person)
    domain = _mean_skill(skills, domains)
    leadership = max(0.0, float(skills.get("Leadership", 0.0) or 0.0))
    intelligence = max(0.0, float(attrs.get("Intelligence", 0.0) or 0.0))
    presence = max(0.0, float(attrs.get("Presence", 0.0) or 0.0))
    return 0.40 * domain + 0.30 * leadership + 0.20 * intelligence + 0.10 * presence


def _health_ok(person: Mapping[str, Any]) -> bool:
    raw = person.get("health", person.get("health_status", "healthy"))
    if isinstance(raw, Mapping):
        raw = raw.get("status", "healthy")
    return str(raw).lower() not in {"dead", "incapacitated", "critical", "unfit"}


def _location(person: Mapping[str, Any]) -> str:
    for key in ("current_location", "location_ref", "location"):
        value = person.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _same_training_area(candidate_location: str, trainee_location: str, registry: Mapping[str, Any]) -> tuple[bool, float]:
    if not trainee_location:
        return True, 1.0
    if candidate_location == trainee_location:
        return True, 1.0
    groups = registry.get("instructor_location_groups", []) if isinstance(registry, Mapping) else []
    if isinstance(groups, Sequence) and not isinstance(groups, (str, bytes, bytearray)):
        for row in groups:
            if not isinstance(row, Mapping):
                continue
            prefixes = [str(x) for x in row.get("prefixes", []) if str(x)] if isinstance(row.get("prefixes"), Sequence) else []
            if prefixes and any(candidate_location.startswith(p) for p in prefixes) and any(trainee_location.startswith(p) for p in prefixes):
                return True, max(0.0, min(1.0, float(row.get("availability_factor", 0.92) or 0.92)))
    return False, 0.0


def _candidate_refs(registry: Mapping[str, Any], instructor_role: str, formation: Mapping[str, Any] | None) -> list[str]:
    refs: list[str] = []
    if isinstance(formation, Mapping):
        value = formation.get("commander_ref")
        if isinstance(value, str) and value:
            refs.append(value)
        cadre = officer_cadre_summary(formation)
        materialized = cadre.get("materialized_refs_by_rank") if isinstance(cadre, Mapping) and isinstance(cadre.get("materialized_refs_by_rank"), Mapping) else {}
        if isinstance(materialized, Mapping):
            for values in materialized.values():
                if isinstance(values, Sequence) and not isinstance(values, (str, bytes, bytearray)):
                    refs.extend(str(x) for x in values if str(x))
    pools = registry.get("instructor_pools", {}) if isinstance(registry, Mapping) else {}
    if isinstance(pools, Mapping):
        row = pools.get(instructor_role, pools.get("default", []))
        if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)):
            refs.extend(str(x) for x in row if str(x))
    seen: set[str] = set(); out: list[str] = []
    for ref in refs:
        if ref and ref not in seen:
            seen.add(ref); out.append(ref)
    return out


def _read_person(runtime: Any, ref: str) -> Mapping[str, Any] | None:
    try:
        path = runtime.owner_path(ref)
        row = runtime.read(path)
        return row if isinstance(row, Mapping) else None
    except Exception:
        return None


def _higher_command_instructor_refs(runtime: Any, formation: Mapping[str, Any] | None) -> list[str]:
    """Return lawful higher-command training candidates for a routed formation.

    The higher commander sets the command standard. Explicit saved command staff
    may also be candidates, but only their actual skills and physical presence can
    make them effective instructors. No generic second top-command post is implied.
    """
    if not isinstance(formation, Mapping):
        return []
    ref = str(formation.get("higher_command_ref", "") or "")
    if not ref:
        return []
    try:
        path = runtime.owner_path(ref)
        group = runtime.read(path)
    except Exception:
        return []
    if not isinstance(group, Mapping):
        return []
    out: list[str] = []
    commander = group.get("commander_ref")
    if isinstance(commander, str) and commander:
        out.append(commander)
    roles = group.get("role_assignments") if isinstance(group.get("role_assignments"), Mapping) else {}
    for value in sorted(roles):
        if isinstance(value, str) and value and value not in out:
            out.append(value)
    return out

def _mean_skill(skills: Mapping[str, Any], names: Sequence[str]) -> float:
    vals: list[float] = []
    for name in names:
        try:
            if name in skills:
                vals.append(max(0.0, float(skills[name])))
        except (TypeError, ValueError):
            pass
    return sum(vals) / len(vals) if vals else 0.0



def _loadout_items(runtime: Any, person: Mapping[str, Any]) -> dict[str, Any]:
    """Return the person's actual/saved training equipment without inventing kit."""
    manifest = person.get("equipment_manifest") if isinstance(person.get("equipment_manifest"), Mapping) else None
    if isinstance(manifest, Mapping):
        items = manifest.get("items") if isinstance(manifest.get("items"), Mapping) else manifest
        return dict(items) if isinstance(items, Mapping) else {}
    loadout_id = explicit_personal_loadout_id(person)
    if loadout_id:
        try:
            row = load_loadout(runtime.read, loadout_id)
            if row:
                return row
        except Exception:
            pass
    # Tang Wei's personal equipment is conserved in the exact manifest owner.
    if str(person.get("id") or person.get("player_id") or person.get("owner_id") or "") in {"char_tang_wei", "player_tang_wei"} or str(person.get("name", "")) == "Tang Wei":
        try:
            doc = runtime.read("state/player-detail/equipment-manifest.json")
            rows = doc.get("equipment_manifest", []) if isinstance(doc, Mapping) else []
            out: dict[str, Any] = {}
            if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes, bytearray)):
                for row in rows:
                    if not isinstance(row, Mapping) or int(row.get("quantity", 0) or 0) <= 0:
                        continue
                    item = str(row.get("item_id", ""))
                    state = str(row.get("current_state", "")).lower()
                    if not item or any(token in state for token in ("destroyed", "lost", "broken")):
                        continue
                    out[item] = item
            return out
        except Exception:
            pass
    return {}


def _available_training_resources(items: Mapping[str, Any], person: Mapping[str, Any]) -> set[str]:
    text = " ".join(str(v).lower() for v in items.values()) + " " + " ".join(str(k).lower() for k in items)
    resources: set[str] = set()
    tokens = {
        "sword": ("sword",), "spear": ("spear", "lance"), "lance": ("lance",),
        "bow": ("bow",), "crossbow": ("crossbow",), "shield": ("shield",),
        "mount": ("horse", "mount"), "tack": ("tack",), "armor": ("armor",),
        "arrows": ("arrow",), "bolts": ("bolt",),
    }
    for name, needles in tokens.items():
        if any(needle in text for needle in needles):
            resources.add(name)
    contract = person.get("activity_contract") if isinstance(person.get("activity_contract"), Mapping) else {}
    supervised = contract.get("training_resource_access", []) if isinstance(contract, Mapping) else []
    if isinstance(supervised, Sequence) and not isinstance(supervised, (str, bytes, bytearray)):
        resources.update(str(x) for x in supervised if str(x))
    return resources


def exact_person_drill_access(runtime: Any, *, registry: Mapping[str, Any], program_ref: str, person: Mapping[str, Any]) -> dict[str, float]:
    """Physical equipment *and facility* gate for exact/person-lite training.

    Program membership proves relevance, not possession or place. Weapon/mount
    drills are blocked unless the saved loadout/manifest or an explicit supervised
    resource grant proves access. Registered ``facility_tag`` requirements are
    resolved against the saved physical location. Specialist institutional resources
    such as artillery, engineering tools and signals can be shared only when the
    matching physical facility is present.
    """
    location_ref = _location(person)
    resources = _available_training_resources(_loadout_items(runtime, person), person)
    resources.update(shared_training_resources(runtime, location_ref=location_ref))
    facilities = program_facility_access(
        runtime, registry=registry, program_ref=program_ref, location_ref=location_ref
    ) if location_ref else {}
    out: dict[str, float] = {}
    for allocation in module_allocations(registry, program_ref, 1.0, integer_hours=False):
        dref = str(allocation["drill_ref"])
        reqs = {str(x) for x in allocation["drill"].get("equipment_requirements", []) if str(x)}
        equipment_access = 1.0 if reqs.issubset(resources) else 0.0
        # A missing location on synthetic/legacy records preserves the equipment-only
        # result; persisted campaign people are expected to carry location evidence.
        facility_access = float(facilities.get(dref, 1.0 if not location_ref else 0.0))
        out[dref] = max(0.0, min(1.0, min(equipment_access, facility_access)))
    return out

def _ranked_instructor_candidates(
    runtime: Any,
    *,
    registry: Mapping[str, Any],
    training_rules: Mapping[str, Any],
    drill_ref: str,
    trainee_skills: Mapping[str, Any],
    trainee_location: str,
    formation: Mapping[str, Any] | None = None,
    trainee_ref: str | None = None,
    use_mass_pool_cache: bool = False,
) -> list[dict[str, Any]]:
    drill = drill_record(registry, drill_ref)
    role = str(drill.get("instructor_role", "role_instructor"))
    domains = [str(x) for x in drill.get("skills", []) if str(x)]
    trainee_domain = _mean_skill(trainee_skills, domains)
    candidate_refs = _higher_command_instructor_refs(runtime, formation) + _candidate_refs(registry, role, formation)
    seen_refs: set[str] = set()
    unique_refs: list[str] = []
    for ref in candidate_refs:
        if ref and ref not in seen_refs:
            seen_refs.add(ref)
            unique_refs.append(ref)

    base_candidates: list[dict[str, Any]] | None = None
    cache = getattr(runtime, "_training_instructor_pool_cache", None)
    cache_key: tuple[Any, ...] | None = None
    if use_mass_pool_cache and isinstance(cache, dict):
        try:
            world_time = str(runtime.read("state/runtime.json").get("world_time", ""))
        except Exception:
            world_time = ""
        cache_key = (world_time, str(drill_ref), str(trainee_location), tuple(unique_refs))
        cached = cache.get(cache_key)
        if isinstance(cached, list):
            base_candidates = cached

    if base_candidates is None:
        base_candidates = []
        for ref in unique_refs:
            person = _read_person(runtime, ref)
            if not isinstance(person, Mapping) or not _health_ok(person):
                continue
            allowed, area_availability = _same_training_area(_location(person), trainee_location, registry)
            if not allowed:
                continue
            skills = _skills(person)
            base_candidates.append({
                "instructor_ref": ref,
                "teaching_score": _teaching_capability(person, domains),
                "domain_score": _mean_skill(skills, domains),
                "area_availability": area_availability,
                "person": person,
            })
        if cache_key is not None and isinstance(cache, dict):
            cache[cache_key] = base_candidates

    candidates: list[dict[str, Any]] = []
    for base in base_candidates:
        ref = str(base.get("instructor_ref", ""))
        if trainee_ref and ref == trainee_ref:
            continue
        teaching_score = float(base.get("teaching_score", 0.0) or 0.0)
        domain_score = float(base.get("domain_score", 0.0) or 0.0)
        quality = instructor_quality_factor(
            training_rules,
            instructor_teaching=teaching_score,
            instructor_domain_skill=domain_score,
            trainee_skill=trainee_domain,
        ) * float(base.get("area_availability", 1.0) or 1.0)
        candidates.append({
            "instructor_ref": ref,
            "quality_factor": round(max(0.0, min(1.35, quality)), 6),
            "teaching_score": round(teaching_score, 3),
            "domain_score": round(domain_score, 3),
            "source": "best_lawful_exact_instructor",
            "person": base.get("person"),
        })
    return sorted(
        candidates,
        key=lambda row: (-float(row["quality_factor"]), -float(row["teaching_score"]), str(row["instructor_ref"])),
    )


def best_instructor_for_drill(
    runtime: Any,
    *,
    registry: Mapping[str, Any],
    training_rules: Mapping[str, Any],
    drill_ref: str,
    trainee_skills: Mapping[str, Any],
    trainee_location: str,
    formation: Mapping[str, Any] | None = None,
    trainee_ref: str | None = None,
    _ranked_candidates: Sequence[Mapping[str, Any]] | None = None,
    use_mass_pool_cache: bool = False,
) -> dict[str, Any]:
    drill = drill_record(registry, drill_ref)
    domains = [str(x) for x in drill.get("skills", []) if str(x)]
    trainee_domain = _mean_skill(trainee_skills, domains)
    candidates = list(_ranked_candidates) if _ranked_candidates is not None else _ranked_instructor_candidates(
        runtime, registry=registry, training_rules=training_rules, drill_ref=drill_ref,
        trainee_skills=trainee_skills, trainee_location=trainee_location, formation=formation, trainee_ref=trainee_ref,
        use_mass_pool_cache=use_mass_pool_cache,
    )
    if candidates:
        row = dict(candidates[0])
        row.pop("person", None)
        return row
    # Large formations always have ordinary drill leaders inside the fighting body.
    # Their quality is bounded by the formation/cohort's own saved subject and Leadership means;
    # this is not a new manpower class or a fabricated specialist slot.
    internal_teaching = 0.70 * trainee_domain + 0.30 * max(0.0, float(trainee_skills.get("Leadership", 0.0) or 0.0))
    internal_domain = trainee_domain
    quality = instructor_quality_factor(
        training_rules,
        instructor_teaching=internal_teaching,
        instructor_domain_skill=internal_domain,
        trainee_skill=trainee_domain,
    )
    return {
        "instructor_ref": None,
        "quality_factor": round(quality, 6),
        "teaching_score": round(internal_teaching, 3),
        "domain_score": round(internal_domain, 3),
        "source": "internal_drill_leader_cadre",
    }


def direct_instruction_capacity(training_rules: Mapping[str, Any], *, student_count: int) -> float:
    """Capacity for genuinely personalized exact-person coaching groups.

    This is deliberately separate from formation training. A lead instructor does
    not directly coach a whole Unit; mass drill is propagated through its existing
    command hierarchy.
    """
    students = max(0, int(student_count))
    if students <= 0:
        return 1.0
    cfg = training_rules.get("instructor", {}) if isinstance(training_rules, Mapping) else {}
    cap = max(1, int(cfg.get("direct_personalized_group_max_students", 8) or 8)) if isinstance(cfg, Mapping) else 8
    return max(0.0, min(1.0, cap / students))


def distributed_instructor_capacity(
    *,
    training_rules: Mapping[str, Any],
    drill: Mapping[str, Any],
    student_count: int,
    formation: Mapping[str, Any] | None,
    trainee_skills: Mapping[str, Any],
) -> float:
    """Mass-training delivery through the real saved command hierarchy.

    Formation size never creates a synthetic instructor penalty. Unit commander and explicit staff
    set and inspect the standard, required 1000/500/100 echelons propagate it, and the
    100-command layer conducts hands-on troop drill. Coverage is simply the weakest
    required staffed echelon. There is no Units-per-instructor cap and no extra trainer
    manpower class. Aggregate cohorts without a concrete formation retain their embedded
    professional drill cadre and therefore do not receive an invented headcount penalty.
    """
    students = max(0, int(student_count))
    if students <= 1:
        return 1.0
    if not isinstance(formation, Mapping):
        return 1.0

    current = max(0, int(formation.get("personnel", students) or students))
    klass = formation_class_for(formation, personnel=current, explicit=formation.get("formation_class"))
    authorized = authorized_strength_for(formation, personnel=current, formation_class=klass)
    counts = hierarchy_counts(authorized_strength=authorized, formation_class=klass)
    cadre = officer_cadre_summary(formation)
    active = cadre.get("active_billets") if isinstance(cadre.get("active_billets"), Mapping) else {}

    coverage = 1.0
    for scale, key in ((1000, "1000_commander"), (500, "500_commander"), (100, "100_commander")):
        required = max(0, int(counts.get(scale, 0)))
        if required <= 0:
            continue
        have = required
        if isinstance(active, Mapping) and key in active:
            have = max(0, min(required, int(active.get(key, 0) or 0)))
        coverage = min(coverage, have / required)

    unit_command = {
        "named_commander_ref": formation.get("commander_ref"),
        "allocated_aggregate_by_role": formation.get("attached_unit_command_by_role", {}),
    }

    def _top_post_staffed(ref_key: str, post_key: str) -> bool | None:
        # Exact refs prove a staffed post. Aggregate posts such as
        # ``materialize_when_individually_relevant`` also represent a real staffed
        # commander whose individual sheet has simply not been materialized.
        # Only an explicitly vacant/absent post counts as missing.
        raw_ref = formation.get(ref_key, unit_command.get(ref_key) if isinstance(unit_command, Mapping) else None)
        if raw_ref:
            return True
        if isinstance(unit_command, Mapping) and post_key in unit_command:
            post = str(unit_command.get(post_key, "") or "").strip().lower()
            if post in {"vacant", "unfilled", "absent", "none", "no_post"}:
                return False
            if post:
                return True
        if ref_key in formation or (isinstance(unit_command, Mapping) and ref_key in unit_command):
            # A literal null ref with no aggregate-post declaration is an explicit
            # missing exact appointment, not evidence that no command echelon exists.
            return False
        return None

    top_state = _top_post_staffed("commander_ref", "commander_post")
    if top_state is False:
        coverage *= 0.5

    return round(max(0.0, min(1.0, coverage)), 6)

def _internal_instruction_quality(
    training_rules: Mapping[str, Any],
    *,
    drill: Mapping[str, Any],
    trainee_skills: Mapping[str, Any],
    student_count: int,
) -> float:
    if max(0, int(student_count)) <= 1:
        # No exact instructor means actual self-practice, not a fictional drill leader.
        return 1.0
    domains = [str(x) for x in drill.get("skills", []) if str(x)]
    trainee_domain = _mean_skill(trainee_skills, domains)
    internal_teaching = 0.70 * trainee_domain + 0.30 * max(0.0, float(trainee_skills.get("Leadership", 0.0) or 0.0))
    return instructor_quality_factor(
        training_rules,
        instructor_teaching=internal_teaching,
        instructor_domain_skill=trainee_domain,
        trainee_skill=trainee_domain,
    )


def instructor_contexts_for_program(
    runtime: Any,
    *,
    registry: Mapping[str, Any],
    training_rules: Mapping[str, Any],
    program_ref: str,
    trainee_skills: Mapping[str, Any],
    student_count: int,
    location_ref: str,
    formation: Mapping[str, Any] | None = None,
    trainee_ref: str | None = None,
    scheduled_hours: float | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    evidence_ref: str | None = None,
    reserve_duty: bool = False,
    focus_drill_ref: str | None = None,
    hierarchical_delivery: bool = False,
) -> dict[str, dict[str, Any]]:
    """Resolve lawful instruction for personal or command-chain training.

    Direct personalized coaching still consumes exact instructor time and therefore
    cannot overlap for free. Military mass training is different: commander and explicit staff
    set and inspect the standard and the saved hierarchy propagates it downward. That
    command-chain supervision is part of standing command duty and is not booked once
    per subordinate Unit, so there is no arbitrary four-Unit ceiling or O(N Units)
    instructor ledger. Physical presence, health, relevant skill, facilities, equipment,
    fatigue and actual command coverage still matter.
    """
    contexts: dict[str, dict[str, Any]] = {}
    allocation_hours = max(0.0, float(scheduled_hours or 0.0))
    if focus_drill_ref:
        focused = drill_record(registry, str(focus_drill_ref))
        allocations = [{
            "drill_ref": str(focus_drill_ref),
            "drill": focused,
            "hours": allocation_hours if allocation_hours > 0 else 1.0,
        }]
    else:
        allocations = module_allocations(
            registry, program_ref, allocation_hours if allocation_hours > 0 else 1.0, integer_hours=False
        )
    mass_chain = bool(hierarchical_delivery or max(0, int(student_count)) > 1)

    for allocation in allocations:
        dref = str(allocation["drill_ref"])
        drill = allocation["drill"]
        ranked_candidates = _ranked_instructor_candidates(
            runtime, registry=registry, training_rules=training_rules, drill_ref=dref,
            trainee_skills=trainee_skills, trainee_location=location_ref, formation=formation, trainee_ref=trainee_ref,
            use_mass_pool_cache=mass_chain,
        )
        row = best_instructor_for_drill(
            runtime, registry=registry, training_rules=training_rules, drill_ref=dref,
            trainee_skills=trainee_skills, trainee_location=location_ref, formation=formation,
            trainee_ref=trainee_ref, _ranked_candidates=ranked_candidates,
            use_mass_pool_cache=mass_chain,
        )
        internal_quality = _internal_instruction_quality(
            training_rules, drill=drill, trainee_skills=trainee_skills, student_count=student_count
        )
        if not row.get("instructor_ref") and max(0, int(student_count)) <= 1:
            row["quality_factor"] = round(internal_quality, 6)
            row["source"] = "self_practice_no_exact_instructor"
        row["internal_quality_factor"] = round(internal_quality, 6)
        row["capacity_factor"] = round(distributed_instructor_capacity(
            training_rules=training_rules, drill=drill, student_count=student_count,
            formation=formation, trainee_skills=trainee_skills,
        ), 6)
        if mass_chain:
            # Senior command/domain expertise sets and corrects the standard while
            # the existing command cadre delivers repetitions down to the 100-man
            # drill layer. Both matter, but no one exact instructor is treated as
            # personally teaching every body.
            senior_quality = max(0.0, min(1.35, float(row.get("quality_factor", internal_quality) or internal_quality)))
            delivered_quality = max(0.0, min(1.35, 0.5 * senior_quality + 0.5 * internal_quality))
            row["standard_setter_quality_factor"] = round(senior_quality, 6)
            row["delivery_cadre_quality_factor"] = round(internal_quality, 6)
            row["quality_factor"] = round(delivered_quality, 6)
            row["delivery_model"] = "hierarchical_command_chain"
            if not row.get("instructor_ref"):
                row["source"] = "embedded_command_chain"

        if reserve_duty and evidence_ref and window_start and window_end and allocation_hours > 0.0:
            module_hours = max(0.0, float(allocation.get("hours", 0.0) or 0.0))
            mode = str(drill.get("practice_mode", "drill"))
            if mass_chain:
                # This is hierarchical command supervision, not one-to-one teaching.
                # The commander and explicit staff can set one standard for every subordinate Unit
                # and each echelon propagates it. No per-Unit instructor booking occurs.
                row["instructor_duty"] = {
                    "model": "hierarchical_command_chain",
                    "requested_hours": 0.0,
                    "reserved_hours": 0.0,
                    "availability_factor": 1.0,
                    "window_start": str(window_start),
                    "window_end": str(window_end),
                    "reservation_ref": None,
                    "practice_mode": mode,
                    "module_training_hours": round(module_hours, 6),
                }
                contexts[dref] = row
                continue

            instructor_ref = str(row.get("instructor_ref", "") or "")
            requested_duty = module_hours
            if requested_duty > 0.0:
                timed: list[tuple[float, float, float, str, dict[str, Any]]] = []
                for candidate in ranked_candidates:
                    cref = str(candidate.get("instructor_ref", "") or "")
                    cperson = candidate.get("person")
                    if not cref or not isinstance(cperson, Mapping):
                        continue
                    budget = training_window_budget_hours(training_rules, window_start=window_start, window_end=window_end)
                    used = reserved_training_time_hours(cperson, window_start=window_start, window_end=window_end)
                    available_hours = max(0.0, budget - used)
                    availability_factor = max(0.0, min(1.0, available_hours / requested_duty))
                    cquality = max(0.0, min(1.35, float(candidate.get("quality_factor", internal_quality) or 0.0)))
                    effective = internal_quality + (cquality - internal_quality) * availability_factor
                    timed.append((effective, cquality, available_hours, cref, dict(candidate)))
                if timed:
                    _effective, _quality, _available, _cref, selected = sorted(
                        timed, key=lambda item: (-item[0], -item[1], -item[2], item[3])
                    )[0]
                    if _effective > internal_quality + 1e-12:
                        row = {k: v for k, v in selected.items() if k != "person"}
                        row["internal_quality_factor"] = round(internal_quality, 6)
                        row["capacity_factor"] = 1.0
                        instructor_ref = str(row.get("instructor_ref", "") or "")
                    else:
                        instructor_ref = ""
                        row["instructor_ref"] = None
                        row["quality_factor"] = round(internal_quality, 6)
                        row["source"] = "self_practice_due_instructor_time_limit"
                else:
                    instructor_ref = ""

            if not instructor_ref:
                row["instructor_duty"] = {
                    "model": "direct_personalized",
                    "requested_hours": round(requested_duty, 6),
                    "reserved_hours": 0.0,
                    "availability_factor": 0.0,
                    "window_start": str(window_start),
                    "window_end": str(window_end),
                    "reservation_ref": None,
                }
                contexts[dref] = row
                continue

            reservation_ref = f"{evidence_ref}:instructor:{instructor_ref}:{dref}"
            try:
                path = runtime.owner_path(instructor_ref)
                instructor = _copy_person_for_training_time(runtime.read(path))
                duty = reserve_person_training_time(
                    instructor, requested_hours=requested_duty, window_start=window_start, window_end=window_end,
                    reservation_ref=reservation_ref, kind="instructor_duty", training_rules=training_rules,
                    metadata={
                        "program_ref": program_ref, "drill_ref": dref,
                        "student_count": max(0, int(student_count)), "practice_mode": mode,
                        "delivery_model": "direct_personalized",
                    },
                )
                runtime.put(path, instructor)
                duty_factor = max(0.0, min(1.0, float(duty.get("availability_factor", 0.0) or 0.0)))
                selected_quality = max(0.0, min(1.35, float(row.get("quality_factor", internal_quality) or 0.0)))
                effective_quality = internal_quality + (selected_quality - internal_quality) * duty_factor
                row["quality_factor"] = round(max(0.0, min(1.35, effective_quality)), 6)
                row["instructor_duty"] = {
                    "model": "direct_personalized",
                    "requested_hours": round(requested_duty, 6),
                    "reserved_hours": round(float(duty.get("reserved_hours", 0.0) or 0.0), 6),
                    "availability_factor": round(duty_factor, 6),
                    "window_start": str(window_start), "window_end": str(window_end),
                    "reservation_ref": reservation_ref,
                }
                if duty_factor <= 1e-12:
                    row["selected_instructor_ref"] = instructor_ref
                    row["instructor_ref"] = None
                    row["source"] = "self_practice_due_instructor_time_limit"
            except (KeyError, ValueError, FileNotFoundError):
                row["selected_instructor_ref"] = instructor_ref
                row["instructor_ref"] = None
                row["quality_factor"] = round(internal_quality, 6)
                row["source"] = "self_practice_due_missing_instructor_owner"
                row["instructor_duty"] = {
                    "model": "direct_personalized",
                    "requested_hours": round(requested_duty, 6), "reserved_hours": 0.0,
                    "availability_factor": 0.0, "window_start": str(window_start),
                    "window_end": str(window_end), "reservation_ref": reservation_ref,
                }
        contexts[dref] = row
    return contexts


__all__ = [
    "best_instructor_for_drill",
    "direct_instruction_capacity",
    "distributed_instructor_capacity",
    "exact_person_drill_access",
    "instructor_contexts_for_program",
]

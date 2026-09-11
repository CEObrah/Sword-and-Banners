"""Deterministic persistent-Unit establishment geometry.

A persistent military Unit has a durable authorized fighting establishment
separate from its current surviving fighting manpower. Formation-level command
personnel are conserved separately as external Unit-command attachments and do
not consume fighting-establishment billets. Unit establishments are never
inferred from post-casualty headcount: they are at least 500 and use 100-man
increments so mixed formations do not have to hide real combat arms as support.
Smaller persistent formations are detachments/commands, not Units.

Standard internal Unit echelons are 1,000 -> 500 -> 100. The Unit commander owns
the Unit echelon; internal billets are strictly subordinate and are derived from
the actual role composition rather than an automatically generated binary tree.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

UNIT_MIN = 500
UNIT_STEP = 100
UNIT_INTERNAL_SCALES = (1000, 500, 100)
DETACHMENT_INTERNAL_SCALES = (100,)


def represented_establishment_composition(formation: Mapping[str, Any]) -> dict[str, int]:
    """Return current fighting bodies by role.

    External Unit-command attachments are conserved personnel, but they are
    outside the formation's fighting establishment and therefore never alter the
    authorized fighting role mix used by reconstitution.
    """
    represented: dict[str, int] = {}
    raw = formation.get("composition")
    if isinstance(raw, Mapping):
        for role, value in raw.items():
            count = max(0, int(value))
            if count:
                represented[str(role)] = represented.get(str(role), 0) + count
    return represented


def represented_establishment_personnel(formation: Mapping[str, Any]) -> int:
    return sum(represented_establishment_composition(formation).values())


def round_unit_strength(value: int) -> int:
    n = max(0, int(value))
    if n <= UNIT_MIN:
        return UNIT_MIN
    return ((n + UNIT_STEP - 1) // UNIT_STEP) * UNIT_STEP


def classify_formation(*, personnel: int, explicit: Any = None) -> str:
    text = str(explicit or "").strip().lower()
    if text in {"unit", "detachment"}:
        return text
    return "unit" if max(0, int(personnel)) >= UNIT_MIN else "detachment"



def _saved_hierarchy_establishment(formation: Mapping[str, Any]) -> int:
    """Infer legacy authorized strength from an already-saved internal tree.

    A saved 100-man layer is the strongest evidence because every lawful Unit
    establishment uses 100-man increments and therefore has exactly one 100-man
    element per hundred authorized fighters. 500 and 1,000 layers are fallback
    evidence for older records that omitted the 100 layer. This inference is used
    only when no explicit authorized_strength/establishment_composition exists.
    """
    structure = formation.get("command_structure") if isinstance(formation.get("command_structure"), Mapping) else {}
    raw = structure.get("internal_hierarchy") if isinstance(structure, Mapping) else None
    rows: list[Mapping[str, Any]] = []
    if isinstance(raw, list):
        rows = [row for row in raw if isinstance(row, Mapping)]
    elif isinstance(raw, Mapping):
        summary = raw.get("summary")
        if isinstance(summary, list):
            rows = [row for row in summary if isinstance(row, Mapping)]
        if not rows:
            by_role = raw.get("by_role")
            if isinstance(by_role, Mapping):
                counts = {1000: 0, 500: 0, 100: 0}
                for role_row in by_role.values():
                    if not isinstance(role_row, Mapping):
                        continue
                    counts[1000] += max(0, int(role_row.get("commanders_1000", 0) or 0))
                    counts[500] += max(0, int(role_row.get("commanders_500", 0) or 0))
                    counts[100] += max(0, int(role_row.get("commanders_100", 0) or 0))
                rows = [{"scale": scale, "count": count} for scale, count in counts.items() if count > 0]
    counts = {max(0, int(row.get("scale", 0) or 0)): max(0, int(row.get("count", row.get("authorized_count", 0)) or 0)) for row in rows}
    if counts.get(100, 0) > 0:
        return counts[100] * 100
    if counts.get(500, 0) > 0:
        return counts[500] * 500
    # A legacy 1,000 layer at the same scale as a 1,000 Unit was redundant, so
    # use it only as a lower bound. Rounding keeps the result lawful.
    if counts.get(1000, 0) > 0:
        return counts[1000] * 1000
    return 0



def formation_class_for(formation: Mapping[str, Any] | None = None, *, personnel: int | None = None, explicit: Any = None) -> str:
    """Resolve durable Unit/detachment class from saved establishment evidence.

    Legacy formations may have fallen below 500 current personnel after casualties
    without an explicit ``formation_class``.  A saved Unit-scale establishment or
    hierarchy therefore takes precedence over current headcount.
    """
    formation = formation or {}
    saved_explicit = explicit if explicit is not None else formation.get("formation_class")
    text = str(saved_explicit or "").strip().lower()
    if text in {"unit", "detachment"}:
        return text
    current = max(0, int(personnel if personnel is not None else formation.get("personnel", 0) or 0))
    saved_authorized = max(0, int(formation.get("authorized_strength", 0) or 0))
    est = formation.get("establishment_composition")
    est_total = sum(max(0, int(v)) for v in est.values()) if isinstance(est, Mapping) else 0
    tree_total = _saved_hierarchy_establishment(formation)
    if max(saved_authorized, est_total, tree_total) >= UNIT_MIN:
        return "unit"
    return classify_formation(personnel=current, explicit=None)

def authorized_strength_for(
    formation: Mapping[str, Any] | None = None,
    *,
    personnel: int | None = None,
    explicit_authorized: int | None = None,
    formation_class: str | None = None,
) -> int:
    formation = formation or {}
    current = max(0, int(personnel if personnel is not None else formation.get("personnel", 0) or 0))
    klass = formation_class_for(
        formation, personnel=current,
        explicit=formation_class if formation_class is not None else formation.get("formation_class"),
    )
    raw = explicit_authorized
    explicit_saved = raw is not None
    if raw is None and formation.get("authorized_strength") is not None:
        raw = int(formation.get("authorized_strength") or 0)
        explicit_saved = True
    if raw is None:
        est = formation.get("establishment_composition")
        est_total = sum(max(0, int(v)) for v in est.values()) if isinstance(est, Mapping) else 0
        saved_tree = _saved_hierarchy_establishment(formation)
        raw = max(current, est_total, saved_tree)
    authorized = max(0, int(raw or 0))
    if klass == "unit":
        # A saved establishment is durable authority. Current manpower may fall
        # below it through casualties, but may not silently enlarge it. Legacy
        # formations with no saved establishment are initialized once from their
        # current strength rounded to the next lawful 500-man Unit size.
        return authorized if explicit_saved else round_unit_strength(authorized)
    # Detachments are deliberately not Units.  Their top commander owns the
    # detachment itself, and their authorized strength may be below 500.
    return max(current, authorized)


def validate_establishment(*, personnel: int, authorized_strength: int, formation_class: str) -> None:
    current = max(0, int(personnel))
    authorized = max(0, int(authorized_strength))
    klass = classify_formation(personnel=current, explicit=formation_class)
    if authorized < current:
        raise ValueError("authorized_strength cannot be below current formation personnel")
    if klass == "unit":
        if authorized < UNIT_MIN or authorized % UNIT_STEP:
            raise ValueError("Unit authorized_strength must be at least 500 and a multiple of 100")
    elif authorized >= UNIT_MIN:
        # A persistent formation of Unit scale must use Unit organization.  This
        # prevents large arbitrary 'detachments' from becoming a backdoor to a
        # 1,200-man command tree.
        raise ValueError("detachment authorized_strength must remain below 500")


def _largest_remainder_scale(counts: Mapping[str, Any], target: int) -> dict[str, int]:
    target = max(0, int(target))
    clean = {str(k): max(0, int(v)) for k, v in counts.items() if max(0, int(v)) > 0}
    if target <= 0 or not clean:
        return {}
    total = sum(clean.values())
    raw = {k: target * v / total for k, v in clean.items()}
    result = {k: int(raw[k]) for k in clean}
    remaining = target - sum(result.values())
    order = sorted(clean, key=lambda k: (-(raw[k] - result[k]), k))
    for key in order[:remaining]:
        result[key] += 1
    return {k: v for k, v in result.items() if v > 0}


def establishment_composition(current_composition: Mapping[str, Any], authorized_strength: int) -> dict[str, int]:
    return _largest_remainder_scale(current_composition, authorized_strength)



def command_rank_grade_for_span(authorized_strength: int) -> str:
    """Return the numerical command tier implied by one authorized span.

    This is classification only. Durable personal rank still changes only through
    explicit promotion/demotion or an explicit development rebaseline. Casualty
    survivors therefore do not silently demote a commander.
    """
    n = max(0, int(authorized_strength))
    if n >= 10000:
        return "general"
    if n >= 2000:
        return f"{min(9, n // 1000)}000_commander"
    if n >= 1000:
        return "1000_commander"
    if n >= 500:
        return "500_commander"
    if n >= 100:
        return "100_commander"
    return "unranked"


def _top_numeric_rank_scale(authorized_strength: int) -> int:
    grade = command_rank_grade_for_span(authorized_strength)
    if grade.endswith("000_commander"):
        return int(grade.split("_", 1)[0])
    if grade == "500_commander":
        return 500
    if grade == "100_commander":
        return 100
    return max(2000, int(authorized_strength)) if grade == "general" else 0


def _role_direct_segments(role_count: int, top_scale: int) -> list[int]:
    """Partition one physical role into lawful direct tactical bodies.

    A segment at the same formal scale as the top commander is never created.
    Thus a 1,500-person Unit led at the 1,000 tier uses three 500 bodies, while
    a 2,100-person Unit led at the 2,000 tier may use 1,000/500/100 children.
    """
    remaining = max(0, int(role_count))
    segments: list[int] = []
    if top_scale > 1000:
        while remaining >= 1000:
            segments.append(1000)
            remaining -= 1000
    if top_scale > 500:
        while remaining >= 500:
            segments.append(500)
            remaining -= 500
    while remaining >= 100:
        segments.append(100)
        remaining -= 100
    if remaining:
        raise ValueError("formation role composition must use 100-man increments")
    return segments


def hierarchy_counts_by_role(*, composition: Mapping[str, Any], authorized_strength: int, formation_class: str) -> dict[int, int]:
    authorized = max(0, int(authorized_strength))
    klass = classify_formation(personnel=authorized, explicit=formation_class)
    if authorized <= 0:
        return {}
    if klass != "unit":
        return {100: authorized // 100} if authorized > 100 else {}
    top_scale = _top_numeric_rank_scale(authorized)
    # Casualty survivors and proportionally reconstructed legacy establishments
    # may have arbitrary per-role headcounts. Command geometry stays exact at the
    # Unit level and becomes role-specific only when the authorized role mix itself
    # is 100-man granular. This preserves arbitrary casualty counts without making
    # a 37-person tail into a fictional new echelon.
    clean = {str(role): max(0, int(raw or 0)) for role, raw in composition.items() if max(0, int(raw or 0)) > 0}
    role_granular = sum(clean.values()) == authorized and all(count % 100 == 0 for count in clean.values())
    source = clean if role_granular else {"all": authorized}
    direct: list[int] = []
    for role in sorted(source):
        count = source[role]
        if count:
            direct.extend(_role_direct_segments(count, top_scale))
    if sum(direct) != authorized:
        raise ValueError("command topology does not reconcile authorized strength")
    counts = {1000: 0, 500: 0, 100: 0}
    for scale in direct:
        if scale == 1000:
            counts[1000] += 1
            counts[500] += 2
            counts[100] += 10
        elif scale == 500:
            counts[500] += 1
            counts[100] += 5
        elif scale == 100:
            counts[100] += 1
    return {scale: count for scale, count in counts.items() if count > 0}

def hierarchy_counts(*, authorized_strength: int, formation_class: str, composition: Mapping[str, Any] | None = None) -> dict[int, int]:
    authorized = max(0, int(authorized_strength))
    klass = classify_formation(personnel=authorized, explicit=formation_class)
    if authorized <= 0:
        return {}
    if klass == "unit":
        validate_establishment(personnel=authorized, authorized_strength=authorized, formation_class=klass)
        comp = composition if isinstance(composition, Mapping) and composition else {"all": authorized}
        if sum(max(0, int(v or 0)) for v in comp.values()) != authorized:
            comp = {"all": authorized}
        return hierarchy_counts_by_role(composition=comp, authorized_strength=authorized, formation_class=klass)
    if authorized > 100:
        return {100: authorized // 100}
    return {}


def hierarchy_topology(*, authorized_strength: int, formation_class: str, composition: Mapping[str, Any] | None = None) -> dict[str, Any]:
    authorized = max(0, int(authorized_strength))
    klass = classify_formation(personnel=authorized, explicit=formation_class)
    comp = composition if isinstance(composition, Mapping) and composition else {"all": authorized}
    if sum(max(0, int(v or 0)) for v in comp.values()) != authorized:
        comp = {"all": authorized}
    counts = hierarchy_counts(authorized_strength=authorized, formation_class=klass, composition=comp)
    if klass == "unit":
        top_scale = _top_numeric_rank_scale(authorized)
        direct_by_role: dict[str, list[dict[str, int]]] = {}
        direct_summary: dict[int, int] = {}
        granular = all(max(0, int(v or 0)) % 100 == 0 for v in comp.values()) and sum(max(0, int(v or 0)) for v in comp.values()) == authorized
        topology_comp = comp if granular else {"all": authorized}
        for role in sorted(topology_comp):
            segments = _role_direct_segments(max(0, int(topology_comp[role] or 0)), top_scale)
            role_counts: dict[int, int] = {}
            for scale in segments:
                role_counts[scale] = role_counts.get(scale, 0) + 1
                direct_summary[scale] = direct_summary.get(scale, 0) + 1
            direct_by_role[str(role)] = [
                {"scale": scale, "count": count}
                for scale, count in sorted(role_counts.items(), reverse=True)
            ]
        return {
            "formation_class": "unit",
            "unit_command_scale": authorized,
            "recognized_commander_grade": command_rank_grade_for_span(authorized),
            "direct_subordinates": [
                {"scale": scale, "count": count}
                for scale, count in sorted(direct_summary.items(), reverse=True)
            ],
            "direct_subordinates_by_role": direct_by_role,
            "children_per_parent": {
                "1000": [{"scale": 500, "count": 2}],
                "500": [{"scale": 100, "count": 5}],
            },
            "summary_counts": {str(k): v for k, v in counts.items()},
            "rule": "The Unit commander owns the top echelon. Internal 1,000/500/100 bodies are role-aware, strictly subordinate, and remain fixed through casualties; no second top-command or higher arithmetic layer is auto-created.",
        }
    return {
        "formation_class": "detachment",
        "unit_command_scale": authorized,
        "recognized_commander_grade": command_rank_grade_for_span(authorized),
        "direct_subordinates": ([{"scale": 100, "count": counts[100]}] if 100 in counts else []),
        "direct_subordinates_by_role": {},
        "children_per_parent": {},
        "summary_counts": {str(k): v for k, v in counts.items()},
        "rule": "Sub-500 persistent commands are detachments, not Units; their top commander owns the detachment echelon.",
    }



def freeze_establishment_composition(formation: dict[str, Any]) -> None:
    """Freeze the pre-loss role mix only when future casualties need it.

    Full-strength formations derive their authorized mix directly from current
    composition.  Once a composition-changing loss is about to occur, this
    compact override preserves the authorized pre-loss mix so reconstitution
    does not learn the casualty pattern as a new establishment.
    """
    current = max(0, int(formation.get("personnel", 0) or 0))
    klass = formation_class_for(formation, personnel=current, explicit=formation.get("formation_class"))
    authorized = authorized_strength_for(formation, personnel=current, formation_class=klass)
    existing = formation.get("establishment_composition")
    if isinstance(existing, Mapping) and sum(max(0, int(v)) for v in existing.values()) == authorized:
        return
    represented = represented_establishment_composition(formation)
    if represented and sum(represented.values()) == authorized:
        formation["establishment_composition"] = represented


def normalize_formation_establishment(formation: dict[str, Any]) -> dict[str, Any]:
    """Normalize the compact durable Unit/detachment establishment.

    Formation class and authorized strength are authoritative.  Role mix is
    persisted only when it is an exceptional or casualty-preservation override;
    command topology is always derived.
    """
    current = max(0, int(formation.get("personnel", 0) or 0))
    klass = formation_class_for(formation, personnel=current, explicit=formation.get("formation_class"))
    authorized = authorized_strength_for(formation, personnel=current, formation_class=klass)
    validate_establishment(personnel=current, authorized_strength=authorized, formation_class=klass)
    formation["formation_class"] = klass
    formation["authorized_strength"] = authorized

    current_comp = formation.get("composition") if isinstance(formation.get("composition"), Mapping) else {}
    represented_comp = represented_establishment_composition(formation)
    saved_est = formation.get("establishment_composition") if isinstance(formation.get("establishment_composition"), Mapping) else {}
    represented_total = sum(represented_comp.values())
    saved_total = sum(max(0, int(v)) for v in saved_est.values())
    if saved_est and saved_total == authorized:
        normalized_saved = {str(k): max(0, int(v)) for k, v in saved_est.items() if max(0, int(v)) > 0}
        if represented_total == authorized and normalized_saved == represented_comp:
            formation.pop("establishment_composition", None)
        else:
            formation["establishment_composition"] = normalized_saved
    elif represented_comp and represented_total == authorized:
        formation.pop("establishment_composition", None)
    elif represented_comp:
        formation["establishment_composition"] = establishment_composition(represented_comp, authorized)

    rows = hierarchy_rows(
        authorized_strength=authorized, current_personnel=current, formation_class=klass, composition=(formation.get("establishment_composition") if isinstance(formation.get("establishment_composition"), Mapping) else represented_comp)
    )
    return {
        "formation_class": klass,
        "authorized_strength": authorized,
        "current_personnel": current,
        "internal_hierarchy": rows,
        "establishment_topology": hierarchy_topology(authorized_strength=authorized, formation_class=klass, composition=(formation.get("establishment_composition") if isinstance(formation.get("establishment_composition"), Mapping) else represented_comp)),
    }


def _existing_hierarchy_rows(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [dict(row) for row in raw if isinstance(row, Mapping)]
    if isinstance(raw, Mapping):
        summary = raw.get("summary")
        if isinstance(summary, list):
            return [dict(row) for row in summary if isinstance(row, Mapping)]
    return []

def hierarchy_rows(
    *,
    authorized_strength: int,
    current_personnel: int,
    formation_class: str,
    representation_by_scale: Mapping[int, str] | None = None,
    composition: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    representations = representation_by_scale or {}
    current = max(0, int(current_personnel))
    rows: list[dict[str, Any]] = []
    for scale, count in hierarchy_counts(
        authorized_strength=authorized_strength,
        formation_class=formation_class, composition=composition,
    ).items():
        full = min(count, current // scale) if current else 0
        tail = current % scale if current and count > full else 0
        rows.append({
            "scale": scale,
            "count": count,
            "authorized_count": count,
            "full_elements": full,
            "partial_tail_personnel": tail,
            "current_strength_fraction": round(current / max(1, authorized_strength), 6),
            "representation": str(representations.get(scale, "aggregate")),
            "inside_fighting_establishment": True,
        })
    return rows

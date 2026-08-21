"""Deterministic persistent-Unit establishment geometry.

A persistent military Unit has a durable authorized fighting establishment that is
separate from its current surviving manpower.  Unit establishments are never
inferred from post-casualty headcount: they are at least 500 and always a
multiple of 500.  Smaller persistent formations are detachments/commands, not
Units.

Standard internal Unit echelons are 1,000 -> 500 -> 100.  The Unit commander and
formal deputy occupy the Unit's own command echelon outside fighting strength,
so no internal billet may exist at the same or a larger scale than the Unit.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

UNIT_MIN = 500
UNIT_STEP = 500
UNIT_INTERNAL_SCALES = (1000, 500, 100)
DETACHMENT_INTERNAL_SCALES = (100,)


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
    establishment is a multiple of 500 and therefore has exactly one 100-man
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
            raise ValueError("Unit authorized_strength must be at least 500 and a multiple of 500")
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


def hierarchy_counts(*, authorized_strength: int, formation_class: str) -> dict[int, int]:
    authorized = max(0, int(authorized_strength))
    klass = classify_formation(personnel=authorized, explicit=formation_class)
    if authorized <= 0:
        return {}
    if klass == "unit":
        validate_establishment(personnel=min(authorized, authorized), authorized_strength=authorized, formation_class=klass)
        result: dict[int, int] = {}
        # 1,000 command exists only strictly below the Unit command.  At 1,500,
        # floor(1500/1000)=1, giving 1 x 1,000 + a direct 500 remainder.
        if authorized > 1000:
            result[1000] = authorized // 1000
        if authorized > 500:
            result[500] = authorized // 500
        if authorized > 100:
            result[100] = authorized // 100
        return result
    # Sub-500 detachments use only subordinate 100-man elements, again strictly
    # smaller than the detachment itself.  A 100-man command therefore has no
    # redundant internal 100-man commander.
    if authorized > 100:
        return {100: (authorized + 99) // 100}
    return {}


def hierarchy_topology(*, authorized_strength: int, formation_class: str) -> dict[str, Any]:
    authorized = max(0, int(authorized_strength))
    klass = classify_formation(personnel=authorized, explicit=formation_class)
    counts = hierarchy_counts(authorized_strength=authorized, formation_class=klass)
    if klass == "unit":
        direct: list[dict[str, int]] = []
        if authorized == 500:
            direct.append({"scale": 100, "count": 5})
        elif authorized == 1000:
            direct.append({"scale": 500, "count": 2})
        elif authorized > 1000:
            thousands = authorized // 1000
            remainder = authorized % 1000
            if thousands:
                direct.append({"scale": 1000, "count": thousands})
            if remainder >= 500:
                direct.append({"scale": 500, "count": 1})
        return {
            "formation_class": "unit",
            "unit_command_scale": authorized,
            "direct_subordinates": direct,
            "children_per_parent": {
                "1000": [{"scale": 500, "count": 2}],
                "500": [{"scale": 100, "count": 5}],
            },
            "summary_counts": {str(k): v for k, v in counts.items()},
            "rule": "Unit commander/deputy own the Unit echelon; internal 1,000/500/100 billets are strictly subordinate and remain fixed through casualties.",
        }
    return {
        "formation_class": "detachment",
        "unit_command_scale": authorized,
        "direct_subordinates": ([{"scale": 100, "count": counts[100]}] if 100 in counts else []),
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
    composition = formation.get("composition")
    if isinstance(composition, Mapping) and sum(max(0, int(v)) for v in composition.values()) == current == authorized:
        formation["establishment_composition"] = {str(k): max(0, int(v)) for k, v in composition.items() if max(0, int(v)) > 0}


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
    saved_est = formation.get("establishment_composition") if isinstance(formation.get("establishment_composition"), Mapping) else {}
    current_total = sum(max(0, int(v)) for v in current_comp.values())
    saved_total = sum(max(0, int(v)) for v in saved_est.values())
    if saved_est and saved_total == authorized:
        normalized_saved = {str(k): max(0, int(v)) for k, v in saved_est.items() if max(0, int(v)) > 0}
        normalized_current = {str(k): max(0, int(v)) for k, v in current_comp.items() if max(0, int(v)) > 0}
        if current_total == authorized and normalized_saved == normalized_current:
            formation.pop("establishment_composition", None)
        else:
            formation["establishment_composition"] = normalized_saved
    elif current_comp and current_total == authorized:
        formation.pop("establishment_composition", None)
    elif current_comp:
        # Legacy under-strength records without an explicit target are repaired
        # deterministically, but new casualty paths freeze before mutation.
        formation["establishment_composition"] = establishment_composition(current_comp, authorized)

    rows = hierarchy_rows(
        authorized_strength=authorized, current_personnel=current, formation_class=klass
    )
    return {
        "formation_class": klass,
        "authorized_strength": authorized,
        "current_personnel": current,
        "internal_hierarchy": rows,
        "establishment_topology": hierarchy_topology(authorized_strength=authorized, formation_class=klass),
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
) -> list[dict[str, Any]]:
    representations = representation_by_scale or {}
    current = max(0, int(current_personnel))
    rows: list[dict[str, Any]] = []
    for scale, count in hierarchy_counts(
        authorized_strength=authorized_strength,
        formation_class=formation_class,
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

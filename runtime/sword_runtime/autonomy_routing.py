"""Fair bounded routing for large autonomous formation sets.

A bounded working window is allowed for cost control, but it must rotate so an
exact formation outside the first page never becomes permanently ineligible.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

AUTONOMY_CANDIDATE_WINDOW = 24


def rotating_candidate_refs(
    refs: Sequence[str],
    cursor: int,
    limit: int = AUTONOMY_CANDIDATE_WINDOW,
) -> tuple[list[str], int]:
    values = sorted(set(str(ref) for ref in refs if isinstance(ref, str) and ref))
    if not values:
        return [], 0
    if isinstance(cursor, bool) or not isinstance(cursor, int):
        cursor = 0
    start = cursor % len(values)
    count = min(max(1, int(limit)), len(values))
    window = [values[(start + index) % len(values)] for index in range(count)]
    return window, (start + count) % len(values)


def select_formations_fair(
    planner: Any,
    state: str,
    objective_text: str,
    memory: dict[str, Any],
    *,
    reserved: set[str],
    count: int = 2,
) -> list[str]:
    force = planner.read(f"state/forces/state-{state}.json")
    allocated = force.get("allocated_to_formations") if isinstance(force, Mapping) else None
    refs = [str(ref) for ref in allocated] if isinstance(allocated, Mapping) else []
    state_memory = planner._state_memory(memory, state)
    cursor = int(state_memory.get("formation_candidate_cursor", 0))
    window, next_cursor = rotating_candidate_refs(refs, cursor)
    state_memory["formation_candidate_cursor"] = next_cursor

    candidates: list[tuple[int, str, frozenset[str]]] = []
    for ref in window:
        try:
            _path, formation = planner._load_formation(ref)
        except ValueError:
            continue
        if str(formation.get("administrative_owner")) != f"state_{state}":
            continue
        score = planner._formation_score(ref, formation, objective_text, memory, reserved)
        if score <= -(10**8):
            continue
        roles = planner._formation_roles(formation) if hasattr(planner, "_formation_roles") else {planner._formation_role(formation): 1}
        candidates.append((score, ref, frozenset(roles)))
    candidates.sort(key=lambda row: (-row[0], row[1]))
    if not candidates:
        return []

    selected: list[tuple[int, str, frozenset[str]]] = [candidates[0]]
    while len(selected) < min(count, len(candidates)):
        selected_refs = {row[1] for row in selected}
        used_roles = set().union(*(row[2] for row in selected))
        remaining = [row for row in candidates if row[1] not in selected_refs]
        if not remaining:
            break
        remaining.sort(
            key=lambda row: (
                -(row[0] + (90 if row[2] - used_roles else 0)),
                row[1],
            )
        )
        selected.append(remaining[0])
    return [row[1] for row in selected]


__all__ = ["AUTONOMY_CANDIDATE_WINDOW", "rotating_candidate_refs", "select_formations_fair"]

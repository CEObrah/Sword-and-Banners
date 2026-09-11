"""Scoped command authority for recursive armies and explicit command staff.

A strategist is attached to one exact zero-body command group.  That appointment
can carry registered recursive order authority over that group's entire subtree:
its direct formations, direct nested armies, and every descendant unit beneath
those nested armies.  The scope never reaches upward into the parent command or
sideways into a sibling command unless the same person is separately assigned
there.

Routine planning still follows the chain of command.  Recursive order authority
means a strategist *may address* any lawful descendant when needed; it does not
force higher headquarters to bypass subordinate commanders on every order.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

_POLICY_PATH = "game/data/mechanics/command-staff.json"
_GROUP_PREFIX = "state/cmd/command-groups/"


def group_path(group_ref: str) -> str:
    return f"{_GROUP_PREFIX}{group_ref}.json"


def read_group(read: Callable[[str], Any], group_ref: str) -> Mapping[str, Any]:
    row = read(group_path(group_ref))
    if not isinstance(row, Mapping) or row.get("schema") != "command-group":
        raise ValueError(f"invalid command group: {group_ref}")
    return row


def staff_role_policy(read: Callable[[str], Any], role: str | None) -> Mapping[str, Any]:
    if not isinstance(role, str) or not role:
        return {}
    doc = read(_POLICY_PATH)
    roles = doc.get("roles") if isinstance(doc, Mapping) else None
    row = roles.get(role) if isinstance(roles, Mapping) else None
    if not isinstance(row, Mapping) and isinstance(roles, Mapping):
        row = roles.get(role.casefold())
    return row if isinstance(row, Mapping) else {}


def staff_role(group: Mapping[str, Any], person_ref: str) -> str | None:
    assignments = group.get("role_assignments")
    if not isinstance(assignments, Mapping):
        return None
    value = assignments.get(person_ref)
    return str(value) if isinstance(value, str) and value else None


def strategist_refs(group: Mapping[str, Any]) -> list[str]:
    assignments = group.get("role_assignments")
    if not isinstance(assignments, Mapping):
        return []
    return sorted(
        str(person_ref)
        for person_ref, role in assignments.items()
        if isinstance(person_ref, str) and person_ref and str(role).casefold() == "strategist"
    )


def ancestor_chain(read: Callable[[str], Any], target_group_ref: str, *, limit: int = 32) -> list[tuple[str, Mapping[str, Any]]]:
    """Return target -> root command chain, failing closed on cycles."""
    out: list[tuple[str, Mapping[str, Any]]] = []
    current = target_group_ref
    seen: set[str] = set()
    for _ in range(limit):
        if current in seen:
            raise ValueError("command hierarchy contains a cycle")
        seen.add(current)
        group = read_group(read, current)
        out.append((current, group))
        parent = group.get("parent_command_group_ref")
        if not isinstance(parent, str) or not parent:
            return out
        current = parent
    raise ValueError("command hierarchy exceeds supported recursion depth")


def group_within_scope(read: Callable[[str], Any], *, scope_root_ref: str, target_group_ref: str) -> bool:
    return any(ref == scope_root_ref for ref, _group in ancestor_chain(read, target_group_ref))


def scoped_staff_order_authority(
    read: Callable[[str], Any],
    *,
    person_ref: str,
    target_group_ref: str,
) -> dict[str, Any]:
    """Resolve explicit staff order authority over one command-group target.

    The target chain itself is sufficient evidence: if the person is a strategist
    on any ancestor command group, that assignment is the exact scope root.
    """
    for depth, (group_ref, group) in enumerate(ancestor_chain(read, target_group_ref)):
        role = staff_role(group, person_ref)
        if not role:
            continue
        policy = staff_role_policy(read, role)
        recursive = bool(policy.get("recursive_order_authority"))
        if group_ref == target_group_ref or recursive:
            return {
                "allowed": True,
                "person_ref": person_ref,
                "role": role,
                "scope_root_ref": group_ref,
                "target_group_ref": target_group_ref,
                "scope_depth": depth,
                "recursive": recursive,
                "chain_of_command_default": bool(policy.get("chain_of_command_default", True)),
                "knowledge_rule": policy.get("knowledge_rule"),
                "communication_rule": policy.get("communication_rule"),
            }
    return {
        "allowed": False,
        "person_ref": person_ref,
        "role": None,
        "scope_root_ref": None,
        "target_group_ref": target_group_ref,
        "scope_depth": None,
        "recursive": False,
    }


def person_order_authority(
    read: Callable[[str], Any],
    *,
    person_ref: str,
    target_group_ref: str,
) -> dict[str, Any]:
    """Resolve commander/authority or scoped staff authority over a target.

    A commander/authority on an ancestor has normal recursive command authority.
    A registered strategist has the narrower staff authority described above.
    """
    for depth, (group_ref, group) in enumerate(ancestor_chain(read, target_group_ref)):
        if person_ref in {str(group.get("commander_ref") or ""), str(group.get("authority_ref") or "")}:
            return {
                "allowed": True,
                "person_ref": person_ref,
                "role": "commander_or_command_authority",
                "scope_root_ref": group_ref,
                "target_group_ref": target_group_ref,
                "scope_depth": depth,
                "recursive": True,
                "chain_of_command_default": True,
            }
    return scoped_staff_order_authority(read, person_ref=person_ref, target_group_ref=target_group_ref)


def command_routing_from_groups(read: Callable[[str], Any], group_refs: list[str]) -> dict[str, list[str]]:
    """Build a non-authoritative person -> groups-commanded routing projection.

    One person may lawfully command more than one zero-body command group. This is
    required for structures such as a field commander who also retains a direct
    mobile command. The projection never changes authority; exact group records do.
    """
    routing: dict[str, list[str]] = {}
    for group_ref in sorted(set(group_refs)):
        group = read_group(read, group_ref)
        person_ref = group.get("commander_ref")
        if isinstance(person_ref, str) and person_ref:
            routing.setdefault(person_ref, []).append(group_ref)
    return {person_ref: sorted(set(refs)) for person_ref, refs in sorted(routing.items())}


def membership_routing_from_groups(read: Callable[[str], Any], group_refs: list[str]) -> dict[str, list[str]]:
    """Build person -> direct command-group membership routing.

    Direct membership includes explicit staff and other zero-body group personnel,
    but does not itself grant command authority.
    """
    routing: dict[str, list[str]] = {}
    for group_ref in sorted(set(group_refs)):
        group = read_group(read, group_ref)
        for person_ref in group.get("direct_person_refs", []) if isinstance(group.get("direct_person_refs"), list) else []:
            if isinstance(person_ref, str) and person_ref:
                routing.setdefault(person_ref, []).append(group_ref)
    return {person_ref: sorted(set(refs)) for person_ref, refs in sorted(routing.items())}


def primary_person_routing_from_groups(read: Callable[[str], Any], group_refs: list[str]) -> dict[str, str]:
    """Choose one deterministic primary organizational group per routed person.

    A real command outranks staff/membership routing. When a person commands
    several groups, the group with the largest recursive strength is primary; a
    root command wins an exact-strength tie, followed by stable group identity.
    This is a projection only. `command_person_groups` preserves the full set.
    """
    command = command_routing_from_groups(read, group_refs)
    membership = membership_routing_from_groups(read, group_refs)

    def choose(refs: list[str]) -> str:
        rows: list[tuple[int, int, str]] = []
        for ref in sorted(set(refs)):
            group = read_group(read, ref)
            org = group.get("organizational_state") if isinstance(group.get("organizational_state"), Mapping) else {}
            strength = int(org.get("current_recursive_strength", org.get("authorized_strength", 0)) or 0)
            is_child = 1 if isinstance(group.get("parent_command_group_ref"), str) and group.get("parent_command_group_ref") else 0
            rows.append((-strength, is_child, ref))
        return sorted(rows)[0][2]

    out: dict[str, str] = {}
    for person_ref in sorted(set(command) | set(membership)):
        refs = command.get(person_ref) or membership.get(person_ref) or []
        if refs:
            out[person_ref] = choose(list(refs))
    return out


def staff_routing_from_groups(read: Callable[[str], Any], group_refs: list[str]) -> dict[str, list[str]]:
    """Build a non-authoritative person -> staff-appointment routing projection."""
    routing: dict[str, list[str]] = {}
    for group_ref in sorted(set(group_refs)):
        group = read_group(read, group_ref)
        assignments = group.get("role_assignments")
        if not isinstance(assignments, Mapping):
            continue
        for person_ref, role in assignments.items():
            if not isinstance(person_ref, str) or not person_ref or not isinstance(role, str) or not role:
                continue
            routing.setdefault(person_ref, []).append(group_ref)
    return {person_ref: sorted(set(refs)) for person_ref, refs in sorted(routing.items())}

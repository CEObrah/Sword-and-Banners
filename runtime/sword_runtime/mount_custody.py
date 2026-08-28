"""Conserved aggregate horse custody helpers.

Mount pools own living horses that are not individually materialized. A horse is
in exactly one current physical partition: regional reserve, force-role reserve,
or formation allocation. Formation records mirror their allocated physical mount
count for combat, but the mount pool remains the conservation ledger.
"""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any


def _nonnegative(value: Any) -> int:
    return max(0, int(value or 0))


def _nested_horse_total(rows: Any) -> int:
    if not isinstance(rows, Mapping):
        return 0
    total = 0
    for value in rows.values():
        if isinstance(value, Mapping):
            if "horse" in value:
                total += _nonnegative(value.get("horse"))
            else:
                total += sum(_nonnegative(v) for v in value.values() if isinstance(v, (int, float)) and not isinstance(v, bool))
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            total += _nonnegative(value)
    return total


def mount_partition_horse_total(pool: Mapping[str, Any]) -> int:
    return (
        _nested_horse_total(pool.get("regional_reserve"))
        + _nested_horse_total(pool.get("allocated_to_formations"))
        + _nested_horse_total(pool.get("allocated_to_force_reserve"))
    )


def validate_mount_partitions(pool: Mapping[str, Any]) -> None:
    expected = _nonnegative((pool.get("types") or {}).get("horse", 0) if isinstance(pool.get("types"), Mapping) else 0)
    actual = mount_partition_horse_total(pool)
    if actual != expected:
        raise ValueError(f"mount horse partition conservation failed: partitions={actual}, type_total={expected}")


def regional_horses(pool: Mapping[str, Any], location_ref: str) -> int:
    regional = pool.get("regional_reserve", {}) if isinstance(pool.get("regional_reserve"), Mapping) else {}
    row = regional.get(location_ref, {}) if isinstance(regional, Mapping) else {}
    return _nonnegative(row.get("horse", 0)) if isinstance(row, Mapping) else 0


def force_role_horses(pool: Mapping[str, Any], location_ref: str, role: str) -> int:
    reserved = pool.get("allocated_to_force_reserve", {}) if isinstance(pool.get("allocated_to_force_reserve"), Mapping) else {}
    row = reserved.get(location_ref, {}) if isinstance(reserved, Mapping) else {}
    return _nonnegative(row.get(role, 0)) if isinstance(row, Mapping) else 0


def reserve_regional_horses_for_role(
    pool: MutableMapping[str, Any], *, location_ref: str, role: str, count: int
) -> int:
    requested = _nonnegative(count)
    if requested <= 0:
        return 0
    regional = pool.setdefault("regional_reserve", {})
    if not isinstance(regional, MutableMapping):
        raise ValueError("mount regional reserve is invalid")
    local = regional.setdefault(location_ref, {})
    if not isinstance(local, MutableMapping):
        raise ValueError("mount local reserve is invalid")
    available = _nonnegative(local.get("horse", 0))
    moved = min(requested, available)
    if moved <= 0:
        return 0
    local["horse"] = available - moved
    force_reserve = pool.setdefault("allocated_to_force_reserve", {})
    if not isinstance(force_reserve, MutableMapping):
        raise ValueError("mount force-reserve allocation is invalid")
    role_row = force_reserve.setdefault(location_ref, {})
    if not isinstance(role_row, MutableMapping):
        raise ValueError("mount force-reserve location row is invalid")
    role_row[role] = _nonnegative(role_row.get(role, 0)) + moved
    validate_mount_partitions(pool)
    return moved



def release_formation_horses_to_role_reserve(
    pool: MutableMapping[str, Any], *, formation_ref: str, location_ref: str, role: str, count: int
) -> int:
    """Move part of one formation's conserved horse allocation into role reserve.

    Used when mounted soldiers leave a standing formation for promotion. The horse
    remains House property at the same physical location and changes custody only;
    no remount is created or destroyed.
    """
    requested = _nonnegative(count)
    if requested <= 0:
        return 0
    allocated = pool.setdefault("allocated_to_formations", {})
    if not isinstance(allocated, MutableMapping):
        raise ValueError("mount formation allocation registry is invalid")
    row = allocated.get(formation_ref)
    if not isinstance(row, MutableMapping):
        return 0
    held = _nonnegative(row.get("horse", 0))
    moved = min(requested, held)
    if moved <= 0:
        return 0
    row["horse"] = held - moved
    if row["horse"] <= 0:
        allocated.pop(formation_ref, None)
    force_reserve = pool.setdefault("allocated_to_force_reserve", {})
    if not isinstance(force_reserve, MutableMapping):
        raise ValueError("mount force-reserve allocation is invalid")
    role_row = force_reserve.setdefault(location_ref, {})
    if not isinstance(role_row, MutableMapping):
        raise ValueError("mount force-reserve location row is invalid")
    role_row[role] = _nonnegative(role_row.get(role, 0)) + moved
    validate_mount_partitions(pool)
    return moved

def transfer_force_role_horses(
    pool: MutableMapping[str, Any], *, location_ref: str, source_role: str, destination_role: str, count: int
) -> int:
    requested = _nonnegative(count)
    if requested <= 0 or source_role == destination_role:
        return requested
    force_reserve = pool.setdefault("allocated_to_force_reserve", {})
    if not isinstance(force_reserve, MutableMapping):
        raise ValueError("mount force-reserve allocation is invalid")
    role_row = force_reserve.setdefault(location_ref, {})
    if not isinstance(role_row, MutableMapping):
        raise ValueError("mount force-reserve location row is invalid")
    available = _nonnegative(role_row.get(source_role, 0))
    moved = min(requested, available)
    if moved <= 0:
        return 0
    role_row[source_role] = available - moved
    role_row[destination_role] = _nonnegative(role_row.get(destination_role, 0)) + moved
    validate_mount_partitions(pool)
    return moved


def issue_force_role_horses_to_formation(
    pool: MutableMapping[str, Any], *, location_ref: str, role: str, formation_ref: str, count: int
) -> int:
    requested = _nonnegative(count)
    if requested <= 0:
        return 0
    force_reserve = pool.setdefault("allocated_to_force_reserve", {})
    if not isinstance(force_reserve, MutableMapping):
        raise ValueError("mount force-reserve allocation is invalid")
    role_row = force_reserve.setdefault(location_ref, {})
    if not isinstance(role_row, MutableMapping):
        raise ValueError("mount force-reserve location row is invalid")
    available = _nonnegative(role_row.get(role, 0))
    moved = min(requested, available)
    if moved <= 0:
        return 0
    role_row[role] = available - moved
    allocated = pool.setdefault("allocated_to_formations", {})
    if not isinstance(allocated, MutableMapping):
        raise ValueError("mount formation allocation registry is invalid")
    row = allocated.setdefault(formation_ref, {})
    if not isinstance(row, MutableMapping):
        raise ValueError("mount formation allocation row is invalid")
    row["horse"] = _nonnegative(row.get("horse", 0)) + moved
    validate_mount_partitions(pool)
    return moved


def return_formation_horses_to_role_reserve(
    pool: MutableMapping[str, Any], *, formation_ref: str, location_ref: str, role_counts: Mapping[str, int]
) -> dict[str, int]:
    """Return an existing formation allocation into reserve role custody.

    Horses are distributed across mounted role demand in deterministic sorted-role
    order, capped by each returned role body count. Any surplus physical horses
    become ordinary regional reserve at the same location.
    """
    allocated = pool.setdefault("allocated_to_formations", {})
    if not isinstance(allocated, MutableMapping):
        raise ValueError("mount formation allocation registry is invalid")
    row = allocated.get(formation_ref, {}) if isinstance(allocated.get(formation_ref, {}), Mapping) else {}
    horses = _nonnegative(row.get("horse", 0))
    allocated.pop(formation_ref, None)
    force_reserve = pool.setdefault("allocated_to_force_reserve", {})
    if not isinstance(force_reserve, MutableMapping):
        raise ValueError("mount force-reserve allocation is invalid")
    role_row = force_reserve.setdefault(location_ref, {})
    if not isinstance(role_row, MutableMapping):
        raise ValueError("mount force-reserve location row is invalid")
    returned: dict[str, int] = {}
    remaining = horses
    for role in sorted(str(r) for r in role_counts):
        if remaining <= 0:
            break
        demand = _nonnegative(role_counts.get(role, 0))
        moved = min(remaining, demand)
        if moved:
            role_row[role] = _nonnegative(role_row.get(role, 0)) + moved
            returned[role] = moved
            remaining -= moved
    if remaining:
        regional = pool.setdefault("regional_reserve", {})
        if not isinstance(regional, MutableMapping):
            raise ValueError("mount regional reserve is invalid")
        local = regional.setdefault(location_ref, {})
        if not isinstance(local, MutableMapping):
            raise ValueError("mount local reserve is invalid")
        local["horse"] = _nonnegative(local.get("horse", 0)) + remaining
    validate_mount_partitions(pool)
    return returned


def allocate_regional_horses_to_formation(
    pool: MutableMapping[str, Any], *, location_ref: str, formation_ref: str, count: int
) -> int:
    requested = _nonnegative(count)
    if requested <= 0:
        return 0
    regional = pool.setdefault("regional_reserve", {})
    if not isinstance(regional, MutableMapping):
        raise ValueError("mount regional reserve is invalid")
    local = regional.setdefault(location_ref, {})
    if not isinstance(local, MutableMapping):
        raise ValueError("mount local reserve is invalid")
    available = _nonnegative(local.get("horse", 0))
    moved = min(requested, available)
    if moved <= 0:
        return 0
    local["horse"] = available - moved
    allocated = pool.setdefault("allocated_to_formations", {})
    if not isinstance(allocated, MutableMapping):
        raise ValueError("mount formation allocation registry is invalid")
    row = allocated.setdefault(formation_ref, {})
    if not isinstance(row, MutableMapping):
        raise ValueError("mount formation allocation row is invalid")
    row["horse"] = _nonnegative(row.get("horse", 0)) + moved
    validate_mount_partitions(pool)
    return moved


def formation_allocated_horses(pool: Mapping[str, Any], formation_ref: str) -> int:
    allocated = pool.get("allocated_to_formations", {}) if isinstance(pool.get("allocated_to_formations"), Mapping) else {}
    row = allocated.get(formation_ref, {}) if isinstance(allocated, Mapping) else {}
    return _nonnegative(row.get("horse", 0)) if isinstance(row, Mapping) else 0


def record_formation_horse_losses(pool: MutableMapping[str, Any], *, formation_ref: str, count: int) -> int:
    requested = _nonnegative(count)
    if requested <= 0:
        return 0
    allocated = pool.setdefault("allocated_to_formations", {})
    if not isinstance(allocated, MutableMapping):
        raise ValueError("mount formation allocation registry is invalid")
    row = allocated.get(formation_ref)
    if not isinstance(row, MutableMapping):
        return 0
    held = _nonnegative(row.get("horse", 0))
    lost = min(requested, held)
    if lost <= 0:
        return 0
    row["horse"] = held - lost
    if not any(_nonnegative(v) for v in row.values() if isinstance(v, (int, float)) and not isinstance(v, bool)):
        allocated.pop(formation_ref, None)
    types = pool.setdefault("types", {})
    health = pool.setdefault("health", {})
    pool["total"] = max(0, _nonnegative(pool.get("total", 0)) - lost)
    types["horse"] = max(0, _nonnegative(types.get("horse", 0)) - lost)
    remaining = lost
    for key in ("fit", "limited", "recovering", "unfit"):
        held_health = _nonnegative(health.get(key, 0))
        take = min(remaining, held_health)
        health[key] = held_health - take
        remaining -= take
        if remaining <= 0:
            break
    if remaining:
        raise ValueError("mount health ledger cannot absorb recorded horse losses")
    validate_mount_partitions(pool)
    return lost


def return_formation_horses_to_regional_reserve(
    pool: MutableMapping[str, Any], *, formation_ref: str, location_ref: str
) -> int:
    allocated = pool.setdefault("allocated_to_formations", {})
    if not isinstance(allocated, MutableMapping):
        raise ValueError("mount formation allocation registry is invalid")
    row = allocated.pop(formation_ref, {})
    horses = _nonnegative(row.get("horse", 0)) if isinstance(row, Mapping) else 0
    if horses:
        regional = pool.setdefault("regional_reserve", {})
        if not isinstance(regional, MutableMapping):
            raise ValueError("mount regional reserve is invalid")
        local = regional.setdefault(location_ref, {})
        if not isinstance(local, MutableMapping):
            raise ValueError("mount local reserve is invalid")
        local["horse"] = _nonnegative(local.get("horse", 0)) + horses
    validate_mount_partitions(pool)
    return horses


def replace_formation_horse_allocations(pool: MutableMapping[str, Any], allocations: Mapping[str, int]) -> None:
    registry = pool.setdefault("allocated_to_formations", {})
    if not isinstance(registry, MutableMapping):
        raise ValueError("mount formation allocation registry is invalid")
    for formation_ref, count in allocations.items():
        n = _nonnegative(count)
        if n:
            registry[str(formation_ref)] = {"horse": n}
        else:
            registry.pop(str(formation_ref), None)
    validate_mount_partitions(pool)


__all__ = [
    "allocate_regional_horses_to_formation", "force_role_horses", "formation_allocated_horses",
    "issue_force_role_horses_to_formation", "mount_partition_horse_total", "record_formation_horse_losses",
    "regional_horses", "release_formation_horses_to_role_reserve", "replace_formation_horse_allocations", "reserve_regional_horses_for_role",
    "return_formation_horses_to_regional_reserve", "return_formation_horses_to_role_reserve",
    "transfer_force_role_horses", "validate_mount_partitions",
]

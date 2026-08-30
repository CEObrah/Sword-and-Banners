"""Shared deterministic time accounting for training and instructor duty.

This module owns no scheduler and creates no hours. It only prevents already-scheduled
training/teaching work for one exact or person-lite individual from exceeding the
lawful waking-time budget inside overlapping campaign-time windows.
"""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from copy import deepcopy
from functools import lru_cache
from typing import Any

from sword_runtime.sim.calendar import CampaignTime


@lru_cache(maxsize=16384)
def _parse_text(value: str) -> CampaignTime:
    # Campaign timestamps are immutable value objects. Training ledgers repeatedly
    # compare the same saved window endpoints across many drills/instructors, so
    # reparsing identical strings becomes quadratic long-horizon overhead.
    return CampaignTime.parse(value)


def _parse(value: str | CampaignTime) -> CampaignTime:
    return value if isinstance(value, CampaignTime) else _parse_text(str(value))


def _window_hours(start: CampaignTime, end: CampaignTime) -> float:
    return max(0.0, start.seconds_until(end) / 3600.0)


def training_window_budget_hours(
    training_rules: Mapping[str, Any],
    *,
    window_start: str | CampaignTime,
    window_end: str | CampaignTime,
) -> float:
    """Return lawful waking hours in one elapsed window.

    Short explicit sessions may use their whole elapsed window. Across full days, the
    data-owned waking cap preserves ordinary sleep/recovery time.
    """
    start = _parse(window_start)
    end = _parse(window_end)
    elapsed = _window_hours(start, end)
    if elapsed <= 0.0:
        return 0.0
    cfg = training_rules.get("time_accounting", {}) if isinstance(training_rules, Mapping) else {}
    waking = max(1.0, min(24.0, float(cfg.get("waking_hours_per_24h", 16.0) or 16.0))) if isinstance(cfg, Mapping) else 16.0
    full_days = int(elapsed // 24.0)
    remainder = elapsed - full_days * 24.0
    return max(0.0, full_days * waking + min(remainder, waking))


def _overlap_hours(
    left_start: CampaignTime,
    left_end: CampaignTime,
    right_start: CampaignTime,
    right_end: CampaignTime,
) -> float:
    start = max(left_start, right_start)
    end = min(left_end, right_end)
    return _window_hours(start, end) if end > start else 0.0


def _training_ledger(person: Mapping[str, Any]) -> Mapping[str, Any] | None:
    dev = person.get("development_state") if isinstance(person, Mapping) else None
    ledger = dev.get("training_time_ledger") if isinstance(dev, Mapping) else None
    return ledger if isinstance(ledger, Mapping) else None


def _ledger_entries(
    person: Mapping[str, Any],
    *,
    query_start: CampaignTime | None = None,
) -> list[Mapping[str, Any]]:
    """Return current reservations that can still constrain training time.

    The ledger is a live overlap index, not a historical audit trail. Completed
    reservations are pruned as chronology advances; transaction receipts own
    command idempotency.
    """
    ledger = _training_ledger(person)
    if not isinstance(ledger, Mapping):
        return []
    active = ledger.get("active_entries")
    if not isinstance(active, list):
        return []
    return [row for row in active if isinstance(row, Mapping)]

def compact_person_training_time_ledger(
    person: Mapping[str, Any],
    *,
    through: str | CampaignTime,
) -> dict[str, Any]:
    """Drop completed training-time reservations at a committed chronology frontier.

    The ledger is a live overlap index, not a diary. It remains intact while
    multiple participants settle the same causal window, but reservations that
    ended at or before the final transaction frontier cannot constrain future
    work and must not remain in committed gameplay state.
    """
    out = deepcopy(dict(person))
    dev = out.get("development_state")
    if not isinstance(dev, MutableMapping):
        return out
    ledger = dev.get("training_time_ledger")
    if not isinstance(ledger, Mapping):
        return out

    frontier = _parse(through)
    raw_active = ledger.get("active_entries")
    source_active = [row for row in raw_active if isinstance(row, Mapping)] if isinstance(raw_active, list) else []
    active_entries: list[dict[str, Any]] = []
    for row in source_active:
        try:
            row_end = _parse(str(row.get("window_end")))
            hours = max(0.0, float(row.get("hours", 0.0) or 0.0))
        except (TypeError, ValueError):
            continue
        if row_end > frontier and hours > 0.0:
            active_entries.append(dict(row))

    if not active_entries:
        dev.pop("training_time_ledger", None)
        return out

    totals: dict[tuple[str, str], float] = {}
    for row in active_entries:
        ws = str(row.get("window_start", ""))
        we = str(row.get("window_end", ""))
        if not ws or not we:
            continue
        hours = max(0.0, float(row.get("hours", 0.0) or 0.0))
        totals[(ws, we)] = totals.get((ws, we), 0.0) + hours

    dev["training_time_ledger"] = {
        "active_entries": active_entries,
        "active_windows": [
            {"window_start": ws, "window_end": we, "hours": round(hours, 6)}
            for (ws, we), hours in sorted(totals.items())
            if hours > 0.0
        ],
        "active_floor": str(frontier),
    }
    return out


def reserved_training_time_hours(
    person: Mapping[str, Any],
    *,
    window_start: str | CampaignTime,
    window_end: str | CampaignTime,
    exclude_reservation_ref: str | None = None,
) -> float:
    """Project existing ledger work into a requested window.

    Long-cycle work is treated as uniformly distributed through its verified window.
    This allows a monthly training plan and a short instructor duty to share time
    without pretending the whole monthly workload happened in the short interval.
    """
    start = _parse(window_start)
    end = _parse(window_end)
    used = 0.0
    ledger = _training_ledger(person)
    grouped: list[Mapping[str, Any]] | None = None
    if exclude_reservation_ref is None and isinstance(ledger, Mapping):
        active_windows = ledger.get("active_windows")
        floor_text = ledger.get("active_floor")
        if isinstance(active_windows, list) and isinstance(floor_text, str):
            try:
                floor = _parse(floor_text)
            except (TypeError, ValueError):
                floor = None
            if floor is not None and start >= floor:
                grouped = [row for row in active_windows if isinstance(row, Mapping)]
    rows = grouped if grouped is not None else _ledger_entries(person, query_start=start)
    for row in rows:
        if exclude_reservation_ref and str(row.get("reservation_ref", "")) == exclude_reservation_ref:
            continue
        try:
            row_start = _parse(str(row.get("window_start")))
            row_end = _parse(str(row.get("window_end")))
            row_hours = max(0.0, float(row.get("hours", 0.0) or 0.0))
        except (TypeError, ValueError):
            continue
        row_elapsed = _window_hours(row_start, row_end)
        if row_elapsed <= 0.0 or row_hours <= 0.0:
            continue
        overlap = _overlap_hours(start, end, row_start, row_end)
        if overlap <= 0.0:
            continue
        used += row_hours * min(1.0, overlap / row_elapsed)
    return max(0.0, used)


def reserve_person_training_time(
    person: MutableMapping[str, Any],
    *,
    requested_hours: float,
    window_start: str | CampaignTime,
    window_end: str | CampaignTime,
    reservation_ref: str,
    kind: str,
    training_rules: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
    whole_hours: bool = False,
) -> dict[str, Any]:
    """Reserve bounded exact/person-lite waking time idempotently."""
    requested = max(0.0, float(requested_hours))
    start = _parse(window_start)
    end = _parse(window_end)
    if end <= start:
        return {"requested_hours": requested, "reserved_hours": 0.0, "availability_factor": 0.0, "budget_hours": 0.0, "used_hours": 0.0}

    dev = person.setdefault("development_state", {})
    if not isinstance(dev, MutableMapping):
        raise ValueError("person development_state must be mutable")
    ledger = dev.setdefault("training_time_ledger", {"active_entries": [], "active_windows": []})
    if not isinstance(ledger, MutableMapping):
        raise ValueError("training_time_ledger must be mutable")

    # Training settlement moves forward in campaign time. Reservations ending
    # at/before the new window start cannot consume future waking time and are
    # deleted rather than retained as replay/audit history.
    raw_active = ledger.get("active_entries")
    raw_floor = ledger.get("active_floor")
    if isinstance(raw_active, list) and isinstance(raw_floor, str):
        try:
            active_floor = _parse(raw_floor)
        except (TypeError, ValueError):
            active_floor = None
    else:
        active_floor = None
    source_active = [row for row in raw_active if isinstance(row, Mapping)] if isinstance(raw_active, list) else []
    active_entries: list[Mapping[str, Any]] = []
    for row in source_active:
        try:
            row_end = _parse(str(row.get("window_end")))
        except (TypeError, ValueError):
            continue
        if row_end > start:
            active_entries.append(row)
    ledger["active_entries"] = [dict(row) for row in active_entries]
    active_totals: dict[tuple[str, str], float] = {}
    for row in active_entries:
        ws = str(row.get("window_start", ""))
        we = str(row.get("window_end", ""))
        if not ws or not we:
            continue
        try:
            hours = max(0.0, float(row.get("hours", 0.0) or 0.0))
        except (TypeError, ValueError):
            continue
        active_totals[(ws, we)] = active_totals.get((ws, we), 0.0) + hours
    ledger["active_windows"] = [
        {"window_start": ws, "window_end": we, "hours": round(hours, 6)}
        for (ws, we), hours in sorted(active_totals.items())
    ]
    ledger["active_floor"] = str(start)

    for row in active_entries:
        if str(row.get("reservation_ref", "")) == reservation_ref:
            reserved = max(0.0, float(row.get("hours", 0.0) or 0.0))
            return {
                "requested_hours": requested,
                "reserved_hours": reserved,
                "availability_factor": 1.0 if requested <= 1e-12 else min(1.0, reserved / requested),
                "budget_hours": training_window_budget_hours(training_rules, window_start=start, window_end=end),
                "used_hours": reserved_training_time_hours(person, window_start=start, window_end=end, exclude_reservation_ref=reservation_ref),
                "idempotent": True,
            }

    budget = training_window_budget_hours(training_rules, window_start=start, window_end=end)
    used = reserved_training_time_hours(person, window_start=start, window_end=end)
    available = max(0.0, budget - used)
    reserved = min(requested, available)
    if whole_hours:
        reserved = float(int(reserved + 1e-9))
    entry: dict[str, Any] = {
        "reservation_ref": reservation_ref,
        "kind": str(kind),
        "window_start": str(start),
        "window_end": str(end),
        "hours": round(reserved, 6),
        "requested_hours": round(requested, 6),
    }
    if isinstance(metadata, Mapping):
        entry.update({str(k): v for k, v in metadata.items() if v is not None})
    active_rows = ledger.setdefault("active_entries", [])
    if not isinstance(active_rows, list):
        raise ValueError("training_time_ledger active_entries must be a list")
    active_rows.append(dict(entry))
    active_windows = ledger.setdefault("active_windows", [])
    if not isinstance(active_windows, list):
        raise ValueError("training_time_ledger active_windows must be a list")
    matched = False
    for window in active_windows:
        if not isinstance(window, MutableMapping):
            continue
        if str(window.get("window_start")) == entry["window_start"] and str(window.get("window_end")) == entry["window_end"]:
            window["hours"] = round(max(0.0, float(window.get("hours", 0.0) or 0.0)) + reserved, 6)
            matched = True
            break
    if not matched:
        active_windows.append({
            "window_start": entry["window_start"],
            "window_end": entry["window_end"],
            "hours": round(reserved, 6),
        })
    ledger["active_entries"] = active_rows
    return {
        "requested_hours": requested,
        "reserved_hours": reserved,
        "availability_factor": 1.0 if requested <= 1e-12 else min(1.0, reserved / requested),
        "budget_hours": budget,
        "used_hours": used,
        "idempotent": False,
    }


__all__ = [
    "compact_person_training_time_ledger",
    "reserve_person_training_time",
    "reserved_training_time_hours",
    "training_window_budget_hours",
]

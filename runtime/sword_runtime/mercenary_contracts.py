"""Compact causal utilities for mercenary contract ownership and scheduling.

Mercenary company files own contract facts and manpower. Scheduler hosts are only
execution routes: cold available accounting-only market rows need no clock, while
any company with a live contractual obligation must remain causally reachable.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.sim.calendar import CampaignTime

LIVE_MERCENARY_CONTRACT_STATUSES = frozenset(
    {"offered", "accepted_unpaid", "active", "renewal_offered", "renewal_accepted"}
)
MERCENARY_COMPANY_SCHEMAS = frozenset({"mercenary", "mercenary-company", "regional-mercenary-company"})
TERMINAL_MERCENARY_CONTRACT_LIMIT = 32
DEFAULT_MERCENARY_REVIEW_SECONDS = 90 * 86400
OFFER_REVIEW_SECONDS = 86400
UNFUNDED_GRACE_SECONDS = 30 * 86400


def mercenary_route_ids(owner_ref: str) -> tuple[str, str]:
    slug = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(owner_ref))
    return f"host_merc_{slug}", f"event_merc_{slug}"


def mercenary_contract_is_live(contract: Mapping[str, Any]) -> bool:
    return str(contract.get("status", "")) in LIVE_MERCENARY_CONTRACT_STATUSES


def mercenary_is_company_owner(owner: Mapping[str, Any]) -> bool:
    return str(owner.get("schema", "")) in MERCENARY_COMPANY_SCHEMAS


def mercenary_has_live_contract(owner: Mapping[str, Any]) -> bool:
    if not mercenary_is_company_owner(owner):
        return False
    contracts = owner.get("contracts", [])
    return isinstance(contracts, list) and any(
        isinstance(row, Mapping) and mercenary_contract_is_live(row) for row in contracts
    )


def compact_mercenary_contracts(
    contracts: list[Any], *, terminal_limit: int = TERMINAL_MERCENARY_CONTRACT_LIMIT
) -> list[Any]:
    """Preserve every live obligation plus only the bounded recent terminal tail."""
    live_indices = {
        i for i, row in enumerate(contracts)
        if isinstance(row, Mapping) and mercenary_contract_is_live(row)
    }
    terminal_indices = [
        i for i, row in enumerate(contracts)
        if i not in live_indices and isinstance(row, Mapping)
    ]
    keep = live_indices | set(terminal_indices[-max(0, int(terminal_limit)):])
    return [row for i, row in enumerate(contracts) if i in keep]


def _parse_time(value: Any) -> CampaignTime | None:
    if not isinstance(value, str):
        return None
    try:
        return CampaignTime.parse(value)
    except (TypeError, ValueError):
        return None


def _future_or_immediate(due: CampaignTime, now: CampaignTime) -> CampaignTime:
    # A missing route may be discovered after its lawful deadline. Put it at the
    # front of the runnable queue without pretending that the deadline moved.
    return due if due > now else now.add_seconds(1)


def mercenary_next_due(
    owner: Mapping[str, Any],
    now_text: str,
    *,
    review_seconds: int = DEFAULT_MERCENARY_REVIEW_SECONDS,
) -> CampaignTime | None:
    """Return the next causal deadline required by current contract facts.

    Accounting-only available companies stay cold. Offers require a prompt
    decision review, accepted-but-unfunded obligations must be checked by the
    thirty-day funding deadline, and active contracts are reviewed at their exact
    expiry. Tactical companies with no live contract keep their ordinary review.
    """
    if not mercenary_is_company_owner(owner) or str(owner.get("status", "")) in {"destroyed", "dissolved"}:
        return None
    now = CampaignTime.parse(now_text)
    due_rows: list[CampaignTime] = []
    contracts = owner.get("contracts", [])
    if isinstance(contracts, list):
        for row in contracts:
            if not isinstance(row, Mapping):
                continue
            status = str(row.get("status", ""))
            if status not in LIVE_MERCENARY_CONTRACT_STATUSES:
                continue
            if status in {"offered", "renewal_offered"}:
                base = _parse_time(row.get("offered_at")) or _parse_time(row.get("renewal_offered_at")) or now
                due_rows.append(_future_or_immediate(base.add_seconds(OFFER_REVIEW_SECONDS), now))
            elif status in {"accepted_unpaid", "renewal_accepted"}:
                base = _parse_time(row.get("accepted_at")) or _parse_time(row.get("renewal_offered_at")) or now
                due_rows.append(_future_or_immediate(base.add_seconds(UNFUNDED_GRACE_SECONDS), now))
            elif status == "active":
                due = _parse_time(row.get("expires_at"))
                if due is None:
                    base = _parse_time(row.get("active_at")) or now
                    due = base.add_days(max(1, int(row.get("term_days", 90))))
                due_rows.append(_future_or_immediate(due, now))
    if due_rows:
        return min(due_rows)
    if isinstance(owner.get("tactical_retirement_pending"), Mapping):
        return now.add_seconds(OFFER_REVIEW_SECONDS)
    if bool(owner.get("accounting_only")):
        return None
    return now.add_seconds(max(1, int(review_seconds)))


def mercenary_requires_causal_host(owner: Mapping[str, Any]) -> bool:
    if not mercenary_is_company_owner(owner) or str(owner.get("status", "")) in {"destroyed", "dissolved"}:
        return False
    return mercenary_has_live_contract(owner) or not bool(owner.get("accounting_only"))


def sync_mercenary_route(
    runtime: dict[str, Any],
    owner_ref: str,
    owner: Mapping[str, Any],
    at: str,
    *,
    recurrence_seconds: int = DEFAULT_MERCENARY_REVIEW_SECONDS,
    priority: int = 75,
) -> bool:
    """Synchronize one compact mercenary causal route with current owner facts.

    Returns whether the runtime registry changed. Existing earlier due work is
    never postponed. Duplicate/noncanonical routes for the same owner are folded
    into the canonical route id.
    """
    hosts = runtime.get("hosts")
    events = runtime.get("events")
    if not isinstance(hosts, dict) or not isinstance(events, list):
        raise ValueError("runtime causal queue is invalid")
    host_id, event_id = mercenary_route_ids(owner_ref)
    due = mercenary_next_due(owner, at, review_seconds=recurrence_seconds)
    matching_host_ids = [
        str(hid) for hid, host in hosts.items()
        if isinstance(host, Mapping)
        and str(host.get("kind", "")) == "mercenary"
        and str(host.get("owner_ref", "")) == str(owner_ref)
    ]
    changed = False

    if due is None:
        dead = set(matching_host_ids)
        if dead:
            for hid in dead:
                hosts.pop(hid, None)
            runtime["events"] = [
                row for row in events
                if not (isinstance(row, Mapping) and str(row.get("target_host", "")) in dead)
            ]
            changed = True
        return changed

    # Preserve an already-earlier lawful review, but never retain a later route
    # than the current contract deadline.
    existing_due: CampaignTime | None = None
    resolved_through = at
    quiet_run_count = 0
    for hid in matching_host_ids:
        host = hosts.get(hid)
        if not isinstance(host, Mapping):
            continue
        prior = _parse_time(host.get("next_due"))
        if prior is not None and prior > CampaignTime.parse(at):
            existing_due = prior if existing_due is None or prior < existing_due else existing_due
        if isinstance(host.get("resolved_through"), str):
            resolved_through = str(host["resolved_through"])
        quiet_run_count = max(quiet_run_count, int(host.get("quiet_run_count", 0) or 0))
    target_due = due if existing_due is None or due < existing_due else existing_due

    dead = set(matching_host_ids) - {host_id}
    if dead:
        for hid in dead:
            hosts.pop(hid, None)
        events[:] = [
            row for row in events
            if not (isinstance(row, Mapping) and str(row.get("target_host", "")) in dead)
        ]
        changed = True

    host = hosts.get(host_id)
    effective_recurrence = (
        OFFER_REVIEW_SECONDS
        if isinstance(owner.get("tactical_retirement_pending"), Mapping)
        else max(1, int(recurrence_seconds))
    )
    desired_host = {
        "kind": "mercenary",
        "owner_ref": owner_ref,
        "quiet_run_count": quiet_run_count,
        "recurrence_seconds": effective_recurrence,
        "resolved_through": resolved_through,
        "next_due": str(target_due),
        "safe_through": str(target_due.add_seconds(-1)),
    }
    if not isinstance(host, dict):
        hosts[host_id] = desired_host
        host = hosts[host_id]
        changed = True
    else:
        for key, value in desired_host.items():
            if host.get(key) != value:
                host[key] = value
                changed = True
        host.pop("retire_after_settlement", None)

    matches = [row for row in events if isinstance(row, dict) and str(row.get("target_host", "")) == host_id]
    if not matches:
        events.append({"event_id": event_id, "priority": int(priority), "target_host": host_id, "due_at": str(target_due)})
        changed = True
    else:
        keep = matches[0]
        if len(matches) > 1:
            match_ids = {id(row) for row in matches[1:]}
            events[:] = [row for row in events if id(row) not in match_ids]
            changed = True
        desired_event = {"event_id": event_id, "priority": int(priority), "target_host": host_id, "due_at": str(target_due)}
        for key, value in desired_event.items():
            if keep.get(key) != value:
                keep[key] = value
                changed = True
        if keep.pop("suspended", None) is not None:
            changed = True
    return changed

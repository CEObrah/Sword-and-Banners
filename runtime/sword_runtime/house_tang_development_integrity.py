"""Conservation and operating-cost hardening for House Tang development.

The underlying HouseTangDevelopmentMixin remains the semantic owner of Sword Manor
training, promotion, recruitment, expansion, and Great Bow Guard applicant work.
This production composition layer keeps aggregate establishment totals, scheduler
chronology, House recurring expense summaries, and player-safe report projection
synchronized after those exact owner mutations.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.causal_event_store import get_causal_event, read_causal_event_owner, write_causal_event_owner
from sword_runtime.cohort_personnel import role_count
from sword_runtime.house_tang_development import (
    HouseTangDevelopmentMixin,
    MONTH_SECONDS,
    _public_owner_label,
)
from sword_runtime.sim.calendar import CampaignTime


class HouseTangDevelopmentIntegrityMixin(HouseTangDevelopmentMixin):
    """Close derived establishment/economy/chronology/report invariants after House development."""

    def _normalize_sword_manor_host(self, runtime: dict[str, Any]) -> None:
        hosts = runtime.get("hosts")
        events = runtime.get("events")
        if not isinstance(hosts, dict) or not isinstance(events, list):
            raise ValueError("runtime causal queue is invalid")
        now = CampaignTime.parse(str(runtime["world_time"]))
        progression = self.read("state/prog/sword-manor-progression.json")
        prog_runtime = progression.get("runtime", {}) if isinstance(progression, Mapping) else {}
        last_settled = prog_runtime.get("last_settled_at") if isinstance(prog_runtime, Mapping) else None
        desired = now.add_seconds(MONTH_SECONDS)
        if isinstance(last_settled, str) and last_settled:
            lawful_next = CampaignTime.parse(last_settled).add_seconds(MONTH_SECONDS)
            desired = now if lawful_next <= now else lawful_next
        for host_id, host in hosts.items():
            if not isinstance(host_id, str) or not isinstance(host, dict):
                continue
            if host.get("owner_ref") != "institution_sword_manor" and host_id != "host_sword_manor":
                continue
            host["kind"] = "sword_manor"
            host["recurrence_seconds"] = MONTH_SECONDS
            current_due = CampaignTime.parse(str(host["next_due"])) if isinstance(host.get("next_due"), str) else desired
            if current_due != desired:
                host["next_due"] = str(desired)
                host["safe_through"] = str(desired.add_seconds(-1))
                for event in events:
                    if isinstance(event, dict) and event.get("target_host") == host_id:
                        event["due_at"] = str(desired)
                        break
            break

    def _sync_sword_manor_derived_state(self) -> None:
        sword = copy.deepcopy(self.read("state/forces/sword-manor.json"))
        authorized = sword.get("authorized_by_role", {})
        if not isinstance(authorized, Mapping):
            raise ValueError("Sword Manor authorized role registry is invalid")
        sword["authorized_strength"] = sum(max(0, int(value)) for value in authorized.values())
        self.put("state/forces/sword-manor.json", sword)

        treasury = copy.deepcopy(self.read("state/treasury/treasury-house-tang.json"))
        rules = self.read("game/data/mechanics/house-tang-development.json")
        cost_rule = rules.get("sword_manor_operating_costs", {}) if isinstance(rules, Mapping) else {}
        if not isinstance(cost_rule, Mapping):
            raise ValueError("Sword Manor operating-cost rule is invalid")
        trainees = role_count(sword, "trainee")
        cash_per_head = max(0, int(cost_rule.get("trainee_monthly_cash_per_head_silver", 40)))
        food_per_head = max(0, int(cost_rule.get("trainee_monthly_food_per_head_kg", 48)))

        components = treasury.setdefault("monthly_flow_components", {})
        cash = components.setdefault("cash", {})
        food = components.setdefault("food", {})
        if not isinstance(cash, dict) or not isinstance(food, dict):
            raise ValueError("House Tang monthly flow components are invalid")
        cash["sword_manor_trainee_program_expense_silver"] = trainees * cash_per_head
        food["trainee_population_requirement_kg"] = trainees * food_per_head

        stable = treasury.setdefault("stable_monthly_flows", {})
        if not isinstance(stable, dict):
            raise ValueError("House Tang stable monthly flow summary is invalid")
        stable["expense_silver"] = sum(max(0, int(value)) for value in cash.values())
        food_in = sum(
            max(0, int(value))
            for key, value in food.items()
            if "production" in str(key) or "delivery" in str(key)
        )
        food_out = sum(
            max(0, int(value))
            for key, value in food.items()
            if "production" not in str(key) and "delivery" not in str(key)
        )
        stable["food_net_change_kg"] = food_in - food_out
        self.put("state/treasury/treasury-house-tang.json", treasury)

    def _enrich_world_arc_report(self, source_event_ref: str) -> None:
        """Add bounded material detail without mutating closed provenance schemas."""
        source = get_causal_event(self, source_event_ref)
        report_ref = f"{source_event_ref}.report"
        report = get_causal_event(self, report_ref)
        if not isinstance(source, Mapping) or not isinstance(report, Mapping):
            return
        current_summary = str(report.get("summary", ""))
        if any(marker in current_summary for marker in (
            " The material evidence is specific enough to establish that ",
            " The material evidence establishes that ",
            " The source carries concrete actor-owned evidence that ",
            " The available evidence establishes that ",
        )):
            return
        result = str(source.get("result", ""))
        actor = _public_owner_label(source.get("actor_ref"))
        target = _public_owner_label(source.get("target_ref")) if source.get("target_ref") else "its reported objective"
        detail = ""
        if result == "material_action_settled":
            src_prov = source.get("provenance") if isinstance(source.get("provenance"), Mapping) else {}
            evidence = src_prov.get("material_evidence") if isinstance(src_prov.get("material_evidence"), Mapping) else {}
            kind = str(evidence.get("kind", ""))
            if kind == "exact_operation_created":
                detail = f" The material evidence is specific enough to establish that {actor} has opened an actual military operation directed at {target} and assigned an existing formation to it. The delivered channels do not establish the formation's size, exact route, supply state, combat contact, or result."
            elif kind in {"exact_operation_transition", "exact_operation_advanced"}:
                detail = f" The material evidence establishes that an existing operation owned by {actor} has advanced to a new settled operational state against {target}. The delivered channels do not establish undisclosed orders, force size, or combat outcome."
            elif kind in {"exact_formation_moved", "exact_formation_state_change"}:
                detail = f" The material evidence establishes that a real formation-level movement or state change by {actor} occurred in connection with {target}. Exact strength and undisclosed destination details remain outside this report."
            else:
                detail = f" The source carries concrete actor-owned evidence that {actor} completed a real domain action connected to {target}, rather than merely recording intent. The delivered channels do not establish additional tactical particulars."
        elif result == "work_blocked":
            detail = f" The available evidence establishes that {actor}'s attempted move toward {target} failed to satisfy a concrete domain requirement; no success is inferred from the attempt."
        if not detail:
            return
        _path, owner = read_causal_event_owner(self)
        mutable = owner.get("causal_events", {}).get(report_ref)
        if not isinstance(mutable, dict):
            return
        mutable["summary"] = (str(mutable.get("summary", "")).rstrip() + detail)[:4000]
        # Deliberately do not add bookkeeping keys to provenance: each provenance
        # variant is a closed schema. Idempotence is derived from the public summary.
        owner.setdefault("runtime", {})["last_settled_at"] = str(report.get("triggered_at", report.get("due_at", "")))
        write_causal_event_owner(self, owner)

    def _settle_expansion_request(self, host: Mapping[str, Any], at: str) -> None:
        super()._settle_expansion_request(host, at)
        self._sync_sword_manor_derived_state()

    def _settle_expansion_completion(self, host: Mapping[str, Any], at: str) -> None:
        super()._settle_expansion_completion(host, at)
        self._sync_sword_manor_derived_state()

    def _autonomy_manor(self, host: Mapping[str, Any], occurrences: int, at: str) -> None:
        super()._autonomy_manor(host, occurrences, at)
        self._sync_sword_manor_derived_state()


__all__ = ["HouseTangDevelopmentIntegrityMixin"]

"""Conservation and operating-cost hardening for House Tang development.

The underlying HouseTangDevelopmentMixin remains the semantic owner of Sword Manor
training, promotion, recruitment, expansion, and Great Bow Guard applicant work.
This production composition layer keeps aggregate establishment totals and House
recurring expense summaries synchronized after those exact owner mutations.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from sword_runtime.cohort_personnel import role_count
from sword_runtime.house_tang_development import HouseTangDevelopmentMixin


class HouseTangDevelopmentIntegrityMixin(HouseTangDevelopmentMixin):
    """Close derived establishment/economy invariants after House development."""

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

"""Great Bow Guard combat-role specialization.

The generic role registry predates Tang Wei's personal Great Bow Guard and would
otherwise fall back to an ordinary household-retainer loadout merely because the
role name contains ``guard``.  Keep the cohort statistics authoritative while
mapping this one exact role to its registered Tang equipment and battlefield
weights.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_PROFILE_PATH = "game/data/mil/great-bow-guard-combat-profile.json"


class GreatBowGuardCombatProfileMixin:
    def _combat_role_profile(self, role: str) -> Mapping[str, Any]:
        if str(role) == "great_bow_guard":
            record = self.read(_PROFILE_PATH)
            profile = record.get("profile") if isinstance(record, Mapping) else None
            if not isinstance(profile, Mapping):
                raise ValueError("Great Bow Guard combat profile is invalid")
            return profile
        return super()._combat_role_profile(role)


__all__ = ["GreatBowGuardCombatProfileMixin"]

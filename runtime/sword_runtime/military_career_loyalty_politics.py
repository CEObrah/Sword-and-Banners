"""Political consequence overlay for military career networks.

Personal military followings are political facts even when administrative
ownership remains with a state. This layer persists bounded state pressure and
causal events when officer interest concentrates around any commander.
"""
from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.military_career_loyalty import _PLAYER_REF
from sword_runtime.military_career_loyalty_integrity import MilitaryCareerLoyaltyIntegrityMixin
from sword_runtime.player_story_flow import _event_owner_write, _player_delivery


class MilitaryCareerLoyaltyPoliticsMixin(MilitaryCareerLoyaltyIntegrityMixin):
    """Turn excessive personal military attraction into institutional pressure."""

    def _career_concentration_event(
        self,
        *,
        state_ref: str,
        commander_ref: str,
        concentration_milli: int,
        at: str,
    ) -> None:
        rules = self._military_rules()["institutional_response"]
        soft = int(rules["political_concentration_soft_milli"])
        hard = int(rules["political_concentration_hard_milli"])
        if concentration_milli < soft:
            return
        network = self._career_network()
        state_pressure = network.setdefault("state_pressure", {}).setdefault(state_ref, {})
        previous = state_pressure.get(commander_ref)
        prior_level = str(previous.get("level", "none")) if isinstance(previous, Mapping) else "none"
        level = "hard" if concentration_milli >= hard else "soft"
        state_pressure[commander_ref] = {
            "level": level,
            "concentration_milli": int(concentration_milli),
            "last_observed_at": at,
            "basis": "saved military career petitions and propagated commander reputation",
        }
        self.put("state/military/career-network/index.json", network)
        if prior_level == level:
            return

        digest = hashlib.sha256(f"{state_ref}|{commander_ref}|{level}".encode("utf-8")).hexdigest()[:18]
        event_ref = f"event_military_following_pressure_{digest}"
        state_name = state_ref.removeprefix("state_")
        summary = (
            f"{state_ref}'s military administration has registered a {level} concentration of officer interest around "
            f"{commander_ref}. This is a political-personnel pressure signal, not a transfer of troop ownership, state allegiance, "
            "or command authority. Future personnel approvals may be restricted, redirected, or balanced by independent commands."
        )
        payload: dict[str, Any] = {
            "event_ref": event_ref,
            "kind": "military_following_political_pressure",
            "status": "triggered",
            "due_at": at,
            "triggered_at": at,
            "actor_ref": f"inst_{state_name}_military_bureau",
            "target_ref": commander_ref,
            "basis_goal": "prevent unhealthy concentration of personal military patronage",
            "process_kind": "military_personnel_politics",
            "process_stage": level,
            "summary": summary,
        }
        if commander_ref == _PLAYER_REF:
            payload["delivery"] = _player_delivery(self, "military bureau memorandum")
        _event_owner_write(
            self,
            event_ref,
            payload,
            at,
            source_owner_ref=f"inst_{state_name}_military_bureau",
        )

    def _settle_petitions(self, state_ref: str, at: str) -> None:
        super()._settle_petitions(state_ref, at)
        index = self._petition_index()
        commander_refs: set[str] = set()
        for petition_ref in index.get("pending_by_state", {}).get(state_ref, []):
            petition = self.read_optional(self._petition_path(str(petition_ref)))
            if not isinstance(petition, Mapping):
                continue
            desired = petition.get("desired_commander_ref")
            if isinstance(desired, str) and desired:
                commander_refs.add(desired)
        network = self._career_network()
        for commander_ref in network.get("public_commander_refs", []):
            if not isinstance(commander_ref, str):
                continue
            path = network.get("commanders", {}).get(commander_ref)
            dossier = self.read_optional(path) if isinstance(path, str) else None
            if isinstance(dossier, Mapping) and dossier.get("state_ref") == state_ref:
                commander_refs.add(commander_ref)
        for commander_ref in sorted(commander_refs):
            concentration = self._political_concentration(state_ref, commander_ref)
            self._career_concentration_event(
                state_ref=state_ref,
                commander_ref=commander_ref,
                concentration_milli=concentration,
                at=at,
            )


__all__ = ["MilitaryCareerLoyaltyPoliticsMixin"]

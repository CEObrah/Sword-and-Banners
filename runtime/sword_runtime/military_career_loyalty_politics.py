"""Political consequence overlay for military career networks.

Personal military followings are political facts even when administrative
ownership remains with a state. This layer persists bounded state pressure and
causal events when officer interest concentrates around any commander.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from sword_runtime.military_career_loyalty import _PLAYER_REF, _clamp
from sword_runtime.military_career_loyalty_integrity import MilitaryCareerLoyaltyIntegrityMixin
from sword_runtime.player_story_flow import _event_owner_write, _player_delivery


class MilitaryCareerLoyaltyPoliticsMixin(MilitaryCareerLoyaltyIntegrityMixin):
    """Turn excessive personal military attraction into institutional pressure."""

    def _create_petition(
        self,
        person: dict[str, Any],
        *,
        state_ref: str,
        desired_commander_ref: str | None,
        request_kind: str,
        attraction_milli: int,
        evidence_refs: list[str],
        at: str,
    ) -> str | None:
        petition_ref = super()._create_petition(
            person,
            state_ref=state_ref,
            desired_commander_ref=desired_commander_ref,
            request_kind=request_kind,
            attraction_milli=attraction_milli,
            evidence_refs=evidence_refs,
            at=at,
        )
        if petition_ref is None or not desired_commander_ref:
            return petition_ref
        network = self._career_network()
        interest = network.setdefault("career_interest", {}).setdefault(state_ref, {}).setdefault(desired_commander_ref, {})
        interest["petition_count"] = int(interest.get("petition_count", 0)) + 1
        interest["weighted_interest_milli"] = min(
            50000,
            int(interest.get("weighted_interest_milli", 0)) + max(100, int(attraction_milli) // 2),
        )
        interest["last_petition_at"] = at
        recent = interest.setdefault("recent_petition_refs", [])
        if petition_ref not in recent:
            recent.append(petition_ref)
        interest["recent_petition_refs"] = recent[-32:]
        self.put("state/military/career-network/index.json", network)
        return petition_ref

    def _political_concentration(self, state_ref: str, commander_ref: str | None) -> int:
        base = super()._political_concentration(state_ref, commander_ref)
        if not commander_ref:
            return base
        network = self._career_network()
        interest = network.get("career_interest", {}).get(state_ref, {}).get(commander_ref, {})
        if not isinstance(interest, Mapping):
            return base
        cumulative = min(700, int(interest.get("weighted_interest_milli", 0)) // 4)
        repeat = min(180, int(interest.get("petition_count", 0)) * 18)
        return _clamp(base + cumulative + repeat)

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
        network = self._career_network()
        commander_refs: set[str] = set()
        for commander_ref in network.get("career_interest", {}).get(state_ref, {}):
            if isinstance(commander_ref, str):
                commander_refs.add(commander_ref)
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

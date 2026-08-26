"""Career promotion bridge from formation command to a recursive nested army.

The ordinary military-career system can award an independent-command handoff.
When the authorized officer already commands a direct Unit of a higher army,
the promotion may elevate that existing commander into a new zero-body nested army
instead of hunting for an unrelated vacant formation. The original formation becomes
Unit 1 and receives one lawful successor commander drawn from its already-conserved
internal officer cadre. No generic second-command body is created.
"""
from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", ".", value.lower()).strip(".")[:48] or "general"


class MilitaryNestedCareerMixin:
    def _career_nested_army_promotion(self, petition_ref: str, at: str) -> bool:
        path = self._petition_path(petition_ref)
        raw = self.read_optional(path)
        if not isinstance(raw, Mapping) or str(raw.get("status", "")) != "authorized_handoff":
            return False
        if str(raw.get("request_kind", "")) != "independent_command":
            return False
        petition = copy.deepcopy(dict(raw))
        officer_ref = str(petition.get("officer_ref", ""))
        if not officer_ref:
            return False
        person_path, person = self._exact_person(officer_ref, active=False)
        current_ref, formation = self._person_current_formation(person)
        if not current_ref or not isinstance(formation, Mapping):
            return False
        if str(formation.get("commander_ref", "")) != officer_ref:
            return False
        parent_ref = formation.get("higher_command_ref")
        if not isinstance(parent_ref, str) or not parent_ref.startswith("cmdgrp."):
            return False
        parent_path = f"state/cmd/command-groups/{parent_ref}.json"
        parent0 = self.read_optional(parent_path)
        if not isinstance(parent0, Mapping):
            return False
        parent = copy.deepcopy(dict(parent0))
        units = parent.get("units", []) if isinstance(parent.get("units"), list) else []
        if not any(isinstance(row, Mapping) and row.get("kind") == "formation" and str(row.get("ref")) == current_ref for row in units):
            return False
        state_ref = str(petition.get("state_ref", ""))
        digest = hashlib.sha256(f"{petition_ref}|{officer_ref}|{current_ref}".encode()).hexdigest()[:10]
        army_ref = f"cmdgrp.{_slug(state_ref.removeprefix('state_'))}.{_slug(officer_ref.removeprefix('char_'))}.army.{digest}"
        if self.read_optional(f"state/cmd/command-groups/{army_ref}.json") is not None:
            return False
        display_name = str(person.get("name") or officer_ref) + " Army"
        command = SimpleNamespace(actor_id=officer_ref, digest=digest, semantic_digest=digest, command_type="career_nested_army_promotion")
        result = self._promote_formation_to_nested_army(
            command,
            {"formation_ref": current_ref, "subordinate_group_ref": army_ref, "display_name": display_name},
            parent_doc=parent,
            parent_path=parent_path,
            now=at,
            write_command_meta=False,
        )
        petition = copy.deepcopy(dict(self.read(path)))
        petition["status"] = "completed"
        petition["execution_status"] = "promoted_existing_formation_to_nested_army"
        petition["completed_at"] = at
        petition["nested_army_ref"] = army_ref
        petition["promotion_result"] = {
            "original_formation_ref": current_ref,
            "resulting_formation_personnel": int(result.get("resulting_formation_personnel", 0)),
            "new_formation_commander_ref": result.get("new_formation_commander_ref"),
            "rule": "authorized commander rises to the nested army; one conserved internal officer succeeds to the original Unit command",
        }
        self.put(path, petition)
        person = copy.deepcopy(self.read(person_path))
        rank = person.setdefault("military_rank", {})
        if not isinstance(rank, dict):
            rank = {}; person["military_rank"] = rank
        rank["title"] = "General"
        rank["durable"] = True
        rank["promoted_at"] = at
        rank["basis"] = "authorized independent nested-army command"
        person.setdefault("career_state", {})["current_billet"] = "nested_army_commander"
        person["career_state"].setdefault("appointments", []).append({
            "kind": "nested_army_command", "command_group_ref": army_ref,
            "original_formation_ref": current_ref, "appointed_at": at,
            "source_petition_ref": petition_ref, "status": "active",
        })
        person["career_state"]["appointments"] = person["career_state"]["appointments"][-32:]
        self.put(person_path, person)
        return True

    def _execute_authorized_petition(self, petition_ref: str, at: str) -> None:
        if self._career_nested_army_promotion(petition_ref, at):
            return
        super()._execute_authorized_petition(petition_ref, at)

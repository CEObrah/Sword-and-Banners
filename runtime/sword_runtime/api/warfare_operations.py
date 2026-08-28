"""Current player-facing warfare operations."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sword_runtime.api.input_guidance import INPUT_GUIDANCE_POLICY
from sword_runtime.api.equipment_operations import EquipmentAwareCampaignOperations
from sword_runtime.command_contracts import COMMAND_PAYLOAD_KEYS
from sword_runtime.scene_sessions import active_scene_session

_MILITARY_ALLEGIANCE_COMMAND = "military_allegiance_action"
_COMMAND_PERSONNEL_INDEX_PATH = "state/cmd/command-personnel.json"
_BEHAVIOR_PROFILE_INDEX_PATH = "game/data/people/behavior-profile-index.json"
_SAFE_PERFORMANCE_CUE_FIELDS = (
    "core_traits", "temperament", "speech_pattern", "humor_style",
    "conflict_style", "individual_tell",
)
_COMMAND_SERVICE_FIELDS = (
    "name", "life_status", "sex", "pronouns", "family_role", "role", "rank", "military_rank", "authority", "affiliation",
    "command_assignment", "military_command", "current_formation_id", "current_location", "location", "location_ref",
    "health_status", "health", "fatigue", "attributes", "aptitude", "skills",
    "specializations", "personal_loadout_ref", "equipment_loadout_id", "equipment_standard",
)
_SERVICE_INTERACTION_LENSES = {
    "Strategy": "objectives, sequencing, uncertainty, reserves, and second-order consequences",
    "Tactics": "timing, local advantage, contact conditions, positioning, and execution risk",
    "Logistics": "supply, transport, sustainment, route burden, and practical capacity",
    "Formation Command": "command clarity, coordination, readiness, control, and subordinate execution",
    "Leadership": "discipline, morale, responsibility, cohesion, and command communication",
    "Scouting": "source quality, observation gaps, reconnaissance, routes, and what remains unverified",
    "Engineering": "works, crossings, fortifications, labor, material constraints, and time",
    "Medicine": "injury, recovery, treatment capacity, and human cost",
}
_ROLE_INTERACTION_LENSES = (
    (("legal", "law"), "law, wording, procedure, authority, evidence, and precedent"),
    (("chancellor",), "institutional coordination, state capacity, resources, and political consequence"),
    (("sovereign", "king", "queen", "ruler"), "state purpose, lawful authority, competing obligations, and consequence"),
    (("strategist",), "assumptions, alternatives, sequencing, uncertainty, and downstream risk"),
    (("commander", "general"), "command clarity, military feasibility, responsibility, readiness, and execution"),
    (("treasurer", "steward"), "cost, capacity, accounting, provisioning, and sustainability"),
    (("merchant", "trader"), "price, delivery, reliability, scarcity, transport, and risk"),
    (("physician", "doctor", "healer"), "health, treatment, recovery, capacity, and risk"),
    (("court", "minister"), "procedure, institutional consequence, witnesses, authority, and coordination"),
)
_MILITARY_ALLEGIANCE_GUIDANCE = {
    "action": {"allowed_values": ["rebel", "defect", "mutiny", "defy_state_order", "desert"]},
    "formation_refs": {
        "type": "array", "minimum_items": 1, "maximum_items": 64,
        "rule": "use distinct exact formations currently under the acting commander's authority; this is a resolution payload bound, never a world-size cap",
    },
    "proposed_commander_ref": {"rule": "optional exact proposed commander; gameplay defaults to the player and cannot nominate another person's voluntary rebellion, defection, or desertion"},
    "claimant_ref": {"rule": "optional exact political claimant or legal authority relevant to legitimacy; it does not itself grant recognition"},
    "basis_ref": {"rule": "optional exact saved information/evidence claim already available to the actor"},
    "outcome_rule": "contested execute-only resolution; formations and named officers resolve independently through saved state allegiance, professional duty, formation identity, commander bonds, legitimacy, disaffection, command hierarchy, and deterministic crisis pressure",
    "ownership_rule": "personal following, desertion, defection, or mutiny never silently transfers administrative ownership, equipment title, or state sovereignty",
}


def _safe_service_performance_cues(projected: Mapping[str, Any]) -> dict[str, Any]:
    """Derive interaction lenses only from fields already exposed on the person sheet.

    These cues help the GM choose what a person is professionally equipped to
    notice, question, or emphasize. They are not personality, motive, knowledge,
    authority, or permission to create facts.
    """
    cues: dict[str, Any] = {}
    role = projected.get("role") or projected.get("rank") or projected.get("family_role")
    military_rank = projected.get("military_rank")
    if not role and isinstance(military_rank, Mapping):
        role = military_rank.get("grade")
    if isinstance(role, str) and role.strip():
        public_role = role.strip()[:200]
        cues["public_role_context"] = public_role
        lowered = public_role.lower()
        for tokens, emphasis in _ROLE_INTERACTION_LENSES:
            if any(token in lowered for token in tokens):
                cues["role_lens"] = emphasis
                break

    family_role = projected.get("family_role")
    if isinstance(family_role, str) and family_role.strip():
        cues["family_role_context"] = family_role.strip()[:120]

    skills = projected.get("skills") if isinstance(projected.get("skills"), Mapping) else {}
    lenses: list[tuple[float, str, str]] = []
    for domain, emphasis in _SERVICE_INTERACTION_LENSES.items():
        value = skills.get(domain) if isinstance(skills, Mapping) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            lenses.append((float(value), domain, emphasis))
    lenses.sort(key=lambda row: (-row[0], row[1]))
    if lenses:
        cues["professional_lenses"] = [
            {
                "domain": domain,
                "emphasis": emphasis,
                "basis": "player_visible_service_capability",
            }
            for _value, domain, emphasis in lenses[:3]
        ]
    if cues:
        cues["use_rule"] = (
            "Use these cues only to vary delivery and select lawful questions, objections, clarifications, or advice from established player-safe facts. "
            "They do not establish personality, motive, knowledge, authority, or outcomes."
        )
    return cues


class WarfareCampaignOperations(EquipmentAwareCampaignOperations):
    """Stable warfare surface with bounded exact command-person reads."""

    def _safe_scene_performance_cues(self, person_id: str, projected: Mapping[str, Any]) -> dict[str, Any]:
        """Return safe presentation cues plus role/service fallbacks, never private goals."""
        cues = _safe_service_performance_cues(projected)
        try:
            index = self.store.read_json(_BEHAVIOR_PROFILE_INDEX_PATH)
        except (FileNotFoundError, KeyError, TypeError, ValueError):
            return cues
        profiles = index.get("profiles", {}) if isinstance(index, Mapping) else {}
        path = profiles.get(person_id) if isinstance(profiles, Mapping) else None
        if not isinstance(path, str) or not path.startswith("game/data/people/behavior-profiles/"):
            return cues
        try:
            profile = self.store.read_json(path)
        except (FileNotFoundError, KeyError, TypeError, ValueError):
            return cues
        if not isinstance(profile, Mapping) or profile.get("schema") != "behavior-profile" or profile.get("person_id") != person_id:
            return cues
        behavior = profile.get("behavior", {}) if isinstance(profile.get("behavior"), Mapping) else {}
        for key in _SAFE_PERFORMANCE_CUE_FIELDS:
            value = behavior.get(key)
            if isinstance(value, str) and value.strip():
                cues[key] = value.strip()[:300]
            elif isinstance(value, (list, tuple)):
                rows = [str(item).strip()[:160] for item in value if isinstance(item, str) and item.strip()]
                if rows:
                    cues[key] = rows[:8]
        return cues

    def _with_scene_response_envelope(self, result: dict[str, Any], person_id: str, context: Mapping[str, Any]) -> dict[str, Any]:
        session = active_scene_session(self.store)
        if not isinstance(session, Mapping):
            return result
        participants = {str(x) for x in session.get("participant_refs", []) if isinstance(x, str)}
        player_id = str(context.get("campaign", {}).get("player_id") or "")
        player_location = context.get("player", {}).get("location")
        if person_id not in participants or player_id not in participants or not player_location:
            return result
        owner_index = self.store.read_json("state/index/owner-index.json")
        owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
        path = owners.get(person_id) if isinstance(owners, Mapping) else None
        if not isinstance(path, str):
            return result
        try:
            person = self.store.read_json(path)
        except FileNotFoundError:
            return result
        location = person.get("current_location") or person.get("location_ref") or person.get("location") if isinstance(person, Mapping) else None
        if location != player_location or session.get("location_ref") != player_location:
            return result
        projected = result.get("person") if isinstance(result.get("person"), Mapping) else {}
        out = dict(result)
        performance_cues = self._safe_scene_performance_cues(person_id, projected)
        scene_focus = {
            "kind": session.get("kind"),
            "purpose": session.get("purpose"),
            "agenda": [str(x) for x in session.get("agenda", []) if isinstance(x, str)][:12],
        }
        out["npc_response_envelope"] = {
            "speaker_ref": person_id,
            "role": projected.get("role") or projected.get("rank") or projected.get("military_rank") or projected.get("family_role"),
            "scene_focus": scene_focus,
            "performance_cues": performance_cues,
            "performance_cues_rule": "player-safe delivery and conversational emphasis only; never factual knowledge, private motive, authority, or outcome",
            "may": [
                "acknowledge", "clarify_player_safe_facts", "offer_nonbinding_advice", "object",
                "ask_followup", "speculate_from_known_evidence", "express_nonbinding_professional_opinion",
            ],
            "must_preserve_uncertainty": True,
            "factual_basis": "player_safe_runtime_context_only",
            "cannot_establish": [
                "new_secret_fact", "formal_authority", "resource_transfer", "movement",
                "relationship_change", "contract_or_oath", "mechanical_acceptance_or_refusal",
            ],
            "private_motives_excluded": True,
            "mechanical_consequence_authority": False,
        }
        return out

    def person_sheet(self, person_id: str) -> dict[str, Any]:
        context = super().play_context()
        permitted = set(context.get("permitted_person_ids", []))

        # A controlled formation may fall outside the hot formation window while
        # still being exactly inspectable through paging or a returned command
        # hierarchy. Its actual top commander remains a lawful follow-up read.
        # Authorize only that exact commander relation, not every person-lite
        # officer in the formation, so bounded context stays small.
        player_id = str(context.get("campaign", {}).get("player_id") or "")
        controlled_top_commanders: set[str] = set()
        if player_id and hasattr(self, "_all_controlled_formations"):
            for formation in self._all_controlled_formations(player_id):
                if not isinstance(formation, Mapping):
                    continue
                commander_ref = formation.get("commander_ref")
                if isinstance(commander_ref, str) and commander_ref:
                    controlled_top_commanders.add(commander_ref)

        if person_id in permitted or person_id in controlled_top_commanders:
            index = self.store.read_json(_COMMAND_PERSONNEL_INDEX_PATH)
            records = index.get("record_index", {}) if isinstance(index, Mapping) else {}
            path = records.get(person_id) if isinstance(records, Mapping) else None
            if isinstance(path, str):
                person = self.store.read_json(path)
                if isinstance(person, Mapping):
                    schema = str(person.get("schema", ""))
                    if schema in {"sab_character", "person-lite"}:
                        representation = "full_character" if schema == "sab_character" else "person_lite"
                        projected = {"person_id": person_id, "representation": representation}
                        projected.update({key: person.get(key) for key in _COMMAND_SERVICE_FIELDS if key in person})
                        if schema == "person-lite":
                            assignment = person.get("command_assignment") if isinstance(person.get("command_assignment"), Mapping) else {}
                            military_rank = person.get("military_rank") if isinstance(person.get("military_rank"), Mapping) else {}
                            stats = person.get("stats") if isinstance(person.get("stats"), Mapping) else {}
                            if assignment.get("formation_ref") and not projected.get("current_formation_id"):
                                projected["current_formation_id"] = assignment["formation_ref"]
                            if military_rank.get("grade") and not projected.get("rank"):
                                projected["rank"] = military_rank["grade"]
                            if isinstance(stats.get("attributes"), Mapping):
                                projected["attributes"] = dict(stats["attributes"])
                            if isinstance(stats.get("skills"), Mapping):
                                projected["skills"] = dict(stats["skills"])
                        projected.setdefault("life_status", "active")
                        return self._with_scene_response_envelope({
                            "visibility": "player_visible_command_service_sheet",
                            "person": projected,
                            "scope": "Command-relevant service capability only. Private motives, relationships, hidden knowledge, and unrelated personal state remain excluded.",
                        }, person_id, context)
        return self._with_scene_response_envelope(super().person_sheet(person_id), person_id, context)

    def play_context(self) -> dict[str, Any]:
        context = super().play_context()
        commands = context.setdefault("commands", {})
        command_types = dict(commands.get("command_types", {}))
        command_types[_MILITARY_ALLEGIANCE_COMMAND] = {
            "accepted_payload_keys": sorted(COMMAND_PAYLOAD_KEYS[_MILITARY_ALLEGIANCE_COMMAND]),
            "input_guidance": dict(_MILITARY_ALLEGIANCE_GUIDANCE),
            "contested_preview_policy": "outcome_hidden_until_execute",
        }
        commands["command_types"] = command_types
        commands["supported_command_types"] = sorted(command_types)
        wake = context.get("pending_wake")
        return context

    def get_command_contract(self, command_type: str) -> dict[str, Any]:
        if command_type != _MILITARY_ALLEGIANCE_COMMAND:
            return super().get_command_contract(command_type)
        runtime = self.runtime.store.read_json("state/runtime.json")
        wake = runtime.get("pending_wake") if isinstance(runtime, Mapping) else None
        available = not isinstance(wake, Mapping)
        scope = "normal" if available else "pending_wake_response"
        return {
            "command_type": command_type,
            "accepted_payload_keys": sorted(COMMAND_PAYLOAD_KEYS[command_type]),
            "input_guidance": dict(_MILITARY_ALLEGIANCE_GUIDANCE),
            "contested_preview_policy": "outcome_hidden_until_execute",
            "availability": {"available": available, "scope": scope},
            "input_guidance_policy": INPUT_GUIDANCE_POLICY,
        }


__all__ = ["WarfareCampaignOperations"]

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
_GM_PRIVATE_SCENE_PERSON_LIMIT = 16
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




def _bounded_private_cognition_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 3:
        return None
    if isinstance(value, str):
        return value[:600]
    if isinstance(value, (int, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        rows = []
        for item in value[:16]:
            bounded = _bounded_private_cognition_value(item, depth=depth + 1)
            if bounded is not None:
                rows.append(bounded)
        return rows
    if isinstance(value, Mapping):
        out = {}
        for key in sorted(str(k) for k in value.keys())[:24]:
            bounded = _bounded_private_cognition_value(value.get(key), depth=depth + 1)
            if bounded is not None:
                out[key] = bounded
        return out
    return None


def _gm_private_goal_cognition(person: Mapping[str, Any]) -> dict[str, Any]:
    """Return bounded private current-character truth for scene direction.

    The GM may be more informed than Tang Wei. This prevents secrecy rules from
    starving NPC cognition while keeping disclosure separate from direction.
    """
    out: dict[str, Any] = {}
    goal_state = person.get("goal_state") if isinstance(person.get("goal_state"), Mapping) else {}
    for key in ("current_goals", "institutional_duties", "long_term_goals", "personal_desires"):
        values = goal_state.get(key) if isinstance(goal_state, Mapping) else None
        if isinstance(values, (list, tuple)):
            rows = [str(value).strip()[:300] for value in values if isinstance(value, str) and value.strip()]
            if rows:
                out[key] = rows[:8]
    for key in (
        "private_knowledge", "hidden_goals", "secret_notes", "autonomy_private",
        "memory_state", "belief_state", "internal_state", "temperament",
    ):
        if key not in person:
            continue
        bounded = _bounded_private_cognition_value(person.get(key))
        if bounded not in (None, [], {}):
            out[key] = bounded
    if out:
        out["privacy"] = "gm_private_cognition_not_player_knowledge"
        out["use_rule"] = (
            "Use this private current-character truth to decide coherent NPC choices, lies, omissions, priorities and performance. "
            "Never narrate hidden entries as Wei's knowledge or reveal them in narration/options unless they become perceptible or the NPC lawfully discloses them. "
            "Hard consequences still require their mechanical/domain authority."
        )
    return out


def _gm_private_character_truth(person: Mapping[str, Any]) -> dict[str, Any]:
    """Return compact exact character truth for scene-bounded GM omniscience."""
    out: dict[str, Any] = {}
    for key in (
        "name", "life_status", "health_status", "health", "fatigue", "state",
        "house_ref", "allegiance", "legal_status", "role", "role_archetype",
        "rank", "military_rank", "authority", "career_state", "command_assignment",
        "military_command", "current_location", "location", "attributes", "aptitude",
        "skills", "professional_skills", "specializations", "goal_state",
        "current_equipment_state", "equipment_loadout_id", "personal_loadout_ref",
    ):
        value = person.get(key)
        if value not in (None, "", [], {}):
            out[key] = value
    if not out:
        return {}
    out["privacy"] = "gm_private_scene_bounded_omniscient_truth_not_player_knowledge"
    out["use_rule"] = (
        "Use exact private character truth to keep competence, priorities, choices, lies, omissions and emotional performance coherent. "
        "Do not state hidden motives, numeric capability, private goals, unobserved condition or other concealed facts as Wei's knowledge unless they become perceptible, disclosed or lawfully inferred."
    )
    return out

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

    def _gm_private_behavior_profile(self, person_id: str) -> dict[str, Any]:
        """Load full static behavior guidance for GM-only characterization."""
        try:
            index = self.store.read_json(_BEHAVIOR_PROFILE_INDEX_PATH)
        except (FileNotFoundError, KeyError, TypeError, ValueError):
            return {}
        profiles = index.get("profiles", {}) if isinstance(index, Mapping) else {}
        path = profiles.get(person_id) if isinstance(profiles, Mapping) else None
        if not isinstance(path, str) or not path.startswith("game/data/people/behavior-profiles/"):
            return {}
        try:
            profile = self.store.read_json(path)
        except (FileNotFoundError, KeyError, TypeError, ValueError):
            return {}
        if not isinstance(profile, Mapping) or profile.get("schema") != "behavior-profile" or profile.get("person_id") != person_id:
            return {}
        behavior = profile.get("behavior") if isinstance(profile.get("behavior"), Mapping) else {}
        if not behavior:
            return {}
        return {
            "behavior": dict(behavior),
            "privacy": "gm_private_scene_bounded_omniscient_truth_not_player_knowledge",
            "mechanical_authority": False,
            "use_rule": "Use as stable character-direction guidance. Mutable knowledge, relationships, authority, health and outcomes still come from current runtime state.",
        }

    def _with_scene_response_envelope(self, result: dict[str, Any], person_id: str, context: Mapping[str, Any]) -> dict[str, Any]:
        session = active_scene_session(self.store)
        player_id = str(context.get("campaign", {}).get("player_id") or "")
        player_location = context.get("player", {}).get("location")
        scene = context.get("scene", {}) if isinstance(context.get("scene"), Mapping) else {}
        cast = scene.get("scene_cast", {}) if isinstance(scene.get("scene_cast"), Mapping) else {}
        present_refs = {
            str(row.get("person_id")) for row in cast.get("present_people", [])
            if isinstance(row, Mapping) and isinstance(row.get("person_id"), str)
        } if isinstance(cast.get("present_people"), list) else set()
        session_visible = False
        if isinstance(session, Mapping):
            participants = {str(x) for x in session.get("participant_refs", []) if isinstance(x, str)}
            session_visible = person_id in participants and player_id in participants
        if not player_location or (person_id not in present_refs and not session_visible):
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
        if location != player_location:
            return result
        if session_visible and isinstance(session, Mapping) and session.get("location_ref") != player_location:
            return result
        projected = result.get("person") if isinstance(result.get("person"), Mapping) else {}
        out = dict(result)
        performance_cues = self._safe_scene_performance_cues(person_id, projected)
        scene_focus = {
            "kind": session.get("kind") if session_visible and isinstance(session, Mapping) else "established_scene",
            "purpose": session.get("purpose") if session_visible and isinstance(session, Mapping) else scene.get("summary"),
            "agenda": [str(x) for x in session.get("agenda", []) if isinstance(x, str)][:12] if session_visible and isinstance(session, Mapping) else [],
        }
        private_cognition = _gm_private_goal_cognition(person)
        private_character_truth = _gm_private_character_truth(person)
        private_behavior = self._gm_private_behavior_profile(person_id)
        out["npc_response_envelope"] = {
            "speaker_ref": person_id,
            "role": projected.get("role") or projected.get("rank") or projected.get("military_rank") or projected.get("family_role"),
            "scene_focus": scene_focus,
            "performance_cues": performance_cues,
            "performance_cues_rule": "Player-safe cues shape what may be presented directly; separately marked GM-private truth may guide internal characterization and decision generation without becoming Wei's knowledge.",
            "may_is_non_exhaustive": True,
            "reversible_dialogue_is_open_ended": True,
            "ordinary_dialogue_requires_command": False,
            "dialogue_authoring_rule": "The runtime supplies facts, constraints, roles, and optional private decision context; the AI GM authors the actual human line. Never recite runtime fields as a script.",
            "subjective_characterization_latitude": True,
            "subjective_characterization_rule": "The AI may choose momentary nonbinding emotion, tone, hesitation, humor, warmth, irritation, conversational tactics, and ordinary opinion consistent with established role/relationship/history. Do not invent a secret factual motive, durable relationship change, or hard outcome.",
            "may": [
                "acknowledge", "answer_from_player_safe_facts", "clarify_player_safe_facts",
                "respond_to_request_without_binding_consequence", "offer_nonbinding_advice",
                "object", "disagree", "correct", "ask_followup", "coordinate",
                "interrupt_when_socially_plausible", "speak_to_other_present_people",
                "hesitate_or_remain_silent", "joke_or_tease_if_supported",
                "speculate_from_known_evidence", "express_nonbinding_professional_opinion",
                "disclose_existing_private_fact_when_the_speaker_lawfully_knows_and_chooses_to_reveal_it",
                "lie_or_withhold_when_supported_by_private_cognition",
            ],
            "must_preserve_uncertainty": True,
            "factual_basis": "player_safe_runtime_context_plus_explicit_gm_private_cognition_for_decision_generation",
            "cannot_establish": [
                "invented_secret_fact", "formal_authority", "resource_transfer", "movement",
                "relationship_change", "contract_or_oath", "mechanical_acceptance_or_refusal",
            ],
            "disclosure_rule": "An NPC may disclose an already-existing private fact present in lawful speaker cognition. The spoken line makes the disclosure observable to Wei but does not by itself convert the statement into independently verified objective truth or create a secret that did not already exist.",
            "private_motives_may_be_gm_private_but_are_not_player_knowledge": True,
            "mechanical_consequence_authority": False,
        }
        if private_cognition:
            out["npc_response_envelope"]["gm_private_cognition"] = private_cognition
        if private_character_truth:
            out["npc_response_envelope"]["gm_private_character_truth"] = private_character_truth
        if private_behavior:
            out["npc_response_envelope"]["gm_private_behavior_profile"] = private_behavior
        try:
            relationships = self.store.read_json("state/relationships.json")
            edges = relationships.get("edges", []) if isinstance(relationships, Mapping) else []
        except (FileNotFoundError, KeyError, TypeError, ValueError):
            edges = []
        relation_rows = []
        if isinstance(edges, list):
            for edge in edges:
                if not isinstance(edge, Mapping):
                    continue
                source = str(edge.get("source_ref") or "")
                target = str(edge.get("target_ref") or "")
                if {source, target} != {player_id, person_id}:
                    continue
                relation_rows.append({
                    key: edge.get(key) for key in ("edge_ref", "source_ref", "target_ref", "kind", "history", "current_tension", "dimensions")
                    if edge.get(key) not in (None, "", [], {})
                })
        if relation_rows:
            out["npc_response_envelope"]["gm_private_relationship_context"] = {
                "privacy": "gm_private_cognition_not_player_knowledge",
                "edges": relation_rows[:4],
                "mechanical_consequence_authority": False,
                "use_rule": "Use as qualitative relationship/history direction only. Do not quote numeric dimensions or turn them into guaranteed emotions, consent, loyalty, or hard outcomes.",
            }
        return out

    def _with_gm_private_scene_director_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """Add bounded backstage truth for exact present cast before dialogue begins."""
        scene = dict(context.get("scene", {})) if isinstance(context.get("scene"), Mapping) else {}
        cast = scene.get("scene_cast", {}) if isinstance(scene.get("scene_cast"), Mapping) else {}
        present = cast.get("present_people", []) if isinstance(cast.get("present_people"), list) else []
        player_id = str(context.get("campaign", {}).get("player_id") or "")
        player_location = context.get("player", {}).get("location")
        if not player_id or not player_location or not present:
            return context
        try:
            owner_index = self.store.read_json("state/index/owner-index.json")
        except (FileNotFoundError, KeyError, TypeError, ValueError):
            return context
        owners = owner_index.get("owners", {}) if isinstance(owner_index, Mapping) else {}
        if not isinstance(owners, Mapping):
            return context

        # Transport order is not conversational importance.  Build one
        # deterministic salience order so active interaction targets and live
        # session participants keep their backstage cognition even in crowded
        # councils where the cast list itself is sorted for stable output.
        present_by_ref = {
            str(row.get("person_id")): row
            for row in present
            if isinstance(row, Mapping)
            and isinstance(row.get("person_id"), str)
            and row.get("person_id")
        }
        prioritized_refs: list[str] = []

        def prioritize(ref: object) -> None:
            if (
                isinstance(ref, str)
                and ref != player_id
                and ref in present_by_ref
                and ref not in prioritized_refs
            ):
                prioritized_refs.append(ref)

        active_threads = scene.get("active_threads", []) if isinstance(scene.get("active_threads"), list) else []
        for thread in reversed(active_threads):
            if isinstance(thread, Mapping):
                prioritize(thread.get("target_ref"))
        session = scene.get("active_scene_session") if isinstance(scene.get("active_scene_session"), Mapping) else context.get("active_scene_session")
        if isinstance(session, Mapping):
            for ref in session.get("participant_refs", []) if isinstance(session.get("participant_refs"), list) else []:
                prioritize(ref)
        recent = context.get("recent_scene_history", []) if isinstance(context.get("recent_scene_history"), list) else []
        for history_row in reversed(recent):
            if not isinstance(history_row, Mapping):
                continue
            prioritize(history_row.get("speaker_ref"))
            prioritize(history_row.get("actor_ref"))
        for cast_row in present:
            if isinstance(cast_row, Mapping):
                prioritize(cast_row.get("person_id"))

        people: list[dict[str, Any]] = []
        accepted: list[str] = []
        for ref in prioritized_refs:
            cast_row = present_by_ref[ref]
            path = owners.get(ref) if ref and ref != player_id else None
            if not isinstance(path, str):
                continue
            try:
                person = self.store.read_json(path)
            except (FileNotFoundError, KeyError, TypeError, ValueError):
                continue
            location = person.get("current_location") or person.get("location_ref") or person.get("location") if isinstance(person, Mapping) else None
            if location != player_location:
                continue
            row: dict[str, Any] = {"person_ref": ref, "name": person.get("name") or cast_row.get("name")}
            truth = _gm_private_character_truth(person)
            cognition = _gm_private_goal_cognition(person)
            behavior = self._gm_private_behavior_profile(ref)
            if truth:
                row["character_truth"] = truth
            if cognition:
                row["cognition"] = cognition
            if behavior:
                row["behavior_profile"] = behavior
            people.append(row)
            accepted.append(ref)
            if len(people) >= _GM_PRIVATE_SCENE_PERSON_LIMIT:
                break
        if not people:
            return context
        edges_out: list[dict[str, Any]] = []
        try:
            relationships = self.store.read_json("state/relationships.json")
            edges = relationships.get("edges", []) if isinstance(relationships, Mapping) else []
        except (FileNotFoundError, KeyError, TypeError, ValueError):
            edges = []
        allowed = {player_id, *accepted}
        if isinstance(edges, list):
            for edge in edges:
                if not isinstance(edge, Mapping):
                    continue
                source = str(edge.get("source_ref") or "")
                target = str(edge.get("target_ref") or "")
                if source not in allowed or target not in allowed or source == target:
                    continue
                row = {
                    key: edge.get(key) for key in ("edge_ref", "source_ref", "target_ref", "kind", "history", "current_tension", "dimensions")
                    if edge.get(key) not in (None, "", [], {})
                }
                edges_out.append(row)
                if len(edges_out) >= 24:
                    break
        director = scene.get("gm_private_director_context") if isinstance(scene.get("gm_private_director_context"), Mapping) else {}
        director = dict(director)
        director["present_people_context"] = {
            "privacy": "gm_private_scene_bounded_omniscient_truth_not_player_knowledge",
            "scope": "exact_present_scene_cast_only",
            "present_people": people,
            "candidate_present_people_count": len(prioritized_refs),
            "present_people_context_count": len(people),
            "present_people_context_truncated": len(prioritized_refs) > len(people),
            "selection_rule": "active interaction targets, active-session participants and recent scene actors first; remaining exact present cast fill the bounded packet",
            "relationship_edges": edges_out,
            "mechanical_consequence_authority": False,
            "director_rule": (
                "Use this backstage truth to let present NPCs initiate, react, interrupt, joke, disagree, lie, omit, leave, or speak to one another coherently even before a formal conversation session. "
                "Do not expose hidden motives, private numeric state, or undisclosed knowledge as Tang Wei's knowledge; narrate only perception, lawful inference, or actual disclosure. Hard outcomes still belong to their runtime mechanics."
            ),
        }
        scene["gm_private_director_context"] = director
        out = dict(context)
        out["scene"] = scene
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
                    if schema in {"sab_character", "sword-materialized-person", "person-lite"}:
                        representation = "person_lite" if schema == "person-lite" else "full_character"
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
        context = self._with_gm_private_scene_director_context(dict(super().play_context()))
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

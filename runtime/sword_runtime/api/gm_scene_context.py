"""Scene-first writer workspace for the ChatGPT Game Master.

The builder creates no fiction and no campaign state. It reorganizes already
projected player-safe evidence and explicitly marked GM-private truth so the GM
can write continuous fiction without treating runtime object boundaries as prose.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _text(value: object, maximum: int = 700) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value if len(value) <= maximum else value[: maximum - 3].rstrip() + "..."


def _refs(value: object, maximum: int = 24) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item and item not in out:
            out.append(item)
        if len(out) >= maximum:
            break
    return out


def _pick(source: object, keys: Sequence[str]) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        return {}
    return {key: source[key] for key in keys if source.get(key) not in (None, "", [], {})}



_GM_PRIVATE_BULK_KEYS = frozenset({
    "attributes", "martial_skills", "skills", "capabilities", "equipment_manifest",
    "inventory", "participant_sheets", "focus_participants", "participants",
    "positions", "team_plans", "obstacles", "raw_state", "full_state",
})


def _compact_private_extension(value: object, *, depth: int = 0) -> Any:
    """Preserve unknown semantic backstage fields without carrying raw state bulk."""
    if depth >= 3:
        if isinstance(value, str):
            return value[:1200]
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return None
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in list(value.items())[:32]:
            key_text = str(key)
            if key_text in _GM_PRIVATE_BULK_KEYS:
                continue
            compact = _compact_private_extension(item, depth=depth + 1)
            if compact not in (None, {}, []):
                out[key_text] = compact
        return out
    if isinstance(value, list):
        rows: list[Any] = []
        for item in value[:16]:
            compact = _compact_private_extension(item, depth=depth + 1)
            if compact not in (None, {}, []):
                rows.append(compact)
        return rows
    if isinstance(value, tuple):
        return _compact_private_extension(list(value), depth=depth)
    if isinstance(value, str):
        return value[:1200]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return None


def _compact_private_person_direction(source: object) -> dict[str, Any]:
    """Keep one bounded backstage characterization packet for one exact present person."""
    if not isinstance(source, Mapping):
        return {}
    row = _pick(source, ("person_ref", "name", "behavior_profile"))
    truth = source.get("character_truth")
    if isinstance(truth, Mapping):
        truth_out = _pick(truth, (
            "life_status", "health_status", "fatigue", "role",
            "authority", "command_assignment", "military_command",
            "private_knowledge", "hidden_goals", "secret_notes",
            "autonomy_private",
        ))
        career = truth.get("career_state")
        if isinstance(career, Mapping):
            career_out = _pick(career, ("current_billet", "current_command_span", "office_or_command"))
            if career_out:
                truth_out["career_state"] = career_out
        if truth_out:
            row["character_truth"] = truth_out
    cognition = source.get("cognition")
    if isinstance(cognition, Mapping):
        cognition_out = {
            key: item for key, item in cognition.items()
            if key not in {"privacy", "use_rule"}
        }
        if cognition_out:
            row["cognition"] = cognition_out
    return row


def _compact_private_director(value: object) -> dict[str, Any]:
    """Project scene-relevant backstage truth without duplicating per-person direction."""
    if not isinstance(value, Mapping):
        return {}
    out = _pick(value, (
        "privacy", "scope", "director_rule", "disclosure_rule",
        "mechanical_consequence_authority",
    ))
    handled_root = {
        "privacy", "scope", "director_rule", "disclosure_rule",
        "mechanical_consequence_authority", "present_people_context",
        "participant_identities", "participant_capability_and_condition",
    }
    for key, item in value.items():
        if key in handled_root:
            continue
        compact = _compact_private_extension(item)
        if compact not in (None, {}, []):
            out[str(key)] = compact

    present = value.get("present_people_context")
    if isinstance(present, Mapping):
        packet = _pick(present, (
            "privacy", "scope", "candidate_present_people_count",
            "present_people_context_count", "present_people_context_truncated",
        ))
        # Stable directing doctrine belongs in the GM Skill. Repeating long
        # director/selection/performance instructions inside every live packet
        # wastes context and encourages the model to treat transport prose as
        # scene content. Keep only runtime-varying backstage facts here.
        handled_present = {
            "privacy", "scope", "candidate_present_people_count",
            "present_people_context_count", "present_people_context_truncated",
            "director_rule", "selection_rule", "performance_cues_rule",
            "present_people", "relationship_edges",
        }
        for key, item in present.items():
            if key in handled_present:
                continue
            compact = _compact_private_extension(item)
            if compact not in (None, {}, []):
                packet[str(key)] = compact
        if isinstance(present.get("present_people"), list) and present.get("present_people"):
            packet["people_context_source"] = "present_people[].gm_private_direction"
        if isinstance(present.get("relationship_edges"), list) and present.get("relationship_edges"):
            packet["relationship_context_source"] = "relationship_edges_gm_private"
        if packet:
            out["present_people_context"] = packet

    identities = value.get("participant_identities")
    if isinstance(identities, Mapping):
        out["participant_identities"] = {
            str(ref): dict(row) for ref, row in list(identities.items())[:16]
            if isinstance(ref, str) and isinstance(row, Mapping)
        }
    conditions = value.get("participant_capability_and_condition")
    if isinstance(conditions, Mapping):
        compact_conditions: dict[str, Any] = {}
        for ref, source in list(conditions.items())[:16]:
            if not isinstance(ref, str) or not isinstance(source, Mapping):
                continue
            row = _pick(source, ("alignment", "health", "fatigue", "combat_doctrine_ref", "equipment", "start_state", "end_state"))
            if row:
                compact_conditions[ref] = row
        if compact_conditions:
            out["participant_condition"] = compact_conditions
    return out

def _history_row(source: object) -> dict[str, Any] | None:
    if not isinstance(source, Mapping):
        return None
    row = _pick(source, (
        "speech_ref", "fact_ref", "continuity_ref", "at", "session_ref",
        "speaker_ref", "actor_ref", "speech_kind", "fact_kind", "continuity_kind",
        "resolves_thread_ref", "truth_status",
    ))
    statement = _text(source.get("statement"), 650)
    summary = _text(source.get("summary"), 650)
    if statement:
        row["statement"] = statement
    if summary:
        row["summary"] = summary
    subject_refs = _refs(source.get("subject_refs"), 12)
    participant_refs = _refs(source.get("participant_refs"), 12)
    if subject_refs:
        row["subject_refs"] = subject_refs
    if participant_refs:
        row["participant_refs"] = participant_refs
    return row or None


def _history(value: object, maximum: int = 10) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in (_history_row(item) for item in value[-maximum:]) if row]


def _scene_history_window(history: list[dict[str, Any]], session: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    # Immediate continuity is scene-local. Once the active session closes, older
    # attributed speech and reversible scene facts remain available through
    # durable literary continuity, but they must not masquerade as the current
    # conversational beat in a fresh scene.
    if not isinstance(session, Mapping):
        return []
    session_ref = session.get("session_ref")
    if not isinstance(session_ref, str) or not session_ref:
        return []
    matched = [row for row in history if row.get("session_ref") == session_ref]
    return matched[-10:] if matched else []


def _scene_people(scene: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cast = scene.get("scene_cast")
    present = cast.get("present_people") if isinstance(cast, Mapping) else None
    private = scene.get("gm_private_director_context")
    private_context = private.get("present_people_context") if isinstance(private, Mapping) else None
    private_people = private_context.get("present_people") if isinstance(private_context, Mapping) else None
    private_by_ref: dict[str, dict[str, Any]] = {}
    if isinstance(private_people, list):
        for source in private_people[:16]:
            row = _compact_private_person_direction(source)
            ref = row.get("person_ref") if isinstance(row, Mapping) else None
            if isinstance(ref, str) and ref:
                private_by_ref[ref] = row

    rows: list[dict[str, Any]] = []
    if isinstance(present, list):
        for source in present[:20]:
            if not isinstance(source, Mapping):
                continue
            row = _pick(source, ("person_id", "person_ref", "name", "role", "player_identity_awareness", "scene_basis"))
            ref = row.get("person_id") or row.get("person_ref")
            if isinstance(ref, str) and ref in private_by_ref:
                row["gm_private_direction"] = private_by_ref[ref]
            if row:
                rows.append(row)

    edges = private_context.get("relationship_edges") if isinstance(private_context, Mapping) else None
    relationship_edges = [dict(row) for row in edges[:24] if isinstance(row, Mapping)] if isinstance(edges, list) else []
    return rows, relationship_edges

def _human_threads(context: Mapping[str, Any], session: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Return only human threads that are live in the current scene.

    Historical/open interaction attempts can remain valid obligations without
    proving that their target is standing in this room.  Scene direction must
    therefore prefer the active-session projection, which already revalidates
    physical participation, and leave remote replies to their process/report
    owners.
    """
    if not isinstance(session, Mapping):
        return []
    session_ref = session.get("session_ref")
    if not isinstance(session_ref, str) or not session_ref:
        return []

    rows: list[dict[str, Any]] = []
    scene = context.get("scene") if isinstance(context.get("scene"), Mapping) else {}
    projected = scene.get("active_threads") if isinstance(scene, Mapping) else None
    source_rows: list[Mapping[str, Any]] = []
    if isinstance(projected, list):
        source_rows = [row for row in projected if isinstance(row, Mapping)]
    else:
        attempts = context.get("recent_interaction_attempts")
        if isinstance(attempts, list):
            source_rows = [
                row for row in attempts
                if isinstance(row, Mapping)
                and row.get("scene_session_ref") == session_ref
                and str(row.get("thread_status") or row.get("status") or "open") in {"open", "pending"}
            ]

    for source in source_rows[:16]:
        row = _pick(source, (
            "event_id", "attempt_ref", "at", "action", "target_ref",
            "topic", "process_ref", "scene_session_ref", "thread_status",
        ))
        statement = _text(source.get("player_statement"), 700)
        if statement:
            row["player_statement"] = statement
        if row:
            rows.append(row)

    # Do not reconstruct missing durable thread refs as live human threads.
    # The active-thread projection has already filtered by fresh physical
    # presence. An opaque session ref may belong to a departed participant and
    # is useful only through the exact thread read if that person later returns.
    return rows[:16]


def _recent_player_actions(context: Mapping[str, Any], session: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Keep Wei's latest declared words/actions even after a thread is resolved.

    These rows prove only what the player authored or attempted. They never
    import an NPC response or hard outcome.
    """
    attempts = context.get("recent_interaction_attempts")
    if not isinstance(attempts, list):
        return []
    session_ref = session.get("session_ref") if isinstance(session, Mapping) else None
    if not isinstance(session_ref, str) or not session_ref:
        # No live scene session means prior attempts are historical intent, not
        # immediate dialogue/action continuity. Current player input is already
        # present in the chat turn and durable standing intent is projected by
        # its exact operation/process owner.
        return []
    source_rows = [
        row for row in attempts
        if isinstance(row, Mapping) and row.get("scene_session_ref") == session_ref
    ]
    # Sword's public attempt window is newest-first. Keep the newest eight
    # for this scene, then restore causal (oldest-to-newest) order for the
    # writer workspace instead of accidentally selecting the oldest tail.
    source_rows = list(reversed(source_rows[:8]))
    rows: list[dict[str, Any]] = []
    for source in source_rows:
        row = _pick(source, (
            "event_id", "attempt_ref", "at", "action", "target_ref", "process_ref",
            "posture", "topic", "scopes", "scene_session_ref", "thread_status",
            "resolved_at", "response_ref",
        ))
        statement = _text(source.get("player_statement"), 650)
        if statement:
            row["player_statement"] = statement
        if row:
            rows.append(row)
    return rows[-8:]


def _immediate_scene_timeline(
    history: list[dict[str, Any]], player_actions: list[dict[str, Any]], maximum: int = 10
) -> list[dict[str, Any]]:
    """Merge human scene continuity into causal order without writing prose."""
    rows: list[dict[str, Any]] = []
    for source in history:
        if source.get("continuity_ref"):
            continue
        row = dict(source)
        if row.get("speech_ref"):
            row["beat_kind"] = "attributed_speech"
        elif row.get("fact_ref"):
            row["beat_kind"] = "reversible_scene_fact"
        else:
            row["beat_kind"] = "scene_history"
        rows.append(row)
    for source in player_actions:
        row = dict(source)
        row["beat_kind"] = "player_declared_action"
        rows.append(row)
    rows.sort(key=lambda row: (str(row.get("at") or ""), str(row.get("attempt_ref") or row.get("speech_ref") or row.get("fact_ref") or "")))
    return rows[-max(1, min(int(maximum), 16)):]

def _compact_operational_intent(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    out = _pick(value, (
        "operational_intent", "deliberate_battle_commitment_authorized",
        "field_command_relationship", "independent_detachment",
        "contact_is_not_synonymous_with_battle",
        "general_attack_requires_explicit_attack_authority_or_player_commitment",
        "campaign_commander_ref", "friendly_campaign_participant_operation_count",
    ))
    if value.get("support_continuity_rule") is not None or value.get("parent_campaign_support_remains_real") is True:
        out["parent_campaign_support_remains_real"] = True
    return out





def _protected_player_decision_pending(context: Mapping[str, Any], scene: Mapping[str, Any]) -> bool:
    """Detect only explicit player-owned decision boundaries.

    This is presentation guidance, not a new decision authority.  It prevents
    active-scene direction from accidentally resolving Wei's protected choice
    while still allowing NPCs to react, clarify, or continue reversible work.
    """
    for value in (context.get("unresolved_decision"), scene.get("unresolved_decision")):
        if isinstance(value, Mapping) and value:
            return True
    for value in (context.get("unresolved_decisions"), scene.get("unresolved_decisions")):
        if isinstance(value, list) and any(isinstance(row, Mapping) and row for row in value):
            return True
    for value in (context.get("pending_wake"), scene.get("pending_wake"), scene.get("activity_handoff")):
        if not isinstance(value, Mapping):
            continue
        if any(value.get(key) is True for key in (
            "requires_player_decision", "requires_player_response", "response_required", "decision_required"
        )):
            return True
    return False

def _scene_direction_packet(
    *,
    session: Mapping[str, Any] | None,
    present_people: list[dict[str, Any]],
    player_ref: str | None,
    human_threads: list[dict[str, Any]],
    practical_threads: list[dict[str, Any]],
    immediate_continuity: list[dict[str, Any]],
    recent_hard_events: list[dict[str, Any]],
    protected_player_decision_pending: bool,
) -> dict[str, Any]:
    """Compact dynamic handoff for LLM scene direction.

    The detailed directing doctrine lives in the Game Master Skill.  This packet
    carries only turn-specific evidence and concise quality gates so the writer
    gets a strong directing signal without spending the context budget on the
    same static prose every turn.  It never selects dialogue or outcomes.
    """
    agent_refs: list[str] = []
    directed_agent_refs: list[str] = []
    for row in present_people:
        if not isinstance(row, Mapping):
            continue
        ref = row.get("person_ref") or row.get("person_id")
        if not isinstance(ref, str) or not ref or ref == player_ref:
            continue
        if ref not in agent_refs:
            agent_refs.append(ref)
        if isinstance(row.get("gm_private_direction"), Mapping) and ref not in directed_agent_refs:
            directed_agent_refs.append(ref)

    human_target_refs: list[str] = []
    for row in human_threads:
        if not isinstance(row, Mapping):
            continue
        ref = row.get("target_ref") or row.get("person_ref")
        if isinstance(ref, str) and ref and ref != player_ref and ref not in human_target_refs:
            human_target_refs.append(ref)

    recent_actor_refs: list[str] = []
    for row in reversed(immediate_continuity):
        if not isinstance(row, Mapping):
            continue
        ref = row.get("speaker_ref") or row.get("actor_ref") or row.get("target_ref")
        if isinstance(ref, str) and ref and ref != player_ref and ref not in recent_actor_refs:
            recent_actor_refs.append(ref)
        if len(recent_actor_refs) >= 6:
            break

    already_narrated_beat_refs: list[str] = []
    for row in immediate_continuity:
        if not isinstance(row, Mapping):
            continue
        ref = row.get("speech_ref") or row.get("fact_ref") or row.get("attempt_ref") or row.get("event_id")
        if isinstance(ref, str) and ref and ref not in already_narrated_beat_refs:
            already_narrated_beat_refs.append(ref)

    session_kind = str(session.get("kind") or session.get("scene_kind") or "") if isinstance(session, Mapping) else ""
    session_presence_viable = not (
        isinstance(session, Mapping)
        and session.get("physical_scene_viable") is False
    )
    external_practical_threads = [
        row for row in practical_threads
        if isinstance(row, Mapping) and row.get("thread_kind") != "active_scene"
    ]
    if protected_player_decision_pending:
        continuation_mode = "preserve_player_decision_and_allow_reversible_reaction"
    elif isinstance(session, Mapping) and not session_presence_viable:
        continuation_mode = "reconcile_stale_formal_session_then_transition"
    elif isinstance(session, Mapping) and (human_threads or external_practical_threads):
        continuation_mode = "continue_active_scene"
    elif isinstance(session, Mapping):
        continuation_mode = "active_scene_continue_or_transition_by_lived_pressure"
    elif agent_refs:
        continuation_mode = "present_people_may_initiate"
    elif practical_threads:
        continuation_mode = "continue_process_or_compress"
    elif recent_hard_events:
        continuation_mode = "render_consequence_then_follow_causality"
    else:
        continuation_mode = "quiet_beat_or_transition"

    session_priority_refs = [
        ref for ref in (_refs(session.get("participant_refs"), 24) if isinstance(session, Mapping) else [])
        if ref != player_ref and ref in agent_refs
    ]
    situational_priority_refs: list[str] = []
    for row in present_people:
        if not isinstance(row, Mapping):
            continue
        ref = row.get("person_ref") or row.get("person_id")
        bases = row.get("scene_basis")
        if not isinstance(ref, str) or ref == player_ref or ref not in agent_refs or not isinstance(bases, list):
            continue
        if any(base in {
            "calendar_event", "campaign_command_event", "command_conference",
            "mission_event", "escort_handoff", "active_process",
        } for base in bases if isinstance(base, str)) and ref not in situational_priority_refs:
            situational_priority_refs.append(ref)

    actor_pressure_refs: list[str] = []
    for ref in human_target_refs + recent_actor_refs + session_priority_refs + situational_priority_refs + directed_agent_refs + agent_refs:
        if isinstance(ref, str) and ref and ref not in actor_pressure_refs:
            actor_pressure_refs.append(ref)

    # Give the LLM a tiny causal ranking signal without choosing dialogue or
    # behavior for it.  These are reasons an already-present person may deserve
    # the next beat, not a speaking queue or a deterministic NPC script.
    beat_candidates: list[dict[str, str]] = []
    seen_candidate_refs: set[str] = set()
    for refs, reason in (
        (human_target_refs, "open_human_thread"),
        (recent_actor_refs, "recent_exchange"),
        (session_priority_refs, "active_formal_session"),
        (situational_priority_refs, "current_event_or_process"),
        (directed_agent_refs, "private_direction_available"),
        (agent_refs, "present_agent"),
    ):
        for ref in refs:
            if ref in seen_candidate_refs:
                continue
            beat_candidates.append({"person_ref": ref, "reason": reason})
            seen_candidate_refs.add(ref)
            if len(beat_candidates) >= 8:
                break
        if len(beat_candidates) >= 8:
            break

    contested_process_active = any(
        isinstance(row, Mapping) and row.get("thread_kind") in {"exact_combat", "active_conflict"}
        for row in practical_threads
    )
    session_active = isinstance(session, Mapping)
    session_ref = str(session.get("session_ref") or "") if session_active else ""
    session_participants = _refs(session.get("participant_refs"), 24) if session_active else []
    projected_absent_refs = _refs(session.get("physically_absent_participant_refs"), 24) if session_active else []
    scene_participants: list[str] = []
    for ref in ([player_ref] if isinstance(player_ref, str) and player_ref else []) + agent_refs:
        if isinstance(ref, str) and ref and ref not in scene_participants:
            scene_participants.append(ref)
    currently_present_session_refs = [ref for ref in session_participants if ref in scene_participants]
    absent_session_refs: list[str] = []
    for ref in projected_absent_refs + [ref for ref in session_participants if ref not in scene_participants]:
        if ref not in absent_session_refs:
            absent_session_refs.append(ref)
    nonplayer_present_session_refs = [ref for ref in currently_present_session_refs if ref != player_ref]
    formal_session_presence_viable = bool(nonplayer_present_session_refs)
    close_risks: list[str] = []
    if human_threads:
        close_risks.append("open_human_threads")
    if protected_player_decision_pending:
        close_risks.append("protected_player_decision")

    fresh_scene_entry = not immediate_continuity and not session_active
    if protected_player_decision_pending:
        narrative_stage_hint = "decision_handoff"
    elif recent_hard_events:
        narrative_stage_hint = "consequence_or_aftermath"
    elif human_threads:
        narrative_stage_hint = "friction_or_development"
    elif practical_threads and agent_refs:
        narrative_stage_hint = "approach_or_anticipation" if fresh_scene_entry else "development"
    elif practical_threads:
        narrative_stage_hint = "process_continuation"
    else:
        narrative_stage_hint = "quiet_transition"

    scene_lifecycle = {
        "formal_session_active": session_active,
        "formal_session_ref": session_ref or None,
        "formal_session_participant_refs": session_participants,
        "formal_session_currently_present_refs": currently_present_session_refs,
        "formal_session_absent_participant_refs": absent_session_refs,
        "formal_session_has_absent_participant": bool(absent_session_refs),
        "formal_session_presence_viable": formal_session_presence_viable if session_active else None,
        "lifecycle_reconciliation_recommended": bool(session_active and not formal_session_presence_viable),
        "lifecycle_reconciliation_reason": (
            "formal_session_has_no_other_physically_present_participant"
            if session_active and not formal_session_presence_viable else None
        ),
        "candidate_participant_refs": scene_participants[:16],
        "open_affordance": (not session_active and bool(agent_refs) and not contested_process_active),
        "close_affordance": session_active,
        "contested_process_active": contested_process_active,
        "close_risks": close_risks,
        "persistence_route_source": "GM Skill scene lifecycle contract",
    }

    return {
        "schema": "llm-scene-direction-2.0",
        "llm_is_scene_director": True,
        "continuation_mode": continuation_mode,
        "session_kind": session_kind or None,
        "present_agent_refs": agent_refs[:16],
        "present_agent_count": len(agent_refs),
        "agents_with_private_direction_refs": directed_agent_refs[:16],
        "open_human_thread_count": len(human_threads),
        "open_human_target_refs": human_target_refs[:12],
        "practical_thread_count": len(practical_threads),
        "external_practical_thread_count": len(external_practical_threads),
        "recent_continuity_beat_count": len(immediate_continuity),
        "already_narrated_beat_refs": already_narrated_beat_refs[-12:],
        "recent_nonplayer_actor_refs": recent_actor_refs,
        "actor_pressure_refs": actor_pressure_refs[:16],
        "beat_candidates": beat_candidates,
        "beat_candidate_rule": "causal_priority_hint_not_speaking_queue_or_script",
        "recent_hard_event_count": len(recent_hard_events),
        "protected_player_decision_pending": protected_player_decision_pending,
        "fresh_scene_entry": fresh_scene_entry,
        "narrative_stage_hint": narrative_stage_hint,
        "raw_context_paraphrase_risk": "high" if fresh_scene_entry and (practical_threads or recent_hard_events) else "normal",
        "scene_lifecycle": scene_lifecycle,
        "next_beat_requirement": "advance_grounded_scene_or_compress",
        "director_protocol": [
            "reconstruct_live_beat",
            "choose_change_before_prose",
            "select_actor_by_pressure_not_cast_order",
            "stage_reversible_world_response",
            "translate_only_committed_hard_consequences",
            "decide_scene_lifecycle_from_lived_pressure",
            "stop_at_real_handoff_not_runtime_boundary",
        ],
        "director_doctrine_source": "GM Skill scene/runtime, active-scene progression, and scene-craft contract",
    }

def _practical_threads(context: Mapping[str, Any], scene: Mapping[str, Any], session: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(session, Mapping):
        row = _pick(session, ("session_ref", "kind", "process_ref", "purpose", "agenda", "location_ref"))
        if row:
            row["thread_kind"] = "active_scene"
            rows.append(row)
    for source in context.get("active_player_processes", []) if isinstance(context.get("active_player_processes"), list) else []:
        if isinstance(source, Mapping):
            row = _pick(source, ("object_ref", "kind", "status", "phase", "summary", "purpose", "target_ref"))
            if row:
                row["thread_kind"] = "player_process"
                rows.append(row)
    for source in context.get("controlled_operations", []) if isinstance(context.get("controlled_operations"), list) else []:
        if isinstance(source, Mapping):
            row = _pick(source, ("operation_ref", "object_ref", "kind", "status", "campaign_phase", "mission_phase", "summary"))
            intent = _compact_operational_intent(source.get("operational_intent_contract"))
            if intent:
                row["operational_intent"] = intent
            if row:
                row["thread_kind"] = "controlled_operation"
                rows.append(row)
    for key in ("personal_combat", "battle", "siege"):
        conflict = scene.get(key)
        if isinstance(conflict, Mapping):
            row = _pick(conflict, ("combat_ref", "battle_ref", "siege_ref", "status", "phase"))
            if row:
                row["thread_kind"] = "active_conflict"
                rows.append(row)
                break
    return rows[:10]


def _shared_premises(history: list[dict[str, Any]], scene: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [row for row in history if row.get("fact_kind") == "shared_premise"][-8:]
    narrative = scene.get("narrative")
    if isinstance(narrative, Mapping):
        source_rows = narrative.get("shared_premises")
        if isinstance(source_rows, list):
            for source in source_rows:
                if isinstance(source, Mapping):
                    rows.append(dict(source))
                elif isinstance(source, str):
                    rows.append({"summary": _text(source, 600)})
    return rows[-10:]


def _compact_observation(key: str, value: Mapping[str, Any]) -> dict[str, Any]:
    """Project scene evidence without duplicating complete battle/person state."""
    if key in {"battlefield_perception", "combat_observation_context"}:
        return _pick(value, (
            "combat_ref", "battle_ref", "status", "phase", "elapsed_ms",
            "material_beats", "recent_material_events", "recent_events",
            "player_visible_geometry", "nearby_threats", "visible_formations",
            "signals", "reports", "report_delays", "uncertainty",
            "narration_contract",
        ))
    if key == "current_information_boundary":
        return _pick(value, (
            "observed_refs", "reported_refs", "rumor_refs", "inferred_refs",
            "verified_refs", "uncertain_refs", "knowledge_cutoff",
        ))
    return {
        str(item_key): item
        for item_key, item in list(value.items())[:24]
        if item not in (None, "", [], {})
    }


def _hard_events(context: Mapping[str, Any], scene: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    for key in ("recent_causal_events", "campaign_event_notices", "recent_events"):
        value = context.get(key)
        if isinstance(value, list):
            candidates.extend(value)
    for key in ("combat_observation_context", "battlefield_perception", "battle", "personal_combat"):
        value = scene.get(key)
        if isinstance(value, Mapping):
            for event_key in ("material_beats", "recent_material_events", "recent_events"):
                events = value.get(event_key)
                if isinstance(events, list):
                    candidates.extend(events)
    return [dict(row) for row in candidates[-10:] if isinstance(row, Mapping)]


def _world_pressure(context: Mapping[str, Any], scene: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("available_reports", "pending_information_paths", "recent_reveals", "unresolved_hooks", "observable_pressures"):
        value = scene.get(key)
        if isinstance(value, list):
            for source in value[:3]:
                if isinstance(source, Mapping):
                    row = _pick(source, (
                        "interaction_ref", "event_ref", "report_ref", "kind", "status", "at",
                        "triggered_at", "source_ref", "target_ref", "operation_ref",
                    ))
                    if source.get("summary"):
                        row["detail_available_via_exact_read"] = True
                elif isinstance(source, str):
                    row = {"detail_available_via_exact_read": True}
                else:
                    row = None
                if row:
                    row["source_kind"] = key
                    rows.append(row)
        elif isinstance(value, Mapping):
            row = _pick(value, ("event_ref", "report_ref", "kind", "status", "at", "source_ref", "target_ref"))
            if value.get("summary"):
                row["detail_available_via_exact_read"] = True
            if row:
                row["source_kind"] = key
                rows.append(row)
    handles = context.get("interaction_handles")
    if isinstance(handles, list):
        for source in handles[:3]:
            if isinstance(source, Mapping):
                row = _pick(source, ("interaction_ref", "kind", "triggered_at", "source_ref", "target_ref", "operation_ref"))
                if source.get("summary"):
                    row["detail_available_via_exact_interaction_read"] = True
                if row:
                    row["source_kind"] = "delivered_interaction"
                    rows.append(row)
    # The same report may appear both as an observable pressure and as its
    # delivered interaction handle. Keep one causally useful row, preferring the
    # richer delivered summary instead of making the writer re-read duplicates.
    deduped: list[dict[str, Any]] = []
    index: dict[tuple[str, str], int] = {}
    for row in rows:
        identity = str(row.get("interaction_ref") or row.get("event_ref") or row.get("report_ref") or "")
        kind = str(row.get("kind") or "")
        key = (identity, kind) if identity else (str(row.get("source_kind") or ""), kind)
        if key in index:
            current = deduped[index[key]]
            if row.get("summary") and not current.get("summary"):
                current.update(row)
            elif row.get("source_kind") == "delivered_interaction":
                # Delivery is the player-facing causal channel; preserve that
                # label even when the observable-pressure copy arrived first.
                current["source_kind"] = "delivered_interaction"
                if row.get("summary"):
                    current["summary"] = row["summary"]
            continue
        index[key] = len(deduped)
        deduped.append(row)
    return deduped[:8]


def build_gm_scene_context(context: Mapping[str, Any]) -> dict[str, Any]:
    campaign = context.get("campaign") if isinstance(context.get("campaign"), Mapping) else {}
    scene = context.get("scene") if isinstance(context.get("scene"), Mapping) else {}
    player = context.get("player") if isinstance(context.get("player"), Mapping) else {}
    session = context.get("active_scene_session") if isinstance(context.get("active_scene_session"), Mapping) else None
    all_history = _history(context.get("recent_scene_history"), 16)
    history = _scene_history_window(all_history, session)
    recent_player_actions = _recent_player_actions(context, session)

    now = {
        "world_time": campaign.get("world_time") or scene.get("world_time"),
        "location_ref": player.get("location") or scene.get("location") or scene.get("location_id"),
        "projection_status": scene.get("projection_status"),
    }
    physical = scene.get("physical_scene")
    if isinstance(physical, Mapping):
        physical_out = {
            str(key): value
            for key, value in physical.items()
            if key != "controlled_formation_refs_at_player_location" and value not in (None, "", [], {})
        }
        local_formations = physical.get("controlled_formation_refs_at_player_location")
        if isinstance(local_formations, list):
            physical_out["controlled_formation_count_at_player_location"] = len(local_formations)
            physical_out["controlled_formation_detail"] = "demand_load_exact_controlled_formation_when_material"
        if physical_out:
            now["physical_scene"] = physical_out

    observations: dict[str, Any] = {}
    for key in ("player_observable_state", "observable_pressures", "battlefield_perception", "combat_observation_context", "current_information_boundary"):
        value = scene.get(key)
        if isinstance(value, Mapping):
            compact = _compact_observation(key, value)
            if compact:
                observations[key] = compact

    private = scene.get("gm_private_director_context") if isinstance(scene.get("gm_private_director_context"), Mapping) else {}
    immediate_continuity = _immediate_scene_timeline(history, recent_player_actions, 8)
    human_threads = _human_threads(context, session)
    practical_threads = _practical_threads(context, scene, session)
    recent_hard_events = _hard_events(context, scene)
    protected_player_decision_pending = _protected_player_decision_pending(context, scene)
    present_people, relationship_edges = _scene_people(scene)
    player_ref = str(player.get("person_id") or campaign.get("player_id") or "") or None
    scene_direction = _scene_direction_packet(
        session=session,
        present_people=present_people,
        player_ref=player_ref,
        human_threads=human_threads,
        practical_threads=practical_threads,
        immediate_continuity=immediate_continuity,
        recent_hard_events=recent_hard_events,
        protected_player_decision_pending=protected_player_decision_pending,
    )
    operational_intent_contracts = []
    controlled_ops = context.get("controlled_operations")
    if isinstance(controlled_ops, list):
        for op in controlled_ops:
            if isinstance(op, Mapping) and isinstance(op.get("operational_intent_contract"), Mapping):
                compact_intent = _compact_operational_intent(op["operational_intent_contract"])
                if compact_intent:
                    operational_intent_contracts.append(compact_intent)
                if len(operational_intent_contracts) >= 4:
                    break
    return {
        "schema": "sword-gm-scene-context-1.0",
        "authority": False,
        "mechanical_consequence_authority": False,
        "purpose": "prioritized_writer_workspace_not_prose",
        "now": now,
        "immediate_continuity": immediate_continuity,
        "scene_direction": scene_direction,
        "present_people": present_people,
        "relationship_edges_gm_private": relationship_edges,
        "shared_premises": _shared_premises(history, scene),
        "wei_observations_and_known_scene_evidence": observations,
        "gm_private_scene_truth": {
            "director_context": _compact_private_director(private),
            "rule": "Backstage direction only. Never expose hidden truth as Tang Wei knowledge or a choice premise until lawfully perceived, inferred, reported, or disclosed.",
        },
        "recent_player_action_count": len(recent_player_actions),
        "human_threads": human_threads,
        "practical_threads": practical_threads,
        "literary_continuity": [dict(row) for row in context.get("literary_continuity", []) if isinstance(row, Mapping)][-16:] or [row for row in history if row.get("continuity_ref")][-8:],
        "recent_hard_events": recent_hard_events,
        "world_pressure": _world_pressure(context, scene),
        "hard_constraints": {
            "authority_rule_source": "GM Skill scene/runtime contract",
            "player_location_ref": now.get("location_ref"),
            "pending_wake": context.get("pending_wake") if isinstance(context.get("pending_wake"), Mapping) else None,
            "operational_intent_contracts": operational_intent_contracts,
        },
        "deep_reads": {
            "permitted_person_ref_count": len(context.get("permitted_person_ids") or []) if isinstance(context.get("permitted_person_ids"), list) else 0,
            "permitted_object_ref_count": len(context.get("permitted_object_refs") or []) if isinstance(context.get("permitted_object_refs"), list) else 0,
            "permitted_person_refs_source": "play_context.permitted_person_ids",
            "permitted_object_refs_source": "play_context.permitted_object_refs",
            "read_hints_source": "play_context.read_hints",
            "rule_source": "GM Skill progressive reads contract",
        },
        "writer_contract": {
            "doctrine_source": "GM Skill universal novel-first and scene/runtime contract",
            "scene_direction_owner": "llm",
            "hard_consequence_owner": "runtime",
            "serial_scene_not_turn_summary": True,
            "raw_summaries_are_reference_not_prose": True,
            "anti_state_dump_gate": True,
        },
    }


__all__ = ["build_gm_scene_context"]

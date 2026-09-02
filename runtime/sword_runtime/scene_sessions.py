"""Non-authoritative live scene sessions and attributed-speech history.

The campaign runtime owns hard world truth.  This module owns only the durable
*record of play* needed to keep people-centered scenes coherent across command
boundaries and fresh ChatGPT contexts.  Nothing written here may move a body,
spend resources, grant authority, reveal hidden facts, or establish that an
NPC's attributed statement is objectively true.
"""
from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

ACTIVE_SESSION_PATH = "state/index/active-scene-session.json"
HISTORY_HEAD_PATH = "state/index/scene-history-head.json"
HISTORY_HEAD_LIMIT = 64
HISTORY_SHARD_LIMIT = 512
INTERACTION_LEDGER_PATH = "state/index/interaction-attempts.json"
INTERACTION_CLOSED_HISTORY_LIMIT = 128
CONTINUITY_SUBJECT_LIMIT = 128
CONTINUITY_PER_SUBJECT_LIMIT = 6

SESSION_KINDS = frozenset({
    "war_council", "council", "audience", "briefing", "family_discussion",
    "negotiation", "conversation", "interview", "examination", "command_conference",
})
SPEECH_KINDS = frozenset({
    "clarification", "opinion", "inference", "question", "nonbinding_proposal",
    "nonbinding_response", "observation", "advice", "objection",
})
SCENE_FACT_KINDS = frozenset({
    "local_action", "object_state", "positioning", "visible_reaction",
    "shared_premise", "incidental_detail",
})
CONTINUITY_NOTE_KINDS = frozenset({
    "portrayal_evidence", "relationship_expression", "recurring_reference",
    "conversation_memory", "place_memory",
})
CLOSE_REASONS = frozenset({
    "completed", "player_left", "hard_interruption", "skipped_to_conclusion",
    "superseded", "cancelled",
})

_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")

_RESPONSE_BEARING_ACTIONS = frozenset({"ask", "request", "petition", "offer", "present", "report", "speak"})


def _expects_response(action: str, explicit: object) -> bool:
    if isinstance(explicit, bool):
        return explicit
    return action in _RESPONSE_BEARING_ACTIONS



def _read_optional(reader: Any, path: str) -> Any:
    if hasattr(reader, "read_optional"):
        return reader.read_optional(path)
    if hasattr(reader, "read_optional_json"):
        return reader.read_optional_json(path)
    if hasattr(reader, "read_json"):
        try:
            return reader.read_json(path)
        except FileNotFoundError:
            return None
    if hasattr(reader, "read"):
        try:
            return reader.read(path)
        except FileNotFoundError:
            return None
    raise TypeError("scene-session reader does not support optional JSON reads")


def _put(writer: Any, path: str, value: Mapping[str, Any]) -> None:
    if hasattr(writer, "put"):
        writer.put(path, dict(value))
        return
    raise TypeError("scene-session writer does not support JSON writes")


def _safe_ref(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF.fullmatch(value):
        raise ValueError(f"scene {field} is invalid")
    return value


def _bounded_text(value: object, field: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ch in value for ch in ("\x00", "\r"))
    ):
        raise ValueError(f"scene {field} is invalid")
    return value.strip()


def _period_token(at: str) -> str:
    # Campaign timestamps are not guaranteed to be ISO years (e.g. 244-BCE-...).
    # Keep a readable, path-safe monthly token without parsing chronology here.
    text = re.sub(r"[^A-Za-z0-9]+", "-", str(at)).strip("-")
    parts = text.split("-")
    if len(parts) >= 3 and parts[1] in {"BCE", "CE"}:
        token = "-".join(parts[:3])
    elif len(parts) >= 2:
        token = "-".join(parts[:2])
    else:
        token = text[:24] or "unknown"
    return token[:40]


def history_period_ref(at: str) -> str:
    return f"scene_history_period_{_period_token(at)}"


def history_period_path(period_ref: str) -> str:
    ref = _safe_ref(period_ref, "history period ref")
    if not ref.startswith("scene_history_period_"):
        raise ValueError("scene history period ref is invalid")
    return f"state/history/scene-speech/{ref}.json"


def active_scene_session(reader: Any) -> dict[str, Any] | None:
    raw = _read_optional(reader, ACTIVE_SESSION_PATH)
    if not isinstance(raw, Mapping) or raw.get("schema") != "sword-scene-session":
        return None
    if raw.get("status") != "active":
        return None
    return copy.deepcopy(dict(raw))


def scene_session_projection(reader: Any) -> dict[str, Any] | None:
    session = active_scene_session(reader)
    if session is None:
        return None
    return {
        "session_ref": session.get("session_ref"),
        "kind": session.get("kind"),
        "status": "active",
        "location_ref": session.get("location_ref"),
        "process_ref": session.get("process_ref"),
        "participant_refs": list(session.get("participant_refs", [])),
        "started_at": session.get("started_at"),
        "soft_end_at": session.get("soft_end_at"),
        "purpose": session.get("purpose"),
        "agenda": list(session.get("agenda", [])),
        "open_thread_refs": list(session.get("open_thread_refs", session.get("open_question_refs", [])))[-16:],
        "open_thread_count": len(session.get("open_thread_refs", session.get("open_question_refs", []))),
        "open_threads_truncated": len(session.get("open_thread_refs", session.get("open_question_refs", []))) > 16,
        # Legacy question-only aliases remain for old clients and saves.
        "open_question_refs": list(session.get("open_question_refs", []))[-16:],
        "open_question_count": len(session.get("open_question_refs", [])),
        "open_questions_truncated": len(session.get("open_question_refs", [])) > 16,
        "authority": False,
        "mechanical_consequence_authority": False,
    }


def start_scene_session(
    writer: Any,
    *,
    session_ref: str,
    kind: str,
    location_ref: str,
    participant_refs: Sequence[str],
    started_at: str,
    process_ref: str | None = None,
    purpose: str | None = None,
    agenda: Sequence[str] = (),
    soft_end_at: str | None = None,
) -> dict[str, Any]:
    session_ref = _safe_ref(session_ref, "session_ref")
    if kind not in SESSION_KINDS:
        raise ValueError("scene session kind is unsupported")
    location_ref = _safe_ref(location_ref, "location_ref")
    participants = [_safe_ref(ref, "participant_ref") for ref in participant_refs]
    participants = list(dict.fromkeys(participants))
    if not participants or len(participants) > 128:
        raise ValueError("scene session requires between one and 128 unique participants")
    if process_ref is not None:
        process_ref = _safe_ref(process_ref, "process_ref")
    if purpose is not None:
        purpose = _bounded_text(purpose, "purpose", 1000)
    if len(agenda) > 32:
        raise ValueError("scene session agenda exceeds bounded transport")
    agenda_rows = [_bounded_text(value, "agenda item", 500) for value in agenda]
    current = active_scene_session(writer)
    if current is not None and current.get("session_ref") != session_ref:
        prior_ref = str(current.get("session_ref"))
        abandon_session_threads(writer, prior_ref, at=started_at)
        close_scene_session(writer, at=started_at, reason="superseded")
    record = {
        "schema": "sword-scene-session",
        "authority": False,
        "mechanical_consequence_authority": False,
        "session_ref": session_ref,
        "kind": kind,
        "status": "active",
        "location_ref": location_ref,
        "process_ref": process_ref,
        "participant_refs": participants,
        "started_at": started_at,
        "soft_end_at": soft_end_at,
        "purpose": purpose,
        "agenda": agenda_rows,
        "open_thread_refs": [],
        "open_question_refs": [],
        "last_updated_at": started_at,
    }
    _put(writer, ACTIVE_SESSION_PATH, record)
    return copy.deepcopy(record)



def touch_active_scene(writer: Any, *, at: str, session_ref: str | None = None) -> bool:
    """Mark an active presentation session as actually engaged by play.

    Session timestamps are presentation metadata only.  This touch lets causal
    lifecycle code distinguish a merely auto-opened scene from one the player
    has genuinely continued, without creating any mechanical world fact.
    """
    session = active_scene_session(writer)
    if session is None:
        return False
    if session_ref is not None and _safe_ref(session_ref, "session_ref") != str(session.get("session_ref")):
        return False
    if session.get("last_updated_at") == at:
        return True
    session["last_updated_at"] = at
    _put(writer, ACTIVE_SESSION_PATH, session)
    return True

def attach_open_thread(writer: Any, thread_ref: str, *, at: str, is_question: bool = False) -> str | None:
    """Attach one unresolved conversational move to the active reversible scene.

    A thread may be a question, request, proposal, petition, offer, or another
    response-bearing scene move. It is continuity metadata only and never grants
    acceptance, permission, authority, or another mechanical consequence.
    """
    session = active_scene_session(writer)
    if session is None:
        return None
    ref = _safe_ref(thread_ref, "thread_ref")
    rows = [str(x) for x in session.get("open_thread_refs", session.get("open_question_refs", [])) if isinstance(x, str)]
    if ref not in rows:
        rows.append(ref)
    session["open_thread_refs"] = rows
    if is_question:
        questions = [str(x) for x in session.get("open_question_refs", []) if isinstance(x, str)]
        if ref not in questions:
            questions.append(ref)
        session["open_question_refs"] = questions
    session["last_updated_at"] = at
    _put(writer, ACTIVE_SESSION_PATH, session)
    return str(session.get("session_ref"))


def attach_open_question(writer: Any, question_ref: str, *, at: str) -> str | None:
    return attach_open_thread(writer, question_ref, at=at, is_question=True)


def resolve_open_thread(writer: Any, thread_ref: str, *, at: str) -> bool:
    session = active_scene_session(writer)
    if session is None:
        return False
    ref = _safe_ref(thread_ref, "thread_ref")
    before = [str(x) for x in session.get("open_thread_refs", session.get("open_question_refs", [])) if isinstance(x, str)]
    after = [x for x in before if x != ref]
    questions_before = [str(x) for x in session.get("open_question_refs", []) if isinstance(x, str)]
    questions_after = [x for x in questions_before if x != ref]
    if after == before and questions_after == questions_before:
        return False
    session["open_thread_refs"] = after
    session["open_question_refs"] = questions_after
    session["last_updated_at"] = at
    _put(writer, ACTIVE_SESSION_PATH, session)
    return True


def resolve_open_question(writer: Any, question_ref: str, *, at: str) -> bool:
    return resolve_open_thread(writer, question_ref, at=at)


def abandon_session_threads(writer: Any, session_ref: str, *, at: str) -> int:
    """Mark unresolved conversational threads abandoned when their scene closes.

    The interaction ledger is routing/history metadata only.  Updating thread
    lifecycle here cannot establish an NPC response or any mechanical outcome.
    Legacy rows are normalized lazily so old saves remain writable.
    """
    ref = _safe_ref(session_ref, "session_ref")
    raw = _read_optional(writer, INTERACTION_LEDGER_PATH)
    if not isinstance(raw, Mapping):
        return 0
    ledger = copy.deepcopy(dict(raw))
    values = ledger.get("attempts")
    if not isinstance(values, list):
        return 0
    changed = 0
    normalized = False
    rows: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, Mapping):
            continue
        original = dict(value)
        row = copy.deepcopy(original)
        row.setdefault("scene_session_ref", None)
        expects_response = _expects_response(str(row.get("action") or ""), row.get("expects_response"))
        has_statement = isinstance(row.get("player_statement"), str) and bool(row.get("player_statement"))
        row.setdefault("thread_status", "open" if expects_response and has_statement and row.get("scene_session_ref") else "not_applicable")
        row.setdefault("resolved_at", None)
        row.setdefault("response_ref", None)
        if str(row.get("scene_session_ref")) == ref and row.get("thread_status") == "open":
            row["thread_status"] = "abandoned_with_scene_close"
            row["resolved_at"] = at
            changed += 1
        normalized = normalized or row != original
        rows.append(row)
    if changed:
        open_rows = [row for row in rows if row.get("thread_status") == "open"]
        closed_rows = [row for row in rows if row.get("thread_status") != "open"]
        ledger["attempts"] = open_rows + closed_rows[-INTERACTION_CLOSED_HISTORY_LIMIT:]
        _put(writer, INTERACTION_LEDGER_PATH, ledger)
    elif normalized:
        ledger["attempts"] = rows
        _put(writer, INTERACTION_LEDGER_PATH, ledger)
    return changed


def abandon_session_questions(writer: Any, session_ref: str, *, at: str) -> int:
    # Backward-compatible name retained for older callers.
    return abandon_session_threads(writer, session_ref, at=at)

def close_scene_session(writer: Any, *, at: str, reason: str) -> dict[str, Any] | None:
    raw = _read_optional(writer, ACTIVE_SESSION_PATH)
    if not isinstance(raw, Mapping) or raw.get("schema") != "sword-scene-session":
        return None
    if reason not in CLOSE_REASONS:
        raise ValueError("scene close reason is unsupported")
    session = copy.deepcopy(dict(raw))
    if session.get("status") != "active":
        return session
    session["status"] = "closed"
    session["closed_at"] = at
    session["close_reason"] = reason
    session["last_updated_at"] = at
    _put(writer, ACTIVE_SESSION_PATH, session)
    return session


def close_active_scene(writer: Any, *, at: str, reason: str) -> dict[str, Any] | None:
    """Close the active reversible scene and terminate its unresolved threads."""
    session = active_scene_session(writer)
    if session is None:
        return None
    session_ref = str(session.get("session_ref"))
    abandoned = abandon_session_threads(writer, session_ref, at=at)
    closed = close_scene_session(writer, at=at, reason=reason)
    return {
        "session_ref": session_ref,
        "close_reason": reason,
        "abandoned_thread_count": abandoned,
        "abandoned_question_count": abandoned,  # legacy aggregate alias
        "closed": closed is not None,
    }


def _history_head(reader: Any) -> dict[str, Any]:
    raw = _read_optional(reader, HISTORY_HEAD_PATH)
    if isinstance(raw, Mapping) and raw.get("schema") == "sword-scene-history-head":
        return copy.deepcopy(dict(raw))
    return {
        "schema": "sword-scene-history-head",
        "authority": False,
        "mechanical_consequence_authority": False,
        "purpose": "bounded recent non-authoritative scene history; speech remains attributed and reversible scene facts never replace hard world authority",
        "total_recorded": 0,
        "latest_period_ref": None,
        "recent": [],
        "continuity_by_subject": {},
        "continuity_subject_order": [],
    }


def recent_scene_history(reader: Any, *, limit: int = 8) -> list[dict[str, Any]]:
    head = _history_head(reader)
    rows = head.get("recent", []) if isinstance(head.get("recent"), list) else []
    bounded = max(1, min(int(limit), HISTORY_HEAD_LIMIT))
    return [copy.deepcopy(dict(row)) for row in rows[-bounded:] if isinstance(row, Mapping)]


def scene_history_record(reader: Any, record_ref: str, *, session_ref: str | None = None, max_shards: int = 8) -> dict[str, Any] | None:
    """Resolve one exact recent scene-history record without a repository scan.

    The hot head is checked first, then the bounded shard chain is followed
    backwards.  This is intentionally suitable for promoting an already
    established reversible scene prop into one mechanical resolver; it never
    converts arbitrary narration into world authority.
    """
    record_ref = _safe_ref(record_ref, "scene_history_record_ref")
    wanted_session = _safe_ref(session_ref, "session_ref") if session_ref is not None else None
    head = _history_head(reader)
    recent = head.get("recent", []) if isinstance(head.get("recent"), list) else []
    for row in reversed(recent):
        if not isinstance(row, Mapping):
            continue
        try:
            ref = _history_row_ref(row)
        except ValueError:
            continue
        if ref == record_ref and (wanted_session is None or str(row.get("session_ref")) == wanted_session):
            return copy.deepcopy(dict(row))
    period_ref = head.get("latest_period_ref") if isinstance(head.get("latest_period_ref"), str) else None
    seen: set[str] = set()
    for _ in range(max(1, min(int(max_shards), 32))):
        if not period_ref or period_ref in seen:
            break
        seen.add(period_ref)
        shard = _read_optional(reader, history_period_path(period_ref))
        if not isinstance(shard, Mapping) or shard.get("schema") != "sword-scene-history-shard":
            break
        rows = shard.get("records", []) if isinstance(shard.get("records"), list) else []
        for row in reversed(rows):
            if not isinstance(row, Mapping):
                continue
            try:
                ref = _history_row_ref(row)
            except ValueError:
                continue
            if ref == record_ref and (wanted_session is None or str(row.get("session_ref")) == wanted_session):
                return copy.deepcopy(dict(row))
        period_ref = shard.get("previous_period_ref") if isinstance(shard.get("previous_period_ref"), str) else None
    return None


def inspect_scene_history(reader: Any, object_ref: str) -> dict[str, Any] | None:
    if object_ref == "scene_history_head":
        return _history_head(reader)
    if object_ref.startswith("scene_history_period_"):
        raw = _read_optional(reader, history_period_path(object_ref))
        if isinstance(raw, Mapping) and raw.get("schema") == "sword-scene-history-shard":
            return copy.deepcopy(dict(raw))
    return None


def _speech_ref(surface_digest: str, speaker_ref: str, statement: str, at: str) -> str:
    token = hashlib.sha256(f"{surface_digest}|{speaker_ref}|{at}|{statement}".encode("utf-8")).hexdigest()[:24]
    return f"scene_speech_{token}"


def _fact_ref(surface_digest: str, actor_ref: str, fact_kind: str, summary: str, at: str) -> str:
    token = hashlib.sha256(f"{surface_digest}|{actor_ref}|{fact_kind}|{at}|{summary}".encode("utf-8")).hexdigest()[:24]
    return f"scene_fact_{token}"


def _continuity_ref(surface_digest: str, continuity_kind: str, summary: str, at: str) -> str:
    token = hashlib.sha256(f"{surface_digest}|{continuity_kind}|{at}|{summary}".encode("utf-8")).hexdigest()[:24]
    return f"scene_continuity_{token}"


def _history_row_ref(row: Mapping[str, Any]) -> str:
    for key in ("speech_ref", "fact_ref", "continuity_ref"):
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    raise ValueError("scene history record lacks stable identity")


def relevant_scene_continuity(
    reader: Any, *, subject_refs: Sequence[str] = (), location_ref: str | None = None, limit: int = 12
) -> list[dict[str, Any]]:
    """Return bounded long-lived literary continuity relevant to this scene."""
    head = _history_head(reader)
    index = head.get("continuity_by_subject") if isinstance(head.get("continuity_by_subject"), Mapping) else {}
    keys: list[str] = []
    for ref in subject_refs:
        if isinstance(ref, str) and ref and ref not in keys:
            keys.append(ref)
    if isinstance(location_ref, str) and location_ref:
        key = f"location:{location_ref}"
        if key not in keys:
            keys.append(key)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in keys:
        values = index.get(key) if isinstance(index, Mapping) else None
        if not isinstance(values, list):
            continue
        for raw in values:
            if not isinstance(raw, Mapping):
                continue
            ref = raw.get("continuity_ref")
            if not isinstance(ref, str) or not ref or ref in seen:
                continue
            seen.add(ref)
            rows.append(copy.deepcopy(dict(raw)))
    # Relevance is the union of the current people and place. Select the most
    # recent notes across that whole union so the first indexed person cannot
    # crowd out newer relationship/place continuity for somebody else.
    rows.sort(key=lambda row: (str(row.get("at") or ""), str(row.get("continuity_ref") or "")))
    bounded = max(1, min(int(limit), 32))
    return rows[-bounded:]


def _update_continuity_hot_index(head: dict[str, Any], row: Mapping[str, Any]) -> None:
    if not isinstance(row.get("continuity_ref"), str):
        return
    keys: list[str] = []
    for ref in row.get("subject_refs", []) if isinstance(row.get("subject_refs"), list) else []:
        if isinstance(ref, str) and ref and ref not in keys:
            keys.append(ref)
    location_ref = row.get("location_ref")
    if isinstance(location_ref, str) and location_ref:
        keys.append(f"location:{location_ref}")
    if not keys:
        return
    index_raw = head.get("continuity_by_subject")
    index = copy.deepcopy(dict(index_raw)) if isinstance(index_raw, Mapping) else {}
    order = [str(x) for x in head.get("continuity_subject_order", []) if isinstance(x, str)]
    for key in keys:
        values = [copy.deepcopy(dict(x)) for x in index.get(key, []) if isinstance(x, Mapping)] if isinstance(index.get(key), list) else []
        values = [x for x in values if x.get("continuity_ref") != row.get("continuity_ref")]
        values.append(copy.deepcopy(dict(row)))
        index[key] = values[-CONTINUITY_PER_SUBJECT_LIMIT:]
        order = [x for x in order if x != key] + [key]
    while len(order) > CONTINUITY_SUBJECT_LIMIT:
        old = order.pop(0)
        index.pop(old, None)
    head["continuity_by_subject"] = index
    head["continuity_subject_order"] = order


def _append_history_row(writer: Any, row: Mapping[str, Any]) -> dict[str, Any]:
    """Append one non-authoritative scene-history row to bounded head + shard."""
    record = copy.deepcopy(dict(row))
    record_ref = _history_row_ref(record)
    at = str(record.get("at") or "")
    head = _history_head(writer)
    recent = [dict(x) for x in head.get("recent", []) if isinstance(x, Mapping)]
    recent_duplicate = any(_history_row_ref(x) == record_ref for x in recent if isinstance(x, Mapping) and (x.get("speech_ref") or x.get("fact_ref") or x.get("continuity_ref")))
    period_base = history_period_ref(at)
    latest_ref = head.get("latest_period_ref") if isinstance(head.get("latest_period_ref"), str) else None
    same_period = bool(latest_ref and (latest_ref == period_base or latest_ref.startswith(period_base + "_part_")))
    period_ref = latest_ref if same_period else period_base
    existing = _read_optional(writer, history_period_path(period_ref)) if isinstance(period_ref, str) else None
    if isinstance(existing, Mapping) and existing.get("schema") == "sword-scene-history-shard":
        shard = copy.deepcopy(dict(existing))
    else:
        shard = {
            "schema": "sword-scene-history-shard",
            "authority": False,
            "mechanical_consequence_authority": False,
            "period_ref": period_ref,
            "previous_period_ref": latest_ref if latest_ref != period_ref else None,
            "records": [],
        }
    records = [dict(x) for x in shard.get("records", []) if isinstance(x, Mapping)]
    duplicate = any(_history_row_ref(x) == record_ref for x in records if isinstance(x, Mapping) and (x.get("speech_ref") or x.get("fact_ref") or x.get("continuity_ref")))
    if duplicate:
        return record
    if len(records) >= HISTORY_SHARD_LIMIT:
        previous_ref = str(shard.get("period_ref"))
        if previous_ref == period_base:
            part = 2
        else:
            match = re.search(r"_part_(\d+)$", previous_ref)
            part = int(match.group(1)) + 1 if match else 2
        period_ref = f"{period_base}_part_{part:04d}"
        shard = {
            "schema": "sword-scene-history-shard",
            "authority": False,
            "mechanical_consequence_authority": False,
            "period_ref": period_ref,
            "previous_period_ref": previous_ref,
            "records": [],
        }
        records = []
    records.append(copy.deepcopy(record))
    shard["records"] = records
    if not recent_duplicate:
        recent.append(copy.deepcopy(record))
        head["total_recorded"] = int(head.get("total_recorded", 0)) + 1
    head["latest_period_ref"] = period_ref
    head["recent"] = recent[-HISTORY_HEAD_LIMIT:]
    _update_continuity_hot_index(head, record)
    _put(writer, history_period_path(period_ref), shard)
    _put(writer, HISTORY_HEAD_PATH, head)
    return record


def record_attributed_speech(
    writer: Any,
    *,
    surface_digest: str,
    at: str,
    speaker_ref: str,
    statement: str,
    speech_kind: str,
    session_ref: str | None = None,
    basis_refs: Sequence[str] = (),
    resolves_thread_ref: str | None = None,
    resolves_question_ref: str | None = None,
) -> dict[str, Any]:
    if speech_kind not in SPEECH_KINDS:
        raise ValueError("scene speech kind is unsupported")
    speaker_ref = _safe_ref(speaker_ref, "speaker_ref")
    statement = _bounded_text(statement, "statement", 2500)
    active = active_scene_session(writer)
    if active is None:
        raise ValueError("attributed scene speech requires an active scene session")
    actual_session_ref = str(active.get("session_ref"))
    if session_ref is not None and _safe_ref(session_ref, "session_ref") != actual_session_ref:
        raise ValueError("attributed scene speech session does not match active session")
    if speaker_ref not in set(str(x) for x in active.get("participant_refs", []) if isinstance(x, str)):
        raise ValueError("attributed scene speaker is not an active session participant")
    basis = [_safe_ref(ref, "basis_ref") for ref in basis_refs]
    basis = list(dict.fromkeys(basis))[:32]
    active_participants = set(str(x) for x in active.get("participant_refs", []) if isinstance(x, str))
    active_threads = set(str(x) for x in active.get("open_thread_refs", active.get("open_question_refs", [])) if isinstance(x, str))
    allowed_basis = active_participants | active_threads
    if isinstance(active.get("process_ref"), str):
        allowed_basis.add(str(active.get("process_ref")))
    for ref in basis:
        if ref in allowed_basis:
            continue
        history_row = scene_history_record(writer, ref, session_ref=actual_session_ref)
        if not isinstance(history_row, Mapping):
            raise ValueError("scene speech basis_ref is not visible in the active session")
    thread_ref = resolves_thread_ref if resolves_thread_ref is not None else resolves_question_ref
    question_ref = None
    if thread_ref is not None:
        thread_ref = _safe_ref(thread_ref, "resolves_thread_ref")
        open_threads = set(str(x) for x in active.get("open_thread_refs", active.get("open_question_refs", [])) if isinstance(x, str))
        if thread_ref not in open_threads:
            raise ValueError("scene response may resolve only an open conversational thread in the active session")
        if thread_ref in set(str(x) for x in active.get("open_question_refs", []) if isinstance(x, str)):
            question_ref = thread_ref
    row = {
        "speech_ref": _speech_ref(surface_digest, speaker_ref, statement, at),
        "at": at,
        "session_ref": actual_session_ref,
        "speaker_ref": speaker_ref,
        "speech_kind": speech_kind,
        "statement": statement,
        "basis_refs": basis,
        "resolves_thread_ref": thread_ref,
        "resolves_question_ref": question_ref,
        "truth_status": "attributed_statement",
        "authority": False,
        "mechanical_consequence_authority": False,
    }
    stored = _append_history_row(writer, row)
    touch_active_scene(writer, at=at, session_ref=actual_session_ref)
    if thread_ref is not None:
        resolve_open_thread(writer, thread_ref, at=at)
    return stored


def record_scene_fact(
    writer: Any,
    *,
    surface_digest: str,
    at: str,
    actor_ref: str,
    summary: str,
    fact_kind: str,
    session_ref: str | None = None,
    participant_refs: Sequence[str] = (),
    basis_refs: Sequence[str] = (),
    improvised_prop: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one salient reversible scene fact without mechanical authority.

    This is continuity, not a generic state-write escape hatch. It may remember
    that an established participant moved within the room, handled an already
    established mundane object, visibly reacted, or established a shared premise.
    It cannot grant access, move a person between mechanical locations, transfer
    inventory/resources, injure anyone, settle a contest, or create authority.
    """
    if fact_kind not in SCENE_FACT_KINDS:
        raise ValueError("scene fact kind is unsupported")
    actor_ref = _safe_ref(actor_ref, "actor_ref")
    summary = _bounded_text(summary, "scene fact summary", 1500)
    active = active_scene_session(writer)
    if active is None:
        raise ValueError("scene fact requires an active scene session")
    actual_session_ref = str(active.get("session_ref"))
    if session_ref is not None and _safe_ref(session_ref, "session_ref") != actual_session_ref:
        raise ValueError("scene fact session does not match active session")
    active_participants = set(str(x) for x in active.get("participant_refs", []) if isinstance(x, str))
    if actor_ref not in active_participants:
        raise ValueError("scene fact actor is not an active session participant")
    participants = list(dict.fromkeys(_safe_ref(ref, "participant_ref") for ref in participant_refs))[:32]
    if any(ref not in active_participants for ref in participants):
        raise ValueError("scene fact participant is not in the active session")
    basis = list(dict.fromkeys(_safe_ref(ref, "basis_ref") for ref in basis_refs))[:32]
    open_threads = set(str(x) for x in active.get("open_thread_refs", active.get("open_question_refs", [])) if isinstance(x, str))
    allowed_basis = active_participants | open_threads
    if isinstance(active.get("process_ref"), str):
        allowed_basis.add(str(active.get("process_ref")))
    history_basis: dict[str, dict[str, Any]] = {}
    for ref in basis:
        if ref in allowed_basis:
            continue
        history_row = scene_history_record(writer, ref, session_ref=actual_session_ref)
        if not isinstance(history_row, Mapping):
            raise ValueError("scene fact basis_ref is not visible in the active session")
        history_basis[ref] = dict(history_row)
    prop = None
    source_object_fact_ref = None
    if improvised_prop is not None:
        if fact_kind != "object_state":
            raise ValueError("improvised scene prop requires object_state fact kind")
        allowed_keys = {"kind", "form", "material", "condition"}
        if not isinstance(improvised_prop, Mapping) or set(improvised_prop) - allowed_keys:
            raise ValueError("improvised scene prop is invalid")
        prop = {str(k): str(v) for k, v in improvised_prop.items()}
        if prop.get("kind") != "mundane_improvised_prop":
            raise ValueError("improvised scene prop kind is unsupported")
        prior_object_facts = [
            row for row in history_basis.values()
            if row.get("fact_kind") == "object_state"
            and row.get("truth_status") == "observed_reversible_scene_fact"
            and row.get("mechanical_consequence_authority") is False
        ]
        # A first observation may carry the bounded physical descriptor, but
        # that fact alone is not combat-usable.  Once a later object-state fact
        # cites prior object history, at least one cited prior object must carry
        # the exact same descriptor.  This prevents a harmless cup fact from
        # being reused to justify a different heavy/sharp object.
        if prior_object_facts:
            matching_sources = [
                history_row for history_row in prior_object_facts
                if isinstance(history_row.get("improvised_prop"), Mapping)
                and dict(history_row.get("improvised_prop")) == prop
            ]
            if not matching_sources:
                raise ValueError("improvised scene prop does not match prior object_state descriptor")
            source_object_fact_ref = str(matching_sources[0].get("fact_ref") or "") or None
    row = {
        "fact_ref": _fact_ref(surface_digest, actor_ref, fact_kind, summary, at),
        "at": at,
        "session_ref": actual_session_ref,
        "actor_ref": actor_ref,
        "fact_kind": fact_kind,
        "summary": summary,
        "participant_refs": participants,
        "basis_refs": basis,
        "truth_status": "observed_reversible_scene_fact",
        "scope": "scene_local_history_only",
        "authority": False,
        "mechanical_consequence_authority": False,
    }
    if prop is not None:
        row["improvised_prop"] = prop
    if source_object_fact_ref is not None:
        row["source_object_fact_ref"] = source_object_fact_ref
    stored = _append_history_row(writer, row)
    touch_active_scene(writer, at=at, session_ref=actual_session_ref)
    return stored


def record_continuity_note(
    writer: Any,
    *,
    surface_digest: str,
    at: str,
    summary: str,
    continuity_kind: str,
    session_ref: str | None = None,
    subject_refs: Sequence[str] = (),
    basis_refs: Sequence[str] = (),
) -> dict[str, Any]:
    """Store an interpretive literary-memory note grounded in scene history.

    A continuity note is deliberately weaker than a reversible scene fact. It
    summarizes how an already-recorded exchange may be portrayed later, and
    cannot establish objective motive, relationship state, place state, injury,
    movement, resources, authority, or any other hard campaign fact.
    """
    if continuity_kind not in CONTINUITY_NOTE_KINDS:
        raise ValueError("scene continuity kind is unsupported")
    summary = _bounded_text(summary, "continuity summary", 1500)
    active = active_scene_session(writer)
    if active is None:
        raise ValueError("scene continuity requires an active scene session")
    actual_session_ref = str(active.get("session_ref"))
    if session_ref is not None and _safe_ref(session_ref, "session_ref") != actual_session_ref:
        raise ValueError("scene continuity session does not match active session")
    active_participants = set(str(x) for x in active.get("participant_refs", []) if isinstance(x, str))
    subjects = list(dict.fromkeys(_safe_ref(ref, "subject_ref") for ref in subject_refs))[:16]
    if any(ref not in active_participants for ref in subjects):
        raise ValueError("scene continuity subject is not an active session participant")
    basis = list(dict.fromkeys(_safe_ref(ref, "basis_ref") for ref in basis_refs))[:16]
    if not basis:
        raise ValueError("scene continuity requires cited scene history")
    primary_basis_present = False
    for ref in basis:
        history_row = scene_history_record(writer, ref, session_ref=actual_session_ref)
        if not isinstance(history_row, Mapping):
            raise ValueError("scene continuity basis_ref is not active-session scene history")
        if history_row.get("mechanical_consequence_authority") is not False:
            raise ValueError("scene continuity basis_ref is not presentation-only")
        if isinstance(history_row.get("speech_ref"), str) or isinstance(history_row.get("fact_ref"), str):
            primary_basis_present = True
    if not primary_basis_present:
        raise ValueError("scene continuity requires primary speech or scene-fact evidence")
    row = {
        "continuity_ref": _continuity_ref(surface_digest, continuity_kind, summary, at),
        "at": at,
        "session_ref": actual_session_ref,
        "continuity_kind": continuity_kind,
        "summary": summary,
        "subject_refs": subjects,
        "basis_refs": basis,
        "location_ref": str(active.get("location_ref") or ""),
        "truth_status": "derived_narrative_continuity",
        "scope": "scene_history_only",
        "derivation_rule": "interpretive_summary_of_cited_authority_false_scene_history_not_objective_world_truth",
        "authority": False,
        "mechanical_consequence_authority": False,
    }
    stored = _append_history_row(writer, row)
    touch_active_scene(writer, at=at, session_ref=actual_session_ref)
    return stored


__all__ = [
    "ACTIVE_SESSION_PATH", "CLOSE_REASONS", "HISTORY_HEAD_PATH", "INTERACTION_CLOSED_HISTORY_LIMIT", "SESSION_KINDS", "SPEECH_KINDS", "SCENE_FACT_KINDS", "CONTINUITY_NOTE_KINDS",
    "abandon_session_questions", "abandon_session_threads", "active_scene_session", "attach_open_question", "attach_open_thread", "close_active_scene", "close_scene_session", "history_period_path",
    "history_period_ref", "inspect_scene_history", "recent_scene_history", "relevant_scene_continuity", "scene_history_record", "record_attributed_speech", "record_scene_fact", "record_continuity_note",
    "resolve_open_question", "resolve_open_thread", "scene_session_projection", "start_scene_session", "touch_active_scene",
]

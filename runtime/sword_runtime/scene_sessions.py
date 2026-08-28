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

SESSION_KINDS = frozenset({
    "war_council", "council", "audience", "briefing", "family_discussion",
    "negotiation", "conversation", "interview", "examination", "command_conference",
})
SPEECH_KINDS = frozenset({
    "clarification", "opinion", "inference", "question", "nonbinding_proposal",
    "nonbinding_response", "observation", "advice", "objection",
})
CLOSE_REASONS = frozenset({
    "completed", "player_left", "hard_interruption", "skipped_to_conclusion",
    "superseded", "cancelled",
})

_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$")


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
        abandon_session_questions(writer, prior_ref, at=started_at)
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

def attach_open_question(writer: Any, question_ref: str, *, at: str) -> str | None:
    session = active_scene_session(writer)
    if session is None:
        return None
    ref = _safe_ref(question_ref, "question_ref")
    rows = [str(x) for x in session.get("open_question_refs", []) if isinstance(x, str)]
    if ref not in rows:
        rows.append(ref)
    session["open_question_refs"] = rows
    session["last_updated_at"] = at
    _put(writer, ACTIVE_SESSION_PATH, session)
    return str(session.get("session_ref"))


def resolve_open_question(writer: Any, question_ref: str, *, at: str) -> bool:
    session = active_scene_session(writer)
    if session is None:
        return False
    ref = _safe_ref(question_ref, "question_ref")
    before = [str(x) for x in session.get("open_question_refs", []) if isinstance(x, str)]
    after = [x for x in before if x != ref]
    if after == before:
        return False
    session["open_question_refs"] = after
    session["last_updated_at"] = at
    _put(writer, ACTIVE_SESSION_PATH, session)
    return True



def abandon_session_questions(writer: Any, session_ref: str, *, at: str) -> int:
    """Mark unresolved player questions as abandoned when their scene closes.

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
    rows: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, Mapping):
            continue
        row = copy.deepcopy(dict(value))
        row.setdefault("scene_session_ref", None)
        is_question = (
            str(row.get("action")) == "ask"
            and isinstance(row.get("player_statement"), str)
            and bool(row.get("player_statement"))
        )
        row.setdefault("thread_status", "open" if is_question else "not_applicable")
        row.setdefault("resolved_at", None)
        row.setdefault("response_ref", None)
        if str(row.get("scene_session_ref")) == ref and row.get("thread_status") == "open":
            row["thread_status"] = "abandoned_with_scene_close"
            row["resolved_at"] = at
            changed += 1
        rows.append(row)
    if changed:
        open_rows = [row for row in rows if row.get("thread_status") == "open"]
        closed_rows = [row for row in rows if row.get("thread_status") != "open"]
        ledger["attempts"] = open_rows + closed_rows[-INTERACTION_CLOSED_HISTORY_LIMIT:]
        _put(writer, INTERACTION_LEDGER_PATH, ledger)
    return changed

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
    abandoned = abandon_session_questions(writer, session_ref, at=at)
    closed = close_scene_session(writer, at=at, reason=reason)
    return {
        "session_ref": session_ref,
        "close_reason": reason,
        "abandoned_question_count": abandoned,
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
        "purpose": "bounded recent attributed scene history; statements remain attributed speech rather than objective world truth",
        "total_recorded": 0,
        "latest_period_ref": None,
        "recent": [],
    }


def recent_scene_history(reader: Any, *, limit: int = 8) -> list[dict[str, Any]]:
    head = _history_head(reader)
    rows = head.get("recent", []) if isinstance(head.get("recent"), list) else []
    bounded = max(1, min(int(limit), HISTORY_HEAD_LIMIT))
    return [copy.deepcopy(dict(row)) for row in rows[-bounded:] if isinstance(row, Mapping)]


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
    question_ref = None
    if resolves_question_ref is not None:
        question_ref = _safe_ref(resolves_question_ref, "resolves_question_ref")
        if question_ref not in set(str(x) for x in active.get("open_question_refs", []) if isinstance(x, str)):
            raise ValueError("scene response may resolve only an open question in the active session")
    speech_ref = _speech_ref(surface_digest, speaker_ref, statement, at)
    row = {
        "speech_ref": speech_ref,
        "at": at,
        "session_ref": actual_session_ref,
        "speaker_ref": speaker_ref,
        "speech_kind": speech_kind,
        "statement": statement,
        "basis_refs": basis,
        "resolves_question_ref": question_ref,
        "truth_status": "attributed_statement",
        "authority": False,
        "mechanical_consequence_authority": False,
    }

    head = _history_head(writer)
    recent = [dict(x) for x in head.get("recent", []) if isinstance(x, Mapping)]
    recent_duplicate = any(str(x.get("speech_ref")) == speech_ref for x in recent)
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
    duplicate = any(str(x.get("speech_ref")) == speech_ref for x in records)
    if duplicate:
        return copy.deepcopy(row)
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
    records.append(copy.deepcopy(row))
    shard["records"] = records
    if not recent_duplicate:
        recent.append(copy.deepcopy(row))
        head["total_recorded"] = int(head.get("total_recorded", 0)) + 1
    head["latest_period_ref"] = period_ref
    head["recent"] = recent[-HISTORY_HEAD_LIMIT:]
    _put(writer, history_period_path(period_ref), shard)
    _put(writer, HISTORY_HEAD_PATH, head)
    touch_active_scene(writer, at=at, session_ref=actual_session_ref)
    if question_ref is not None:
        resolve_open_question(writer, question_ref, at=at)
    return copy.deepcopy(row)


__all__ = [
    "ACTIVE_SESSION_PATH", "CLOSE_REASONS", "HISTORY_HEAD_PATH", "INTERACTION_CLOSED_HISTORY_LIMIT", "SESSION_KINDS", "SPEECH_KINDS",
    "abandon_session_questions", "active_scene_session", "attach_open_question", "close_active_scene", "close_scene_session", "history_period_path",
    "history_period_ref", "inspect_scene_history", "recent_scene_history", "record_attributed_speech",
    "resolve_open_question", "scene_session_projection", "start_scene_session", "touch_active_scene",
]

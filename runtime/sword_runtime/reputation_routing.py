"""Identity-safe routing for reputation subjects and audience profiles.

``state/reputation/index.json`` is authority:false.  Its subject map accelerates
lookup but cannot decide which exact reputation subject is being mutated.
Likewise, an exact subject's audience-profile path is a routing handle; the
profile document still has to name the same subject and audience before a
write can use it.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any, Callable

_LEGACY_SAFE_REF = re.compile(r"[A-Za-z0-9_.:-]{1,256}")


def _legacy_slug(ref: str) -> str:
    return ref.replace(".", "-").replace("_", "-").replace(":", "-")


def reputation_subject_path(subject_ref: str) -> str:
    if not isinstance(subject_ref, str) or not subject_ref or len(subject_ref) > 512 or "\x00" in subject_ref:
        raise ValueError("invalid reputation subject ref")
    stem = re.sub(r"[^A-Za-z0-9-]+", "-", subject_ref).strip("-")[:64] or "subject"
    digest = hashlib.sha256(subject_ref.encode("utf-8")).hexdigest()[:16]
    return f"state/reputation/subjects/{stem}--{digest}.json"


def reputation_profile_path(subject_ref: str, audience_ref: str) -> str:
    for value, label in ((subject_ref, "subject"), (audience_ref, "audience")):
        if not isinstance(value, str) or not value or len(value) > 512 or "\x00" in value:
            raise ValueError(f"invalid reputation {label} ref")
    stem_subject = re.sub(r"[^A-Za-z0-9-]+", "-", subject_ref).strip("-")[:40] or "subject"
    stem_audience = re.sub(r"[^A-Za-z0-9-]+", "-", audience_ref).strip("-")[:40] or "audience"
    digest = hashlib.sha256(f"{subject_ref}\0{audience_ref}".encode("utf-8")).hexdigest()[:16]
    return f"state/reputation/audiences/{stem_subject}--{stem_audience}--{digest}.json"


def resolve_reputation_subject(
    read_optional: Callable[[str], Any],
    index: Mapping[str, Any],
    subject_ref: str,
) -> tuple[str, Mapping[str, Any]] | None:
    canonical = reputation_subject_path(subject_ref)
    routes = index.get("subjects", {}) if isinstance(index.get("subjects"), Mapping) else {}
    routed = routes.get(subject_ref) if isinstance(routes, Mapping) else None
    candidates: list[str] = []
    if isinstance(routed, str) and routed:
        candidates.append(routed)
    if _LEGACY_SAFE_REF.fullmatch(subject_ref):
        # Authored baseline subjects historically used the exact safe ref as
        # the filename, while runtime-created subjects used the hyphen slug.
        candidates.append(f"state/reputation/subjects/{subject_ref}.json")
        candidates.append(f"state/reputation/subjects/{_legacy_slug(subject_ref)}.json")
    candidates.append(canonical)
    seen: set[str] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        doc = read_optional(path)
        if not isinstance(doc, Mapping):
            continue
        if str(doc.get("schema", "")) != "reputation-subject" or str(doc.get("subject_id", "")) != subject_ref:
            continue
        return path, doc
    return None


def resolve_reputation_profile(
    read_optional: Callable[[str], Any],
    subject: Mapping[str, Any],
    subject_ref: str,
    audience_ref: str,
) -> tuple[str, Mapping[str, Any]] | None:
    canonical = reputation_profile_path(subject_ref, audience_ref)
    routes = subject.get("audience_profiles", {}) if isinstance(subject.get("audience_profiles"), Mapping) else {}
    routed = routes.get(audience_ref) if isinstance(routes, Mapping) else None
    candidates: list[str] = []
    if isinstance(routed, str) and routed:
        candidates.append(routed)
    if _LEGACY_SAFE_REF.fullmatch(subject_ref) and _LEGACY_SAFE_REF.fullmatch(audience_ref):
        candidates.append(
            f"state/reputation/audiences/{subject_ref}--{audience_ref}.json"
        )
        candidates.append(
            f"state/reputation/audiences/{_legacy_slug(subject_ref)}--{_legacy_slug(audience_ref)}.json"
        )
    candidates.append(canonical)
    seen: set[str] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        doc = read_optional(path)
        if not isinstance(doc, Mapping):
            continue
        if str(doc.get("schema", "")) != "reputation-audience-profile":
            continue
        if str(doc.get("subject_id", "")) != subject_ref or str(doc.get("audience_id", "")) != audience_ref:
            continue
        return path, doc
    return None

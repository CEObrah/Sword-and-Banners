"""Transport-independent preview attestation security.

The production MCP server and core release tests use these same helpers.  This
module deliberately does not import the optional MCP transport package.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Optional, Protocol

from sword_runtime.commands import CommandEnvelope

_PREVIEW_ATTESTATION_TTL_SECONDS = 300
_PREVIEW_ATTESTATION_CLOCK_SKEW_SECONDS = 60
_MAX_PREVIEW_ATTESTATION_BYTES = 1024


class _PreviewSecretOwner(Protocol):
    preview_secret: str


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    if not value or len(value) > _MAX_PREVIEW_ATTESTATION_BYTES:
        raise ValueError("preview attestation segment is invalid")
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def _preview_attestation(
    command: CommandEnvelope,
    settings: _PreviewSecretOwner,
    *,
    now: Optional[int] = None,
) -> str:
    issued_at = int(time.time()) if now is None else now
    payload = json.dumps(
        {
            "command_sha256": command.digest,
            "expires_at": issued_at + _PREVIEW_ATTESTATION_TTL_SECONDS,
            "version": 1,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    signature = hmac.new(
        settings.preview_secret.encode("ascii"),
        payload,
        hashlib.sha256,
    ).digest()
    return _b64url_encode(payload) + "." + _b64url_encode(signature)


def _verify_preview_attestation(
    command: CommandEnvelope,
    attestation: object,
    settings: _PreviewSecretOwner,
    *,
    now: Optional[int] = None,
) -> bool:
    if (
        not isinstance(attestation, str)
        or not attestation
        or len(attestation) > _MAX_PREVIEW_ATTESTATION_BYTES
        or attestation.count(".") != 1
    ):
        return False
    try:
        payload_part, signature_part = attestation.split(".", 1)
        payload = _b64url_decode(payload_part)
        signature = _b64url_decode(signature_part)
        expected = hmac.new(
            settings.preview_secret.encode("ascii"),
            payload,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected):
            return False
        record = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(record, dict) or set(record) != {
        "command_sha256",
        "expires_at",
        "version",
    }:
        return False
    expires_at = record.get("expires_at")
    current = int(time.time()) if now is None else now
    earliest_valid_expiry = current - _PREVIEW_ATTESTATION_CLOCK_SKEW_SECONDS
    latest_valid_expiry = (
        current
        + _PREVIEW_ATTESTATION_TTL_SECONDS
        + _PREVIEW_ATTESTATION_CLOCK_SKEW_SECONDS
    )
    return (
        record.get("version") == 1
        and record.get("command_sha256") == command.digest
        and isinstance(expires_at, int)
        and not isinstance(expires_at, bool)
        and earliest_valid_expiry <= expires_at <= latest_valid_expiry
    )


__all__ = [
    "_MAX_PREVIEW_ATTESTATION_BYTES",
    "_PREVIEW_ATTESTATION_CLOCK_SKEW_SECONDS",
    "_PREVIEW_ATTESTATION_TTL_SECONDS",
    "_preview_attestation",
    "_verify_preview_attestation",
]

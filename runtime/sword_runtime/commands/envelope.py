"""Strict, hashable command envelope.

An envelope records the player/client request exactly enough for optimistic
concurrency and idempotency checks.  It is not permission to mutate arbitrary
repository paths; reducers and transaction planners determine the write set.
"""

from dataclasses import dataclass
from typing import Any, Mapping

from sword_runtime.tx.canonical import canonical_sha256, freeze_json, thaw_json


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string" % field)
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise ValueError("%s may not contain control line breaks" % field)
    return value


@dataclass(frozen=True)
class CommandEnvelope:
    """One immutable request submitted against an expected world revision."""

    campaign_id: str
    request_id: str
    actor_id: str
    command_type: str
    expected_revision: int
    submitted_at: str
    payload: Mapping[str, Any]
    mode: str = "gameplay"

    SCHEMA = "sword.command"
    VERSION = 1
    MODES = frozenset(("gameplay", "autonomous", "ooc", "maintenance"))

    def __post_init__(self) -> None:
        for name in (
            "campaign_id",
            "request_id",
            "actor_id",
            "command_type",
            "submitted_at",
            "mode",
        ):
            _required_text(getattr(self, name), name)
        if self.mode not in self.MODES:
            raise ValueError("unsupported command mode: %s" % self.mode)
        if isinstance(self.expected_revision, bool) or not isinstance(
            self.expected_revision, int
        ):
            raise TypeError("expected_revision must be an integer")
        if self.expected_revision < 0:
            raise ValueError("expected_revision must be non-negative")
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a JSON object")

        # Freezing prevents a caller from changing the command after its digest
        # has been used for an idempotency decision.
        object.__setattr__(self, "payload", freeze_json(self.payload))

    def to_record(self) -> Mapping[str, Any]:
        return {
            "schema": self.SCHEMA,
            "version": self.VERSION,
            "campaign_id": self.campaign_id,
            "request_id": self.request_id,
            "actor_id": self.actor_id,
            "command_type": self.command_type,
            "expected_revision": self.expected_revision,
            "submitted_at": self.submitted_at,
            "mode": self.mode,
            "payload": thaw_json(self.payload),
        }

    @property
    def semantic_digest(self) -> str:
        """Stable gameplay identity independent of transport retry identity.

        ``request_id`` exists only for transaction idempotency/recovery. Gameplay
        evidence, deterministic seeds, and semantic event IDs must not change when
        the same command is retried under a different transport identifier.
        """
        return canonical_sha256({
            "campaign_id": self.campaign_id,
            "actor_id": self.actor_id,
            "command_type": self.command_type,
            "expected_revision": self.expected_revision,
            "submitted_at": self.submitted_at,
            "mode": self.mode,
            "payload": thaw_json(self.payload),
        })

    @property
    def digest(self) -> str:
        """Request-bound SHA-256 used by preview/transaction idempotency."""

        return canonical_sha256(self.to_record())

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "CommandEnvelope":
        if not isinstance(record, Mapping):
            raise TypeError("command record must be an object")
        allowed = {
            "schema",
            "version",
            "campaign_id",
            "request_id",
            "actor_id",
            "command_type",
            "expected_revision",
            "submitted_at",
            "mode",
            "payload",
        }
        unknown = set(record) - allowed
        if unknown:
            raise ValueError("unknown command fields: %s" % sorted(unknown))
        if record.get("schema") != cls.SCHEMA:
            raise ValueError("unsupported command schema")
        if record.get("version") != cls.VERSION:
            raise ValueError("unsupported command version")
        return cls(
            campaign_id=record.get("campaign_id"),
            request_id=record.get("request_id"),
            actor_id=record.get("actor_id"),
            command_type=record.get("command_type"),
            expected_revision=record.get("expected_revision"),
            submitted_at=record.get("submitted_at"),
            mode=record.get("mode", "gameplay"),
            payload=record.get("payload"),
        )

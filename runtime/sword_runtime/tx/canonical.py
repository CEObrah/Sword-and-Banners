"""Canonical JSON bytes used for hashes, receipts, and deterministic files."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any


def _normalize_json(value: Any, path: str = "$") -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise TypeError(
            "floating-point values are forbidden at %s; use fixed integers or strings"
            % path
        )
    if isinstance(value, Mapping):
        normalized = {}
        keys = list(value)
        if any(not isinstance(key, str) for key in keys):
            raise TypeError("JSON object keys must be strings at %s" % path)
        for key in sorted(keys):
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings at %s" % path)
            normalized[key] = _normalize_json(value[key], "%s.%s" % (path, key))
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            _normalize_json(item, "%s[%d]" % (path, index))
            for index, item in enumerate(value)
        ]
    raise TypeError("unsupported JSON value at %s: %s" % (path, type(value).__name__))


def canonical_json_bytes(value: Any) -> bytes:
    """Encode strict JSON with stable key order, separators, UTF-8, and newline."""

    normalized = _normalize_json(value)
    rendered = json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return rendered.encode("utf-8") + b"\n"


def sha256_bytes(content: bytes) -> str:
    if not isinstance(content, bytes):
        raise TypeError("hash input must be bytes")
    return hashlib.sha256(content).hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def freeze_json(value: Any) -> Any:
    """Validate and recursively freeze a JSON-compatible value."""

    normalized = _normalize_json(value)

    def freeze(item: Any) -> Any:
        if isinstance(item, dict):
            return MappingProxyType({key: freeze(child) for key, child in item.items()})
        if isinstance(item, list):
            return tuple(freeze(child) for child in item)
        return item

    return freeze(normalized)


def thaw_json(value: Any) -> Any:
    """Return ordinary dict/list containers from a frozen JSON value."""

    if isinstance(value, Mapping):
        return {key: thaw_json(child) for key, child in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [thaw_json(child) for child in value]
    return value

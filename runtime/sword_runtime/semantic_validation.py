from __future__ import annotations

from typing import Any, Mapping


def require_int(payload: Mapping[str, Any], key: str, *, minimum: int | None = None, maximum: int | None = None, default: Any = None) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{key} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{key} must be <= {maximum}")
    return value


def require_number(payload: Mapping[str, Any], key: str, *, minimum: float | None = None, maximum: float | None = None, default: Any = None) -> float:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    result = float(value)
    if minimum is not None and result < minimum:
        raise ValueError(f"{key} must be >= {minimum}")
    if maximum is not None and result > maximum:
        raise ValueError(f"{key} must be <= {maximum}")
    return result


def require_text(payload: Mapping[str, Any], key: str, *, allowed: set[str] | None = None, default: Any = None, max_length: int = 256) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be non-empty text")
    if len(value) > max_length:
        raise ValueError(f"{key} is too long")
    if allowed is not None and value not in allowed:
        raise ValueError(f"unsupported {key}: {value}")
    return value


def require_list(payload: Mapping[str, Any], key: str, *, minimum: int = 0, maximum: int = 256) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{key} must be a list")
    out = list(value)
    if len(out) < minimum or len(out) > maximum:
        raise ValueError(f"{key} must contain between {minimum} and {maximum} values")
    return out


def reject_unknown_keys(payload: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError("unknown payload fields: %s" % sorted(unknown))

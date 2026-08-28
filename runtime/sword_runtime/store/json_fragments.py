"""JSON-pointer routing for compact sharded state records.

Owner indexes may route a logical exact record to a JSON object nested inside a
bounded shard using ``path.json#/records/<id>``.  The filesystem owner remains
one ordinary JSON file; the fragment is only a deterministic logical locator.
"""
from __future__ import annotations

from collections.abc import MutableMapping, MutableSequence
from typing import Any


def split_json_fragment(relative_path: object) -> tuple[str, tuple[str, ...]]:
    text = str(relative_path)
    if "#" not in text:
        return text, ()
    base, fragment = text.split("#", 1)
    if not base:
        raise ValueError("JSON fragment route requires a file path")
    if not fragment:
        return base, ()
    if not fragment.startswith("/"):
        raise ValueError("JSON fragment route must use JSON Pointer syntax")
    tokens: list[str] = []
    for raw in fragment[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        tokens.append(token)
    return base, tuple(tokens)


def json_fragment_route(base_path: str, *tokens: object) -> str:
    encoded = []
    for token in tokens:
        text = str(token).replace("~", "~0").replace("/", "~1")
        encoded.append(text)
    if not encoded:
        return base_path
    return f"{base_path}#/" + "/".join(encoded)


def select_json_fragment(value: Any, tokens: tuple[str, ...]) -> Any:
    current = value
    for token in tokens:
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(token)
            current = current[token]
            continue
        if isinstance(current, list):
            try:
                index = int(token)
            except ValueError as exc:
                raise KeyError(token) from exc
            if index < 0 or index >= len(current):
                raise KeyError(token)
            current = current[index]
            continue
        raise KeyError(token)
    return current


def assign_json_fragment(value: Any, tokens: tuple[str, ...], replacement: Any) -> None:
    if not tokens:
        raise ValueError("cannot assign empty JSON fragment")
    current = value
    for token in tokens[:-1]:
        if isinstance(current, MutableMapping):
            if token not in current:
                current[token] = {}
            current = current[token]
            continue
        if isinstance(current, MutableSequence):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise KeyError(token) from exc
            continue
        raise KeyError(token)
    leaf = tokens[-1]
    if isinstance(current, MutableMapping):
        current[leaf] = replacement
        return
    if isinstance(current, MutableSequence):
        try:
            current[int(leaf)] = replacement
        except (ValueError, IndexError) as exc:
            raise KeyError(leaf) from exc
        return
    raise KeyError(leaf)


def delete_json_fragment(value: Any, tokens: tuple[str, ...]) -> None:
    if not tokens:
        raise ValueError("cannot delete empty JSON fragment")
    current = value
    for token in tokens[:-1]:
        if isinstance(current, dict):
            if token not in current:
                raise KeyError(token)
            current = current[token]
            continue
        if isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise KeyError(token) from exc
            continue
        raise KeyError(token)
    leaf = tokens[-1]
    if isinstance(current, dict):
        if leaf not in current:
            raise KeyError(leaf)
        del current[leaf]
        return
    if isinstance(current, list):
        try:
            del current[int(leaf)]
        except (ValueError, IndexError) as exc:
            raise KeyError(leaf) from exc
        return
    raise KeyError(leaf)

from __future__ import annotations

import json
import re


_LANCE_TOKEN = re.compile(r"(?<![a-z])lance(?:r|s)?(?![a-z])", re.IGNORECASE)
_RED_LANCE = re.compile(r"red[ _.-]+lance", re.IGNORECASE)


def _mechanical_lance_text(text: str) -> bool:
    if not _LANCE_TOKEN.search(text):
        return False
    # Red Lance is an organization/proper name, not an equipment semantic.
    stripped = _RED_LANCE.sub("", text)
    return bool(_LANCE_TOKEN.search(stripped))


def _walk(value, *, path: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if _mechanical_lance_text(key_text):
                yield f"{child_path} [key]"
            yield from _walk(child, path=child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, path=f"{path}[{index}]")
    elif isinstance(value, str) and _mechanical_lance_text(value):
        yield f"{path} [value={value!r}]"


def test_persisted_json_has_no_mechanical_lance_terminology(campaign):
    """Lance is not an equipment semantic; Red Lance remains a proper name."""
    problems: list[str] = []
    for root_name in ("game", "state"):
        root = campaign / root_name
        for file_path in sorted(root.rglob("*.json")):
            document = json.loads(file_path.read_text(encoding="utf-8"))
            for object_path in _walk(document):
                problems.append(f"{file_path.relative_to(campaign)}:{object_path}")
    assert not problems, "mechanical lance terminology remains; use spear semantics:\n" + "\n".join(problems)

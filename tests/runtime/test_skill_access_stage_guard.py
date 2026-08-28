from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHOICES = ROOT / "plugins" / "sword-and-banners" / "skill" / "sword-and-banners-game-master" / "references" / "choices.md"


def test_choices_require_access_before_direct_npc_interaction() -> None:
    choices = CHOICES.read_text(encoding="utf-8")
    assert "## Access-stage guard for people" in choices
    assert "must not collapse `seek/contact` and `speak/press/petition`" in choices
    assert "`nearby_people`" in choices
    assert "do not narrate face-to-face speech" in choices
    assert "refresh context after the access or routing step" in choices

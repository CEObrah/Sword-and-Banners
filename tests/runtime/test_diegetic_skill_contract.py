from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins" / "sword-and-banners" / "skills" / "sword-and-banners-game-master"


def _text(name: str) -> str:
    return (SKILL / name).read_text(encoding="utf-8")


def test_narration_has_diegetic_firewall_and_training_translation() -> None:
    narration = _text("references/narration.md")
    assert "## Diegetic firewall" in narration
    assert "## Translate mechanics into lived consequence" in narration
    assert "## Use authored places as real spaces" in narration
    assert "## Quiet time and non-events" in narration
    assert "### Arrival handoffs" in narration
    assert "history of a software correction" in narration
    assert "no whole-number skill increase is not automatically pointless" in narration
    assert "routine-training ceiling" in narration


def test_choices_do_not_reoffer_setup_or_leak_implementation() -> None:
    choices = _text("references/choices.md")
    assert "## Arrival and stale-projection handoffs" in choices
    assert "scene.continuity_anchor" in choices
    assert "## Do not re-offer completed setup" in choices
    assert "## Keep implementation state out of IC choices" in choices
    assert "fictionally worse but executable workaround" in choices
    assert "separate OOC note" in choices

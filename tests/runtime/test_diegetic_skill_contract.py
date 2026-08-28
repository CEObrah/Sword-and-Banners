from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "plugins" / "sword-and-banners" / "sword-and-banners-skill" / "sword-and-banners-game-master"


def _text(name: str) -> str:
    return (SKILL / name).read_text(encoding="utf-8")


def test_narration_has_diegetic_firewall_and_training_translation() -> None:
    narration = _text("references/narration.md")
    assert "## Diegetic firewall" in narration
    assert "## Translate mechanics into lived consequence" in narration
    assert "## Use authored places as real spaces" in narration
    assert "## Quiet time and non-events" in narration
    assert "### Arrival handoffs" in narration
    assert "### Player action is not world reaction" in narration
    assert "### Standing policies and waiting" in narration
    assert "history of a software correction" in narration
    assert "no whole-number skill increase is not automatically pointless" in narration
    assert "routine-training ceiling" in narration
    assert "Do not narrate the hidden rationale for permissions" in narration
    assert "The narrator must not explain why the GM chose that actor" in narration


def test_scene_craft_keeps_authority_rationale_out_of_narrator_voice() -> None:
    scene_craft = _text("references/scene-craft.md")
    assert "The GM's internal reason for respecting an authority or agency boundary is not itself scene content" in scene_craft
    assert "If the reason is genuinely player-visible and matters" in scene_craft
    assert "The narrator does not explain the hidden rationale for authority" in scene_craft


def test_choices_do_not_reoffer_setup_or_leak_implementation() -> None:
    choices = _text("references/choices.md")
    assert "## Arrival and stale-projection handoffs" in choices
    assert "## Standing-policy choices" in choices
    assert "Do not offer two choices whose practical effect is the same waiting posture" in choices
    assert "scene.continuity_anchor" in choices
    assert "## Do not re-offer completed setup" in choices
    assert "## Keep implementation state out of IC choices" in choices
    assert "fictionally worse but executable workaround" in choices
    assert "separate OOC note" in choices

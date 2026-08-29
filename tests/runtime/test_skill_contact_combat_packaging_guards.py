from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = ROOT / "plugins" / "sword-and-banners" / "skill" / "sword-and-banners-game-master"
COMBAT = SKILL_ROOT / "references" / "combat-and-warfare.md"
WAITING = SKILL_ROOT / "references" / "waiting-and-handoffs.md"
GITHUB = SKILL_ROOT / "references" / "github-development.md"


def test_combat_narration_is_scene_first_without_cinematic_fabrication() -> None:
    combat = COMBAT.read_text(encoding="utf-8")
    assert "## Battlefield scene, not accounting dump" in combat
    assert "primary IC presentation a grounded battlefield scene" in combat
    assert "what happened, why it happened, what materially changed, and what Wei now faces" in combat
    assert "Do not lead with HP, casualty totals, readiness percentages" in combat
    assert "Scene-first does not authorize cinematic invention" in combat
    assert "End a resolved combat beat on the **changed battlefield**" in combat


def test_declared_command_contact_wait_is_not_reprompted_after_zero_time_attempt() -> None:
    waiting = WAITING.read_text(encoding="utf-8")
    assert "## Declared command-contact waits are one standing objective" in waiting
    assert "commit the lawful contact/message attempt as its own zero-time interaction action" in waiting
    assert "Do not stop after the attempt merely to ask whether Wei wants to wait" in waiting
    assert "does not satisfy the declared objective" in waiting
    assert "diagnose the missing lifecycle" in waiting


def test_skill_packages_can_only_follow_committed_github_source() -> None:
    github = GITHUB.read_text(encoding="utf-8")
    assert "## Skill packaging is GitHub-first" in github
    assert "only then build `skill.zip` from that exact committed tree" in github
    assert "Never hand-edit or package a Skill ZIP ahead of GitHub" in github
    assert "must not contain Skill content that has not first been committed to GitHub" in github

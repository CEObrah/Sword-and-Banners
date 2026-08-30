from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WAITING = (
    ROOT
    / "plugins/sword-and-banners/skill/sword-and-banners-game-master/references/waiting-and-handoffs.md"
)


def test_scheduled_war_council_is_a_causal_wait_not_player_registration() -> None:
    text = WAITING.read_text(encoding="utf-8")

    assert "## Scheduled councils and pre-convening projections" in text
    assert "not** as a claim that Tang Wei personally needs to register" in text
    assert "Do **not** use `interaction_action` merely to \"register\"" in text
    assert "Use the supported `advance_time` path" in text
    assert "Never narrate the council as underway before that event commits" in text

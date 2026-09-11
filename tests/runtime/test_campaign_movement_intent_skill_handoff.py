from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WAITING = (
    ROOT
    / "plugins/sword-and-banners/skill/sword-and-banners-game-master/references/waiting-and-handoffs.md"
)


def test_declared_war_movement_intent_survives_command_delivery_handoffs() -> None:
    text = WAITING.read_text(encoding="utf-8")

    assert "## Declared campaign movement survives administrative handoffs" in text
    assert "Distinguish `wait for orders`" in text
    assert "use the real travel/movement consequence owner" in text
    assert "Do **not** loop back into `seek_contact`" in text
    assert "A command that has been delivered but not yet physically executed is not progress" in text
    assert "do not issue a second march to a destination already physically reached" in text

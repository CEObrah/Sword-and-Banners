from pathlib import Path


CHOICES = Path("plugins/sword-and-banners/skill/sword-and-banners-game-master/references/choices.md")


def test_choices_contract_forbids_prose_created_dead_ends():
    text = CHOICES.read_text(encoding="utf-8")
    assert "## Narrated-fork guard" in text
    assert "Never manufacture decision language merely for drama and then stop without options." in text
    assert "if the player's current message already supplied the next action" in text
    assert "Never use `unresolved_decision: null` to excuse a prose-created dead end." in text

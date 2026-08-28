from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = ROOT / "plugins/sword-and-banners/skill/sword-and-banners-game-master/references/scene-playbook.md"


def test_campaign_command_scenes_use_concrete_march_planning_substrate():
    text = PLAYBOOK.read_text()
    assert "march_planning" in text
    assert "route capacity" in text
    assert "shared bottleneck" in text
    assert "troop-clearance floor" in text
    assert "not an assigned route" in text
    assert "Do not invent wagon counts" in text
    assert "vague abstractions" in text

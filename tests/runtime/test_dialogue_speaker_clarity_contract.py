from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCENE_CONTRACT = ROOT / "plugins/sword-and-banners/skill/sword-and-banners-game-master/references/scene-contract.md"
NARRATION = ROOT / "plugins/sword-and-banners/skill/sword-and-banners-game-master/references/narration.md"


def test_crowded_dialogue_requires_local_speaker_attribution():
    scene = SCENE_CONTRACT.read_text()
    narration = NARRATION.read_text()
    assert "every speaker change must be locally unmistakable" in scene
    assert "same paragraph" in scene
    assert "Do not rely on alternating quotation marks" in scene
    assert "speaker audit" in scene
    assert "three or more plausible speakers" in narration
    assert "Never rely on quote alternation" in narration

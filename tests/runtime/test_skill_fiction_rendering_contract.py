from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCENE_CRAFT = ROOT / 'plugins/sword-and-banners/skill/sword-and-banners-game-master/references/scene-craft.md'


def test_scene_craft_enforces_film_and_novel_rendering():
    text = SCENE_CRAFT.read_text(encoding='utf-8').lower()

    assert 'film-and-novel rendering gate' in text
    assert 'movie/book test' in text
    assert 'structured-state paraphrase' in text
    assert 'npc dialogue must not be used to verbalize runtime disclaimers' in text
    assert 'show the report arriving' in text
    assert "the narrator is not an analyst standing beside the scene" in text
    assert "if a paragraph's main purpose is to explain state semantics" in text
    assert 'do not append routine ooc qa to a clean playable ic scene' in text

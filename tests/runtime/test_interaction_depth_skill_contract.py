from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCENE_CONTRACT = ROOT / "plugins/sword-and-banners/skill/sword-and-banners-game-master/references/scene-contract.md"


def test_general_interaction_contract_requires_distinct_conversational_work():
    text = SCENE_CONTRACT.read_text(encoding="utf-8")

    assert "## Interaction depth and differentiation" in text
    assert "distinct conversational jobs" in text
    assert "two to four people" in text
    assert "professional_lenses" in text
    assert "absence of personality cues is **not** a reason to make everyone sound alike" in text
    assert "uncertainty as playable material" in text
    assert "Runtime summaries are briefing material for the GM, never dialogue scripts" in text


def test_interaction_contract_preserves_common_ground_instead_of_schema_checklists():
    text = SCENE_CONTRACT.read_text(encoding="utf-8")

    assert "### Shared premises and motivated questions" in text
    assert "shared premises" in text
    assert "logically entailed by the immediate chronology and position" in text
    assert "Do not use dialogue to audit runtime fields" in text
    assert "interrogatory checklist" in text
    assert "do not make a commander ask whether battle contact is confirmed" in text
    assert "The shared premise is that the field armies have not yet met the enemy" in text
    assert "Avoid the **analytic chorus**" in text
    assert "Do not manufacture a question solely to give a speaker a conversational job" in text


def test_interaction_depth_contract_still_preserves_hard_truth_boundary():
    text = SCENE_CONTRACT.read_text(encoding="utf-8")

    assert "never create knowledge, motive, authority, or outcome" in text
    assert "new world truth still requires lawful evidence or runtime authority" in text
    assert "issuing a new binding order" in text
    assert "revealing new secret factual information" in text

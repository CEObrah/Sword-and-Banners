from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCENE_CONTRACT = ROOT / "plugins/sword-and-banners/skill/sword-and-banners-game-master/references/scene-contract.md"


def test_general_interaction_contract_uses_expertise_without_turn_quotas():
    text = SCENE_CONTRACT.read_text(encoding="utf-8")

    assert "## Interaction depth and differentiation" in text
    assert "meaningful conversational moves" in text
    assert "not as turns allocated across the attendee list" in text
    assert "professional_lenses" in text
    assert "Expertise is a **performance lens, not a speaking quota**" in text
    assert "absence of personality cues is **not** a reason to make everyone sound alike" in text
    assert "rank, generation, education" in text
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


def test_interaction_contract_rejects_round_robin_and_analytic_chorus():
    text = SCENE_CONTRACT.read_text(encoding="utf-8")

    assert "### Dialogue choreography" in text
    assert "**Information follows the interaction.**" in text
    assert "The attendee list is **not a speaking queue**" in text
    assert "Do not write round-robin dialogue" in text
    assert "Uneven participation is expected" in text
    assert "The same speaker may stay active across follow-up questions" in text
    assert "Avoid the **analytic chorus**" in text
    assert "fact -> caveat -> implication -> narrator significance" in text
    assert "respond to the **meaning** of what was said" in text
    assert "Short answers, fragments, hesitation, interruption, silence" in text
    assert "Do not manufacture a question or objection solely to give a speaker a conversational job" in text


def test_interaction_contract_does_not_narrate_its_own_dialogue():
    text = SCENE_CONTRACT.read_text(encoding="utf-8")

    assert "### Do not narrate the narration" in text
    assert "Do not explain that your own dialogue worked" in text
    assert "that answer matters more" in text
    assert "the discussion reaches a natural stopping point" in text
    assert "Let significance appear through what people do next" in text
    assert "Meeting transitions should also be enacted rather than announced" in text
    assert "Do not end a topic merely because the narrator declares that the matter is settled" in text


def test_interaction_contract_rejects_authorial_negative_contrast():
    text = SCENE_CONTRACT.read_text(encoding="utf-8")

    assert "Do not narrate **authorial negative contrast**" in text
    assert "Mou Gou does not ask Shou Hei Kun to read the roster back" in text
    assert "he does not need to explain the structure" in text
    assert "there is no need to repeat the figures" in text
    assert "Delete the contrast and show only what actually happens" in text
    assert "Negative wording remains valid when the absence itself is an observable in-world event" in text
    assert "whether Wei can perceive the absence as part of the world" in text


def test_interaction_depth_contract_still_preserves_hard_truth_boundary():
    text = SCENE_CONTRACT.read_text(encoding="utf-8")

    assert "never create knowledge, motive, authority, or outcome" in text
    assert "new world truth still requires lawful evidence or runtime authority" in text
    assert "issuing a new binding order" in text
    assert "revealing new secret factual information" in text

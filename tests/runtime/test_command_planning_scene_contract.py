from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK = ROOT / "plugins/sword-and-banners/skill/sword-and-banners-game-master/references/scene-playbook.md"
SCENE_CONTRACT = ROOT / "plugins/sword-and-banners/skill/sword-and-banners-game-master/references/scene-contract.md"


def test_campaign_command_scenes_establish_campaign_scheme_before_route_minutiae():
    text = PLAYBOOK.read_text()
    assert "Campaign scheme before march detail" in text
    assert "march_planning.campaign_scheme" in text
    assert "operational purpose and primary objective" in text
    assert "campaign theater/region" in text
    assert "strategic anchor" in text
    assert "how many current campaign objectives/axes" in text
    assert "which intact commands and commanders are proposed for each objective" in text
    assert "which command remains strategic reserve" in text
    assert "what completing the current campaign phase means" in text
    assert "Political war termination" not in text  # prose should use ordinary wording, not a hard-coded proper label
    assert "political war end state" in text
    assert "staff plan, not yet a movement order" in text
    assert "Do not reduce a campaign to `advance toward Sanyou`" in text


def test_regional_campaign_scenes_do_not_collapse_anchor_city_into_whole_theater():
    text = PLAYBOOK.read_text()
    assert "Do not confuse a campaign region with its strategic anchor" in text
    assert "campaign_scope_kind" in text
    assert "regional_campaign" in text
    assert "one important site inside that region" in text
    assert "control of the strategic anchor" in text or "Capturing or approaching the anchor" in text
    assert "Sanyou Region" in text
    assert "city of Sanyou and the whole campaign" in text
    assert "Do not invent Kourou, Kinrikan" in text


def test_command_dialogue_rejects_database_shaped_target_language():
    text = PLAYBOOK.read_text()
    assert "Do not make officers speak in schema language" in text
    assert "`Sanyou is named`" in text
    assert "`only Sanyou is fixed`" in text
    assert "`the record names Sanyou`" in text
    assert "the dialogue must not expose that the GM is reasoning from a field name" in text


def test_campaign_command_scenes_use_concrete_march_planning_substrate_after_scheme():
    text = PLAYBOOK.read_text()
    assert "march_planning" in text
    assert "Route capacity" in text
    assert "shared bottleneck" in text
    assert "troop_clearance_days_floor" in text
    assert "not an assigned route" in text
    assert "Do not invent wagon counts" in text
    assert "campaign theater and operational end state" in text
    assert "Do not begin by asking individual commanders where they want to be used" in text
    assert "vague abstractions" in text


def test_command_scene_uses_full_recursive_strength_without_singling_out_player_private_troops():
    text = SCENE_CONTRACT.read_text()
    assert "full recursive command span" in text
    assert "Do not single Tang Wei out as the only commander with private troops" in text
    assert "State-owned, House-owned, and other non-state bodies remain separately owned" in text


def test_command_scene_does_not_append_repeated_authority_boilerplate_after_concrete_answer():
    text = SCENE_CONTRACT.read_text()
    assert "Do not append **authority boilerplate** after a concrete military answer" in text
    assert "mention it again only when it changes the immediate requested action" in text
    assert "the disposition is mine to settle, but crossing is not" in text
    assert "End on the actual assignment" in text

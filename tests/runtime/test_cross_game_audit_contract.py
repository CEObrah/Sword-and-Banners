from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def test_confirmed_systemic_defect_requires_analogous_cross_game_audit_before_global_closure():
    text = (ROOT / "plugins/sword-and-banners/skill/sword-and-banners-game-master/references/ooc-dev.md").read_text(encoding="utf-8")
    assert "## Cross-game analogous-defect rule" in text
    assert "P0, P1, or a systemic/repeating P2" in text
    assert "Before calling that defect **globally fixed**" in text
    assert "audit the analogous subsystem in the other RPG" in text
    assert "without creating runtime imports" in text

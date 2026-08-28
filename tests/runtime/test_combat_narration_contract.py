from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMBAT = ROOT / "plugins/sword-and-banners/sword-and-banners-skill/sword-and-banners-game-master/references/combat-and-warfare.md"


def test_combat_narration_requires_aim_contact_and_confirmed_consequence_separation():
    text = COMBAT.read_text(encoding="utf-8")
    assert "Distinguish **aim**, **contact**, and **confirmed consequence**" in text
    assert "not valid to say the wrist was severed unless" in text


def test_multi_attacker_narration_exposes_shared_defensive_commitment_not_fresh_duels():
    text = COMBAT.read_text(encoding="utf-8")
    assert "shared body state" in text
    assert "cumulative whole-body active-defense load" in text
    assert "distinct attackers inside that recovery window" in text
    assert "passive armor" in text
    assert "Never narrate a second pristine defense" in text
    for term in ("weight", "blade", "shield", "second attacker", "grapple", "fall", "obstacle"):
        assert term in text


def test_projectile_and_near_simultaneous_causality_are_explicit_narration_rules():
    text = COMBAT.read_text(encoding="utf-8")
    assert "shooter is incapacitated after release" in text
    assert "arrow or bolt still flies" in text
    assert "Near-simultaneous contacts may both land" in text


def test_structural_injury_physiology_and_mass_hero_facts_are_trace_bound():
    text = COMBAT.read_text(encoding="utf-8")
    for term in ("tendon", "major vessel", "fractured bone", "penetrated lung", "blood-loss progression", "shock", "loss of consciousness"):
        assert term in text
    assert "bounded local-contact trace" in text
    assert "tactical gate/bridge seizure" in text
    assert "fictional troop-equivalent bodies" in text

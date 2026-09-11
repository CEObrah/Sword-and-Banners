from __future__ import annotations

import json
from pathlib import Path

from conftest import activate_operation, execute, execute_internal
from sword_runtime.command_units import recursive_refs
from sword_runtime.support_tasks import FORBIDDEN_PERMANENT_SUPPORT_ROLES
from test_operational_battlefield import _co_locate_formations_direct, _operation
from test_warfare import create_local_scale_pair


def _owners(campaign: Path) -> dict[str, str]:
    return json.loads((campaign / "state/index/owner-index.json").read_text())["owners"]


def _formation(campaign: Path, ref: str) -> dict:
    return json.loads((campaign / _owners(campaign)[ref]).read_text())


def _group(campaign: Path, ref: str) -> dict:
    return json.loads((campaign / f"state/cmd/command-groups/{ref}.json").read_text())


def test_mass_battle_registry_has_no_permanent_medic_or_support_troop_castes(campaign):
    """Sword scale keeps support expertise separate from permanent combat roles.

    Medicine, signal, logistics, engineering, and similar capabilities may drive
    temporary duties. They may not silently remove a permanent slice of an army
    from combat merely because a person/cohort has that profession or skill.
    """
    profiles = json.loads((campaign / "game/data/mil/combat-role-profiles.json").read_text())
    roles = set(profiles["profiles"])
    assert roles.isdisjoint(FORBIDDEN_PERMANENT_SUPPORT_ROLES)
    assert "temporary duties" in profiles["authority"].lower()

    duties = json.loads((campaign / "game/data/mechanics/unit-duties.json").read_text())
    rule = duties["rules"]["composition_rule"].lower()
    for label in ("medical", "signal", "engineer"):
        assert label in rule
    assert "no permanent" in rule


def test_200k_battle_uses_bounded_frontage_not_200k_individual_attack_macros(campaign):
    """100k vs 100k must remain a formation fight, not exact-person spam.

    This is the mass-scale analogue of the Shinobi spear/knee failure: hundreds
    of thousands of represented soldiers cannot each emit a synchronized exact
    target/defense action. Only physically expressible frontage contributes to
    the score, while casualties remain conserved against the aggregate owners.
    """
    attacker, defender, operation_ref = create_local_scale_pair(campaign, "crossgame_fair_200k", 100000)

    before = {ref: _formation(campaign, ref) for ref in (attacker, defender)}
    for formation in before.values():
        assert int(formation["personnel"]) == 100000
        assert set(formation.get("composition", {})).isdisjoint(FORBIDDEN_PERMANENT_SUPPORT_ROLES)

    result = execute_internal(campaign, "battle_resolve", {
        "attacker_formation_refs": [attacker],
        "defender_formation_refs": [defender],
        "operation_ref": operation_ref,
        "objective": "large-scale cross-game fairness acceptance",
    }).receipt.result

    assert result["represented_personnel"] == 200000
    assert result["combat_information"]["scale"] == "formation_battle"

    for ref in (attacker, defender):
        score = result["score_breakdown"][ref]
        effective_bodies = int(score["effective_bodies_milli"]) / 1000.0
        # Frontage + bounded depth support may involve many thousands, but a
        # 100,000-person formation cannot express all 100,000 as simultaneous
        # melee contacts. This is the mass-battle counterpart to body/lane blocking.
        assert 0 < effective_bodies < 50000, (ref, effective_bodies)
        assert 0 <= int(result["casualties"][ref]) <= 100000

    trace = list(result["causal_trace"])
    assert len(trace) <= 16
    kinds = {str(row.get("kind")) for row in trace}
    assert {"contact_geometry", "formation_contact", "casualty_pressure", "battle_result"}.issubset(kinds)

    # Aggregate battle traces may describe representative contact pressure, but
    # must not manufacture one exact anatomy/attack macro per anonymous soldier.
    forbidden_exact_fields = {
        "aim_structure", "aim_side", "defense_method", "active_defense_load_after",
        "active_defense_load_before", "target_ref",
    }
    assert not any(forbidden_exact_fields & set(row) for row in trace)
    assert not any((campaign / "state").rglob("soldier-*.json"))


def test_tang_wei_9500_vs_40000_front_distributes_the_coarse_enemy_instead_of_dogpiling(campaign):
    """Campaign-shaped scale: 9,500 under Wei versus one 40,000-man coarse body.

    The 40k owner may be coarse storage, but operational geometry must distribute
    its conserved frontage. It cannot attack each 500-man Tang leaf as if all
    40,000 enemy bodies were simultaneously present in every local lane.
    """
    leaves, _groups = recursive_refs(lambda ref: _group(campaign, ref), "cmdgrp.tang_wei.field_army")
    tang_leaves = sorted(leaves)
    assert len(tang_leaves) == 19
    assert sum(int(_formation(campaign, ref)["personnel"]) for ref in tang_leaves) == 9500

    enemy = "formation_wei_reconstitution"
    assert int(_formation(campaign, enemy)["personnel"]) == 40000
    location = "loc_wei_regional_02"
    _co_locate_formations_direct(campaign, [*tang_leaves, enemy], location)

    operation_ref = activate_operation(
        campaign,
        "operation_crossgame_fair_9500_vs_40000",
        [*tang_leaves, enemy],
        location=location,
    )
    battlefield_ref = "battlefield_crossgame_fair_9500_vs_40000"
    execute(campaign, "battlefield_control", {
        "action": "open",
        "operation_ref": operation_ref,
        "battlefield_ref": battlefield_ref,
        "name": "Cross-game Fairness Front",
    })

    battlefield = _operation(campaign, operation_ref)["battlefields"][battlefield_ref]
    enemy_commitments = battlefield["assignments"][enemy]["sector_commitments_milli"]
    assert len(enemy_commitments) >= 3
    assert sum(enemy_commitments.values()) == 1000

    represented_by_sector = {
        sector_ref: round(40000 * share / 1000)
        for sector_ref, share in enemy_commitments.items()
    }
    assert sum(represented_by_sector.values()) == 40000
    assert max(represented_by_sector.values()) < 40000
    assert all(value > 0 for value in represented_by_sector.values())

    # Every Tang 500-man leaf occupies one local sector. No local sector may
    # implicitly inherit the whole 40,000-man enemy owner.
    for ref in tang_leaves:
        sector_ref = battlefield["assignments"][ref]["sector_ref"]
        assert represented_by_sector[sector_ref] < 40000


def test_100k_spear_reach_advantage_collapses_as_contact_compresses_instead_of_snowballing_forever(campaign):
    """Reach is useful at ordered frontage, not a perpetual free-action engine."""
    from sword_runtime.engine import RepositoryCommandPlanner

    planner = RepositoryCommandPlanner(campaign)
    long_spears = [{
        "count": 100000,
        "melee_reach_m": 2.4,
        "melee_minimum_range_m": 0.65,
    }]
    short_swords = [{
        "count": 100000,
        "melee_reach_m": 0.85,
        "melee_minimum_range_m": 0.10,
    }]

    spear_ordered = planner._combat_reach_factor(long_spears, short_swords, 90, "plain")
    sword_ordered = planner._combat_reach_factor(short_swords, long_spears, 90, "plain")
    spear_compressed = planner._combat_reach_factor(long_spears, short_swords, 25, "fortress")
    sword_compressed = planner._combat_reach_factor(short_swords, long_spears, 25, "fortress")

    assert spear_ordered > 1.0 > sword_ordered
    assert spear_compressed < spear_ordered
    assert sword_compressed > sword_ordered
    assert abs(spear_compressed - 1.0) < abs(spear_ordered - 1.0)
    assert abs(sword_compressed - 1.0) < abs(sword_ordered - 1.0)

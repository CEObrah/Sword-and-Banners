"""Evidence-oriented military service appraisal.

Career merit is an institutional judgment score, not a body-count counter.  The
appraisal deliberately uses facts the battle resolver already owns: assigned
command role, whether the local objective was won, relative force adversity,
casualty stewardship and duration.  Court review remains a separate authority.
"""
from __future__ import annotations

from typing import Any


def battle_service_appraisal(
    *,
    won: bool,
    command_role: str,
    own_personnel_before: int,
    enemy_personnel_before: int,
    own_casualties: int,
    battle_hours: float,
    operational_contact: bool,
) -> dict[str, Any]:
    own = max(1, int(own_personnel_before))
    enemy = max(0, int(enemy_personnel_before))
    casualties = max(0, min(own, int(own_casualties)))
    casualty_fraction = casualties / own
    adversity_ratio = max(0.0, min(3.0, enemy / own))

    outcome_component = 4.0 if won else 1.5
    adversity_component = max(-0.5, min(2.0, (adversity_ratio - 1.0) * 1.8))
    preservation_component = max(-2.5, min(1.5, (0.12 - casualty_fraction) * 10.0))
    endurance_component = min(1.0, max(0.0, float(battle_hours)) / 8.0)
    operational_component = 0.5 if operational_contact else 0.0
    role_factor = 1.0 if str(command_role) == "commander" else 0.78
    raw = (outcome_component + adversity_component + preservation_component + endurance_component + operational_component) * role_factor
    merit = max(1, min(10, int(round(raw))))

    if casualty_fraction >= 0.30:
        stewardship = "severe_losses"
    elif casualty_fraction >= 0.18:
        stewardship = "heavy_losses"
    elif casualty_fraction <= 0.06:
        stewardship = "well_preserved"
    else:
        stewardship = "material_losses"
    return {
        "adjudicated_merit": merit,
        "objective_result": "local_objective_achieved" if won else "local_objective_not_achieved",
        "command_role": str(command_role),
        "own_personnel_before": own,
        "enemy_personnel_before": enemy,
        "relative_enemy_strength_milli": int(round(adversity_ratio * 1000)),
        "own_casualties": casualties,
        "own_casualty_fraction_milli": int(round(casualty_fraction * 1000)),
        "casualty_stewardship": stewardship,
        "battle_hours_milli": int(round(max(0.0, float(battle_hours)) * 1000)),
        "operational_contact": bool(operational_contact),
        "review_scope": "battle service evidence only; obedience to broader campaign orders, political sponsorship and later testimony remain separate court-review evidence",
    }


__all__ = ["battle_service_appraisal"]

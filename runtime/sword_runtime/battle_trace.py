from __future__ import annotations

from typing import Any, Mapping, Sequence


def _int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _side_totals(refs: Sequence[str], formations: Mapping[str, Any], killed: Mapping[str, Any]) -> tuple[int, int]:
    survivors = sum(max(0, _int(formations[ref][1].get("personnel", 0))) for ref in refs)
    losses = sum(max(0, _int(killed.get(ref, 0))) for ref in refs)
    return survivors + losses, losses


def _ammo(refs: Sequence[str], material_losses: Mapping[str, Any]) -> dict[str, int]:
    total: dict[str, int] = {}
    for ref in refs:
        row = material_losses.get(ref, {}) if isinstance(material_losses.get(ref), Mapping) else {}
        consumed = row.get("ammunition_consumed", {}) if isinstance(row.get("ammunition_consumed"), Mapping) else {}
        for resource, amount in consumed.items():
            total[str(resource)] = total.get(str(resource), 0) + max(0, _int(amount))
    return {k: v for k, v in total.items() if v > 0}


def _weighted_factor(refs: Sequence[str], formations: Mapping[str, Any], score_details: Mapping[str, Any], key: str, scale: float = 10000.0) -> float:
    numerator = 0.0
    denominator = 0
    for ref in refs:
        detail = score_details.get(ref, {}) if isinstance(score_details.get(ref), Mapping) else {}
        survivors = max(0, _int(formations[ref][1].get("personnel", 0)))
        weight = survivors if survivors > 0 else 1
        numerator += weight * (_int(detail.get(key, int(scale))) / scale)
        denominator += weight
    return numerator / denominator if denominator else 1.0


def build_battle_causal_trace(
    *,
    attackers: Sequence[str],
    defenders: Sequence[str],
    battlefield_ref: str,
    terrain_kind: str,
    formations: Mapping[str, Any],
    killed: Mapping[str, Any],
    material_losses: Mapping[str, Any],
    score_details: Mapping[str, Any],
    named_person_outcomes: Mapping[str, Any],
    attacker_won: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build a player-narratable formation-scale causal chain.

    This intentionally uses only already-resolved physical/organizational facts.
    It does not create extra casualties, maneuvers, or hidden battlefield truth.
    """
    trace: list[dict[str, Any]] = []
    must_render: list[str] = []
    may_compress: list[str] = []

    a_before, a_losses = _side_totals(attackers, formations, killed)
    d_before, d_losses = _side_totals(defenders, formations, killed)
    a_ammo = _ammo(attackers, material_losses)
    d_ammo = _ammo(defenders, material_losses)

    contact_id = "phase_contact_geometry"
    contact = {
        "id": contact_id,
        "kind": "contact_geometry",
        "battlefield_ref": battlefield_ref,
        "terrain_kind": terrain_kind,
        "attacker_formation_refs": list(attackers),
        "defender_formation_refs": list(defenders),
        "attacker_personnel_entering": a_before,
        "defender_personnel_entering": d_before,
    }
    if terrain_kind in {"pass", "fort", "fortress"}:
        contact["space_effect"] = "restricted_frontage_and_reduced_mounted_expression"
    elif terrain_kind in {"capital", "city", "town", "estate", "hall"}:
        contact["space_effect"] = "built_or_constrained_ground_reduces_open_mounted_expression"
    else:
        contact["space_effect"] = "open_or_unconstrained_contact"
    trace.append(contact)
    must_render.append(contact_id)

    if a_ammo or d_ammo:
        missile_id = "phase_missile_exchange"
        trace.append({
            "id": missile_id,
            "kind": "missile_exchange",
            "attacker_ammunition_consumed": a_ammo,
            "defender_ammunition_consumed": d_ammo,
            "result": "finite_ammunition_was_expended_before_or_during_contact",
        })
        must_render.append(missile_id)

    method_rows = {}
    charge_rows = {}
    for ref in list(attackers) + list(defenders):
        detail = score_details.get(ref, {}) if isinstance(score_details.get(ref), Mapping) else {}
        method = detail.get("formation_method", {}) if isinstance(detail.get("formation_method"), Mapping) else {}
        methods = [str(x) for x in method.get("methods", []) if isinstance(x, str)]
        if methods:
            method_rows[str(ref)] = {
                "methods": methods,
                "shieldwall_integrity_milli": int(round(1000 * float(method.get("shieldwall_integrity", 0) or 0))),
                "phalanx_integrity_milli": int(round(1000 * float(method.get("phalanx_integrity", 0) or 0))),
                "brace_integrity_milli": int(round(1000 * float(method.get("brace_integrity", 0) or 0))),
                "average_melee_reach_m": float(method.get("average_melee_reach_m", 0) or 0),
                "melee_penetration_pressure": float(method.get("melee_penetration_pressure", 0) or 0),
                "opposing_protection_layer": float(method.get("opposing_protection_layer", 0) or 0),
                "penetration_ratio": float(method.get("penetration_ratio", 0) or 0),
            }
        if "mounted_charge" in methods and float(method.get("charge_collision_index", 0) or 0) > 0:
            charge_rows[str(ref)] = {
                "charge_speed_mps": float(method.get("charge_speed_mps", 0) or 0),
                "charge_mass_kg": float(method.get("charge_mass_kg", 0) or 0),
                "brace_absorption_milli": int(round(1000 * float(method.get("brace_absorption", 0) or 0))),
                "result": "mounted_mass_speed_alignment_and_opposing_brace_resolved_the_charge_contact",
            }
    if method_rows:
        method_id = "phase_formed_weapon_methods"
        trace.append({
            "id": method_id,
            "kind": "formed_weapon_methods",
            "formations": method_rows,
            "result": "shield_overlap_spear_depth_bracing_charge_lanes_and_weapon_penetration_against_opposing_protection_were_derived_from_actual_equipment_order_frontage_and_loadouts",
        })
        must_render.append(method_id)
    if charge_rows:
        charge_id = "phase_mounted_collision"
        trace.append({
            "id": charge_id,
            "kind": "mounted_collision",
            "formations": charge_rows,
            "result": "horse_and_rider_mass_speed_barding_load_lance_geometry_and_braced_reach_resolved_mounted_impact",
        })
        must_render.append(charge_id)

    hero_rows = []
    for ref in list(attackers) + list(defenders):
        detail = score_details.get(ref, {}) if isinstance(score_details.get(ref), Mapping) else {}
        for row in detail.get("hero_interventions", []) if isinstance(detail.get("hero_interventions"), list) else []:
            if not isinstance(row, Mapping) or int(row.get("physical_contacts", 0) or 0) <= 0:
                continue
            hero_rows.append({
                "formation_ref": ref,
                "person_ref": row.get("person_ref"),
                "representation": row.get("representation"),
                "role": row.get("role"),
                "active_window_seconds": row.get("active_window_seconds"),
                "action_interval_seconds": row.get("action_interval_seconds"),
                "physical_contacts": int(row.get("physical_contacts", 0) or 0),
                "casualty_pressure": int(row.get("casualty_pressure", 0) or 0),
                "frontage_displacement_m": float(row.get("frontage_displacement_m", 0) or 0),
                "mounted": bool(row.get("mounted")),
                "weapon_id": row.get("weapon_id"),
                "attack_mode": row.get("attack_mode"),
                "impact_index": float(row.get("impact_index", 0) or 0),
                "penetration_index": float(row.get("penetration_index", 0) or 0),
                "opposing_protection_index": float(row.get("opposing_protection_index", 0) or 0),
                "aim_zone": row.get("aim_zone"),
                "aim_structure": row.get("aim_structure"),
                "aim_purpose": row.get("aim_purpose"),
                "aim_selection_basis": row.get("aim_selection_basis"),
                "weighted_post_layer_injury_expression": float(row.get("weighted_post_layer_injury_expression", 0) or 0),
                "weighted_armor_penetration_fraction": float(row.get("weighted_armor_penetration_fraction", 0) or 0),
                "weighted_shield_condition_loss_pct": float(row.get("weighted_shield_condition_loss_pct", 0) or 0),
                "officer_pressure": float(row.get("officer_pressure", 0) or 0),
                "cohesion_shock_pressure": float(row.get("cohesion_shock_pressure", 0) or 0),
                "artillery_pressure": float(row.get("artillery_pressure", 0) or 0),
                "command_attention_seconds": float(row.get("command_attention_seconds", 0) or 0),
                "representative_contact_layers": row.get("representative_contact_layers", []),
                "incoming_expected_contacts": float(row.get("incoming_expected_contacts", 0) or 0),
                "incoming_injury_risk_milli": int(round(1000 * float(row.get("incoming_injury_risk", 0) or 0))),
                "incoming_death_risk_milli": int(round(1000 * float(row.get("incoming_death_risk", 0) or 0))),
                "incoming_hero_defense_control": float(row.get("incoming_hero_defense_control", 0) or 0),
                "representative_incoming_contact_layers": row.get("representative_incoming_contact_layers", []),
                "projectiles_released": int(row.get("projectiles_released", 0) or 0),
                "projectile_item_id": row.get("projectile_item_id"),
                "projectile_recovery_base": float(row.get("projectile_recovery_base", 0) or 0),
            })
    if hero_rows:
        hero_id = "phase_named_local_interventions"
        trace.append({
            "id": hero_id,
            "kind": "named_local_interventions",
            "interventions": hero_rows,
            "result": "exact_people_used_bounded_local_contact_windows; outgoing and incoming representative contacts passed through physical shield and armor layers; named ammunition, casualty risk, officer pressure, cohesion shock, artillery pressure, frontage displacement, and command attention remained separately traceable; no fictitious extra troops were created",
        })
        must_render.append(hero_id)

    a_reach = _weighted_factor(attackers, formations, score_details, "reach")
    d_reach = _weighted_factor(defenders, formations, score_details, "reach")
    a_effective = sum(max(0, _int(score_details.get(ref, {}).get("effective_bodies_milli", 0))) for ref in attackers) / 1000.0
    d_effective = sum(max(0, _int(score_details.get(ref, {}).get("effective_bodies_milli", 0))) for ref in defenders) / 1000.0
    reach_balance = "balanced"
    if a_reach > d_reach * 1.05:
        reach_balance = "attacker"
    elif d_reach > a_reach * 1.05:
        reach_balance = "defender"
    frontage_id = "phase_frontage_and_weapon_contact"
    trace.append({
        "id": frontage_id,
        "kind": "formation_contact",
        "reach_advantage": reach_balance,
        "attacker_frontage_expression_milli": int(round(1000 * a_effective / max(1, a_before))),
        "defender_frontage_expression_milli": int(round(1000 * d_effective / max(1, d_before))),
        "result": "formation_geometry_weapon_reach_and_protection_resolved_local_contact",
    })
    must_render.append(frontage_id)

    casualty_id = "phase_casualty_pressure"
    trace.append({
        "id": casualty_id,
        "kind": "casualty_pressure",
        "attacker_losses": a_losses,
        "defender_losses": d_losses,
        "attacker_loss_fraction_basis_points": int(round(10000 * a_losses / max(1, a_before))),
        "defender_loss_fraction_basis_points": int(round(10000 * d_losses / max(1, d_before))),
        "per_formation_losses": {str(ref): max(0, _int(killed.get(ref, 0))) for ref in list(attackers) + list(defenders)},
    })
    must_render.append(casualty_id)

    end_rows: list[dict[str, Any]] = []
    for ref in list(attackers) + list(defenders):
        formation = formations[ref][1]
        end_rows.append({
            "formation_ref": ref,
            "personnel_remaining": max(0, _int(formation.get("personnel", 0))),
            "status": str(formation.get("status", "")),
            "morale": _int(formation.get("morale", 0)),
            "cohesion": _int(formation.get("cohesion", 0)),
            "fatigue": _int(formation.get("fatigue", 0)),
        })
    cohesion_id = "phase_cohesion_response"
    trace.append({
        "id": cohesion_id,
        "kind": "cohesion_response",
        "formations": end_rows,
        "result": "surviving_formations_absorbed_losses_and_updated_cohesion_morale_and_fatigue",
    })
    must_render.append(cohesion_id)

    equipment_rows = {}
    for ref in list(attackers) + list(defenders):
        loss = material_losses.get(ref, {}) if isinstance(material_losses.get(ref), Mapping) else {}
        condition = loss.get("equipment_condition_losses", {}) if isinstance(loss.get("equipment_condition_losses"), Mapping) else {}
        mount_casualties = max(0, _int(loss.get("mount_casualties", 0)))
        if condition or mount_casualties:
            equipment_rows[str(ref)] = {
                "equipment_condition_losses": condition,
                "mount_casualties": mount_casualties,
                "hero_attributed_casualties": max(0, _int(loss.get("hero_attributed_casualties", 0))),
            }
    if equipment_rows:
        equipment_id = "phase_equipment_and_mount_condition"
        trace.append({
            "id": equipment_id,
            "kind": "equipment_and_mount_condition",
            "formations": equipment_rows,
            "result": "surviving_role_equipment_condition_and_mount_losses_followed_the_actual_contact_method_and_casualty_exposure",
        })
        may_compress.append(equipment_id)

    material_named = {
        str(ref): {
            "formation_ref": row.get("formation_ref"),
            "role": row.get("role"),
            "outcome": row.get("outcome"),
            "named_intervention": bool(row.get("named_intervention", False)),
            "intervention_incoming_injury_risk_milli": _int(row.get("intervention_incoming_injury_risk_milli", 0)),
            "intervention_incoming_death_risk_milli": _int(row.get("intervention_incoming_death_risk_milli", 0)),
            "named_ammunition": row.get("named_ammunition", {}),
        }
        for ref, row in named_person_outcomes.items()
        if isinstance(row, Mapping) and str(row.get("outcome", "unharmed")) != "unharmed"
    }
    if material_named:
        named_id = "phase_named_person_consequences"
        trace.append({
            "id": named_id,
            "kind": "named_person_consequences",
            "outcomes": material_named,
            "result": "individually_represented_people_received_separate_consequences_within_the_formation_battle",
        })
        must_render.append(named_id)

    result_id = "phase_local_result"
    trace.append({
        "id": result_id,
        "kind": "battle_result",
        "winner": "attacker" if attacker_won else "defender",
        "result": "local_contact_resolved_without_implying_unrecorded_territorial_or_political_consequences",
    })
    must_render.append(result_id)

    contract = {
        "must_render": must_render,
        "may_compress": may_compress,
        "do_not_reveal": [
            "causal seed or deterministic variance",
            "hidden numeric score breakdowns as narration",
            "enemy commander statistics or knowledge not lawfully visible to the player",
        ],
        "rule": "Narrate the battle through terrain, actual formed methods, penetration pressure against physical protection, mounted collision when present, exact named local interventions with their weapon mode/impact/penetration, formation contact, casualty pressure, equipment/mount consequences, cohesion, and the committed local result. Never translate a hero into fictional troop-equivalent bodies and never invent a penetration, broken shield, collapsed wall, or anatomical consequence that the causal trace did not establish; exact casualties remain authoritative underneath.",
    }
    return trace, contract

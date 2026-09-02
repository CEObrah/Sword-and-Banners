"""Bounded player-safe command input guidance.

These records expose exact enum/range constraints that are useful for natural-
language command construction without exposing hidden campaign state. They are
not a replacement for runtime validation. Exact object/person references must
still come from fresh play context or bounded inspection.
"""
from __future__ import annotations

from typing import Any, Mapping


COMMAND_INPUT_GUIDANCE: Mapping[str, Mapping[str, Any]] = {
    "advance_time": {
        "rule": "provide exactly one of hours or target_time",
        "hours": {"type": "integer", "minimum": 1, "maximum": 876000},
        "target_time": {"type": "campaign_time", "rule": "not earlier than current world time and no more than 100 years ahead"},
        "scene_policy": {
            "allowed_values": ["preserve_active_scene", "finish_active_scene", "leave_active_scene", "skip_to_conclusion"],
            "rule": "required when an active scene session exists; preserve has no artificial duration cap, while the other values explicitly close the scene before chronology advances",
        },
        "wait_policy": {
            "type": "object",
            "rule": "optional semantic stop conditions; fields inside one clause are conjunctive, values inside a field are alternatives, and distinct natural-language stop reasons belong in any_of clauses",
            "accepted_keys": ["event_kinds", "source_refs", "operation_refs", "classifications", "topic_terms", "any_of"],
        },
    },
    "travel": {
        "mode": {"allowed_values": ["foot", "horse"], "default": "foot"},
        "destination_ref": {"rule": "use an exact player-known registered location ref"},
        "formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 128, "rule": "optional exact controlled escort formations; all must be mobilized and co-located with the player; the column advances time once and its current derived strategic-supply condition applies without creating a separate ration inventory"},
    },
    "individual_training": {"hours": {"type": "integer", "minimum": 1, "maximum": 12}},
    "cohort_training": {"hours": {"type": "integer", "minimum": 1, "maximum": 12}},
    "formation_train": {
        "hours": {"type": "integer", "minimum": 1, "maximum": 12},
        "formation_ref": {"rule": "use an exact controlled formation ref"},
    },
    "formation_mobilize": {
        "rule": "provide exactly one of formation_ref or formation_refs",
        "formation_ref": {"rule": "use one exact controlled formation ref"},
        "formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 128, "rule": "use unique exact controlled formation refs; grouped formations mobilize in parallel and consume the normal mobilization duration once"},
    },
    "health_injury": {"severity": {"allowed_values": ["minor", "moderate", "severe", "critical"], "default": "minor"}},
    "health_recovery": {"hours": {"type": "integer", "minimum": 1, "maximum": 168}},
    "relationship_change": {
        "kind": {"allowed_values": ["trust", "affection", "respect", "fear", "resentment", "loyalty"], "default": "trust"},
        "delta": {"type": "integer", "minimum": -5, "maximum": 5, "forbidden_values": [0]},
        "target_ref": {"rule": "use an exact permitted person ref"},
    },
    "market_purchase": {"quantity": {"type": "integer", "minimum": 1, "maximum": 10000}},
    "market_sell": {"quantity": {"type": "integer", "minimum": 1, "maximum": 10000}},
    "economy_transfer": {
        "direction": {"allowed_values": ["player_to_state", "state_to_player"]},
        "amount_silver": {"type": "integer", "minimum": 1, "maximum": 1000000000},
    },
    "enlisted_service_pay": {"amount_silver": {"type": "integer", "minimum": 1, "maximum": 1000000000, "default": 7}},
    "resupply": {
        "rule": "provide at least one positive requested material quantity",
        "war_arrows": {"type": "integer", "minimum": 0, "maximum": 1000000000},
        "war_bolts": {"type": "integer", "minimum": 0, "maximum": 1000000000},
        "formation_ref": {"rule": "use an exact controlled formation ref"},
    },
    "recruitment_campaign_start": {
        "applicant_count": {"type": "integer", "minimum": 2, "maximum": 100000, "rule": "reserves real civilians from the registered source mix; it does not create soldiers or individual NPC sheets"},
        "campaign_ref": {"rule": "new stable recruitment-campaign ref"},
        "destination_force_ref": {"rule": "use the exact controlled personal-force ref; current Wei personal recruitment uses force_tang_wei_personal"},
        "role": {"rule": "use a registered destination military role"},
        "location_ref": {"rule": "use an exact lawful recruiting/training location ref"},
    },
    "recruitment_campaign_stage": {
        "campaign_ref": {"rule": "use an active recruitment campaign ref"},
        "selection_profile": {"rule": "must be a registered selection profile; ChatGPT must never invent stat bonuses or thresholds"},
        "retain_count": {"type": "integer", "minimum": 1, "rule": "provide exactly one of retain_count or retain_fraction; rejected candidates return to their conserved source population"},
        "retain_fraction": {"type": "number", "minimum": 0.0001, "maximum": 0.9999, "rule": "provide exactly one of retain_count or retain_fraction"},
    },
    "recruitment_campaign_train": {
        "campaign_ref": {"rule": "use an active recruitment campaign ref"},
        "hours": {"type": "integer", "minimum": 1, "maximum": 56, "rule": "real training consumes elapsed time, food and registered capacity; it changes development, unlike selection"},
    },
    "recruitment_campaign_finalize": {
        "campaign_ref": {"rule": "accepts the surviving candidate cohort into the destination force; acceptance remains cohort-first and does not auto-materialize individuals"},
    },
    "recruitment_campaign_cancel": {
        "campaign_ref": {"rule": "returns remaining reserved candidates to their original population strata; already spent recruiting/training costs are not refunded"},
    },
    "person_materialize": {
        "person_ref": {"rule": "new stable identity for one already-conserved cohort body; materialization never creates headcount"},
        "representation": {"allowed_values": ["person_lite", "exact"], "default": "person_lite"},
        "formation_ref": {"rule": "optional exact formation whose existing cohort slot is being materialized"},
        "source_cohort_ref": {"rule": "optional exact known source cohort; starting stats are sampled deterministically from that cohort and cannot be caller supplied"},
    },
    "formation_create": {
        "personnel": {"type": "integer", "minimum": 1, "maximum": 1000000, "rule": "current fighting personnel drawn from the exact force pool"},
        "formation_class": {"allowed_values": ["unit", "detachment"], "rule": "optional explicit establishment class; omitted values derive unit for 500+ personnel and detachment below 500"},
        "authorized_strength": {"type": "integer", "minimum": 1, "maximum": 1000000, "rule": "durable authorized establishment; must satisfy the selected formation class and may exceed current personnel for an understrength Unit"},
        "equipment_units": {"type": "integer", "minimum": 0, "maximum": 1000000},
    },
    "formation_reconstitute": {
        "target_personnel": {"type": "integer", "minimum": 1, "maximum": 1000000, "rule": "must exceed current formation personnel"},
        "equipment_units": {"type": "integer", "minimum": 0, "maximum": 1000000},
        "formation_ref": {"rule": "use an exact controlled formation ref"},
    },
    "formation_split": {
        "personnel": {"type": "integer", "minimum": 1, "maximum": 1000000},
        "formation_ref": {"rule": "use an exact controlled formation ref"},
    },
    "formation_doctrine_set": {
        "doctrine_ref": {"rule": "must be an exact registered doctrine ref; do not guess hidden doctrine IDs"},
        "doctrine_behavior.reserve_commitment": {"type": "integer", "minimum": 0, "maximum": 100},
        "doctrine_behavior.withdrawal_threshold": {"type": "integer", "minimum": 0, "maximum": 100},
        "doctrine_behavior.casualty_tolerance": {"allowed_values": ["low", "moderate", "high", "extreme"]},
    },
    "formation_equipment_repair": {
        "formation_ref": {"rule": "exact player-commanded House Tang formation physically at Tang Manor"},
        "hours": {"type": "integer", "minimum": 1, "maximum": 720, "rule": "calendar workshop time; actual repair is additionally bounded by exact forge worker-hours, nearby private construction materials and House silver"},
        "categories": {"type": "array", "minimum_items": 1, "maximum_items": 2, "allowed_values": ["shield", "armor"], "default": ["shield", "armor"], "rule": "repair only surviving serviceable units; destroyed or missing units require exact armory replacement stock"},
    },
    "formation_training_set": {"training_ref": {"rule": "must be an exact registered training-profile ref; do not guess hidden training IDs"}},
    "personal_combat": {
        "duration_minutes": {"type": "integer", "minimum": 1, "maximum": 240, "default": 60, "rule": "maximum engagement horizon; exact combat may stop earlier at a material decision boundary"},
        "opponent_ref": {"rule": "single-opponent shorthand; use an exact permitted person ref"},
        "opponent_refs": {"type": "array", "minimum_items": 1, "maximum_items": 31, "rule": "exact hostile people sharing one local continuous combat timeline; refs must be co-located and individually represented"},
        "ally_refs": {"type": "array", "minimum_items": 1, "maximum_items": 31, "rule": "optional exact allied people sharing the same local timeline; total exact scene size including the player is at most 32"},
        "target_ref": {"rule": "optional exact current player target and must be one of opponent_refs; omission allows physical/adaptive target selection"},
        "participant_positions": {"type": "object", "rule": "optional local combat-plane seed keyed only by scene participant refs with x_m/y_m/facing_deg; omitted positions are deterministically placed from distance_m"},
        "local_obstacles": {"type": "array", "maximum_items": 24, "rule": "optional player-visible/runtime-supplied local geometry only: circles use x_m/y_m/radius_m and segments use x1_m/y1_m/x2_m/y2_m/clearance_m; base_elevation_m/height_m may bound vertical obstruction; this constrains movement/contact/LOS but never creates world objects"},
        "objective_position": {"type": "object", "rule": "optional exact local x_m/y_m/elevation_m point for seize, hold, or destination escape objectives"},
        "objective_radius_m": {"type": "number", "minimum": 0.25, "maximum": 25.0, "default": 1.5},
        "objective_hold_seconds": {"type": "number", "minimum": 0.0, "maximum": 3600.0, "default": 10.0},
        "escape_distance_m": {"type": "number", "minimum": 0.5, "maximum": 500.0, "default": 8.0},
        "intent_sequence": {"type": "array", "minimum_items": 1, "maximum_items": 24, "rule": "optional ordered player-authored linked actions such as parry, close, cut the weapon arm; later links depend on earlier physical success and are cancelled when made impossible"},
        "stop_on_decision": {"type": "boolean", "default": True, "rule": "normally stop when injury, disarm, fall, separation, surrender/flee opportunity, or another protected decision materially changes the fight"},
        "improvised_prop_fact_ref": {"rule": "optional exact active-scene fact_ref for a typed mundane improvised prop whose object existence was already established by an earlier object_state scene fact in the same session; the runtime derives a transient combat profile and never mints inventory, value, or a durable item from it"},
    },
    "recover_projectiles": {
        "minutes": {"type": "integer", "minimum": 1, "maximum": 240, "rule": "actual search/recovery time spent at the current exact location; only already-fired recoverable personal projectiles at this location may be returned"},
        "projectile_item_id": {"rule": "optional exact projectile item filter; omit to recover any lawful personal projectile candidates at the current location"},
    },
    "operation_create": {
        "formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 512, "rule": "transport payload bound only; use exact controlled formation refs. Larger campaign forces remain lawful as multiple operations or battle sectors rather than disappearing from the world"},
        "location_ref": {"rule": "use an exact player-known registered location ref"},
    },
    "operation_transition": {"status": {"allowed_values": ["planned", "mobilizing", "active", "engaged", "occupied", "completed", "cancelled"]}},
    "battle_resolve": {
        "attacker_formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 128, "rule": "per-contact payload bound, not a force-size limit; a larger saved operation may be resolved through multiple disjoint battlefield sectors sharing exact operation evidence"},
        "defender_formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 128, "rule": "per-contact payload bound, not a force-size limit; every participating formation remains an exact persistent owner outside this call"},
        "operation_ref": {"rule": "exact active operation proving contact; larger operations may continue through multiple sector/contact resolutions"},
        "battlefield_ref": {"rule": "optional active operational battlefield inside operation_ref; when supplied sector_ref is also required and all contact formations must actually be assigned there"},
        "sector_ref": {"rule": "optional exact sector inside battlefield_ref; exact battle casualties/outcome reconcile back into only this local sector"},
    },
    "battlefield_control": {
        "action": {"allowed_values": ["open", "assign", "redeploy", "set_order", "close"]},
        "layout_ref": {"allowed_values": ["battlefield.layout.line_three", "battlefield.layout.deep_five"], "applies_to": ["open"]},
        "side_refs": {"type": "array", "minimum_items": 2, "maximum_items": 2, "applies_to": ["open"], "rule": "two stable operational side labels; they do not transfer formation ownership"},
        "sector_ref": {"rule": "exact sector assignment for one present participating formation", "applies_to": ["assign"]},
        "target_sector_ref": {"rule": "exact different sector; movement takes battlefield time and the formation contributes to neither endpoint while in transit", "applies_to": ["redeploy"]},
        "pace": {"allowed_values": ["forced", "standard", "cautious"], "default": "standard", "applies_to": ["redeploy"]},
        "order": {"allowed_values": ["hold", "attack", "breakthrough", "delay", "reserve", "withdraw"], "default": "hold", "applies_to": ["assign", "redeploy", "set_order"]},
        "rule": "operational battlefield state owns sector geometry, command pressure, redeployment clocks, contacts and messenger delay only; battle_resolve remains casualty/outcome authority"
    },
    "state_action": {
        "action": {"allowed_values": ["strategic_goal", "appointment", "enemy_action", "record_threat", "recognize_polity"], "default": "strategic_goal"},
        "severity": {"type": "integer", "minimum": 0, "maximum": 100, "applies_to": ["enemy_action", "record_threat"]},
        "information_ref": {"rule": "optional exact saved information claim that the acting player already knows; autonomous callers may attach only an existing claim ref", "applies_to": ["enemy_action", "record_threat"]},
    },
    "fortification_materialize": {
        "integrity": {"type": "integer", "minimum": 1, "maximum": 100, "default": 100},
        "garrison_formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 512, "rule": "fortification custody payload bound only; the garrison remains an exact saved formation set and large assaults are resolved by explicit battlefield sectors"},
    },
    "siege_start": {"attacker_formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 512, "rule": "saved siege-force payload bound only; use exact controlled formation refs. Assaults involving more than 128 formations on either side continue through explicit disjoint battlefield sectors"}},
    "siege_action": {
        "action": {"allowed_values": ["blockade", "build_work", "ram_gate", "repair", "assault", "withdraw", "settle", "relief"]},
        "days": {"type": "integer", "minimum": 1, "maximum": 30, "default": 7, "applies_to": ["blockade"]},
        "route_refs": {"type": "array", "minimum_items": 1, "maximum_items": 64, "applies_to": ["blockade"], "rule": "exact approaches being invested; omitted only where the fortification profile has a small registered route set that can be covered as one operation"},
        "blueprint_ref": {"type": "string", "applies_to": ["build_work"], "rule": "must identify a registered engineering blueprint in game/data/mechanics/siege-engineering-blueprints.json"},
        "quantity": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 1, "applies_to": ["build_work"]},
        "source_formation_ref": {"type": "string", "applies_to": ["build_work", "repair"], "rule": "exact co-located formation supplying conserved labor and carried materials"},
        "target": {"allowed_values": ["gate", "wall", "investment"], "applies_to": ["build_work", "repair", "assault"]},
        "method": {"allowed_values": ["auto", "breach", "ladder", "siege_tower", "swim_grapnel"], "default": "auto", "applies_to": ["assault"]},
        "work_ref": {"type": "string", "applies_to": ["ram_gate"], "rule": "optional exact serviceable ram work; if omitted the runtime uses a lawful serviceable ram at the gate"},
        "cycles": {"type": "integer", "minimum": 1, "maximum": 200, "default": 10, "applies_to": ["ram_gate"]},
        "hours": {"type": "integer", "minimum": 1, "maximum": 168, "default": 12, "applies_to": ["repair"]},
        "attacker_formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 128, "applies_to": ["assault"], "rule": "optional explicit assault-sector attacker subset; required with defender_formation_refs when the saved siege exceeds one contact payload"},
        "defender_formation_refs": {"type": "array", "minimum_items": 1, "maximum_items": 128, "applies_to": ["assault"], "rule": "optional exact garrison subset for this assault sector; the unselected saved garrison remains present for later sectors"},
        "physical_access_rule": "exact fortifications must have a lawful crossing and gate/wall contact path before troop battle can begin; grapnel access never grants wheeled-engine access",
        "outcome_rule": "breach, structural damage, casualties, capture and other contested outcomes are runtime-owned and may not be caller supplied",
    },
    "family_event": {
        "kind": {"accepted_values": ["proposal", "engagement", "marriage", "pregnancy", "birth", "death", "widowhood", "succession_review"]},
        "player_authored_kinds": ["proposal", "engagement", "marriage"],
        "runtime_only_involuntary_kinds": ["pregnancy", "birth", "death", "widowhood", "succession_review"],
        "marriage_rule": "a player-authored marriage requires the player actor to be one marrying party and a previously accepted betrothal; NPC-only marriages remain autonomous/runtime consequences",
    },
    "career_event": {
        "kind": {"allowed_values": ["qualification", "promotion", "demotion", "office_appointment", "office_removal", "relief", "reserve", "retirement", "return_to_service", "affiliation_add", "affiliation_remove", "merit"]},
        "grade": {"rule": "promotion/demotion uses one exact formal grade from game/data/mechanics/military-career.json; rank is durable and independent from billet/span", "applies_to": ["promotion", "demotion"]},
        "merit": {"type": "integer", "minimum": 1, "maximum": 1000, "applies_to": ["merit"]},
        "office": {"type": "string", "applies_to": ["office_appointment", "office_removal", "relief"]},
        "affiliation_ref": {"type": "string", "applies_to": ["affiliation_add", "affiliation_remove"]},
        "rule": "durable rank, current billet, current command span and affiliation are separate saved dimensions; only promotion/demotion changes rank",
        "player_rule": "career_event is a derived world consequence and is not directly player-authored",
    },
    "mercenary_contract": {
        "action": {"allowed_values": ["offer", "accept", "pay", "deploy", "breach", "renew", "complete"]},
        "amount_silver": {"type": "integer", "minimum": 1, "maximum": 100000000, "applies_to": ["offer", "pay", "renew"]},
        "term_days": {"type": "integer", "minimum": 1, "maximum": 3650, "default": 90, "applies_to": ["offer"]},
        "player_rule": "mercenary acceptance is an autonomous company decision and cannot be player-authored",
    },
    "institution_project": {
        "duration_hours": {"type": "integer", "minimum": 1, "maximum": 8760, "default": 168},
        "magnitude": {"type": "integer", "minimum": 1, "maximum": 1000000, "default": 1},
        "kind": {"rule": "use infrastructure for physical works or settlement_foundation to create a new conserved settlement from an existing site; administrative/process/resource projects remain available for non-physical institution work"},
        "effect": {"rule": "infrastructure requires infrastructure_blueprint_ref plus target_site_ref. settlement_foundation requires source_site_ref, new_settlement_name, and 1..1000 initial_settlers. The runtime derives money, materials, labor, roads, physical support, and queues real household movement; no residents are spawned."},
    },
    "project_cancel": {
        "institution_ref": {"rule": "exact institution authority"},
        "project_ref": {"rule": "exact active funded project; cancellation releases reserved workers and returns only unconsumed/recoverable inputs"},
    },
    "house_action": {
        "action": {"allowed_values": ["assign_duty", "set_policy", "grant_nobility", "proclaim_territorial_authority"], "default": "assign_duty"},
        "subject_ref": {"rule": "assign_duty requires an exact person already within House Tang or Tang Wei personal-retinue authority", "applies_to": ["assign_duty"]},
        "duty": {"type": "string", "maximum_length": 160, "applies_to": ["assign_duty"]},
        "policy_key": {"type": "string", "maximum_length": 120, "applies_to": ["set_policy"]},
        "policy_value": {"type": "string", "maximum_length": 400, "applies_to": ["set_policy"]},
        "target_grade": {"allowed_values": ["recognized_house", "minor_noble_house", "noble_house", "high_noble_house", "great_noble_house"], "rule": "grant_nobility advances one formal non-royal House grade; it creates no land, silver, office, troops, tax privilege, or royal claim", "applies_to": ["grant_nobility"]},
        "grantor_ref": {"rule": "grant_nobility requires the acting exact sovereign or a person holding explicit grant_house_nobility authority", "applies_to": ["grant_nobility"]},
        "evidence_ref": {"rule": "exact saved service/reward/court evidence supporting the grant; merit never auto-promotes a House", "applies_to": ["grant_nobility"]},
        "location_ref": {"rule": "proclamation requires an exact currently occupied seat", "applies_to": ["proclaim_territorial_authority"]},
        "operation_ref": {"rule": "exact surviving House-backed occupation evidence", "applies_to": ["proclaim_territorial_authority"]},
        "polity_name": {"type": "string", "maximum_length": 120, "applies_to": ["proclaim_territorial_authority"]},
    },
    "command_group_action": {
        "action": {"allowed_values": ["create", "add_person", "remove_person", "attach_formation", "detach_formation", "attach_command_group", "detach_command_group", "move_unit", "move_army", "promote_formation_to_army", "set_successors", "set_order", "set_communication", "set_doctrine"]},
        "command_group_ref": {"rule": "use an exact command-group ref already controlled by Tang Wei, except create which allocates a new command-group ref"},
        "unit_slot": {"rule": "1-based ordered direct Unit slot; used only by move_unit"},
        "subordinate_group_ref": {"rule": "attach/detach an exact controlled zero-body command group without flattening any of its subordinate units"},
        "location_ref": {"rule": "move_army destination; every descendant formation follows one physical ordered road-column plan and remains a separate conserved owner", "applies_to": ["move_army"]},
        "doctrine_ref": {"rule": "set_doctrine requires an exact registered standing army doctrine; this changes command procedure, not troop capability", "applies_to": ["set_doctrine"]},
        "issuer_ref": {"rule": "optional exact commander or strategist who actually transmits set_order. A strategist may issue only within the recursive subtree of the command group where that strategist is assigned; parent/sibling scope is forbidden and normal communication delay still applies", "applies_to": ["set_order"]},
        "rule": "command groups are recursive command structure only and never create manpower; each group has one commander plus explicit staff roles. A registered strategist may formulate/transmit operational orders anywhere inside that command group's recursive subtree, including nested armies, but cannot reach upward or sideways and gains no hidden knowledge or teleporting communication.",
    },
    "command_group_train": {
        "hours": {"type": "integer", "minimum": 1, "maximum": 12},
        "command_group_ref": {"rule": "use an exact player-controlled command-group ref whose participating exact people are co-located"},
        "rule": "advances time once, improves bounded group familiarity, and may train one explicit exact-person skill focus without duplicating elapsed time",
    },
    "information_create": {
        "claim": {"type": "string", "maximum_length": 4000},
        "knowers": {"type": "array", "minimum_items": 1, "maximum_items": 128, "rule": "use exact person refs; gameplay creation must include the player actor as an exact knower"},
        "epistemic_kind": {"allowed_values": ["observation", "report", "rumor", "testimony", "document", "captured_document", "inference", "estimate", "official_report"]},
        "confidence_milli": {"type": "integer", "minimum": 0, "maximum": 1000},
        "rule": "creates Tang Wei's saved assertion with provenance, not world truth; gameplay callers cannot supply evidence_refs or discoverability, and authoritative evidence must come from persisted runtime-owned observation/document/report paths",
    },
    "information_deliver": {
        "channel": {"allowed_values": ["spoken", "written_message", "official_report", "courier", "scout_report", "merchant_network", "prisoner_testimony"]},
        "rule": "delivery preserves provenance and can reduce confidence; it does not turn a report into direct observation",
    },
    "investigation_action": {
        "action": {"allowed_values": ["start", "work", "close"]},
        "hours": {"type": "integer", "minimum": 1, "maximum": 24, "applies_to": ["work"]},
        "rule": "the player may choose investigator, place, scope, and time but may not declare culprit, clue, or result; only runtime-established discoverable claims backed by lawful evidence can be found",
    },
    "commission_action": {
        "action": {"allowed_values": ["request", "accept", "decline", "report"]},
        "rule": "requests are processed durably by the world; issuer eligibility is validated, assignment objective/location are committed before tactics, hidden risk is only an issuer assessment rather than proof of opposition, and reports settle only from relevant runtime-established evidence; location-only evidence is accepted only for reconnaissance/inspection/investigation/intelligence work",
    },
    "medical_treatment": {
        "treatment": {"allowed_values": ["stabilize", "treat", "surgery", "rehabilitation"]},
        "rule": "requires exact co-location, procedure-specific Medicine qualification, and for facility-backed care an exact co-located facility owner/location; treatment consequences are runtime-owned and surgery preview is hidden until execute",
    },
    "commitment_action": {
        "action": {"allowed_values": ["create", "fulfill", "confirm_fulfillment", "breach", "release"]},
        "rule": "gameplay may create only Tang Wei's own voluntary obligation; fulfill submits a runtime-established evidence-backed claim, the beneficiary confirms fulfillment, and only the beneficiary may release it",
    },
    "fortification_logistics": {
        "action": {"allowed_values": ["dispatch_resupply", "withdraw_reserve", "settle_convoy", "review_site", "dematerialize"]},
        "site_ref": {"rule": "exact fortified House Tang site for player-directed review/resupply/withdrawal/dematerialization; sovereign state logistics is autonomous/internal"},
        "source_depot_ref": {"rule": "dispatch_resupply requires an exact House Tang depot owner", "applies_to": ["dispatch_resupply"]},
        "destination_depot_ref": {"rule": "withdraw_reserve requires an exact lawful destination depot", "applies_to": ["withdraw_reserve"]},
        "cargo": {"type": "object", "rule": "1..16 positive exact physical stock quantities; dispatch removes them from the source immediately and the convoy owns them in transit", "applies_to": ["dispatch_resupply", "withdraw_reserve"]},
        "convoy_ref": {"rule": "exact fortified-site logistics convoy ref that has physically arrived", "applies_to": ["settle_convoy"]},
        "rule": "campaign resupply/withdrawal never teleports stock. Cold-site dematerialization is legal only after mutable stock/water/damage and active convoy/siege state are resolved.",
    },
    "strategic_crossing_action": {
        "route_ref": {"rule": "exact strategic route with a registered water crossing"},
        "action": {"allowed_values": ["set_water_stage", "damage_bridge", "repair_bridge", "damage_ferries", "restore_ferries", "open_ford", "close_ford"]},
        "water_stage": {"allowed_values": ["low", "normal", "high", "flood"], "applies_to": ["set_water_stage"]},
        "amount": {"type": "integer", "minimum": 1, "maximum": 100, "applies_to": ["damage_bridge", "repair_bridge"]},
        "quantity": {"type": "integer", "minimum": 1, "maximum": 1000, "applies_to": ["damage_ferries", "restore_ferries"]},
        "rule": "crossing actions change the mutable bridge/ferry/ford/water state used by real route throughput and closure checks",
    },
    "settlement_civic_action": {
        "action": {"allowed_values": ["register_local_case", "resolve_local_case", "start_outbreak", "set_quarantine", "review_outbreak"]},
        "location_ref": {"rule": "exact represented demographic site", "applies_to": ["register_local_case", "start_outbreak"]},
        "case_kind": {"allowed_values": ["theft", "violence", "corruption", "tax_dispute", "banditry", "desertion", "property", "contract", "other"], "applies_to": ["register_local_case"]},
        "severity": {"type": "integer", "minimum": 1, "maximum": 100, "applies_to": ["register_local_case"]},
        "disposition": {"allowed_values": ["dismissed", "remedy", "sanction", "escalated"], "applies_to": ["resolve_local_case"]},
        "transmission_route": {"allowed_values": ["close_contact", "water_food", "vector", "respiratory", "wound_contact", "unknown"], "applies_to": ["start_outbreak"]},
        "severity_band": {"allowed_values": ["mild", "moderate", "severe", "critical"], "applies_to": ["start_outbreak"]},
        "quarantine_strength": {"type": "integer", "minimum": 0, "maximum": 100, "applies_to": ["set_quarantine"]},
        "rule": "local cases never invent guilt/evidence; outbreaks remain aggregate compartments and debit exact conserved population only when deaths occur",
    },
    "organization_action": {
        "action": {"allowed_values": ["create", "fund", "withdraw", "join", "leave", "appoint_leader", "nominate_candidate", "remove_candidate", "link_force", "unlink_force", "set_policy", "dissolve"]},
        "organization_ref": {"rule": "new exact ref for create; otherwise use an exact player-visible organization ref"},
        "amount_silver": {"type": "integer", "minimum": 1, "applies_to": ["fund", "withdraw"]},
        "person_ref": {"rule": "exact existing person; organization membership/leadership never creates a body", "applies_to": ["join", "leave", "appoint_leader", "nominate_candidate", "remove_candidate"]},
        "force_ref": {"rule": "exact existing force owner; linking does not transfer or duplicate its personnel", "applies_to": ["link_force", "unlink_force"]},
        "rule": "organizations own zero population; treasury, members, leadership, projects, policies and linked forces remain separate exact authorities",
    },
    "custody_action": {
        "action": {"allowed_values": ["accept_surrender", "allocate_guards", "provision", "transfer_custodian", "release", "parole", "execute", "escape_attempt", "set_ransom", "accept_ransom", "propose_exchange", "accept_exchange", "interrogate", "offer_recruitment", "finalize_recruitment"]},
        "prisoner_group_ref": {"rule": "exact player-visible held prisoner-group ref for all actions except accept_surrender"},
        "personnel": {"type": "integer", "minimum": 1, "rule": "exact surrendered aggregate headcount removed from the surrendering formation", "applies_to": ["accept_surrender", "execute"]},
        "guards": {"type": "integer", "minimum": 0, "rule": "duty allocation from existing custodian formation personnel, never extra bodies", "applies_to": ["allocate_guards"]},
        "amount_silver": {"type": "integer", "minimum": 1, "applies_to": ["set_ransom"]},
        "rule": "custody is physical and conserved: prisoners, guards, food/water, movement, ransom/exchange, testimony, recruitment and escape remain causal owners/actions",
    },
    "scene_consequence": {"summary": {"type": "string", "maximum_length": 4000}},
}


INPUT_GUIDANCE_POLICY = (
    "Exact enum/range constraints are shown where the player-facing runtime can safely advertise them. "
    "Absent constraints remain governed by live validation. Exact person, formation, location, doctrine, "
    "training, operation, institution, mercenary, and other object refs must come from fresh context or "
    "bounded player-visible inspection; never guess hidden IDs."
)


__all__ = ["COMMAND_INPUT_GUIDANCE", "INPUT_GUIDANCE_POLICY"]

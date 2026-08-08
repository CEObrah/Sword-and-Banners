# Organization and Unit Law

## Core hierarchy

`source population / unorganized manpower -> homogeneous unit -> command group -> formation -> army / operation / institution`.

A **unit** is the only persistent aggregate mass-combat organization. A unit has one troop type and one intended organizational standard loadout. It owns headcount, aggregate capability, population/development profile, doctrine, training, tendencies, cohesion, morale, readiness, condition, experience/history, home chain, current assignment and equipment issue state. Large ordinary units resolve from aggregate statistics under `data/mechanics/unit-resolution.json`; never create one character sheet per ordinary soldier.

A **commander** is a separate person who may command multiple units or subordinate command nodes. A **formation** is a temporary operational/battle arrangement of units and owns no manpower. A force pool or civilian population is accounting-only people and cannot fight as a military unit until lawfully recruited/allocated and organized.

## Recruitment provenance and population conservation

Every ordinary recruit, replacement, transfer or newly organized soldier must come from an authoritative source population, manpower pool, existing unit, mercenary pool, institutional population or other registered owner. The transaction settles that source through the transfer time, deducts the exact conserved headcount once, records the source claim, and carries forward the selected source population's relevant capability, occupation/history, body/age, aptitude, experience and qualification state. Organization never rerolls the people into a generic troop template.

Selection criteria are causal. Hunters/foresters, agricultural workers, craftsmen, professional soldiers, veterans, mercenaries, guards, riders, scouts and other source strata differ only where authoritative source state supports the distinction. A request to recruit a specific stratum fails closed when that stratum does not exist or cannot be lawfully identified in the source owner. Never substitute a convenient population and then grant the requested profile by narration.

Training, doctrine, equipment and later service may change the organized unit after recruitment, but they do not rewrite its recruitment provenance. Replacements carry their own source claims and are pooled into the receiving unit by the same deterministic merge law. Returning or demobilized personnel return to a lawful destination population with their surviving history/condition; they do not recreate the source population's old state.

Named commanders and exceptional persistent people remain separate characters. Ordinary soldiers become individual-lite/exact only when a real causal reason requires persistent individual identity: a named interaction, exceptional act, promotion/appointment, distinctive injury, relationship, contract, specialist assignment, prisoner status or another registered need. Materialization deducts that individual exactly once from the surviving aggregate population and inherits only capability/history supported by the selected stratum; becoming named grants no bonus.

## Hard unit boundary

One unit means one troop type and one intended standard loadout. If only a subset should receive a different durable loadout, doctrine, training plan, commander, mount standard, assignment or other persistent standard, `SPLIT UNIT` first. Example: re-equipping 1,000 men inside a 5,000-infantry unit produces a 4,000-infantry unit retaining the old standard and a 1,000-infantry unit beginning the new refit. Infantry and archers never share a unit.

Split/merge is a canonical transaction governed by `data/mechanics/unit-partition.json`. Neutral splits preserve the parent represented capability and population/development distributions, including source provenance. Integer categories use deterministic largest-remainder allocation. Explicitly concentrating veterans, specialists, stronger members, better equipment, hunters, riders, or other quality requires a real selection/reallocation action with criteria, authority, evidence and time. Conserve people, source claims, named-member claims, horses/animals, weapons, armor, ammunition, supplies, injuries, fatigue, experience, morale/cohesion inputs and history. Do not silently select superior soldiers into a child without an explicit lawful selection action. Compatible same-type units may merge only after standards are reconciled; continuous capabilities use personnel-weighted pooled moments, integer categories sum exactly, source claims remain traceable, and integration can reduce cohesion/familiarity until real training/time restores it. Split/merge invalidates and rebuilds derived battle kernels.

`SET LOADOUT` changes the target standard for the whole unit. It does not instantly create equipment. Refit consumes real stock, transport, fitting/maintenance, ammunition, mounts where relevant, familiarization and time. Temporary shortages/damage/substitutes are issue/readiness state, not a second standard. Named exact/individual-lite members may retain personal equipment exceptions.

## Command hierarchy

Use `data/mechanics/command.json`. Every commander has one ownership-agnostic direct budget with two axes: direct personnel and direct command slots. Personal, assigned, attached, institutional and mercenary units share the same limits. A direct leaf unit costs one slot. A subordinate command node costs one slot. Delegated whole units stop counting against the superior direct personnel/leaf-unit load and count against the subordinate instead; the superior retains one subordinate-node slot. Recursive strategic authority is not direct control.

Thus a commander comfortable at 10,000 personnel / 8 slots who has 15,000 in 10 units can delegate 5,000 in 4 units to a subordinate. The superior then carries 10,000 direct personnel plus six leaf-unit slots and one subordinate-command slot; the subordinate carries 5,000 plus four units.

Splitting never grants free power: additional directly controlled units increase span burden and do not create frontage, actions or combat multipliers. Effective capacity is deterministic: interpolate the commander rating anchors, apply only evidence-supported health/staff/doctrine/terrain/information modifiers from `data/mechanics/command.json`, then compute `load_ratio = max(direct_personnel/effective_personnel_capacity, direct_slots/effective_slot_capacity)`. The saved state therefore produces the same command-delay/synchronization consequences every time. Staff/signals, doctrine familiarity, terrain/dispersion, information quality, health and fatigue affect command/control rather than soldiers permanent attributes.

## Ownership, attachment, return

Temporary command never changes ownership. Intact assigned units retain their source owner, home establishment, identity, history, doctrine identity, recruitment provenance and equipment custody unless lawfully transferred. Raw personnel entrusted for player or NPC organization may be formed into legal same-type units only from the actually granted source claims.

Returning troops restores the surviving force to its home organizational chain, not its old condition. Casualties, injuries, experience, lawful promotions, morale/cohesion changes, equipment/horse losses, source lineage and history persist. The owner reconstitutes with real replacement manpower, officers, stock, horses, training and time.

## Support and camp followers

Use `data/mechanics/support.json`. Medical, logistics and signal units are real military service-support units and can be moved, disrupted, defended and suffer casualties, but they do not automatically add offensive line frontage. Engineers/scouts contribute their specialist capacity unless deliberately committed. Civilian camp followers/dependents/laborers are noncombat populations, not military units; armed train guards are separate homogeneous guard units.

## Formation and large battle

Formation templates describe arrangements a force knows; active formations exist only for real operations. Formations reference units and own no manpower. Large battles resolve ordinary units as aggregate statistical actors. Materially equivalent units may be vectorized for computation only, with every result settled to actual unit IDs. Wake full capability for close thresholds, specialist actions, unusual terrain/equipment, named actors or any asymmetry that can change the outcome.

## Player agency

Tang Wei's personal retinue is represented by its named persistent people plus its actual permanent aggregate units. Ordinary soldiers do not appear in `pforce.tang_wei.members`; the personal-force owner references their unit owners instead. The player controls consequential choices about permanent unit names, roles, doctrine, standard loadouts and commanders within lawful authority. OOC/preview discussion never creates organization, recruits, source claims or intent.

## Command groups as direct elements

A **command group** is a persistent/operational command-only node, not a troop unit. It owns no manpower. It points to one real commander person, zero or more directly controlled homogeneous units, optional directly controlled named people, and zero or more subordinate command groups. Its authoritative state lives under `state/cmd/command-groups/` only after an actual appointment/delegation creates it.

For span-of-command, a superior's direct elements are **direct troop units + direct subordinate command groups**. Example: `Archer Unit`, `Infantry Unit`, `Mercenary Unit`, and `Jang Command` consume four direct slots. The units nested under `Jang Command` do not also consume the superior's direct slots or personnel budget; they consume Jang's. The superior still retains recursive strategic authority where the appointment/order grants it.

The commander of a command group remains a real combat-capable person. If present, that person can move, fight, use personal equipment/techniques, be wounded, killed, captured, isolated, exhausted, or routed. Personal combat never gets averaged into the unit's ordinary-soldier capability. Command loss triggers deputy/succession/standing-doctrine handling; directly absorbing orphaned child units increases the superior's direct load immediately.

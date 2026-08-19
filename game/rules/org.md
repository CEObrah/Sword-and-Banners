# Organization and Unit Law

## Core hierarchy

`person / unorganized manpower -> homogeneous unit -> command group -> formation -> army / operation / institution`.

A **unit** is the only persistent aggregate mass-combat organization. A unit has one troop type and one intended organizational standard loadout. It owns headcount, aggregate capability, doctrine, training, tendencies, cohesion, morale, readiness, condition, experience/history, home chain, current assignment and equipment issue state. Large ordinary units resolve from aggregate statistics under `game/data/mechanics/unit-resolution.json`; never create one character sheet per ordinary soldier.

A **commander** is a separate person who may command multiple units or subordinate command nodes. A **formation** is a temporary operational/battle arrangement of units and owns no manpower. A force pool is accounting-only manpower and cannot fight until allocated to units.

## Hard unit boundary

One unit means one troop type and one intended standard loadout. If only a subset should receive a different durable loadout, doctrine, training plan, commander, mount standard, assignment or other persistent standard, `SPLIT UNIT` first. Example: re-equipping 1,000 men inside a 5,000-infantry unit produces a 4,000-infantry unit retaining the old standard and a 1,000-infantry unit beginning the new refit. Infantry and archers never share a unit.

Split/merge is a canonical transaction governed by `game/data/mechanics/unit-partition.json`. Neutral splits preserve the parent represented capability distribution; integer categories use deterministic largest-remainder allocation. Explicitly concentrating veterans, specialists, stronger members, better equipment, or other quality requires a real selection/reallocation action with criteria, authority, evidence and time. Conserve people, named-member claims, horses/animals, weapons, armor, ammunition, supplies, injuries, fatigue, experience, morale/cohesion inputs and history. Do not silently select superior soldiers into a child without an explicit lawful selection action. Compatible same-type units may merge only after standards are reconciled; continuous capabilities use personnel-weighted pooled moments, integer categories sum exactly, and integration can reduce cohesion/familiarity until real training/time restores it. Split/merge invalidates and rebuilds derived battle kernels.

`SET LOADOUT` changes the target standard for the whole unit. It does not instantly create equipment. Refit consumes real stock, transport, fitting/maintenance, ammunition, mounts where relevant, familiarization and time. Temporary shortages/damage/substitutes are issue/readiness state, not a second standard. Named exact/individual-lite members may retain personal equipment exceptions.

## Command hierarchy

Use `game/data/mechanics/command.json`. Every commander has one ownership-agnostic direct budget with two axes: direct personnel and direct command slots. Personal, assigned, attached, institutional and mercenary units share the same limits. A direct leaf unit costs one slot. A subordinate command node costs one slot. Delegated whole units stop counting against the superior direct personnel/leaf-unit load and count against the subordinate instead; the superior retains one subordinate-node slot. Recursive strategic authority is not direct control.

Thus a commander comfortable at 10,000 personnel / 8 slots who has 15,000 in 10 units can delegate 5,000 in 4 units to a subordinate. The superior then carries 10,000 direct personnel plus six leaf-unit slots and one subordinate-command slot; the subordinate carries 5,000 plus four units.

Splitting never grants free power: additional directly controlled units increase span burden and do not create frontage, actions or combat multipliers. Effective capacity is deterministic: interpolate the commander rating anchors, apply only evidence-supported health/staff/doctrine/terrain/information modifiers from `game/data/mechanics/command.json`, then compute `load_ratio = max(direct_personnel/effective_personnel_capacity, direct_slots/effective_slot_capacity)`. The saved state therefore produces the same command-delay/synchronization consequences every time. Staff/signals, doctrine familiarity, terrain/dispersion, information quality, health and fatigue affect command/control rather than soldiers permanent attributes.

## Ownership, attachment, return

Temporary command never changes ownership. Intact assigned units retain their source owner, home establishment, identity, history, doctrine identity and equipment custody unless lawfully transferred. Raw personnel entrusted for player organization may be formed into legal same-type units within granted authority.

Returning troops restores the surviving force to its home organizational chain, not its old condition. Casualties, injuries, experience, lawful promotions, morale/cohesion changes, equipment/horse losses and history persist. The owner reconstitutes with real replacement manpower, officers, stock, horses, training and time.

## Support and camp followers

Use `game/data/mechanics/support.json`. Medical, logistics and signal units are real military service-support units and can be moved, disrupted, defended and suffer casualties, but they do not automatically add offensive line frontage. Engineers/scouts contribute their specialist capacity unless deliberately committed. Civilian camp followers/dependents/laborers are noncombat populations, not military units; armed train guards are separate homogeneous guard units.

## Formation and large battle

Formation templates describe arrangements a force knows; active formations exist only for real operations. Formations reference units and own no manpower. Large battles resolve ordinary units as aggregate statistical actors. Materially equivalent units may be vectorized for computation only, with every result settled to actual unit IDs. Wake full capability for close thresholds, specialist actions, unusual terrain/equipment, named actors or any asymmetry that can change the outcome.

## Player agency

World-owned forces retain their lawful home establishment. Tang Wei's personal-force owner records only units and named people actually created, assigned, attached, hired or otherwise placed under his authority. OOC/preview discussion never creates organization, assignment or intent.

## Command groups as direct elements

A **command group** is a persistent/operational command-only node, not a troop unit. It owns no manpower. It points to one real commander person, zero or more directly controlled homogeneous units, optional directly controlled named people, and zero or more subordinate command groups. Its authoritative state lives under `state/cmd/command-groups/` only after an actual appointment/delegation creates it.

For span-of-command, a superior's direct elements are **direct troop units + direct subordinate command groups**. Example: `Archer Unit`, `Infantry Unit`, `Mercenary Unit`, and `Jang Command` consume four direct slots. The units nested under `Jang Command` do not also consume the superior's direct slots or personnel budget; they consume Jang's. The superior still retains recursive strategic authority where the appointment/order grants it.

Routine headquarters staff offices may be anonymous command-staff role slots when only institutional function, capability, availability and succession matter. The commander and any staff member whose personal agency/history becomes causal are materialized people. A role slot is never a hidden character, never a one-person unit, and never an automatic command bonus.

## Field-army and Unit echelon separation

A Field Army or other command group is a zero-manpower command wrapper over its direct subordinate Units or intact nested armies. Its commander and deputy command those subordinate commands; they do not create another fighting echelon inside a Unit.

Every persistent fighting Unit has its own commander and deputy outside that Unit's fighting establishment. Those two people already occupy the Unit's top command echelon. Internal 1,000/500/100 command billets may exist only when their nominal span is strictly smaller than the Unit's authorized fighting establishment. Therefore a 1,000-man Unit is `Unit commander + deputy -> 2 x 500 -> 10 x 100`, never `Unit commander + deputy -> internal 1,000 commander`. A 2,000-man Unit is `Unit commander + deputy -> 2 x 1,000 -> 4 x 500 -> 20 x 100`. This rule applies recursively and does not change when casualties make a Unit understrength.

The commander of a command group remains a real combat-capable person. If present, that person can move, fight, use personal equipment/techniques, be wounded, killed, captured, isolated, exhausted, or routed. Personal combat never gets averaged into the unit's ordinary-soldier capability. Command loss triggers deputy/succession/standing-doctrine handling; directly absorbing orphaned child units increases the superior's direct load immediately.

## Aggregate recruitment provenance

Ordinary recruitment is a conserved aggregate transfer from an exact source owner stratum or manpower pool into an accounting pool or homogeneous unit. Recruitment never creates one person record per recruit. The destination inherits source capability and demographic inputs when causally relevant. A named standout, commander, specialist, prisoner, casualty, award recipient, or recurring NPC materializes only through a separate transaction that identifies one real surviving body exactly once.

## Household and personal military networks

State command, household ownership, and personal-retainer loyalty are separate authorities. A general may command state troops while also belonging to or maintaining a smaller enduring household or personal-retainer network; commanding state manpower never converts it into private property.

`state/force/household-military-networks.json` owns recognized household/personal-network profiles and references to any exact materialized private forces. A `profile_only` network records existence/classification only: it has no exact headcount, composition, training, equipment, horses, supplies or combat capability and cannot fight. Exact forces materialize only through lawful population/manpower sources, wealth or treasury support, equipment/horse/supply sources, political/legal authority, elapsed organization/training where required, and normal conservation transactions. Missing source evidence fails closed.

Household military quality is derived from real source population, selection, training, equipment, resources and history. No noble house receives House Tang capability by analogy. Royal households must resolve crown/palace state manpower separately from genuinely dynastic/private retainers before ownership is persisted. Personal troops, house troops, state troops, mercenaries and allies remain distinct ownership classes even when temporarily combined under one command tree.


## Generic non-sovereign organizations

Schools, guilds, escort bureaus, trade associations, professional orders, clan associations, religious groups, and local societies that become materially persistent use the shared independent-organization owner. The owner records institutional identity, exact treasury, headquarters, policies, existing-person members/leaders, facilities/projects, and linked force refs while owning zero population itself. Founding/funding/withdrawal moves real silver. Joining never creates a body. An armed branch remains a normal force/formation owner. Organization projects consume the organization's exact treasury plus real local labor/material through the shared project engine.

# Injury, Health, and Death

`game/data/mechanics/injury.json` is the structured numerical authority for wounds, armor interaction, impairment, bleeding, shock, infection, recovery, equipment failure, and lethal-state resolution.





`game/rules/characters.md` and `game/rules/careers.md` owns the universal character kernel, development, materialization, and featured-character rules. `game/rules/doctrine.md`, `game/rules/doctrine.md`, `game/rules/loadouts.md`, and `game/rules/careers.md` own reusable force profiles. This file owns detailed personal combat, injury, command, bodyguard, scouting, and operational resolution.

Equipment state uses standardized type, quantity, condition band, location, and loadout assignment.

## Injury record

Each wound records:

- exact zone and subzone;
- cut, thrust, blunt, crush, burn, or mixed channel;
- severity band 0-4;
- bleeding, pain, structural damage, neurological or organ risk;
- immediate functional impairment by domain;
- contamination and infection risk;
- treatment, immobilization, and evacuation;
- expected review and recovery conditions.

Toughness and Composure affect shock, pain response, and continued action. They do not erase severed tissue, broken bone, organ damage, blood loss, or infection.

## Recovery

Healing requires elapsed time, adequate nutrition, rest, sanitation, treatment, and freedom from repeated trauma. Recovery reviews update bleeding, pain, infection, stability, structural healing, and impairment. Serious wounds may leave permanent limitations, scars, chronic pain, or reduced recovery even after the acute wound closes.

## Treatment, stabilization, infection, and recovery stages

Treatment is an action, not an automatic Medicine check. The caregiver must have access, time, a safe enough position, light, water, dressings, tools, assistance, and authority or consent where required. Use `game/rules/personal-force.md#opposed-field-procedure` with Medicine, relevant knowledge, tools, evidence from examination, and patient cooperation.

Each serious wound stores four current tracks: `bleeding`, `structural_stability`, `contamination_pressure`, and `systemic_stress`. Stabilization can stop or reduce bleeding, protect airway, restore alignment, immobilize a fracture, clean contamination, reduce pain, and prepare evacuation. It cannot regrow destroyed anatomy.

Infection pressure is calculated by `game/data/mechanics/injury.json`.

Fixed clinical factor levels and infection-pressure bands are defined only in `game/data/mechanics/injury.json`. Review only when time, symptoms, care, environment, or wound state changes. The same unchanged state cannot randomly become infected twice.

Recovery has explicit stages: `unstable -> stabilized -> early_healing -> functional_rehabilitation -> healed_with_or_without_sequelae`. A wound advances at most one stage per scheduled review unless a decisive intervention or catastrophic deterioration is recorded. Required time is a floor, not a guarantee. Reopened wounds, starvation, forced march, contamination, poor immobilization, and repeated impact can reverse a stage.

Recovery progress is calculated by `game/data/mechanics/injury.json`.

All terms use current capability or fixed levels and are recorded with the review. When sufficient progress and minimum biological time are both met, advance the stage. Permanent impairment is assessed only after anatomy is stable enough to judge, and must identify the damaged structure and affected domains.

## Aging
Age controls bodily development, realistic access, and current performance; it is not a cosmetic number. Every named person and consequential unit stores age, life stage, health, body, current age-scaled values, preserved prime targets, potential, routine, and next age review.

Ordinary current-performance ceilings by age are defined only in `game/data/mechanics/training.json`. They are ceilings, not automatic values. A character may remain far below them without supported training and experience. Physical and high-speed martial ceilings mature, peak, and later decline; command, judgment, civil skill, and knowledge can peak later and decline more slowly. Saved injury, illness, exceptional health, or a documented special circumstance may adjust a ceiling, but never creates free ability.

A documented prodigy or unusually early martial upbringing may exceed the ordinary age cap only by the saved exception allowance. It does not grant adult authority, anatomy, judgment, legal capacity, command experience, or immunity.

On an age review, recovery, fertility, maturation, and age cap may change. Raising a cap grants no free learned skill. Children may gain limited biological physical development when nutrition and health support it. Skills, command, and civil capability require actual education, practice, work, duty, instruction, or reviewed experience. Background routines may be quarterly-batched from real household, tutor, school, apprenticeship, or service owners.

Peak acceleration, recovery, tissue resilience, and sustained physical output may later decline. Judgment, technique, strategy, diplomacy, governance, and knowledge may remain stable or improve with supported experience. Major illness, injury, deprivation, or exceptional health can alter the ordinary curve.

## Consciousness, incapacity, and dying state

Unconsciousness, incapacity, dying, and death are separate. A person may be unable to fight but still breathe, speak, crawl, surrender, receive treatment, or survive transport. Record airway, breathing, circulation, neurological function, temperature, blood loss, and immediate hazards when material.

A dying state requires an unresolved lethal process such as uncontrolled major bleeding, airway failure, critical chest injury, severe brain injury, drowning, burning, poison, or systemic infection. It owns an exact next review based on the process. Rescue requires a physically and medically plausible intervention before that review. Death occurs only when the causal process crosses an irreversible anatomical or physiological condition.

## Death and estate

Death follows anatomy and physiology, not hit points. On death, freeze the character record, resolve body location, personal inventory, issued property, debts, prisoners, dependents, offices, commanded troops, inheritance, burial, reports, and succession. The killer does not automatically receive the estate or command.

## Universal mortality and no plot armor

Tang Wei, canonical heroes, rulers, children, officers, companions, named soldiers, and anonymous people use the same anatomy, physiology, fire, water, falling, disease, poison, starvation, and battlefield rules. No one is protected because they are famous, future-canon, player-aligned, narratively important, or high-stat. No character receives plot armor. The same complete physical state produces the same result regardless of identity.

Death still requires a real causal chain. The engine may not kill someone for drama, protect someone to preserve history, or hide a lethal result behind anonymous casualties. Exact position, assignment, awareness, armor, bodyguards, terrain, missiles, weapon contact, wounds, evacuation, treatment, and elapsed time determine exposure and survival.

A canonical trajectory ends or replans if its required person dies. Player death resolves succession, estate, companions, troops, contracts, and continuation through `RUNTIME.md#death-succession-and-continuation`; it is not automatically rewound. Offscreen death requires an owned event and exact consequences, not an unobserved narrative assertion.

## Anonymous-to-named emergence

Anonymous people are real but aggregated. Materialize a person when individual identity becomes consequential through command, repeated interaction, exceptional action, unique injury, captivity, testimony, sensitive knowledge, relationship, promotion, defection, inheritance, or special training.

Promotion is atomic:

1. select the exact source formation and personnel band;
2. remove one living anonymous member and their issued equipment;
3. derive a plausible body, attributes, skills, background, service history, current condition, and goals from the band and source population;
4. transfer custody and pay status;
5. create one permanent character record;
6. update formation, pool, inventory, household, and appointment owners.

A named person is never rerolled or returned to anonymity.

## Capability contracts, offscreen routines, and lossless materialization

Every living named character retains a capability contract: current permanent attributes and skills, current plan, legal routine or assignment, location, equipment access, knowledge boundary, development focus, and the review batch or exception that advances them offscreen.

Offscreen time grants no automatic growth. Permanent credits require an actual scheduled activity with attendance, challenge, instruction or opposition, equipment, recovery, and assessment. Stable routines may be batch-settled, but every awarded credit must retain evidence and may be awarded only once.

When an anonymous person becomes consequential:

1. subtract exactly one person from one source band or unit tranche;
2. derive a permanent individual variation vector consistent with that source;
3. transfer exact equipment, money, wounds, location, service, knowledge, and relationships;
4. assign one stable character ID and one display name;
5. preserve the variation vector permanently and never reroll it.

Returning a named character to background residency removes only transient scene detail. A named person never becomes anonymous again.

## Materialization integrity contract

A named character's persistent contract includes identity, body, permanent capabilities, development-state reference, injuries, location, plan, affiliations, equipment, household, and knowledge references. Runtime materialization adds only crossed due results, actual loadout, temporary resources, received information, local geometry, readiness, facing, targets, and action queues.

On dematerialization, commit only causally supported persistent changes and discard ephemeral scene state. Unknown required state remains unknown and blocks consequential resolution; it is never filled for convenience. Validation compares authoritative fields and causal receipts directly. No character hash, checkpoint hash, or commit lineage is required.

## Record closure and death estates

Death, dissolution, completion, failure, delivery, inheritance, or destruction closes the current record at an exact timestamp or explicitly bounded time. Property, command, prisoners, dependents, obligations, and claims transfer before the former owner is removed from current registries. The closed record becomes a compact terminal receipt; it is not left active and is never copied as a second owner.

## character resolution and development

Tang Wei and active major characters use full individual records. Permanent minor personnel remain named-unit or unit state with exact capability and health distributions. A person is separated only when full-sheet materialization is causally required. Distant important NPCs use compact activity contracts and gain only evidence supported by saved activity. Becoming named never rerolls or changes potential. Combat evidence and technical training remain distinct.

## registered-health-clocks

Every active injury, illness, treatment, recovery, disability, captivity, prisoner-health, disease-unit, or death-processing object owns a next stage or interruption trigger discoverable through the world-processing registry. A stable healthy state may be interruption-driven; an active wound or illness may not lack a review.

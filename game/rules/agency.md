# Commands, Actions, Consent, and Narration

This file owns the Warring-States action grammar and narration constraints. Repository loading, transactions, checkpoint, and persistence discipline are defined in `RUNTIME.md`.

## Action classification

A message is **read-only** when it asks about rules, known facts, inventory, status, comparisons, hypotheticals, or a correction to unaccepted narration. Read-only messages do not advance time or create a transaction.

A message is **state-changing** when Tang Wei moves, speaks in-world, trains, waits, travels, fights, gives an order, spends or transfers resources, changes equipment, accepts an appointment or contract, recruits, dismisses, appoints, delegates, opens a report, or otherwise changes an owner or the world clock. State-changing messages require a revision-locked transaction and one atomic Git commit before narration.

## Resolution order

For every declaration, determine:

1. **Intent** — the exact result Tang Wei is trying to cause.
2. **Legality and authority** — charter, household, office, command, contract, custody, and consent limits.
3. **Capacity** — health, fatigue, skill, time, equipment, mounts, formation readiness, personnel, supply, money, and information.
4. **Demand** — opposition, terrain, distance, weather, command friction, political risk, market conditions, and uncertainty.
5. **Outcome** — deterministic resolution from the current state and recorded transaction seed.
6. **Consequences** — elapsed time, casualties, injuries, morale, cohesion, reputation, custody, information, finance, appointments, and successor events.

The player's declared objective is not a guaranteed result. Do not invent additional commitments merely because they would be convenient.

## Player agency and consent

Never author Tang Wei's private thoughts, emotions, allegiance, voluntary dialogue, spending, appointments, contracts, surrender, mercy, execution, equipment changes, family decisions, political promises, or irreversible escalation. Resolve only what the player actually declared.

Standing orders may execute routine reversible work inside saved authority. Stop for Tang Wei when a matter is exceptional, irreversible, materially risky, outside delegated authority, politically binding, strategically committing, or changes protected custody.

## Standing-order boundary

Routine gate inspection, fire response, stable care, medical triage, warehouse rotation, ordinary patrols, scheduled instruction, and administrative processing may continue under `owner:standing_orders`. Staff must escalate altered contracts, exceptional cargo, identity disputes, restricted equipment, major spending, appointments, deployment, hostile contact, prisoner disposition, family commitments, and political or military alignment.

## Information

World truth is not player knowledge. Tang Wei may learn offscreen events only through direct observation, a delivered report, a witness, a courier, a spy network, physical evidence, changed behavior, shortages, casualties, movement, public proclamation, or another valid information path. State the source and reliability when uncertainty matters.

## Combat and casualties

Personal combat preserves weapon state, handedness, mount state, reach, geometry, timing, injury, fatigue, armor, terrain, and intent. Formation combat preserves frontage, depth, cohesion, morale, command, supply, ammunition, mounts, terrain, weather, casualty state, and retreat routes.

Anonymous casualties remain unit counts unless identity becomes consequential through command, relationship, promotion, capture, investigation, unique equipment, memorial importance, or recurring narration. Named and materialized targets remain exact. Tang Wei controls surrender, pursuit, prisoner disposition, mercy, execution, and other irreversible treatment of named or featured opponents.

## Narration

Narrate only committed results and only from Tang Wei's available knowledge. Preserve exact time, location, who is present, visibility, equipment custody and readiness, injuries, fatigue, mount state, formation position, supply, command authority, and legal authority. End at the next consequential decision rather than deciding it for the player.

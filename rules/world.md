# World Arcs, Canon, Characters, and Succession

Kingdom characters and events begin as mutable pressure. No named character is protected, guaranteed to rise, or forced into canon timing. Succession follows actual vacancy, authority, survival, support, and information.




## Authority

This file owns universal arc, pressure, event, review, propagation, successor, and hot-projection rules. Current arc facts live in their durable current-save owners. `state/index/owners.json` and the active-scene dependency set are generated projections and never override typed owners.

## Active arc contract

Every active executable arc or pressure retains:

- stable arc or pressure ID;
- authoritative owner and layer;
- status and current stage;
- actors and affected factions or institutions;
- last review time;
- last material progress time;
- next actor and next action;
- target and location;
- executable next-event reference or other authoritative clock owner;
- earliest time, deadline, or bounded recheck;
- committed resources and access routes;
- real blockers and the actor capable of addressing them;
- stakes, escalation paths, resolution and failure conditions;
- successor candidates and selection inputs;
- visibility, knowledge boundary, and delivery paths.

An active arc without an executable next move must name a real blocker and bounded recheck. Generic text such as "continue organizing" or "monitor the situation" is not an executable plan unless an actor, action, target, means, and clock are present.

## Arc states

Supported states include:

- `active`;
- `blocked`;
- `hidden`;
- `ignored_by_tang_wei`;
- `dormant`;
- `transformed`;
- `closed`;
- `cancelled`;
- `failed`;
- `resolved_independently`.

Hidden and ignored arcs continue from their own actors. Tang Wei's absence or ignorance is not a blocker. Dormant trajectories store prerequisites and activation triggers rather than pretending to execute a current plan.

## Progress stages

Progress stages are:

`latent_pressure -> advocacy_or_intrigue -> organizing -> mobilizing -> active_operation -> contact_or_siege -> settlement_or_aftermath -> terminal`

`preparation_blocked` is a reversible status projection, not a successful progress stage. Save `blocked_from_stage`, exact blockers, the responsible actor, and the bounded recheck. When prerequisites become true, resume from the blocked stage and advance at most one stage unless a decisive event supports more.

## Event authority and lifecycle

An event object owns its executable scheduled time, lifecycle, affected owners, causal basis, and result-event links.

Lifecycle:

`scheduled -> due -> processing -> resolved`

or terminal:

`cancelled | superseded | failed`

Every event records:

- event ID;
- status;
- scheduled time;
- processed time when terminal;
- actor, action, target, and location;
- visibility and information consequences;
- affected owner references;
- processing commit ID;
- result classification;
- result-event IDs;
- compact causal receipt.

A terminal event cannot process again. An active owner's next-event reference may point only to `scheduled`, `due`, or `processing` state.

## Recurring review successor rule

When an event reviews an arc, pressure, operation, faction project, cell network, or trajectory, all linked state changes are one atomic transaction.

A continued recurring review must:

1. Evaluate the current review.
2. Update every affected durable owner.
3. Create the next review event in `scheduled` state.
4. Put the new event ID in the current event's `result_event_ids`.
5. Update every linked active owner to reference the new event.
6. Set every mirrored next-review time to the new event's exact `scheduled_at`.
7. Rebuild the hot arc stack and due queue.
8. Validate the successor chain before the current event becomes terminal.

A resolved, cancelled, superseded, or failed review event cannot remain the `next_decision_event_ref`, `next_event_ref`, or equivalent future reference of an active owner.

If no successor event is created because the arc closes, fails, or transforms, the same transaction must close the old active slot and install the selected successor arc or an explicit dormant state. A global arc cannot vanish without a stored successor or dormant global condition.

## Single scheduling authority

For event-driven arc reviews, the successor event is the authoritative clock. Pressure, operation, faction, cell, and trajectory owners reference it. They may mirror its exact time for retrieval, but they do not own independent competing schedules.

Validation requires:

The successor event time, every mirrored active-owner review time, and the due-queue time must all resolve to the same authoritative clock owner and exact timestamp.

All matching fields must reference the same event or authoritative clock owner.

A non-event clock is allowed when the domain authority is explicitly a message, movement, training program, contract, project, payroll schedule, or other scheduler. Hot projections must point to that exact owner and time.

## Hot arc stack

`state/scene.json` identifies the current dependency boundary, while `state/index/owners.json` routes to every non-null active layer required by the current campaign, including immediate, legal or financial, personal force, career, equipment, regional, and global layers when present.

Each projection records:

- layer;
- arc or owner ID;
- stage;
- authoritative file or owner;
- next authoritative event or clock owner;
- exact next clock.

Missing, extra, duplicate, stale, terminal-event, or mismatched projections fail validation. The hot due queue is rebuilt from authoritative clocks, never maintained as an independent source of truth.

## Crossed-clock processing

When time reaches or crosses an arc clock:

1. Load its authoritative event or scheduler.
2. Load every listed affected owner.
3. Retrieve additional owners required by causal dependencies.
4. Resolve earliest-first by exact timestamp and stable ID.
5. Classify the review as `progressed`, `blocked`, `transformed`, `closed`, `cancelled`, or `failed`.
6. Record causal basis, affected actors and factions, changed owners, material consequences, information consequences, and next exact clock.
7. Recalculate later clocks if the result changes their prerequisites, route, actor, or feasibility.

Generic maintenance prose cannot resolve an active arc.

## Review timestamps

Every review updates `last_review_at`.

Update `last_progress_at` only when the arc materially changes, including stage, resources, membership, route, detection, readiness, casualties, authority, information, alliances, opposition, or feasible next action. A no-change review may leave `last_progress_at` unchanged.

## Propagation

World propagation requires persistent event, message, movement, operation, or project objects. A phrase such as "mobilization causes investigation" is not state until each causal link has an actor, action, target, location, timing, visibility, resources, and possible results.

Processing a propagation link updates every materially affected owner, including factions, settlements, routes, treasuries, formations, relationships, knowledge, markets, and successor arcs when applicable.

## Information and visibility

Hidden world truth, delivered reports, testimony, accusation, rumor, false rumor, propaganda, and Tang Wei's inference remain distinct.

Tang Wei learns only through a valid path such as direct observation, witness, report, messenger, intercepted document, interrogation, investigation, traveler, market change, arrest, refugee movement, or public proclamation. Processing a hidden event does not automatically reveal it.

## Deterministic successor selection

A successor candidate is eligible only when all saved requirements are true. Score eligible candidates from saved outcome, surviving actors, urgency, location, commitments, reputation, knowledge, unresolved obligations, threat, opportunity, resources, and timing. Ties resolve by stable candidate ID.

The receipt stores:

- selected successor;
- score and causal basis;
- eligible rejected candidates;
- ineligible candidates and failed requirements;
- installed active layer or dormant state.

Successor selection may not be improvised after export.

## Validation failures

Turn resolution and checkpoint export fail when:

- an active arc has no executable next move and no real blocker;
- an active owner's next event is missing or terminal;
- a recurring terminal review has no successor while its linked arc remains active;
- event, pressure, trajectory, hot projection, and due-queue clocks disagree;
- a due entry lacks an authoritative owner;
- a required review is past due without receipt, delay, or blocker;
- an affected owner named by an event was not updated or explicitly recorded as unchanged;
- a global arc closes or transforms without an installed successor or dormant global state;
- hidden information is revealed without a causal path;
- an event can process twice;
- a generated hot projection overrides durable owner state.

Validation names the exact owner, event, field, and expected successor relationship. Preserve the prior valid commit on failure.

## world-registry-integration

Every active arc, pressure, operation, recurring review, message, and movement registers its authoritative due/trigger timing in `state/time/frontier.json`. `state/reg/registry-processes.json` provides process discovery/visibility/event-type metadata, and `state/reg/registry-process-contracts.json` routes process semantics; each process contract lives at `state/reg/process-contracts/<owner_id>.json`. Neither duplicates frontier clock state.

Monthly world-close events process registered cold domains and create their next close before resolving. An arc cannot progress merely because a monthly close exists; it still requires actors, means, action, target, blockers, and causal results.

## four-layer-player-facing-arc-projection

The backend retains every registered event and pressure. The normal interface projects:

- Immediate: current scene, next irreversible decision, and near clocks.
- Personal and household: House Tang, debt, contracts, personnel, equipment, career, health, and relationships.
- Regional: Qin administration, markets, banditry, military operations, and local factions.
- Global and historical: dynastic instability, Julu mobilization, distant wars, and major trajectories.

An arc record includes stage, actors, resources, information, blockers, next action, next clock, divergence conditions, possible successors, visibility, and status. Player-facing output reveals only information that reached Tang Wei through a valid path.




# Kingdom Canon and Mutable Warring States Chronology

The campaign begins in 245 BCE at the opening era of Kingdom. One Kingdom-style display name is authoritative for each person. No alias array, duplicate historical name, later title, future equipment, future relationship, future unit, or future accomplishment is imported.

Canon provides people, starting pressures, institutions, reputations already earned by the opening boundary, and possible trajectories. It does not provide plot armor, guaranteed survival, future knowledge, guaranteed promotion, or forced battles. Historical and manga-inspired actors use the same causal rules as campaign-original people.


A later canon event occurs only if its living actors, authority, goals, knowledge, relationships, forces, budget, routes, supplies, and triggering pressures still exist. Changed causes create changed events.

When an important person dies or becomes unable to act, the vacancy procedure searches living full-featured candidates, then recurring exact candidates, then qualified people in the relevant unit. A unit candidate materializes once from a stable seed and receives no free competence, memory, reputation, property, or equipment. Failure to find a suitable successor may create an acting appointment, political contest, fragmentation, conquest, or collapse.

Ordinary troops are not pre-named for narrative decoration. Exact identity follows `rules/agency.md`; a new name must correspond to one real person and one causal need.


## canonical-name narration

## Cold-active canonical identities

The canonical named roster is current state under `state/char-roster/index.json` and its routed shards. Do not hard-code roster counts in rules; derive the current count from that index. Cold-active status is a retrieval representation, not dormancy or nonexistence.

A cold-active canonical identity keeps one canonical display name and world route/source. It does not own fabricated exact statistics, inventory, office, location, knowledge or personal clock until causal evidence requires materialization. When materialized, resolve a lawful source institution/unit/population slot, conserve one real person, reconstruct supported life/development/history, and preserve the canonical identity.

Cold-active identities receive no free progression and do not freeze. Their ordinary aging, occupation, training, health exposure and career movement are covered through source owner/institution/unit aggregate processes. Direct command, office, travel, interaction, injury, capture, investigation or another exact dependency wakes the person into exact/lite process coverage.

Unknown affiliation/office remains unknown rather than being invented to fill the roster.

## Canonical identity resolution

Current canonical identity coverage is derived only from `state/char-roster/index.json`; rules never own a hard-coded roster count.

Representation tiers are:

- **Full exact character:** complete independently simulated actor when exact agency/body/capability/knowledge/relationship state is causally required.
- **Individual-lite person:** persistent named person with exact body/capability/equipment/service state and compact narrative state.
- **Cold active routed identity:** canonical named person with a current route/source and activation triggers, but no fabricated exact body/location/office/capability until causally materialized.
- **Aggregate person:** ordinary population, soldier, official, worker, student or dependent represented through the appropriate unit/institution/population owner.

A cold active identity materializes only after a lawful source route and existing person/slot are resolved. It receives no free elite skills, state affiliation, age, office, equipment, knowledge, future accomplishment or personal history. Materialization conserves one real person exactly once.

## Development parity

Every person develops through real activity. Exact/lite people use exact activity contracts. Cold active identities receive only source-owner-supported aging, training, experience, health exposure and career movement through force/court/institution/unit/population processes. Materialization reconstructs that supported history without double-awarding time, credits, injury or equipment.

## Scheduler rule

Cold active routed identities own no periodic personal clock by default. State, force, court, institution and unit processes cover ordinary offscreen time. A personal clock is created only by active command, office, travel, interaction, training, injury, capture, investigation or another exact dependency. This prevents hundreds of unsupported individual reviews during long horizons while keeping life-course fairness.

## Vacancy sequence

1. Eligible living full-featured character.
2. Eligible living recurring exact character.
3. Qualified identified person in the relevant unit.
4. Deterministically materialized person from that unit.
5. Acting leader, vacancy, contest, fragmentation, conquest, or collapse.

No successor receives free competence, history, equipment, loyalty, survival, or plot protection.


## canonical-name narration

Every full capability-profile identity, active exact external actor, routed named identity, and cold-active routed identity retains one canonical display name. Whenever the identity is legitimately referenced, reported, encountered, or materialized, narration uses that canonical name. Cold status suppresses irrelevant loading, not the name.

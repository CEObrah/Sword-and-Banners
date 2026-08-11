# World Arcs, Canon, Characters, and Succession

Kingdom characters and events begin as mutable pressure. No named character is protected, guaranteed to rise, or forced into canon timing. Succession follows actual vacancy, authority, survival, support, and information.




## Authority

This file owns universal arc, pressure, event, review, propagation, successor, and hot-projection rules. Current arc facts live in their durable current-save owners. `state/index/owner-index-gold.json` and the active-scene dependency set are generated projections and never override typed owners.

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

`state/scene.json` identifies the current dependency boundary, while `state/index/owner-index-gold.json` routes to every non-null active layer required by the current campaign, including immediate, legal or financial, personal force, career, equipment, regional, and global layers when present.

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

Every active arc, pressure, operation, message, movement, institution, House, faction, population process, or state process that can change while cold is attached to an explicit causal host or exact scheduled owner. `state/runtime.json` owns the bounded due-event queue, host `resolved_through`, host `safe_through`, and the next known successor boundary. `state/index/owner-index-gold.json` resolves mutable owners directly.

A recurring host review may compact any number of identical quiet recurrences arithmetically when no intervening causal consequence requires exact resolution. It wakes only because its own due event is reached, an outward consequence reaches it, or an explicit gameplay command materially touches its domain. There is no global monthly person, faction, House, force, or region scan.

A causal review cannot progress an arc merely because time crossed a recurrence. It still requires lawful actors, knowledge, authority, resources, means, action, target, blockers, and causal results. When the review schedules a successor, `safe_through` extends to one second before that known successor unless another causal boundary is earlier.

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

Ordinary troops are not pre-named for narrative decoration. Exact identity follows `game/rules/agency.md`; a new name must correspond to one real person and one causal need.


## Source identities and current people

`game/data/people/latent-identities.json` is a static source-name catalog. A catalog entry does not assert that the named person currently exists, occupies an office, has a location, owns equipment, knows anything, or receives development. It therefore has no personal clock.

Current people are represented only when the world requires them: exact characters, individual-lite people, anonymous role-slot incumbents, or aggregate population/unit members. An anonymous role-slot incumbent ages, develops, becomes unavailable, retires, dies, or triggers succession only through the owning institution/process. The slot stores functional continuity, not a secret biography.

A source-canon name may bind to a current person only after current existence, source population/unit/role, age or life stage when needed, and one conserved body are established from live authority. Materialization imports only supported source history and creates no free capability, office, equipment, knowledge, relationship, achievement or survival.

## Development parity

Every current person develops through real activity. Exact/lite people use their registered activity/process coverage. Aggregate people inherit only the development, health exposure and career movement earned by their population, unit, institution or role process. Representation compression never grants an advantage.

## Scheduler rule

Static identity-catalog names have no scheduler entries. Anonymous role-slot incumbents settle with their owning institution/process. Exact personal clocks exist only when exact personal causality requires them.

## Vacancy sequence

1. Eligible living full-featured character.
2. Eligible living recurring exact character.
3. Qualified identified person in the relevant unit.
4. Deterministically materialized person from that unit.
5. Acting leader, vacancy, contest, fragmentation, conquest, or collapse.

No successor receives free competence, history, equipment, loyalty, survival, or plot protection.


## canonical-name narration

Every materialized named person retains one canonical display name. A static source-catalog name is used only after the identity is lawfully bound to a current person; catalog presence alone never creates that person.

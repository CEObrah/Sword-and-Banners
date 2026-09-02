# Player Interface

Natural language is the player interface. The player describes what Tang Wei tries to do in ordinary language. ChatGPT interprets the action first, realizes reversible scene behavior directly, and consults the runtime mechanic catalog only for contested or durable consequences.

## Interaction modes

Unlabeled gameplay text is normal in-character play. `IC:` explicitly marks gameplay. `OOC:` is read-only discussion, planning, explanation, inspection, comparison, feasibility, or hypotheticals. `OOC DEV:` is development or maintenance of the runtime, rules, repository, deployment, Skill, or integration and is not gameplay.

A message can contain multiple blocks. Resolve them in order.

## Bare continuation is presentation, not elapsed-time consent

A bare player message such as `continue`, `continue game`, `go on`, `keep going`, or an equivalent continuation phrase means: refresh current authority and resume the current scene or causal process from the exact current campaign timestamp. By itself it does **not** authorize `advance_time`, waiting, travel, training, marching, formation movement, or any other persistent action.

Resolve a bare continuation in this order:

1. If fresh context already contains a player-facing event, report, message, pressure, question, or decision, narrate that material at the current timestamp and provide grounded decision scaffolding when a real choice exists. Do not advance time merely to look for something newer.
2. If an established scene has an obvious reversible non-decision continuation, continue the lived scene at the same campaign timestamp within the scene-local narration contract.
3. If the player previously authored an explicit standing policy such as `wait until the courier answers`, `continue training until interrupted`, `hold here until summoned`, or `skip until something significant happens`, a later bare continuation may resume that **already-declared** elapsed-time policy within its saved scope.
4. If there is no standing wait/skip policy and no obvious reversible continuation, present the exact current situation and lawful next actions without mutating campaign time. Do not create content by silently fast-forwarding.

A runtime `pending_wake.continue_command` or similar resume hint is mechanical capability, not natural-language authorization. Never interpret the ordinary word `continue` as consent to execute that command unless the player's current or persisted standing intent actually includes elapsed time.

Before any persistent write whose only apparent trigger is a continuation phrase, verify that the player has separately authorized the action being written. If not, stay read-only and narrate.

## The player does not write commands

**The LLM is the command orchestrator.** It understands the player's natural-language objective first, then uses fresh mechanic-family discovery as a consequence toolkit. It may sequence several exact runtime operations beneath one continuing player intent and one continuous narrated scene, refreshing context between writes and stopping only for a real new decision or hard causal boundary. Do not force one player turn per command and do not expose command selection as gameplay. Scene start/end is not derived from command count.

Never require the player to know command names, JSON payloads, revisions, request IDs, repository paths, refs, or schemas.

Internally, a consequential action follows:

`natural-language intent -> semantic interpretation -> reversible scene realization -> mechanic discovery only where consequences require it -> exact contract -> preview/execute -> fresh context -> narration`

If the runtime cannot represent a hard persistent consequence, carry the attempt and conversation as far as lawful scene truth permits, then explain only that consequential limitation OOC if it matters. Never convert a missing mechanic into fictional inability to speak, ask, threaten, joke, move locally, or manipulate an established mundane object.


## Action versus consequence

Accept the player's attempted action before asking which mechanics apply. A missing `punch`, `put_bowl_on_head`, `interrupt_meeting`, or similarly bespoke command is irrelevant. If Wei says `I punch him`, the semantic meaning implicates personal combat. If he places an established bowl on someone's head and nobody meaningfully resists, that may remain scene realization. If he later smashes that same bowl into someone's skull, combat, improvised-weapon/contact, injury, witnesses, and related consequences become relevant because the **meaning** changed. When a mundane prop may later cross into combat, persist its first observed `object_state` with the bounded form/material/condition descriptor. When Wei later takes up or uses that same object, persist a second `object_state` that cites the first fact and repeats the exact descriptor. Only that matching two-stage fact may be promoted into transient combat physics. Never invent the prop and its combat classification in one mechanical step, and never reuse one object's provenance to classify a different object.

For compound declarations such as `I draw my sword, attack Han, and tell everyone else to stay back`, preserve all stated components. Resolve the attack mechanically, realize the concurrent speech naturally, and let witnesses exercise their own agency. Never translate the declaration into only the first backend operation and silently discard the rest.

The semantic representation may contain actor, target, method, goal, manner, constraints, sequencing, spoken words, and player-declared intent. It must never contain `the enemy fails to dodge`, `the guard agrees`, `the general gives me command`, `the troops obey`, or another outcome owned by mechanics or NPC agency.

## Do not edit campaign JSON manually

Normal gameplay must never ask the player to edit campaign JSON. Persistent mutations belong to the runtime's semantic command/transaction systems. OOC DEV repairs also avoid casual direct state edits; confirmed bad campaign truth uses an explicit repair or migration path with provenance.

A player-facing wording preference is not campaign truth. Do not edit a formation, person, House, place, or other mutable owner merely to change how the GM labels it in prose. Keep presentation aliases in the presentation layer unless the player explicitly requests a real in-world rename and the runtime supports that consequential change.


## Read tools

Use `get_play_context` first for every live turn. It is the bounded entry point for current state and capability.

Use targeted continuation reads only when material:
- `get_person_sheet` for an exact permitted person;
- `inspect_game_object` for an exact permitted or lawfully revalidated object;
- after the natural-language action is already understood and a hard consequence is implicated, `get_command_family` for one advertised **mechanic family**, then `get_command_contract` for the one selected mechanical operation when exact payload guidance is needed;
- `list_controlled_formations` when the controlled-formation hot window is truncated;
- `list_known_information` when saved player knowledge falls outside the hot window;
- `list_interaction_handles` when triggered interaction/message handles are truncated;
- `search_world_reference` for bounded cold identity/background lookup only;
- `ooc_audit` for read-only diagnostics.

Treat every count/truncated marker as a completeness signal. A hot window is not a lifetime limit and omission is not proof of absence. Continue using returned cursors or exact rehydration; never guess hidden IDs.

## Writes

Each persistent write is one exact semantic command, but one natural-language player declaration may contain reversible scene components and several sequential consequential steps under the same standing intent. A new command gets a fresh request ID and uses the exact expected revision returned by fresh context.

`preview_command` is read-only. It validates the proposed semantic command and returns the complete command object plus a short-lived preview attestation when executable.

`execute_command` receives that exact command and matching attestation. Do not reconstruct either. After committed or duplicate execution, refresh play context before narrating persistent aftermath.

## Player interaction attempts versus world responses

Court, social, petition, audience, report, request, and similar actions may be represented by `interaction_action` when persistence or cross-turn continuity is useful. Ordinary conversation itself does not require that command. When a substantive targeted `speak` is persisted because cross-turn continuity matters, treat it as response-bearing by default; the player should not need an extra backend flag merely to make a human reply remain live. An explicitly final/non-response-bearing line may suppress the thread; defaults must never override that semantic intent.

The command records only Tang Wei's voluntary side: target/process, action, his exact player-supplied statement when any, posture, and controlled accompanying formations. It must not contain caller-authored NPC reaction, access, acceptance, appointment, rank, vacancy, permission, or other external result.

New player-facing raw `scene_consequence` writes are not a valid escape hatch. If a proposed other-side response would itself establish a hard consequence, invent or mechanically verify hidden information, create remote delivery, or make a binding decision that the runtime has not established, stop before inventing that consequence. An established co-located speaker may still disclose an already-existing private fact they lawfully know; that line remains attributed speech unless another authority verifies the claim. This is not a gag order on a co-located person: ordinary reversible acknowledgement, opinion, objection, advice, humor, bargaining, questioning, or conversational refusal may be AI-realized immediately from lawful scene/NPC cognition context.

`seek_contact` can record an attempt to find a lawful receiving channel at Tang Wei's exact current location when no exact official/office is yet available. It does not create that official, office, audience, or access.

An interaction attempt by itself does not advance time. If the player chooses to wait, use the current `advance_time` contract. A later reply becomes fact only when the runtime actually establishes one.


### Live scene sessions and attributed speech

When fresh context exposes an active scene session, treat it as reversible conversational continuity. `interaction_action` records Wei's side of an exchange. The advertised `scene_session_action` may open/close an explicit scene, persist an important NPC attributed statement that is already safe to realize from lawful context, or record a salient reversible scene-local fact for fresh-chat continuity. `record_speech` and `record_fact` have no mechanical-consequence authority. Speech may resolve a generic open conversational thread, including a question, request, petition, offer, proposal, or other response-bearing move in the active session. A scene fact is only observed local continuity such as object placement, room-level positioning, a visible reaction, or a shared premise; it cannot substitute for combat, inventory, money, travel, command, relationship, or other hard-state mechanics.

The LLM owns whether that persistence session should exist. A narrative scene can start, continue, transition, or end without one. When continuity across commands or fresh contexts is useful, use `gm_scene_context.scene_direction.scene_lifecycle` to route through the interaction family, load `scene_session_action`, and open or close the presentation session automatically. The player never needs to say `open scene` or `close scene`. Do not let an open session keep a spent scene talking, and do not let a completed runtime command terminate a still-living scene.

Do not persist every sentence or gesture. Use ordinary narration for disposable connective dialogue and staging. Persist only speech or reversible scene details that materially improve future continuity. An NPC may disclose an already-existing private fact the speaker lawfully knows; persist the attributed statement and use the information mechanic when a durable epistemic record is needed. A formal order, acceptance/refusal, invented secret, transfer, travel, injury, relationship change, or other binding result belongs to its actual mechanic instead.

## Recruitment campaigns

The player may describe selective recruiting in natural language, including broad campaigns such as inviting thousands of applicants and reducing them through several trials before accepting a small final cohort. ChatGPT selects the advertised recruitment-campaign commands and registered selection profiles; it never invents applicant statistics, hidden thresholds, or free bonuses.

Treat the pipeline distinctly:

`real population reservation -> registered background mix -> registered selection -> optional real training -> accepted cohort`

Selection discovers/retains qualified people and returns rejected candidates to their source population; it does not train them. Training consumes real time, food, capacity, and development law. Final acceptance is cohort-first. Materialize an individual later only when a conserved member becomes individually important.

## Contested and hidden-future actions

Sword protects contested combat and broad future advancement from preview probing. Battle, personal combat, siege assault, and broad time advancement can have valid previews that expose readiness but not outcome. ChatGPT executes the declared action once when the player has committed to it.

## Multi-step intent

A natural-language request can imply several runtime steps. Carry intent through obvious prerequisites only while no new material choice appears.

Example: `I accept the review and go to Kanyou.` may require an interaction attempt, departure/travel, arrival, and a later runtime-established review boundary. Resolve sequentially and refresh after each write. Stop when route, timing, danger, cost, conflicting obligations, command allocation, access, or another consequence creates a new decision.

A remote objective, formation, officer, invitation, report, or suggested option never implies that Tang Wei has traveled there. If current authority places Wei and the relevant target at different locations, keep that separation explicit until the player has actually declared or already delegated travel and the runtime commits it. A bare `continue` after hearing about a remote target does not choose that destination.

After a committed travel action, the player-facing handoff must make movement legible: identify the origin and destination, compress or stage the journey at a level appropriate to its importance, state the authoritative arrival time, and identify which declared companions/formations actually moved. Carry forward committed fatigue, supply, weather, interruption, or arrival consequences when material. If the refreshed location did not change, never write prose that implies arrival, border presence, or physical contact with a remote formation.

## Player-facing mechanics

During ordinary play, present mechanics through lived consequences. Exact mechanical detail is appropriate when asked OOC or when a number is relevant to the decision, such as money, personnel, travel time, casualties, supplies, or authority.

Do not expose OAuth, Git hashes, revisions, request IDs, attestation strings, command payloads, or validators in IC narration.

## Current environment

Fresh `get_play_context` may expose a top-level `environment` object for Tang Wei's exact current location. Treat it as authoritative derived runtime context for that campaign instant: season, light band, weather, wind, temperature band, visibility, ground condition, and the registered mechanical effect channels.

The environment object is derived deterministically from authoritative campaign time, world seed, static location/climate rules, and the environment contract. It is not an invitation to invent conditions for another place or another time. Use `environment.mechanical_effects` only through runtime-owned mechanics; never add a second rain, darkness, cavalry, missile, agriculture, forage, market, or travel modifier in narration.

Environment does not own mutable fires, smoke events, flood-control works, siege damage, gate status, office hours, staffing, institutional availability, or other exact campaign state. Those remain with their existing owners. A weather/light transition is not automatically a scheduler wake.

## Freedom of action

Choice menus are examples, not limits. The player may ignore them and type any natural-language action. Do not reduce play to repeated menus when the world can continue naturally. Surface choices only at genuine decision points.

## Actionability of restrictions

A mechanically correct refusal is not a complete player interface when the player cannot tell what must change. When fresh runtime context exposes a safe readiness or eligibility reason, explain who or what is blocked, why, and the known condition or time at which it can become available again. Never expose hidden state to explain a restriction.

Treat recurring opaque rejection as a runtime-interface defect worth surfacing through the live-play review loop. Do not make the player discover required enum values, nullable fields, custody conditions, readiness rules, or legal prerequisites by repeated failed guesses when the runtime can safely advertise them.

## Progressive command discovery

Fresh play context exposes mechanic families rather than the full internal operation catalog. Do not consult them to decide what Wei is allowed to attempt. After the natural-language action is understood and a hard consequence has been identified, demand-load only the relevant family through `get_command_family`, choose the mechanical operation that owns that consequence, then call `get_command_contract` for that operation only. Do not infer omitted fields from memory and do not bulk-load unrelated families or contracts.

The internal human-scale consequence surface includes persistent command-group/retinue state, retinue training, investigations, commission requests and decisions, medical treatment, commitments, and richer information creation/delivery. These are runtime resolvers/persistence owners, not a player action vocabulary. They retain the same preview, attestation, transaction, chronology, agency, and knowledge guarantees as older mechanics.

`active_player_processes` may surface actionable investigations, commission requests/offers, and commitments after a fresh chat. These are bounded routing cues, not complete hidden process state. Inspect the exact advertised ref only when its detail changes the next decision.

## Retinue and command-group interaction

A command group is organization, not manpower. It may bind exact people and formations into a persistent command relationship, store deputy/successor/communication/standing-order data, and develop familiarity through real elapsed training, but it never creates soldiers or duplicates a formation's personnel.

Use the projected personal retinue root and immediate child groups for discovery. Inspect deeper subordinate groups only by exact advertised ref. A named person attached to a retinue remains the same conserved person; an attached formation remains owned by its normal military authority.

## Information and investigation

Player-known information now carries epistemic kind, holder-specific confidence, source/channel, subject and evidence where available. A saved claim is not automatically world truth. Preserve the distinction among direct observation, report, inference, rumor, testimony, document, captured document, estimate and official report.

An investigation records a question and lawful work. It may discover only evidence/claims that already exist through authoritative state and routing. Never let the caller specify the culprit, clue, hidden cause, or result. Investigation output changes what an investigator can lawfully know, not the underlying truth.

# Player Interface

Natural language is the player interface. The player describes what Tang Wei wants to do in ordinary language; ChatGPT translates that intent into the current runtime's advertised semantic surface.

## Interaction modes

Unlabeled gameplay text is normal in-character play. `IC:` explicitly marks gameplay. `OOC:` is read-only discussion, planning, explanation, inspection, comparison, feasibility, or hypotheticals. `OOC DEV:` is development or maintenance of the runtime, rules, repository, deployment, Skill, or integration and is not gameplay.

A message can contain multiple blocks. Resolve them in order.

## The player does not write commands

Never require the player to know command names, JSON payloads, revisions, request IDs, repository paths, refs, or schemas.

Internally, a consequential action follows:

`natural-language intent -> fresh play context -> one current semantic command -> exact contract if needed -> preview -> exact execute -> fresh context -> narration`

If the runtime cannot represent a persistent action, explain the limitation OOC rather than pretending it happened.

## Do not edit campaign JSON manually

Normal gameplay must never ask the player to edit campaign JSON. Persistent mutations belong to the runtime's semantic command/transaction systems. OOC DEV repairs also avoid casual direct state edits; confirmed bad campaign truth uses an explicit repair or migration path with provenance.

## Read tools

Use `get_play_context` first for every live turn. It is the bounded entry point for current state and capability.

Use targeted continuation reads only when material:
- `get_person_sheet` for an exact permitted person;
- `inspect_game_object` for an exact permitted or lawfully revalidated object;
- `get_command_contract` for one advertised command when exact payload guidance is needed;
- `list_controlled_formations` when the controlled-formation hot window is truncated;
- `list_known_information` when saved player knowledge falls outside the hot window;
- `list_interaction_handles` when triggered interaction/message handles are truncated;
- `search_world_reference` for bounded cold identity/background lookup only;
- `ooc_audit` for read-only diagnostics.

Treat every count/truncated marker as a completeness signal. A hot window is not a lifetime limit and omission is not proof of absence. Continue using returned cursors or exact rehydration; never guess hidden IDs.

## Writes

Each persistent write is one semantic command. A new command gets a fresh request ID and uses the exact expected revision returned by fresh context.

`preview_command` is read-only. It validates the proposed semantic command and returns the complete command object plus a short-lived preview attestation when executable.

`execute_command` receives that exact command and matching attestation. Do not reconstruct either. After committed or duplicate execution, refresh play context before narrating persistent aftermath.

## Player interaction attempts versus world responses

Court, social, petition, audience, report, request, and similar actions may be represented by the advertised `interaction_action` surface.

The command records only Tang Wei's voluntary side: target/process, action, his exact player-supplied statement when any, posture, and controlled accompanying formations. It must not contain caller-authored NPC reaction, access, acceptance, appointment, rank, vacancy, permission, or other external result.

New player-facing raw `scene_consequence` writes are not a valid escape hatch. If the runtime has not established the other side's response, stop before inventing it.

`seek_contact` can record an attempt to find a lawful receiving channel at Tang Wei's exact current location when no exact official/office is yet available. It does not create that official, office, audience, or access.

An interaction attempt by itself does not advance time. If the player chooses to wait, use the current `advance_time` contract. A later reply becomes fact only when the runtime actually establishes one.

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

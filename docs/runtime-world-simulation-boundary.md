# Runtime World-Simulation Boundary

## Constitution

The runtime is the laws of the world, not the menu of possible fictional actions.

Player and NPC intent is open-world. Hard consequences are closed-world and must be resolved through authoritative mechanics. The absence of a bespoke command can block an unsupported persistent consequence, but it must never make ordinary conversation or reversible scene behavior impossible.

## Intent before mechanics

Interpret the full natural-language declaration before looking for a mechanic. Preserve actor, target, method, spoken words, constraints, goal, sequence, and concurrency that the player actually supplied. Never add success, consent, obedience, fear, injury, access, appointment, or another external outcome to the player's intent.

After the action is understood, discover only the mechanical consequence families actually implicated. The command registry exists for safe mutation and adjudication; it is not an action vocabulary.

Examples:

- `What do you think?` is ordinary dialogue unless a hard consequence follows.
- `Can my army lead the vanguard?` is immediately a live request. A binding vanguard assignment still belongs to military authority.
- `I punch him` is a physical attack attempt. Combat mechanics resolve contact and injury whether or not a command named `punch` exists.
- `I put the bowl on his head` is normally reversible scene realization. `I smash the bowl into his skull` implicates combat, contact, anatomy, injury, witnesses, and possibly legal/social consequences.
- A compound declaration may contain reversible speech or movement around one or more persistent mechanical writes. Do not discard the nonmechanical parts merely because a hard resolver is also required.

## Conversation

Conversation is free; consequences are governed.

A present established NPC may acknowledge, answer, refuse conversationally, ask, object, advise, joke, interrupt, speculate from lawful evidence, or speak to another present person without a bespoke Python responder. Response-bearing conversational moves are generic threads, not only literal questions. Requests, petitions, offers, proposals, and other moves can remain live until responded to or abandoned with the scene.

Attributed speech proves what was said, not that its content is objectively true. Binding orders, appointments, transfers, contracts, formal acceptance/refusal, hidden factual revelations, movement, injury, and other hard consequences still require their actual authority.

Do not solve human interaction by adding phrase recognizers for every anticipated sentence. Structured semantic topic metadata may help route an already-understood consequential request; legacy text matching exists only where old persisted records require compatibility.

## GM-private omniscience, NPC cognition, and hidden information

Player knowledge and GM direction context are different projections.

The AI GM may receive explicitly marked **GM-private current-scene truth** that Tang Wei does not know. This may include exact character state, private goals, stable behavior profiles, hidden motives, real wounds, tactical intent, concealed participants, or other current facts needed to direct people and combat coherently. The restriction applies to **player-facing disclosure**, not to the GM's ability to understand the world.

Use private truth as backstage direction. An NPC may disclose, conceal, refuse, mislead, bargain, protect a private goal, or react to something Wei cannot yet see. Only the resulting observable speech/action and lawful inference become player-visible. If speech reveals a mechanically significant secret, use the appropriate information authority to persist the revelation. GM-private truth never grants hard consequences by itself.

## Fact levels

1. **Ephemeral presentation**: posture, pauses, tone, ordinary local handling and positioning. No write required.
2. **Scene continuity**: authority-false sessions, attributed speech, shared conversational premises, and response-bearing threads. These support continuity but never grant mechanical truth.
3. **Adjudicated consequences**: contested outcomes produced by the relevant resolver.
4. **Hard campaign truth**: time, injury, death, money, equipment, manpower, formation state, command, office, territory, training gains, relationships when mechanically significant, contracts, custody, travel, and other durable facts.

Narration can establish levels 1-2 within fresh lawful context. Only mechanics and transactions establish levels 3-4.

## Deterministic longitudinal simulation remains authoritative

Do not weaken the systems that motivated the runtime. Off-screen training, development, recovery, aging where registered, cohort/unit experience, faction and institutional activity, projects, economy, populations, military logistics, world arcs, travel, wars, and scheduled obligations continue through runtime chronology whether or not the GM narrates them.

Screen time must not determine mechanical development.

## Transaction boundary

Persistent writes retain exact revision checks, preview attestation, idempotent request IDs, conservation, authority validation, WAL/receipts, and durable commit. A natural-language declaration can span reversible scene realization plus sequential exact mechanical writes under standing intent. Each hard write remains an authoritative transaction unless/until a separately designed composite transaction owner exists.

Do not fake atomic multi-resolver behavior in narration. If a later hard step creates a new protected choice or cannot lawfully proceed, stop there while preserving everything already committed and the player's remaining stated intent where safe.

## Anti-regression rules

A proposed feature or fix is architecturally suspect if it:

- adds a bespoke command only so a character can utter or understand an ordinary human sentence;
- adds keyword matching as the primary way to understand a player request;
- exposes the whole command catalog before understanding intent;
- requires a runtime write for every sentence, gesture, or local reversible action;
- lets attributed speech mutate objective truth;
- treats GM-private hidden state as Wei's knowledge, hidden-thought narration, or choice premises;
- lets narration bypass combat, authority, conservation, economy, time, knowledge, or persistence rules;
- makes off-screen development depend on narration.

Release tests should preserve both master invariants:

1. Absence of a bespoke runtime command never makes an otherwise plausible ordinary conversation or reversible action impossible.
2. AI narration alone never creates a hard mechanical consequence without adjudication and commitment by its authoritative owner.

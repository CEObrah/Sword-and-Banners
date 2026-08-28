# Scene Contract

This reference defines the boundary between hard simulation truth and fluid human roleplay. The two RPGs may mirror this contract independently, but each repository remains self-contained.

## Three layers of truth

1. **Hard world truth** is runtime-owned. Movement over meaningful distance, elapsed campaign time, injury, death, combat outcomes, money, resources, equipment ownership, training gain, office, formal orders, contracts, promises with mechanical consequences, relationship changes, secrets, custody, formation movement, territory, diplomacy, and other irreversible consequences require runtime authority.
2. **Bounded scene truth** is GM-owned inside fresh runtime limits. Present NPCs may acknowledge, clarify, advise, object, disagree, speculate from lawful evidence, ask follow-up questions, joke, interrupt, discuss established facts, and express nonbinding opinions without a bespoke mechanic for every sentence.
3. **Connective presentation** is freely reversible. Posture, pauses, looking at a map, sitting, standing, handling already-established objects, tone, silence, and a few plausible steps inside the established space do not require a write.

Be permissive about reversible fiction and strict about persistent consequence.

## Active scene sessions

Treat an active scene session as presentation and continuity state, not a second mechanics engine. Sword scene presence must still agree with exact current person owners and Wei's exact location. It may identify the exact established participants, location, process, purpose, agenda, open conversational threads, and a soft scheduling boundary. It never moves bodies, creates access, grants authority, spends resources, changes relationships, or proves hidden facts.

A planned meeting duration is a soft boundary. Do not dismiss participants merely because the nominal duration has elapsed while Wei is still lawfully present and the scene remains active. The session ends because it is completed, Wei leaves, a hard interruption occurs, the player explicitly skips to the conclusion, or another lawful scene supersedes it.

When the player begins a substantive conversation with an established, exactly co-located NPC and no active session exists, establish a lightweight `conversation` session as the first reversible continuity step whenever question tracking or multi-exchange continuity will matter. Do this as part of carrying the player's declared intent; never require the player to ask for a session or expose the session mechanic IC. Do not create a session merely for a greeting, a trivial acknowledgement, or a one-line exchange that needs no durable thread.

## NPC response envelopes

When `get_person_sheet` or fresh context exposes an `npc_response_envelope`, use it as GM-private performance guidance. It defines what the NPC may safely do in ordinary dialogue and what kinds of consequences ordinary speech cannot establish.

Generate nonbinding dialogue from player-safe facts only. Preserve uncertainty. Do not use private motives, hidden database truth, external history, or model knowledge as factual dialogue content. The envelope may shape delivery and professional posture, but it never authorizes a new fact.

Ordinary reversible dialogue does not need a runtime write every sentence. Persist an important line only when durable conversational continuity materially benefits later play. Persisted scene speech is an **attributed statement**, not objective world truth.

## Speech versus mechanical speech acts

Examples that may remain bounded scene truth when supported by player-safe context:
- professional advice;
- disagreement or objection;
- clarification of an already-established order;
- speculation explicitly framed as uncertainty;
- a personal opinion;
- a follow-up question;
- ordinary NPC-to-NPC cross-talk.

Examples that cross into hard world truth and require the relevant runtime mechanic:
- issuing a new binding order;
- granting or revoking authority, office, access, rank, custody, money, equipment, or troops;
- accepting or refusing a contract, oath, alliance, surrender, marriage, or other mechanically consequential commitment;
- revealing new secret factual information not already player-visible;
- causing movement, injury, combat, recruitment, relationship change, or another persistent consequence.

## Question lifecycle

A player `ask` inside an active session creates an open conversational thread only when the runtime records it as such. An important persisted answer may resolve that exact thread. Closing a scene abandons its remaining unresolved threads rather than leaving them falsely active for weeks.

Do not treat a historical recent question as active merely because it was asked recently.

## Continuation and time

Bare `continue` resumes the active scene or already-declared process at the exact current campaign timestamp. It does not authorize a broad time skip.

If substantive conversation has clearly consumed material campaign time, commit conservative in-scene elapsed time only through the runtime's explicit active-scene time policy. There is no artificial maximum scene duration. A true hard causal interruption may end the reversible scene.

Finishing the meeting, leaving it, preserving it while some time passes, and explicitly skipping to its conclusion are distinct intents. Never infer one from bare `continue`.

## Durable scene history

Durable attributed speech exists to make fresh-chat continuity possible without turning conversation into a second rules engine. Preserve speaker, listener/session context, attribution kind, time, and player-safe basis when supported by the runtime. Historical speech can establish that **the speaker said something**, not that the statement was factually correct.

Keep live context bounded. Recent speech may be projected in the hot handoff while older attributed history remains available through exact history reads/shards.

## Decision UX

Do not append a menu after every paragraph. Continue reversible scene flow until a genuine unresolved Wei decision, material tradeoff, protected commitment, or hard causal boundary arrives. At that point, narrate the decision-relevant facts first and scaffold choices only when useful.

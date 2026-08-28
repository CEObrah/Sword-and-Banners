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

## Interaction depth and differentiation

Treat substantive interaction as a sequence of **distinct conversational jobs**, not as prose wrapped around a state summary. This rule applies across councils, family scenes, command meetings, audiences, negotiations, briefings, interviews, camp conversations, institutional exchanges, and other multi-turn social scenes.

Before giving a materially relevant present NPC substantive dialogue, retrieve that person's permitted sheet when the compact cast does not already supply enough role/voice context. In a crowded scene, retrieve only the two to four people whose contribution matters to the current beat rather than loading the whole room.

Use `npc_response_envelope.performance_cues` as follows:
- `public_role_context` and `role_lens` identify the lawful public or social perspective from which the person can naturally question or emphasize established facts;
- `professional_lenses` identify player-visible areas of demonstrated service competence that may shape what the person notices, tests, clarifies, or advises about;
- explicit safe speech/temperament cues, when present, may shape delivery but never create knowledge, motive, authority, or outcome;
- absence of personality cues is **not** a reason to make everyone sound alike. Differentiate speakers first through role, expertise, rank, relationship, audience, and the immediate agenda.

For each speaker selected into the beat, give the line a different job whenever the situation supports it: question an assumption, identify a practical constraint, distinguish fact from estimate, object to a consequence, compare alternatives, ask who bears a burden, clarify authority, recommend a reversible next step, or expose an unresolved tradeoff. Two NPCs should not merely paraphrase the same runtime field unless the repetition itself is meaningful disagreement, confirmation, correction, or hierarchy.

### Shared premises and motivated questions

Before writing a substantive question, separate **shared premises** from **live unknowns**. A fact that fresh context already establishes for everyone in the exchange, or that is logically entailed by the immediate chronology and position, normally belongs in common ground rather than in a question-and-answer sequence.

Every substantive NPC question should have a conversational motive. It should obtain genuinely missing information, test a disputed assumption, force prioritization, expose a tradeoff, clarify responsibility or authority, challenge a proposal, or determine what should happen next. Do not use dialogue to audit runtime fields or translate a structured briefing into an interrogatory checklist.

Do not make people solemnly reconfirm the obvious merely because a status field exists. For example, if Qin is still staged at Kanyou awaiting authority to enter Wei and no separate scout, border, or contact event establishes otherwise, do not make a commander ask whether battle contact is confirmed just because an intelligence record contains `contact_status`. The shared premise is that the field armies have not yet met the enemy. A useful military question would instead pursue a live unknown: which reports are reliable enough to shape the first march, which enemy movements are actually observed, or what reconnaissance can narrow the estimate before entry, when those questions are supported by player-safe evidence.

Confirmation is natural when the fact is surprising, disputed, newly changed, legally consequential, or the speaker needs another person to commit to the wording. Otherwise let established facts remain implicit. Characters do not need to recite obvious premises to prove that they understand them.

Avoid the **analytic chorus**: one speaker states a fact, another restates the same inference, a third says `correct`, `better`, or otherwise validates it, and the conversation advances field by field. A second speaker should materially change the point through disagreement, consequence, burden, alternative, authority, or a genuinely new question. If they add nothing, compress the reaction or leave them silent.

Do not manufacture a question solely to give a speaker a conversational job. If a person's role adds nothing useful to the current beat, let that person remain silent, react nonverbally, or wait for a later point where their perspective matters.

When the player-safe facts are thin, use **uncertainty as playable material** instead of inventing detail. A strategist can ask which evidence supports an estimate; a logistician can ask what burden a route must carry; a legal official can question what authority a seal actually grants; a family member can ask what a decision means for the household. The question or opinion may be generated from the safe lens, but any factual answer that would establish new world truth still requires lawful evidence or runtime authority.

In a substantive multi-person scene, normally let at least two materially relevant NPC voices perform distinct conversational jobs before returning to narrator compression, unless hierarchy, urgency, silence, or focus gives a concrete reason not to. Runtime summaries are briefing material for the GM, never dialogue scripts.

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

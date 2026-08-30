# Runtime Character Behavior

Use this rule for ordinary interaction with an already-routed or materialized character. Load `game/rules/characters.md` only when creating/materializing a person, changing representation depth, or resolving character structure.

## Authority order

For an active character, behavior comes from the smallest relevant authoritative set: current goals, duties, appointments, relationships, knowledge, health, recent consequences and any explicit saved mutable behavior. Cold records under `game/data/people/behavior-profiles/` are non-authoritative static guidance and are demand-loaded only by registered consumers that have a mechanical reason to use them. They are never copied into hot state merely because a character appears in a scene.

Commander cognition is one registered consumer. It may translate only explicitly registered behavior cues into a bounded decision-policy bias; capability remains the primary input, the bias grants no combat strength or hidden information, and famous commander overrides remain canonical military style. Ordinary scene behavior remains constrained by current player-visible facts and the Game Master Skill rather than by an automatic hidden-profile loader.

Missing personality detail is unknown, not permission to invent filler. A behavior-light exact character acts conservatively from current duty, knowledge, incentives and proven traits until distinctive behavior is supported by current authority.

## Runtime decision rule

A character chooses only among actions they can know, attempt and authorize. Weight current goals, institutional duty, relationships, risk, health/fatigue, available resources, prior consequences and established behavior. Rank, canon importance and narrative attention never grant free competence or information.

Do not infer the player character's voluntary thoughts, dialogue, commitments or choices.

## Knowledge and relationships

Use relationship/knowledge authority for consequential social state. Shared affiliation is not automatically a personal relationship. Knowledge arrives only through valid observation, records, reports, messengers, scouts, spies or other saved paths.

## Updating an NPC

Persist only changes caused by the event: health/fatigue to the body/condition owner; capability through registered development/training; relationship/knowledge/reputation to their authorities; role/office/assignment/command to institutional owners; goals only when causally revised; behavior only when repeated or decisive evidence makes it persistent. Do not write narration summaries or developer/audit commentary back as character facts.

## Source identity catalog

A static source identity is a canonical name/source hint, not a current actor. Do not load or simulate it during ordinary interaction. If the name becomes causally relevant and no current person owner exists, use `game/rules/characters.md` to prove current existence and materialize from one lawful source person/role without importing future achievements or later-series state.

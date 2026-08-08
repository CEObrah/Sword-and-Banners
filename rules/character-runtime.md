# Runtime Character Behavior

Use this rule for ordinary interaction with an already-routed or materialized character. Load `rules/characters.md` only when creating/materializing a person, changing representation depth, or resolving character structure.

## Authority order

For an active character, behavior comes from the smallest relevant saved set:

1. explicit bespoke `behavior` or compact personality state;
2. when inline behavior is insufficient, the one load-on-demand support profile routed by `data/people/behavior-profile-index.json`;
3. current goals, duties, appointments, relationships, knowledge and recent history;
4. established role/career/canon characterization already saved in the owner;
5. general human constraints from this rule.

Missing personality detail is unknown, not permission to invent filler. A behavior-light exact character acts conservatively from current duty, knowledge, incentives and proven traits until distinctive behavior is supported by source/campaign evidence.

Before a behavior-light exact character enters sustained direct interaction, independent high-stakes decision-making, recurring command, or a scene where personality can materially change the result, perform a behavior-depth check. If the owner ID is routed by `data/people/behavior-profile-index.json`, load exactly that profile, then only causal source/canon hints, office/duty, relationships, knowledge, goals and campaign history. Persist a compact behavior anchor only when those sources support it. Insufficient evidence keeps the character role-driven and restrained. Brief routine contact does not require forced deepening.

## Runtime decision rule

A character chooses only among actions they can know, attempt and authorize. Weight current goals, institutional duty, relationships, risk, health/fatigue, available resources, prior consequences and established behavior. Rank, canon importance and narrative attention never grant free competence or information.

Do not infer the player character's voluntary thoughts, dialogue, commitments or choices.

## Knowledge and relationships

Use relationship/knowledge authority for consequential social state. Shared affiliation is not automatically a personal relationship. Knowledge arrives only through valid observation, records, reports, messengers, scouts, spies or other saved paths.

## Updating an NPC

Persist only changes caused by the event: health/fatigue to the body/condition owner; capability through registered development/training; relationship/knowledge/reputation to their authorities; role/office/assignment/command to institutional owners; goals only when causally revised; behavior only when repeated or decisive evidence makes it persistent. Do not write narration summaries or developer/audit commentary back as character facts.

## Source identity catalog

A static source identity is a canonical name/source hint, not a current actor. Do not load or simulate it during ordinary interaction. If the name becomes causally relevant and no current person owner exists, use `rules/characters.md` to prove current existence and materialize from one lawful source person/role without importing future achievements or later-series state.

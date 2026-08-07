# Runtime Character Behavior

Use this rule for ordinary interaction with an already-routed or materialized character. Load the full `rules/characters.md` only when creating/materializing a person, changing representation depth, or resolving a character-structure question.

## Authority order

For an active character, behavior comes from the smallest relevant set of saved owners:

1. explicit bespoke `behavior` / compact personality state;
2. if inline behavior is absent, the one cold profile routed by `data/people/behavior-profile-index.json`;
3. current goals, duties, appointments, relationships, knowledge and recent history;
4. established role/career/canon characterization already saved in the character owner;
5. general human constraints from this rule.

Never manufacture a deep personality merely because a field is absent. Cold or behavior-light exact profiles may act conservatively from their current duty, knowledge, incentives and proven traits until distinctive behavior is supported by canon/source evidence or campaign events. Do not restore mass-generated trait filler.

Before a behavior-light exact/cold profile enters sustained direct interaction, independent high-stakes decision-making, recurring command, or a scene where personality materially changes the outcome, perform a behavior-depth check. If its owner ID appears in `data/people/behavior-profile-index.json`, load exactly that one profile first, then load only its routed source/canon hints, current office/duty, relationships, knowledge, goals and campaign history. Persist a compact behavior anchor only when those sources support it. If evidence is insufficient, keep the character role-driven and restrained rather than inventing quirks, fears, humor, ambitions or private opinions. A brief routine encounter does not require forced deepening.

## Runtime decision rule

A character chooses only among actions they can know, attempt and authorize. Weight current goals, institutional duty, relationships, risk, health/fatigue, available resources, prior consequences and established behavior. Rank, canon importance and narrative attention never grant free competence or information.

Do not infer the player character's voluntary thoughts, dialogue, commitments or choices.

## Knowledge and relationships

Use the relationship/knowledge authority for consequential social state. Shared affiliation is not automatically a personal relationship. Knowledge must arrive through valid observation, records, reports, messengers, scouts, spies or other saved paths.

## Updating an NPC

After a material event, persist only changes actually caused by the event:

- injuries/health/fatigue to the body/condition owner;
- capability development through the registered development/training process and receipts;
- relationship/knowledge/reputation changes to their dedicated authority;
- role, office, assignment and command changes to their institutional owners;
- goal changes only when the character causally forms/revises them;
- behavior traits only when repeated or decisive evidence makes the trait persistent.

Do not write summaries of narration back as new facts. Do not create developer/audit/version commentary inside character state.

## Cold-active routed identities

A cold-active canon identity is a real named world identity but not a fabricated exact current body sheet. Load its one routing shard. If it becomes causally active, use `rules/characters.md` to reconstruct/materialize only the state justified by current time, source organization, age, known canon anchor, campaign history and conserved source population. Future achievements or later-series ranks are never back-projected.

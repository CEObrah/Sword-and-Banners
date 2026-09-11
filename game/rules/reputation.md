# Reputation, Renown, Fame, Prestige, Notoriety, and Infamy

This rule owns social reputation semantics for the Warring States world. Current sparse reputation state lives under `state/reputation/`; deterministic update/propagation mechanics live in `game/data/mechanics/reputation.json`; game-specific dimensions and audience segments live in `game/data/reputation/`. Reputation is **perceived social information**, not an objective character stat.

## Separate concepts

- **Reputation**: what one specific audience currently believes about a subject.
- **Renown**: recognition for meaningful achievements inside that audience.
- **Fame**: public recognition inside that audience. There is no omniscient global fame score.
- **Prestige**: esteem/status the audience assigns from known achievement, office, lineage, honors, wealth, patronage, rank, or institutional standing.
- **Notoriety**: recognition driven by danger, controversy, criminality, scandal, disruption, or feared conduct.
- **Infamy**: strongly negative notoriety carrying hatred, stigma, or moral condemnation.

These are not synonyms and none substitutes for legal authority, personal relationship, or actual capability.

## Audience-specific and sparse

Every stored value belongs to one subject + one audience. Use audience IDs such as the pattern declared in `game/data/reputation/audience-segments.json`. Do not create reputation entries for audiences that have no evidence. Absence means **unknown/not established**, not neutral 50.

A subject may be a person, unit, team, force, institution, faction, or settlement. Units and organizations can earn reputations for discipline, contract reliability, steadiness, brutality, security, or other supported dimensions without giving every member an identical personal reputation.

## Knowledge gate

Reputation never teleports. An audience changes only after direct observation or a valid report/communication path reaches it. Separate direct personal knowledge, relationship, rumor, inference, official report, and verified evidence. A person who directly witnessed an event may know more than their broader audience profile.

Known rank, office, title, uniform, banner, seal, or affiliation can influence treatment as a direct institutional fact if the observer actually knows/sees it. Do not invent a reputation score merely because a title exists.

## Relationship is not reputation

Personal affection, trust, obligation, rivalry, resentment, and loyalty remain relationship state. A rival can hate a highly respected commander; a family member can love someone while doubting their military competence. Load both authorities when both matter.

## Causal reputation events

Create a reputation event only when an event could materially alter how observers/audiences perceive a subject. Examples include a witnessed battle result, command success/failure, public rescue, scandal, atrocity, contract fulfillment/breach, major duel, appointment, official honor, public speech, exposed deception, famous technique, successful mission, public disaster, or documented act of mercy/cruelty.

A reputation event records the underlying event/time, actual witnesses or reporting origin, perception signals, visibility, evidence quality, report routes, and delivery receipts. The underlying world event remains authoritative for what physically happened. Reputation history records how that event was perceived/transmitted.

Do not create `+7 fame` by narration. Apply the deterministic evidence update in `game/data/mechanics/reputation.json`. Duplicate report lineage cannot double-apply the same evidence. Independent corroboration can increase weight.

## Propagation and misinformation

Reports travel through existing messenger, intelligence, institution, market, military, court, or faction processes. Do not create a second global reputation clock. A report can be delayed, lost, censored, exaggerated, distorted, contradicted, or countered only when saved sources/incentives/channels support that transformation. Preserve the original event separately from the report's claim.

A secret event with no surviving witness/report path creates no broad fame merely because the repository knows it happened.

## Mechanical effects

Reputation never directly modifies body, weapon, stamina, raw unit combat stats, treasury, authority, or knowledge. It may condition other mechanics when those rules make social perception relevant: meeting access, initial expectations, recruitment interest, contract terms, morale expectations, enemy caution, patronage, political attention, security posture, propaganda, or willingness to listen. Always cite the relevant audience profile and causal domain.

Prestige cannot command troops without legal/delegated authority. Fame cannot reveal secrets. Infamy does not force fear in everyone.

## Recognition

When deciding whether an NPC recognizes Tang Wei or another subject: check direct personal knowledge first, then audience membership/access and that subject's audience profile. Location, profession, information access, recency, visible identifiers, introductions, and current role may matter. If the evidence does not support recognition, the NPC does not recognize the subject.

## Memory and decay

Reputation has exact-time decay classes. Routine/ephemeral attention fades faster than durable military or institutional renown; truly historical events may persist. Decay reduces confidence/evidence mass and recognition according to `game/data/mechanics/reputation.json`; it does not rewrite the physical historical event. Current office/title effects come from current institutional facts rather than immortal memory.

## Current-state storage

`state/reputation/index.json` is derived routing only. Each current subject record lives in `state/reputation/subjects/<subject_id>.json` and points only to audience profiles that actually exist. Audience profiles are authoritative current perception state. Event files are load-on-demand causal history and should not be loaded for ordinary interaction unless provenance, propagation, or dispute matters.

When updating reputation: persist the underlying event first; establish witnesses/report origin; write the reputation event; propagate only along valid routes at the correct time; update delivered audience profile(s); update derived indexes; validate; then narrate reactions only for actors who can know.

## Setting-specific dimensions

Military and political reputation often travels through officer reports, court memorials, merchants, prisoners, returning soldiers, proclamations, envoys, and rumor. Battlefield command, strategy, logistics, siege skill, discipline, courage, contract reliability, honor, generosity, mercy, cruelty, political danger, security, administration, and patronage may matter to different audiences. A court rival can hate a general while sincerely rating that general as highly competent.

## Player agency

Reputation may change because of witnessed player actions, but it never supplies Tang Wei's private motive or intention. OOC discussion and previews do not create reputation events.

# Recruitment, Service, Careers, and Command

Current career authority is split by function rather than collected in a paper formula registry. `game/data/mechanics/military-career.json` owns the formal rank ladder and rank/billet/span separation. `runtime/sword_runtime/military_merit.py` derives bounded battle-service appraisal from committed battle evidence. `runtime/sword_runtime/court_rewards.py` owns court review and any actual reward decision. `runtime/sword_runtime/commander_cognition.py` changes command decision policy without granting combat power. `game/data/mechanics/career.json` now contains only the runtime-consumed mercenary pay overlay plus the invariant that promotion grants no permanent capability.

## Separate concepts

Institutional membership, formal rank, billet, command authority, assigned strength, qualification, experience, merit, reputation, and reward remain separate facts. Promotion or appointment never grants attributes or skills. Assignment of an army does not transfer ownership of its bodies.

## Recruitment and materialization

Recruitment consumes real population through the current recruitment/cohort system. Named or person-lite materialization reclassifies exactly one already-conserved cohort body. The materialized person's capability is sampled deterministically from that source cohort's actual attribute, skill, professional-skill, aptitude, and spread distributions, including its settled training/service development. Generic role-template stat packages are not a production authority.

## Military merit and court accountability

A battle-service appraisal may consider command role, result, relative force adversity, casualty stewardship, duration, and whether the action occurred in an operational contact. It is evidence for later institutional review, not an automatic promotion. Formal court reward remains a separate process and may grant or withhold lawful rewards according to the evidence and current authority. The current implementation does not pretend that every possible political or order-compliance factor has been adjudicated when no saved evidence exists.

## Command behavior

Commanders differ through cognition and institutional decision policy: commitment thresholds, reserve use, patience, initiative, information discipline, revision pressure, and pursuit limits. These policies affect what commanders decide, not the physical strength of their soldiers. Command hierarchy, span, officer cadres, communications, formation cohesion, and logistics remain owned by their existing runtime systems.

## Mercenary service economics

Mercenary offer acceptance uses the professional-soldier monthly wage from `game/data/mechanics/economy.json` multiplied by the current runtime-consumed mercenary pay factor in `game/data/mechanics/career.json`. Exact contracts own their own employer, amount, term, status, payment, deployment, completion, and breach facts.

## Invariants

- recruitment and materialization conserve people;
- rank, billet, command, merit, reward, and capability remain separate;
- promotion grants no permanent stats;
- cognition changes decisions rather than damage or troop strength;
- court review does not infer missing evidence;
- current mechanics are described by their active runtime owners, not by unused formula prose.

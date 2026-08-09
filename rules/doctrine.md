# Doctrine, Tendencies, and Orders

## Doctrine layers

1. Institutional doctrine
2. Unit-type doctrine
3. Unit-specific doctrine
4. Commander interpretation
5. Temporary battle orders

Higher-numbered layers may override lower layers within lawful authority. Temporary orders never rewrite permanent doctrine.

## Permanent doctrine and reform

A doctrine record represents one current durable military standard under a stable semantic doctrine ID. A materially different durable standard uses a distinct meaningful semantic doctrine ID.

A unit's `doctrine` reference is the durable standard it can presently execute as doctrine. Doctrinal reform requires a real decision, dissemination, instructor preparation, drills, equipment where needed, time, and familiarization. A unit does not switch its doctrine reference until the required transition has actually completed under training/development mechanics. Partial preparation grants no automatic target-doctrine benefit; only effects independently supported by completed training, temporary orders, commander capability, equipment and current unit state may apply.

When a material doctrine change is being prepared, keep the target doctrine and its training/familiarization work in the causal reform/training transaction rather than cloning the unit or inventing a numeric doctrine revision. Once the transition completes, change the unit's doctrine reference atomically and retain only the receipts/history required by the transaction contract.

## Combat tendencies

Each meaningful unit stores persistent tendencies such as aggression, initiative, caution, adaptability, flank bias, ambush bias, counterattack bias, pursuit bias, reserve bias, withdrawal willingness, casualty tolerance, objective focus, ally support, formation discipline, and commander dependence.

Tendencies describe habitual execution, not personality for every anonymous soldier. They evolve slowly from saved battle and training history.

## Fairness and battle snapshots

NPC institutions may create and reform doctrine through autonomous strategic processes. They may not retroactively invent the perfect doctrine after observing the player's battle plan.

At battle start, snapshot the resolved doctrine reference and doctrine content actually available to the unit, completed reform/training state that can affect execution, tendencies, commander, posture, orders, stats, equipment, morale, cohesion, fatigue, supply, terrain, and known intelligence. Historical resolution relies on that settled snapshot/receipt, not on a mutable numeric doctrine version.

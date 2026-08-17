# Jo, House Training, and Mercenary Ecology Overhaul

This release layers the requested Jo/minor-polity, permanent smart-training, House growth, private-service revenue, and wider mercenary ecology on top of the world-geography overhaul. It does not advance campaign time or replace existing House Tang/Sword Manor/Qin manpower owners.

## Jo

Jo is represented as a small independent mountain polity between Wei, Zhao, and Chu with an information-broker political identity. Canon/setting claims are separated from game-seeded quantities. The current game seed uses 32,000 population and a 1,500-person standing defense force because the source setting does not provide exact authoritative numbers for those values. Jo has exact population, force, treasury, private economy, council faction, territory, city, fortification baseline, and strategic border routes.

## House Tang and Sword Manor training/growth

`game/data/mechanics/house-tang-force-policy.json` is the static policy. The only autonomous entry point for new House regular manpower is Sword Manor trainee intake from conserved Qin population, with a maximum 2,000 lawful entrants per month while vacancies/housing/resources permit. Advancement remains:

trainee -> junior disciple -> general disciple -> senior disciple -> House Guard -> Guardian Cavalry -> Tang Champion.

Promotions still require registered thresholds, service time, vacancies, equipment, and mounts. Smart training changes focus selection only. It does not create training time or bypass EDU/diminishing returns. Cohorts and person-lite officers rotate toward next-promotion deficits, current loadout/troop-type skills, command/logistics needs, and weak useful stats. Requested adult exact commanders use the same maximum-sustainable standing regimen; Tang Kai remains on age-appropriate development only. Tang Wei's standing plan auto-consumes earned whole training hours during lawful downtime so manual settlement is not required.

## Force-employment doctrine

House Tang now has a separate force-employment policy from tactical combat doctrine:

1. standing contracted mercenaries;
2. additional hired mercenaries when a real threat/operation and solvency permit;
3. Sword Manor mobilization when required;
4. House Tang regulars as the last-resort/scarce-life layer.

This preference never overrides direct emergency, lawful command obligations, route impossibility, company refusal, or inability to pay. Mercenary contracts remain zero-body agreements; mercenary companies remain independent manpower owners.

The existing tactical doctrine remains unchanged: infantry uses bow -> long spear + shield -> long sword + shield; cavalry uses bow -> cavalry lance + shield -> long sword + shield.

## Mercenary ecology

The represented market is now exactly 450,000 people:

- 115,000 major/famous companies;
- 115,000 specialist companies, including House Tang's unchanged 75,000 standing contract;
- 140,000 regional professional companies;
- 80,000 local/seasonal hired manpower.

Short-notice availability is 135,100, inside the configured 100,000-180,000 band. Exact companies are geographically distributed and carry statuses such as available, state campaign, House contract, merchant escort, fortress contract, city security, travel, and reconstitution. The market file is a projection only and owns no bodies.

Exact company reconstitution uses the finite local mercenary pool, reservations, time, and company money; replacement bodies do not appear until the reservation matures. Quarterly training uses the same smart role/specialty focus selection. White Lantern signals and logistics capability records now reconcile to their exact 1,855 and 1,865 pools.

## House revenue and Sword Manor jobs

House commercial infrastructure provides bonded warehousing/cartage, grain milling/preservation, armory/repair contracting, remount/stable/carriage services, and market storage/transport brokerage. Revenue is transfer-based: realized receipts debit exact Qin private-economy cash and credit House Tang treasury, so no silver is minted.

Sword Manor may perform bounded private escort/security/courier/site-security work with otherwise-unallocated general/senior disciples. The service registry owns zero bodies. Sword Manor remains private and may not train outsiders for tuition or sell its House curriculum.

## Accounting fixes

- Sword Manor's monthly cash/food burden is charged exactly once across its whole conserved headcount, including internal officers materialized from those same bodies.
- House Tang contracted-defense `combined_total` is 75,002: 75,000 fighting troops plus named marshal Mu Zhen and named deputy He Shan, both external to the troop count.
- Mercenary pricing recognizes both `headcount` and regional-company `count` fields.
- House equipment-production procurement uses legitimate geographic economy regions and numeric workforce capacities correctly.

## Validation

Release validation includes the dedicated mercenary-ecology validator plus the geography validator. Focused tests cover Jo conservation/routes, House recruitment/training policy, requested exact-person training contracts, 450,000-market conservation, White Lantern capability reconciliation, transfer-based House commercial revenue, Sword Manor private-service revenue, and zero-body contingency mercenary offers.

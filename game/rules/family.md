# Sword and Banners Family, Marriage, Household, and Succession

Family status is sparse life-course/institutional state. Direct recognized kinship (for example a known sibling relation whose unknown parents should not be invented) may use a sparse kinship record; parent-child truth still belongs to parentage. It is **not** a romance score. Relationship state owns trust/affection/resentment; reputation owns audience belief; health owns pregnancy/childbirth/recovery; property/title/office/treasury remain in their existing authorities. `state/family/` owns only courtship records when persistent, proposals, recognized unions, households/dependents, parentage/guardianship, succession claims/order, and family-event provenance.

## Retrieval

Known person -> `state/family/index.json#person_index` -> load only referenced records. Do not load every union/Household/kinship record. `kinship-index.json` is derived routing only. Historical events stay load-on-demand unless explaining provenance, settling an undelivered consequence, or auditing a transition.

## Courtship, proposals, betrothal, marriage

Interest/speculation alone is not state. A persistent courtship record requires actual in-world conduct/intent by the NPCs involved; never create it for the player from OOC discussion. A real NPC proposal to the player may persist as `pending` because the NPC acted, but acceptance/rejection/negotiation remains the player's choice. Betrothal is distinct from marriage and may carry terms/expectations without spouse status. Marriage becomes canonical only after its real consent/authority/custom requirements resolve and the union transaction persists.

Marriage never fabricates affection. A spouse relationship may be warm, cold, conflicted, political, distant, or changing; those dimensions remain in relationship state. Conversely affection/courtship does not itself create marriage.

## Households and dependents

Create a household record only when co-residence, dependents, shared domestic obligations/property, staff/security, or administration is materially persistent. Marriage does not automatically transfer property, office, command, allegiance, clan/House ownership, or residence. Children, adopted children and wards are real people; guardianship/parentage is recorded explicitly and never creates a free duplicate body.

## Births and parentage

Reproduction/parenthood is an abstract life-course process. Do not model sexual activity as a mechanical step. When a supported birth occurs: advance exact time; resolve health through health/body mechanics; create exactly one child person on live birth; record parentage; update household/dependents; then recompute succession only where a relevant rule exists. Player parenthood is never chosen implicitly.

## Adoption, wards, guardianship

Adoption changes legal/adoptive parentage only through a real recognized process. Guardianship/fosterage/wardship is separate from biological/adoptive parentage and can begin/end without rewriting lineage. Persist guardian authority, dependent obligations, residence/custody and any diplomatic/security terms that actually exist.

## Separation, divorce, annulment, widowhood, remarriage

Never delete history. Dissolution changes the union status, then resolves residence, dependents, property obligations, legal claims and reputation/information consequences through their proper owners. Death triggers widowhood/death-family settlement before succession/inheritance. Remarriage creates a new union; old unions remain historical.

## Succession and inheritance

Kinship can create a **claim or eligibility input**, not an automatic transfer. A succession record must cite its rule basis and current holder/candidate ordering where known. On death/incapacity, settle dependents and claims, then load the actual House/clan/state/law/property rules. Disputed claims remain disputes rather than being auto-resolved for narrative convenience.

## NPC autonomy and time

**Runtime parity note:** Exact saved life-stage transitions, due pregnancies/births, death, widowhood, succession, and bounded NPC courtship autonomy are live. Autonomous courtship may only use already-saved mutual relationship evidence, lawful age/kinship/location opportunity, and deterministic review clocks. It may create an NPC-to-NPC proposal and later mature a mutually accepted betrothal, but it never invents affection and never accepts, rejects, marries, or creates parenthood for the player. Every resulting proposal/union remains exact persisted family state.

NPCs can court, propose, marry, separate, adopt, become guardians, have children, become widowed and remarry offscreen when saved relationships/goals, law/custom, resources, health, location, opportunity, elapsed time and deterministic process rules support it. No marriage/child/succession event exists merely to make the world dramatic. Aggregate populations may batch only while equivalent; named/material threshold crossings wake exact state. Use existing life-course/House/institution clocks, never a duplicate family-only global clock.

## Knowledge and reputation

Private family facts remain private until observed/reported through valid channels. Marriage, children, widowhood, scandal, dynastic alliances or succession can create reputation/prestige/notoriety evidence only for audiences that actually learn the fact. Reputation never substitutes for legal family state.

## Player agency

Never author the player character's attraction, courtship intent, proposal, acceptance, rejection, spouse selection, decision to have/adopt a child, separation/divorce decision, or testamentary/political commitment. NPCs may act toward the player, including making proposals or applying lawful/social pressure; those are world actions, not player intent.

## Sword setting overlay

Marriage may matter to Houses, courts, estates, patronage, titles, alliance expectations, wards and inheritance. Those consequences are resolved through actual terms and the existing politics/property/economy owners. Political usefulness can motivate an NPC/family offer or pressure campaign, but cannot choose Tang Wei's spouse or answer for him. Heir status requires an explicit succession basis rather than being inferred from kinship alone.

## Deterministic transaction order

For any family transition: load participants + relevant family records + relationship/knowledge + only causally relevant House/clan/law/property/health/reputation owners; validate authority/eligibility; resolve exact elapsed time and any registered random draw; write the family transition and event provenance; update relationship/household/dependent/succession/property owners only where actually changed; route information/reputation consequences; settle due processes; rebuild family/kinship indexes; validate/read back; narrate only player-known consequences.

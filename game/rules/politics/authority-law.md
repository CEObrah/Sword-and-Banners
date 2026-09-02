# Politics Module: Authority Law

## Authority and ownership

Authority may be personal, household, city, commandery, provincial, imperial, mercenary, tribal, religious, merchant, or criminal. Commanding a force does not necessarily mean owning it. Every appointment records grantor, holder, jurisdiction, duties, resources, limits, reporting line, term, succession, and revocation method.

Loyalty may divide among commander, paymaster, state, household, troop class, region, comrades, ideology, religion, and family. Conflicting loyalties create decisions, not automatic betrayal.

## Offices, titles, and claims

- **office:** current administrative or military authority;
- **title:** recognized rank, dignity, or landed status;
- **claim:** asserted right requiring evidence, recognition, coercion, or adjudication;
- **control:** physical ability to enforce decisions;
- **legitimacy:** acceptance that authority ought to rule.

Grant, inheritance, purchase, election, appointment, conquest, marriage, forgery, and usurpation have different evidence and consequences. A title without control may be symbolic; control without legitimacy may require constant force.

## Recognition, political support, and faction coalitions

A political decision identifies the deciding body, eligible participants, formal procedure, informal power, agenda, deadline, and enforcement. Each relevant actor has a supported position, power basis, interests, relationships, obligations, information, and acceptable alternatives.

Coalition support and effective political weight use `game/data/mechanics/politics.json`. Missing or duplicated power-basis inputs block resolution rather than being estimated.

Effective political weight comes from office, troops, money, land, household, elite network, popular support, legal authority, and control of procedure. Count each basis once and only where it can influence the deciding body. A positive coalition margin can pass or enforce only decisions within the coalition's legal and physical reach. Abstention, conditional support, secret opposition, and divided households remain distinct.

Recognition of a title, office, heir, claimant, treaty, or ruler requires a recognizing actor with authority and a recorded reason. Recognition can be partial or regional. It does not transfer physical control by itself.

## Territory and occupation

Track separately: legal claim, military occupation, administration, taxation, food access, road security, elite cooperation, civilian loyalty, resistance, and communication with the capital. A garrison controls only what it can reach, observe, and support.

Occupation policy addresses surrender, property, taxes, requisition, hostages, collaborators, courts, local officials, refugees, prisoners, disarmament, garrison, and resistance. Sack or massacre may create immediate loot and fear while destroying population, production, legitimacy, future surrender, and officer support.

## Occupation, administration, resistance, and control

For each occupied settlement or district, store garrison reach, patrol time, gates and roads, local officials, tax collectors, courts, food access, elite cooperation, popular compliance, resistance cells, communications, and relief threat.

Effective occupation reach uses the minimum-gate formula in `game/data/mechanics/politics.json`.

Control outside that reach is claim or influence, not daily enforcement. Policies are resolved separately for property, weapons, taxes, requisition, hostages, local office retention, courts, religion, refugees, surrender terms, prisoners, and collective punishment. Resistance gains people and resources only through exact grievances, organizations, external support, concealment, and recruitment. Repression may reduce visible action while increasing hidden support or future revolt.

## Law and justice

Law covers crimes, evidence, jurisdiction, arrest, detention, trial, punishment, debt, property, contracts, taxes, conscription, desertion, banditry, religion, status, inheritance, and war conduct. Minimum ordinary state conscription age is 16; eligibility still requires health, custody, authority, equipment, and an actual recruitment or levy transaction. Voluntary House Tang battlefield service may begin at age 10 under direct protection and does not grant adult office, independent command, or general contractual capacity. Local custom and emergency military authority may conflict with written Han law.

Tang Wei or an NPC may act outside law, but the engine records witnesses, evidence, victims, jurisdiction, pursuers, reputation, and political protection. “No one objected in the scene” is not legal immunity.

## Legal cases, investigation, judgment, and enforcement

A legal case owns alleged acts, jurisdiction, claimant or prosecutor, accused, victims, evidence lineage, witnesses, custody, applicable law or custom, presiding authority, procedure, advocates, deadline, and enforcement capacity.

Proceed through complaint or charge, jurisdiction review, evidence collection, notice or arrest, hearing, judgment, appeal or political intervention where available, sentence or remedy, and enforcement. Emergency military action may compress procedure but still creates evidence and consequences.

Legal finding margins and bands use `game/data/mechanics/politics.json`; evidentiary conclusion remains separate from the authority's actual judgment.

Use fixed levels and `game/rules/politics/intrigue-governance.md#evidence-and-judgment`. A strong margin supports only what the evidence proves. The presiding authority may still act corruptly, politically, mercifully, or coercively, but the divergence between evidence and judgment becomes a recorded fact affecting legitimacy, relationships, appeal, resistance, and future claims.

## Fiscal and recruitment authority

Holding troops, collecting revenue, and issuing obligations are separate authorities. A commander may command soldiers paid by another treasury without owning them. A tax collector may collect for an office without personal ownership. A patron may fund a force without lawful command.

Every recruitment, tax, requisition, toll, confiscation, land grant, debt, and payroll order records the office, contract, household right, property right, coercive control, or criminal act that authorizes it. Unsupported collection may still physically occur, but it becomes an illegal seizure with evidence, resistance, reputation, and enforcement consequences.

Changing regime does not automatically transfer private estates, merchant debt, tax arrears, soldier contracts, or local compliance. Each claim must be recognized, enforced, renegotiated, confiscated, or contested through actual actors and reach.

## military-appointment-authority

Military rank and command require the grantor, jurisdiction, legal basis, limits, succession, and revocation method defined in `game/rules/careers.md`. Command never implies ownership of state, household, allied, or contracted troops.

## evidence-objective-fact-and-judgment-separation

Every legal or political matter separates hidden objective fact, available evidence, admitted evidence, authority hearing the matter, legal standard, judgment, enforcement, and public belief.

Use the information taxonomy in `game/rules/agency.md`. A correct judgment is not guaranteed. An incorrect judgment remains a real legal and political event. A successful investigation cannot create evidence that does not exist.

Constructed legal, diplomatic, intelligence, and political actions use the common capacity-versus-demand grammar but remain bounded by actual authority, procedure, access, evidence, resources, and opposition.

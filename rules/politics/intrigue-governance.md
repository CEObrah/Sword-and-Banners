# Politics Module: Intrigue Governance

## Schemes, intrigue progress, and discovery

Schemes include bribery, blackmail, forgery, defection, sabotage, gate opening, assassination, kidnapping, theft, misinformation, discrediting, prisoner escape, and revolt.

A scheme record contains objective, sponsor, agents, target, access path, information, money, tools, timeline, cover story, communications, discovery risk, contingency, expected benefit, required progress, completed progress, exposure progress, and terminal conditions.

Each activity resolves two separate tracks:

Scheme progress and exposure use the separate numerical tracks in `data/mechanics/politics.json`. All component values must already be saved before resolution.

Use `rules/personal-force.md#extended-work-blocks` and fixed levels. Progress cannot exceed what the current step physically accomplishes. Exposure does not mean the entire truth is known: it may reveal only an anomaly, agent, method, sponsor link, or false lead. When an exposure threshold is crossed, create an investigation, warning, arrest, counter-scheme, or changed security response supported by who learned what. No Intrigue score bypasses access, physical method, evidence, or willing agents.

## Vassals and delegated rulers

A vassal or subordinate governor records land/office, rights, taxes, troops, service, hostages, court access, succession, disputes, and enforcement. They retain goals and local power. High opinion does not erase material interests; low opinion does not force rebellion without capacity and motive.

## Surrender and prisoner policy

Prior treatment affects future behavior. Massacring surrendering troops increases desperate resistance and flight; honoring terms can encourage surrender but may anger hardliners. Officers, civilians, and ordinary soldiers may have different legal and ransom status.

## evidence-and-judgment

Evidence quality, legality, witness access, custody, corroboration, contradiction, authority, corruption, and enforcement are separate. A result records both evidentiary conclusion and actual judgment when they differ.

## executable scheme and legal settlement

Scheme progress and exposure are separate tracks. Progress uses access, agent capability, resources, target vulnerability, preparation, difficulty, and opposition. Exposure uses traces, witnesses, communication risk, suspicious access, counterintelligence, compartmentation, cover, and cleanup. Progress never implies secrecy; exposure never implies knowledge of the full truth.

Legal evidence weight uses quality, reliability, lawful custody, support or contradiction, and corroboration. Evidentiary conclusion, actual judgment, and enforcement strength are separate. Authority, procedure, corruption, and enforcement can cause judgment to diverge from evidence without changing what the evidence supports.

## registered-institution-and-legal-clocks

Active offices, petitions, hearings, seizures, claims, succession, legal stays, institutional reviews, and faction decisions must have a next event, interruption trigger, blocked state, or terminal result registered through the world-processing registry. Law changes authority and obligations only through a valid decision owner and effective time.


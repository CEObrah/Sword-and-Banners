#!/usr/bin/env python3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def patch(rel, replacements):
    p=ROOT/rel
    text=p.read_text(encoding='utf-8')
    for old,new in replacements:
        if old not in text:
            raise SystemExit(f'expected active-rule text missing from {rel}: {old!r}')
        text=text.replace(old,new,1)
    p.write_text(text,encoding='utf-8')

patch('rules/characters.md',[
    ('`rules/combat.md`, `rules/combat.md`, `rules/combat.md`, and `rules/battle.md` own combat resolution.',
     '`rules/combat.md` and `rules/battle.md` own combat resolution.'),
])

patch('rules/world.md',[
    ('\n## canonical-name narration\n\n## Deferred-detail canonical identities\n',
     '\n## Deferred-detail canonical identities\n'),
    ('A cold-active canonical identity keeps one canonical display name and world route/source.',
     'A deferred-detail canonical identity keeps one canonical display name and world route/source.'),
    ('Cold active identities receive only source-owner-supported aging, training, experience, health exposure and career movement through force/court/institution/unit/population processes.',
     'Deferred-detail identities receive only source-owner-supported aging, training, experience, health exposure and career movement through force/court/institution/unit/population processes.'),
    ('Every full capability-profile identity, active exact external actor, routed named identity, and cold-active routed identity retains one canonical display name.',
     'Every full capability-profile identity, active exact external actor, and deferred-detail routed identity retains one canonical display name.'),
])

# This is a one-shot maintenance patch, not a permanent wording validator.
Path(__file__).unlink()
print('active rule duplicates and incomplete identity terminology cleaned')

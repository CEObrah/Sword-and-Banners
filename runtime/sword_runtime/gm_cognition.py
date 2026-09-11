"""GM-authored NPC cognition, with no authority over the claims it contains.

The runtime validates identity, evidence access, lifecycle and write scope. The
GM supplies psychological interpretation; no keyword rules pretend to prove it.
"""
from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Mapping

from sword_runtime.scene_sessions import active_scene_session, scene_history_record

COMMAND = 'gm_cognition_action'
PAYLOAD_KEYS = frozenset({
    'action', 'subject_ref', 'cognition_ref', 'kind', 'statement',
    'basis_refs', 'reason', 'salience', 'epistemic_status',
})
MAX_RECORDS = 32
_REF = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')


def _read(reader, path, default=None):
    method = getattr(reader, 'read_json', None) or getattr(reader, 'read', None)
    try:
        return method(path)
    except FileNotFoundError:
        return copy.deepcopy(default)


def cognition_path(subject_ref):
    return 'state/cognition/' + hashlib.sha256(subject_ref.encode()).hexdigest() + '.json'


def _text(value, key, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(c in value for c in '\x00\r\n'):
        raise ValueError('gm_cognition_' + key + '_invalid')
    return value.strip()


def _ref(value, key):
    if not isinstance(value, str) or not _REF.fullmatch(value):
        raise ValueError('gm_cognition_' + key + '_invalid')
    return value


def validate_proposal(reader, command):
    p = command.payload
    if set(p) - PAYLOAD_KEYS:
        raise ValueError('gm_cognition_unsupported_fields')
    action = p.get('action')
    if action not in {'create', 'update', 'resolve'}:
        raise ValueError('gm_cognition_action_invalid')
    subject = _ref(p.get('subject_ref'), 'subject_ref')
    ref = _ref(p.get('cognition_ref'), 'cognition_ref')
    meta = _read(reader, 'state/meta.json')
    if command.mode != 'gameplay' or command.actor_id != meta.get('player_id'):
        raise PermissionError('gm_cognition_requires_authenticated_gm_gameplay_surface')
    if subject == meta.get('player_id'):
        raise PermissionError('gm_cognition_may_not_author_player_inner_state')
    session = active_scene_session(reader)
    if not session or subject not in session.get('participant_refs', ()) or command.actor_id not in session.get('participant_refs', ()):
        raise ValueError('gm_cognition_subject_requires_active_scene')
    owners = _read(reader, 'state/index/owner-index.json')['owners']
    person_path = owners.get(subject)
    if not isinstance(person_path, str):
        raise ValueError('gm_cognition_subject_not_exact')
    person = _read(reader, person_path)
    player = _read(reader, 'state/player.json')
    location = person.get('current_location') or person.get('location_ref') or person.get('location')
    if person.get('schema') not in {'sab_character', 'person-lite', 'sword-materialized-person'} or location != player.get('location') or location != session.get('location_ref'):
        raise ValueError('gm_cognition_subject_not_present')
    if person.get('life_status') in {'dead', 'deceased'} or person.get('health_status') == 'dead':
        raise ValueError('gm_cognition_subject_dead')
    refs = p.get('basis_refs')
    if not isinstance(refs, (tuple, list)) or not 1 <= len(refs) <= 8 or len(set(refs)) != len(refs):
        raise ValueError('gm_cognition_requires_bounded_primary_evidence')
    basis = []
    for evidence_ref in refs:
        _ref(evidence_ref, 'basis_ref')
        evidence = scene_history_record(reader, evidence_ref, session_ref=session['session_ref'])
        if not evidence or not (evidence.get('speech_ref') or evidence.get('fact_ref')) or evidence.get('mechanical_consequence_authority') is not False:
            raise ValueError('gm_cognition_basis_not_primary_scene_evidence')
        witnesses = set(evidence.get('witness_refs', ())) | set(evidence.get('participant_refs', ()))
        witnesses.update(x for x in (evidence.get('speaker_ref'), evidence.get('actor_ref')) if isinstance(x, str))
        if subject not in witnesses:
            raise ValueError('gm_cognition_basis_not_witnessed_by_subject')
        basis.append({
            'ref': evidence_ref, 'at': evidence.get('at'),
            'attribution': evidence.get('speaker_ref') or evidence.get('actor_ref'),
            'summary': str(evidence.get('statement') or evidence.get('summary') or '')[:600],
            'truth_status': evidence.get('truth_status'),
        })
    owner = _read(reader, cognition_path(subject), {
        'schema': 'sword-npc-cognition', 'subject_ref': subject, 'entries': {},
    })
    if owner.get('subject_ref') != subject or not isinstance(owner.get('entries'), Mapping):
        raise ValueError('gm_cognition_owner_invalid')
    previous = owner['entries'].get(ref)
    if action == 'create':
        if previous:
            raise ValueError('gm_cognition_ref_already_exists_use_update')
        if len(owner['entries']) >= MAX_RECORDS:
            raise ValueError('gm_cognition_capacity_requires_explicit_consolidation')
    elif not previous or previous.get('status') != 'active':
        raise ValueError('gm_cognition_update_requires_active_entry')
    if previous and not set(refs) - set(previous.get('basis_refs', ())):
        raise ValueError('gm_cognition_change_requires_new_causal_evidence')
    reason = _text(p.get('reason'), 'reason', 600)
    statement = _text(p.get('statement'), 'statement', 900)
    kind = _ref(p.get('kind'), 'kind')
    epistemic = p.get('epistemic_status')
    if epistemic not in {'belief', 'intention', 'interpretation', 'recollection'}:
        raise ValueError('gm_cognition_epistemic_status_invalid')
    salience = p.get('salience', 'important')
    if salience not in {'important', 'defining'}:
        raise ValueError('gm_cognition_salience_invalid')
    if action == 'create' and any(row.get('statement') == statement and row.get('status') == 'active' for row in owner['entries'].values()):
        raise ValueError('gm_cognition_duplicate_meaning_use_existing_ref')
    record = {
        'cognition_ref': ref, 'subject_ref': subject, 'kind': kind,
        'statement': statement, 'epistemic_status': epistemic,
        'basis_refs': list(refs), 'basis': basis, 'reason': reason,
        'salience': salience, 'status': 'resolved' if action == 'resolve' else 'active',
        'created_at': previous['created_at'] if previous else command.submitted_at,
        'updated_at': command.submitted_at, 'campaign_revision': command.expected_revision + 1,
        'world_truth_authority': False, 'mechanical_consequence_authority': False,
    }
    return owner, record, previous


def apply_proposal(planner, command):
    owner, record, previous = validate_proposal(planner, command)
    owner = copy.deepcopy(owner)
    if previous:
        # Preserve prior interpretations without inflating the hot NPC owner.
        history_ref = 'cognition_history_' + command.semantic_digest
        planner.put('state/cognition/history/' + history_ref + '.json', {
            'schema': 'sword-npc-cognition-history', 'history_ref': history_ref,
            'subject_ref': record['subject_ref'], 'previous': previous,
        })
        record['previous_history_ref'] = history_ref
    owner['entries'][record['cognition_ref']] = record
    planner.put(cognition_path(record['subject_ref']), owner)
    return {
        'record_kind': 'npc_cognition', 'gm_private_cognition': {
            'privacy': 'gm_private_cognition_not_player_knowledge',
            'accepted': record, 'hard_world_state_changed': False,
        },
    }


def private_cognition(reader, subject_ref, *, full=False):
    owner = _read(reader, cognition_path(subject_ref))
    if owner is None:
        return {}
    entries = list(owner['entries'].values())
    entries.sort(key=lambda row: (row['status'] != 'active', row['salience'] != 'defining', -row['campaign_revision']))
    return {
        'privacy': 'gm_private_cognition_not_player_knowledge',
        'authored_cognition': entries if full else entries[:8], 'authored_cognition_count': len(entries),
        'authored_cognition_truncated': not full and len(entries) > 8,
        'cognition_detail_rule': 'get_person_sheet returns all current cognitive entries; inspect_game_object(previous_history_ref) retrieves one prior version for a currently permitted NPC. Statements are attributed mental state, never objective proof or orders.',
    }


def cognition_history(reader, history_ref):
    if not isinstance(history_ref, str) or not re.fullmatch(r'cognition_history_[0-9a-f]{64}', history_ref):
        return None
    return _read(reader, 'state/cognition/history/' + history_ref + '.json')


def command_guidance():
    return {
        'action': {'allowed_values': ['create', 'update', 'resolve']},
        'subject_ref': {'rule': 'exact living NPC in the active scene; never the player'},
        'cognition_ref': {'rule': 'stable short ID; reuse with update/resolve; do not create synonyms of an existing entry'},
        'kind': {'rule': 'short semantic label chosen by the GM, e.g. suspicion, goal, plan, grievance, relationship_cause, memory'},
        'epistemic_status': {'allowed_values': ['belief', 'intention', 'interpretation', 'recollection']},
        'statement': {'maximum_length': 900, 'rule': 'what this NPC thinks/intends; no binding promise, objective fact, resource transfer or player decision'},
        'basis_refs': {'rule': '1–8 exact primary speech/fact refs in this session witnessed by this NPC; updates/resolution need new evidence'},
        'reason': {'maximum_length': 600, 'rule': 'GM explanation of why this history supports the interpretation or change'},
        'salience': {'allowed_values': ['important', 'defining']},
        'authority_rule': 'AI authors psychological meaning; runtime commits attributed cognition only. It changes no time, scores, knowledge claims, bodies, resources or orders.',
        'capacity_rule': f'{MAX_RECORDS} current entries per NPC; full capacity fails explicitly, never silently evicts memory. Historical versions are retained separately.',
    }

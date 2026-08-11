#!/usr/bin/env python3
"""Render deterministic blank creation plans for mutable owner schemas.

A blank creation plan is not a persisted gameplay owner. It contains only
structure that can be inferred from the exact registered file template and a
list of required scalar inputs that must be resolved from authoritative state
or mechanics before persistence. It never inspects neighboring owner files.
"""
import json, os, sys


def load_template_entries(repo):
    idx = json.load(open(os.path.join(repo, 'game/data/runtime/template-index.json'), encoding='utf-8'))
    out = {}
    for rel in idx.get('shards', {}).values():
        shard = json.load(open(os.path.join(repo, rel), encoding='utf-8'))
        out.update(shard.get('templates', {}))
    return out


def load_contract(repo, target_schema):
    entries = load_template_entries(repo)
    ent = entries.get(target_schema)
    if not ent:
        raise KeyError(f'unregistered target schema: {target_schema}')
    path = os.path.join(repo, ent['path'])
    contract = json.load(open(path, encoding='utf-8'))
    if contract.get('scope') != 'mutable_state':
        raise ValueError(f'{target_schema} is not a mutable_state template')
    if contract.get('target_schema') != target_schema:
        raise ValueError(f'template target mismatch for {target_schema}')
    if contract.get('unknown_key_policy') != 'reject':
        raise ValueError(f'{target_schema} does not reject unknown keys')
    return ent, contract


def build_blank_creation_plan(contract):
    """Build a deterministic, non-persistable blank plan from one contract."""
    if contract.get('scope') != 'mutable_state':
        raise ValueError('blank creation plans are only for mutable_state templates')
    target = contract.get('target_schema')
    root = contract.get('object_contracts', {}).get('', {})
    allowed = set(root.get('allowed_keys', [])) if root.get('mode') == 'closed' else None
    types = contract.get('type_contracts', {})
    required = list(contract.get('required_top_level_keys', []))
    document = {}
    unresolved = []

    # The discriminator is structural truth, not a guessed gameplay fact.
    if allowed is None or 'schema' in allowed:
        document['schema'] = target

    for key in required:
        if key == 'schema':
            continue
        path = '/' + key
        t = list(types.get(path, []))
        if 'object' in t:
            document[key] = {}
        elif 'array' in t:
            document[key] = []
        else:
            unresolved.append({'path': path, 'types': t})

    # Canonicalize only keys actually present in the blank document.
    order = root.get('canonical_order', []) if isinstance(root, dict) else []
    ordered = {}
    for key in order:
        if key in document:
            ordered[key] = document[key]
    for key in sorted(document):
        if key not in ordered:
            ordered[key] = document[key]

    return {
        'target_schema': target,
        'template_id': contract.get('template_id'),
        'document': ordered,
        'required_inputs': unresolved,
        'persistence_rule': 'Resolve every required input from authoritative owners/mechanics before persistence; never persist placeholders or invent optional fields.'
    }


def plan_for_schema(repo, target_schema):
    _ent, contract = load_contract(repo, target_schema)
    return build_blank_creation_plan(contract)


def main(argv):
    if len(argv) < 2 or len(argv) > 3:
        print('usage: blank_owner_template.py <target_schema> [repo]', file=sys.stderr)
        return 2
    schema = argv[1]
    repo = argv[2] if len(argv) == 3 else '.'
    try:
        plan = plan_for_schema(repo, schema)
    except Exception as exc:
        print(f'BLANK TEMPLATE ERROR: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))

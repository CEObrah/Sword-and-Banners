from __future__ import annotations
import json


def test_sparse_crown_successions_use_exact_people_and_no_speculative_rosters(campaign):
    idx=json.loads((campaign/'state/family/index.json').read_text())
    expected={
      'succession.qin_crown':('state_qin','char_ei_sei'),
      'succession.zhao_crown':('state_zhao','char_tou_jou'),
      'succession.qi_crown':('state_qi','char_ou_ken'),
      'succession.yotanwa_confederation':('polity_yotanwa_confederation','char_yotanwa'),
    }
    owners=json.loads((campaign/'state/index/owner-index.json').read_text())['owners']
    for sid,(subject,holder) in expected.items():
        path=idx['successions'][sid]; doc=json.loads((campaign/path).read_text())
        assert doc['subject_owner_id']==subject and doc['current_holder_id']==holder
        assert owners.get(holder)
        assert all(owners.get(row['person_id']) for row in doc['candidate_order'])
        assert sid in idx['person_index'][holder]['successions']
    assert [x['person_id'] for x in json.loads((campaign/idx['successions']['succession.zhao_crown']).read_text())['candidate_order']] == ['char_prince_ka']


def test_unmaterialized_crowns_do_not_invent_exact_rulers(campaign):
    idx=json.loads((campaign/'state/family/index.json').read_text())
    for sid in ('succession.wei_crown','succession.chu_crown','succession.han_crown','succession.yan_crown'):
        assert sid not in idx['successions']

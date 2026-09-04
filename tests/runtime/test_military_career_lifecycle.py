from __future__ import annotations
import json
from pathlib import Path
from conftest import execute_internal


def person(root: Path, ref: str) -> dict:
    idx=json.load(open(root/'state/index/owner-index.json'))['owners']
    return json.load(open(root/idx[ref]))


def test_relief_reserve_retirement_preserve_durable_rank(campaign):
    before=person(campaign,'char_ousen')
    assert before['military_rank']['grade']=='general'
    assert before['command_assignment']['current_command_span']>0

    execute_internal(campaign,'career_event',{
        'person_ref':'char_ousen','kind':'relief','office':before['career_state']['office_or_command'],
        'grantor_ref':'state_qin','evidence_ref':'test.relief.order'
    },request_id='career-relief')
    relieved=person(campaign,'char_ousen')
    assert relieved['military_rank']['grade']=='general'
    assert relieved['career_state']['current_billet']=='officer_reserve'
    assert relieved['command_assignment']['current_command_span']==0

    execute_internal(campaign,'career_event',{'person_ref':'char_ousen','kind':'retirement'},request_id='career-retire')
    retired=person(campaign,'char_ousen')
    assert retired['military_rank']['grade']=='general'
    assert retired['career_state']['current_billet']=='retired'

    execute_internal(campaign,'career_event',{'person_ref':'char_ousen','kind':'return_to_service'},request_id='career-return')
    returned=person(campaign,'char_ousen')
    assert returned['military_rank']['grade']=='general'
    assert returned['career_state']['current_billet']=='officer_reserve'


def test_demotion_is_explicit_and_billet_loss_is_not_demotion(campaign):
    before=person(campaign,'char_karin')
    assert before['military_rank']['grade']=='general'
    execute_internal(campaign,'career_event',{
        'person_ref':'char_karin','kind':'demotion','grade':'1000_commander',
        'grantor_ref':'state_chu','evidence_ref':'test.formal.demotion'
    },request_id='career-demotion')
    after=person(campaign,'char_karin')
    assert after['military_rank']['grade']=='1000_commander'
    # Rank change alone does not silently rewrite the separately saved billet/span.
    assert after['command_assignment']['current_command_span']==before['command_assignment']['current_command_span']


def test_promotion_requires_evidence_and_changes_only_rank(campaign):
    before=person(campaign,'char_mou_ten')
    assert before['military_rank']['grade']=='1000_commander'
    execute_internal(campaign,'career_event',{
        'person_ref':'char_mou_ten','kind':'promotion','grade':'2000_commander',
        'grantor_ref':'state_qin','evidence_ref':'test.promotion.board'
    },request_id='career-promotion')
    after=person(campaign,'char_mou_ten')
    assert after['military_rank']['grade']=='2000_commander'
    assert after['command_assignment']['formation_ref']==before['command_assignment']['formation_ref']
    assert after['command_assignment']['current_command_span']==before['command_assignment']['current_command_span']

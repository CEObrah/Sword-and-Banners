import json
from pathlib import Path


ROOT=Path(__file__).resolve().parents[2]

def read(path): return json.loads((ROOT/path).read_text())

def test_current_cast_assignments_are_concrete_without_future_canon_guarantees():
    # Current service identity distinguishes zero-body command groups/staff billets
    # from leaf-formation command.  Do not force group commanders back into one
    # of their own child formations merely to give them a current_formation_id.
    expected={
        'state/char/shin.json':('loc_qin_eastern_depot',None,'cmdgrp.shin.hi_shin'),
        'state/char/hyou.json':('loc_jouto_village',None,None),
        'state/char/heki.json':('loc_kanyou','formation_qin_heki_royal_detail','formation_qin_heki_royal_detail'),
        'state/char/mou-ten.json':('loc_qin_regional_01',None,'cmdgrp.mou_ten.gaku_ka'),
        'state/char/ou-hon.json':('loc_qin_regional_01',None,'cmdgrp.ou_hon.gyoku_hou'),
        'state/char/mou-ki.json':('loc_kanyou_strategist_academy',None,None),
        'state/char/karyoten.json':('loc_qin_eastern_depot',None,'cmdgrp.shin.hi_shin'),
        'state/char/kyoukai.json':('loc_qin_eastern_depot','formation_qin_kyoukai_command','formation_qin_kyoukai_command'),
    }
    for path,(location,formation,assignment) in expected.items():
        person=read(path)
        assert person.get('current_location')==location
        assert person.get('current_formation_id')==formation
        command_assignment=person.get('command_assignment',{})
        if assignment is not None:
            assert command_assignment.get('command_group_ref')==assignment or command_assignment.get('formation_ref')==assignment
        career=person['career_state']
        assert career['office_or_command']!='saved profile role'
        assert career['future_canon_guaranteed'] is False
        rendered=json.dumps(career,ensure_ascii=False).lower()
        assert 'great general appointment' not in rendered


def test_qin_service_formations_are_conserved_and_use_one_top_commander():
    force=read('state/forces/state-qin.json')
    # The maintained force can lawfully change size as campaign recruitment,
    # losses, and replenishment settle. Test the live ledger relationship rather
    # than pinning one historical headcount snapshot.
    assert force['headcount']==force['authorized_strength']
    assert force['headcount']>0
    assert force['allocated_to_formations']
    for allocation in force['allocated_to_formations'].values():
        assert allocation['personnel']==sum(allocation['composition'].values())

    specs={
      'formation_qin_heki_royal_detail': (500, {'line_infantry':400,'missile_crossbow':100}),
      'formation_qin_gaku_ka_core': (500, {'line_infantry':500}),
      'formation_qin_gyoku_hou_core': (500, {'line_infantry':500}),
    }
    paths={
      'formation_qin_heki_royal_detail':'state/formations/qin-heki-royal-detail.json',
      'formation_qin_gaku_ka_core':'state/formations/qin-gaku-ka-core.json',
      'formation_qin_gyoku_hou_core':'state/formations/qin-gyoku-hou-core.json',
    }
    for ref,(n,composition) in specs.items():
        allocation=force['allocated_to_formations'][ref]
        assert allocation['personnel']==n
        assert allocation['composition']==composition
        formation=read(paths[ref])
        assert formation['personnel']==n
        assert formation['composition']==composition
        assert formation.get('commander_ref')
        assert sum(x['count'] for x in formation['cohort_composition'])==n

    # Gaku Ka and Gyoku Hou are 1,500-man recursive commands: a 500-man Qin
    # line core plus a separate 1,000-man family-owned cavalry formation.
    for rel in ('state/cmd/command-groups/cmdgrp.mou_ten.gaku_ka.json','state/cmd/command-groups/cmdgrp.ou_hon.gyoku_hou.json'):
        group=read(rel)
        assert group['organizational_state']['current_recursive_strength']==1500
        assert len(group['units'])==2


def test_career_training_contracts_route_through_registered_curricula():
    from sword_runtime.training_programs import resolve_program_ref, program_record, drill_record
    registry=read('game/data/mil/deterministic-training-programs.json')
    for rel in ('state/char/mou-ten.json','state/char/mou-ki.json'):
        person=read(rel)
        contract=person['activity_contract']
        assert 'focus' not in contract
        program_ref=resolve_program_ref(registry,person=person,explicit_program_ref=contract.get('training_program_ref'))
        skills=[]
        for row in program_record(registry,program_ref)['rotation']:
            skills.extend(drill_record(registry,row['drill_ref']).get('skills',[]))
        assert skills
    mou_ki=read('state/char/mou-ki.json')
    assert mou_ki['activity_contract'].get('training_program_ref')=='program.strategic_apprentice'

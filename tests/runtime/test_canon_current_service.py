import json
from pathlib import Path

from sword_runtime.smart_training import select_exact_focus

ROOT=Path(__file__).resolve().parents[2]

def read(path): return json.loads((ROOT/path).read_text())

def test_opening_cast_has_current_assignments_without_future_canon_grants():
    expected={
        'state/char/shin.json':('loc_jouto_village',None),
        'state/char/hyou.json':('loc_jouto_village',None),
        'state/char/heki.json':('loc_kanyou','formation_qin_heki_royal_detail'),
        'state/char/mou-ten.json':('loc_kanyou','formation_qin_mou_ten_100'),
        'state/char/ou-hon.json':('loc_kanyou','formation_qin_ou_hon_100'),
        'state/char/mou-ki.json':('loc_kanyou_strategist_academy',None),
        'state/char/karyoten.json':('loc_kokuhi_village',None),
    }
    for path,(location,formation) in expected.items():
        person=read(path)
        assert person.get('current_location')==location
        assert person.get('current_formation_id')==formation
        career=person['career_state']
        assert career['office_or_command']!='saved profile role'
        assert career['future_canon_guaranteed'] is False
        rendered=json.dumps(career,ensure_ascii=False).lower()
        assert 'hi shin unit' not in rendered
        assert 'great general appointment' not in rendered

def test_qin_service_formations_are_conserved_mixed_role_and_external_command():
    force=read('state/forces/state-qin.json')
    assert force['headcount']==675000
    specs={
      'formation_qin_heki_royal_detail':500,
      'formation_qin_mou_ten_100':100,
      'formation_qin_ou_hon_100':100,
    }
    for ref,n in specs.items():
        allocation=force['allocated_to_formations'][ref]
        assert allocation['personnel']==n
        assert sum(allocation['composition'].values())==n
        assert len(allocation['composition'])>=2
        formation=read(f"state/formations/{ref.replace('formation_','').replace('_','-')}.json")
        assert formation['personnel']==n
        assert sum(formation['composition'].values())==n
        assert formation['top_command_staff_accounting']['commander_and_deputy_external_to_troop_strength'] is True
        assert sum(x['count'] for x in formation['cohort_composition'])==n

def test_career_training_targets_useful_deficits_not_only_existing_strengths():
    mou_ten=read('state/char/mou-ten.json')
    chosen=[select_exact_focus(mou_ten,mou_ten['activity_contract'],i) for i in range(6)]
    assert 'Logistics' in chosen
    assert 'Bow' in chosen or 'Scouting' in chosen
    mou_ki=read('state/char/mou-ki.json')
    chosen_student=[select_exact_focus(mou_ki,mou_ki['activity_contract'],i) for i in range(6)]
    assert any(x in chosen_student for x in ('Strategy','Tactics','Logistics','Formation Command'))

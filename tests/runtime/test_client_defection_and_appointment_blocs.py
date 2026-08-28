import json
from sword_runtime.production_planner import ProductionCampaignPlanner


def planner_for(campaign):
    p=ProductionCampaignPlanner(campaign); p._reset(); return p


def write(campaign,path,doc):
    out=campaign/path; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(doc,ensure_ascii=False,indent=2,sort_keys=True)+'\n')


def test_client_state_defection_breaks_only_exact_client_treaty_without_inventing_territory(campaign):
    idx=json.load(open(campaign/'state/index/owner-index.json'))
    polity_ref='polity_test_client'; polity_path='state/politics/polities/test-client.json'
    polity={
        'schema':'sword-polity','owner_id':polity_ref,'polity_ref':polity_ref,'name':'Test Client',
        'status':'recognized_state','recognition_status':'recognized','treasury_ref':'treasury_house_tang',
        'military_force_refs':[],'occupied_site_refs':[],'diplomacy':{},'seat_claim_ref':'loc_kanyou'
    }
    write(campaign,polity_path,polity); idx['owners'][polity_ref]=polity_path; write(campaign,'state/index/owner-index.json',idx)
    treaties=json.load(open(campaign/'state/politics/treaties.json'))
    treaties['records']['treaty_test_client']={
        'treaty_ref':'treaty_test_client','kind':'client_state','parties':[polity_ref,'state_qin'],'status':'active',
        'signed_at':'244-BCE-01-01T00:00:00+08:00','terms':{'client_ref':polity_ref,'patron_ref':'state_qin','mutual_nonaggression':True,'patron_defense_obligation':True}
    }
    write(campaign,'state/politics/treaties.json',treaties)
    p=planner_for(campaign); territory_before=json.dumps(p.read('state/territory/control.json'),sort_keys=True)
    result=p._defect_client_state(polity_ref,'treaty_test_client',str(p._world_time()))
    assert result['break_kind']=='client_defection'
    treaty=p.read('state/politics/treaties.json')['records']['treaty_test_client']
    assert treaty['status']=='broken' and treaty['broken_by_ref']==polity_ref
    assert json.dumps(p.read('state/territory/control.json'),sort_keys=True)==territory_before


def test_appointment_blocs_require_exact_saved_relationship_evidence(campaign):
    p=planner_for(campaign)
    evidence=p._appointment_bloc_evidence('char_riboku')
    assert set(evidence['evidence_refs']) >= {'rel.char_futei.char_riboku.retainer','rel.char_kaine.char_riboku.retainer'}
    assert evidence['supporters']
    # A person with no qualifying exact relationship edge gets no invented bloc.
    empty=p._appointment_bloc_evidence('char_tang_wei')
    assert empty['evidence_refs']==[] and empty['supporters']==[]

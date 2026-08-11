import json
import pytest
from conftest import execute, execute_internal

def test_remaining_semantic_command_surface(campaign):
    execute_internal(campaign,'population_transfer',{'state':'qin','personnel':10,'source_stratum':'agricultural','destination_stratum':'administration_and_education'})
    execute_internal(campaign,'person_materialize',{'state':'qin','person_ref':'char_surface_officer','name':'Surface Officer','birth_date':'266-BCE-01-01','role':'command_personnel'})
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':'formation_surface','role':'line_infantry','personnel':500,'location_ref':'loc_qin_eastern_depot','commander_ref':'char_heki'})
    execute_internal(campaign,'formation_doctrine_set',{'formation_ref':'formation_surface','doctrine_ref':'doc.house_tang_internal.standard','doctrine_behavior':{'reserve_commitment':35,'casualty_tolerance':'moderate'}})
    execute_internal(campaign,'formation_training_set',{'formation_ref':'formation_surface','training_ref':'train.house_tang_internal.standard'})
    execute_internal(campaign,'command_transfer',{'formation_ref':'formation_surface','commander_ref':'char_tou','command_authority':'char_tou'})
    execute_internal(campaign,'formation_assign',{'formation_ref':'formation_surface','commander_ref':'char_tou','command_authority':'state_qin'})
    execute_internal(campaign,'institution_project',{'institution_ref':'inst_qin_fortification_bureau','project_ref':'surface_project','kind':'repair'})
    execute_internal(campaign,'state_action',{'state':'qin','action':'appointment','office':'field_inspector','person_ref':'char_heki','capabilities':['information_review']})
    execute(campaign,'house_action',{'house_ref':'house_tang','action':'promotion','subject_ref':'char_tang_kai'})
    execute_internal(campaign,'economy_transfer',{'state':'qin','amount_silver':3,'direction':'state_to_player'})
    execute_internal(campaign,'formation_dissolve',{'formation_ref':'formation_surface'})

def test_player_cannot_run_maintenance_repair(campaign):
    from sword_runtime.commands import CommandEnvelope
    from sword_runtime.engine import SwordRuntime
    from conftest import meta
    m=meta(campaign); c=CommandEnvelope(m['campaign_id'],'player-repair','char_tang_wei','repair',m['revision'],m['time'],{'path':'state/player.json','changes':{}},mode='maintenance')
    with pytest.raises(PermissionError): SwordRuntime(campaign).execute(c)

import json
import pytest
from conftest import execute, execute_internal

def test_remaining_semantic_command_surface(campaign):
    execute_internal(campaign,'population_transfer',{'state':'qin','personnel':10,'source_stratum':'agricultural','destination_stratum':'administration_and_education'})
    execute_internal(campaign,'person_materialize',{'state':'qin','person_ref':'char_surface_officer','name':'Surface Officer','birth_date':'266-BCE-01-01','role':'command_personnel','source_location_ref':'loc_qin_eastern_depot'})
    execute_internal(campaign,'person_materialize',{'state':'qin','person_ref':'char_surface_officer_two','name':'Surface Officer Two','birth_date':'267-BCE-01-01','role':'command_personnel','source_location_ref':'loc_qin_eastern_depot'})
    execute_internal(campaign,'formation_create',{'state':'qin','formation_ref':'formation_surface','role':'line_infantry','personnel':500,'location_ref':'loc_qin_eastern_depot','commander_ref':'char_surface_officer'})
    execute_internal(campaign,'formation_doctrine_set',{'formation_ref':'formation_surface','doctrine_ref':'doc.house_tang_internal.standard','doctrine_behavior':{'reserve_commitment':35,'casualty_tolerance':'moderate'}})
    execute_internal(campaign,'formation_training_set',{'formation_ref':'formation_surface','training_ref':'train.house_tang_internal.standard'})
    execute_internal(campaign,'command_transfer',{'formation_ref':'formation_surface','commander_ref':'char_surface_officer_two','command_authority':'char_surface_officer_two'})
    execute_internal(campaign,'formation_assign',{'formation_ref':'formation_surface','commander_ref':'char_surface_officer','command_authority':'state_qin'})
    execute_internal(campaign,'institution_project',{'institution_ref':'inst_qin_fortification_bureau','project_ref':'surface_project','kind':'repair'})
    execute_internal(campaign,'state_action',{'state':'qin','action':'appointment','office':'field_inspector','person_ref':'char_heki','capabilities':['information_review']})
    execute(campaign,'house_action',{'house_ref':'house_tang','action':'assign_duty','subject_ref':'char_tang_kai','duty':'manor_training_assistant'})
    execute_internal(campaign,'economy_transfer',{'state':'qin','amount_silver':3,'direction':'state_to_player'})
    execute_internal(campaign,'formation_dissolve',{'formation_ref':'formation_surface'})


def test_generic_ooc_repair_command_is_not_in_live_surface(campaign):
    import json
    from sword_runtime.command_contracts import COMMAND_PAYLOAD_KEYS
    catalog = json.load(open(campaign / "game/data/mechanics/command-catalog.json"))["commands"]
    assert "repair" not in catalog
    assert "repair" not in COMMAND_PAYLOAD_KEYS

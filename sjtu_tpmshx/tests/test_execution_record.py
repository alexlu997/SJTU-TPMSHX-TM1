"""Energy identity stays distinct from transport resources and user inputs."""
from dataclasses import replace
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.domain.case_data import CaseData
from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.model_refs import ModelRef
from sjtu_tpmshx.io.result_io import load_result, save_result
from sjtu_tpmshx.solvers.execution_record import full_execution_record


def evidence(mode, *, settings=None, temperature=None, table=None,
             table_key='sco2_enthalpy_eos', fluid='sco2'):
    refs = (ModelRef('fluid', 'test-v1', {'fluid': fluid}),
            ModelRef('fluid', 'test-v1', {'fluid': 'water'}),
            ModelRef('geometry', 'test-v1'), ModelRef('darcy_forchheimer', 'test-v1'))
    grid = dict(dimension=2, length_unit='m', axis_order=('x', 'y'),
                dx=np.ones(1), dy=np.ones(1), x_edges=np.arange(2.), y_edges=np.arange(2.))
    case = CaseData('case', grid=grid, model_refs=refs,
                    config_snapshot={'solver': {'enthalpy_algorithm': 'unused_request'}},
                    metadata={'model_roles': dict(fluid_A=0, fluid_B=1, geometry=2, darcy_forchheimer=3)})
    fields = {name: np.ones((1, 1)) * value for name, value in
              dict(Ta=310., Tb=300., Ts=305., P_thermal_A=1e7, P_thermal_B=2e6,
                   P_report_A=1.1e7, P_report_B=2.1e6).items()}
    field_metadata = {name: dict(unit='K' if name.startswith('T') else 'Pa', axes=('x', 'y'),
                                location='cell', state='post flow' if name.startswith('P_report') else 'thermal')
                      for name in fields}
    result = FieldResult('result', 'case', 'cpp', backend_version='test-v1', grid=grid,
                         fields=fields, field_metadata=field_metadata, model_refs=refs,
                         pressure_evidence={'A': {}, 'B': {}}, run_status={'execution': 'completed', 'converged': True, 'outer_index': 4},
                         boundary_fluxes={'state': 'last thermal input', 'temperature': temperature},
                         metadata=dict(thermal_mode=mode,
                                       diagnostics={'true_h_balance': {'effective_settings': settings or {}}},
                                       model_metadata={table_key: table or {}}))
    return case, result


def test_water_energy_and_transport_resources_are_distinct():
    case, result = evidence('true_h')
    record = full_execution_record(case, result)
    water = record['sides']['B']
    assert water['flow_and_exchange_model_ref'] == 1
    assert case.model_refs[1].parameters['fluid'] == 'water'
    assert water['energy']['property_provider'] == 'HEOS'
    assert water['energy']['relation'] == 'eos_h_TP'
    assert water['energy']['pressure_field'] == 'P_thermal_B'
    assert record['evidence']['pressure_report_states']['B'] == 'post flow'


def test_temperature_unknown_can_reconstruct_enthalpy():
    settings = dict(energy_algorithm='temperature_sou', energy_algorithm_version=2,
                    nonlinear_state_update='HEOS_PT', enthalpy_face_reconstruction='h_minmod_outlet_v1')
    case, result = evidence('conservative_energy', settings=settings)
    record = full_execution_record(case, result)
    assert record['numerics']['unknown'] == 'T'
    assert record['numerics']['algorithm'] == 'temperature_sou'
    assert record['numerics']['face_reconstruction'] == 'h_minmod_outlet_v1'
    assert record['sides']['A']['property_evaluation']['state_update'] == 'HEOS_PT'
    assert 'iteration_inverse_backend' not in record['sides']['A']['property_evaluation']


@pytest.mark.parametrize('table_key', ['enthalpy_eos', 'sco2_enthalpy_eos'])
@pytest.mark.parametrize('fluid', ['co2', 'sco2'])
def test_table_evidence_applies_only_to_its_recorded_side(table_key, fluid):
    table = dict(sides=('A',), iteration_backend='BICUBIC&HEOS', algorithm='recorded-table-v1',
                 heos_polish=False, coolprop_version='recorded-version')
    case, result = evidence('true_h', table=table, table_key=table_key, fluid=fluid)
    record = full_execution_record(case, result)
    assert record['sides']['A']['property_evaluation']['iteration_inverse_backend'] == 'BICUBIC&HEOS'
    assert record['sides']['A']['property_evaluation']['heos_polish'] is False
    assert record['sides']['B']['property_evaluation']['iteration_inverse_backend'] == 'HEOS'
    assert record['numerics']['algorithm'] is None


def test_temperature_ledger_distinguishes_integral_energy_and_prescribed_side():
    ledger = dict(definition='model_enthalpy_temperature_v1', solved={'A': True, 'B': False})
    case, result = evidence('temperature', temperature=ledger)
    record = full_execution_record(case, result)
    assert record['sides']['A']['energy']['relation'] == 'integral_cp_T'
    assert record['sides']['B']['energy']['relation'] == 'prescribed_temperature'
    assert record['sides']['B']['solved'] is False
    assert record['sides']['B']['energy']['property_provider'] is None
    case, result = evidence('legacy_temperature')
    old = full_execution_record(case, result)
    assert old['sides']['A']['energy']['relation'] == 'capacity_temperature'
    assert 'property_sampling' not in old and 'input_resolution' not in old


def test_record_is_immutable_and_survives_file_handoff(tmp_path):
    case, result = evidence('true_h', settings={'energy_algorithm': 'legacy_h_fou'})
    sampling = [dict(side='B', outer_index=4, stage='thermal_hv', quantity='conductivity',
                     provider='model_resource', temperature='inlet', pressure='inlet', operation='scalar_evaluation')]
    resolution = dict(version='prepared_input_v1', source='CaseData.parameters', active_sides=('A', 'B'))
    result = replace(result, metadata={**result.metadata, 'property_sampling': sampling, 'input_resolution': resolution})
    record = full_execution_record(case, result)
    result = replace(result, metadata={**result.metadata, 'execution_record': record})
    sampling[0]['temperature'] = 'later edit'
    assert result.metadata['execution_record']['property_sampling']['records'][0]['temperature'] == 'inlet'
    record['sides']['B']['energy']['relation'] = 'later edit'
    path = tmp_path / 'result.h5'
    save_result(result, path)
    loaded = load_result(path)
    assert loaded.metadata['execution_record'] == result.metadata['execution_record']
    subprocess.run([sys.executable, '-c',
        "import sys; from sjtu_tpmshx.io.result_io import load_result; "
        "r=load_result(sys.argv[1]).metadata['execution_record']; "
        "assert r['input_resolution']['source']=='CaseData.parameters'; "
        "assert r['property_sampling']['records'][0]['temperature']=='inlet'; "
        "assert not any(x in sys.modules for x in ('CoolProp','numba','PySide6'))", str(path)], check=True)
    assert loaded.metadata['execution_record']['sides']['B']['energy']['relation'] == 'eos_h_TP'
    with pytest.raises(TypeError):
        loaded.metadata['execution_record']['sides']['B']['energy']['relation'] = 'edit'
    old = replace(result, metadata={key: value for key, value in result.metadata.items()
                                    if key != 'execution_record'})
    save_result(old, path)
    assert 'execution_record' not in load_result(path).metadata


def test_model_h_last_main_settings_keep_refined_and_startup_records_separate():
    case, result = evidence('model_h')
    calls = dict(version='model_h_iterations_v1', records=[
        dict(outer_index=0, attempt=0, stage='outer_thermal', settings={'max_iterations': 250}),
        dict(outer_index=0, attempt=1, stage='outer_thermal', settings={'max_iterations': 125}),
        dict(outer_index=0, attempt=0, stage='refined_thermal', settings={'max_iterations': 12000})])
    result = replace(result, metadata={**result.metadata, 'model_h_iterations': calls})
    record = full_execution_record(case, result)
    assert record['numerics']['effective_settings']['max_iterations'] == 125
    assert len(record['numerics']['model_h_iterations']['records']) == 3
    assert record['sides']['B']['energy']['relation'] == 'integral_cp_T'


def test_executed_flow_methods_survive_result_files(tmp_path):
    case, result = evidence('true_h')
    flow = {'A': dict(algorithm='simple_2d_fixed_density_anderson_v1', iterations=109,
                      proposal_steps=44, accepted_proposals=37)}
    result = replace(result, metadata=dict(result.metadata, simple_flow=flow))
    path = tmp_path/'flow-result.h5'
    save_result(result, path)
    restored = load_result(path)
    assert full_execution_record(case, restored)['numerics']['simple_flow'] == flow
    assert 'simple_flow' not in full_execution_record(*evidence('true_h'))['numerics']

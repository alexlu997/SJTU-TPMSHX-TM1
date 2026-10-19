"""Native engineering cases retain physical gates and per-side energy models."""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import FluidConfig, PartialBCConfig, ZoneInputConfig
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.tests.native import test_cpp_full_3d as native_3d
from sjtu_tpmshx.tests.native.test_native_execution import _config
from sjtu_tpmshx.tests.native.full_result_audit import physical_gates
from sjtu_tpmshx.tests.test_co2_model import CO2_PAIRS, co2_config, co2_engineering_config

native_path = native_3d.native_path


PAIRS = ('air-air', 'air-water', 'water-air', 'air-sco2', 'sco2-air',
         'water-sco2', 'sco2-water', 'sco2-sco2', *CO2_PAIRS)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('pair', PAIRS)
def test_public_native_cases_keep_physical_gates(native_path, dimension, pair):
    def fluid(name, side):
        return FluidConfig(type=name, u_mps=3. if name == 'air' else .2,
            T_in_K=(350. if name == 'water' else 500.) if side == 0 else 300.,
            P_in_Pa={'air': 2e5, 'water': 2e6, 'sco2': 12e6}[name])

    names = pair.split('-')
    config = (co2_engineering_config(dimension, pair) if pair in CO2_PAIRS else
              replace(_config(dimension, True), fluid_A=fluid(names[0], 0), fluid_B=fluid(names[1], 1)))
    if dimension == 2 and all(name in ('co2', 'sco2') for name in names):
        # Retain the qualified flow tolerances for the two real-fluid streams.
        config = replace(config, solver=replace(config.solver, mom_tol=1e-6,
            mass_local_tol=1e-8, mass_global_tol=1e-8))
    algorithm = config.solver.enthalpy_algorithm
    assert algorithm == 'temperature_sou'
    prepared = prepare_case(config, case_id=f'native-engineering-{dimension}d-{pair}')
    result = run_case(prepared, native_3d.control(native_path))
    _assert_engineering_result(result)
    record = result.metadata['execution_record']
    assert record['backend'] == result.backend_id
    assert record['dimension'] == dimension
    assert record['numerics']['thermal_mode'] == result.metadata['thermal_mode']
    if {'co2', 'sco2'}.intersection(names):
        assert result.metadata['thermal_mode'] == 'conservative_energy'
        assert record['numerics']['algorithm'] == algorithm
        assert record['numerics']['unknown'] == 'T'
    for side, fluid in zip('AB', names):
        actual = record['sides'][side]
        assert actual['fluid'] == fluid and actual['solved']
        ref = prepared.model_refs[actual['flow_and_exchange_model_ref']]
        assert ref.parameters['fluid'] == fluid
        relation = ('eos_h_TP' if result.metadata['thermal_mode'] in ('true_h', 'conservative_energy')
                    and fluid in ('co2', 'sco2') else 'integral_cp_T')
        assert actual['energy']['relation'] == relation


def test_refined_true_h_partial_ports_keep_physical_gates(native_path):
    from sjtu_tpmshx.tests.native.test_cpp_conservative_full3d import candidate

    prepared = candidate('temperature_sou', 'sco2-water', port_refined='partial')
    result = run_case(prepared, native_3d.control(native_path))
    _assert_engineering_result(result)


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('fluid', ['co2', 'sco2'])
def test_continuous_real_fluid_native_cases(native_path, dimension, fluid):
    config = co2_config(1 if dimension == 2 else 3)
    config.fluid_A.type = fluid
    count = 2 if dimension == 2 else 6
    spec = dict(n_ctrl_x=1, n_ctrl_y=2, symmetric_y=False, spline_order=2,
                L_bounds=[6.8, 7.2], t_bounds=[.55, .6],
                x_decision=np.r_[np.linspace(6.8, 7.2, count), np.linspace(.55, .6, count)].tolist())
    if dimension == 3:
        spec['n_ctrl_z'] = 3
    else:
        config.solver.max_outer_ltne = 100
        config.bc_A = PartialBCConfig(dir=0, in_ctr=.021, in_w=.021, out_ctr=.021, out_w=.021)
        config.bc_B = PartialBCConfig(dir=3, in_ctr=.091, in_w=.091, out_ctr=.091, out_w=.091)
    config.zones = ZoneInputConfig(enabled=True, axis='continuous', config=spec)
    prepared = prepare_case(config, case_id=f'continuous-{dimension}d-{fluid}')
    result = run_case(prepared, native_3d.control(native_path))
    assert result.metadata['thermal_mode'] == 'conservative_energy'
    assert result.metadata['design_mode'] == ('continuous' if dimension == 2 else 'continuous_xyz')
    for side in 'AB':
        assert abs(result.metadata['diagnostics']['mass_imbalance_rel_' + side]) <= 1e-6
    _assert_engineering_result(result)


def _assert_engineering_result(result):
    physical_gates(result)
    if result.metadata['thermal_mode'] in ('true_h', 'conservative_energy'):
        from sjtu_tpmshx.tests.native.full_thermal_reference import assert_selected_enthalpy
        assert_selected_enthalpy(result)
    for key, specification in result.field_metadata.items():
        if specification['unit'] in ('K', 'm/s'):
            assert np.isfinite(result.fields[key]).all(), key
    metrics = evaluate(result).metrics
    for key in ('Q', 'Q_A', 'Q_B', 'dP_A', 'dP_B', 'mass_flow_A', 'mass_flow_B', 'T_out_A', 'T_out_B'):
        value = metrics[key]
        assert value.status == 'available' and np.isfinite(value.value), (key,value.reason)

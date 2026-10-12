"""Research data stay explicit, portable, and separate from production defaults."""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.io.case_io import load_case, save_case
from sjtu_tpmshx.io.result_io import load_result, save_result
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.preprocess.api import prepare_research_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs
from sjtu_tpmshx.validation.cases.audit_3d_conservation import make_T2, make_T5


def test_synthetic_porosity_profile_and_explicit_phase_survive_preparation():
    inputs = make_T5(20)
    inputs.update(sweep_profile='fast_sweep', max_outer_ltne=1, _emit_audit=True)
    case = prepare_research_case(inputs, case_id='synthetic')
    assert case.config_snapshot['inputs']['Nx'] == 20
    assert tuple(len(case.grid['d' + axis]) for axis in 'xyz') == (15, 15, 15)
    assert case.parameters['prepared']['max_outer'] == 1
    assert case.parameters['prepared']['ltne_max_iter'] == 20000
    assert case.parameters['prepared']['geometry']['epsilon'] != .85
    assert np.all(case.design_fields['eps_arr'] == .85)
    assert case.metadata['active_fluids'] == ('A',)
    assert case.parameters['fluid_B_cfg'] is None
    assert set(case.parameters['prepared']['axes']) == {'A'}
    inputs['fluid_A_cfg']['dir'] = 1
    assert case.parameters['fluid_A_cfg']['dir'] == 0
    damaged = replace(case, metadata={**case.metadata, 'active_fluids': ('A', 'B')})
    with pytest.raises(ValueError, match='active fluids'):
        build_execution_inputs(damaged)
    with pytest.raises(ValueError, match='research case does not support backend=cpp'):
        run_case(case, RunControl(backend='cpp'))


@pytest.mark.parametrize('profile,outer,inner,shape', [
    (None, None, 20000, (20, 20, 20)),
    ('fast_sweep', 3, 20000, (15, 15, 15)),
    ('full_validate', 12, 50000, (20, 20, 20)),
])
def test_research_profiles_keep_the_original_effective_budgets(profile, outer, inner, shape):
    case = prepare_research_case(dict(make_T2(20), sweep_profile=profile), case_id='budget')
    assert tuple(len(case.grid['d' + axis]) for axis in 'xyz') == shape
    assert case.parameters['prepared']['max_outer'] == outer
    assert case.parameters['prepared']['ltne_max_iter'] == inner


@pytest.mark.parametrize('update,match', [
    ({'max_outer_ltne': 0}, 'max_outer_ltne'),
    ({'eps': np.nan}, 'porosity'),
    ({'Lz': 0.}, 'Lz'),
    ({'u_A': np.inf}, 'u_A'),
    ({'fluid_A_cfg': None}, 'fluid A must be active'),
    ({'sweep_profile': 'unknown'}, 'sweep_profile'),
    ({'unknown_override': True}, 'unknown research inputs'),
    ({'mms_S_A_field': np.ones((3, 4, 4))}, 'effective grid'),
])
def test_invalid_research_data_fail_before_execution(update, match):
    with pytest.raises(ValueError, match=match):
        prepare_research_case(dict(make_T2(4), **update), case_id='invalid')


@pytest.mark.parametrize('single', [False, True])
def test_one_pass_case_and_result_replay_keeps_the_verdict_and_inactive_phase(tmp_path, single):
    inputs = (make_T5 if single else make_T2)(4)
    inputs.update(max_outer_ltne=1, _emit_audit=True)
    case = prepare_research_case(inputs, case_id='replay')
    save_case(case, tmp_path/'case.yaml')
    restored_case = load_case(tmp_path/'case.yaml')
    assert restored_case.config_snapshot['inputs']['eps'] == .85
    result = run_case(restored_case)
    assert result.run_status['converged'] is False
    save_result(result, tmp_path/'result.h5')
    restored = load_result(tmp_path/'result.h5')
    assert restored.run_status == result.run_status
    assert restored.metadata['active_fluids'] == (('A',) if single else ('A', 'B'))
    for key in result.fields:
        np.testing.assert_array_equal(restored.fields[key], result.fields[key])
    assert set(restored.metadata['audit']['masks']) == ({'A'} if single else {'A', 'B'})
    metrics = evaluate(restored).metrics
    if single:
        assert restored.metadata['diagnostics']['eps_B_strict'] is None
        assert restored.metadata['diagnostics']['Q_sB'] == 0.
        assert restored.boundary_fluxes['mass_B'] is None
        for name in ('Q_B', 'dP_B', 'T_out_B', 'mass_flow_B', 'energy_imbalance_rel'):
            assert metrics[name].value is None
            assert metrics[name].status == 'unsupported'
            assert 'inactive' in metrics[name].reason
    else:
        assert metrics['Q_A'].status == metrics['Q_B'].status == 'available'

"""Native SIMPLE consumes frozen drag, even under receiver overrides."""
from dataclasses import replace
import numpy as np
import pytest
from sjtu_tpmshx.run_control.module_ports import RunControl
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.run_control.module_ports import resolve_control
from sjtu_tpmshx.cpp_interface import full_2d_stage
from tests.python.integration_tm1.integration_support import baseline_config


def test_full_prepared_flow_consumes_drag_without_prediction(monkeypatch):
    from sjtu_tpmshx.physical_models.df_surrogate import predict
    from sjtu_tpmshx.cpp_interface import _native_df
    from sjtu_tpmshx.physical_models import grid as grids
    config = baseline_config()
    config.solver = replace(config.solver, max_outer_ltne=2, max_iter_simple=500)
    case = prepare_case(config, case_id='prepared-flow')
    def forbidden(*args, **kwargs):
        raise AssertionError('execution rebuilt fixed drag or grid')
    for module, names in ((grids, ('_aligned_grid',)),
                          (predict, ('predict_K_cF', 'predict_K_cF_vec')),
                          (_native_df, ('project_rows',))):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setenv('TPMSHX_DF_METHOD', 'rbf')
    residuals = []
    control = resolve_control(RunControl(residual=lambda *row: residuals.append(row)))
    states = []
    result = full_2d_stage.run_case(case, control, checkpoint=states.append)
    # The last saved boundary holds the inputs and the completed flow grids.
    state = states[-1]
    for index, side in enumerate('AB'):
        flow = case.parameters['flow_inputs'][side]
        np.testing.assert_array_equal(state[f'input.sides.{index}.row_permeability'], flow['K_m2'])
        np.testing.assert_array_equal(state[f'input.sides.{index}.row_forchheimer'], flow['cF_per_m'])
        np.testing.assert_array_equal(state[f'state.result.flow.{index}.dy'], flow['dy'])
    assert result.run_status['execution'] == 'completed'
    assert {side for side, _, _ in residuals} == {'A', 'B'}
    assert all(np.isfinite(value) for _, _, value in residuals)
    flow = {**case.parameters['flow_inputs']['A'], 'dy': np.ones(2)}
    bad = replace(case, parameters={**case.parameters, 'flow_inputs': {**case.parameters['flow_inputs'], 'A': flow}})
    residuals.clear()
    with pytest.raises(ValueError, match='grid disagrees'):
        full_2d_stage.run_case(bad, control)
    assert not residuals

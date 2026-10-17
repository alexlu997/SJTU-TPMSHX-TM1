"""Native SIMPLE consumes frozen drag, even under receiver overrides."""
from dataclasses import replace
import numpy as np
import pytest
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.backends.prepared_2d import build_execution_inputs
from sjtu_tpmshx.domain.module_ports import resolve_control
from sjtu_tpmshx.solvers.backends.cpp.full_2d import NativeFull2DDriver, _pack
from sjtu_tpmshx.tests.integration_tm1.test_2d_real import baseline_config


def test_full_prepared_flow_consumes_drag_without_prediction(monkeypatch):
    from sjtu_tpmshx.df_surrogate import predict
    from sjtu_tpmshx.models import df_projection, grid as grids
    config = baseline_config()
    config.solver = replace(config.solver, max_outer_ltne=2, max_iter_simple=500)
    case = prepare_case(config, case_id='prepared-flow')
    cfg, grid = build_execution_inputs(case)
    def forbidden(*args, **kwargs):
        raise AssertionError('execution rebuilt fixed drag or grid')
    for module, names in ((grids, ('_aligned_grid',)),
                          (predict, ('predict_K_cF', 'predict_K_cF_vec')),
                          (df_projection, ('project_fields_to_streamwise_K_cF',))):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setenv('TPMSHX_DF_METHOD', 'rbf')
    residuals = []
    control = resolve_control(RunControl(residual=lambda *row: residuals.append(row)))
    driver = NativeFull2DDriver(control.native_library)
    _, arrays, _ = _pack(cfg, grid, None, driver.library)
    for index, side in enumerate('AB'):
        np.testing.assert_array_equal(arrays[10+9*index], case.parameters['flow_inputs'][side]['K_m2'])
        np.testing.assert_array_equal(arrays[11+9*index], case.parameters['flow_inputs'][side]['cF_per_m'])
    raw = driver.run_prepared(cfg, grid, control)
    for side, flow in zip('AB', raw['flow']):
        np.testing.assert_array_equal(flow['dy'], case.parameters['flow_inputs'][side]['dy'])
    assert {side for side, _, _ in residuals} == {'A', 'B'}
    assert all(np.isfinite(value) for _, _, value in residuals)
    flow = {**case.parameters['flow_inputs']['A'], 'dy': np.ones(2)}
    bad = replace(case, parameters={**case.parameters, 'flow_inputs': {**case.parameters['flow_inputs'], 'A': flow}})
    with pytest.raises(ValueError, match='grid disagrees'):
        build_execution_inputs(bad)

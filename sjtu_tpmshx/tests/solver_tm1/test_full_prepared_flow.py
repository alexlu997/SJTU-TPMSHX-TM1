"""Full-mode SIMPLE consumes frozen drag, even under receiver overrides."""
from dataclasses import replace
import numpy as np
import pytest
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.backends.python.two_d.execution import build_execution_inputs
from sjtu_tpmshx.solvers.backends.python.two_d.runtime import build_runtime
from sjtu_tpmshx.tests.integration_tm1.test_2d_real import baseline_config


def test_full_prepared_flow_consumes_drag_without_prediction(monkeypatch):
    from sjtu_tpmshx.solvers import simple_solver
    from sjtu_tpmshx.df_surrogate import predict
    from sjtu_tpmshx.models import df_projection
    case = prepare_case(baseline_config(), case_id='prepared-flow')
    cfg, grid = build_execution_inputs(case)
    def forbidden(*args, **kwargs):
        raise AssertionError('execution rebuilt fixed drag or grid')
    for module, names in ((simple_solver, ('_aligned_grid','predict_K_cF','predict_K_cF_vec')),
                          (predict, ('predict_K_cF','predict_K_cF_vec')),
                          (df_projection, ('project_fields_to_streamwise_K_cF','project_cells_to_streamwise_K_cF'))):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(simple_solver.SIMPLESolver, 'solve', lambda *a, **k: (True, 1))
    monkeypatch.setenv('TPMSHX_DF_METHOD', 'rbf')
    run = build_runtime(cfg, grid)['_run_simple']
    for side in ('A', 'B'):
        solver = run(cfg['cfg'+side],1.2,1.8e-5,400.,5.,side)[2]
        np.testing.assert_array_equal(solver._K_arr, case.parameters['flow_inputs'][side]['K_m2'])
        np.testing.assert_array_equal(solver.dy_arr, case.parameters['flow_inputs'][side]['dy'])
    flow = {**case.parameters['flow_inputs']['A'], 'dy': np.ones(2)}
    bad = replace(case, parameters={**case.parameters, 'flow_inputs': {**case.parameters['flow_inputs'], 'A':flow}})
    with pytest.raises(ValueError, match='grid disagrees'):
        build_execution_inputs(bad)

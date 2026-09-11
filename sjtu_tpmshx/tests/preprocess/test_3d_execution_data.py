"""Prepared data must reach 3D execution or be rejected explicitly."""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.model_refs import ModelRef
from sjtu_tpmshx.preprocess.three_d.preparation import prepare_case
from sjtu_tpmshx.solvers.backends.python.three_d.execution import build_execution_inputs


def test_three_d_execution_consumes_design_and_rejects_inconsistent_data():
    config = ComputeConfig()
    config.geometry.Lz_m = .03
    config.solver.Nx, config.solver.Ny, config.solver.Nz = 6, 5, 4
    case = prepare_case(config, case_id='prepared-3d')
    changed = np.asarray(case.design_fields['K_ss']) * 2
    updated = replace(case, design_fields={**case.design_fields, 'K_ss': changed})
    _, prepared = build_execution_inputs(updated)
    np.testing.assert_array_equal(prepared['design']['K_ss'], changed)
    prepared['design']['K_ss'][0, 0, 0] = 1
    assert updated.design_fields['K_ss'][0, 0, 0] != 1
    with pytest.raises(ValueError, match='grid does not cover'):
        build_execution_inputs(replace(case, grid={**case.grid, 'dx': case.grid['dx'] * 2}))
    with pytest.raises(ValueError, match='unknown model resource'):
        build_execution_inputs(replace(case, model_refs=(ModelRef('fluid', 'unknown'), *case.model_refs[1:])))
    with pytest.raises(ValueError, match='does not match the grid'):
        build_execution_inputs(replace(case, design_fields={**case.design_fields, 'K_ss': np.ones((2, 3))}))

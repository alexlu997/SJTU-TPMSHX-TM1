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
        build_execution_inputs(replace(case, grid={**case.grid,
            'dx': case.grid['dx'] * 2, 'x_edges': case.grid['x_edges'] * 2}))
    with pytest.raises(ValueError, match='unknown model resource'):
        build_execution_inputs(replace(case, model_refs=(ModelRef('fluid', 'unknown'), *case.model_refs[1:])))
    with pytest.raises(ValueError, match='does not match the grid'):
        build_execution_inputs(replace(case, design_fields={**case.design_fields, 'K_ss': np.ones((2, 3))}))


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('entry', ['builder', 'public'])
def test_prepared_axis_permutation_must_match_declared_physical_axes(side, entry, tmp_path, monkeypatch):
    from sjtu_tpmshx.domain.portable_data import mutable_data
    from sjtu_tpmshx.io.case_io import save_case, load_case
    from sjtu_tpmshx.solvers.api import run_case
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime
    from sjtu_tpmshx.tests.solver_tm1.test_prepared_continuous_field import _config

    config = _config(volume=True)
    config.geometry = replace(config.geometry, L_dom_m=.06, H_dom_m=.06, Lz_m=.06)
    config.solver = replace(config.solver, Nx=4, Ny=4, Nz=4)
    case = prepare_case(config, case_id='permutation-conflict')
    build_execution_inputs(case)
    parameters = mutable_data(case.parameters)
    axes = parameters['prepared']['axes']
    # Both maps are valid on their own, but equal cell counts cannot justify
    # applying the other side's permutation to this side's declared axes.
    axes[side]['solver_to_real_perm'] = axes['B' if side == 'A' else 'A']['solver_to_real_perm']
    save_case(replace(case, parameters=parameters), tmp_path / 'case.h5')
    restored = load_case(tmp_path / 'case.h5')
    monkeypatch.setattr(runtime, 'build_problem',
                        lambda *a, **k: pytest.fail('conflicting axes reached runtime'))
    with pytest.raises(ValueError, match=f'fluid {side} axis permutation'):
        (run_case if entry == 'public' else build_execution_inputs)(restored)

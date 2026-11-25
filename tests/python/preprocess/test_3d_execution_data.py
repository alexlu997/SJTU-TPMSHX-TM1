"""Prepared data must reach 3D execution or be rejected explicitly."""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.data_types.compute_config import ComputeConfig
from sjtu_tpmshx.data_types.model_refs import ModelRef
from sjtu_tpmshx.preprocess.three_d.preparation import prepare_case
from sjtu_tpmshx.cpp_interface import full_3d_stage
from sjtu_tpmshx.solvers import full_3d
from sjtu_tpmshx.solvers.api import run_case
from tests.python.native.stage_interception import first_state, stage_control


def _rejected(case, message):
    """Require a saved-stage rejection before any native progress."""
    progress = []
    with pytest.raises(ValueError, match=message):
        run_case(case, stage_control(progress=progress.append))
    assert not progress


def test_three_d_execution_consumes_design_and_rejects_inconsistent_data():
    config = ComputeConfig()
    config.geometry.Lz_m = .03
    config.solver.Nx, config.solver.Ny, config.solver.Nz = 6, 5, 4
    case = prepare_case(config, case_id='prepared-3d')
    changed = np.asarray(case.design_fields['K_ss']) * 2
    updated = replace(case, design_fields={**case.design_fields, 'K_ss': changed})
    state = first_state(updated)
    np.testing.assert_array_equal(state['input.geometry.solid_conductivity'], changed.ravel())
    state['input.geometry.solid_conductivity'][0] = 1
    assert updated.design_fields['K_ss'][0, 0, 0] != 1
    _rejected(replace(case, grid={**case.grid, 'dx': case.grid['dx'] * 2, 'x_edges': case.grid['x_edges'] * 2}),
              'grid does not cover')
    fluid = case.model_refs[0]
    _rejected(replace(case, model_refs=(ModelRef(fluid.name, 'unknown', fluid.parameters), *case.model_refs[1:])),
              'unknown model resource')
    _rejected(replace(case, design_fields={**case.design_fields, 'K_ss': np.ones((2, 3))}), 'does not match the grid')


@pytest.mark.parametrize('side', ['A', 'B'])
@pytest.mark.parametrize('entry', ['validator', 'public'])
def test_prepared_axis_permutation_must_match_declared_physical_axes(side, entry, tmp_path, monkeypatch):
    from sjtu_tpmshx.data_types.portable_data import mutable_data
    from sjtu_tpmshx.file_io.case_io import save_case, load_case
    from tests.python.solver_tm1.test_prepared_continuous_field import _config

    config = _config(volume=True)
    config.geometry = replace(config.geometry, L_dom_m=.06, H_dom_m=.06, Lz_m=.06)
    config.solver = replace(config.solver, Nx=4, Ny=4, Nz=4)
    case = prepare_case(config, case_id='permutation-conflict')
    full_3d.validate_saved_axes(case)
    parameters = mutable_data(case.parameters)
    axes = parameters['prepared']['axes']
    # Both maps are valid on their own, but equal cell counts cannot justify
    # applying the other side's permutation to this side's declared axes.
    axes[side]['solver_to_real_perm'] = axes['B' if side == 'A' else 'A']['solver_to_real_perm']
    save_case(replace(case, parameters=parameters), tmp_path / 'case.h5')
    restored = load_case(tmp_path / 'case.h5')
    monkeypatch.setattr(full_3d_stage, 'run_saved',
                        lambda *a, **k: pytest.fail('conflicting axes reached runtime'))
    with pytest.raises(ValueError, match=f'fluid {side} axis permutation'):
        if entry == 'public':
            run_case(restored, stage_control())
        else:
            full_3d.validate_saved_axes(restored)

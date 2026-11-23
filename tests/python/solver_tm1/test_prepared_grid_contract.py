"""Full execution and file handoff enforce the same physical grid axes."""
from dataclasses import replace

import numpy as np
import pytest

from sjtu_tpmshx.data_types.compute_config import ComputeConfig
from sjtu_tpmshx.file_io.case_io import load_case, save_case
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.cpp_interface import full_2d_stage, full_3d_stage
from tests.python.native.stage_interception import first_state, stage_control


@pytest.fixture(params=[2, 3], ids=['2d', '3d'])
def prepared_case(request):
    config = ComputeConfig()
    config.solver.Nx, config.solver.Ny = 4, 3
    config.solver.Nz = 1 if request.param == 2 else 2
    config.geometry.Lz_m = .03
    return prepare_case(config, case_id=f'grid-{request.param}d')


def _validate(case):
    """Apply the saved-stage grid validation of the case dimension."""
    if case.grid['dimension'] == 2:
        full_2d_stage.execution_grid(case)
    else:
        full_3d_stage.validate_saved_case(case)


@pytest.mark.parametrize('axes', ['reversed', 'missing'])
@pytest.mark.parametrize('entry', ['validator', 'public'])
def test_invalid_axes_rejected_before_runtime_and_file_handoff(
        prepared_case, axes, entry, monkeypatch, tmp_path):
    grid = dict(prepared_case.grid)
    if axes == 'missing':
        grid.pop('axis_order')
    else:
        grid['axis_order'] = tuple(reversed(grid['axis_order']))
    case = replace(prepared_case, grid=grid)
    with pytest.raises(ValueError, match='axis order'):
        save_case(case, tmp_path / 'invalid.h5')

    def unexpected_runtime(*args, **kwargs):
        pytest.fail('invalid grid axes reached numerical runtime construction')
    monkeypatch.setattr(full_2d_stage, 'run_stage', unexpected_runtime)
    monkeypatch.setattr(full_3d_stage, 'run_saved', unexpected_runtime)
    with pytest.raises(ValueError, match='axis order'):
        if entry == 'public':
            run_case(case, stage_control())
        else:
            _validate(case)


def test_valid_grid_handoff_preserves_widths_and_private_execution_copy(prepared_case, tmp_path):
    save_case(prepared_case, tmp_path / 'case.h5')
    restored = load_case(tmp_path / 'case.h5')
    state = first_state(restored)
    for axis in restored.grid['axis_order']:
        key = ('input.grid.d' if restored.grid['dimension'] == 2 else 'input.geometry.grid.d') + axis
        np.testing.assert_array_equal(state[key], prepared_case.grid['d' + axis])
        assert len(state[key]) == state[key[:-2] + 'n' + axis][0]
        state[key][0] = 0.
        assert restored.grid['d' + axis][0] > 0.


def test_execution_extent_uses_runtime_width_precision(prepared_case, tmp_path):
    widths = np.full(len(prepared_case.grid['dx']), .01, dtype=np.float32)
    widths[0] = .02
    edges = np.r_[0., np.cumsum(widths)]
    case = replace(prepared_case,
        grid={**prepared_case.grid, 'dx': widths, 'x_edges': edges},
        parameters={**prepared_case.parameters, 'L': float(edges[-1])})
    # The archive is internally consistent at float32 precision. Execution
    # consumes float64 widths, whose extent must still cover the given domain.
    save_case(case, tmp_path / 'float32.h5')
    progress = []
    with pytest.raises(ValueError, match='grid does not cover'):
        run_case(load_case(tmp_path / 'float32.h5'), stage_control(progress=progress.append))
    assert not progress

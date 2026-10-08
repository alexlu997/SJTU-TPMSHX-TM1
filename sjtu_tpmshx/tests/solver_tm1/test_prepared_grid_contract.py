"""Full execution and file handoff enforce the same physical grid axes."""
from dataclasses import replace
from importlib import import_module

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.io.case_io import load_case, save_case
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case


@pytest.fixture(params=[2, 3], ids=['2d', '3d'])
def prepared_case(request):
    config = ComputeConfig()
    config.solver.Nx, config.solver.Ny = 4, 3
    config.solver.Nz = 1 if request.param == 2 else 2
    config.geometry.Lz_m = .03
    return prepare_case(config, case_id=f'grid-{request.param}d')


def _execution(case):
    dimension = 'two_d' if case.grid['dimension'] == 2 else 'three_d'
    return import_module(f'sjtu_tpmshx.solvers.backends.python.{dimension}.execution')


@pytest.mark.parametrize('axes', ['reversed', 'missing'])
@pytest.mark.parametrize('entry', ['builder', 'public'])
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

    execution = _execution(case)
    def unexpected_runtime(*args, **kwargs):
        pytest.fail('invalid grid axes reached numerical runtime construction')
    if case.grid['dimension'] == 2:
        runtime = import_module('sjtu_tpmshx.solvers.backends.python.two_d.runtime')
        monkeypatch.setattr(runtime, 'build_runtime', unexpected_runtime)
    else:
        runtime = import_module('sjtu_tpmshx.solvers.backends.python.three_d.runtime')
        monkeypatch.setattr(runtime, 'build_problem', unexpected_runtime)
    with pytest.raises(ValueError, match='axis order'):
        (run_case if entry == 'public' else execution.build_execution_inputs)(case)


def test_valid_grid_handoff_preserves_widths_and_private_execution_copy(prepared_case, tmp_path):
    save_case(prepared_case, tmp_path / 'case.h5')
    restored = load_case(tmp_path / 'case.h5')
    cfg, grid = _execution(restored).build_execution_inputs(restored)
    for axis in restored.grid['axis_order']:
        key = ('energy_d' if restored.grid['dimension'] == 2 else 'd') + axis
        np.testing.assert_array_equal(grid[key], prepared_case.grid['d' + axis])
        assert len(grid[key]) == (cfg['N_' + axis] if restored.grid['dimension'] == 2
                                 else grid['N' + axis])
        grid[key][0] = 0.
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
    with pytest.raises(ValueError, match='grid does not cover'):
        _execution(case).build_execution_inputs(load_case(tmp_path / 'float32.h5'))

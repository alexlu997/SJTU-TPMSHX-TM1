"""The saved native velocity control must reach its prepared consumer."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.io.case_io import load_case, save_case
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case


@pytest.mark.parametrize('dimension', [2, 3])
@pytest.mark.parametrize('value', [None, .35, 1.])
def test_relaxation_survives_config_and_prepared_file(tmp_path, dimension, value):
    cfg = ComputeConfig()
    cfg.solver = replace(cfg.solver, Nx=6, Ny=6, Nz=3 if dimension == 3 else 1,
                         simple_velocity_relaxation=value)
    if dimension == 3:
        cfg.geometry.Lz_m = .012
    cfg.validate_static_inputs()
    restored = ComputeConfig.from_dict(cfg.to_dict())
    assert restored.solver.simple_velocity_relaxation == value
    prepared = prepare_case(restored, case_id='flow-relaxation')
    path = tmp_path / 'case.h5'
    save_case(prepared, path)
    loaded = load_case(path)
    settings = loaded.parameters['run_settings']['solver'] if dimension == 2 else loaded.parameters
    assert settings['simple_velocity_relaxation'] == value


@pytest.mark.parametrize('value', [0., -1., 1.01, True, '0.35', float('nan'), float('inf')])
def test_invalid_relaxation_is_rejected_before_preparation(value):
    cfg = ComputeConfig()
    cfg.solver.simple_velocity_relaxation = value
    with pytest.raises(ValueError, match='simple_velocity_relaxation'):
        cfg.validate_static_inputs()


@pytest.mark.parametrize('dimension,backend,mode', [(2, 'python', 'full'), (3, 'python', 'full'),
                                                   (2, 'cpp', 'quick_design')])
def test_unsupported_route_rejects_relaxation_before_dispatch(dimension, backend, mode):
    settings = dict(simple_velocity_relaxation=.35)
    case = SimpleNamespace(grid={'dimension': dimension}, metadata={'mode': mode},
        parameters={'run_settings': {'solver': settings}} if dimension == 2 else settings)
    with pytest.raises(ValueError, match='simple_velocity_relaxation requires full compute with backend=cpp'):
        run_case(case, RunControl(backend=backend))

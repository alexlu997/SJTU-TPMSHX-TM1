"""Real module execution and offline application mapping, including old slots."""
from collections.abc import Mapping
from dataclasses import replace
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.controllers.module_adapter import to_compute_result
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.io.result_io import load_result, save_result
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.tests.integration_tm1.test_2d_real import baseline_config
from sjtu_tpmshx.tests.test_pipeline_3d_e2e import _small_air_cfg


def assert_slots(actual, expected):
    if isinstance(expected, Mapping):
        for key, value in expected.items():
            assert key in actual, key
            assert_slots(actual[key], value)
    elif isinstance(expected, (list, tuple)):
        assert len(actual) == len(expected)
        for left, right in zip(actual, expected):
            assert_slots(left, right)
    elif isinstance(expected, (np.ndarray, int, float, np.number)):
        np.testing.assert_allclose(actual, expected, rtol=1e-10, atol=1e-10, equal_nan=True)
    else:
        assert actual == expected


@pytest.mark.slow
@pytest.mark.parametrize('dimension', [2, 3])
def test_real_application_mapping_and_offline_readback(monkeypatch, tmp_path, dimension):
    config = baseline_config() if dimension == 2 else _small_air_cfg()
    expected = []
    if dimension == 2:
        from sjtu_tpmshx.solvers.backends.python.two_d import result_capture
        from sjtu_tpmshx.tests.integration_tm1.legacy_result_mapping import _finalize_cfg
        capture = result_capture.capture_result
        def checked_capture(case, raw):
            result = capture(case, raw)
            legacy = dict(raw)
            for group in ('coeffs', 'props'):
                legacy.update({'_shim_' + name: value
                               for name, value in raw['application'][group].items()})
            legacy.update({'_shim_zone_' + name: value for name, value in
                           (raw['application']['zones'] or {}).items()})
            parsed = dict(compute_cfg=config, N_x=len(case.grid['dx']), N_y=len(case.grid['dy']),
                          L=case.parameters['L'], H=case.parameters['H'],
                          dir_A=case.parameters['dir_A'], dir_B=case.parameters['dir_B'],
                          zone_config=None, za=None, extrap_reasons=case.parameters['extrap_reasons'])
            expected.append(lambda: _finalize_cfg(legacy, parsed))
            return result
    else:
        from sjtu_tpmshx.solvers.backends.python.three_d import result_capture
        from sjtu_tpmshx.tests.integration_tm1.legacy_result_mapping import _finalize_3d_cfg
        capture = result_capture.capture_result
        def checked_capture(case, problem, outer, raw):
            result = capture(case, problem, outer, raw)
            expected.append(lambda: _finalize_3d_cfg(dict(raw), dict(
                compute_cfg=config, extrap_reasons=case.parameters['extrap_reasons'])))
            return result
    monkeypatch.setattr(result_capture, 'capture_result', checked_capture)
    case = prepare_case(config, case_id=f'application-{dimension}d')
    # The prepared boundary owns fixed geometry, including the air bulk
    # closure. Temperature-dependent fluid/Nu evaluation remains permitted.
    from sjtu_tpmshx.models import tpms_props, tpms_calc, tpms_geometry
    def forbidden_geometry(*args, **kwargs):
        raise AssertionError('execution rebuilt prepared thermal geometry')
    with monkeypatch.context() as geometry_guard:
        geometry_guard.setattr(tpms_props, 'geometry', forbidden_geometry)
        geometry_guard.setattr(tpms_calc, 'geometry', forbidden_geometry)
        geometry_guard.setattr(tpms_geometry, '_phi_grid', forbidden_geometry)
        result = run_case(case, RunControl())
    performance = evaluate(result)
    actual = to_compute_result(result, performance)
    reference = expected[0]()
    for slot in ('fields', 'coeffs', 'props', 'diagnostics', 'metadata', 'extrap_reasons'):
        assert_slots(getattr(actual, slot), getattr(reference, slot))
    # Old backend scalars remain an oracle for unchanged fields. The public
    # thermal metrics now deliberately use one native boundary state.
    native_residuals = {'Q_A', 'Q_B', 'Q_net', 'energy_imbalance_rel', 'enthalpy_imbalance_rel',
                        'mass_imbalance_rel_A', 'mass_imbalance_rel_B'}
    assert_slots(actual.residuals, {k: v for k, v in reference.residuals.items() if k not in native_residuals})
    for name in ('Q_A', 'Q_B', 'energy_imbalance_rel', 'mass_imbalance_rel_A', 'mass_imbalance_rel_B'):
        assert actual.residuals[name] == performance.metrics[name].value
    assert actual.Q_W == abs(actual.residuals['Q_A'])
    assert set(reference.warnings) <= set(actual.warnings)
    for side in ('A', 'B'):
        assert_slots(getattr(actual, f'dP_{side}_Pa'), performance.metrics[f'dP_{side}'].value)
        assert performance.metrics[f'dP_{side}'].spec.definition_version == 'pressure_face_v1'
    for name in ('T_out_A_K', 'T_out_B_K', 'converged'):
        assert_slots(getattr(actual, name), getattr(reference, name))
    assert actual.metadata['units']['Q'] == ('W/m' if dimension == 2 else 'W')
    assert actual.metadata['metric_definitions']['Q']['definition_version'] == 'native_boundary_v1'
    with pytest.raises(ValueError, match='another result'):
        to_compute_result(result, replace(performance, source_result_id='other'))
    path = tmp_path / 'results.h5'
    save_result(result, path)
    loaded = load_result(path)
    archived = to_compute_result(loaded, evaluate(loaded))
    assert_slots(archived.fields, actual.fields)
    child = subprocess.run([sys.executable, '-c', '''
import sys
from sjtu_tpmshx.io.result_io import load_result
from sjtu_tpmshx.postprocess.api import evaluate
from sjtu_tpmshx.controllers.module_adapter import to_compute_result
result = load_result(sys.argv[1])
display = to_compute_result(result, evaluate(result))
assert display.metadata['source_result_id'] == result.result_id
from pathlib import Path
import numpy as np
from sjtu_tpmshx.postprocess.export import export_vtk
from vtkmodules.vtkIOLegacy import vtkRectilinearGridReader
from vtkmodules.util.numpy_support import vtk_to_numpy
vtk_path = export_vtk(result, Path(sys.argv[1]).with_suffix('.vtk'))
reader = vtkRectilinearGridReader()
reader.SetFileName(str(vtk_path))
reader.ReadAllScalarsOn()
reader.Update()
grid = reader.GetOutput()
assert grid.GetNumberOfCells() == np.prod(result.fields['Ta'].shape)
for name, values in result.fields.items():
    np.testing.assert_array_equal(vtk_to_numpy(grid.GetCellData().GetArray(name)),
                                  np.asarray(values).ravel(order='F'))
for prefix in ('sjtu_tpmshx.solvers', 'sjtu_tpmshx.preprocess', 'sjtu_tpmshx.pipelines', 'numba', 'PySide6'):
    assert not any(name == prefix or name.startswith(prefix + '.') for name in sys.modules), prefix
''', str(path)], capture_output=True, text=True, timeout=30)
    assert child.returncode == 0, child.stdout + child.stderr

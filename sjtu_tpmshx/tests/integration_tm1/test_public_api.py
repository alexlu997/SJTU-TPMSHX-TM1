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


def legacy_2d_result(case, display_fields, diagnostics):
    """Recreate the retired 2D input for the frozen application-mapping oracle."""
    raw = {key: display_fields[key + '_display'] for key in ('Ta', 'Tb', 'Ts', 'P_fA', 'P_fB')}
    for key in ('ucA', 'vcA', 'ucB', 'vcB'):
        raw[key] = display_fields[key]
        raw[key + '_disp'] = display_fields.get(key + '_display')
    raw.update(energy_dx=case.grid['dx'], energy_dy=case.grid['dy'])
    raw.update(diagnostics)
    return raw


def native_3d_mapping_input(case, cfg, prepared, raw, diagnostics):
    """Read the detached C++ fields for the application-mapping oracle."""
    a, b = raw['flow']
    values = dict(zip(('Ta', 'Tb', 'Ts'), raw['temperature']))
    values.update(vmag=a['speed_real'], vmag_B=b['speed_real'],
        P_kPa=a['pressure_real']/1000., P_Pa=a['pressure_real'], P_Pa_B=b['pressure_real'],
        L_mm=case.design_fields['L_field_m']*1000.,
        dx=case.grid['dx'], dy=case.grid['dy'], dz=case.grid['dz'],
        h_vA_field=raw['hv'][0], h_vB_field=raw['hv'][1])
    for suffix, flow in (('', a), ('_B', b)):
        values.update({axis+'_real'+suffix: field
                       for axis, field in zip(('uc', 'vc', 'wc'), flow['velocity_real'])})
    values.update(diagnostics)
    if cfg.get('_emit_audit', False):
        values.update(_audit_K_ffA=raw['final_conductivity'][0],
            _audit_K_ffB=raw['final_conductivity'][1], _audit_K_ss=prepared['design']['K_ss'],
            _audit_rho_cp_fA=raw['final_rho_cp'][0], _audit_rho_cp_fB=raw['final_rho_cp'][1])
    return values


@pytest.mark.slow
@pytest.mark.parametrize('dimension', [2, 3])
def test_real_application_mapping_and_offline_readback(monkeypatch, tmp_path, dimension):
    config = baseline_config() if dimension == 2 else _small_air_cfg()
    expected = []
    if dimension == 2:
        from sjtu_tpmshx.solvers.backends.cpp import full_2d_capture as result_capture
        from sjtu_tpmshx.tests.integration_tm1.legacy_result_mapping import _finalize_cfg
        capture = result_capture._capture_result
        def checked_capture(case, display_fields, native, application, diagnostics, **kwargs):
            result = capture(case, display_fields, native, application, diagnostics, **kwargs)
            legacy = legacy_2d_result(case, display_fields, diagnostics)
            for group in ('coeffs', 'props'):
                legacy.update({'_shim_' + name: value
                               for name, value in application[group].items()})
            legacy.update({'_shim_zone_' + name: value for name, value in
                           (application['zones'] or {}).items()})
            parsed = dict(compute_cfg=config, N_x=len(case.grid['dx']), N_y=len(case.grid['dy']),
                          L=case.parameters['L'], H=case.parameters['H'],
                          dir_A=case.parameters['dir_A'], dir_B=case.parameters['dir_B'],
                          zone_config=None, za=None, extrap_reasons=case.parameters['extrap_reasons'])
            expected.append(lambda: _finalize_cfg(legacy, parsed))
            return result
    else:
        from sjtu_tpmshx.solvers.backends.cpp import full_3d_capture as result_capture
        from sjtu_tpmshx.tests.integration_tm1.legacy_result_mapping import _finalize_3d_cfg
        capture = result_capture.capture_result
        def checked_capture(case, cfg, prepared, native, abi):
            result = capture(case, cfg, prepared, native, abi)
            raw = native_3d_mapping_input(case, cfg, prepared, native, result.metadata['diagnostics'])
            expected.append(lambda: _finalize_3d_cfg(dict(raw), dict(
                compute_cfg=config, extrap_reasons=case.parameters['extrap_reasons'])))
            return result
    monkeypatch.setattr(result_capture, '_capture_result' if dimension == 2 else 'capture_result', checked_capture)
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
    assert_slots(actual.metadata['execution_record'], result.metadata['execution_record'])
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
        to_compute_result(result, replace(performance, source_result_id='other', qualification={}))
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
from sjtu_tpmshx.domain.portable_data import mutable_data
assert display.metadata['execution_record'] == mutable_data(result.metadata['execution_record'])
sample = display.metadata['execution_record']['property_sampling']['records'][0]
original_stage = result.metadata['execution_record']['property_sampling']['records'][0]['stage']
sample['stage'] = 'GUI edit'
assert result.metadata['execution_record']['property_sampling']['records'][0]['stage'] == original_stage
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

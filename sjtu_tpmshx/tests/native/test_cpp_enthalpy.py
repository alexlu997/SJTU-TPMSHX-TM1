"""Public true-h C ABI and thin Python adapter use the frozen driver gates."""
import copy
import ctypes as ct
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import warnings

import CoolProp.CoolProp as CP
import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.models.fluid_props import WaterStateError
from sjtu_tpmshx.solvers.backends.cpp.enthalpy import NativeEnthalpyDriver
from sjtu_tpmshx.solvers import ltne_enthalpy_3d as python
from sjtu_tpmshx.tests.native.test_enthalpy_driver import (
    TABLES, assert_same, case_data, library_path,
)


@pytest.fixture(scope='module')
def driver_library():
    name = ('tpmshx_enthalpy_shared.dll' if os.name == 'nt' else
            'libtpmshx_enthalpy_shared.dylib' if sys.platform == 'darwin'
            else 'libtpmshx_enthalpy_shared.so')
    path = Path(os.environ.get('TPMSHX_ENTHALPY_LIBRARY', str(library_path().with_name(name)))).resolve()
    if not path.is_file():
        message = f'public native true-h library is not built: {path}'
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1' or 'TPMSHX_ENTHALPY_LIBRARY' in os.environ:
            pytest.fail(message)
        pytest.skip(message)
    return path


@pytest.fixture(scope='module')
def driver(driver_library):
    return NativeEnthalpyDriver(driver_library, table_directory=TABLES)


def qualification_record(result):
    a, b, solid, info = result
    state = info['_native_state']
    eos = state.get('sco2_enthalpy_eos', {})
    coupled, eq = info.get('coupled_energy_balance'), info.get('equation_energy_balance')
    statuses = ({'converged': 0, 'enthalpy_limited': 1, 'iteration_limit': 2}[info['exit_reason']],
        info['iterations'], 0, *info['enthalpy_clip_counts']['last'], *info['enthalpy_clip_counts']['total'],
        *(int(side in eos.get('sides', [])) for side in 'AB'), int(eos.get('heos_polish', False)),
        int(coupled is not None), int(eq is not None))
    metrics = [info['residual'], info['Q_A'], info['Q_B'], info['energy_imbalance_rel'],
               state['h_in_A'], state['h_in_B']]
    metrics += ([info['Q_A'], info['Q_B'], coupled['net'], coupled['solid_abs_sum'],
                 coupled['denominator'], coupled['ratio']] if coupled else [np.nan] * 6)
    metrics += ([*eq['fluid_abs_sum'], *eq['fluid_cell_max'], eq['ratio']] if eq else [np.nan] * 5)
    return dict(code=0, error='', fields=[a, b, solid], h=[state['h_A'], state['h_B']],
                status=statuses, metrics=np.array(metrics))


@pytest.mark.parametrize('pair', [('air', 'water'), ('water', 'air'), ('sco2', 'sco2'),
                                  ('sco2', 'water'), ('sco2', 'air'), ('water', 'sco2')])
@pytest.mark.parametrize('shape,warm', [((4, 3, 1), False), ((4, 3, 2), True)])
def test_public_driver_has_same_complete_solve_and_evidence(driver, pair, shape, warm):
    case = case_data(pair, shape, warm=warm)
    actual = driver(**case)
    assert_same(case, qualification_record(actual))
    settings = actual[3]['effective_settings']
    assert settings['thermal_driver'] == settings['sweep_kernel'] == settings['energy_audit'] == 'cpp'
    assert settings['driver_abi'] == 1
    eos = actual[3]['_native_state'].get('sco2_enthalpy_eos')
    if eos:
        assert eos['coolprop_version'] == '8.0.0'


@pytest.mark.parametrize('coupled,equation', [(None, None), (1e-3, None), (None, 1e-3)])
def test_public_optional_audit_presence_is_preserved(driver, coupled, equation):
    case = case_data(('sco2', 'water'), shape=(3, 2, 1))
    case.update(coupled_energy_tol=coupled, equation_energy_tol=equation)
    assert_same(case, qualification_record(driver(**case)))


def test_unit_depth_extrusion_preserves_temperature_and_scales_duty(driver):
    physical = case_data(('sco2', 'water'), shape=(4, 3, 1))
    per_metre = copy.deepcopy(physical)
    thickness = float(physical['dz'][0])
    per_metre['dz'][:] = 1.
    for side in 'AB':
        per_metre['mass_flux_'+side] = tuple(face / thickness for face in physical['mass_flux_'+side])
    a, b = driver(**physical), driver(**per_metre)
    for x, y in zip(a[:3], b[:3]):
        np.testing.assert_allclose(x, y, rtol=2e-10, atol=2e-8)
    for key in ('Q_A', 'Q_B'):
        assert a[3][key] == pytest.approx(thickness * b[3][key], rel=2e-8, abs=2e-8)


def test_readonly_inputs_and_warm_states_remain_unchanged(driver):
    case = case_data(warm=True)
    arrays = [value for value in case.values() if isinstance(value, np.ndarray)]
    arrays += [face for side in 'AB' for face in case['mass_flux_'+side]]
    copies = [value.copy() for value in arrays]
    for value in arrays:
        value.flags.writeable = False
    result = driver(**case)
    assert result[3]['iterations'] > 0
    for value, initial in zip(arrays, copies):
        np.testing.assert_array_equal(value, initial)
    assert all(not np.shares_memory(value, seed) for value in result[:3] for seed in arrays)


def test_native_driver_has_no_python_eos_or_numerical_callback(driver, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('complete native true-h solve called a Python numerical/EOS operation')
    for name in ('_prop_field', '_T_of_h_field', '_gs_enthalpy_sweeps_3d',
                 '_boundary_enthalpy_duty', '_coupled_energy_balance', '_fluid_energy_residual'):
        monkeypatch.setattr(python, name, forbidden)
    monkeypatch.setattr(CP, 'PropsSI', forbidden)
    monkeypatch.setattr(CP, 'AbstractState', forbidden)
    result = driver(**case_data(('sco2', 'water'), shape=(3, 2, 1)))
    assert result[3]['converged']


@pytest.mark.parametrize('cancel_at', [1, 2, 3])
def test_cancelled_solve_raises_without_publishing_partial_fields(driver, cancel_at):
    calls = 0
    def cancel():
        nonlocal calls
        calls += 1
        return calls == cancel_at
    with pytest.raises(CancelledError, match='cancelled'):
        driver(**case_data(), cancel_check=cancel)
    assert calls == cancel_at


def test_cancel_callback_exception_is_propagated(driver):
    failure = RuntimeError('cancel callback sentinel')
    def cancel():
        raise failure
    with pytest.raises(RuntimeError) as caught:
        driver(**case_data(), cancel_check=cancel)
    assert caught.value is failure


@pytest.mark.parametrize('stage', ['inlet', 'warm_nan', 'warm_vapor', 'local_pressure_nan', 'local_low_pressure'])
def test_water_error_type_and_context_match_python(driver, stage):
    case = case_data(('water', 'air'), shape=(2, 1, 1))
    if stage == 'inlet':
        case['T_inA'] = 500.
    elif stage.startswith('warm'):
        case['Ta_init'] = np.full((2, 1, 1), np.nan if stage == 'warm_nan' else 500.)
    else:
        case['pressure_A_field'][:] = np.nan if stage == 'local_pressure_nan' else 1000.
    with pytest.raises(WaterStateError):
        python.solve_ltne_enthalpy_3d_pipeline(**case)
    with pytest.raises(WaterStateError, match='P_abs='):
        driver(**case)


def test_coolprop_value_error_does_not_become_generic_native_error(driver):
    case = case_data(('air', 'air'), shape=(2, 1, 1))
    case['T_inA'] = 50.
    with pytest.raises(ValueError):
        python.solve_ltne_enthalpy_3d_pipeline(**case)
    with pytest.raises(ValueError):
        driver(**case)


@pytest.mark.parametrize('key,value', [('T_inA', 279.), ('T_inA', 701.),
                                      ('P_A', 7.8e6), ('P_A', 16.1e6),
                                      ('pressure_A_field', np.nan)])
def test_actual_sco2_domain_error_remains_value_error(driver, key, value):
    case = case_data(('sco2', 'water'), shape=(2, 1, 1))
    if key == 'pressure_A_field':
        case[key][:] = value
    else:
        case[key] = value
    with pytest.raises(ValueError):
        python.solve_ltne_enthalpy_3d_pipeline(**case)
    with pytest.raises(ValueError):
        driver(**case)


def test_native_call_keeps_python_coolprop_config_and_warning_evidence(driver):
    case = case_data(('sco2', 'water'), shape=(3, 2, 1))
    before = CP.get_config_as_json_string()
    with warnings.catch_warnings(record=True) as native_warnings:
        warnings.simplefilter('always')
        driver(**case)
    with warnings.catch_warnings(record=True) as python_warnings:
        warnings.simplefilter('always')
        python.solve_ltne_enthalpy_3d_pipeline(**case)
    assert CP.get_config_as_json_string() == before
    assert [str(w.message) for w in native_warnings] == [str(w.message) for w in python_warnings]


def test_public_concurrent_first_use_keeps_run_state_and_python_configuration(driver_library):
    script = r'''
import sys
from concurrent.futures import ThreadPoolExecutor
import CoolProp.CoolProp as CP
import numpy as np
from sjtu_tpmshx.solvers.backends.cpp.enthalpy import NativeEnthalpyDriver
from sjtu_tpmshx.tests.native.test_enthalpy_driver import TABLES, case_data, assert_same
from sjtu_tpmshx.tests.native.test_cpp_enthalpy import qualification_record
driver=NativeEnthalpyDriver(sys.argv[1],table_directory=TABLES)
case=case_data(('sco2','water'),shape=(3,2,1))
before=CP.get_config_as_json_string()
with ThreadPoolExecutor(max_workers=2) as pool:
    results=list(pool.map(lambda _:driver(**case),range(2)))
assert CP.get_config_as_json_string()==before
for result in results: assert_same(case,qualification_record(result))
for a,b in zip(results[0][:3],results[1][:3]):
    assert not np.shares_memory(a,b)
    np.testing.assert_array_equal(a,b)
print('public concurrent first use ok')
'''
    result = subprocess.run([sys.executable, '-c', script, str(driver_library)],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout+result.stderr
    assert 'public concurrent first use ok' in result.stdout


def test_missing_and_relative_library_requests_never_fall_back(tmp_path):
    with pytest.raises(ValueError, match='absolute'):
        NativeEnthalpyDriver('relative.so')
    with pytest.raises(FileNotFoundError):
        NativeEnthalpyDriver(tmp_path / 'missing.so')


def test_co2_requires_explicit_tables_after_first_cancellation(driver_library):
    driver = NativeEnthalpyDriver(driver_library)
    assert driver(**case_data(shape=(2, 1, 1)))[3]['converged']
    co2 = case_data(('sco2', 'water'), shape=(2, 1, 1))
    with pytest.raises(CancelledError):
        driver(**co2, cancel_check=lambda: True)
    with pytest.raises(ValueError, match='absolute directory'):
        driver(**co2)


def test_table_directory_cannot_change_for_loaded_library(driver, driver_library, tmp_path):
    case = case_data(('sco2', 'water'), shape=(2, 1, 1))
    driver(**case)
    assert (Path(driver.table_directory.decode()) / 'CoolProp-8.0.0').is_dir()
    with pytest.raises(ValueError, match='absolute path'):
        NativeEnthalpyDriver(driver_library, table_directory='relative')
    changed = tmp_path / 'other-tables'
    other = NativeEnthalpyDriver(driver_library, table_directory=changed)
    with pytest.raises(ValueError, match='already fixed'):
        other(**case)
    assert not changed.exists()


def test_wrong_abi_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / 'fake.so'
    path.touch()
    monkeypatch.setattr(ct, 'CDLL', lambda _: SimpleNamespace(tpmshx_enthalpy_driver_abi_version=lambda: 99))
    with pytest.raises(ValueError, match='ABI: 99; expected 1'):
        NativeEnthalpyDriver(path)


@pytest.mark.parametrize('kind', ['cell', 'face', 'warm', 'negative_budget', 'huge_budget', 'gate'])
def test_invalid_public_inputs_are_rejected(driver, kind):
    case = case_data()
    if kind == 'cell':
        case['pressure_A_field'] = np.zeros((1, 1, 1))
    elif kind == 'face':
        case['mass_flux_A'] = case['mass_flux_A'][:2]
    elif kind == 'warm':
        case['Ta_init'] = np.zeros((1, 1, 1))
    elif kind == 'negative_budget':
        case['n_outer'] = -1
    elif kind == 'huge_budget':
        case['n_outer'] = 2**100
    else:
        case['coupled_energy_tol'] = np.nan
    with pytest.raises(ValueError):
        driver(**case)


def test_pure_c_static_and_shared_callers(driver_library):
    environment = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'CONDA'))
        and k not in ('VIRTUAL_ENV', 'DYLD_LIBRARY_PATH', 'DYLD_FALLBACK_LIBRARY_PATH')}
    if os.name != 'nt':
        environment['PATH'] = '/usr/bin:/bin'
    for kind in ('static', 'shared'):
        path = driver_library.with_name('enthalpy_c_'+kind+('.exe' if os.name == 'nt' else ''))
        result = subprocess.run([str(path)], env=environment, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout+result.stderr
        assert 'enthalpy C ABI ok' in result.stdout and 'CoolProp=8.0.0' in result.stdout

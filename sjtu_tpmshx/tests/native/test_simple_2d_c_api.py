"""Public SIMPLE C ABI/binding qualification with the unchanged Python oracle."""
import copy
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.solvers._solve_common import F2Monitor
from sjtu_tpmshx.solvers.backends.cpp.simple_2d import NativeSimple2D
from sjtu_tpmshx.tests.native import test_simple_2d as oracle


@pytest.fixture(scope='module')
def public_library():
    root = Path(__file__).resolve().parents[3]
    host = 'windows-x64' if os.name == 'nt' else 'macos-arm64'
    name = 'tpmshx_simple_2d_shared.dll' if os.name == 'nt' else 'libtpmshx_simple_2d_shared.dylib'
    path = Path(os.environ.get('TPMSHX_SIMPLE2D_LIBRARY', root/'.cache/native-deps/build'/f'pilot-{host}'/name))
    if not path.is_file():
        message = f'explicit SIMPLE C ABI build is missing {path}'
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1':
            pytest.fail(message)
        pytest.skip(message)
    return path


def arguments(solver):
    names = ('epsilon', 'viscosity', 'effective_viscosity', 'permeability', 'forchheimer',
             'temperature', 'u', 'v', 'pressure', 'pressure_correction', 'd_u', 'd_v',
             'density', 'inlet_velocity', 'inlet_fraction', 'outlet_u_fraction')
    fields = dict(zip(names, oracle.packed(solver)))
    monitor = F2Monitor(solver, (solver.u, solver.v), 20)
    settings = dict(max_iterations=600, inner_sweeps=2, alpha_velocity=.7, alpha_pressure=.3,
        alpha_density=solver.alpha_rho, pressure_reference_absolute=solver.P_ref_abs,
        gas_constant=solver.R_gas, cf_anisotropy=solver.cf_aniso,
        ideal_gas=int(solver.fluid_type == 'ideal_gas'), massflux_inlet=1, close_outlet_on_exit=1,
        reference_inlet_velocity=solver.v_inlet, taper_flux_scale=solver._inlet_taper_flux_scale,
        inlet_density_reference=solver._rho_inlet_ref,
        f2=dict(momentum_tolerance=monitor.mom_tol, local_mass_tolerance=monitor.mass_local_tol,
            global_mass_tolerance=monitor.mass_global_tol, backflow_maximum=monitor.backflow_max,
            velocity_check_tolerance=monitor.vtol, stall_ratio=monitor.stall_ratio,
            confirmations=monitor.n_confirm, momentum_interval=monitor.mom_every, stall_window=monitor.stall_window))
    return dict(fields=fields, settings=settings)


def create(path, solver):
    return NativeSimple2D(path, dx=solver.dx_arr, dy=solver.dy_arr,
                          outlet_open=solver.outlet_geom_frac > 0)


def compare(result, handle, expected, reference):
    assert (result['converged'], result['iterations']) == reference
    assert result['exit_reason'] == expected.exit_reason
    assert result['post_closure_certified'] == bool(expected.f2_cert_post_rescale_ok)
    assert result['post_closure_measured'] == (expected.f2_cert_post_rescale_ok is not None)
    assert result['native_abi'] == 1
    np.testing.assert_allclose([result['legacy_residual'], result['momentum']['maximum'],
        result['mass']['local_residual'], result['mass']['global_residual']],
        [expected.final_res, expected.final_res_mom, expected.final_res_mass_local, expected.final_res_mass_global],
        rtol=2e-10, atol=2e-11)
    for kind, name in enumerate(('residuals', 'mass_local_residuals', 'mass_global_residuals')):
        np.testing.assert_allclose(handle.history(kind), getattr(expected, name), rtol=2e-10, atol=2e-11)
    records = [[r['iter'], r['max'], *r['num'], *r['den'], r['u'], r['v']]
               for r in expected.mom_residuals]
    np.testing.assert_allclose(handle.history(3), records, rtol=2e-10, atol=2e-11)
    assert result['pressure']['success']
    assert result['pressure']['relative_residual'] <= 1e-10
    assert result['pressure']['pin_maximum'] <= 1e-10


@pytest.mark.parametrize('fluid', ['incompressible', 'ideal_gas'])
@pytest.mark.parametrize('variable', [False, True])
def test_public_prepared_fields_f2_and_progress(public_library, fluid, variable):
    expected = oracle.make_solver(fluid=fluid, partial=True, variable=variable, stretched=variable)
    actual = copy.deepcopy(expected)
    reference_progress, progress = [], []
    reference = expected.solve(max_iter=600, verbose=False,
                               progress_cb=lambda i, r: reference_progress.append((i, r)))
    with create(public_library, actual) as handle:
        result = handle.solve(**arguments(actual), progress_cb=lambda i, r: progress.append((i, r)))
        oracle.compare_fields(actual, expected)
        compare(result, handle, expected, reference)
        np.testing.assert_allclose(progress, reference_progress, rtol=2e-10, atol=2e-11)


def test_public_warm_reuse_target_history_and_grid_copy(public_library):
    expected = oracle.make_solver(fluid='ideal_gas', partial=True)
    actual = copy.deepcopy(expected)
    dx, dy, outlet = actual.dx_arr.copy(), actual.dy_arr.copy(), actual.outlet_geom_frac > 0
    with NativeSimple2D(public_library, dx=dx, dy=dy, outlet_open=outlet) as handle:
        dx[:] = 100.; dy[:] = 200.; outlet[:] = False
        for warm in range(2):
            if warm:
                for solver in (actual, expected):
                    solver.rho_field *= np.linspace(.97, 1.03, solver.Ny)[None, :]
                    solver.update_T_field(np.ascontiguousarray(solver.T_field+2.))
            reference = expected.solve(max_iter=600, verbose=False)
            result = handle.solve(**arguments(actual))
            oracle.compare_fields(actual, expected)
            compare(result, handle, expected, reference)
            assert result['massflux_target'] == expected._massflux_target
    handle.close()
    with pytest.raises(ValueError, match='closed'):
        handle.history(0)
    with pytest.raises(ValueError, match='closed'):
        handle.solve(**arguments(actual))


@pytest.mark.parametrize('after', [1, 4])
def test_public_cancellation_preserves_partial_state_and_recovers(public_library, after):
    actual = oracle.make_solver(partial=True)
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        return calls >= after

    with create(public_library, actual) as handle:
        with pytest.raises(CancelledError):
            handle.solve(**arguments(actual), cancel_check=cancel)
        assert handle.last_result['exit_reason'] == 'cancelled'
        assert handle.last_result['iterations'] == after-1
        assert not handle.last_result['converged']
        result = handle.solve(**arguments(actual))
        assert result['converged']


@pytest.mark.parametrize('callback', ['cancel', 'progress'])
def test_python_callback_exception_returns_through_c_boundary(public_library, callback):
    actual = oracle.make_solver(partial=True)

    def failed(*_):
        raise LookupError('callback sentinel')

    option = {'cancel_check' if callback == 'cancel' else 'progress_cb': failed}
    with create(public_library, actual) as handle:
        with pytest.raises(LookupError, match='callback sentinel'):
            handle.solve(**arguments(actual), **option)
        assert handle.last_result['exit_reason'] == 'cancelled'
        assert handle.solve(**arguments(actual))['converged']


@pytest.mark.parametrize('bad', ['dtype', 'layout', 'readonly', 'shape', 'alias'])
def test_invalid_mutable_buffers_fail_before_field_changes(public_library, bad):
    actual = oracle.make_solver(partial=True)
    request = arguments(actual)
    if bad == 'dtype':
        request['fields']['u'] = actual.u.astype(np.float32)
    elif bad == 'layout':
        request['fields']['u'] = np.asfortranarray(actual.u)
    elif bad == 'readonly':
        request['fields']['u'].flags.writeable = False
    elif bad == 'shape':
        request['fields']['pressure'] = np.empty((actual.Ny, actual.Nx))
    else:
        request['fields']['pressure_correction'] = actual.P
    before = actual.v.copy()
    with create(public_library, actual) as handle:
        with pytest.raises(ValueError):
            handle.solve(**request)
        np.testing.assert_array_equal(actual.v, before)
        assert handle.last_result is None


@pytest.mark.parametrize('name,value', [('ideal_gas', 2), ('max_iterations', -1),
    ('max_iterations', 0), ('inner_sweeps', 2.5), ('alpha_velocity', np.nan)])
def test_invalid_controls_are_not_silently_coerced(public_library, name, value):
    actual = oracle.make_solver()
    request = arguments(actual)
    request['settings'][name] = value
    with create(public_library, actual) as handle:
        with pytest.raises((ValueError, TypeError)):
            handle.solve(**request)
        assert handle.last_result is None


def test_nonfinite_evidence_is_returned_as_nonconverged(public_library):
    actual = oracle.make_solver()
    actual.P[1, 2] = np.nan
    with create(public_library, actual) as handle:
        result = handle.solve(**arguments(actual))
        assert result['exit_reason'] == 'nonfinite' and not result['converged']
        assert np.isnan(actual.P[1, 2]) and np.isnan(result['momentum']['maximum'])
        assert handle.history(0).size == 0


def test_rejected_call_does_not_retain_previous_convergence_certificate(public_library):
    actual = oracle.make_solver()
    with create(public_library, actual) as handle:
        assert handle.solve(**arguments(actual))['converged']
        request = arguments(actual)
        request['fields']['pressure_correction'] = actual.P
        with pytest.raises(ValueError, match='overlap'):
            handle.solve(**request)
        assert handle.last_result is None


def test_independent_public_handles_can_run_concurrently(public_library):
    def run():
        actual = oracle.make_solver(fluid='ideal_gas', partial=True)
        with create(public_library, actual) as handle:
            result = handle.solve(**arguments(actual))
            assert result['converged']
            return actual.P.copy(), actual.u.copy()
    serial = run()
    with ThreadPoolExecutor(max_workers=2) as pool:
        concurrent = list(pool.map(lambda _: run(), range(2)))
    for result in concurrent:
        for actual, expected in zip(result, serial):
            np.testing.assert_array_equal(actual, expected)


@pytest.mark.parametrize('kind', ['static', 'shared'])
def test_independent_pure_c_caller(public_library, kind):
    executable = public_library.parent / ('simple_2d_c_'+kind+('.exe' if sys.platform == 'win32' else ''))
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert 'analytic Darcy/wall solution, warm/history, errors and cancellation passed' in result.stdout

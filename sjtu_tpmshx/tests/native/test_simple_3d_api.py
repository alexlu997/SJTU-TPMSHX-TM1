"""Public C ABI and thin Python 3D SIMPLE adapter contracts."""
import copy
import ctypes as ct
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.solvers.backends.cpp.simple_3d import NativeSimple3D
from sjtu_tpmshx.tests.native.test_simple_3d import make_solver, compare_fields

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope='module')
def public_library():
    host = 'windows-x64' if sys.platform == 'win32' else 'macos-arm64'
    name = 'tpmshx_simple_3d_shared.dll' if sys.platform == 'win32' else 'libtpmshx_simple_3d_shared.dylib'
    path = Path(os.environ.get('TPMSHX_SIMPLE3D_LIBRARY', ROOT / '.cache/native-deps/build' / f'pilot-{host}' / name))
    if not path.is_file():
        if os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1':
            pytest.fail(f'explicit native dependency build is missing {path}')
        pytest.skip(f'explicit native dependency build is missing {path}')
    return path


def prepared(s):
    material = dict(epsilon=s.eps_field, viscosity=s.mu_field, effective_viscosity=s._mu_eff_field,
        permeability=s.K_arr, forchheimer=s.cF_arr, temperature=s.T_field)
    boundary = dict(outlet_u_fraction=s.outlet_u_frac, outlet_w_fraction=s.outlet_w_frac)
    state = dict(u=s.u, v=s.v, w=s.w, pressure=s.P, pressure_correction=s.Pp,
        d_u=s.d_u, d_v=s.d_v, d_w=s.d_w, density=s.rho_field, inlet_velocity=s.v_inlet_field)
    controls = dict(alpha_u=s.alpha_u, alpha_p=s.alpha_p, alpha_rho=s.alpha_rho,
        P_ref_abs=s.P_ref_abs, R_gas=s.R_gas, ideal_gas=s.fluid_type == 'ideal_gas',
        second_order_upwind=s.use_sou_momentum, track_momentum=s.track_momentum_residual)
    return material, boundary, state, controls


def driver(path, s):
    return NativeSimple3D(path, s.dx, s.dy, s.dz, s.outlet_mask_ij)


def raw_faces(s):
    re = s.rho_field*s.eps_field
    results = []
    for axis, velocity in enumerate((s.u, s.v, s.w)):
        lower, upper = [[(0, 0)]*3 for _ in range(2)]
        lower[axis], upper[axis] = (1, 0), (0, 1)
        rho_face = .5*(np.pad(re, lower, mode='edge') + np.pad(re, upper, mode='edge'))
        area = (s.dy[None, :, None]*s.dz[None, None, :] if axis == 0 else
                s.dx[:, None, None]*s.dz[None, None, :] if axis == 1 else
                s.dx[:, None, None]*s.dy[None, :, None])
        results.append(rho_face*velocity*area)
    return results


@pytest.mark.parametrize('fluid,sou,shape', [('ideal_gas', False, (5, 7, 4)),
    ('incompressible', True, (5, 7, 4)), ('ideal_gas', False, (13, 13, 13))])
def test_public_cold_warm_complete_state_and_raw_faces(public_library, fluid, sou, shape):
    expected = make_solver(shape, fluid=fluid, sou=sou, partial=True)
    actual = copy.deepcopy(expected)
    amg = actual.P.size > 2000
    with driver(public_library, actual) as native:
        target = None
        for warm in (False, True):
            if warm:
                actual.T_field *= 1.001
                expected.T_field *= 1.001
            material, boundary, state, controls = prepared(actual)
            result = native.solve(material, boundary, state, max_iter=600, **controls)
            python_result = expected.solve(max_iter=600)
            assert result['converged'] == python_result[0]
            assert result['exit_reason'] == expected.exit_reason
            assert result['post_closure_measured'] and result['post_closure_certified'] == expected.f2_cert_post_rescale_ok
            assert result['momentum']['maximum'] < 1e-4
            assert result['mass']['local_residual'] < 1e-6 and result['mass']['global_residual'] < 1e-6
            assert result['mass']['backflow_fraction'] <= .01
            assert result['pressure']['success'] and result['pressure']['pin_max_abs'] <= 1e-10
            assert result['pressure']['method'] == ('pyamg_classical_bicgstab' if amg else 'superlu_colamd')
            compare_fields(actual, expected, amg=amg)
            for a, b in zip(result['raw_mass_flux'], raw_faces(actual)):
                np.testing.assert_allclose(a, b, rtol=3e-13, atol=2e-18)
            if not amg:
                assert result['iterations'] == python_result[1]
                np.testing.assert_allclose(native.history(), expected.residuals, rtol=1e-8, atol=1e-8)
            assert native.history('momentum').shape[1] == 11
            if target is None:
                target = native.history('massflux_target').copy()
            else:
                np.testing.assert_array_equal(native.history('massflux_target'), target)


def test_explicit_seed_max_budget_and_no_python_numerics(public_library):
    s = make_solver(fluid='ideal_gas', partial=True)
    s.P[:] = np.linspace(50., 0., s.Ny)[None, :, None]
    with driver(public_library, s) as native:
        material, boundary, state, controls = prepared(s)
        # These owners must remain unreachable from the explicit native call.
        with patch('sjtu_tpmshx.solvers.simple_solver_3d._solve_pp_amg', side_effect=AssertionError('Python pressure used')), \
             patch('sjtu_tpmshx.solvers.simple_solver_3d._sweep_u_jit_df_3d', side_effect=AssertionError('Python momentum used')), \
             patch('sjtu_tpmshx.solvers._solve_common.F2Monitor', side_effect=AssertionError('Python F2 used')):
            result = native.solve(material, boundary, state, max_iter=1, **controls)
        assert not result['converged'] and result['exit_reason'] == 'max_iter'
        assert result['post_closure_measured'] and result['raw_mass_flux'] is not None
        assert result['iterations'] == 1
        for a, b in zip(result['raw_mass_flux'], raw_faces(s)):
            np.testing.assert_allclose(a, b, rtol=3e-13, atol=2e-18)


@pytest.mark.parametrize('after', [1, 3])
def test_cancellation_never_publishes_mass_faces(public_library, after):
    s = make_solver(fluid='ideal_gas')
    calls = 0
    def cancel():
        nonlocal calls
        calls += 1
        return calls >= after
    with driver(public_library, s) as native:
        material, boundary, state, controls = prepared(s)
        with pytest.raises(CancelledError):
            native.solve(material, boundary, state, cancel_check=cancel, **controls)
        assert calls == after
        assert native.last_result['exit_reason'] == 'cancelled'
        assert native.last_result['iterations'] == max(0, after-2)
        assert not native.last_result['converged'] and native.last_result['raw_mass_flux'] is None


@pytest.mark.parametrize('callback', ['cancel_check', 'progress'])
def test_callback_exception_returns_to_python(public_library, callback):
    s = make_solver()
    def fail(*args):
        raise LookupError('callback sentinel')
    with driver(public_library, s) as native:
        material, boundary, state, controls = prepared(s)
        with pytest.raises(LookupError, match='callback sentinel'):
            native.solve(material, boundary, state, **controls, **{callback: fail})
        assert native.last_result is None


@pytest.mark.parametrize('invalid', ['dtype', 'readonly', 'noncontiguous', 'alias', 'short', 'flags', 'SOU_order'])
def test_array_and_control_contract_rejection(public_library, invalid):
    s = make_solver()
    with driver(public_library, s) as native:
        material, boundary, state, controls = prepared(s)
        if invalid == 'dtype': state['u'] = state['u'].astype(np.float32)
        if invalid == 'readonly': state['u'].flags.writeable = False
        if invalid == 'noncontiguous': state['u'] = state['u'][::-1]
        if invalid == 'alias': state['pressure_correction'] = state['pressure']
        if invalid == 'short': state['u'] = state['u'][:-1]
        if invalid == 'flags': controls['ideal_gas'] = 2
        if invalid == 'SOU_order': controls.update(second_order_upwind=True, ordering='red_black')
        before = {key: value.copy() for key, value in state.items()}
        with pytest.raises(ValueError): native.solve(material, boundary, state, **controls)
        for key, value in state.items(): np.testing.assert_array_equal(value, before[key])


def test_nonfinite_and_closed_handle(public_library):
    s = make_solver()
    s.w.flat[0] = np.nan
    native = driver(public_library, s)
    material, boundary, state, controls = prepared(s)
    result = native.solve(material, boundary, state, **controls)
    assert result['exit_reason'] == 'nonfinite' and not result['converged'] and result['raw_mass_flux'] is None
    assert not native.history().size
    native.close()
    native.close()
    with pytest.raises(ValueError, match='closed'):
        native.solve(material, boundary, state, **controls)


def test_history_short_buffer_and_bounded_error(public_library):
    s = make_solver()
    with driver(public_library, s) as native:
        material, boundary, state, controls = prepared(s)
        native.solve(material, boundary, state, max_iter=3, **controls)
        output = np.full(2, -999.)
        size = ct.c_size_t(888)
        error = ct.create_string_buffer(5)
        code = native._history(native._handle, 0, output.ctypes.data_as(ct.POINTER(ct.c_double)), 2,
            ct.byref(size), error, len(error))
        assert code == 1 and size.value == 888 and error.raw[-1] == 0
        np.testing.assert_array_equal(output, [-999., -999.])


@pytest.mark.parametrize('suffix', ['static', 'shared'])
def test_independent_c_callers(public_library, suffix):
    executable = public_library.parent / (f'simple_3d_c_{suffix}' + ('.exe' if sys.platform == 'win32' else ''))
    assert executable.is_file(), f'missing independent C caller {executable}'
    result = subprocess.run([str(executable)], text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout+result.stderr
    assert 'cold/warm/raw-mass/error/cancel passed' in result.stdout


def test_failed_attempt_clears_previous_certificate(public_library):
    s = make_solver()
    with driver(public_library, s) as native:
        material, boundary, state, controls = prepared(s)
        assert native.solve(material, boundary, state, **controls)['converged']
        controls['ideal_gas'] = 2
        with pytest.raises(ValueError):
            native.solve(material, boundary, state, **controls)
        assert native.last_result is None

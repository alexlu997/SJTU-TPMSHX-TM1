"""Native 2D SIMPLE fields, independent equations, and F2 acceptance checks."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import ctypes as ct
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.tests.native.momentum_audit_2d import _mom_res_jit_2d
from sjtu_tpmshx.tests.native.simple_inputs import make_2d as make_solver
from sjtu_tpmshx.tests.native.simple_audit import momentum_component_residuals, mass_balance
from sjtu_tpmshx.tests.native.simple_inputs import f2_settings


ROOT = Path(__file__).resolve().parents[3]
DOUBLE = ct.POINTER(ct.c_double)
SIZE = ct.POINTER(ct.c_size_t)
STOP = {1: "tol", 2: "stall", 3: "max_iter", 4: "nonfinite", 5: "cancelled", 6: "pressure_failure"}


@pytest.fixture(scope="module")
def library():
    host = "windows-x64" if sys.platform == "win32" else "macos-arm64"
    name = "simple_2d_test.dll" if sys.platform == "win32" else "libsimple_2d_test.dylib"
    path = Path(os.environ.get("TPMSHX_SIMPLE2D_TEST_LIBRARY", ROOT / ".cache/native-deps/build" / f"pilot-{host}" / name))
    if not path.is_file():
        message = f"explicit native dependency build is missing {path}"
        if os.environ.get("TPMSHX_REQUIRE_NATIVE_DEPS_TESTS") == "1":
            pytest.fail(message)
        pytest.skip(message)
    lib = ct.CDLL(str(path))
    lib.tpmshx_simple2d_create.argtypes = [ct.c_size_t, ct.c_size_t, DOUBLE, DOUBLE,
                                         ct.POINTER(ct.c_ubyte), ct.c_char_p, ct.c_size_t]
    lib.tpmshx_simple2d_create.restype = ct.c_void_p
    lib.tpmshx_simple2d_destroy.argtypes = [ct.c_void_p]
    lib.tpmshx_simple2d_call.argtypes = [ct.c_void_p, ct.c_int, ct.POINTER(DOUBLE), SIZE,
                                       DOUBLE, SIZE, DOUBLE, ct.c_char_p, ct.c_size_t]
    lib.tpmshx_simple2d_call.restype = ct.c_int
    lib.tpmshx_simple2d_history.argtypes = [ct.c_void_p, ct.c_int, DOUBLE, ct.c_size_t]
    lib.tpmshx_simple2d_history.restype = ct.c_size_t
    return lib, path





def drag_fields(solver):
    if solver._K_field2d is not None:
        return solver._K_field2d, solver._cF_field2d
    return (np.ascontiguousarray(np.repeat(solver._K_arr[None, :], solver.Nx, axis=0)),
            np.ascontiguousarray(np.repeat(solver._cF_arr[None, :], solver.Nx, axis=0)))


def packed(solver):
    k, cf = drag_fields(solver)
    return [solver.eps_field, solver.mu_field, solver._mu_eff_field, k, cf, solver.T_field,
            solver.u, solver.v, solver.P, solver.Pp, solver.d_u, solver.d_v, solver.rho_field,
            solver.v_inlet_field, solver.inlet_frac, solver.outlet_u_frac]


class Native:
    def __init__(self, library, solver):
        self.lib = library[0]
        error = ct.create_string_buffer(512)
        opening = np.ascontiguousarray(solver.outlet_geom_frac > 0., dtype=np.uint8)
        self.pointer = self.lib.tpmshx_simple2d_create(solver.Nx, solver.Ny,
            solver.dx_arr.ctypes.data_as(DOUBLE), solver.dy_arr.ctypes.data_as(DOUBLE),
            opening.ctypes.data_as(ct.POINTER(ct.c_ubyte)), error, len(error))
        assert self.pointer, error.value.decode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.lib.tpmshx_simple2d_destroy(self.pointer)

    def call(self, solver, *, operation=2, iterations=600, sweeps=2, alpha_u=.7,
             alpha_p=.3, cancel_after=0, arrays=None, accelerate=False):
        self.history_offset = len(self.history(0))
        arrays = packed(solver) if arrays is None else arrays
        assert all(a.dtype == np.float64 and a.flags.c_contiguous for a in arrays)
        pointers = (DOUBLE * len(arrays))(*(a.ctypes.data_as(DOUBLE) for a in arrays))
        sizes = np.array([a.size for a in arrays], dtype=np.uintp)
        monitor = f2_settings(solver)
        values = np.array([solver.v_inlet, solver._inlet_taper_flux_scale,
            np.nan if solver._rho_inlet_ref is None else solver._rho_inlet_ref,
            alpha_u, alpha_p, solver.alpha_rho, solver.P_ref_abs, solver.R_gas, solver.cf_aniso,
            monitor.mom_tol, monitor.mass_local_tol, monitor.mass_global_tol, monitor.backflow_max,
            monitor.vtol, monitor.stall_ratio], dtype=np.float64)
        flags = (int(solver.fluid_type == "ideal_gas")
                 + 2*int(getattr(solver, "massflux_inlet", True))
                 + 4*int(getattr(solver, "enforce_outlet_mass_balance", True)) + 8*int(accelerate))
        counts = np.array([iterations, sweeps, monitor.n_confirm, monitor.mom_every,
                           monitor.stall_window, flags, cancel_after], dtype=np.uintp)
        out = np.empty(25, dtype=np.float64)
        error = ct.create_string_buffer(512)
        status = self.lib.tpmshx_simple2d_call(self.pointer, operation, pointers,
            sizes.ctypes.data_as(SIZE), values.ctypes.data_as(DOUBLE), counts.ctypes.data_as(SIZE),
            out.ctypes.data_as(DOUBLE), error, len(error))
        if status:
            raise ValueError(error.value.decode())
        return out

    def history(self, kind):
        size = self.lib.tpmshx_simple2d_history(self.pointer, kind, None, 0)
        values = np.empty(size, dtype=np.float64)
        assert self.lib.tpmshx_simple2d_history(self.pointer, kind, values.ctypes.data_as(DOUBLE), size) == size
        return values


def audit_momentum(solver):
    k, cf = drag_fields(solver)
    nu, du, nv, dv = _mom_res_jit_2d(solver.u, solver.v, solver.P, solver.Nx, solver.Ny,
        solver.dx_arr, solver.dy_arr, solver.rho_field, solver._mu_eff_field, k, cf,
        solver.mu_field, solver.eps_field, solver.outlet_u_frac, solver.cf_aniso)
    ru, rv = momentum_component_residuals((nu, nv), (du, dv))
    return np.array([nu, nv, du, dv, ru, rv]), max(ru, rv)


def assert_momentum(actual, value, history, *, measured, converged):
    for row in history:
        ru, rv = momentum_component_residuals(row[2:4], row[4:6])
        np.testing.assert_allclose(row[[1, 6, 7]], [max(ru, rv), ru, rv], rtol=2e-12, atol=2e-12)
    if measured:
        _, maximum = audit_momentum(actual)
        np.testing.assert_allclose(value, maximum, rtol=2e-12, atol=2e-12)
        if converged:
            assert maximum < getattr(actual, 'mom_tol', 1e-4)
    else:
        np.testing.assert_allclose(value, history[-1, 1] if len(history) else np.nan,
                                   rtol=2e-12, atol=2e-12, equal_nan=True)


def assert_result(out, actual, native):
    assert int(out[0]) in STOP
    assert bool(out[1]) == (out[0] == 1 and bool(out[4]))
    assert_momentum(actual, out[6], native.history(3).reshape(-1, 8),
                    measured=bool(out[3]), converged=bool(out[1]))
    assert len(native.history(0)) == native.history_offset + out[2]
    for kind in (0, 1, 2):
        assert np.isfinite(native.history(kind)).all()
        assert (native.history(kind) >= 0.).all()
    if out[3]:
        mass, counted, _ = mass_balance(actual, exclude_outlet=True)
        np.testing.assert_allclose(out[7:12], mass, rtol=2e-12, atol=2e-12)
        assert out[22] == counted
    if out[1]:
        assert out[6] < 1e-4 and out[7] < 1e-6 and out[8] < 1e-6 and out[9] <= .01
        assert out[3] and out[4]
        assert np.isfinite(out[20]) and out[21] <= 1e-10














@pytest.mark.parametrize("sweeps", [1, 3])
@pytest.mark.parametrize("shape", [(1, 7), (7, 1), (7, 9)])
@pytest.mark.parametrize("anisotropy", [0., .4])
def test_predictor_and_unrelaxed_equations(library, shape, sweeps, anisotropy):
    actual = make_solver(shape=shape, partial=shape[0] > 1)
    rng = np.random.default_rng(4291)
    actual.u[:] = rng.normal(0., .002, actual.u.shape)
    actual.u[[0, -1], :] = 0.
    actual.v[:] = rng.normal(.003, .007, actual.v.shape)
    actual.P[:] = rng.normal(0., 1., actual.P.shape)
    actual.cf_aniso = anisotropy
    with Native(library, actual) as native:
        for operation in (1, 0):
            out = native.call(actual, operation=operation, sweeps=sweeps)
            raw, maximum = audit_momentum(actual)
            np.testing.assert_allclose(out[14:20], raw, rtol=2e-12, atol=2e-12)
            np.testing.assert_allclose(out[6], maximum, rtol=2e-12, atol=2e-12)
        assert np.isfinite(actual.u).all() and np.isfinite(actual.v).all()
        np.testing.assert_array_equal(actual.u[[0, -1]], 0.)


@pytest.mark.parametrize("fluid", ["incompressible", "ideal_gas"])
@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("variable", [False, True])
def test_complete_cold_solver_fields_and_f2(library, fluid, partial, variable):
    actual = make_solver(fluid=fluid, partial=partial, variable=variable, stretched=variable)
    with Native(library, actual) as native:
        out = native.call(actual)
        assert out[1]
        assert_result(out, actual, native)
        history = native.history(4).reshape(-1, 2)
        expected_iterations = [1, *range(20, int(out[2])+1, 20)]
        np.testing.assert_array_equal(history[:, 0], expected_iterations)
        np.testing.assert_array_equal(history[:, 1], native.history(0)[history[:, 0].astype(int)-1])
        assert out[24] == out[2]


def test_momentum_audit_rejects_changed_returned_pressure(library):
    actual = make_solver()
    with Native(library, actual) as native:
        out = native.call(actual)
        history = native.history(3).reshape(-1, 8)
        assert_momentum(actual, out[6], history, measured=True, converged=True)
        actual.P[2, 3] += .1
        with pytest.raises(AssertionError):
            assert_momentum(actual, out[6], history, measured=True, converged=True)


@pytest.mark.parametrize("fluid", ["incompressible", "ideal_gas"])
def test_warm_restart_retains_target_and_histories(library, fluid):
    actual = make_solver(fluid=fluid, partial=True)
    with Native(library, actual) as native:
        out = native.call(actual)
        assert out[1]
        assert_result(out, actual, native)
        fixed_target = out[13]
        actual.rho_field *= np.linspace(.97, 1.03, actual.Ny)[None, :]
        if fluid == 'ideal_gas':
            actual.T_field += np.linspace(0., 3., actual.Ny)[None, :]
        out = native.call(actual)
        assert out[1]
        assert_result(out, actual, native)
        assert out[13] == fixed_target


@pytest.mark.parametrize("iterations", [1, 2, 19])
def test_budget_exit_keeps_existing_2d_certificate_contract(library, iterations):
    actual = make_solver(fluid='ideal_gas', partial=True)
    with Native(library, actual) as native:
        out = native.call(actual, iterations=iterations)
        assert_result(out, actual, native)
        assert out[2] == iterations and out[0] == 3 and not out[1] and not out[3]


def test_stall_is_failure(library):
    actual = make_solver()
    actual.mom_tol = 0.
    actual.f2_velocity_check_tol = 1e3
    actual.f2_stall_window = 1
    actual.f2_stall_ratio = 1.
    with Native(library, actual) as native:
        out = native.call(actual, iterations=80)
        assert_result(out, actual, native)
        assert out[0] == 2 and not out[1]


def test_pressure_clip_keeps_gauge_density_and_counter(library):
    actual = make_solver(fluid='ideal_gas', variable=False)
    actual.P.fill(20e6)
    with Native(library, actual) as native:
        out = native.call(actual, iterations=1)
        assert_result(out, actual, native)
        assert out[12] == actual.P.size
        assert np.max(actual.P + actual.P_ref_abs) == 1e7
        assert np.isfinite(actual.rho_field).all() and np.all(actual.rho_field > 0.)


@pytest.mark.parametrize("mode", ["velocity_inlet", "captured_density", "uniform_partial", "no_exit_closure"])
def test_existing_inlet_and_closeout_controls(library, mode):
    actual = make_solver(fluid='ideal_gas', partial=True, uniform_inlet=mode == 'uniform_partial')
    if mode == 'velocity_inlet':
        actual.massflux_inlet = False
    elif mode == 'captured_density':
        actual._rho_inlet_ref = None
    elif mode == 'no_exit_closure':
        actual.enforce_outlet_mass_balance = False
    with Native(library, actual) as native:
        out = native.call(actual, iterations=60)
        assert_result(out, actual, native)
        if mode == 'velocity_inlet':
            np.testing.assert_allclose(actual.v[:, 0], actual.v_inlet_field * actual.inlet_frac,
                                       rtol=2e-12, atol=2e-12)
        else:
            np.testing.assert_allclose(actual.v_inlet_field * actual.rho_field[:, 0],
                                       out[13], rtol=2e-12, atol=2e-12)
        assert np.isfinite(actual.P).all() and out[1]


def test_finite_input_overflow_retains_failed_field_evidence(library):
    solver = make_solver()
    solver.mu_field.fill(1e308)
    with Native(library, solver) as native:
        out = native.call(solver, iterations=1)
        assert out[0] == 4 and not out[1] and not out[4]
        assert not np.isfinite(solver.u).all() or not np.isfinite(solver.v).all()


@pytest.mark.parametrize("field", ["u", "v", "P", "rho_field", "T_field"])
def test_initial_nonfinite_is_not_convergence(library, field):
    actual = make_solver()
    getattr(actual, field).flat[0] = np.nan
    with Native(library, actual) as native:
        out = native.call(actual, iterations=5)
        assert out[0] == 4 and out[2] == 0 and not out[1] and not out[4]
        assert not native.history(0).size
        assert not np.isfinite(out[[5, 6, 7, 8, 9]]).any()


@pytest.mark.parametrize("cancel_after", [1, 3])
def test_cancellation_preserves_actual_partial_state_and_recovers(library, cancel_after):
    actual = make_solver(fluid='ideal_gas', partial=True)
    initial = copy.deepcopy(actual)
    with Native(library, actual) as native:
        out = native.call(actual, cancel_after=cancel_after)
        assert out[0] == 5 and out[2] == cancel_after - 1 and out[24] == cancel_after
        assert len(native.history(0)) == cancel_after - 1 and not out[1]
        if cancel_after == 1:
            for name in ('u', 'v', 'P', 'Pp'):
                np.testing.assert_array_equal(getattr(actual, name), getattr(initial, name))
        out = native.call(actual)
        assert out[1]
        assert_result(out, actual, native)


def test_alias_rejected_before_mutation_then_recovery(library):
    solver = make_solver()
    before = packed(solver)
    values = [a.copy() for a in before]
    with Native(library, solver) as native:
        aliased = list(before)
        aliased[12] = aliased[0]
        with pytest.raises(ValueError, match="overlap"):
            native.call(solver, arrays=aliased)
        for current, old in zip(before, values):
            np.testing.assert_array_equal(current, old)
        out = native.call(solver)
        assert out[1]


def test_two_independent_native_solver_states(library):
    def run(fluid):
        solver = make_solver(fluid=fluid, partial=True)
        with Native(library, solver) as native:
            out = native.call(solver)
            return out, [a.copy() for a in packed(solver)[6:14]]

    serial = [run(fluid) for fluid in ("ideal_gas", "incompressible")]
    with ThreadPoolExecutor(max_workers=2) as workers:
        concurrent = list(workers.map(run, ("ideal_gas", "incompressible")))
    for (expected, expected_fields), (actual, actual_fields) in zip(serial, concurrent):
        np.testing.assert_allclose(actual, expected, rtol=0., atol=0., equal_nan=True)
        for a, b in zip(actual_fields, expected_fields):
            np.testing.assert_array_equal(a, b)


def test_independent_analytic_native_caller(library):
    suffix = ".exe" if sys.platform == "win32" else ""
    result = subprocess.run([str(library[1].parent / f"simple_2d_smoke{suffix}")],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Darcy/Brinkman" in result.stdout

"""2D SIMPLE equation and full-state qualification against the current Python owner.

Frozen before first comparison: operator rtol=2e-12, atol=2e-12;
full state rtol=2e-10, pressure atol=2e-8 Pa, velocity atol=2e-11 m/s.
These arithmetic tolerances do not alter any SIMPLE/F2 acceptance gate.
"""
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

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.solvers import _kernels_simple_2d as kernels
from sjtu_tpmshx.solvers._solve_common import F2Monitor, momentum_component_residuals
from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver


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


def make_solver(*, shape=(6, 10), fluid="incompressible", partial=False,
                variable=True, stretched=True, uniform_inlet=False):
    nx, ny = shape
    dx = np.linspace(.8, 1.2, nx) if stretched else np.ones(nx)
    dy = np.linspace(1.2, .8, ny) if stretched else np.ones(ny)
    dx *= .036 / dx.sum()
    dy *= .080 / dy.sum()
    rho, mu, velocity = (1.2, 1.8e-5, .7) if fluid == "ideal_gas" else (997., .0009, .004)
    solver = SIMPLESolver(.036, .080, nx, ny, "Diamond", 7., .5, .6, .001,
        rho, mu, 300., .004 if partial else 0., .025 if partial else .036, velocity,
        outlet_lo=.009 if partial else 0., outlet_hi=.031 if partial else .036,
        fluid_type=fluid, P_ref_abs=101325., rho_inlet_ref=rho,
        wall_refine=False, dx_arr=dx, dy_arr=dy,
        K_arr=np.full(ny, 1e-7), cF_arr=np.full(ny, 35.), uniform_inlet=uniform_inlet)
    if variable:
        x, y = np.meshgrid(np.linspace(0., 1., nx), np.linspace(0., 1., ny), indexing="ij")
        solver.eps_field = np.ascontiguousarray(.52 + .08*x + .025*y)
        solver.rho_field *= 1. + .04*x - .02*y
        solver.mu_field *= 1. + .05*x + .03*y
        solver._mu_eff_field = np.ascontiguousarray(solver.mu_field / solver.eps_field)
        solver.set_K_cF_field(np.ascontiguousarray(1e-7*(.9+.2*x+.1*y)),
                             np.ascontiguousarray(35.*(.9+.1*x+.2*y)))
    return solver


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
             alpha_p=.3, cancel_after=0, arrays=None):
        arrays = packed(solver) if arrays is None else arrays
        assert all(a.dtype == np.float64 and a.flags.c_contiguous for a in arrays)
        pointers = (DOUBLE * len(arrays))(*(a.ctypes.data_as(DOUBLE) for a in arrays))
        sizes = np.array([a.size for a in arrays], dtype=np.uintp)
        monitor = F2Monitor(solver, (solver.u, solver.v), 20)
        values = np.array([solver.v_inlet, solver._inlet_taper_flux_scale,
            np.nan if solver._rho_inlet_ref is None else solver._rho_inlet_ref,
            alpha_u, alpha_p, solver.alpha_rho, solver.P_ref_abs, solver.R_gas, solver.cf_aniso,
            monitor.mom_tol, monitor.mass_local_tol, monitor.mass_global_tol, monitor.backflow_max,
            monitor.vtol, monitor.stall_ratio], dtype=np.float64)
        flags = (int(solver.fluid_type == "ideal_gas")
                 + 2*int(getattr(solver, "massflux_inlet", True))
                 + 4*int(getattr(solver, "enforce_outlet_mass_balance", True)))
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


def python_momentum(solver):
    k, cf = drag_fields(solver)
    raw = kernels._mom_res_jit_2d(solver.u, solver.v, solver.P, solver.Nx, solver.Ny,
        solver.dx_arr, solver.dy_arr, solver.rho_field, solver._mu_eff_field, k, cf,
        solver.mu_field, solver.eps_field, solver.outlet_u_frac, solver.cf_aniso)
    nu, du, nv, dv = raw
    ru, rv = momentum_component_residuals((nu, nv), (du, dv), 1e-3)
    return np.array([nu, nv, du, dv, ru, rv]), max(ru, rv)


def python_predictor(solver, sweeps):
    k, cf = drag_fields(solver)
    common = (solver.Nx, solver.Ny, solver.dx_arr, solver.dy_arr, solver.rho_field,
              solver._mu_eff_field, k, cf, solver.mu_field, solver.eps_field, .7, sweeps, solver.cf_aniso)
    kernels._sweep_u_jit_df(solver.u, solver.v, solver.P, solver.d_u, solver.outlet_u_frac, *common)
    kernels._sweep_v_jit_df(solver.u, solver.v, solver.P, solver.d_v, solver.inlet_frac,
                          solver.v_inlet_field, solver.outlet_geom_frac, *common)


def compare_fields(actual, expected, *, operator=False):
    for field in ("u", "v", "P", "Pp", "d_u", "d_v", "rho_field", "v_inlet_field"):
        atol = 2e-12 if operator else (2e-8 if field in {"P", "Pp"} else 2e-11)
        np.testing.assert_allclose(getattr(actual, field), getattr(expected, field),
            rtol=2e-12 if operator else 2e-10, atol=atol, err_msg=field)
    # Raw solver-axis mass flows, without an outlet/global repair or projection.
    for s in (actual, expected):
        re = s.rho_field*s.eps_field
        s.raw_x = .5*(np.pad(re, ((1, 0), (0, 0)), mode="edge")
                     + np.pad(re, ((0, 1), (0, 0)), mode="edge"))*s.u*s.dy_arr[None, :]
        s.raw_y = .5*(np.pad(re, ((0, 0), (1, 0)), mode="edge")
                     + np.pad(re, ((0, 0), (0, 1)), mode="edge"))*s.v*s.dx_arr[:, None]
    np.testing.assert_allclose(actual.raw_x, expected.raw_x, rtol=2e-10, atol=2e-12)
    np.testing.assert_allclose(actual.raw_y, expected.raw_y, rtol=2e-10, atol=2e-12)


def compare_result(out, expected, native, reference_result):
    assert bool(out[1]) == reference_result[0]
    assert int(out[2]) == reference_result[1]
    assert STOP[int(out[0])] == expected.exit_reason
    if expected.exit_reason != "nonfinite":
        assert bool(out[3]) == (expected.f2_cert_post_rescale_ok is not None)
    assert bool(out[4]) == bool(expected.f2_cert_post_rescale_ok)
    for index, name in ((5, "final_res"), (6, "final_res_mom"), (7, "final_res_mass_local"),
                        (8, "final_res_mass_global"), (9, "outlet_backflow_frac")):
        value = getattr(expected, name)
        np.testing.assert_allclose(out[index], np.nan if value is None else value,
                                   rtol=2e-10, atol=2e-11, equal_nan=True, err_msg=name)
    assert out[12] == getattr(expected, "_p_clip_hits", 0)
    np.testing.assert_allclose(out[13], getattr(expected, "_massflux_target", np.nan), equal_nan=True)
    for kind, name in enumerate(("residuals", "mass_local_residuals", "mass_global_residuals")):
        np.testing.assert_allclose(native.history(kind), getattr(expected, name), rtol=2e-10, atol=2e-11)
    records = np.array([[r["iter"], r["max"], *r["num"], *r["den"], r["u"], r["v"]]
                        for r in expected.mom_residuals]).reshape(-1, 8)
    np.testing.assert_allclose(native.history(3).reshape(-1, 8), records, rtol=2e-10, atol=2e-11)


@pytest.mark.parametrize("sweeps", [1, 3])
@pytest.mark.parametrize("shape", [(1, 7), (7, 1), (7, 9)])
@pytest.mark.parametrize("anisotropy", [0., .4])
def test_predictor_and_unrelaxed_equations(library, shape, sweeps, anisotropy):
    expected = make_solver(shape=shape, partial=shape[0] > 1)
    rng = np.random.default_rng(4291)
    expected.u[:] = rng.normal(0., .002, expected.u.shape)
    expected.u[[0, -1], :] = 0.
    expected.v[:] = rng.normal(.003, .007, expected.v.shape)
    expected.P[:] = rng.normal(0., 1., expected.P.shape)
    expected.cf_aniso = anisotropy
    actual = copy.deepcopy(expected)
    with Native(library, actual) as native:
        before = native.call(actual, operation=1)
        raw, maximum = python_momentum(expected)
        np.testing.assert_allclose(before[14:20], raw, rtol=2e-12, atol=2e-12)
        np.testing.assert_allclose(before[6], maximum, rtol=2e-12, atol=2e-12)
        out = native.call(actual, operation=0, sweeps=sweeps)
        python_predictor(expected, sweeps)
        compare_fields(actual, expected, operator=True)
        raw, maximum = python_momentum(expected)
        np.testing.assert_allclose(out[14:20], raw, rtol=2e-12, atol=2e-12)
        np.testing.assert_allclose(out[6], maximum, rtol=2e-12, atol=2e-12)


@pytest.mark.parametrize("fluid", ["incompressible", "ideal_gas"])
@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("variable", [False, True])
def test_complete_cold_solver_fields_and_f2(library, fluid, partial, variable):
    expected = make_solver(fluid=fluid, partial=partial, variable=variable, stretched=variable)
    actual = copy.deepcopy(expected)
    progress = []
    reference = expected.solve(max_iter=600, verbose=False, progress_cb=lambda i, r: progress.append((i, r)))
    with Native(library, actual) as native:
        out = native.call(actual)
        compare_fields(actual, expected)
        compare_result(out, expected, native, reference)
        np.testing.assert_allclose(native.history(4).reshape(-1, 2), progress, rtol=2e-10, atol=2e-11)
        assert out[24] == out[2]


@pytest.mark.parametrize("fluid", ["incompressible", "ideal_gas"])
def test_warm_restart_retains_target_and_histories(library, fluid):
    expected = make_solver(fluid=fluid, partial=True)
    actual = copy.deepcopy(expected)
    with Native(library, actual) as native:
        reference = expected.solve(max_iter=600, verbose=False)
        out = native.call(actual)
        compare_result(out, expected, native, reference)
        fixed_target = out[13]
        for solver in (expected, actual):
            solver.rho_field *= np.linspace(.97, 1.03, solver.Ny)[None, :]
            if fluid == "ideal_gas":
                solver.update_T_field(np.ascontiguousarray(solver.T_field + np.linspace(0., 3., solver.Ny)[None, :]))
        reference = expected.solve(max_iter=600, verbose=False)
        out = native.call(actual)
        compare_fields(actual, expected)
        compare_result(out, expected, native, reference)
        assert out[13] == fixed_target


@pytest.mark.parametrize("iterations", [1, 2, 19])
def test_budget_exit_keeps_existing_2d_certificate_contract(library, iterations):
    expected = make_solver(fluid="ideal_gas", partial=True)
    actual = copy.deepcopy(expected)
    reference = expected.solve(max_iter=iterations, verbose=False)
    with Native(library, actual) as native:
        out = native.call(actual, iterations=iterations)
        compare_fields(actual, expected)
        compare_result(out, expected, native, reference)
        assert STOP[int(out[0])] == "max_iter" and not out[3]


def test_stall_is_failure(library):
    expected = make_solver()
    expected.mom_tol = 0.
    expected.f2_velocity_check_tol = 1e3
    expected.f2_stall_window = 1
    expected.f2_stall_ratio = 1.
    actual = copy.deepcopy(expected)
    reference = expected.solve(max_iter=80, verbose=False)
    with Native(library, actual) as native:
        out = native.call(actual, iterations=80)
        compare_fields(actual, expected)
        compare_result(out, expected, native, reference)
        assert STOP[int(out[0])] == "stall" and not out[1]


def test_pressure_clip_keeps_gauge_density_and_counter(library):
    expected = make_solver(fluid="ideal_gas", variable=False)
    expected.P.fill(20e6)
    actual = copy.deepcopy(expected)
    reference = expected.solve(max_iter=1, verbose=False)
    with Native(library, actual) as native:
        out = native.call(actual, iterations=1)
        compare_fields(actual, expected)
        compare_result(out, expected, native, reference)
        assert out[12] == expected.P.size


@pytest.mark.parametrize("mode", ["velocity_inlet", "captured_density", "uniform_partial", "no_exit_closure"])
def test_existing_inlet_and_closeout_controls(library, mode):
    expected = make_solver(fluid="ideal_gas", partial=True, uniform_inlet=mode == "uniform_partial")
    if mode == "velocity_inlet":
        expected.massflux_inlet = False
    elif mode == "captured_density":
        expected._rho_inlet_ref = None
    elif mode == "no_exit_closure":
        expected.enforce_outlet_mass_balance = False
    actual = copy.deepcopy(expected)
    reference = expected.solve(max_iter=60, verbose=False)
    with Native(library, actual) as native:
        out = native.call(actual, iterations=60)
        compare_fields(actual, expected)
        compare_result(out, expected, native, reference)


def test_finite_input_overflow_retains_failed_field_evidence(library):
    solver = make_solver()
    solver.mu_field.fill(1e308)
    with Native(library, solver) as native:
        out = native.call(solver, iterations=1)
        assert out[0] == 4 and not out[1] and not out[4]
        assert not np.isfinite(solver.u).all() or not np.isfinite(solver.v).all()


@pytest.mark.parametrize("field", ["u", "v", "P", "rho_field", "T_field"])
def test_initial_nonfinite_is_not_convergence(library, field):
    expected = make_solver()
    getattr(expected, field).flat[0] = np.nan
    actual = copy.deepcopy(expected)
    reference = expected.solve(max_iter=5, verbose=False)
    with Native(library, actual) as native:
        out = native.call(actual, iterations=5)
        compare_result(out, expected, native, reference)
        assert out[0] == 4 and out[2] == 0 and not out[1]


@pytest.mark.parametrize("cancel_after", [1, 3])
def test_cancellation_preserves_actual_partial_state_and_recovers(library, cancel_after):
    expected = make_solver(fluid="ideal_gas", partial=True)
    actual = copy.deepcopy(expected)
    checks = 0

    def cancel():
        nonlocal checks
        checks += 1
        return checks >= cancel_after

    with pytest.raises(CancelledError):
        expected.solve(max_iter=600, verbose=False, cancel_check=cancel)
    with Native(library, actual) as native:
        out = native.call(actual, cancel_after=cancel_after)
        assert out[0] == 5 and out[2] == cancel_after - 1 and out[24] == cancel_after
        compare_fields(actual, expected)
        reference = expected.solve(max_iter=600, verbose=False)
        out = native.call(actual)
        compare_fields(actual, expected)
        compare_result(out, expected, native, reference)


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

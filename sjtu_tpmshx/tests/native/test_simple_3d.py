"""Prepared-field native 3D SIMPLE qualification against the current Python owner.

Frozen gates: predictor/raw momentum rtol=3e-12; velocity atol=2e-12 m/s,
d atol=2e-14, raw momentum atol=2e-13. Direct solve rtol=1e-8,
P/dP atol=1e-7 Pa, velocity/rho atol=1e-8. AMG rtol=2e-7,
P/dP atol=1e-5 Pa, velocity/rho atol=1e-7. Original F2 gates are unchanged.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import ctypes as ct
import os
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
import pytest

from sjtu_tpmshx.domain.cancellation import CancelledError
from sjtu_tpmshx.solvers import _kernels_simple_3d as kernels
from sjtu_tpmshx.solvers import simple_solver_3d as owner
from sjtu_tpmshx.solvers._solve_common import F2Monitor

ROOT = Path(__file__).resolve().parents[3]
DOUBLE = ct.POINTER(ct.c_double)
SIZE = ct.POINTER(ct.c_size_t)
STOP = {1: "tol", 2: "stall", 3: "max_iter", 4: "nonfinite", 5: "cancelled",
        6: "pressure_failure", 7: "post_closure"}
FIELDS = ("u", "v", "w", "P", "Pp", "d_u", "d_v", "d_w", "rho_field", "v_inlet_field")


@pytest.fixture(scope="module")
def library():
    host = "windows-x64" if sys.platform == "win32" else "macos-arm64"
    name = "simple_3d_test.dll" if sys.platform == "win32" else "libsimple_3d_test.dylib"
    path = Path(os.environ.get("TPMSHX_SIMPLE3D_TEST_LIBRARY", ROOT / ".cache/native-deps/build" / f"pilot-{host}" / name))
    if not path.is_file():
        message = f"explicit native dependency build is missing {path}"
        if os.environ.get("TPMSHX_REQUIRE_NATIVE_DEPS_TESTS") == "1":
            pytest.fail(message)
        pytest.skip(message)
    lib = ct.CDLL(str(path))
    lib.tpmshx_simple3d_create.argtypes = [ct.c_size_t]*3 + [DOUBLE]*3 + [ct.POINTER(ct.c_ubyte), ct.c_char_p, ct.c_size_t]
    lib.tpmshx_simple3d_create.restype = ct.c_void_p
    lib.tpmshx_simple3d_destroy.argtypes = [ct.c_void_p]
    lib.tpmshx_simple3d_call.argtypes = [ct.c_void_p, ct.c_int, ct.POINTER(DOUBLE), SIZE, DOUBLE, SIZE, DOUBLE, ct.c_char_p, ct.c_size_t]
    lib.tpmshx_simple3d_call.restype = ct.c_int
    lib.tpmshx_simple3d_history.argtypes = [ct.c_void_p, ct.c_int, DOUBLE, ct.c_size_t]
    lib.tpmshx_simple3d_history.restype = ct.c_size_t
    return lib, path


def make_solver(shape=(5, 7, 4), *, variable=True, partial=False, fluid="incompressible", sou=False):
    nx, ny, nz = shape
    widths = [np.linspace(.8, 1.2, n) for n in shape]
    for width, length in zip(widths, (.036, .080, .025)):
        width *= length/width.sum()
    rho, mu, velocity = (1.2, 1.8e-5, .7) if fluid == "ideal_gas" else (997., .0009, .004)
    solver = owner.SIMPLESolver3D(.036, .080, .025, nx, ny, nz, rho, mu, 300., velocity,
        eps=.6, K_arr=np.full(shape, 1e-7), cF_arr=np.full(shape, 35.), P_ref_abs=101325.,
        use_coarse_bootstrap=False, fluid_type=fluid, dx_arr=widths[0], dy_arr=widths[1], dz_arr=widths[2],
        inlet_rect=(.004, .029, .002, .020) if partial else None,
        outlet_rect=(.008, .033, .005, .024) if partial else None)
    if variable:
        x, y, z = np.meshgrid(*(np.linspace(0., 1., n) for n in shape), indexing="ij")
        solver.eps_field = np.ascontiguousarray(.52 + .06*x + .025*y + .015*z)
        solver.rho_field *= 1. + .04*x - .02*y + .01*z
        solver.mu_field *= 1. + .05*x + .03*y + .02*z
        solver._mu_eff_field = np.ascontiguousarray(solver.mu_field/solver.eps_field)
        solver.K_arr *= .9 + .2*x + .1*y + .05*z
        solver.cF_arr *= .9 + .1*x + .2*y + .03*z
    solver.use_sou_momentum = sou
    solver.track_momentum_residual = True
    return solver


def packed(s):
    return [s.eps_field, s.mu_field, s._mu_eff_field, s.K_arr, s.cF_arr, s.T_field,
            s.u, s.v, s.w, s.P, s.Pp, s.d_u, s.d_v, s.d_w, s.rho_field,
            s.v_inlet_field, s.outlet_u_frac, s.outlet_w_frac]


class Native:
    def __init__(self, library, solver):
        self.lib = library[0]
        error = ct.create_string_buffer(512)
        opening = np.ascontiguousarray(solver.outlet_mask_ij, dtype=np.uint8)
        self.pointer = self.lib.tpmshx_simple3d_create(solver.Nx, solver.Ny, solver.Nz,
            *(a.ctypes.data_as(DOUBLE) for a in (solver.dx, solver.dy, solver.dz)),
            opening.ctypes.data_as(ct.POINTER(ct.c_ubyte)), error, len(error))
        assert self.pointer, error.value.decode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.lib.tpmshx_simple3d_destroy(self.pointer)

    def call(self, s, *, operation=2, iterations=600, sweeps=1, cancel_after=0, order=0, arrays=None):
        arrays = packed(s) if arrays is None else arrays
        assert all(a.dtype == np.float64 and a.flags.c_contiguous for a in arrays)
        pointers = (DOUBLE*len(arrays))(*(a.ctypes.data_as(DOUBLE) for a in arrays))
        sizes = np.array([a.size for a in arrays], dtype=np.uintp)
        f2 = F2Monitor(s, (s.u, s.v, s.w), 10)
        values = np.array([s.alpha_u, s.alpha_p, s.alpha_rho, s.P_ref_abs, s.R_gas,
            s.pyamg_rebuild_drift_thresh, f2.mom_tol, f2.mass_local_tol, f2.mass_global_tol,
            f2.backflow_max, f2.vtol, f2.stall_ratio])
        flags = int(s.fluid_type == "ideal_gas") + 2*int(getattr(s, "massflux_inlet", True))
        flags += 4*int(getattr(s, "use_sou_momentum", False)) + 8*int(getattr(s, "use_adaptive_amg_tol", True))
        flags += 16*int(getattr(s, "track_momentum_residual", False))
        counts = np.array([iterations, sweeps, f2.n_confirm, f2.mom_every, f2.stall_window,
            flags, cancel_after, s.pyamg_rebuild_every, order], dtype=np.uintp)
        out = np.empty(32)
        error = ct.create_string_buffer(512)
        status = self.lib.tpmshx_simple3d_call(self.pointer, operation, pointers,
            sizes.ctypes.data_as(SIZE), values.ctypes.data_as(DOUBLE), counts.ctypes.data_as(SIZE),
            out.ctypes.data_as(DOUBLE), error, len(error))
        if status:
            raise ValueError(error.value.decode())
        return out

    def history(self, kind):
        size = self.lib.tpmshx_simple3d_history(self.pointer, kind, None, 0)
        values = np.empty(size)
        assert self.lib.tpmshx_simple3d_history(self.pointer, kind, values.ctypes.data_as(DOUBLE), size) == size
        return values


def python_momentum(s):
    maximum, r = s._momentum_residual(s.Nx, s.Ny, s.Nz, s.dx, s.dy, s.dz,
        int(s.use_sou_momentum), int(np.ptp(s.eps_field) != 0.))
    return np.array([*r["num"], *r["den"], r["u"], r["v"], r["w"]]), maximum


def python_predictor(s, sweeps, order=0):
    suffix = "_parallel" if order else ""
    u, v, w = (getattr(kernels, f"_sweep_{axis}_jit_df_3d{suffix}") for axis in "uvw")
    args = (s.Nx, s.Ny, s.Nz, s.dx, s.dy, s.dz)
    sou, eps = int(s.use_sou_momentum), int(np.ptp(s.eps_field) != 0.)
    u(s.u, s.v, s.w, s.P, s.d_u, *args, s.rho_field, s._mu_eff_field, s.mu_field,
      s.eps_field, s.K_arr, s.cF_arr, s.outlet_u_frac, s.alpha_u, sweeps, sou, eps)
    v(s.u, s.v, s.w, s.P, s.d_v, s.v_inlet_field, *args, s.rho_field, s.eps_field,
      s._mu_eff_field, s.mu_field, s.K_arr, s.cF_arr, s.alpha_u, sweeps, sou, eps, s.outlet_mask_ij)
    w(s.u, s.v, s.w, s.P, s.d_w, *args, s.rho_field, s._mu_eff_field, s.mu_field,
      s.eps_field, s.K_arr, s.cF_arr, s.outlet_w_frac, s.alpha_u, sweeps, sou, eps)


def compare_fields(actual, expected, *, operator=False, amg=False):
    rtol = 3e-12 if operator else 2e-7 if amg else 1e-8
    for field in FIELDS:
        atol = (2e-14 if field.startswith("d_") else 2e-12) if operator else (
            (1e-5 if amg else 1e-7) if field in {"P", "Pp"} else 1e-7 if amg else 1e-8)
        np.testing.assert_allclose(getattr(actual, field), getattr(expected, field), rtol=rtol, atol=atol, err_msg=field)
    if not operator:
        for function in (owner.SIMPLESolver3D.extract_dP_weighted, owner.SIMPLESolver3D.extract_dP_face_extrap):
            np.testing.assert_allclose(function(actual), function(expected), rtol=rtol, atol=1e-5 if amg else 1e-7)
        for axis, (velocity, width) in enumerate((("u", ("dy", "dz")), ("v", ("dx", "dz")), ("w", ("dx", "dy")))):
            flows = []
            for s in (actual, expected):
                re = s.rho_field*s.eps_field
                lower, upper = [[(0, 0)]*3 for _ in range(2)]
                lower[axis], upper[axis] = (1, 0), (0, 1)
                avg = .5*(np.pad(re, lower, mode="edge") + np.pad(re, upper, mode="edge"))
                area = (s.dy[None, :, None]*s.dz[None, None, :] if axis == 0 else
                        s.dx[:, None, None]*s.dz[None, None, :] if axis == 1 else s.dx[:, None, None]*s.dy[None, :, None])
                flows.append(avg*getattr(s, velocity)*area)
            np.testing.assert_allclose(*flows, rtol=rtol, atol=1e-9 if amg else 1e-10)


def compare_result(out, expected, native, reference_result, *, amg=False):
    assert bool(out[1]) == reference_result[0]
    assert STOP[int(out[0])] == expected.exit_reason
    assert bool(out[3])
    assert bool(out[4]) == bool(expected.f2_cert_post_rescale_ok)
    rtol, atol = (2e-7, 1e-7) if amg else (1e-8, 1e-8)
    for index, name in ((5, "final_res"), (6, "final_res_mom"), (7, "final_res_mass_local"),
                        (8, "final_res_mass_global"), (9, "outlet_backflow_frac"), (13, "res_norm_ref")):
        np.testing.assert_allclose(out[index], getattr(expected, name), rtol=rtol, atol=atol, err_msg=name)
    assert out[12] == getattr(expected, "_p_clip_hits", 0)
    _, count = kernels._mass_res_solved_jit_3d(expected.u, expected.v, expected.w,
        expected.Nx, expected.Ny, expected.Nz, expected.dx, expected.dy, expected.dz,
        np.ascontiguousarray(expected.rho_field*expected.eps_field), np.zeros(expected.P.size, dtype=np.uint8))
    assert out[25] == count
    if reference_result[0]:
        assert out[6] < 1e-4 and out[7] < 1e-6 and out[8] < 1e-6 and out[9] <= .01
    if hasattr(expected, "_massflux_target"):
        np.testing.assert_array_equal(native.history(4), expected._massflux_target.ravel())
    if not amg:
        assert out[2] == reference_result[1]
        for kind, name in enumerate(("residuals", "mass_local_residuals", "mass_global_residuals")):
            np.testing.assert_allclose(native.history(kind), getattr(expected, name), rtol=rtol, atol=atol)
        records = np.array([[r["iter"], r["max"], *r["num"], *r["den"], r["u"], r["v"], r["w"]]
                            for r in expected.mom_residuals]).reshape(-1, 11)
        np.testing.assert_allclose(native.history(3).reshape(-1, 11), records, rtol=rtol, atol=atol)


@pytest.mark.parametrize("sou,order", [(False, 0), (True, 0), (False, 1)])
@pytest.mark.parametrize("variable", [False, True])
@pytest.mark.parametrize("sweeps", [1, 3])
def test_predictor_and_raw_unrelaxed_equation(library, sou, order, variable, sweeps):
    expected = make_solver(variable=variable, sou=sou, partial=True)
    rng = np.random.default_rng(92)
    for name, scale in (("u", .003), ("v", .006), ("w", .002), ("P", 8.)):
        a = getattr(expected, name)
        a[:] = rng.normal(0., scale, a.shape)
    expected.u[[0, -1]] = 0.
    expected.w[:, :, [0, -1]] = 0.
    actual = copy.deepcopy(expected)
    with Native(library, actual) as native:
        initial = native.call(actual, operation=1)
        raw, maximum = python_momentum(expected)
        np.testing.assert_allclose(initial[14:23], raw, rtol=3e-12, atol=2e-13)
        np.testing.assert_allclose(initial[6], maximum, rtol=3e-12, atol=2e-13)
        out = native.call(actual, operation=0, sweeps=sweeps, order=order)
    python_predictor(expected, sweeps, order)
    compare_fields(actual, expected, operator=True)
    raw, maximum = python_momentum(expected)
    np.testing.assert_allclose(out[14:23], raw, rtol=3e-12, atol=2e-13)
    np.testing.assert_allclose(out[6], maximum, rtol=3e-12, atol=2e-13)


@pytest.mark.parametrize("shape", [(1, 1, 1), (1, 6, 4), (4, 1, 5), (4, 6, 1)])
def test_singleton_predictor(library, shape):
    expected = make_solver(shape, sou=True, partial=True)
    actual = copy.deepcopy(expected)
    with Native(library, actual) as native:
        out = native.call(actual, operation=0, sweeps=2)
    python_predictor(expected, 2)
    compare_fields(actual, expected, operator=True)
    raw, maximum = python_momentum(expected)
    np.testing.assert_allclose(out[14:23], raw, rtol=3e-12, atol=2e-13)
    np.testing.assert_allclose(out[6], maximum, rtol=3e-12, atol=2e-13)


@pytest.mark.parametrize("fluid,sou,partial", [("incompressible", False, False), ("ideal_gas", False, True),
    ("incompressible", True, True), ("ideal_gas", True, False)])
def test_full_cold_warm_lu(library, fluid, sou, partial):
    expected = make_solver(fluid=fluid, sou=sou, partial=partial)
    actual = copy.deepcopy(expected)
    with Native(library, actual) as native:
        for warm in (False, True):
            if warm:
                for s in (actual, expected):
                    s.T_field *= 1.005
                    s.mu_field *= 1.01
                    s._mu_eff_field = np.ascontiguousarray(s.mu_field/s.eps_field)
            out = native.call(actual)
            result = expected.solve(max_iter=600, n_inner=1)
            compare_result(out, expected, native, result)
            compare_fields(actual, expected)


@pytest.mark.parametrize("order", [0, 1])
def test_full_max_budget_and_redblack(library, order):
    expected = make_solver(fluid="ideal_gas", partial=True)
    actual = copy.deepcopy(expected)
    with Native(library, actual) as native:
        out = native.call(actual, iterations=3, order=order)
        with patch.object(owner, "_should_parallelize", return_value=bool(order)):
            result = expected.solve(max_iter=3, n_inner=1)
        compare_result(out, expected, native, result)
        compare_fields(actual, expected)
        assert out[0] == 3 and not out[1] and out[3]


@pytest.mark.parametrize("cancel_after", [1, 2, 4])
def test_cancel_preserves_original_budget_and_never_succeeds(library, cancel_after):
    expected = make_solver(fluid="ideal_gas")
    actual = copy.deepcopy(expected)
    calls = 0
    def cancel():
        nonlocal calls
        calls += 1
        return calls >= cancel_after
    with Native(library, actual) as native:
        out = native.call(actual, cancel_after=cancel_after)
        with pytest.raises(CancelledError):
            expected.solve(cancel_check=cancel)
        assert out[0] == 5 and not out[1] and out[26] == calls
        assert out[2] == max(0, cancel_after-2)
        assert len(native.history(0)) == max(0, cancel_after-2)
        assert out[31] == (0 if cancel_after == 1 else actual.Nx*actual.Nz)
        compare_fields(actual, expected)


@pytest.mark.parametrize("field", ["u", "v", "w", "P", "rho_field", "T_field"])
def test_nonfinite_entry(library, field):
    s = make_solver(fluid="ideal_gas")
    getattr(s, field).flat[0] = np.nan
    with Native(library, s) as native:
        out = native.call(s)
        assert out[0] == 4 and out[2] == 0 and out[26] == 0 and not out[1]
        assert not np.isfinite(out[[5, 6, 7, 8, 9]]).any()
        assert not native.history(0).size and not native.history(4).size


@pytest.mark.parametrize("kind", ["extent", "alias", "epsilon", "ordering"])
def test_reject_invalid_contract_before_mutation(library, kind):
    s = make_solver(sou=kind == "ordering")
    arrays = packed(s)
    order = 1 if kind == "ordering" else 0
    if kind == "extent": arrays[6] = arrays[6].ravel()[:-1]
    if kind == "alias": arrays[10] = arrays[9]
    if kind == "epsilon": arrays[0].flat[0] = 0.
    before = [a.copy() for a in arrays]
    with Native(library, s) as native:
        with pytest.raises(ValueError): native.call(s, arrays=arrays, order=order)
    for actual, expected in zip(arrays, before): np.testing.assert_array_equal(actual, expected)


def test_amg_cold_warm_fixed_massflux(library):
    expected = make_solver((13, 13, 13), fluid="ideal_gas", variable=False)
    actual = copy.deepcopy(expected)
    with Native(library, actual) as native:
        targets = None
        for warm in (False, True):
            if warm:
                for s in (actual, expected):
                    s.T_field *= 1.001
            out = native.call(actual, iterations=600)
            result = expected.solve(max_iter=600, n_inner=1)
            compare_result(out, expected, native, result, amg=True)
            compare_fields(actual, expected, amg=True)
            assert out[28] >= 1
            assert np.isfinite(out[23]) and out[24] <= 1e-10
            if targets is None: targets = native.history(4).copy()
            else: np.testing.assert_array_equal(native.history(4), targets)


def test_independent_threaded_solver_instances(library):
    def run(seed):
        s = make_solver(fluid="ideal_gas")
        s.T_field += seed
        with Native(library, s) as native:
            out = native.call(s, iterations=5)
        return out, tuple(getattr(s, f).copy() for f in FIELDS)
    serial = [run(i) for i in range(2)]
    with ThreadPoolExecutor(2) as pool:
        parallel = list(pool.map(run, range(2)))
    for a, b in zip(serial, parallel):
        np.testing.assert_array_equal(a[0], b[0])
        for aa, bb in zip(a[1], b[1]): np.testing.assert_array_equal(aa, bb)


@pytest.mark.parametrize("speed", [0., 1e-14])
@pytest.mark.parametrize("track", [False, True])
def test_zero_weak_flow_and_diagnostic_schedule(library, speed, track):
    expected = make_solver(variable=False)
    expected.v.fill(speed)
    expected.v_inlet_field.fill(speed)
    expected.track_momentum_residual = track
    actual = copy.deepcopy(expected)
    with Native(library, actual) as native:
        out = native.call(actual)
        result = expected.solve(max_iter=600)
        compare_result(out, expected, native, result)
        compare_fields(actual, expected)
        assert bool(native.history(3).size) == track
        assert out[13] == 1.  # the original <=1e-12 kg/s legacy fallback


def test_fresh_density_closure_certifies_returned_all_cells(library):
    from sjtu_tpmshx.tests.test_returned_outlet_certificate_3d import _outlet_net
    expected = make_solver(fluid="ideal_gas", partial=True)
    expected.T_field[:] = np.linspace(300., 500., expected.P.size).reshape(expected.P.shape)
    actual = copy.deepcopy(expected)
    with Native(library, actual) as native:
        out = native.call(actual, iterations=1)
        result = expected.solve(max_iter=1)
        compare_result(out, expected, native, result)
        compare_fields(actual, expected)
        np.testing.assert_allclose(_outlet_net(actual)[actual.outlet_mask_ij], 0., atol=2e-18)
        raw, maximum = python_momentum(actual)
        np.testing.assert_allclose(out[14:23], raw, rtol=3e-12, atol=2e-13)
        np.testing.assert_allclose(out[6], maximum, rtol=3e-12, atol=2e-13)
        assert out[25] == actual.P.size


def test_pressure_clip_does_not_hide_nonfinite_state(library):
    expected = make_solver(fluid="ideal_gas")
    expected.P.fill(2e7)
    actual = copy.deepcopy(expected)
    with Native(library, actual) as native:
        out = native.call(actual, iterations=1)
        result = expected.solve(max_iter=1)
        compare_result(out, expected, native, result)
        compare_fields(actual, expected)
        assert out[12] == actual.P.size
        assert np.max(actual.P + actual.P_ref_abs) == 1e7


def test_arithmetic_overflow_is_failed_state(library):
    s = make_solver()
    s.v[:, 1:-1, :] = 1e308
    with Native(library, s) as native:
        out = native.call(s, iterations=3)
        assert out[0] == 4 and not out[1] and not out[4]
        assert out[2] == 1 and not native.history(0).size


def test_unanchored_pressure_contract_is_rejected(library):
    s = make_solver()
    s.outlet_mask_ij[:] = False
    s.outlet_u_frac.fill(0.)
    s.outlet_w_frac.fill(0.)
    with Native(library, s) as native:
        with pytest.raises(ValueError, match="Dirichlet pin"):
            native.call(s, iterations=3)
        assert not native.history(0).size

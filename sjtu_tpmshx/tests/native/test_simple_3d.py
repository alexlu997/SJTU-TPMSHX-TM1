"""Native 3D SIMPLE fields, independent equations, and F2 acceptance checks."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import ctypes as ct
import os
from pathlib import Path
import sys

import numpy as np
import pytest

from sjtu_tpmshx.tests.native.momentum_audit_3d import _mom_res_jit_3d
from sjtu_tpmshx.tests.native.simple_inputs import make_3d as make_solver
from sjtu_tpmshx.tests.native.simple_audit import momentum_component_residuals, mass_balance
from sjtu_tpmshx.tests.native.simple_inputs import f2_settings

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
        self.history_offset = len(self.history(0))
        arrays = packed(s) if arrays is None else arrays
        assert all(a.dtype == np.float64 and a.flags.c_contiguous for a in arrays)
        pointers = (DOUBLE*len(arrays))(*(a.ctypes.data_as(DOUBLE) for a in arrays))
        sizes = np.array([a.size for a in arrays], dtype=np.uintp)
        f2 = f2_settings(s)
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


def audit_momentum(s):
    nu, du, nv, dv, nw, dw = _mom_res_jit_3d(s.u, s.v, s.w, s.P,
        s.Nx, s.Ny, s.Nz, s.dx, s.dy, s.dz, s.rho_field, s._mu_eff_field,
        s.mu_field, s.eps_field, s.K_arr, s.cF_arr, s.outlet_u_frac,
        s.outlet_w_frac, int(s.use_sou_momentum), int(np.ptp(s.eps_field) != 0.))
    ru, rv, rw = momentum_component_residuals((nu, nv, nw), (du, dv, dw))
    return np.array([nu, nv, nw, du, dv, dw, ru, rv, rw]), max(ru, rv, rw)


def assert_result(out, actual, native):
    assert bool(out[1]) == (out[0] == 1 and bool(out[4]))
    assert out[3]
    raw, maximum = audit_momentum(actual)
    np.testing.assert_allclose(out[14:23], raw, rtol=3e-12, atol=2e-13)
    np.testing.assert_allclose(out[6], maximum, rtol=3e-12, atol=2e-13)
    mass, counted, _ = mass_balance(actual)
    np.testing.assert_allclose(out[7:12], mass, rtol=3e-12, atol=2e-13)
    assert out[25] == counted
    assert len(native.history(0)) == native.history_offset + out[2]
    for kind in (0, 1, 2):
        assert np.isfinite(native.history(kind)).all() and (native.history(kind) >= 0.).all()
    for row in native.history(3).reshape(-1, 11):
        components = momentum_component_residuals(row[2:5], row[5:8])
        np.testing.assert_allclose(row[[1, 8, 9, 10]], [max(components), *components],
                                   rtol=3e-12, atol=2e-13)
    if out[1]:
        assert out[6] < 1e-4 and out[7] < 1e-6 and out[8] < 1e-6 and out[9] <= .01











@pytest.mark.parametrize("sou,order", [(False, 0), (True, 0), (False, 1)])
@pytest.mark.parametrize("variable", [False, True])
@pytest.mark.parametrize("sweeps", [1, 3])
def test_predictor_and_raw_unrelaxed_equation(library, sou, order, variable, sweeps):
    actual = make_solver(variable=variable, sou=sou, partial=True)
    rng = np.random.default_rng(92)
    for name, scale in (('u', .003), ('v', .006), ('w', .002), ('P', 8.)):
        a = getattr(actual, name)
        a[:] = rng.normal(0., scale, a.shape)
    actual.u[[0, -1]] = 0.
    actual.w[:, :, [0, -1]] = 0.
    with Native(library, actual) as native:
        for operation in (1, 0):
            out = native.call(actual, operation=operation, sweeps=sweeps, order=order)
            raw, maximum = audit_momentum(actual)
            np.testing.assert_allclose(out[14:23], raw, rtol=3e-12, atol=2e-13)
            np.testing.assert_allclose(out[6], maximum, rtol=3e-12, atol=2e-13)
        np.testing.assert_array_equal(actual.u[[0, -1]], 0.)
        np.testing.assert_array_equal(actual.w[:, :, [0, -1]], 0.)


@pytest.mark.parametrize("shape", [(1, 1, 1), (1, 6, 4), (4, 1, 5), (4, 6, 1)])
def test_singleton_predictor(library, shape):
    actual = make_solver(shape, sou=True, partial=True)
    with Native(library, actual) as native:
        out = native.call(actual, operation=0, sweeps=2)
    raw, maximum = audit_momentum(actual)
    np.testing.assert_allclose(out[14:23], raw, rtol=3e-12, atol=2e-13)
    np.testing.assert_allclose(out[6], maximum, rtol=3e-12, atol=2e-13)


@pytest.mark.parametrize("fluid,sou,partial", [("incompressible", False, False), ("ideal_gas", False, True),
    ("incompressible", True, True), ("ideal_gas", True, False)])
def test_full_cold_warm_lu(library, fluid, sou, partial):
    actual = make_solver(fluid=fluid, sou=sou, partial=partial)
    with Native(library, actual) as native:
        for warm in (False, True):
            if warm:
                actual.T_field *= 1.005
                actual.mu_field *= 1.01
                actual._mu_eff_field = np.ascontiguousarray(actual.mu_field/actual.eps_field)
            out = native.call(actual)
            assert out[1]
            assert_result(out, actual, native)


@pytest.mark.parametrize("order", [0, 1])
def test_full_max_budget_and_redblack(library, order):
    actual = make_solver(fluid='ideal_gas', partial=True)
    with Native(library, actual) as native:
        out = native.call(actual, iterations=3, order=order)
        assert_result(out, actual, native)
        assert out[0] == 3 and out[2] == 3 and not out[1] and out[3]


@pytest.mark.parametrize("cancel_after", [1, 2, 4])
def test_cancel_preserves_original_budget_and_never_succeeds(library, cancel_after):
    actual = make_solver(fluid='ideal_gas')
    initial = copy.deepcopy(actual)
    with Native(library, actual) as native:
        out = native.call(actual, cancel_after=cancel_after)
        assert out[0] == 5 and not out[1] and out[26] == cancel_after
        assert out[2] == max(0, cancel_after-2)
        assert len(native.history(0)) == max(0, cancel_after-2)
        assert out[31] == (0 if cancel_after == 1 else actual.Nx*actual.Nz)
        if cancel_after == 1:
            for name in FIELDS:
                np.testing.assert_array_equal(getattr(actual, name), getattr(initial, name))


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
    actual = make_solver((13, 13, 13), fluid='ideal_gas', variable=False)
    with Native(library, actual) as native:
        targets = None
        for warm in (False, True):
            if warm:
                actual.T_field *= 1.001
            out = native.call(actual, iterations=600)
            assert out[1]
            assert_result(out, actual, native)
            assert out[28] >= 1
            assert np.isfinite(out[23]) and out[24] <= 1e-10
            if targets is None:
                targets = native.history(4).copy()
            else:
                np.testing.assert_array_equal(native.history(4), targets)


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
    actual = make_solver(variable=False)
    actual.v.fill(speed)
    actual.v_inlet_field.fill(speed)
    actual.track_momentum_residual = track
    with Native(library, actual) as native:
        out = native.call(actual)
        assert_result(out, actual, native)
        assert out[1]
        assert bool(native.history(3).size) == track
        assert out[13] == 1.


def test_fresh_density_closure_certifies_returned_all_cells(library):
    actual = make_solver(fluid='ideal_gas', partial=True)
    actual.T_field[:] = np.linspace(300., 500., actual.P.size).reshape(actual.P.shape)
    with Native(library, actual) as native:
        out = native.call(actual, iterations=1)
        assert_result(out, actual, native)
        _, _, net = mass_balance(actual)
        np.testing.assert_allclose(net[:, -1][actual.outlet_mask_ij], 0., atol=2e-18)
        assert out[25] == actual.P.size


def test_pressure_clip_does_not_hide_nonfinite_state(library):
    actual = make_solver(fluid='ideal_gas')
    actual.P.fill(2e7)
    with Native(library, actual) as native:
        out = native.call(actual, iterations=1)
        assert_result(out, actual, native)
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

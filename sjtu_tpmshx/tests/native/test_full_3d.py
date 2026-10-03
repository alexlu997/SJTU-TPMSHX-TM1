"""Prepared-data 3D outer driver qualification against the unchanged backend.

Reference tolerances frozen before execution: temperature rtol1e-8/atol1e-6 K;
flow/pressure rtol2e-7, velocity/density atol1e-7, pressure atol1e-5 Pa.
Native exit reasons, original physical gates and charged thermal counts remain
separate exact assertions. These are software comparison tolerances, not gates.
"""
import copy
import ctypes
from dataclasses import replace
from importlib.metadata import version
import os
from pathlib import Path
import platform
import sys
from unittest.mock import patch

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import FluidConfig
from sjtu_tpmshx.domain.run_environment import run_environment
from sjtu_tpmshx.models.field_coordinates_3d import _port_rectangles
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.backends.python.three_d.execution import build_execution_inputs
from sjtu_tpmshx.solvers.backends.python.three_d import runtime
from sjtu_tpmshx.tests.native.test_native_execution import _config


ROOT = Path(__file__).resolve().parents[3]
FLOW_FIELDS = ("dx", "dy", "dz", "eps_field", "K_arr", "cF_arr", "T_field", "mu_field",
               "_mu_eff_field", "rho_field", "u", "v", "w", "P", "Pp", "d_u", "d_v", "d_w",
               "v_inlet_field", "inlet_frac", "outlet_frac", "outlet_u_frac", "outlet_w_frac",
               "_massflux_target")


class NativeFull3D:
    def __init__(self, library):
        self.library = ctypes.CDLL(str(library))
        sp, dp = ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_double)
        self.library.test_full_3d_run.argtypes = [sp, ctypes.POINTER(dp), sp, sp, dp, ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_char), ctypes.c_size_t]
        self.library.test_full_3d_run.restype = ctypes.c_int
        self.library.test_full_3d_field.argtypes = [ctypes.c_void_p, ctypes.c_size_t, sp]
        self.library.test_full_3d_field.restype = dp
        self.library.test_full_3d_destroy.argtypes = [ctypes.c_void_p]

    def run(self, cfg, prepared, *, cancel_at=0, bad_size=None, cancel_before_thermal=False):
        shape = (prepared["Nx"], prepared["Ny"], prepared["Nz"])
        design, thermal = prepared["design"], cfg["thermal_geometry"]
        spatial = bool(cfg.get("zone_grid_cells") or cfg.get("continuous_field"))
        geom = thermal["fields" if spatial else "uniform"]
        field = lambda x: np.array(np.broadcast_to(x, shape), dtype=np.float64, order="C")
        arrays = [*[np.asarray(prepared["d"+axis]) for axis in "xyz"],
                  *[np.asarray(design[k]) for k in ("eps_arr", "eps_A", "eps_B", "K_m2", "cF_per_m", "K_ss", "L_field_m")],
                  field(geom["A_0"]), field(geom["D_h"])]
        for side in "AB":
            arrays += [np.asarray(prepared["openings"][side][end]) for end in ("inlet", "outlet")]
        arrays += [np.asarray(cfg.get("mms_S_"+side+"_field", np.empty(0))) for side in ("A", "B", "s")]
        arrays = [np.ascontiguousarray(a, dtype=np.float64) for a in arrays]
        assert len(arrays) == 19
        f = np.zeros(47, dtype=np.uintp)
        f[46] = cancel_before_thermal
        v = np.zeros(57, dtype=np.float64)
        f[0] = ("Diamond", "Gyroid").index(cfg["tpms_type"])
        f[1:3] = [("air", "water", "sco2").index(cfg["fluid_type_"+s]) for s in "AB"]
        f[3:5] = [(cfg["fluid_"+s+"_cfg"] or {"dir": 3})["dir"] for s in "AB"]
        f[5:8] = [cfg.get("fluid_B_cfg") is not None, spatial, cfg.get("delta_levelset", 0.) != 0.]
        simple_cap = cfg.get("max_iter_simple")
        f[8:12] = [prepared["max_outer"] if prepared["max_outer"] is not None else 12,
                   simple_cap if simple_cap is not None else 2000, simple_cap if simple_cap is not None else 600,
                   prepared["ltne_max_iter"]]
        f[12] = run_environment(cfg, "TPMSHX_P_IN_SHOOT", "1") != "0"
        vrho = run_environment(cfg, "TPMSHX_VAR_RHOCP")
        f[13] = vrho == "1" if vrho in ("0", "1") else bool(cfg.get("variable_rho_cp", True))
        f[14:19] = [bool(cfg.get("conservative_ltne", True)), bool(cfg.get("strict_mass_balance", True)),
            bool(cfg.get("force_cc_ltne", True)), bool(cfg.get("port_wall_refine", False)),
            bool(cfg.get("_native_rb_energy", np.prod(shape) > 30000))]
        f[19] = run_environment(cfg, "TPMSHX_SCO2_COMPRESSIBLE", "").lower() in ("1", "true", "yes")
        f[20:25] = [bool(cfg.get("use_coarse_bootstrap", False)), bool(cfg.get("outer_anderson", False)),
                    int(cfg.get("coarse_bootstrap_max_iter", 200)), int(cfg.get("outer_anderson_m", 3)),
                    int(cfg.get("outer_anderson_patience", 3))]
        f[25] = ("baseline", "norris_1a", "bhatti_shah_1b").index(cfg["roughness_resolved"]["mode"])
        f[26] = ("raise", "warn", "off").index(cfg.get("envelope_mode", "raise"))
        f[27:33] = [1, 100, bool(cfg.get("_native_sou", False)), bool(cfg.get("use_adaptive_amg_tol", True)),
                    bool(cfg.get("track_momentum_residual", False)), bool(cfg.get("_native_rb_simple", np.prod(shape) >= 200000))]
        f[33:40] = [cfg.get("ltne_enthalpy_outer", 1500), cfg.get("ltne_enthalpy_nsweep", 25), 2, 5, 60,
                    cfg.get("T_s_init") is not None, cancel_at]
        v[0:2] = [cfg["Lcell"]*1e-3, prepared["geometry"]["D_h"]]
        for s, side in enumerate("AB"):
            axis = prepared["axes"][side]
            f[40+3*s:43+3*s] = [axis[k+"_real_axis"] for k in ("cross1", "stream", "cross2")]
            v[2+3*s:5+3*s] = [cfg["T_in"+side], cfg["P_in"+side], cfg["u_"+side]]
            ports = (_port_rectangles(cfg["fluid_"+side+"_cfg"], float(sum(axis["dcross2"])))
                     if cfg["fluid_"+side+"_cfg"] is not None else {"inlet_rect": (0., 1., 0., 1.), "outlet_rect": (0., 1., 0., 1.)})
            v[8+8*s:12+8*s], v[12+8*s:16+8*s] = ports["inlet_rect"], ports["outlet_rect"]
            correction = (cfg.get("df_application") or {}).get(side, {})
            v[24+2*s:26+2*s] = [correction.get("scale_K", 1.), correction.get("scale_F", 1.)]
            v[28+s] = cfg.get("disp_C_"+side, 0.)
            nu = cfg["sco2_nu"]
            v[30+s] = (getattr(nu, "alpha_D" if f[0] == 0 else "alpha_G") if nu.mode == "experimental" else 1.)
            v[32+4*s:36+4*s] = thermal["side_geometry"][side] if f[7] else (1., 1., 1., 1.)
        v[40:45] = [cfg.get("outer_tol_K") if cfg.get("outer_tol_K") is not None else .5,
                   cfg.get("ltne_alpha_T", .7), cfg.get("outer_anderson_trust", 5.),
                   cfg["roughness_resolved"]["eps_m"], cfg.get("T_s_init") or 0.]
        v[45:57] = [.5, .2, .3, .05, cfg.get("mom_tol") or 1e-4,
                   cfg.get("mass_local_tol") or 1e-6, cfg.get("mass_global_tol") or 1e-6,
                   .01, 1e-4, 1e-3, cfg.get("ltne_enthalpy_omega", .6), cfg.get("ltne_enthalpy_tol", 1e-3)]
        dp = ctypes.POINTER(ctypes.c_double)
        pointers = (dp*len(arrays))(*(a.ctypes.data_as(dp) for a in arrays))
        sizes = np.array([a.size for a in arrays], dtype=np.uintp)
        if bad_size is not None:
            sizes[bad_size] -= 1
        handle, error = ctypes.c_void_p(), ctypes.create_string_buffer(1024)
        dimensions = np.array(shape, dtype=np.uintp)
        sp = ctypes.POINTER(ctypes.c_size_t)
        code = self.library.test_full_3d_run(dimensions.ctypes.data_as(sp), pointers, sizes.ctypes.data_as(sp),
            f.ctypes.data_as(sp), v.ctypes.data_as(dp), str(ROOT/".cache/native-deps/full3d-tables").encode(),
            ctypes.byref(handle), error, len(error))
        if code:
            return {"code": code, "error": error.value.decode()}
        result = {"code": 0, "error": ""}
        try:
            for key in (*range(27), *range(100, 136), *range(140, 176), 200, 201, 202):
                size = ctypes.c_size_t()
                p = self.library.test_full_3d_field(handle, key, ctypes.byref(size))
                result[key] = np.ctypeslib.as_array(p, (size.value,)).copy() if size.value else np.empty(0)
        finally:
            self.library.test_full_3d_destroy(handle)
        result[200] = result[200].reshape(-1, 16)
        return result


@pytest.fixture(scope="module")
def native():
    platform = "windows-x64" if os.name == "nt" else "macos-arm64"
    suffix = ".dll" if os.name == "nt" else (".dylib" if sys.platform == "darwin" else ".so")
    name = ("" if os.name == "nt" else "lib")+"full_3d_test"+suffix
    path = Path(os.environ.get("TPMSHX_FULL_3D_TEST_LIBRARY", ROOT/".cache/native-deps/build"/("pilot-"+platform)/name))
    if not path.is_file():
        if os.environ.get("TPMSHX_REQUIRE_NATIVE_DEPS_TESTS") == "1":
            pytest.fail(f"native full 3D library missing: {path}")
        pytest.skip(f"native full 3D library missing: {path}")
    return NativeFull3D(path)


def prepared(pair="air-air", *, directions=None, counts=None, mesh=None, **controls):
    cfg = _config(3, True)
    fluids = pair.split("-")
    def fluid(name, a):
        return FluidConfig(type=name, u_mps=(3. if name == "air" else .2),
            T_in_K=(350. if name == "water" else 500.) if a else 300.,
            P_in_Pa=12e6 if name == "sco2" else (2e6 if name == "water" else 2e5))
    cfg = replace(cfg, fluid_A=fluid(fluids[0], True), fluid_B=fluid(fluids[1], False))
    if directions is not None:
        cfg = replace(cfg, bc_A=replace(cfg.bc_A, dir=directions[0]), bc_B=replace(cfg.bc_B, dir=directions[1]))
    if counts is not None:
        cfg = replace(cfg, solver=replace(cfg.solver, Nx=counts[0], Ny=counts[1], Nz=counts[2]))
    if mesh is not None and mesh != "graded":
        cfg = replace(cfg, flags=replace(cfg.flags, **{mesh: True}))
    if counts is not None and counts[2] == 1:
        # Explicitly exercise the 3D runtime's retained Nz=1 delegate. Public
        # automatic preparation ordinarily routes this configuration to 2D.
        from sjtu_tpmshx.preprocess.three_d.preparation import _parse_inputs_3d_cfg, _prepare_problem_data
        c = _parse_inputs_3d_cfg(cfg)
        p = _prepare_problem_data(c)
        c = p.pop("cfg")
        c.update(controls)
        return c, p
    else:
        if mesh == "graded":
            def graded(_wall, lx, ly, lz, nx, ny, nz):
                widths = [np.linspace(.65, 1.35, n) for n in (nx, ny, nz)]
                for w, length in zip(widths, (lx, ly, lz)):
                    w *= length / w.sum()
                return *widths, nx, ny, nz
            with patch("sjtu_tpmshx.preprocess.three_d.preparation._build_grid_3d", graded):
                case = prepare_case(cfg, case_id="native-full3d-"+pair)
        else:
            case = prepare_case(cfg, case_id="native-full3d-"+pair)
    c, p = build_execution_inputs(case)
    c.update(controls)
    return c, p


def reference(cfg, p):
    original = runtime.SIMPLESolver3D.solve
    def observed(solver, *args, **kwargs):
        value = original(solver, *args, **kwargs)
        solver._full_native_last_iterations = value[1]
        return value
    with patch.object(runtime.SIMPLESolver3D, "solve", observed):
        prob = runtime.build_problem(copy.deepcopy(cfg), copy.deepcopy(p))
        outer = runtime._run_outer_coupling_3d(prob, runtime._build_hv_machinery(prob), capture_native=True)
    metrics = runtime._extract_3d_metrics(prob, outer)
    raw, diagnostics = runtime._assemble_3d_verdict(prob, outer, metrics)
    return prob, outer, metrics, raw, diagnostics


def assert_equivalent(actual, expected):
    assert actual["code"] == 0, actual["error"]
    prob, outer, metrics, raw, diagnostics = expected
    stats = actual[202]
    assert bool(stats[1]) == bool(raw["solver_converged"])
    assert bool(stats[4]) == bool(outer._outer_converged)
    assert actual[200].shape[0] == len(prob._ltne_info)
    np.testing.assert_array_equal(actual[200][:, 1], [x["iters"] for x in prob._ltne_info])
    np.testing.assert_array_equal(actual[200][:, 3], [x["converged"] for x in prob._ltne_info])
    np.testing.assert_allclose(actual[200][:, 5:8], [[x[k] for k in ("Ta", "Tb", "Ts")] for x in outer._outer_dT_hist],
                               rtol=1e-7, atol=2e-6)
    for code, key in enumerate(("Ta", "Tb", "Ts", "P_thermal_A", "P_thermal_B", "h_vA", "h_vB", "rho_cp_A", "rho_cp_B")):
        if outer.native_evidence[key] is None:
            assert actual[code].size == 0
            continue
        np.testing.assert_allclose(actual[code], np.asarray(outer.native_evidence[key]).ravel(),
            rtol=1e-8 if code<3 else 2e-7, atol=1e-6 if code<3 else (1e-5 if code<5 else 1e-7), err_msg=key)
    for side, solver in enumerate((prob.sA, prob.sB)):
        if solver is None:
            continue
        for code, key in enumerate(FLOW_FIELDS):
            want = getattr(solver, key)
            np.testing.assert_allclose(actual[100+40*side+code], np.asarray(want).ravel(), rtol=2e-7,
                atol=1e-5 if key in ("P", "Pp") else 1e-7, err_msg=f"{side}:{key}")
        start = 24+10*side
        assert bool(stats[start+2]) == (solver.exit_reason == "tol")
        assert stats[start+1] == {"tol": 1, "stall": 2, "max_iter": 3, "nonfinite": 4,
                                 "cancelled": 5, "pressure_failure": 6, "post_closure": 7}[solver.exit_reason]
        assert stats[start+3] == solver._full_native_last_iterations
        assert len(actual[132+40*side]) == len(solver.residuals)
        np.testing.assert_allclose(stats[start+4:start+8],
            [solver.final_res_mom, solver.final_res_mass_local, solver.final_res_mass_global, solver.outlet_backflow_frac],
            rtol=3e-5, atol=1e-10)
    metric_values = [metrics.dP, metrics.dP_B, metrics.T_A_out, metrics.T_B_out,
                     metrics.m_dot_A_simple, metrics.m_dot_B_simple, metrics.Q_enthalpy_A, metrics.Q_enthalpy_B]
    np.testing.assert_allclose(stats[12:20], [np.nan if value is None else value for value in metric_values], rtol=2e-7, atol=1e-5)
    for side in range(2):
        for key, start in (("mass_", 11), ("face_velocity_", 17)):
            expected_faces = outer.native_evidence[key+"AB"[side]]
            if expected_faces is None:
                assert all(actual[start+3*side+axis].size == 0 for axis in range(3))
            else:
                for axis in range(3):
                    np.testing.assert_allclose(actual[start+3*side+axis], expected_faces[axis].ravel(), rtol=2e-7, atol=1e-10)


@pytest.mark.parametrize("pair", ["air-air", "air-water", "water-air", "air-sco2", "sco2-water"])
def test_full_prepared_outer(native, pair):
    cfg, p = prepared(pair)
    actual = native.run(cfg, p)
    assert_equivalent(actual, reference(cfg, p))


@pytest.mark.parametrize("conservative,force_cc", [(False, True), (False, False), (True, True)])
def test_temperature_routes(native, conservative, force_cc):
    cfg, p = prepared("air-air", conservative_ltne=conservative, force_cc_ltne=force_cc, variable_rho_cp=False)
    assert_equivalent(native.run(cfg, p), reference(cfg, p))


def test_cap_retains_thermal_and_later_flow(native):
    cfg, p = prepared("air-sco2")
    p["max_outer"] = 1
    actual = native.run(cfg, p)
    assert_equivalent(actual, reference(cfg, p))
    assert actual[202][7] == 1 and actual[202][1] == 0
    assert np.max(np.abs(actual[3]-actual[124])) > 1e-5


@pytest.mark.parametrize("when", [1, 10, 200])
def test_cancel_never_certifies(native, when):
    cfg, p = prepared()
    actual = native.run(cfg, p, cancel_at=when)
    assert actual["code"] == 0, actual["error"]
    assert actual[202][0] == 2 and actual[202][1] == 0


def test_invalid_prepared_extent_before_execution(native):
    cfg, p = prepared()
    actual = native.run(cfg, p, bad_size=3)
    assert actual["code"] == 1 and "extent" in actual["error"]


@pytest.mark.parametrize("direction", range(6))
def test_every_physical_direction(native, direction):
    cfg, p = prepared(directions=(direction, (direction+3)%6))
    p["max_outer"] = 2
    assert_equivalent(native.run(cfg, p), reference(cfg, p))


@pytest.mark.parametrize("pair", ["air-air", "air-sco2"])
def test_nz_one_delegates_original_2d_temperature(native, pair):
    cfg, p = prepared(pair, directions=(0, 3), counts=(4, 4, 1))
    assert_equivalent(native.run(cfg, p), reference(cfg, p))


@pytest.mark.parametrize("pair", ["air-air", "air-water"])
def test_outer_anderson_property_order(native, pair):
    cfg, p = prepared(pair, outer_anderson=True)
    assert_equivalent(native.run(cfg, p), reference(cfg, p))


def test_sco2_a_local_pressure_property_switch(native):
    cfg, p = prepared("sco2-water")
    cfg["_environment"]["TPMSHX_SCO2_COMPRESSIBLE"] = "1"
    assert_equivalent(native.run(cfg, p), reference(cfg, p))


def test_no_b_solver_prescribed_temperature(native):
    cfg, p = prepared("air-air")
    cfg["fluid_B_cfg"] = None
    assert_equivalent(native.run(cfg, p), reference(cfg, p))


def _report_refined_grid_failure(actual, expected):
    """Expose the first CI/local divergence without changing comparison gates."""
    print("wall24 failure environment:", dict(machine=platform.machine(), macos=platform.mac_ver()[0],
        python_compiler=platform.python_compiler(),
        packages={name: version(name) for name in ("numpy", "numba", "llvmlite")}))
    np.show_config()
    print("native return:", actual["code"], actual["error"])
    if actual["code"]:
        return
    prob, outer, metrics, _, _ = expected
    print("native outer history:", actual[200].tolist())
    print("native status/flow statistics:", actual[202].tolist())
    print("python thermal history:", [{key: row[key] for key in ("iters", "converged", "residual")}
                                     for row in prob._ltne_info])
    print("python flow stopping:", [None if solver is None else {
        key: getattr(solver, key) for key in ("exit_reason", "_full_native_last_iterations",
            "final_res_mom", "final_res_mass_local", "final_res_mass_global", "outlet_backflow_frac")}
        for solver in (prob.sA, prob.sB)])
    print("python outer temperature changes:", outer._outer_dT_hist)
    print("python final energy checks:", [row.get("energy_finishing_checks", [])[-3:]
                                         for row in prob._ltne_info])

    def compare(name, got, want, rtol, atol):
        got, want = np.asarray(got), np.asarray(want)
        if got.shape != want.shape:
            print("field mismatch:", name, dict(native_shape=got.shape, python_shape=want.shape))
            return 1
        passing = np.isclose(got, want, rtol=rtol, atol=atol, equal_nan=True)
        if np.all(passing):
            return 0
        finite = np.isfinite(got) & np.isfinite(want)
        print("field mismatch:", name, dict(
            max_abs=float(np.max(np.abs(got[finite]-want[finite]))) if np.any(finite) else None,
            failing_values=int(np.count_nonzero(~passing)),
            native_nonfinite=int(np.count_nonzero(~np.isfinite(got))),
            python_nonfinite=int(np.count_nonzero(~np.isfinite(want))), rtol=rtol, atol=atol))
        return 1

    failed = 0
    for code, key in enumerate(("Ta", "Tb", "Ts", "P_thermal_A", "P_thermal_B", "h_vA", "h_vB", "rho_cp_A", "rho_cp_B")):
        want = outer.native_evidence[key]
        failed += compare(key, actual[code], np.empty(0) if want is None else np.asarray(want).ravel(),
                          1e-8 if code < 3 else 2e-7, 1e-6 if code < 3 else (1e-5 if code < 5 else 1e-7))
    for side, solver in enumerate((prob.sA, prob.sB)):
        if solver is not None:
            for code, key in enumerate(FLOW_FIELDS):
                failed += compare(f"{side}:{key}", actual[100+40*side+code], np.asarray(getattr(solver, key)).ravel(),
                                  2e-7, 1e-5 if key in ("P", "Pp") else 1e-7)
    for side in range(2):
        for key, start in (("mass_", 11), ("face_velocity_", 17)):
            faces = outer.native_evidence[key+"AB"[side]]
            for axis in range(3):
                want = np.empty(0) if faces is None else np.asarray(faces[axis]).ravel()
                failed += compare(f"{key}{'AB'[side]}:{axis}", actual[start+3*side+axis], want, 2e-7, 1e-10)
    print("thermal/flow/face fields failing original tolerances:", failed)
    values = [metrics.dP, metrics.dP_B, metrics.T_A_out, metrics.T_B_out,
              metrics.m_dot_A_simple, metrics.m_dot_B_simple, metrics.Q_enthalpy_A, metrics.Q_enthalpy_B]
    want = np.asarray([np.nan if value is None else value for value in values])
    print("metrics [dP_A,dP_B,Tout_A,Tout_B,mdot_A,mdot_B,Q_A,Q_B]:", dict(
        native=actual[202][12:20].tolist(), python=want.tolist(), delta=(actual[202][12:20]-want).tolist()))


def test_refined_real_grid_and_existing_energy_acceleration(native):
    cfg, p = prepared("air-air", counts=(8, 8, 8), mesh="wall_refine_3d", port_wall_refine=True)
    p["max_outer"] = 2
    actual, expected = native.run(cfg, p), reference(cfg, p)
    try:
        assert_equivalent(actual, expected)
    except AssertionError:
        _report_refined_grid_failure(actual, expected)
        raise


def test_graded_direct_grid_and_existing_energy_acceleration(native):
    cfg, p = prepared("air-air", counts=(8, 8, 8), mesh="graded", port_wall_refine=True)
    p["max_outer"] = 2
    assert_equivalent(native.run(cfg, p), reference(cfg, p))


@pytest.mark.parametrize("mode", ["baseline", "norris_1a", "bhatti_shah_1b"])
def test_original_air_roughness_mode(native, mode):
    cfg, p = prepared("air-air")
    cfg["roughness_resolved"]["mode"] = mode
    assert_equivalent(native.run(cfg, p), reference(cfg, p))


def test_dispersion_and_user_solid_seed(native):
    cfg, p = prepared("air-water", disp_C_A=.1, disp_C_B=.06, T_s_init=335.)
    assert_equivalent(native.run(cfg, p), reference(cfg, p))


@pytest.mark.parametrize("counts,mesh", [((4, 4, 4), None), ((8, 8, 8), None), ((9, 8, 11), "graded"), ((9, 8, 11), "wall_refine_3d")])
def test_coarse_bootstrap_preserves_physical_ports_and_fine_gate(native, counts, mesh):
    cfg, p = prepared("air-air", counts=counts, mesh=mesh, use_coarse_bootstrap=True, coarse_bootstrap_max_iter=30)
    cfg["max_iter_simple"] = 100
    p["max_outer"] = 1
    assert_equivalent(native.run(cfg, p), reference(cfg, p))

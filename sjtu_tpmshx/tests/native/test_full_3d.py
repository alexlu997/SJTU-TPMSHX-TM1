"""Native full 3D states, independent equations, and continuation checks.

Flow mapping retains rtol2e-7 and the original absolute field tolerances.
Independent residuals use the component audit tolerances. Refined thermal
completion retains the 20000-iteration budget and all six physical gates.
"""
import ctypes
from dataclasses import replace
import os
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import FluidConfig
from sjtu_tpmshx.domain.run_environment import run_environment
from sjtu_tpmshx.models.field_coordinates_3d import _port_rectangles
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs
from types import SimpleNamespace
from sjtu_tpmshx.tests.native.test_native_execution import _config
from sjtu_tpmshx.tests.native.simple_audit import mass_balance
from sjtu_tpmshx.tests.native.test_simple_3d import audit_momentum
from sjtu_tpmshx.models.field_coordinates_3d import _solver_velocity_to_real, _solver_staggered_to_real


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

    def balance_outflow(self, shape, axes, direction, widths, solver_faces, coefficient):
        face_shapes = [tuple(n + (axis == d) for d, n in enumerate(shape)) for axis in range(3)]
        mapped = [np.full(dims, np.nan) for dims in face_shapes]
        balanced = [np.full(dims, np.nan) for dims in face_shapes]
        arrays = [*widths, *solver_faces, coefficient, *mapped, *balanced]
        assert all(a.dtype == np.float64 and a.flags.c_contiguous for a in arrays)
        sp, dp = ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_double)
        function = self.library.test_full_3d_outflow
        function.argtypes = [sp, sp, ctypes.c_int, ctypes.POINTER(dp), sp, ctypes.c_char_p, ctypes.c_size_t]
        function.restype = ctypes.c_int
        dimensions = np.array(shape, dtype=np.uintp)
        permutation = np.array(axes, dtype=np.uintp)
        sizes = np.array([a.size for a in arrays], dtype=np.uintp)
        pointers = (dp*len(arrays))(*(a.ctypes.data_as(dp) for a in arrays))
        error = ctypes.create_string_buffer(1024)
        code = function(dimensions.ctypes.data_as(sp), permutation.ctypes.data_as(sp), direction,
                        pointers, sizes.ctypes.data_as(sp), error, len(error))
        assert code == 0, error.value.decode()
        return mapped, balanced

    def run(self, cfg, prepared, *, cancel_at=0, bad_size=None, cancel_before_thermal=False,
            resume_cut=None, invalid_resume=0, audit_prepare=False):
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
        f[46] = audit_prepare
        f[43] = cancel_before_thermal
        f[44] = 0 if resume_cut is None else resume_cut + 1
        f[45] = invalid_resume
        v = np.zeros(56, dtype=np.float64)
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
        f[20:22] = [bool(cfg.get("use_coarse_bootstrap", False)),
                    int(cfg.get("coarse_bootstrap_max_iter", 200))]
        f[22] = ("baseline", "norris_1a", "bhatti_shah_1b").index(cfg["roughness_resolved"]["mode"])
        f[23] = ("raise", "warn", "off").index(cfg.get("envelope_mode", "raise"))
        f[24:30] = [1, 100, bool(cfg.get("_native_sou", False)), bool(cfg.get("use_adaptive_amg_tol", True)),
                    bool(cfg.get("track_momentum_residual", False)), bool(cfg.get("_native_rb_simple", np.prod(shape) >= 200000))]
        f[30:37] = [cfg.get("ltne_enthalpy_outer", 1500), cfg.get("ltne_enthalpy_nsweep", 25), 2, 5, 60,
                    cfg.get("T_s_init") is not None, cancel_at]
        v[0:2] = [cfg["Lcell"]*1e-3, prepared["geometry"]["D_h"]]
        for s, side in enumerate("AB"):
            axis = prepared["axes"][side]
            f[37+3*s:40+3*s] = [axis[k+"_real_axis"] for k in ("cross1", "stream", "cross2")]
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
        v[40:44] = [cfg.get("outer_tol_K") if cfg.get("outer_tol_K") is not None else .5,
                   cfg.get("ltne_alpha_T", .7),
                   cfg["roughness_resolved"]["eps_m"], cfg.get("T_s_init") or 0.]
        v[44:56] = [.5, .2, .3, .05, cfg.get("mom_tol") or 1e-4,
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
            for key in (*range(27), *range(100, 136), *range(140, 176), 200, 201, 202, 203):
                size = ctypes.c_size_t()
                p = self.library.test_full_3d_field(handle, key, ctypes.byref(size))
                result[key] = np.ctypeslib.as_array(p, (size.value,)).copy() if size.value else np.empty(0)
        finally:
            self.library.test_full_3d_destroy(handle)
        result[200] = result[200].reshape(-1, 16)
        result[203] = result[203].reshape(-1, 7)
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
            def graded(lx, ly, lz, nx, ny, nz):
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


def flow_state(actual, side):
    base = 100 + 40*side
    widths = [actual[base+i] for i in range(3)]
    shape = tuple(len(x) for x in widths)
    fields = dict(zip(("Nx", "Ny", "Nz"), shape))
    for code, key in enumerate(FLOW_FIELDS):
        if code < 3:
            dims = (shape[code],)
        elif code in (10, 11, 12, 15, 16, 17):
            axis = (code-10) % 5
            dims = tuple(n + int(i == axis) for i, n in enumerate(shape))
        elif code in (18, 19, 20, 23):
            dims = (shape[0], shape[2])
        elif code == 21:
            dims = (shape[0]+1, shape[2])
        elif code == 22:
            dims = (shape[0], shape[2]+1)
        else:
            dims = shape
        fields[key] = actual[base+code].reshape(dims)
    return SimpleNamespace(**fields)


def audit_flow(actual, cfg, p):
    stats = actual[202]
    real_shape = tuple(p['N'+axis] for axis in 'xyz')
    for side, name in enumerate('AB'):
        if cfg['fluid_'+name+'_cfg'] is None:
            assert not actual[100+40*side].size
            continue
        flow = flow_state(actual, side)
        flow.use_sou_momentum = cfg.get('_native_sou', False)
        base, start = 100+40*side, 24+10*side
        _, momentum = audit_momentum(flow)
        mass, _, _ = mass_balance(flow)
        np.testing.assert_allclose(stats[start+4:start+8], [momentum, *mass[:3]], rtol=3e-12, atol=2e-13)
        assert bool(stats[start+2]) == (stats[start+1] == 1 and bool(stats[start+9]))
        if stats[start+2]:
            assert momentum < (cfg.get('mom_tol') or 1e-4)
            assert mass[0] < (cfg.get('mass_local_tol') or 1e-6)
            assert mass[1] < (cfg.get('mass_global_tol') or 1e-6)
            assert mass[2] <= .01
        for code in range(32, 35):
            assert np.isfinite(actual[base+code]).all() and (actual[base+code] >= 0.).all()
        assert len(actual[base+32]) >= stats[start+3]
        axes = p['axes'][name]
        for code, field in ((24, stats[start]+flow.P), (25, flow.rho_field)):
            field = field.transpose(axes['solver_to_real_perm'])
            if axes['is_reverse']:
                field = np.flip(field, axis=axes['stream_real_axis'])
            np.testing.assert_allclose(actual[base+code], field.ravel(), rtol=2e-7, atol=1e-5 if code == 24 else 1e-7)
        for offset, fields in ((26, _solver_velocity_to_real(flow, axes, real_shape)),
                               (29, _solver_staggered_to_real(flow, axes, real_shape))):
            for axis, field in enumerate(fields):
                np.testing.assert_allclose(actual[base+offset+axis], field.ravel(), rtol=2e-7, atol=1e-10)
        assert np.isfinite(actual[base+24]).all() and (actual[base+24] > 0.).all()


def thermal_case(actual, cfg, p):
    shape = tuple(p['N'+axis] for axis in 'xyz')
    field = lambda value: np.array(np.broadcast_to(value, shape), dtype=np.float64, order='C')
    case = dict(shape=shape, widths=[p['d'+axis] for axis in 'xyz'],
        state=[actual[i].reshape(shape).copy() for i in range(3)],
        ks=field(p['design']['K_ss']), source_s=np.empty(0),
        tin=tuple(cfg['T_in'+s] for s in 'AB'),
        directions=tuple(cfg['fluid_'+s+'_cfg']['dir'] for s in 'AB'),
        fluids=tuple(('air', 'water', 'sco2').index(cfg['fluid_type_'+s]) for s in 'AB'))
    for side, name in enumerate('AB'):
        masses = [actual[11+3*side+axis].reshape(tuple(n+int(i == axis) for i,n in enumerate(shape))) for axis in range(3)]
        case[name.lower()] = [actual[9+side].reshape(shape), actual[5+side].reshape(shape),
            *masses, np.empty(0), np.array(p['openings'][name]['inlet'], dtype=np.float64, order='C'), np.empty(0)]
    return case


def audit_full(actual, cfg, p):
    assert actual['code'] == 0, actual['error']
    stats, history = actual[202], actual[200]
    assert stats[5]
    for side, name in enumerate('AB'):
        if cfg['fluid_'+name+'_cfg'] is not None:
            assert np.isfinite(stats[12+side:24:2]).all()
    assert bool(stats[1]) == bool(np.all(stats[2:7]))
    assert 0 < len(history) <= (p['max_outer'] if p['max_outer'] is not None else 12)
    np.testing.assert_array_equal(history[:, 0], np.arange(len(history)))
    assert np.all(history[:, 1] > 0) and np.all(history[:, 5:8] >= 0.)
    assert stats[9] == history[-1, 0]
    assert bool(stats[3]) == bool(history[-1, 3])
    assert bool(stats[4]) == bool(history[-1, 4])
    for i in range(3):
        assert actual[i].size == p['Nx']*p['Ny']*p['Nz']
        assert np.isfinite(actual[i]).all() and (actual[i] > 0.).all()
    for i in range(5, 11):
        assert np.isfinite(actual[i]).all() and (actual[i] >= 0.).all()
    audit_flow(actual, cfg, p)
    if stats[8] == 1:
        from sjtu_tpmshx.tests.native import test_model_h_3d as model_h
        info = model_h.returned_model_info(thermal_case(actual, cfg, p))
        gates = model_h.compute_phase2a(dict(info, _audit_fB=True))['gates']
        assert abs(info['model_h_balance']['telescoping_error_W']) < 2e-8
        if stats[3]:
            assert all(passed for _, passed in gates), gates
        checks = actual[203]
        if len(checks):
            assert checks[-1, 0] == history[-1, 1]
            np.testing.assert_array_equal(checks[-1, 1:], [passed for _, passed in gates])
        else:
            assert not stats[3]


def outflow_case(shape, direction):
    from sjtu_tpmshx.models.grid_3d import _resolve_axis_map
    widths = [np.linspace(.7, 1.6, n) for n in shape]
    axis_map = _resolve_axis_map(dict(dir=direction), *shape,
                                *(w.sum() for w in widths), *widths)
    axes = [axis_map[key + "_real_axis"] for key in ("cross1", "stream", "cross2")]
    solver_shape = [shape[axis] for axis in axes]
    faces = []
    for component in range(3):
        dims = tuple(n + (component == d) for d, n in enumerate(solver_shape))
        i, j, k = np.indices(dims)
        faces.append(np.asarray(1. + component + .17*i + .31*j + .23*k, order="C"))
    i, j, k = np.indices(shape)
    coefficient = np.asarray(1. + .25*i + .5*j + .75*k, order="C")
    return widths, axes, faces, coefficient


def boundary_flux(face, coefficient, widths, axis, high):
    # Sum boundary fluxes independently of the native face iterator.
    import math
    terms = []
    for cell in np.ndindex(coefficient.shape):
        if cell[axis] != (coefficient.shape[axis]-1 if high else 0):
            continue
        point = list(cell)
        point[axis] = coefficient.shape[axis] if high else 0
        area = math.prod(widths[d][cell[d]] for d in range(3) if d != axis)
        terms.append(coefficient[cell] * face[tuple(point)] * area)
    return math.fsum(terms)


def check_outflow_balance(mapped, balanced, coefficient, widths, direction):
    axis, reverse = direction//2, bool(direction % 2)
    inlet = boundary_flux(mapped[axis], coefficient, widths, axis, reverse)
    outlet = boundary_flux(mapped[axis], coefficient, widths, axis, not reverse)
    scale = inlet/outlet
    assert np.isfinite(scale) and scale > 0. and abs(scale-1.) > 1e-3
    selection = [slice(None)]*3
    selection[axis] = 0 if reverse else -1
    expected = mapped[axis].copy()
    expected[tuple(selection)] *= scale
    np.testing.assert_allclose(balanced[axis], expected, rtol=4e-15, atol=2e-15)
    unchanged = np.ones(mapped[axis].shape, dtype=bool)
    unchanged[tuple(selection)] = False
    np.testing.assert_array_equal(balanced[axis][unchanged], mapped[axis][unchanged])
    for transverse in range(3):
        if transverse != axis:
            np.testing.assert_array_equal(balanced[transverse], mapped[transverse])
    after = boundary_flux(balanced[axis], coefficient, widths, axis, not reverse)
    assert after == pytest.approx(inlet, rel=4e-15, abs=2e-15)


@pytest.mark.parametrize("direction", range(6))
@pytest.mark.parametrize("shape", [(3, 4, 5), (1, 4, 1)])
def test_outflow_balance_changes_only_outlet(native, shape, direction):
    widths, axes, faces, coefficient = outflow_case(shape, direction)
    borrowed = [*widths, *faces, coefficient]
    saved = [a.copy() for a in borrowed]
    mapped, balanced = native.balance_outflow(shape, axes, direction, widths, faces, coefficient)
    check_outflow_balance(mapped, balanced, coefficient, widths, direction)
    for actual, before in zip(borrowed, saved):
        np.testing.assert_array_equal(actual, before)


@pytest.mark.parametrize("direction", range(6))
@pytest.mark.parametrize("guard", ["zero", "tiny", "opposite", "nonfinite"])
def test_outflow_balance_keeps_invalid_scale(native, direction, guard):
    shape = (3, 4, 5)
    widths, axes, faces, coefficient = outflow_case(shape, direction)
    if guard == "nonfinite":
        faces[1][:, 0, :] = np.inf
    else:
        faces[1][:, -1, :] = {"zero": 0., "tiny": 1e-16, "opposite": -1.}[guard]
    mapped, balanced = native.balance_outflow(shape, axes, direction, widths, faces, coefficient)
    for actual, before in zip(balanced, mapped):
        np.testing.assert_array_equal(actual, before)


def test_thermal_preparation_balances_owned_faces(native):
    cfg, p = prepared("water-water", counts=(3, 4, 5), variable_rho_cp=False,
                      force_cc_ltne=False, max_iter_simple=2)
    actual = native.run(cfg, p, audit_prepare=True)
    assert actual["code"] == 0, actual["error"]
    shape = tuple(p["N"+axis] for axis in "xyz")
    widths = [p["d"+axis] for axis in "xyz"]
    for side, name in enumerate("AB"):
        dims = [tuple(n + (axis == d) for d, n in enumerate(shape)) for axis in range(3)]
        mapped = [actual[129+40*side+d].reshape(dims[d]) for d in range(3)]
        balanced = [actual[17+3*side+d].reshape(dims[d]) for d in range(3)]
        coefficient = p["design"]["eps_"+name] * actual[7+side].reshape(shape)
        check_outflow_balance(mapped, balanced, coefficient, widths, cfg["fluid_"+name+"_cfg"]["dir"])


@pytest.mark.parametrize("pair", ["air-air", "air-water", "water-air", "air-sco2", "sco2-water"])
def test_full_prepared_outer(native, pair):
    cfg, p = prepared(pair)
    actual = native.run(cfg, p)
    audit_full(actual, cfg, p)


@pytest.mark.parametrize("conservative,force_cc", [(False, True), (False, False), (True, True)])
def test_temperature_routes(native, conservative, force_cc):
    cfg, p = prepared("air-air", conservative_ltne=conservative, force_cc_ltne=force_cc, variable_rho_cp=False)
    audit_full(native.run(cfg, p), cfg, p)


def test_cap_retains_thermal_and_later_flow(native):
    cfg, p = prepared("air-sco2")
    p["max_outer"] = 1
    actual = native.run(cfg, p)
    audit_full(actual, cfg, p)
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
    audit_full(native.run(cfg, p), cfg, p)


@pytest.mark.parametrize("pair", ["air-air", "air-sco2"])
def test_nz_one_delegates_original_2d_temperature(native, pair):
    cfg, p = prepared(pair, directions=(0, 3), counts=(4, 4, 1))
    audit_full(native.run(cfg, p), cfg, p)


def check_unheated_true_h_state(actual, cfg, p):
    assert actual['code'] == 0, actual['error']
    assert actual[202][8] == 2 and not actual[202][1]
    assert actual[200].shape[0] == p['max_outer']
    np.testing.assert_array_equal(actual[200][:, 1], np.ones(p['max_outer']))
    tin = [cfg['T_inA'], cfg['T_inB']]
    solid = cfg['T_s_init'] if cfg.get('T_s_init') is not None else .5*sum(tin)
    for field, value in enumerate([*tin, solid]):
        np.testing.assert_array_equal(actual[field], np.full(actual[field].shape, value))
    # Preparation and the EOS handoff still supply coefficients, mass faces and h.
    for field in [*range(5, 17), 23, 24, 25, 26]:
        assert actual[field].size and np.isfinite(actual[field]).all()


@pytest.mark.parametrize('nz', [1, 4])
@pytest.mark.parametrize('solid_seed', [None, 335.])
def test_true_h_cell_centered_keeps_temperature_before_eos(native, nz, solid_seed):
    cfg, p = prepared('air-sco2', directions=(0, 3), counts=(4, 4, nz),
        conservative_ltne=False, force_cc_ltne=True, T_s_init=solid_seed,
        ltne_enthalpy_outer=1, ltne_enthalpy_nsweep=0)
    p['max_outer'] = 2
    check_unheated_true_h_state(native.run(cfg, p), cfg, p)


@pytest.mark.parametrize("pair", ["air-air", "air-water"])
def test_outer_property_order(native, pair):
    cfg, p = prepared(pair)
    audit_full(native.run(cfg, p), cfg, p)


def test_sco2_a_local_pressure_property_switch(native):
    cfg, p = prepared("sco2-water")
    cfg["_environment"]["TPMSHX_SCO2_COMPRESSIBLE"] = "1"
    audit_full(native.run(cfg, p), cfg, p)


def test_no_b_solver_prescribed_temperature(native):
    cfg, p = prepared("air-air")
    cfg["fluid_B_cfg"] = None
    audit_full(native.run(cfg, p), cfg, p)


def test_refined_real_grid_and_existing_energy_acceleration(native, record_property):
    cfg, p = prepared('air-air', counts=(30, 30, 30), mesh='port_wall_refine')
    p['max_outer'] = 2
    assert tuple(p['N'+axis] for axis in 'xyz') == (30, 30, 30)
    assert p['ltne_max_iter'] == 20000
    actual = native.run(cfg, p)
    audit_full(actual, cfg, p)
    stats, history, checks = actual[202], actual[200], actual[203]
    assert stats[0] == 1 and not stats[1] and not stats[4]
    assert stats[2] == stats[3] == stats[5] == stats[7] == 1
    assert stats[9] == 1 and history.shape == (2, 16)
    np.testing.assert_array_equal(history[:, 3], [True, True])
    assert np.all((history[:, 1] > 0) & (history[:, 1] <= p['ltne_max_iter']))
    assert np.all(history[:, 1] % 250 == 0)
    assert np.all(np.diff(checks[:, 0]) > 0) and np.all(checks[:, 0] % 250 == 0)
    assert np.all((checks[:, 0] > 0) & (checks[:, 0] <= history[-1, 1]))
    assert np.all((checks[:, 1:] == 0) | (checks[:, 1:] == 1))
    np.testing.assert_array_equal(checks[-1, 1:], np.ones(6))
    for side in range(2):
        start = 24+10*side
        assert stats[start+2] and 0 < stats[start+3] <= 600
        assert not np.array_equal(actual[3+side], actual[124+40*side])
    record_property('native_thermal_iterations', history[:, 1].tolist())


@pytest.mark.parametrize("directions", [(4, 1), (5, 0)])
@pytest.mark.parametrize("red_black", [False, True])
@pytest.mark.parametrize("conservative", [True, False], ids=["conservative", "advective"])
def test_true_h_staggered_keeps_temperature_before_eos(native, directions, red_black, conservative):
    cfg, p = prepared('sco2-water', directions=directions, counts=(8, 6, 7),
        ltne_enthalpy_outer=1, ltne_enthalpy_nsweep=0,
        _native_rb_energy=red_black, conservative_ltne=conservative, force_cc_ltne=False,
        T_s_init=335.)
    p['max_outer'] = 2
    check_unheated_true_h_state(native.run(cfg, p), cfg, p)


def test_graded_direct_grid_and_existing_energy_acceleration(native):
    cfg, p = prepared("air-air", counts=(8, 8, 8), mesh="graded", port_wall_refine=True)
    p["max_outer"] = 2
    audit_full(native.run(cfg, p), cfg, p)


@pytest.mark.parametrize("mode", ["baseline", "norris_1a", "bhatti_shah_1b"])
def test_original_air_roughness_mode(native, mode):
    cfg, p = prepared("air-air")
    cfg["roughness_resolved"]["mode"] = mode
    audit_full(native.run(cfg, p), cfg, p)


def test_dispersion_and_user_solid_seed(native):
    cfg, p = prepared("air-water", disp_C_A=.1, disp_C_B=.06, T_s_init=335.)
    audit_full(native.run(cfg, p), cfg, p)


@pytest.mark.parametrize("counts,mesh", [((4, 4, 4), None), ((8, 8, 8), None), ((9, 8, 11), "graded"), ((30, 30, 30), "port_wall_refine")])
def test_coarse_bootstrap_preserves_physical_ports_and_fine_gate(native, counts, mesh):
    cfg, p = prepared("air-air", counts=counts, mesh=mesh, use_coarse_bootstrap=True, coarse_bootstrap_max_iter=30)
    cfg["max_iter_simple"] = 100
    p["max_outer"] = 1
    audit_full(native.run(cfg, p), cfg, p)


@pytest.mark.parametrize("pair", ["air-air", "water-air", "sco2-water"])
@pytest.mark.parametrize("cut", [0, 1, 2, 3])
def test_outer_boundary_resume_keeps_complete_trajectory(native, pair, cut):
    cfg, p = prepared(pair, counts=(3, 4, 2))
    p["max_outer"] = 3
    continuous = native.run(cfg, p)
    resumed = native.run(cfg, p, resume_cut=cut)
    assert resumed["code"] == continuous["code"] == 0, (resumed, continuous)
    for key in continuous:
        if isinstance(key, int):
            np.testing.assert_array_equal(resumed[key], continuous[key], err_msg=str(key))


@pytest.mark.parametrize("corruption", [1, 2, 3, 4])
def test_outer_boundary_resume_rejects_invalid_state(native, corruption):
    cfg, p = prepared(counts=(3, 4, 2))
    p["max_outer"] = 3
    result = native.run(cfg, p, resume_cut=1, invalid_resume=corruption)
    assert result["code"] == 1
    assert "continuation" in result["error"]

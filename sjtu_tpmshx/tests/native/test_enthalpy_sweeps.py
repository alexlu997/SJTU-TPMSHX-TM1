"""Same-algorithm native port qualification; no production dispatch changes.

Tolerances are fixed before port comparison, allowing LLVM fastmath roundoff:
rtol=2e-13; atol=2e-8 J/kg for h and 2e-11 K for Ts. Clips must match exactly.
They are not solver convergence tolerances or experimental accuracy claims.
"""
import ctypes
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.solvers import ltne_enthalpy_3d as reference


@pytest.fixture(scope="module")
def native_library(tmp_path_factory):
    compiler = shlex.split(os.environ.get("CXX", "c++"))
    if os.name != "posix" or not compiler or not shutil.which(compiler[0]):
        message = "native pilot requires a POSIX C++17 compiler (CXX)"
        if os.environ.get("TPMSHX_REQUIRE_CPP_TESTS") == "1":
            pytest.fail(message)
        pytest.skip(message)
    root = Path(__file__).resolve().parents[3]
    suffix = ".dylib" if sys.platform == "darwin" else ".so"
    output = tmp_path_factory.mktemp("cpp-enthalpy") / ("test_thermal" + suffix)
    subprocess.run(
        [*compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
         "-shared", "-fPIC", "-I", str(root / "native/include"),
         str(root / "native/src/enthalpy_sweeps.cpp"),
         str(Path(__file__).with_name("enthalpy_bridge.cpp")), "-o", str(output)],
        check=True, capture_output=True, text=True,
    )
    return ctypes.CDLL(str(output))


@pytest.fixture(scope="module")
def native(native_library):
    function = native_library.test_enthalpy_sweeps
    double_p = ctypes.POINTER(ctypes.c_double)
    function.argtypes = [ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(double_p),
                         ctypes.POINTER(ctypes.c_size_t), double_p, ctypes.c_size_t,
                         ctypes.POINTER(ctypes.c_uint64)]
    function.restype = ctypes.c_int

    def run(case, sweeps=5, omega=0.6):
        a, b = case["a"], case["b"]
        arrays = [*case["widths"], *case["state"], *a["arrays"], *b["arrays"], case["kss"]]
        assert all(x.dtype == np.float64 and x.flags.c_contiguous for x in arrays)
        pointers = (double_p * len(arrays))(*(x.ctypes.data_as(double_p) for x in arrays))
        sizes = (ctypes.c_size_t * len(arrays))(*(x.size for x in arrays))
        shape = (ctypes.c_size_t * 3)(*case["shape"])
        scalars = (ctypes.c_double * 7)(a["hin"], b["hin"], *a["bounds"], *b["bounds"], omega)
        clips = (ctypes.c_uint64 * 2)(99, 99)
        code = function(shape, pointers, sizes, scalars, sweeps, clips)
        return code, tuple(clips)

    return run


def case_data(shape=(4, 3, 2)):
    rng = np.random.default_rng(710321)
    widths = tuple(rng.uniform(0.001, 0.008, n) for n in shape)
    fluids = []
    state = []
    for _ in range(2):
        cp = rng.uniform(700., 5000., shape)
        t = rng.uniform(290., 400., shape)
        hs = rng.uniform(2e5, 5e5, shape)
        fields = [rng.uniform(0., 0.3, shape) / cp, cp, t, hs,
                  rng.uniform(0., 1e6, shape)]
        for axis in range(3):
            face_shape = list(shape)
            face_shape[axis] += 1
            flow = rng.uniform(-0.002, 0.002, face_shape)
            flow.flat[::4] = 0.  # partial patches / impermeable faces
            fields.append(flow)
        fluids.append(dict(arrays=fields, hin=3e5, bounds=(-1e7, 1e7)))
        state.append(hs + rng.uniform(-5000., 5000., shape))
    state.append(rng.uniform(300., 380., shape))
    return dict(shape=shape, widths=widths, a=fluids[0], b=fluids[1], state=state,
                kss=rng.uniform(0., 10., shape))


def python_sweeps(case, sweeps=5, omega=0.6):
    a, b = case["a"], case["b"]
    aa, bb = a["arrays"], b["arrays"]
    state = [x.copy() for x in case["state"]]
    clips = np.full(2, 99, dtype=np.int64)
    reference._gs_enthalpy_sweeps_3d(
        *state, aa[0], bb[0], aa[1], bb[1], aa[2], bb[2], aa[3], bb[3],
        *aa[5:], *bb[5:], aa[4], bb[4], case["kss"], *case["widths"],
        a["hin"], b["hin"], sweeps, omega, *a["bounds"], *b["bounds"], clips,
    )
    return state, clips


@pytest.mark.parametrize("shape", [(4, 3, 2), (5, 2, 1), (1, 3, 4), (2, 1, 3), (1, 1, 1)])
@pytest.mark.parametrize("sweeps", [0, 1, 7])
def test_same_signed_flow_and_fourier_updates(native, shape, sweeps):
    case = case_data(shape)
    expected, expected_clips = python_sweeps(case, sweeps)
    frozen = [x.copy() for f in (case["a"], case["b"]) for x in f["arrays"]]
    code, clips = native(case, sweeps)
    assert code == 0
    np.testing.assert_array_equal(clips, expected_clips)
    for actual, target, atol in zip(case["state"], expected, (2e-8, 2e-8, 2e-11)):
        np.testing.assert_allclose(actual, target, rtol=2e-13, atol=atol)
    for actual, target in zip([x for f in (case["a"], case["b"]) for x in f["arrays"]], frozen):
        np.testing.assert_array_equal(actual, target)


@pytest.mark.parametrize("direction", range(6))
def test_all_face_directions_transport_inlet_enthalpy(native, direction):
    case = case_data((3, 4, 2))
    for fluid, h in zip((case["a"], case["b"]), case["state"]):
        aa = fluid["arrays"]
        aa[0].fill(0.)
        aa[4].fill(0.)
        aa[5:] = list(reference._uniform_face_mass_flux(case["shape"], .01, direction))
        h.fill(fluid["hin"] + 5000.)
    code, clips = native(case, sweeps=5, omega=1.)
    assert code == 0 and clips == (0, 0)
    for h in case["state"][:2]:
        np.testing.assert_allclose(h, 3e5, rtol=0., atol=2e-8)


def test_isothermal_pressure_gradient_has_no_false_conduction(native, native_audit):
    case = case_data((2, 1, 1))
    temperature = np.full(case["shape"], 400.)
    pressure = np.array([9e6, 8.99e6]).reshape(case["shape"])
    initial = reference._prop_field("H", temperature, pressure, "sco2")
    cp, conductivity = reference._prop_field(("C", "L"), temperature, pressure, "sco2")
    assert abs(initial[0, 0, 0] - initial[1, 0, 0]) > 50.
    for fluid, h in zip((case["a"], case["b"]), case["state"]):
        fluid["arrays"][:5] = [.337265 * conductivity / cp, cp.copy(), temperature.copy(),
                               initial.copy(), np.zeros_like(initial)]
        for flux in fluid["arrays"][5:]:
            flux.fill(0.)
        h[:] = initial
    case["state"][2][:] = temperature
    code, clips = native(case, sweeps=4, omega=1.)
    assert code == 0 and clips == (0, 0)
    for h in case["state"][:2]:
        np.testing.assert_allclose(h, initial, rtol=0., atol=2e-8)
    np.testing.assert_allclose(case["state"][2], temperature, rtol=0., atol=2e-11)
    code, residuals, metrics = native_audit(
        case, [temperature, temperature], [.337265 * conductivity] * 2)
    assert code == 0
    for r in residuals:
        np.testing.assert_allclose(r, 0., rtol=0., atol=1e-9)
    np.testing.assert_allclose(metrics[[0, 1, 2, 3, 5, 6, 7, 8, 9, 10]], 0., rtol=0., atol=1e-9)


def test_clip_counts_match_actual_updates(native):
    case = case_data()
    for fluid in (case["a"], case["b"]):
        fluid["bounds"] = (290000., 310000.)
    expected, expected_clips = python_sweeps(case)
    code, clips = native(case)
    assert code == 0 and all(x > 0 for x in clips)
    np.testing.assert_array_equal(clips, expected_clips)
    for h, target in zip(case["state"][:2], expected[:2]):
        np.testing.assert_allclose(h, target, rtol=2e-13, atol=2e-8)
        assert np.all((h >= 290000.) & (h <= 310000.))


def test_zero_diagonal_preserves_state(native):
    case = case_data((1, 1, 1))
    for fluid in (case["a"], case["b"]):
        for i in (0, 4, 5, 6, 7):
            fluid["arrays"][i].fill(0.)
    case["kss"].fill(0.)
    initial = [x.copy() for x in case["state"]]
    code, clips = native(case)
    assert code == 0 and clips == (0, 0)
    for actual, target in zip(case["state"], initial):
        np.testing.assert_array_equal(actual, target)


def test_fixed_solid_exponential_solution_and_energy(native):
    errors = []
    for n in (16, 32, 64):
        case = case_data((n, 1, 1))
        case["widths"] = (np.full(n, .1 / n), np.array([.1]), np.array([.1]))
        case["state"][2].fill(300.)
        for fluid, h in zip((case["a"], case["b"]), case["state"]):
            aa = fluid["arrays"]
            aa[0].fill(0.)
            aa[1].fill(1000.)
            aa[2].fill(400.)
            aa[3].fill(400000.)
            aa[4].fill(20000.)
            aa[5:] = list(reference._uniform_face_mass_flux(case["shape"], .01, 0))
            fluid["hin"] = 400000.
            h.fill(400000.)
        code, clips = native(case, sweeps=1, omega=1.)
        assert code == 0 and clips == (0, 0)
        h = case["state"][0]
        expected_outlet = 300. + 100. * np.exp(-2.)
        errors.append(abs(h[-1, 0, 0] / 1000. - expected_outlet))
        source = np.sum(20000. * (h / 1000. - 300.)) * .1 / n * .01
        assert source == pytest.approx(.01 * (400000. - h[-1, 0, 0]), rel=1e-12)
    assert 1.8 < errors[0] / errors[1] < 2.1
    assert 1.8 < errors[1] / errors[2] < 2.1


@pytest.mark.parametrize("invalid", ["length", "cp", "width", "nan", "omega"])
def test_invalid_input_rejected_before_state_mutation(native, invalid):
    case = case_data()
    initial = [x.copy() for x in case["state"]]
    if invalid == "length":
        case["a"]["arrays"][5] = np.zeros(1)
    elif invalid == "cp":
        case["b"]["arrays"][1].flat[0] = 0.
    elif invalid == "width":
        case["widths"][0][0] = -1.
    elif invalid == "nan":
        case["a"]["arrays"][6].flat[0] = np.nan
    code, _ = native(case, omega=2. if invalid == "omega" else .6)
    assert code == 1
    for actual, target in zip(case["state"], initial):
        np.testing.assert_array_equal(actual, target)


# Fixed before the energy port comparison: 2e-12 relative / 1e-9 W per cell,
# 1e-8 W for reductions, 1e-12 for ratios. No production gate is changed.
@pytest.fixture(scope="module")
def native_audit(native_library):
    function = native_library.test_thermal_energy_audit
    double_p = ctypes.POINTER(ctypes.c_double)
    function.argtypes = [ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(double_p),
                         ctypes.POINTER(ctypes.c_size_t), double_p, double_p]
    function.restype = ctypes.c_int

    def run(case, temperature=None, conductivity=None):
        a, b = case["a"], case["b"]
        fields = (a["arrays"], b["arrays"])
        if temperature is None:
            temperature = [f[2] + (h - f[3]) / f[1]
                           for f, h in zip(fields, case["state"][:2])]
        if conductivity is None:
            conductivity = [f[0] * f[1] for f in fields]
        residuals = [np.full(case["shape"], 123.) for _ in range(3)]
        arrays = [*case["widths"], *case["state"], *temperature, *conductivity,
                  fields[0][4], fields[1][4], case["kss"],
                  *fields[0][5:], *fields[1][5:], *residuals]
        assert all(x.dtype == np.float64 and x.flags.c_contiguous for x in arrays)
        pointers = (double_p * len(arrays))(*(x.ctypes.data_as(double_p) for x in arrays))
        sizes = (ctypes.c_size_t * len(arrays))(*(x.size for x in arrays))
        shape = (ctypes.c_size_t * 3)(*case["shape"])
        hin = (ctypes.c_double * 2)(a["hin"], b["hin"])
        metrics = np.full(11, np.nan)
        code = function(shape, pointers, sizes, hin, metrics.ctypes.data_as(double_p))
        return code, residuals, metrics

    return run


def python_audit(case, temperature=None, conductivity=None):
    fluids = (case["a"], case["b"])
    fields = [f["arrays"] for f in fluids]
    ts = case["state"][2]
    if temperature is None:
        temperature = [f[2] + (h - f[3]) / f[1]
                       for f, h in zip(fields, case["state"][:2])]
    if conductivity is None:
        conductivity = [f[0] * f[1] for f in fields]
    residuals = [reference._fluid_energy_residual(h, t, ts, f["arrays"][4], k,
                  f["arrays"][5:], f["hin"], *case["widths"])
                 for h, t, k, f in zip(case["state"][:2], temperature, conductivity, fluids)]
    q = [reference._boundary_enthalpy_duty(h, f["hin"], f["arrays"][5:])
         for h, f in zip(case["state"][:2], fluids)]
    coupled = reference._coupled_energy_balance(*temperature, ts, fields[0][4], fields[1][4],
                                               case["kss"], *case["widths"], *q)
    volume = np.prod(np.meshgrid(*case["widths"], indexing="ij"), axis=0)
    solid = ((fields[0][4] * (temperature[0] - ts) + fields[1][4] * (temperature[1] - ts))
             * volume + reference._conduction_source(ts, case["kss"], *case["widths"]))
    fluid_abs = [np.abs(r).sum() for r in residuals]
    metrics = [*q, coupled["net"], coupled["solid_abs_sum"], coupled["denominator"],
               coupled["ratio"], *fluid_abs, *(np.abs(r).max() for r in residuals),
               max(*fluid_abs, coupled["solid_abs_sum"], abs(coupled["net"])) / coupled["denominator"]]
    return [*residuals, solid], np.array(metrics)


@pytest.mark.parametrize("shape", [(4, 3, 2), (5, 2, 1), (1, 3, 4), (2, 1, 3), (1, 1, 1)])
def test_energy_audit_matches_actual_state_and_conserves(native_audit, shape):
    case = case_data(shape)
    expected, metrics = python_audit(case)
    frozen = [x.copy() for x in case["state"]]
    code, actual, measured = native_audit(case)
    assert code == 0
    for r, target in zip(actual, expected):
        np.testing.assert_allclose(r, target, rtol=2e-12, atol=1e-9)
    np.testing.assert_allclose(measured, metrics, rtol=2e-12, atol=1e-8)
    np.testing.assert_allclose(measured[[5, 10]], metrics[[5, 10]], rtol=2e-12, atol=1e-12)
    # Internal Fourier/advective faces and fluid-solid exchange must cancel.
    assert sum(r.sum() for r in actual) == pytest.approx(measured[2], rel=2e-12, abs=1e-9)
    for target, state in zip(frozen, case["state"]):
        np.testing.assert_array_equal(state, target)


@pytest.mark.parametrize("direction", range(6))
def test_energy_audit_signed_boundary_duty(native_audit, direction):
    case = case_data((3, 4, 2))
    for fluid, h in zip((case["a"], case["b"]), case["state"]):
        fluid["arrays"][0].fill(0.)
        fluid["arrays"][4].fill(0.)
        fluid["arrays"][5:] = list(reference._uniform_face_mass_flux(case["shape"], .01, direction))
        h.fill(fluid["hin"] - 5000.)
    case["kss"].fill(0.)
    code, residuals, metrics = native_audit(case)
    assert code == 0
    np.testing.assert_allclose(metrics[:3], [50., 50., 100.], rtol=0., atol=1e-9)
    np.testing.assert_allclose([r.sum() for r in residuals], [50., 50., 0.], rtol=0., atol=1e-9)


def test_energy_audit_cannot_accept_balanced_but_unconverged_cells(native_audit):
    case = case_data((2, 1, 1))
    for fluid, h in zip((case["a"], case["b"]), case["state"]):
        f = fluid["arrays"]
        f[4].fill(0.)
        for flow in f[5:]:
            flow.fill(0.)
        h.fill(fluid["hin"])
    case["kss"].fill(0.)
    temperatures = [np.array([300., 400.]).reshape(2, 1, 1) for _ in range(2)]
    conductivity = [np.ones((2, 1, 1)) for _ in range(2)]
    code, residuals, metrics = native_audit(case, temperatures, conductivity)
    assert code == 0
    assert metrics[2] == 0. and metrics[5] == 0.  # perfect global/coupled balance
    assert metrics[10] > 0.  # but finite local equation errors
    for r in residuals[:2]:
        assert r[0, 0, 0] > 0. and r[1, 0, 0] < 0.
        assert r.sum() == 0.


def test_energy_audit_independent_one_cell_exchange(native_audit):
    case = case_data((1, 1, 1))
    case["widths"] = tuple(np.array([1.]) for _ in range(3))
    case["state"][2].fill(350.)
    for fluid, h, tout, hin, hout, hv in zip(
            (case["a"], case["b"]), case["state"], (380., 320.),
            (400000., 300000.), (380000., 320000.), (2./3., 2./3.)):
        f = fluid["arrays"]
        f[0].fill(0.)
        f[1].fill(1000.)
        f[2].fill(tout)
        f[3].fill(hout)
        f[4].fill(hv)
        f[5:] = list(reference._uniform_face_mass_flux(case["shape"], .001, 0))
        fluid["hin"] = hin
        h.fill(hout)
    code, residuals, metrics = native_audit(case)
    assert code == 0
    np.testing.assert_allclose(metrics[:3], [20., -20., 0.], rtol=0., atol=1e-10)
    for r in residuals:
        np.testing.assert_allclose(r, 0., rtol=0., atol=1e-10)
    assert metrics[5] < 1e-12 and metrics[10] < 1e-12


@pytest.mark.parametrize("invalid", ["nan", "negative_k", "length", "overflow"])
def test_energy_audit_rejects_invalid_or_nonfinite_budget(native_audit, invalid):
    case = case_data((2, 1, 1))
    if invalid == "nan":
        case["state"][2].flat[0] = np.nan
    elif invalid == "negative_k":
        case["a"]["arrays"][0].flat[0] = -1.
    elif invalid == "length":
        case["b"]["arrays"][5] = np.zeros(1)
    else:
        case["a"]["arrays"][5].fill(1e308)
    code, residuals, metrics = native_audit(case)
    assert code == (2 if invalid == "overflow" else 1)
    if invalid != "overflow":
        for r in residuals:
            np.testing.assert_array_equal(r, 123.)
    assert np.isnan(metrics).all()


@pytest.mark.parametrize("overflow", ["exchange", "solid_conductivity", "fluid_update"])
def test_sweeps_reject_finite_input_arithmetic_overflow(native, overflow):
    shape = (2, 1, 1) if overflow == "solid_conductivity" else (1, 1, 1)
    case = case_data(shape)
    case["widths"] = tuple(np.full(n, 2.) for n in shape)
    case["kss"].fill(0.)
    case["state"][2].fill(350.)
    for fluid, h in zip((case["a"], case["b"]), case["state"]):
        f = fluid["arrays"]
        f[0].fill(0.)
        f[1].fill(1000.)
        f[2].fill(300.)
        f[3].fill(300000.)
        f[4].fill(0.)
        for flow in f[5:]:
            flow.fill(0.)
        h.fill(300000.)
    if overflow == "exchange":
        for fluid in (case["a"], case["b"]):
            fluid["arrays"][4].fill(1e308)  # hv * volume overflows
    elif overflow == "solid_conductivity":
        case["kss"].fill(1e308)  # harmonic conductivity produces inf/inf
    else:
        case["a"]["hin"] = 1e308
        case["a"]["arrays"][5][:, 0, 0] = [1., 1e-29]  # finite rhs/ap overflows
    code, clips = native(case, sweeps=1, omega=1.)
    assert code == 2  # specifically std::domain_error, not a successful clipped state
    assert clips == (99, 99)  # no success result returned; state is unusable

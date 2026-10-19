"""Shared energy audits retain independent actual-state and balance checks."""

from sjtu_tpmshx.tests.native.enthalpy_fv_audit import uniform_face_mass_flux, energy
import ctypes
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import numpy as np
import pytest



@pytest.fixture(scope="module")
def native_library(tmp_path_factory):
    compiler = shlex.split(os.environ.get("CXX", "cl" if os.name == "nt" else "c++"))
    if os.name not in ("posix", "nt") or not compiler or not shutil.which(compiler[0]):
        message = "native tests require a C++17 compiler (CXX; MSVC cl on Windows)"
        if os.environ.get("TPMSHX_REQUIRE_CPP_TESTS") == "1":
            pytest.fail(message)
        pytest.skip(message)
    root = Path(__file__).resolve().parents[3]
    build = tmp_path_factory.mktemp("cpp-enthalpy")
    suffix = ".dll" if os.name == "nt" else (".dylib" if sys.platform == "darwin" else ".so")
    output = build / ("test_thermal" + suffix)
    sources = [str(root / "native/src/enthalpy_sweeps.cpp"),
               str(Path(__file__).with_name("enthalpy_bridge.cpp"))]
    if os.name == "nt":
        arguments = ["/nologo", "/std:c++17", "/O2", "/W4", "/WX", "/EHsc", "/MD",
                     "/LD", "/DTPMSHX_THERMAL_BUILD_SHARED", "/I" + str(root / "native/include"),
                     *sources, "/Fe" + str(output), "/link", "/IMPLIB:" + str(build / "test_thermal.lib")]
    else:
        link_flag = "-dynamiclib" if sys.platform == "darwin" else "-shared"
        arguments = ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
                     link_flag, "-fPIC", "-I", str(root / "native/include"), *sources, "-o", str(output)]
    subprocess.run(
        [*compiler, *arguments], cwd=build,
        check=True, capture_output=True, text=True,
    )
    return ctypes.CDLL(str(output))








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


def independent_audit(case, temperature=None, conductivity=None):
    fluids = (case['a'], case['b'])
    fields = [f['arrays'] for f in fluids]
    if temperature is None:
        temperature = [f[2] + (h-f[3])/f[1] for f,h in zip(fields,case['state'])]
    if conductivity is None:
        conductivity = [f[0]*f[1] for f in fields]
    return energy(case['widths'], case['state'][:2], temperature, case['state'][2],
        conductivity, [f[4] for f in fields], case['kss'], [f[5:] for f in fields],
        [f['hin'] for f in fluids])


@pytest.mark.parametrize("shape", [(4, 3, 2), (5, 2, 1), (1, 3, 4), (2, 1, 3), (1, 1, 1)])
def test_energy_audit_matches_actual_state_and_conserves(native_audit, shape):
    case = case_data(shape)
    expected, metrics = independent_audit(case)
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
        fluid["arrays"][5:] = list(uniform_face_mass_flux(case["shape"], .01, direction))
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
        f[5:] = list(uniform_face_mass_flux(case["shape"], .001, 0))
        fluid["hin"] = hin
        h.fill(hout)
    code, residuals, metrics = native_audit(case)
    assert code == 0
    np.testing.assert_allclose(metrics[:3], [20., -20., 0.], rtol=0., atol=1e-10)
    for r in residuals:
        np.testing.assert_allclose(r, 0., rtol=0., atol=1e-10)
    assert metrics[5] < 1e-12 and metrics[10] < 1e-12


def test_energy_audit_keeps_actual_h_independent_of_temperature(native_audit):
    case = case_data((2, 1, 1))
    case["widths"] = tuple(np.ones(n) for n in case["shape"])
    case["state"][2].fill(320.)
    case["kss"].fill(0.)
    for fluid, h in zip((case["a"], case["b"]), case["state"]):
        fluid["arrays"][0].fill(0.)
        fluid["arrays"][4].fill(2.)
        fluid["arrays"][5:] = list(uniform_face_mass_flux(case["shape"], .125, 0))
        fluid["hin"] = 2.**40 + 16.
        h.flat[:] = [2.**40, 2.**40 + 8.]
    temperatures = [np.array(values).reshape(case["shape"])
                    for values in ([310., 315.], [330., 325.])]
    code, residuals, metrics = native_audit(case, temperatures)
    assert code == 0
    # Exact m*h adds [2, -1] W to each independently supplied exchange field.
    np.testing.assert_array_equal(residuals[0].ravel(), [22., 9.])
    np.testing.assert_array_equal(residuals[1].ravel(), [-18., -11.])
    np.testing.assert_array_equal(residuals[2], 0.)
    np.testing.assert_array_equal(metrics[:3], [1., 1., 2.])


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





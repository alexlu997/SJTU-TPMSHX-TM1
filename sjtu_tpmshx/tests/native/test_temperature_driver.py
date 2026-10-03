"""Fixed-coefficient native temperature driver qualification.

Tolerances fixed before comparison: 2D rtol=2e-12, atol=2e-10 K;
3D (Numba fastmath reference) rtol=2e-11, atol=2e-9 K. These allow
floating-point operation ordering, not different equations or stopping gates.
Budgets, convergence decisions and frozen-B values must agree exactly.
No production solver binding is replaced by this test-only bridge.
"""

import ctypes
import importlib
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import numpy as np
import pytest

from sjtu_tpmshx.solvers import ltne_energy, ltne_energy_3d


@pytest.fixture(scope="module")
def temperature_native(tmp_path_factory):
    compiler = shlex.split(os.environ.get("CXX", "cl" if os.name == "nt" else "c++"))
    if os.name not in ("posix", "nt") or not compiler or not shutil.which(compiler[0]):
        message = "native temperature tests require a C++17 compiler"
        if os.environ.get("TPMSHX_REQUIRE_CPP_TESTS") == "1":
            pytest.fail(message)
        pytest.skip(message)
    root = Path(__file__).resolve().parents[3]
    build = tmp_path_factory.mktemp("cpp-temperature")
    suffix = ".dll" if os.name == "nt" else (".dylib" if sys.platform == "darwin" else ".so")
    library = build / ("temperature_test" + suffix)
    sources = [str(root / "native/src/temperature_driver.cpp"),
               str(Path(__file__).with_name("temperature_bridge.cpp"))]
    if os.name == "nt":
        flags = ["/nologo", "/std:c++17", "/O2", "/W4", "/WX", "/EHsc", "/MD", "/LD",
                 "/DTPMSHX_THERMAL_BUILD_SHARED", "/I" + str(root / "native/include"),
                 *sources, "/Fe" + str(library), "/link",
                 "/IMPLIB:" + str(build / "temperature_test.lib")]
    else:
        flags = ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-fPIC",
                 "-dynamiclib" if sys.platform == "darwin" else "-shared",
                 "-I", str(root / "native/include"), *sources, "-o", str(library)]
    subprocess.run([*compiler, *flags], cwd=build, check=True, capture_output=True, text=True)
    lib = ctypes.CDLL(str(library))
    function = lib.test_temperature_driver
    size_p = ctypes.POINTER(ctypes.c_size_t)
    double_p = ctypes.POINTER(ctypes.c_double)
    function.argtypes = [size_p, ctypes.POINTER(double_p), size_p, size_p, double_p,
                         size_p, double_p, ctypes.POINTER(ctypes.c_char), ctypes.c_size_t]
    function.restype = ctypes.c_int

    def run(case, *, mode=None, cancel_at=0, bad_size=None):
        arrays = [*case["widths"], *case["state"], *case["a"], *case["b"],
                  case["ks"], case["prescribed"]]
        assert len(arrays) == 28
        assert all(a.dtype == np.float64 and a.flags.c_contiguous for a in arrays)
        pointers = (double_p * len(arrays))(*(a.ctypes.data_as(double_p) for a in arrays))
        sizes = (ctypes.c_size_t * len(arrays))(*(a.size for a in arrays))
        if bad_size is not None:
            sizes[bad_size] = max(0, sizes[bad_size] - 1)
        shape = (ctypes.c_size_t * 3)(*case["shape"])
        config = (ctypes.c_size_t * 9)(
            (0 if case["shape"][2] == 1 else 1) if mode is None else mode,
            case["maxit"], case["chunk"], case["warm"], case["sou_b"],
            *case["directions"], cancel_at, case.get("rb", False))
        values = (ctypes.c_double * 6)(*case["tin"], case["qtol"], *case["alpha"])
        status = (ctypes.c_size_t * 5)()
        metrics = (ctypes.c_double * 2)()
        error = ctypes.create_string_buffer(256)
        code = function(shape, pointers, sizes, config, values, status, metrics, error, len(error))
        return code, tuple(status), np.array(metrics), error.value.decode()

    return run


def temperature_case(shape=(5, 4, 1), directions=(0, 2), *, sweeps=19, chunk=5):
    rng = np.random.default_rng(821731)
    width = tuple(np.ascontiguousarray(rng.uniform(.01, .04, count)) for count in shape)
    fluids = []
    for side, direction in enumerate(directions):
        fields = [rng.uniform(0., .3, shape), rng.uniform(1000., 10000., shape),
                  rng.uniform(.2, .4, shape), rng.uniform(1000., 5000., shape)]
        velocities = [rng.uniform(-.3, .3, shape) for _ in range(3)]
        axis = direction // 2
        velocities[axis] += 1. if direction % 2 == 0 else -1.
        face_shape = tuple(shape[i] for i in range(3) if i != axis)
        profile = rng.uniform(385., 410., face_shape) if side == 0 else rng.uniform(295., 325., face_shape)
        opening = rng.uniform(.2, 1., face_shape)
        opening.flat[::3] = 0.
        opening.flat[-1] = 1.
        # Deliberately separate the physical inlet capacity from interior rho_cp.
        flux = rng.uniform(-.1, .8, face_shape)
        fluids.append([*fields, *velocities, profile, opening, flux])
    return dict(shape=shape, widths=width, a=fluids[0], b=fluids[1],
                state=[rng.uniform(320., 380., shape) for _ in range(3)],
                ks=rng.uniform(.5, 5., shape), prescribed=np.empty(0),
                directions=directions, tin=(400., 300.), maxit=sweeps, chunk=chunk,
                qtol=1e-4, warm=True, sou_b=shape[2] != 1,
                alpha=(.7, 1., 1.) if shape[2] == 1 else (.3, .5, .6))


def python_temperature(case):
    shape = case["shape"]
    aa, bb = case["a"], case["b"]
    kwargs = dict(max_iter=case["maxit"], conv_chunk=case["chunk"], q_rel_tol=case["qtol"],
                  return_info=True, dir_A=case["directions"][0], dir_B=case["directions"][1])
    for side, fields in (("A", aa), ("B", bb)):
        for key, index in (("T_in" + side + "_profile", 7),
                           ("inlet_mask_" + side, 8), ("inlet_flux_" + side, 9)):
            kwargs[key] = fields[index] if fields[index].size else None
    if case["warm"]:
        kwargs.update(zip(("Ta_init", "Tb_init", "Ts_init"), case["state"]))
    if case["prescribed"].size:
        kwargs["Tb_prescribed"] = case["prescribed"]
    common = (*case["tin"], aa[0], bb[0], case["ks"], aa[1], bb[1],
              aa[3], bb[3], aa[2] + bb[2])
    kwargs.update(eps_A=aa[2], eps_B=bb[2], dx_arr=case["widths"][0], dy_arr=case["widths"][1])
    if shape[2] == 1:
        def squeeze(x):
            return x[..., 0] if isinstance(x, np.ndarray) and x.ndim > 1 and x.shape[-1] == 1 else x
        common = tuple(squeeze(x) for x in common)
        kwargs = {k: squeeze(v) for k, v in kwargs.items()}
        result = ltne_energy.solve_full_domain(
            *[w.sum() for w in case["widths"][:2]], *shape[:2], *common,
            *(squeeze(x) for x in (aa[4], aa[5], bb[4], bb[5])),
            use_sou_B=case["sou_b"], **kwargs)
        return (*[x[..., None] for x in result[:3]], result[3])
    return ltne_energy_3d.solve_full_domain_3d(
        *[w.sum() for w in case["widths"]], *shape, *common,
        *aa[4:7], *bb[4:7], dz_arr=case["widths"][2],
        alpha_T_fA=case["alpha"][0], alpha_T_s=case["alpha"][1], alpha_T_fB=case["alpha"][2],
        **kwargs)


def assert_equivalent(case, native, expected=None):
    expected = python_temperature(case) if expected is None else expected
    code, status, metrics, error = native(case)
    assert code == 0, error
    assert status[0] == (0 if expected[3]["converged"] else 1)
    assert status[1] == expected[3]["iterations"]
    rtol, atol = (2e-12, 2e-10) if case["shape"][2] == 1 else (2e-11, 2e-9)
    for actual, target in zip(case["state"], expected[:3]):
        np.testing.assert_allclose(actual, target, rtol=rtol, atol=atol)
    assert metrics[0] == pytest.approx(expected[3]["residual"], rel=rtol, abs=atol)
    volume = case["widths"][0][:, None, None] * case["widths"][1][None, :, None]
    if case["shape"][2] > 1:
        volume = volume * case["widths"][2][None, None, :]
    q = float(np.sum(case["b"][1] * (expected[2] - expected[1]) * volume))
    if status[1]:
        assert metrics[1] == pytest.approx(q, rel=rtol, abs=1e-8)
    else:
        assert np.isnan(metrics[1])
    return status


@pytest.mark.parametrize("directions", [(0, 2), (1, 3), (2, 1), (3, 0)])
@pytest.mark.parametrize("sou_b", [False, True])
@pytest.mark.parametrize("sweeps", [1, 19])
@pytest.mark.parametrize("rb", [False, True])
def test_2d_variable_fields_nonuniform_grid_and_partial_inlets(temperature_native, monkeypatch, directions, sou_b, sweeps, rb):
    case = temperature_case(directions=directions, sweeps=sweeps)
    case["sou_b"] = sou_b
    case["rb"] = rb
    monkeypatch.setattr(ltne_energy, "_RB_ENERGY_2D", rb)
    monkeypatch.setattr(ltne_energy, "_RB_ENERGY_2D_GATE", 0)
    assert_equivalent(case, temperature_native)


@pytest.mark.parametrize("shape", [(1, 1, 1), (1, 4, 1), (4, 1, 1), (5, 4, 1)])
@pytest.mark.parametrize("warm", [False, True])
@pytest.mark.parametrize("frozen", [False, True])
def test_2d_rb_thin_axes_cold_warm_and_frozen_b(temperature_native, monkeypatch, shape, warm, frozen):
    case = temperature_case(shape, (3, 1), sweeps=23)
    case.update(rb=True, warm=warm, sou_b=True)
    if frozen:
        case["prescribed"] = np.linspace(301, 329, np.prod(shape)).reshape(shape)
    monkeypatch.setattr(ltne_energy, "_RB_ENERGY_2D", True)
    monkeypatch.setattr(ltne_energy, "_RB_ENERGY_2D_GATE", 0)
    assert_equivalent(case, temperature_native)
    if frozen: np.testing.assert_array_equal(case["state"][1], case["prescribed"])


def test_3d_cc_rb_is_rejected_before_state_write(temperature_native):
    case = temperature_case((4, 3, 2))
    case["rb"] = True
    before = [x.copy() for x in case["state"]]
    code, _, _, error = temperature_native(case)
    assert code == 1 and "RB" in error
    for actual, expected in zip(case["state"], before): np.testing.assert_array_equal(actual, expected)


@pytest.mark.parametrize("direction", range(6))
def test_3d_six_directions_and_separate_relaxation(temperature_native, direction):
    case = temperature_case((4, 3, 2), (direction, (direction + 1) % 6))
    assert_equivalent(case, temperature_native)


@pytest.mark.parametrize("shape", [(1, 1, 1), (1, 4, 1), (4, 1, 1), (1, 3, 2), (4, 1, 2)])
@pytest.mark.parametrize("warm", [False, True])
def test_cold_warm_starts_and_degenerate_axes(temperature_native, shape, warm):
    case = temperature_case(shape)
    case["warm"] = warm
    for f in (case["a"], case["b"]):
        f[7:] = [np.empty(0), np.empty(0), np.empty(0)]
    assert_equivalent(case, temperature_native)


@pytest.mark.parametrize("shape", [(5, 4, 1), (5, 2, 3)])
def test_prescribed_b_remains_exact_while_a_and_solid_solve(temperature_native, shape):
    case = temperature_case(shape, sweeps=80, chunk=10)
    prescribed = np.linspace(301., 341., np.prod(shape)).reshape(shape)
    case["prescribed"] = prescribed.copy()
    initial_a, initial_s = case["state"][0].copy(), case["state"][2].copy()
    assert_equivalent(case, temperature_native)
    np.testing.assert_array_equal(case["state"][1], prescribed)
    assert np.max(abs(case["state"][0] - initial_a)) > 1.
    assert np.max(abs(case["state"][2] - initial_s)) > 1.


@pytest.mark.parametrize("shape", [(3, 2, 1), (3, 1, 2)])
@pytest.mark.parametrize("maxit", [0, 1, 7, 20])
def test_equilibrium_still_needs_two_chunks_and_charges_full_budget(temperature_native, shape, maxit):
    case = temperature_case(shape, sweeps=maxit, chunk=5)
    case["tin"] = (330., 330.)
    case["warm"] = False
    for f in (case["a"], case["b"]):
        f[7:] = [np.empty(0), np.empty(0), np.empty(0)]
    status = assert_equivalent(case, temperature_native)
    assert status[1] == min(maxit, 10)
    assert status[0] == (0 if maxit > 5 else 1)


@pytest.mark.parametrize("cancel_at,expected_iterations", [(1, 0), (2, 5), (3, 5)])
def test_cancel_before_or_after_chunk_reports_no_convergence(temperature_native, cancel_at, expected_iterations):
    case = temperature_case(sweeps=19, chunk=5)
    expected_case = temperature_case(sweeps=expected_iterations, chunk=5)
    expected = python_temperature(expected_case)
    code, status, metrics, error = temperature_native(case, cancel_at=cancel_at)
    assert code == 0, error
    assert status[0] == 2 and status[1] == expected_iterations
    assert status[2] == cancel_at
    assert status[3] == int(expected_iterations != 0)
    assert np.isnan(metrics[1])
    for actual, target in zip(case["state"], expected[:3]):
        np.testing.assert_allclose(actual, target, rtol=2e-12, atol=2e-10)


@pytest.mark.parametrize("bad", ["scheme", "size", "nan", "width", "chunk", "qtol", "alpha", "direction", "opening", "alias"])
def test_invalid_inputs_fail_before_any_state_write(temperature_native, bad):
    case = temperature_case()
    mode, bad_size = None, None
    if bad == "scheme": mode = 7
    elif bad == "size": bad_size = 6
    elif bad == "nan": case["a"][3].flat[0] = np.nan
    elif bad == "width": case["widths"][0][0] = 0.
    elif bad == "chunk": case["chunk"] = 0
    elif bad == "qtol": case["qtol"] = np.nan
    elif bad == "alpha": case["alpha"] = (.7, .5, 1.)
    elif bad == "direction": case["directions"] = (4, 2)
    elif bad == "opening": case["a"][8].flat[0] = 1.2
    elif bad == "alias": case["state"][1] = case["state"][0]
    initial = [x.copy() for x in case["state"]]
    code, _, _, error = temperature_native(case, mode=mode, bad_size=bad_size)
    assert code == 1 and error
    for actual, target in zip(case["state"], initial):
        np.testing.assert_array_equal(actual, target)


def test_zero_equation_is_arithmetic_failure_not_false_convergence(temperature_native):
    case = temperature_case((1, 1, 1))
    for fields in (case["a"], case["b"]):
        for index in (0, 1, 4, 5, 6):
            fields[index].fill(0.)
        fields[9] = np.empty(0)
    case["ks"].fill(0.)
    code, _, _, error = temperature_native(case)
    assert code == 2 and "equation" in error


@pytest.mark.parametrize("arrangement", ["cross", "counter"])
def test_actual_quick_design_const_and_mean_prepared_passes(temperature_native, monkeypatch, arrangement):
    from sjtu_tpmshx.preprocess.api import prepare_quick_design
    from sjtu_tpmshx.solvers.api import run_case
    from sjtu_tpmshx.tests.design.test_forward import _case
    execution = importlib.import_module("sjtu_tpmshx.solvers.backends.python.quick_design.execution")
    original = execution.solve_full_domain_3d
    captured = []

    def capture(*args, **kwargs):
        # Capture the real prepared frozen thermal problem at each property
        # pass. Geometry, correlations and water checks remain production Python.
        shape = tuple(args[3:6])
        aa = [np.full(shape, args[8]), np.full(shape, args[11]), np.full(shape, args[15] / 2),
              np.full(shape, args[13]), *[x.copy() for x in args[16:19]],
              np.empty(0), np.empty(0), np.empty(0)]
        bb = [np.full(shape, args[9]), np.full(shape, args[12]), np.full(shape, args[15] / 2),
              np.full(shape, args[14]), *[x.copy() for x in args[19:22]],
              np.empty(0), np.empty(0), np.empty(0)]
        plane = shape[2] == 1
        warm = kwargs["Ta_init"] is not None
        state = ([kwargs[k].copy() for k in ("Ta_init", "Tb_init", "Ts_init")] if warm
                 else [np.zeros(shape) for _ in range(3)])
        case = dict(shape=shape, widths=tuple(kwargs["d" + axis + "_arr"].copy() for axis in "xyz"),
                    a=aa, b=bb, state=state, ks=np.array(args[10], copy=True), prescribed=np.empty(0),
                    directions=(kwargs["dir_A"], kwargs["dir_B"]), tin=tuple(args[6:8]),
                    maxit=kwargs["max_iter"], chunk=kwargs["conv_chunk"] or (500 if plane else 250),
                    qtol=kwargs["q_rel_tol"] or (min(kwargs["tol"]*2e-3, 1e-3) if plane
                                                else max(kwargs["tol"]*10, 1e-4)),
                    warm=warm, sou_b=not plane,
                    alpha=(.7, 1., 1.) if plane else (kwargs["alpha_T"],)*3)
        result = original(*args, **kwargs)
        captured.append((case, tuple(x.copy() for x in result[:3]) + (dict(result[3]),)))
        return result

    monkeypatch.setattr(execution, "solve_full_domain_3d", capture)
    prepared = prepare_quick_design(_case(), "Diamond", 7., .5, .084,
                                    .025 if arrangement == "cross" else .05,
                                    arrangement, prop_model="mean", case_id="native-frozen-" + arrangement)
    result = run_case(prepared)
    assert result.run_status["converged"] and len(captured) == 2
    for case, expected in captured:
        assert_equivalent(case, temperature_native, expected)

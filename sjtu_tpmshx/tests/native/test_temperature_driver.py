"""Fixed-capacity driver: returned-state FV truth and exact lifecycle contracts.

Original cases, controls and short budgets remain intact. Shared-map numerical
truth is independent face-power arithmetic plus the existing analytic tests;
old Python trajectories remain available as explicitly historical helpers.
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
from sjtu_tpmshx.tests.native.temperature_fv_oracle import physical


@pytest.fixture(scope="module")
def temperature_native(tmp_path_factory):
    compiler = shlex.split(os.environ.get("CXX", "cl" if os.name == "nt" else "c++"))
    if os.name not in ("posix", "nt") or not compiler or not shutil.which(compiler[0]):
        message = "native temperature tests require a C++17 compiler"
        if os.environ.get("TPMSHX_REQUIRE_CPP_TESTS") == "1":
            pytest.fail(message)
        pytest.skip(message)
    root = Path(__file__).resolve().parents[3]
    eigen = Path(os.environ.get("TPMSHX_EIGEN_INCLUDE",
                               root / ".cache/native-deps/src/CoolProp-7.2.0/externals/Eigen")).resolve()
    if not (eigen / "Eigen/SparseLU").is_file():
        pytest.fail(f"Missing Eigen/SparseLU in {eigen}; set TPMSHX_EIGEN_INCLUDE "
                    "to the existing locked Eigen headers")
    build = tmp_path_factory.mktemp("cpp-temperature")
    suffix = ".dll" if os.name == "nt" else (".dylib" if sys.platform == "darwin" else ".so")
    library = build / ("temperature_test" + suffix)
    sources = [str(root / "native/src/temperature_driver.cpp"),
               str(root / "native/src/enthalpy_sweeps.cpp"),
               str(root / "native/src/conservative_energy.cpp"),
               str(Path(__file__).with_name("temperature_bridge.cpp"))]
    if os.name == "nt":
        flags = ["/nologo", "/std:c++17", "/O2", "/W4", "/WX", "/EHsc", "/MD", "/LD",
                 "/DTPMSHX_THERMAL_BUILD_SHARED", "/DEIGEN_MPL2_ONLY",
                 "/external:I" + str(eigen), "/external:W0", "/I" + str(root / "native/include"),
                 *sources, "/Fe" + str(library), "/link",
                 "/IMPLIB:" + str(build / "temperature_test.lib")]
    else:
        flags = ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-Werror", "-fPIC",
                 "-dynamiclib" if sys.platform == "darwin" else "-shared",
                 "-DEIGEN_MPL2_ONLY", "-isystem", str(eigen),
                 "-I", str(root / "native/include"), *sources, "-o", str(library)]
    subprocess.run([*compiler, *flags], cwd=build, check=True, capture_output=True, text=True)
    lib = ctypes.CDLL(str(library))
    function = lib.test_temperature_driver
    size_p = ctypes.POINTER(ctypes.c_size_t)
    double_p = ctypes.POINTER(ctypes.c_double)
    function.argtypes = [size_p, ctypes.POINTER(double_p), size_p, size_p, double_p,
                         size_p, double_p, double_p, double_p, double_p,
                         ctypes.POINTER(ctypes.c_char), ctypes.c_size_t]
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
        residual = np.full((3, *case["shape"]), np.nan)
        nx, ny, nz = case["shape"]
        powers = np.full(12*(nx*ny+nx*nz+ny*nz), np.nan)
        audit_meta = np.zeros(3)
        code = function(shape, pointers, sizes, config, values, status, metrics,
            residual.ctypes.data_as(double_p), powers.ctypes.data_as(double_p),
            audit_meta.ctypes.data_as(double_p), error, len(error))
        case["_native_physical"] = (dict(residual=residual, powers=powers,
            boundary_complete=bool(audit_meta[1]), prescribed_b_power=audit_meta[2])
            if audit_meta[0] else None)
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


def assert_returned_physics(case, status, metrics):
    assert status[0] in (0, 1) and 0 <= status[1] <= case["maxit"]
    chunks = (status[1] + case["chunk"] - 1) // case["chunk"]
    assert status[2] == 2*chunks and status[3] == chunks and status[4] == status[1]
    assert status[1] == case["maxit"] or status[1] % case["chunk"] == 0
    if status[0] == 1:
        assert status[1] == case["maxit"]
    else:
        assert chunks >= 2  # convergence needs a previous audited chunk
    assert all(np.isfinite(field).all() for field in case["state"])
    assert np.isfinite(metrics[0]) and metrics[0] >= 0
    if not status[1]:
        assert metrics[0] == 0 and np.isnan(metrics[1])
        assert case["_native_physical"] is None
        return
    expected = physical(case)
    actual = case["_native_physical"]
    assert actual is not None
    for key in ("residual", "powers"):
        np.testing.assert_allclose(actual[key], expected[key], rtol=2e-12, atol=2e-8, equal_nan=True)
    assert actual["boundary_complete"] == expected["boundary_complete"]
    assert actual["prescribed_b_power"] == pytest.approx(expected["prescribed_b_power"], rel=2e-12, abs=2e-8)
    rtol = 2e-12 if case["shape"][2] == 1 else 2e-11
    assert metrics[1] == pytest.approx(expected["qb"], rel=rtol, abs=1e-8)
    solved = [0, 2] if case["prescribed"].size else [0, 1, 2]
    boundary = float(np.nansum(expected["powers"])) - expected["prescribed_b_power"]
    assert abs(float(np.sum(expected["residual"][solved])) + boundary) <= 2e-8
    if status[0] == 0 and expected["boundary_complete"]:
        residual = expected["residual"][solved].reshape(len(solved), -1)
        assert max(np.abs(residual).sum(axis=1).max(), abs(boundary))/expected["denominator"] <= 1e-7
    if case["prescribed"].size:
        np.testing.assert_array_equal(case["state"][1], case["prescribed"])
        assert np.isnan(actual["residual"][1]).all()


def assert_equivalent(case, native):
    # Full input immutability remains independent of numerical-map qualification.
    borrowed = [*case["widths"], *case["a"], *case["b"], case["ks"], case["prescribed"]]
    before = [value.copy() for value in borrowed]
    code, status, metrics, error = native(case)
    assert code == 0, error
    for actual, expected in zip(borrowed, before):
        np.testing.assert_array_equal(actual, expected)
    assert_returned_physics(case, status, metrics)
    return status


def isolated_exchange_case(shape, *, maxit, chunk, alpha, initial=(350., 300., 325.)):
    """No transport/conduction: each cell is the same three scalar equations."""
    case = temperature_case(shape, sweeps=maxit, chunk=chunk)
    case["widths"] = tuple(np.ones(count) for count in shape)
    for fluid in (case["a"], case["b"]):
        for index in (0, 4, 5, 6):
            fluid[index].fill(0.)
        fluid[1].fill(1.)
        fluid[7:] = [np.empty(0), np.empty(0), np.empty(0)]
    case["ks"].fill(0.)
    case["tin"] = (initial[0], initial[1])
    case["state"] = [np.full(shape, value) for value in initial]
    case.update(warm=True, alpha=alpha)
    return case


def assert_one_sweep_alpha_arithmetic(native):
    # Two local analytic probes; no Python iteration or copied native loop.
    for alpha in ((.3, .5, .6), (.11, .4, .13)):
        case = isolated_exchange_case((1, 1, 2), maxit=1, chunk=1, alpha=alpha)
        aa, ss, bb = min(alpha[0], .2), alpha[1], min(alpha[2], .2)
        a = 350. + aa*(325.-350.)
        solid = 325. + ss*((a+300.)/2.-325.)
        b = 300. + bb*(solid-300.)
        target = np.array((350.+.6*(a-350.), 300.+.6*(b-300.), 325.+.6*(solid-325.)))
        code, status, metrics, error = native(case)
        assert code == 0, error
        assert status == (1, 1, 2, 1, 1)
        np.testing.assert_allclose(np.asarray(case["state"])[:, 0, 0, :], np.repeat(target[:, None], 2, axis=1), rtol=0., atol=1e-12)
        assert metrics[0] == pytest.approx(max(abs(target-np.array((350., 300., 325.)))), rel=0., abs=1e-12)
        assert_returned_physics(case, status, metrics)


@pytest.fixture(scope="module")
def accepted_five_sweeps(temperature_native):
    case = temperature_case(sweeps=5, chunk=5)
    assert_equivalent(case, temperature_native)
    return tuple(field.copy() for field in case["state"])


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
    if direction == 0:
        assert_one_sweep_alpha_arithmetic(temperature_native)


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
    # Keep the original random, generally divergent capacities and budget.
    assert_equivalent(case, temperature_native)
    # Equal Tin is not equilibrium for divergent conservative capacity fluxes.
    # Preserve the original exact two-chunk contract on explicit equilibrium.
    equilibrium = isolated_exchange_case(shape, maxit=maxit, chunk=5,
        alpha=case["alpha"], initial=(330., 330., 330.))
    equilibrium["warm"] = False
    status = assert_equivalent(equilibrium, temperature_native)
    for field in equilibrium["state"]:
        np.testing.assert_array_equal(field, np.full(shape, 330.))
    assert status[1] == min(maxit, 10)
    assert status[0] == (0 if maxit > 5 else 1)


@pytest.mark.parametrize("cancel_at,expected_iterations", [(1, 0), (2, 5), (3, 5)])
def test_cancel_before_or_after_chunk_reports_no_convergence(temperature_native, accepted_five_sweeps, cancel_at, expected_iterations):
    case = temperature_case(sweeps=19, chunk=5)
    expected = accepted_five_sweeps if expected_iterations else tuple(field.copy() for field in case["state"])
    code, status, metrics, error = temperature_native(case, cancel_at=cancel_at)
    assert code == 0, error
    assert status[0] == 2 and status[1] == expected_iterations
    assert status[2] == cancel_at
    assert status[3] == int(expected_iterations != 0)
    assert np.isnan(metrics[1])
    for actual, target in zip(case["state"], expected):
        np.testing.assert_array_equal(actual, target)
        assert actual.tobytes() == target.tobytes()


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
        seed = tuple(field.copy() for field in state)
        code, status, metrics, error = temperature_native(case)
        assert code == 0, error
        assert_returned_physics(case, status, metrics)
        info = dict(converged=status[0] == 0, iterations=status[1], residual=float(metrics[0]))
        returned = tuple(field.copy() for field in case["state"])
        captured.append(dict(case=case, input_seed=seed, returned=returned, info=info))
        return (*case["state"], info)

    monkeypatch.setattr(execution, "solve_full_domain_3d", capture)
    prepared = prepare_quick_design(_case(), "Diamond", 7., .5, .084,
                                    .025 if arrangement == "cross" else .05,
                                    arrangement, prop_model="mean", case_id="native-frozen-" + arrangement)
    result = run_case(prepared)
    assert result.run_status["converged"] and len(captured) == 2
    assert captured[0]["case"]["warm"] is False
    assert captured[1]["case"]["warm"] is True
    for seed, previous in zip(captured[1]["input_seed"], captured[0]["returned"]):
        np.testing.assert_array_equal(seed, previous)
        assert seed.tobytes() == previous.tobytes()
    for item in captured:
        assert item["info"]["converged"]
        for side in ("a", "b"):
            for index in (0, 1, 2, 3):
                field = item["case"][side][index]
                np.testing.assert_array_equal(field, np.full(field.shape, field.flat[0]))


def analytic_temperature_case(plane, kind, n):
    """K=0, equal exchange coefficients: eliminate solid to a two-stream ODE."""
    shape = (n, 1, 1 if plane else 2)
    area = .1 * (1. if plane else .02)
    conductance = 1000. * .1 * area
    ca = conductance * (.5 if kind == "wall" else 2.)
    cb = conductance * (1e6 if kind == "wall" else 1.)
    x = (np.arange(n) + .5) / n  # x/L
    if kind == "wall":
        ta = 300. + 100. * np.exp(-conductance * x / ca)
        tb = np.full(n, 300.)
        duty = ca * 100. * -np.expm1(-conductance / ca)
    else:
        rate = conductance * (1. / cb - 1. / ca)
        delta = 100. / (np.exp(rate) + conductance / ca * np.expm1(rate) / rate)
        ta = 400. - conductance / ca * delta * np.expm1(rate * x) / rate
        tb = ta - delta * np.exp(rate * x)
        duty = conductance * delta * np.expm1(rate) / rate
    fields = []
    for capacity, sign in ((ca, 1.), (cb, -1.)):
        values = (0., 2000., .3, 1000., sign * capacity / (.3 * 1000. * area), 0., 0.)
        fields.append([np.full(shape, value) for value in values] + [np.empty(0) for _ in range(3)])
    case = dict(shape=shape, widths=[np.full(n, .1 / n), np.array([.1]),
                    np.array([.017] if plane else [.01, .01])],
                a=fields[0], b=fields[1], ks=np.zeros(shape),
                state=[np.zeros(shape) for _ in range(3)], prescribed=np.empty(0),
                directions=(0, 1), tin=(400., 300.), maxit=10000, chunk=100,
                qtol=1e-12, warm=False, sou_b=not plane,
                alpha=(.7, 1., 1.) if plane else (.7, .7, .7))
    truth = [np.broadcast_to(value[:, None, None], shape) for value in (ta, tb, (ta + tb) / 2.)]
    return case, np.array(truth), duty, (ca, cb), conductance


def one_dimensional_balance(case, capacities, conductance):
    """Direct flux difference, independently reduced over transverse layers."""
    t = np.array(case["state"]).mean(axis=(2, 3))
    n = t.shape[1]
    exchange = 2. * conductance / n * (t[2] - t[:2])
    residual = [exchange[0].copy(), exchange[1].copy(), -exchange.sum(axis=0)]
    boundary = 0.
    for side, capacity in enumerate(capacities):
        values = t[side]
        face = np.empty(n + 1)
        face[0], face[-1] = ((400., values[-1]) if side == 0 else (values[0], 300.))
        if side == 0 or case["sou_b"]:
            jumps = np.diff(values)
            bounded = np.where(jumps[:-1] * jumps[1:] > 0.,
                               np.sign(jumps[:-1]) * np.minimum(abs(jumps[:-1]), abs(jumps[1:])), 0.)
            slopes = np.r_[bounded[0], bounded, bounded[-1]]
            face[1:-1] = (values[:-1] + .5 * slopes[:-1] if side == 0
                           else values[1:] - .5 * slopes[1:])
        else:
            face[1:-1] = values[1:]
        flux = capacity * (1. if side == 0 else -1.) * face
        residual[side] += flux[:-1] - flux[1:]
        boundary += flux[-1] - flux[0]
    qa, qb = -exchange[0].sum(), exchange[1].sum()
    scale = max(abs(qa), abs(qb), 1.)
    return max(np.abs(residual).sum(axis=1).max(), abs(boundary)) / scale, qb


@pytest.mark.parametrize("plane,kind,phases", [(True, "wall", (0, 2)), (False, "counter", (0, 1, 2))])
def test_shared_temperature_analytic_accuracy(temperature_native, plane, kind, phases):
    errors, balances = [], []
    for n in (8, 16, 32, 64):
        case, truth, duty, capacities, conductance = analytic_temperature_case(plane, kind, n)
        code, status, _, message = temperature_native(case)
        assert code == 0, message
        assert status[0] == 0 and status[1] <= case["maxit"]
        assert all(np.isfinite(field).all() for field in case["state"])
        ratio, actual_duty = one_dimensional_balance(case, capacities, conductance)
        balances.append(ratio)
        error = abs(np.array(case["state"]) - truth).reshape(3, -1)
        if kind == "wall":
            assert error[1].max() <= 1.001e-4  # finite C_B wall-limit perturbation
        errors.append((error.mean(axis=1), error.max(axis=1)))
    for phase in phases:
        l1 = np.array([item[0][phase] for item in errors])
        linf = np.array([item[1][phase] for item in errors])
        assert np.all(np.diff(l1) < 0.) and np.all(np.diff(linf) < 0.)
        assert np.log2(l1[-2] / l1[-1]) > .8
        assert linf[-1] < 1.
    assert abs(actual_duty - duty) / duty < .02
    assert max(balances) <= 1e-7


def two_patch_temperature_case(plane, closed, prescribed):
    """Two transverse cells: distinct inlet profiles, capacities and openings."""
    shape = (1, 2, 1) if plane else (1, 1, 2)
    widths = ([np.array([.1]), np.array([.02, .04]), np.array([.017])] if plane
              else [np.array([.1]), np.array([.06]), np.array([.011, .019])])
    area = widths[1] if plane else widths[1][0] * widths[2]
    patch_shape = shape[1:]
    fluids = []
    for side, speed in enumerate(((.2, .3), (-.15, -.25))):
        rho = (1000., 1500.)[side]
        values = ((.1, .2)[side], (100., 150.)[side], .3, rho)
        fluid = [np.full(shape, value) for value in values]
        fluid += [np.array(speed).reshape(shape), np.zeros(shape), np.zeros(shape)]
        profile = np.array((382., 394.) if side == 0 else (301., 313.)).reshape(patch_shape)
        opening = np.array((0. if closed else 1., .4)).reshape(patch_shape)
        # Already integrated inward capacity; neither partial opening nor area
        # may multiply it again. The closed entry deliberately stays positive.
        capacity = (.8 * .3 * rho * abs(np.array(speed)) * area).reshape(patch_shape)
        fluids.append([*fluid, profile, opening, capacity])
    return dict(shape=shape, widths=widths, a=fluids[0], b=fluids[1],
                state=[np.zeros(shape) for _ in range(3)], ks=np.full(shape, .7),
                prescribed=np.array([310., 317.]).reshape(shape) if prescribed else np.empty(0),
                directions=(0, 1), tin=(380., 300.), maxit=10000, chunk=100,
                qtol=1e-12, warm=False, sou_b=not plane,
                alpha=(.7, 1., 1.) if plane else (.7, .7, .7))


def two_patch_balance(c, state):
    """Independent linear FV powers; no B transport equation for prescribed B."""
    plane = c["shape"][2] == 1
    transverse = c["widths"][1 if plane else 2]
    depth = 1. if plane else c["widths"][1][0]
    length = c["widths"][0][0]
    area, volume = transverse * depth, transverse * depth * length
    t = np.array(state).reshape(3, 2)
    exchange = np.array([c[key][1].ravel() * volume * (t[2] - t[side])
                         for side, key in enumerate(("a", "b"))])
    residual = np.array([exchange[0], exchange[1], -exchange.sum(axis=0)])
    powers = np.zeros((3, 2))
    pinned = bool(c["prescribed"].size)
    for phase, conductivity in enumerate((c["a"][0], c["b"][0], c["ks"])):
        if phase == 1 and pinned:
            residual[phase] = np.nan
            powers[phase] = np.nan
            continue
        k = conductivity.ravel()
        conductance = length * depth / (.5 * transverse[0] / k[0] + .5 * transverse[1] / k[1])
        internal = conductance * (t[phase, 0] - t[phase, 1])
        residual[phase] += [-internal, internal]
        if phase < 2:
            fluid = c[("a", "b")[phase]]
            profile, opening, explicit = [field.ravel() for field in fluid[7:10]]
            inward_capacity = np.where(opening > 0, explicit, 0.)
            outward_capacity = fluid[2].ravel() * fluid[3].ravel() * abs(fluid[4].ravel()) * area
            inlet_conduction = 2. * k * area * opening / length * (t[phase] - profile)
            powers[phase] = outward_capacity * t[phase] - inward_capacity * profile + inlet_conduction
            residual[phase] -= powers[phase]
    qa, qb = -exchange[0].sum(), exchange[1].sum()
    reservoir = -qb if pinned else 0.
    return residual, powers, qa, qb, reservoir


@pytest.mark.parametrize("plane,closed,prescribed", [
    (True, False, False), (True, True, True),
    (False, False, True), (False, True, False),
])
def test_shared_temperature_boundary_and_reservoir(temperature_native, plane, closed, prescribed):
    c = two_patch_temperature_case(plane, closed, prescribed)
    phases = [0, 2] if prescribed else [0, 1, 2]
    zero = np.zeros((3, *c["shape"]))
    if prescribed:
        zero[1] = c["prescribed"]
    rhs = two_patch_balance(c, zero)[0][phases].ravel()
    matrix = np.empty((2 * len(phases), 2 * len(phases)))
    for column in range(len(rhs)):
        unit = zero.copy()
        unit[phases[column // 2]].flat[column % 2] = 1.
        matrix[:, column] = rhs - two_patch_balance(c, unit)[0][phases].ravel()
    solution = np.linalg.solve(matrix, rhs)
    assert np.max(abs(matrix @ solution - rhs)) <= 1e-10
    truth = zero.copy()
    truth[phases] = solution.reshape(len(phases), *c["shape"])
    expected = two_patch_balance(c, truth)
    code, status, metrics, message = temperature_native(c)
    assert code == 0, message
    assert status[0] == 0 and status[1] <= c["maxit"]
    np.testing.assert_allclose(c["state"], truth, rtol=0., atol=2e-6)
    residual, powers, qa, qb, reservoir = two_patch_balance(c, c["state"])
    scale = max(abs(qa), abs(qb), 1.)
    assert max(np.abs(residual[phases]).sum(axis=1).max(), abs(np.nansum(powers) - reservoir)) / scale <= 1e-7
    assert abs(np.sum(residual[phases]) + np.nansum(powers) - reservoir) <= 1e-9
    assert np.nanmax(abs(powers - expected[1])) <= 2e-6
    assert metrics[1] == pytest.approx(qb, rel=0., abs=2e-6)
    if prescribed:
        np.testing.assert_array_equal(c["state"][1], c["prescribed"])
        assert abs(-metrics[1] - expected[4]) <= 2e-6
        assert abs(np.nansum(powers) + metrics[1]) / scale <= 1e-7
        # With B prescribed, its conductivity, advection and inlet data cannot
        # influence the solved A/solid equations or the reservoir exchange.
        before = [field.copy() for field in c["state"]]
        c["b"][0] *= 3.
        c["b"][4] *= 2.
        c["b"][7] += 100.
        c["b"][8] = 1. - c["b"][8]
        c["b"][9] *= 5.
        c["state"] = [np.zeros(c["shape"]) for _ in range(3)]
        code, status, metrics, message = temperature_native(c)
        assert code == 0, message
        assert status[0] == 0 and status[1] <= c["maxit"]
        np.testing.assert_allclose(c["state"], before, rtol=0., atol=2e-6)
        np.testing.assert_array_equal(c["state"][1], c["prescribed"])
        assert abs(-metrics[1] - expected[4]) <= 2e-6

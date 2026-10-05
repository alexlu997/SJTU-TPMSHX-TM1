"""Fixed-flow 3D model-h returned-state qualification and retained contracts.

Tolerances fixed before comparisons: nonaccelerated T rtol2e-11/atol2e-9K;
Anderson T rtol2e-10/atol2e-8K; audit powers rtol2e-9/atol2e-9W.
Legacy trajectory tolerances remain on explicit same-map tests. Actual-state
audit tolerances and all six original phase2a gate predicates remain unchanged.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import ctypes
import os
from pathlib import Path
import sys

import numpy as np
import pytest

from sjtu_tpmshx.result_math import compute_phase2a
from sjtu_tpmshx.models.tpms_props import model_h_coefficients
from sjtu_tpmshx.tests.native.model_h_history import (
    compare_shadow, driver_function, heat_in_driver_order, n4_solved_case,
    read_progress, read_trace, stable_chunks,
)
from sjtu_tpmshx.solvers import ltne_energy_3d as energy


FACES = ("x-", "x+", "y-", "y+", "z-", "z+")
SIDE_KEYS = ("net_outward_mass_kg_s", "convective_inward_W", "inlet_diffusion_inward_W",
             "numerical_external_inward_W", "fluid_solid_exchange_to_fluid_W", "explicit_source_W",
             "residual_sum_W", "residual_max_abs_W", "strict_normalization_W")
FACE_KEYS = ("outward_mass_kg_s", "outward_model_h_W", "non_inlet_inward_mass_kg_s",
             "inlet_reverse_outward_mass_kg_s")
TOTAL_KEYS = ("full_volume_m3", "numerical_external_inward_W", "explicit_source_W", "solid_residual_sum_W",
              "solid_residual_max_abs_W", "full_residual_sum_W", "telescoping_error_W")


@pytest.fixture(scope="module")
def native():
    root = Path(__file__).resolve().parents[3]
    platform = "windows-x64" if os.name == "nt" else "macos-arm64"
    suffix = ".dll" if os.name == "nt" else (".dylib" if sys.platform == "darwin" else ".so")
    name = ("" if os.name == "nt" else "lib") + "model_h_3d_test" + suffix
    override = os.environ.get("TPMSHX_MODEL_H_3D_LIBRARY")
    library = Path(override) if override else root / ".cache/native-deps/build" / ("pilot-"+platform) / name
    if not library.is_file():
        message = f"native 3D model-h qualification library not built: {library}"
        if override or os.environ.get("TPMSHX_REQUIRE_NATIVE_DEPS_TESTS") == "1":
            pytest.fail(message)
        pytest.skip(message)
    official_library = ctypes.CDLL(str(library))
    function = driver_function(official_library, 3)
    dp = ctypes.POINTER(ctypes.c_double)

    def run(c, *, cancel_at=0, bad_size=None, alias=False, history=None, shadow=False, trace=None):
        active_library, active_function = official_library, function
        if shadow:
            override_history = os.environ.get("TPMSHX_MODEL_H_3D_HISTORY_LIBRARY")
            observed_path = Path(override_history) if override_history else library.with_name(name.replace("_test", "_history_test"))
            if not observed_path.is_file():
                pytest.fail(f"native model-h history library not built: {observed_path}")
            active_library = ctypes.CDLL(str(observed_path))
            active_function = driver_function(active_library, 3)

        output = [np.full(c["shape"], np.nan) for _ in range(3)]
        output += [np.full(tuple(n for axis, n in enumerate(c["shape"]) if axis != direction//2), np.nan)
                   for direction in c["directions"]]
        output += [np.full(tuple(n for ax, n in enumerate(c["shape"]) if ax != axis), np.nan)
                   for _side in range(2) for axis in range(3) for _end in range(2)]
        output += [np.full(7*(c["maxit"]//max(c["chunk"], 1)+1), np.nan)]
        arrays = [*c["widths"], *c["state"], c["ks"], c["source_s"], *c["a"], *c["b"], *output]
        assert len(arrays) == 42
        assert all(x.dtype == np.float64 and x.flags.c_contiguous for x in arrays)
        pointers = (dp*len(arrays))(*(x.ctypes.data_as(dp) for x in arrays))
        sizes = (ctypes.c_size_t*len(arrays))(*(x.size for x in arrays))
        if bad_size is not None:
            sizes[bad_size] -= 1
        if alias:
            pointers[6] = pointers[3]
        dimensions = (ctypes.c_size_t*3)(*c["shape"])
        config = (ctypes.c_size_t*12)(c["maxit"], c["chunk"], c["warm"], c["accelerate"],
                                    c["rb"], *c["fluids"], *c["directions"], cancel_at, history is not None, c.get("strict", False))
        values = (ctypes.c_double*6)(*c["tin"], c["qtol"], *c["alpha"])
        status, metrics, error = (ctypes.c_size_t*30)(), (ctypes.c_double*84)(), ctypes.create_string_buffer(512)
        code = active_function(dimensions, pointers, sizes, config, values, status, metrics, error, len(error))
        if history is not None:
            history[:] = read_progress(active_library, c["shape"])
        if trace is not None:
            assert shadow
            trace[:] = read_trace(active_library, c["shape"])
        return code, tuple(status), np.array(metrics), output, error.value.decode()

    return run


def case(shape=(4, 3, 3), directions=(0, 2), fluids=(0, 1), sweeps=17, chunk=5):
    rng = np.random.default_rng(1862)
    widths = [rng.uniform(.005, .025, n) for n in shape]
    sides = []
    for side, direction in enumerate(directions):
        fields = [rng.uniform(.02, .4, shape), rng.uniform(3000, 15000, shape)]
        masses = [rng.uniform(-.000002, .000002, tuple(n+(axis == ax) for ax, n in enumerate(shape)))
                  for axis in range(3)]
        masses[direction//2] += .000008 if direction % 2 == 0 else -.000008
        face_shape = tuple(n for axis, n in enumerate(shape) if axis != direction//2)
        profile = rng.uniform(345, 360, face_shape) if side == 0 else rng.uniform(295, 305, face_shape)
        opening = rng.uniform(.1, 1, face_shape)
        opening.flat[::3] = 0
        opening.flat[-1] = 1
        sides.append([*fields, *masses, profile, opening, np.empty(0)])
    return dict(shape=shape, widths=widths, a=sides[0], b=sides[1], source_s=np.empty(0),
                state=[rng.uniform(310, 340, shape) for _ in range(3)], ks=rng.uniform(.5, 4, shape),
                tin=(355., 300.), directions=directions, fluids=fluids, maxit=sweeps, chunk=chunk,
                warm=True, accelerate=False, rb=False, alpha=(.7, .7, .7), qtol=1e-4)


def python(c, monkeypatch):
    monkeypatch.setattr(energy, "_RB_ENERGY", c["rb"])
    monkeypatch.setattr(energy, "_RB_ENERGY_GATE", 0)
    a, b = c["a"], c["b"]
    one, zero = np.ones(c["shape"]), np.zeros(c["shape"])
    kwargs = dict(max_iter=c["maxit"], conv_chunk=c["chunk"], q_rel_tol=c["qtol"],
                  return_info=True, conservative_ltne=True, accelerate=c["accelerate"],
                  model_fluids=tuple(("air", "water")[i] for i in c["fluids"]),
                  model_mass_A=tuple(a[2:5]), model_mass_B=tuple(b[2:5]),
                  ufA=a[2], vfA=a[3], wfA=a[4], ufB=b[2], vfB=b[3], wfB=b[4],
                  dx_arr=c["widths"][0], dy_arr=c["widths"][1], dz_arr=c["widths"][2],
                  T_inA_profile=a[5] if a[5].size else None, T_inB_profile=b[5] if b[5].size else None,
                  inlet_mask_A=a[6] if a[6].size else None, inlet_mask_B=b[6] if b[6].size else None,
                  mms_S_A_field=a[7] if a[7].size else None, mms_S_B_field=b[7] if b[7].size else None,
                  mms_S_s_field=c["source_s"] if c["source_s"].size else None,
                  alpha_T_fA=c["alpha"][0], alpha_T_s=c["alpha"][1], alpha_T_fB=c["alpha"][2])
    if c["warm"]:
        kwargs.update(zip(("Ta_init", "Tb_init", "Ts_init"), c["state"]))
    return energy.solve_full_domain_3d(*[x.sum() for x in c["widths"]], *c["shape"], *c["tin"],
        a[0], b[0], c["ks"], a[1], b[1], one, one, one*.7, zero, zero, zero, zero, zero, zero,
        *c["directions"], **kwargs)


def assert_finishing_history(c, actual, history):
    """Recompute stability and the six original gates at each accepted chunk."""
    _, status, metrics, output, _ = actual
    assert not c.get("strict", False)
    expected_done = list(range(c["chunk"], status[1]+1, c["chunk"]))
    if status[1] % c["chunk"]:
        expected_done.append(status[1])
    assert [done for done, _ in history] == expected_done
    assert len(history) == status[3]
    has_sources = any(np.any(source != 0) for source in (c["a"][7], c["b"][7], c["source_s"]))
    checks = []
    for done, state, stable in stable_chunks(c, history):
        assert all(np.all(np.isfinite(field)) for field in state)
        if not stable:
            continue
        if has_sources:
            assert status[0] == 0 and done == status[1]
            continue
        info = returned_model_info(dict(c, state=state))
        certificate = compute_phase2a(dict(info, _audit_fB=True))
        gates = [passed for _, passed in certificate["gates"]]
        checks.append([done, *gates])
        if all(gates) or not info["model_h_balance"]["physical_boundary_complete"]:
            assert done == status[1] and status[0] == (0 if all(gates) else 1)
    assert status[29] == len(checks)
    np.testing.assert_array_equal(output[-1][:7*status[29]].reshape(-1, 7),
                                  np.asarray(checks).reshape(-1, 7))
    if history:
        assert metrics[1] == pytest.approx(heat_in_driver_order(c, history[-1][1]), rel=2e-9, abs=2e-9)


def equivalent(c, native, monkeypatch):
    if c["maxit"]:
        history = []
        actual = native(c, history=history)
        result = assert_actual_state(c, actual)
        assert_finishing_history(c, actual, history)
        return result
    # Zero-budget states are identical across maps; retain the original audit.
    expected = python(c, monkeypatch)
    return assert_equivalent(c, native(c), expected)


def returned_model_info(c):
    """Existing read-only Python equations evaluated on the actual native T."""
    zero = np.zeros(c["shape"])
    profiles, openings, sources = [], [], []
    for index, side in enumerate((c["a"], c["b"])):
        face_shape = tuple(n for axis, n in enumerate(c["shape"])
                           if axis != c["directions"][index]//2)
        profiles.append(side[5] if side[5].size else np.full(face_shape, c["tin"][index]))
        openings.append(side[6] if side[6].size else np.ones(face_shape))
        sources.append(side[7] if side[7].size else zero)
    balance = energy._model_h_balance(
        c["state"][:2], c["state"][2], (tuple(c["a"][2:5]), tuple(c["b"][2:5])),
        tuple(model_h_coefficients(("air", "water")[f]) for f in c["fluids"]),
        c["directions"], profiles, openings, (c["a"][0], c["b"][0]), c["ks"],
        (c["a"][1], c["b"][1]), (np.full(c["shape"], .35),)*2, sources,
        c["source_s"] if c["source_s"].size else zero, *c["widths"])
    info = dict(model_h_balance=balance, _native_model_h=balance.pop("_native_faces"))
    for side, data in balance["sides"].items():
        scale = data["strict_normalization_W"]
        info[f"eps_{side}_strict"] = abs(data["residual_sum_W"])/scale
        info[f"eps_{side}_strict_cellmax"] = data["residual_max_abs_W"]*c["state"][0].size/scale
        info[f"Q_s{side}"] = data["fluid_solid_exchange_to_fluid_W"]
    return info


def assert_actual_state(c, actual):
    code, status, metrics, output, error = actual
    assert code == 0, error
    assert status[0] in (0, 1) and 0 <= status[1] <= c["maxit"]
    assert np.isfinite(metrics[0]) and metrics[0] >= 0
    assert all(np.all(np.isfinite(t)) for t in c["state"])
    info = returned_model_info(c)
    balance = info["model_h_balance"]
    certificate = compute_phase2a(dict(info, _audit_fB=True))
    has_sources = any(np.any(source != 0) for source in (c["a"][7], c["b"][7], c["source_s"]))
    assert status[5] == 1 and status[6] == has_sources
    assert status[7] == balance["physical_boundary_complete"]
    assert status[8] == all(passed for _, passed in certificate["gates"])
    assert status[9:15] == tuple(passed for _, passed in certificate["gates"])
    assert status[15:17] == tuple(balance["sides"][s]["physical_boundary_complete"] for s in ("A", "B"))
    assert status[17:29] == tuple(balance["sides"][s]["faces"][f]["unknown_inflow_count"]
                                   for s in ("A", "B") for f in FACES)
    scalars = []
    for side in ("A", "B"):
        data = balance["sides"][side]
        scalars.extend(data["temperature_range_K"])
        scalars.extend(data[key] for key in SIDE_KEYS)
        scalars.extend([info[f"eps_{side}_strict"], info[f"eps_{side}_strict_cellmax"]])
    scalars.extend(balance["sides"][side]["faces"][face][key]
                   for side in ("A", "B") for face in FACES for key in FACE_KEYS)
    scalars.extend(balance[key] for key in TOTAL_KEYS)
    scalars.append(certificate["eps_LTNE"])
    np.testing.assert_allclose(metrics[2:], scalars, rtol=2e-9, atol=2e-9)
    for i, side in enumerate(("A", "B")):
        for f, name in enumerate(FACES):
            np.testing.assert_allclose(output[5+6*i+f], info["_native_model_h"][side][name], rtol=2e-9, atol=2e-9)
    zeros, eps = np.zeros(c["shape"]), np.full(c["shape"], .35)
    zero_faces = tuple(np.zeros_like(face) for face in c["a"][2:5])
    exchange = []
    for i, key in enumerate(("a", "b")):
        side, direction = c[key], c["directions"][i]
        face_shape = tuple(n for axis, n in enumerate(c["shape"]) if axis != direction//2)
        inlet = side[5] if side[5].size else np.full(face_shape, c["tin"][i])
        opening = side[6] if side[6].size else np.ones(face_shape)
        residual, source, diffusion = energy._conservation_residual_sum(
            c["state"][i], c["state"][2], *zero_faces, eps, side[0], zeros, side[1], *c["widths"],
            direction, inlet, opening, side[7] if side[7].size else zeros,
            model_mass=tuple(side[2:5]), model_cp=model_h_coefficients(("air", "water")[c["fluids"][i]]),
            return_field=True)
        exchange.append(source)
        np.testing.assert_allclose(output[i], residual, rtol=2e-9, atol=2e-9)
        np.testing.assert_allclose(output[3+i], diffusion, rtol=2e-9, atol=2e-9)
    solid, _, _ = energy._conservation_residual_sum(
        c["state"][2], c["state"][2], *zero_faces, eps, c["ks"], zeros, zeros, *c["widths"],
        0, c["state"][2][0], np.zeros_like(c["state"][2][0]),
        c["source_s"] if c["source_s"].size else zeros, return_field=True)
    np.testing.assert_allclose(output[2], solid+exchange[0]+exchange[1], rtol=2e-9, atol=2e-9)
    checks = output[-1][:7*status[29]].reshape(-1, 7)
    assert len(checks) == status[29] <= (status[1]+c["chunk"]-1)//c["chunk"]
    if len(checks):
        assert np.all(np.isfinite(checks))
        assert np.all((checks[:, 1:] == 0) | (checks[:, 1:] == 1))
        assert np.all(np.diff(checks[:, 0]) > 0)
        assert np.all((checks[:, 0] > 0) & (checks[:, 0] <= status[1]))
        assert np.all((checks[:, 0] % c["chunk"] == 0) | (checks[:, 0] == c["maxit"]))
    if has_sources:
        assert status[29] == 0  # Preserve the old source-bearing stopping rule.
    elif status[0] == 0:
        assert status[8] == 1 and len(checks) > 0
        np.testing.assert_array_equal(checks[-1], [status[1], *(passed for _, passed in certificate["gates"])])
    elif status[1] < c["maxit"]:
        assert not balance["physical_boundary_complete"]
    if c["maxit"]:
        volume = c["widths"][0][:, None, None]*c["widths"][1][None, :, None]*c["widths"][2][None, None, :]
        q = np.sum(c["b"][1]*(c["state"][2]-c["state"][1])*volume)
        assert metrics[1] == pytest.approx(q, rel=2e-9, abs=2e-9)
    else:
        assert np.isnan(metrics[1])
    return status, metrics, output


def assert_equivalent(c, actual, expected):
    code, status, metrics, output, error = actual
    assert code == 0, error
    info = expected[3]
    balance = info["model_h_balance"]
    certificate = compute_phase2a(dict(info, _audit_fB=True))
    assert status[0] == (0 if info["converged"] else 1)
    assert status[1] == info["iterations"]
    assert status[5] == 1
    assert status[7] == balance["physical_boundary_complete"]
    assert status[8] == all(passed for _, passed in certificate["gates"])
    assert status[9:15] == tuple(passed for _, passed in certificate["gates"])
    assert status[15:17] == tuple(balance["sides"][s]["physical_boundary_complete"] for s in ("A", "B"))
    assert status[17:29] == tuple(balance["sides"][s]["faces"][f]["unknown_inflow_count"]
                                   for s in ("A", "B") for f in FACES)
    rtol, atol = (2e-10, 2e-8) if c["accelerate"] else (2e-11, 2e-9)
    for actual, target in zip(c["state"], expected[:3]):
        np.testing.assert_allclose(actual, target, rtol=rtol, atol=atol)
    assert metrics[0] == pytest.approx(info["residual"], rel=rtol, abs=atol)
    scalars = []
    for side in ("A", "B"):
        data = balance["sides"][side]
        scalars.extend(data["temperature_range_K"])
        scalars.extend(data[key] for key in SIDE_KEYS)
        scalars.extend([info[f"eps_{side}_strict"], info[f"eps_{side}_strict_cellmax"]])
    scalars.extend(balance["sides"][side]["faces"][face][key]
                   for side in ("A", "B") for face in FACES for key in FACE_KEYS)
    scalars.extend(balance[key] for key in TOTAL_KEYS)
    scalars.append(certificate["eps_LTNE"])
    np.testing.assert_allclose(metrics[2:], scalars, rtol=2e-9, atol=2e-9)
    for i, side in enumerate(("A", "B")):
        for f, name in enumerate(FACES):
            np.testing.assert_allclose(output[5+6*i+f], info["_native_model_h"][side][name], rtol=2e-9, atol=2e-9)
    # Compare every actual-state equation, not only maxima/integrated sums.
    zeros, eps = np.zeros(c["shape"]), np.full(c["shape"], .35)
    zero_faces = tuple(np.zeros_like(face) for face in c["a"][2:5])
    exchange = []
    for i, key in enumerate(("a", "b")):
        side, direction = c[key], c["directions"][i]
        face_shape = tuple(n for axis, n in enumerate(c["shape"]) if axis != direction//2)
        inlet = side[5] if side[5].size else np.full(face_shape, c["tin"][i])
        opening = side[6] if side[6].size else np.ones(face_shape)
        residual, source, diffusion = energy._conservation_residual_sum(
            expected[i], expected[2], *zero_faces, eps, side[0], zeros, side[1], *c["widths"],
            direction, inlet, opening, side[7] if side[7].size else zeros,
            model_mass=tuple(side[2:5]), model_cp=model_h_coefficients(("air", "water")[c["fluids"][i]]),
            return_field=True)
        exchange.append(source)
        np.testing.assert_allclose(output[i], residual, rtol=2e-9, atol=2e-9)
        np.testing.assert_allclose(output[3+i], diffusion, rtol=2e-9, atol=2e-9)
    solid, _, _ = energy._conservation_residual_sum(
        expected[2], expected[2], *zero_faces, eps, c["ks"], zeros, zeros, *c["widths"],
        0, expected[2][0], np.zeros_like(expected[2][0]), c["source_s"] if c["source_s"].size else zeros,
        return_field=True)
    np.testing.assert_allclose(output[2], solid+exchange[0]+exchange[1], rtol=2e-9, atol=2e-9)
    checks = info["energy_finishing_checks"]
    assert status[29] == len(checks)
    np.testing.assert_array_equal(output[-1][:7*len(checks)].reshape(-1, 7),
        np.array([[x["iterations"], *(passed for _, passed in x["gates"])] for x in checks]).reshape(-1, 7))
    if c["maxit"]:
        volume = c["widths"][0][:, None, None] * c["widths"][1][None, :, None] * c["widths"][2][None, None, :]
        q = np.sum(c["b"][1]*(expected[2]-expected[1])*volume)
        assert metrics[1] == pytest.approx(q, rel=2e-9, abs=2e-9)
    else:
        assert np.isnan(metrics[1])
    return status, metrics, output


@pytest.mark.parametrize("directions", [(0, 2), (1, 3), (2, 4), (3, 5), (4, 1), (5, 0)])
@pytest.mark.parametrize("rb", [False, True])
def test_six_directions_nonuniform_partial_sou(native, monkeypatch, directions, rb):
    c = case(directions=directions)
    c["rb"] = rb
    equivalent(c, native, monkeypatch)


@pytest.mark.parametrize("fluids", [(0, 0), (0, 1), (1, 0)])
@pytest.mark.parametrize("shape", [(1, 1, 3), (1, 4, 2), (4, 1, 2)])
def test_thin_grids_cold_start(native, monkeypatch, fluids, shape):
    c = case(shape=shape, directions=(4, 5), fluids=fluids)
    c["warm"] = False
    for key in ("a", "b"):
        c[key][5] = c[key][6] = np.empty(0)
    equivalent(c, native, monkeypatch)


def straight_case(sweeps=6000, accelerate=False, rb=False):
    c = case(shape=(8, 3, 3), directions=(0, 1), sweeps=sweeps, chunk=100)
    c.update(accelerate=accelerate, rb=rb, warm=False, qtol=1e-5)
    for key, mass in (("a", .000007), ("b", -.00002)):
        c[key][0][:] = .03 if key == "a" else .2
        c[key][1][:] = 25000
        c[key][2][:] = mass
        c[key][3][:] = c[key][4][:] = 0
        c[key][5] = c[key][6] = np.empty(0)
    c["ks"][:] = 2
    return c


@pytest.mark.parametrize("accelerate", [False, True])
@pytest.mark.parametrize("rb", [False, True])
def test_complete_solve_preserves_acceptance(native, monkeypatch, accelerate, rb):
    c = straight_case(accelerate=accelerate, rb=rb)
    status, _, _ = equivalent(c, native, monkeypatch)
    assert status[0] == 0 and status[8] == 1
    assert status[1] < c["maxit"]


def test_smaller_explicit_relaxation_retained(native, monkeypatch):
    c = case(sweeps=23)
    c["alpha"] = (.11, .4, .13)
    assert_actual_state(c, native(c))
    # The 3D API requires nz>1. With zero transport/conduction, these two
    # cells are independent one-CV equations, so no line-solver oracle is needed.
    probe = case(shape=(1, 1, 2), sweeps=1, chunk=1)
    probe.update(alpha=c["alpha"], widths=[np.ones(n) for n in probe["shape"]],
                 state=[np.full(probe["shape"], value) for value in (350., 300., 325.)])
    probe["ks"][:] = 0.
    for key in ("a", "b"):
        side = probe[key]
        side[0][:] = 0.
        side[1][:] = 1.
        side[2][:] = side[3][:] = side[4][:] = 0.
        side[5] = side[6] = np.empty(0)
    result = native(probe)
    status, metrics, _ = assert_actual_state(probe, result)
    assert status[0] == 1 and status[1] == 1
    # A=350+.11*(325-350); S=325+.4*((A+300)/2-325);
    # B=300+.13*(S-300). The fluid .2 ceiling must preserve smaller alphas.
    for field, expected in zip(probe["state"], (347.25, 303.1785, 324.45)):
        np.testing.assert_allclose(field, expected, rtol=0., atol=1e-12)
    assert metrics[0] == pytest.approx(3.1785, rel=0., abs=1e-12)


def test_anderson_budget_remainder(native, monkeypatch):
    c = straight_case(sweeps=139, accelerate=True)
    c["chunk"] = 67
    actual, history, decisions, trace = compare_shadow(c, native, 3)
    status, _, _ = assert_actual_state(c, actual)
    assert_finishing_history(c, actual, history)
    assert status[0] == 1 and status[1] == 139
    assert len(decisions) == 2
    assert sum(row[0] == 0 and row[1] == 1 for row in trace) == 4
    fixed = n4_solved_case(case, 3)
    n4, _, choices, _ = compare_shadow(fixed, native, 3)
    assert n4[1][0] == 1 and n4[1][1] == 139
    assert choices == [False, True]

@pytest.mark.parametrize("sources", [False, True])
def test_zero_budget_final_audit(native, monkeypatch, sources):
    c = case(sweeps=0)
    if sources:
        c["a"][7] = np.full(c["shape"], 1400.)
        c["b"][7] = np.full(c["shape"], -900.)
        c["source_s"] = np.full(c["shape"], -700.)
    state = copy.deepcopy(c["state"])
    status, _, _ = equivalent(c, native, monkeypatch)
    assert status[0] == 1 and status[6] == sources
    for actual, target in zip(c["state"], state):
        np.testing.assert_array_equal(actual, target)


@pytest.mark.parametrize("rb", [False, True])
def test_manufactured_sources_keep_own_stopping_rule(native, monkeypatch, rb):
    c = straight_case(accelerate=True, rb=rb)
    c["a"][7] = np.full(c["shape"], 2400.)
    c["b"][7] = np.full(c["shape"], -900.)
    c["source_s"] = np.full(c["shape"], -700.)
    status, _, _ = equivalent(c, native, monkeypatch)
    assert status[0] == 0 and status[6] == 1 and status[29] == 0


def test_unknown_inflow_does_not_gain_certificate(native, monkeypatch):
    c = straight_case(accelerate=True)
    c["a"][2][-1] = -.000001
    status, _, _ = equivalent(c, native, monkeypatch)
    assert status[0] == 1 and status[7:9] == (0, 0)


@pytest.mark.parametrize("cancel_at", [1, 4, 7, 13])
def test_cancel_and_recovery(native, cancel_at):
    result = native(straight_case(accelerate=True), cancel_at=cancel_at)
    assert result[0] == 0 and result[1][0] == 2 and result[1][5] == 0
    assert np.isnan(result[2][1])
    successful = native(straight_case(accelerate=True))
    assert successful[0] == 0 and successful[1][0] == 0


@pytest.mark.parametrize("invalid", ["extent", "nan", "alias", "WW", "co2", "opening", "alpha", "chunk"])
def test_invalid_inputs_leave_fields_unchanged(native, invalid):
    c = case()
    options = {}
    if invalid == "extent":
        options["bad_size"] = 10
    elif invalid == "nan":
        c["a"][2][0, 0, 0] = np.nan
    elif invalid == "alias":
        options["alias"] = True
    elif invalid == "WW":
        c["fluids"] = (1, 1)
    elif invalid == "co2":
        c["fluids"] = (2, 0)
    elif invalid == "opening":
        c["a"][6][0, 0] = 1.1
    elif invalid == "alpha":
        c["alpha"] = (.2, 0., .2)
    elif invalid == "chunk":
        c["chunk"] = 0
    before = copy.deepcopy(c["state"])
    result = native(c, **options)
    assert result[0] == 1, result[-1]
    for actual, expected in zip(c["state"], before):
        np.testing.assert_array_equal(actual, expected)


def test_parallel_state_and_cancel_isolation(native):
    with ThreadPoolExecutor(2) as pool:
        cancelled = pool.submit(native, straight_case(accelerate=True), cancel_at=4)
        successful = pool.submit(native, straight_case(accelerate=True))
        assert cancelled.result()[1][0] == 2
        assert successful.result()[1][0] == 0

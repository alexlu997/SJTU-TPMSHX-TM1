"""Complete native 2D model-h driver qualification against current Python.

Tolerances fixed before running: unaccelerated T rtol 2e-12 / atol 2e-10 K;
Anderson T rtol 2e-10 / atol 2e-8 K (different SVD implementation). Audits
rtol 2e-10 / atol 2e-8 W/m, with exact budget, exit and gate predicates.
No new acceptance threshold replaces the production equation/energy gates.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import ctypes
import inspect
import os
from pathlib import Path
import sys

import numpy as np
import pytest

from sjtu_tpmshx.solvers import ltne_energy as energy


SIDE_KEYS = (
    "Q_advective_W_per_m", "inlet_conduction_W_per_m", "exchange_W_per_m",
    "residual_sum_W_per_m", "residual_max_abs_W_per_m", "linearized_residual_sum_W_per_m",
    "linearized_residual_max_abs_W_per_m", "linearization_defect_sum_W_per_m",
    "linearization_defect_max_abs_W_per_m", "mass_net_out_kg_s_per_m",
    "mass_local_max_abs_kg_s_per_m", "mass_in_kg_s_per_m", "mass_out_kg_s_per_m",
    "strict_normalization_W_per_m", "residual_cellmax_rel",
)
AUDIT_KEYS = (
    "solid_residual_sum_W_per_m", "solid_residual_max_abs_W_per_m",
    "solid_residual_cellmax_rel", "residual_sum_W_per_m", "telescoping_error_W_per_m",
    "net_boundary_in_W_per_m", "D2_W_per_m", "energy_imbalance_rel", "solid_imbalance_rel",
)
GATE_KEYS = ("physical_boundary_complete", "finite", "energy_ok", "solid_ok", "equations_ok", "passed")


@pytest.fixture(scope="module")
def native():
    root = Path(__file__).resolve().parents[3]
    platform = "windows-x64" if os.name == "nt" else "macos-arm64"
    suffix = ".dll" if os.name == "nt" else (".dylib" if sys.platform == "darwin" else ".so")
    name = ("" if os.name == "nt" else "lib") + "model_h_2d_test" + suffix
    override = os.environ.get("TPMSHX_MODEL_H_2D_LIBRARY")
    library = Path(override) if override else root / ".cache/native-deps/build" / ("pilot-" + platform) / name
    if not library.is_file():
        message = f"native model-h qualification library not built: {library}"
        if override or os.environ.get("TPMSHX_REQUIRE_NATIVE_DEPS_TESTS") == "1":
            pytest.fail(message)
        pytest.skip(message)
    function = ctypes.CDLL(str(library)).test_model_h_2d
    sp = ctypes.POINTER(ctypes.c_size_t)
    dp = ctypes.POINTER(ctypes.c_double)
    function.argtypes = [sp, ctypes.POINTER(dp), sp, sp, dp, sp, dp,
                         ctypes.POINTER(ctypes.c_char), ctypes.c_size_t]
    function.restype = ctypes.c_int

    def run(case, *, bad_size=None, cancel_at=0, alias=False):
        shape = case["shape"]
        outputs = [np.full(shape, np.nan) for _ in range(7)]
        outputs += [np.full_like(case[key][index], np.nan) for key in ("a", "b") for index in (2, 3)]
        outputs += [np.full(shape[1] if direction < 2 else shape[0], np.nan) for direction in case["directions"]]
        outputs += [np.full(3 * (case["maxit"] // max(case["chunk"], 1) + 1), np.nan)]
        arrays = [*case["widths"], *case["state"], case["ks"], *case["a"], *case["b"], *outputs]
        assert len(arrays) == 33
        assert all(a.dtype == np.float64 and a.flags.c_contiguous for a in arrays)
        pointers = (dp * len(arrays))(*(a.ctypes.data_as(dp) for a in arrays))
        sizes = (ctypes.c_size_t * len(arrays))(*(a.size for a in arrays))
        if bad_size is not None:
            sizes[bad_size] -= 1
        if alias:
            pointers[6] = pointers[3]
        config = (ctypes.c_size_t * 10)(case["maxit"], case["chunk"], case["warm"],
            case["accelerate"], case["rb"], *case["fluids"], *case["directions"], cancel_at)
        values = (ctypes.c_double * 3)(*case["tin"], case["qtol"])
        dimensions = (ctypes.c_size_t * 3)(*shape, 1)
        status, metrics = (ctypes.c_size_t * 15)(), (ctypes.c_double * 41)()
        error = ctypes.create_string_buffer(512)
        code = function(dimensions, pointers, sizes, config, values, status, metrics, error, len(error))
        return code, tuple(status), np.array(metrics), outputs, error.value.decode()

    return run


def case(shape=(5, 4), directions=(0, 2), fluids=(0, 1), sweeps=19, chunk=5):
    rng = np.random.default_rng(901)
    widths = [rng.uniform(.005, .025, n) for n in shape] + [np.ones(1)]
    sides = []
    for side, direction in enumerate(directions):
        fields = [rng.uniform(.02, .2, shape), rng.uniform(2000, 15000, shape)]
        mx = rng.uniform(-.0001, .0001, (shape[0]+1, shape[1]))
        my = rng.uniform(-.0001, .0001, (shape[0], shape[1]+1))
        axis = direction // 2
        (mx if axis == 0 else my)[:] += .0003 if direction % 2 == 0 else -.0003
        profile = rng.uniform(360, 385, shape[1-axis]) if side == 0 else rng.uniform(290, 315, shape[1-axis])
        opening = rng.uniform(.1, 1, len(profile))
        opening[::3] = 0
        opening[-1] = 1
        sides.append([*fields, mx, my, profile, opening])
    return dict(shape=shape, widths=widths, a=sides[0], b=sides[1],
                state=[rng.uniform(315, 355, shape) for _ in range(3)],
                ks=rng.uniform(.3, 5, shape), directions=directions, fluids=fluids,
                tin=(375., 300.), maxit=sweeps, chunk=chunk, qtol=1e-4,
                warm=True, accelerate=False, rb=False)


def python(case, monkeypatch):
    monkeypatch.setattr(energy, "_RB_ENERGY_2D", case["rb"])
    monkeypatch.setattr(energy, "_RB_ENERGY_2D_GATE", 0)
    a, b = case["a"], case["b"]
    zero = np.zeros(case["shape"])
    one = np.ones(case["shape"])
    kwargs = dict(max_iter=case["maxit"], conv_chunk=case["chunk"], q_rel_tol=case["qtol"],
                  return_info=True, model_fluids=tuple(("air", "water")[f] for f in case["fluids"]),
                  mass_flux_A=tuple(a[2:4]), mass_flux_B=tuple(b[2:4]),
                  T_inA_profile=a[4] if a[4].size else None,
                  T_inB_profile=b[4] if b[4].size else None,
                  inlet_mask_A=a[5] if a[5].size else None, inlet_mask_B=b[5] if b[5].size else None,
                  dx_arr=case["widths"][0], dy_arr=case["widths"][1], accelerate=case["accelerate"])
    if case["warm"]:
        kwargs.update(zip(("Ta_init", "Tb_init", "Ts_init"), case["state"]))
    return energy.solve_full_domain(
        *[w.sum() for w in case["widths"][:2]], *case["shape"], *case["tin"],
        a[0], b[0], case["ks"], a[1], b[1], one, one, one, zero, zero, zero, zero,
        *case["directions"], **kwargs)


def equivalent(c, native, monkeypatch):
    expected = python(c, monkeypatch)
    code, status, metrics, output, error = native(c)
    assert code == 0, error
    info, balance = expected[3], expected[3]["model_h_balance"]
    assert status[0] == (0 if info["converged"] else 1)
    assert status[1] == info["iterations"]
    assert status[5] == 1
    assert status[6:8] == tuple(balance[side]["unknown_inflow_faces"] for side in ("A", "B"))
    assert status[8:14] == tuple(balance[key] for key in GATE_KEYS)
    rtol, atol = (2e-10, 2e-8) if c["accelerate"] else (2e-12, 2e-10)
    for actual, target in zip(c["state"], expected[:3]):
        np.testing.assert_allclose(actual, target, rtol=rtol, atol=atol)
    assert metrics[0] == pytest.approx(info["residual"], rel=rtol, abs=atol)
    scalars = [balance[side][key] for side in ("A", "B") for key in SIDE_KEYS]
    scalars += [balance[key] for key in AUDIT_KEYS]
    np.testing.assert_allclose(metrics[2:], scalars, rtol=2e-10, atol=2e-8)
    for i, side in enumerate(("A", "B")):
        for axis in range(2):
            np.testing.assert_allclose(output[7+2*i+axis], balance[side]["h_faces_W_per_m"][axis], rtol=2e-10, atol=2e-8)
        np.testing.assert_allclose(output[11+i], balance[side]["inlet_conduction_faces_W_per_m"], rtol=2e-10, atol=2e-8)
    checks = info["energy_finishing_checks"]
    assert status[14] == len(checks)
    np.testing.assert_array_equal(output[-1][:3*len(checks)].reshape(-1, 3),
        np.array([[x["iterations"], x["passed"], x["equations_ok"]] for x in checks]).reshape(-1, 3))
    if c["maxit"]:
        expected_q = np.sum(c["b"][1] * (expected[2] - expected[1]) * c["widths"][0][:, None] * c["widths"][1][None, :])
        assert metrics[1] == pytest.approx(expected_q, rel=2e-10, abs=2e-8)
    else:
        assert np.isnan(metrics[1])
    return status, metrics, output


@pytest.mark.parametrize("directions", [(0, 2), (1, 3), (2, 1), (3, 0), (0, 1), (2, 3)])
@pytest.mark.parametrize("rb", [False, True])
def test_directed_nonuniform_sou_and_final_audit(native, monkeypatch, directions, rb):
    c = case(directions=directions)
    c["rb"] = rb
    equivalent(c, native, monkeypatch)


@pytest.mark.parametrize("directions", [(0, 3), (1, 2)])
def test_strict_model_h_sweep_operation_order(native, monkeypatch, directions):
    # The original 2D Numba kernel forbids fused multiply/add. Its face
    # enthalpy subtraction amplifies an unintended contraction at water cp.
    c = case(shape=(8, 6), directions=directions, sweeps=25, chunk=25)
    expected = python(c, monkeypatch)
    code, _, _, _, error = native(c)
    assert code == 0, error
    for actual, target in zip(c["state"], expected[:3]):
        np.testing.assert_array_equal(actual, target)


@pytest.mark.parametrize("fluids", [(0, 0), (0, 1), (1, 0), (1, 1)])
@pytest.mark.parametrize("shape", [(1, 1), (1, 5), (5, 1)])
def test_thin_grids_cold_start(native, monkeypatch, fluids, shape):
    c = case(shape=shape, fluids=fluids, sweeps=7, chunk=3)
    c["warm"] = False
    for key in ("a", "b"):
        c[key][4] = c[key][5] = np.empty(0)
    equivalent(c, native, monkeypatch)


def straight_case(*, sweeps=6000, accelerate=False, rb=False):
    c = case(shape=(8, 3), directions=(0, 1), sweeps=sweeps, chunk=100)
    c.update(accelerate=accelerate, rb=rb, warm=False, qtol=1e-5)
    for key, mass in (("a", .0007), ("b", -.002)):
        c[key][0][:] = .03 if key == "a" else .2
        c[key][1][:] = 25000
        c[key][2][:] = mass
        c[key][3][:] = 0
        c[key][4] = c[key][5] = np.empty(0)
    c["ks"][:] = 2
    return c


@pytest.mark.parametrize("accelerate", [False, True])
@pytest.mark.parametrize("rb", [False, True])
def test_same_budget_and_physical_acceptance(native, monkeypatch, accelerate, rb):
    c = straight_case(accelerate=accelerate, rb=rb)
    status, _, _ = equivalent(c, native, monkeypatch)
    assert status[0] == 0
    assert status[13] == 1
    assert status[1] < c["maxit"]


def test_anderson_short_budget_restores_snapshot(native, monkeypatch):
    c = straight_case(sweeps=139, accelerate=True)
    c["chunk"] = 67
    original = energy._gs_full_chunk
    signature = inspect.signature(original.py_func)
    trials, snapshots = [], []

    def record(*args, **kwargs):
        values = signature.bind(*args, **kwargs).arguments
        result = original(*args, **kwargs)
        if values["n_iters"] == 1:
            trials.append(result)
        snapshots[:] = [values["last_Ta"], values["last_Tb"]]
        return result

    monkeypatch.setattr(energy, "_gs_full_chunk", record)
    status, _, output = equivalent(c, native, monkeypatch)
    assert status[1] == 139
    assert status[0] == 1
    assert len(trials) == 4
    assert trials[1] > trials[0]  # first candidate rejected
    assert trials[3] <= trials[2]  # second candidate accepted
    for actual, target in zip(output[:2], snapshots):
        np.testing.assert_allclose(actual, target, rtol=2e-10, atol=2e-8)


def test_zero_budget_real_audit(native, monkeypatch):
    c = case(sweeps=0)
    state = copy.deepcopy(c["state"])
    status, _, _ = equivalent(c, native, monkeypatch)
    assert status[0] == 1 and status[1] == 0
    for before, after in zip(state, c["state"]):
        np.testing.assert_array_equal(before, after)


def test_missing_inflow_stops_for_flow_update(native, monkeypatch):
    c = straight_case(sweeps=6000, accelerate=True)
    # Both inlet and outlet are mathematically prescribed incoming faces.
    # Only the designated inlet has known physical temperature data.
    c["a"][2][-1] = -.0001
    status, _, _ = equivalent(c, native, monkeypatch)
    assert status[0] == 1 and status[6] > 0 and status[8] == 0


@pytest.mark.parametrize("sweeps,accepted", [(12000, False), (40000, True)])
def test_stable_heat_cannot_bypass_local_equation_gate(native, monkeypatch, sweeps, accepted):
    # Existing demonstrated stiff failure; same inputs and thresholds as the
    # Python regression, including the original unaccelerated finishing path.
    c = case(shape=(30, 2), directions=(0, 1), fluids=(0, 0), sweeps=sweeps, chunk=500)
    c["widths"] = [np.full(30, .1/30), np.full(2, .005), np.ones(1)]
    x = (np.arange(30) + .5) / 30
    initial = np.broadcast_to((350.5 - x + .15*np.sin(2*np.pi*x))[:, None], (30, 2)).copy()
    c.update(state=[initial.copy() for _ in range(3)], tin=(350.5, 349.5), qtol=.001)
    for key, mass, k in (("a", .005, .025), ("b", -.005, .018)):
        c[key][0][:] = k
        c[key][1][:] = 1e7
        c[key][2][:] = mass
        c[key][3][:] = 0
        c[key][4] = c[key][5] = np.empty(0)
    c["ks"][:] = 5
    status, _, output = equivalent(c, native, monkeypatch)
    assert status[0] == (0 if accepted else 1)
    assert status[12] == accepted
    checks = output[-1][:3*status[14]].reshape(-1, 3)
    assert np.any(checks[:, 1] == 0)
    assert (status[1] > 12000) if accepted else (status[1] == 12000)


@pytest.mark.parametrize("refine", [1, 2])
def test_cancelling_cell_residuals_are_not_an_energy_certificate(native, monkeypatch, refine):
    dx = np.repeat([.25, .75], refine) / refine
    dy = np.repeat([.4, .6], refine) / refine
    shape = (len(dx), len(dy))
    c = case(shape=shape, directions=(0, 0), sweeps=0)
    c["widths"] = [dx, dy, np.ones(1)]
    c["state"] = [np.full(shape, 300.), np.full(shape, 300.),
                  300. + np.repeat([1., -1/3], refine)[:, None] * np.ones(shape)]
    c["tin"] = (300., 300.)
    c["ks"][:] = 0
    for key in ("a", "b"):
        c[key][0][:] = 0
        c[key][1][:] = 1
        c[key][2][:] = c[key][3][:] = 0
        c[key][4] = c[key][5] = np.empty(0)
    status, metrics, _ = equivalent(c, native, monkeypatch)
    assert status[10:14] == (1, 1, 0, 0)
    assert metrics[16] == pytest.approx(.6, abs=1e-12)
    assert metrics[31] == pytest.approx(.6, abs=1e-12)
    assert metrics[34] == pytest.approx(1.2, abs=1e-12)


@pytest.mark.parametrize("cancel_at", [1, 4, 7, 13])
def test_cancel_then_recover(native, cancel_at):
    c = straight_case(accelerate=True)
    result = native(c, cancel_at=cancel_at)
    assert result[0] == 0, result[-1]
    assert result[1][0] == 2
    assert result[1][5] == 0
    assert np.isnan(result[2][1])
    recovered = native(straight_case(accelerate=True))
    assert recovered[0] == 0 and recovered[1][0] == 0


@pytest.mark.parametrize("invalid", ["extent", "alias", "nan", "fluid", "opening", "chunk", "depth"])
def test_invalid_before_state_write(native, invalid):
    c = case()
    options = {}
    if invalid == "extent":
        options["bad_size"] = 9
    elif invalid == "alias":
        options["alias"] = True
    elif invalid == "nan":
        c["a"][2][0, 0] = np.nan
    elif invalid == "fluid":
        c["fluids"] = (2, 1)
    elif invalid == "opening":
        c["a"][5][0] = 1.1
    elif invalid == "chunk":
        c["chunk"] = 0
    elif invalid == "depth":
        c["widths"][2][0] = .5
    before = copy.deepcopy(c["state"])
    result = native(c, **options)
    assert result[0] == 1, result[-1]
    for actual, expected in zip(c["state"], before):
        np.testing.assert_array_equal(actual, expected)


def test_parallel_calls_keep_state_and_cancellation_independent(native):
    with ThreadPoolExecutor(2) as pool:
        cancelled = pool.submit(native, straight_case(accelerate=True), cancel_at=4)
        successful = pool.submit(native, straight_case(accelerate=True))
        assert cancelled.result()[1][0] == 2
        assert successful.result()[1][0] == 0


def test_one_cell_water_row_independent_arithmetic(native):
    c = case(shape=(1, 1), directions=(0, 1), fluids=(1, 1), sweeps=1, chunk=1)
    c["tin"] = (350., 300.)
    c["widths"] = [np.array([.01]), np.array([.01]), np.ones(1)]
    for array, value in zip(c["state"], (350., 300., 325.)):
        array[:] = value
    c["ks"][:] = 0
    for key, mass in (("a", .0001), ("b", -.0001)):
        c[key][0][:] = 0
        c[key][1][:] = 2000
        c[key][2][:] = mass
        c[key][3][:] = 0
        c[key][4] = c[key][5] = np.empty(0)
    # Water model cp=4182 J/(kg K); hv*area=.2 W/(m K).
    expected_a = 350 + .2 * ((.2*325 + .4182*350)/.6182 - 350)
    expected_s = .5 * (expected_a + 300)
    expected_b = 300 + .2 * ((.2*expected_s + .4182*300)/.6182 - 300)
    result = native(c)
    assert result[0] == 0, result[-1]
    np.testing.assert_allclose([x.item() for x in c["state"]],
                               [expected_a, expected_b, expected_s], rtol=0, atol=1e-12)

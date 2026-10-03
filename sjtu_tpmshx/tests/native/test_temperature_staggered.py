"""Original staggered temperature + MAC numerical qualification.

Fixed before comparisons: T/residual K rtol2e-10, atol2e-8;
conservative equation powers rtol2e-8, atol2e-8 W; projection faces
rtol2e-9/atol2e-11 m/s and L2 residual <=1.01e-10.
Exit/charged iterations/frozen B/boundary faces must match exactly.
AMGCL and PyAMG hierarchies are distinct implementations of the same L.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import ctypes
import os
from pathlib import Path
import sys

import numpy as np
import pytest
from scipy.sparse import bmat
from scipy.sparse.linalg import spsolve
from sjtu_tpmshx.solvers import ltne_energy_3d as energy


@pytest.fixture(scope="module")
def native():
    root = Path(__file__).resolve().parents[3]
    platform = "windows-x64" if os.name == "nt" else "macos-arm64"
    suffix = ".dll" if os.name == "nt" else (".dylib" if sys.platform == "darwin" else ".so")
    name = ("" if os.name == "nt" else "lib") + "temperature_staggered_test" + suffix
    override = os.environ.get("TPMSHX_TEMPERATURE_STAGGERED_LIBRARY")
    library = Path(override) if override else root / ".cache/native-deps/build" / ("pilot-"+platform) / name
    if not library.is_file():
        message = f"staggered qualification library not built: {library}"
        if override or os.environ.get("TPMSHX_REQUIRE_NATIVE_DEPS_TESTS") == "1":
            pytest.fail(message)
        pytest.skip(message)
    lib = ctypes.CDLL(str(library))
    sp, dp = ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_double)
    function = lib.test_temperature_staggered
    function.argtypes = [sp, ctypes.POINTER(dp), sp, sp, dp, sp, dp, ctypes.POINTER(ctypes.c_char), ctypes.c_size_t]
    function.restype = ctypes.c_int
    projection = lib.test_mac_projection
    projection.argtypes = [sp, ctypes.POINTER(dp), sp, ctypes.c_int, sp, dp, ctypes.POINTER(ctypes.c_char), ctypes.c_size_t]
    projection.restype = ctypes.c_int

    def run(c, *, cancel_at=0, bad_size=None, alias=False):
        outputs = [np.full(c["shape"], np.nan) for _ in range(2)]
        arrays = [*c["widths"], *c["state"], c["ks"], c["source_s"], c["prescribed"], *c["a"], *c["b"], *outputs]
        assert len(arrays) == 33
        assert all(x.dtype == np.float64 and x.flags.c_contiguous for x in arrays)
        pointers = (dp*len(arrays))(*(x.ctypes.data_as(dp) for x in arrays))
        sizes = (ctypes.c_size_t*len(arrays))(*(x.size for x in arrays))
        if bad_size is not None:
            sizes[bad_size] -= 1
        if alias:
            pointers[6] = pointers[3]
        dimensions = (ctypes.c_size_t*3)(*c["shape"])
        config = (ctypes.c_size_t*8)(c["maxit"], c["chunk"], c["warm"], c["conservative"], c["rb"], *c["directions"], cancel_at)
        values = (ctypes.c_double*6)(*c["tin"], c["qtol"], *c["alpha"])
        status, metrics, error = (ctypes.c_size_t*13)(), (ctypes.c_double*16)(), ctypes.create_string_buffer(512)
        code = function(dimensions, pointers, sizes, config, values, status, metrics, error, len(error))
        return code, tuple(status), np.array(metrics), outputs, error.value.decode()

    def project(c, direct=None):
        a = c["a"]
        outputs = [np.full_like(x, np.nan) for x in a[4:7]] + [np.full(c["shape"], np.nan)]
        arrays = [*c["widths"], a[2] if direct is None else direct, a[3], *a[4:7], *outputs]
        pointers = (dp*len(arrays))(*(x.ctypes.data_as(dp) for x in arrays))
        sizes = (ctypes.c_size_t*len(arrays))(*(x.size for x in arrays))
        dimensions = (ctypes.c_size_t*3)(*c["shape"])
        status, metrics, error = (ctypes.c_size_t*3)(), (ctypes.c_double*2)(), ctypes.create_string_buffer(512)
        code = projection(dimensions, pointers, sizes, direct is not None, status, metrics, error, len(error))
        assert code == 0, error.value.decode()
        return outputs, tuple(status), np.array(metrics)

    run.project = project
    return run


def case(shape=(4, 3, 3), directions=(0, 2), sweeps=17, chunk=5):
    rng = np.random.default_rng(78961)
    widths = [rng.uniform(.005, .025, n) for n in shape]
    sides = []
    for s, direction in enumerate(directions):
        fields = [rng.uniform(.02, .4, shape), rng.uniform(3000, 15000, shape),
                  rng.uniform(.25, .4, shape), rng.uniform(900, 1500, shape)]
        velocity = [rng.uniform(-.01, .01, tuple(n+(axis == ax) for ax, n in enumerate(shape))) for axis in range(3)]
        velocity[direction//2] += .05 if direction % 2 == 0 else -.05
        face_shape = tuple(n for axis, n in enumerate(shape) if axis != direction//2)
        profile = rng.uniform(345, 360, face_shape) if s == 0 else rng.uniform(295, 305, face_shape)
        opening = rng.uniform(.1, 1, face_shape)
        opening.flat[::3] = 0
        opening.flat[-1] = 1
        sides.append([*fields, *velocity, profile, opening, np.empty(0), np.empty(0)])
    return dict(shape=shape, widths=widths, a=sides[0], b=sides[1], source_s=np.empty(0), prescribed=np.empty(0),
                state=[rng.uniform(310, 340, shape) for _ in range(3)], ks=rng.uniform(.5, 4, shape),
                tin=(355., 300.), directions=directions, maxit=sweeps, chunk=chunk,
                warm=True, conservative=True, rb=False, alpha=(.7, .7, .7), qtol=1e-4)


def python(c, monkeypatch):
    monkeypatch.setattr(energy, "_RB_ENERGY", c["rb"])
    monkeypatch.setattr(energy, "_RB_ENERGY_GATE", 0)
    a, b = c["a"], c["b"]
    zero = np.zeros(c["shape"])
    kwargs = dict(max_iter=c["maxit"], conv_chunk=c["chunk"], q_rel_tol=c["qtol"], return_info=True,
                  conservative_ltne=c["conservative"], eps_A=a[2], eps_B=b[2],
                  ufA=a[4], vfA=a[5], wfA=a[6], ufB=b[4], vfB=b[5], wfB=b[6],
                  dx_arr=c["widths"][0], dy_arr=c["widths"][1], dz_arr=c["widths"][2],
                  T_inA_profile=a[7] if a[7].size else None, T_inB_profile=b[7] if b[7].size else None,
                  inlet_mask_A=a[8] if a[8].size else None, inlet_mask_B=b[8] if b[8].size else None,
                  inlet_flux_A=a[9] if a[9].size else None, inlet_flux_B=b[9] if b[9].size else None,
                  mms_S_A_field=a[10] if a[10].size else None, mms_S_B_field=b[10] if b[10].size else None,
                  mms_S_s_field=c["source_s"] if c["source_s"].size else None,
                  Tb_prescribed=c["prescribed"] if c["prescribed"].size else None,
                  alpha_T_fA=c["alpha"][0], alpha_T_s=c["alpha"][1], alpha_T_fB=c["alpha"][2])
    if c["warm"]:
        kwargs.update(zip(("Ta_init", "Tb_init", "Ts_init"), c["state"]))
    return energy.solve_full_domain_3d(*[x.sum() for x in c["widths"]], *c["shape"], *c["tin"],
        a[0], b[0], c["ks"], a[1], b[1], a[3], b[3], a[2]+b[2], zero, zero, zero, zero, zero, zero,
        *c["directions"], **kwargs)


def equivalent(c, native, monkeypatch):
    expected = python(c, monkeypatch)
    code, status, metrics, output, error = native(c)
    assert code == 0, error
    info = expected[3]
    assert status[0] == (0 if info["converged"] else 1)
    assert status[1] == info["iterations"]
    for actual, target in zip(c["state"], expected[:3]):
        np.testing.assert_allclose(actual, target, rtol=2e-10, atol=2e-8)
    assert metrics[0] == pytest.approx(info["residual"], rel=2e-10, abs=2e-8)
    assert status[5:7] == (c["conservative"], c["conservative"] and not c["prescribed"].size)
    for side, key in enumerate(("a", "b")):
        if not status[5+side]:
            assert np.isnan(output[side]).all()
            continue
        f = c[key]
        projected = energy._project_faces_div_free(*f[4:7], f[2], f[3], *c["widths"])
        direction = c["directions"][side]
        patch_shape = tuple(n for ax, n in enumerate(c["shape"]) if ax != direction//2)
        source = f[10] if f[10].size else np.zeros(c["shape"])
        profile = f[7] if f[7].size else np.full(patch_shape, c["tin"][side])
        opening = f[8] if f[8].size else np.ones(patch_shape)
        residual, exchange, _ = energy._conservation_residual_sum(expected[side], expected[2], *projected,
            f[2], f[0], f[3], f[1], *c["widths"], direction, profile, opening, source,
            f[9] if f[9].size else None, return_field=True)
        np.testing.assert_allclose(output[side], residual, rtol=2e-8, atol=2e-8)
        target = [np.sum(residual), np.max(np.abs(residual)), np.sum(exchange),
                  info[f"eps_{'AB'[side]}_strict"], info[f"eps_{'AB'[side]}_strict_cellmax"]]
        np.testing.assert_allclose(metrics[2+7*side:7+7*side], target, rtol=2e-8, atol=2e-8)
    if c["maxit"]:
        volume = c["widths"][0][:, None, None]*c["widths"][1][None, :, None]*c["widths"][2][None, None, :]
        assert metrics[1] == pytest.approx(np.sum(c["b"][1]*(expected[2]-expected[1])*volume), rel=2e-8, abs=2e-8)
    else:
        assert np.isnan(metrics[1])
    return status, metrics, output


@pytest.mark.parametrize("directions", [(0, 2), (1, 3), (2, 4), (3, 5), (4, 1), (5, 0)])
@pytest.mark.parametrize("rb", [False, True])
@pytest.mark.parametrize("conservative", [False, True])
def test_six_directions_nonuniform_partial(native, monkeypatch, directions, rb, conservative):
    c = case(directions=directions)
    c.update(rb=rb, conservative=conservative)
    original = [x.copy() for key in ("a", "b") for x in c[key]]
    equivalent(c, native, monkeypatch)
    for actual, before in zip([x for key in ("a", "b") for x in c[key]], original):
        np.testing.assert_array_equal(actual, before)


@pytest.mark.parametrize("shape", [(1, 1, 3), (1, 4, 2), (4, 1, 2)])
@pytest.mark.parametrize("conservative", [False, True])
def test_thin_grids_cold_start(native, monkeypatch, shape, conservative):
    c = case(shape=shape)
    c.update(warm=False, conservative=conservative)
    for state in c["state"]:
        state[:] = np.nan
    for key in ("a", "b"):
        c[key][7] = np.empty(0)
        c[key][8] = np.empty(0)
    equivalent(c, native, monkeypatch)


@pytest.mark.parametrize("rb", [False, True])
@pytest.mark.parametrize("conservative", [False, True])
@pytest.mark.parametrize("freeze", [False, True])
def test_prescribed_b_mms_and_capacity(native, monkeypatch, rb, conservative, freeze):
    c = case(sweeps=43, chunk=9)
    c.update(rb=rb, conservative=conservative)
    rng = np.random.default_rng(790)
    if freeze:
        c["prescribed"] = rng.uniform(305, 320, c["shape"])
    c["source_s"] = rng.normal(0, 2000, c["shape"])
    for key in ("a", "b"):
        c[key][9] = rng.uniform(-.0003, .001, c[key][8].shape)
        c[key][10] = rng.normal(0, 2000, c["shape"])
    equivalent(c, native, monkeypatch)
    if freeze:
        np.testing.assert_array_equal(c["state"][1], c["prescribed"])


@pytest.mark.parametrize("rb", [False, True])
def test_thermal_multilevel_mac(native, monkeypatch, rb):
    c = case(shape=(9, 8, 5), sweeps=11, chunk=4)
    c["rb"] = rb
    equivalent(c, native, monkeypatch)


@pytest.mark.parametrize("rb", [False, True])
def test_complete_solve(native, monkeypatch, rb):
    c = case(sweeps=5000, chunk=100)
    c.update(rb=rb, warm=False)
    for key, direction in zip(("a", "b"), c["directions"]):
        for field, value in zip(c[key][:4], (.2, 10000, .35, 1200)):
            field[:] = value
        for axis, velocity in enumerate(c[key][4:7]):
            velocity[:] = .1 if axis == direction//2 else 0
        c[key][8][:] = 1
    status, _, _ = equivalent(c, native, monkeypatch)
    assert status[0] == 0


@pytest.mark.parametrize("conservative", [False, True])
def test_zero_budget_final_evidence(native, monkeypatch, conservative):
    c = case(sweeps=0)
    c["conservative"] = conservative
    equivalent(c, native, monkeypatch)


@pytest.mark.parametrize("cancel_at", [1, 2, 4])
def test_cancel_and_recovery(native, cancel_at):
    c = case()
    code, status, metrics, _, error = native(c, cancel_at=cancel_at)
    assert code == 0, error
    assert status[0] == 2 and status[2] == cancel_at
    assert status[5:7] == (0, 0)
    assert np.isnan(metrics[1])
    assert native(case())[0] == 0


@pytest.mark.parametrize("invalid", ["extent", "alias", "nan", "alpha", "opening", "chunk", "direction"])
def test_invalid_inputs_are_atomic(native, invalid):
    c = case()
    options = {}
    if invalid == "extent": options["bad_size"] = 13
    if invalid == "alias": options["alias"] = True
    if invalid == "nan": c["a"][3].flat[0] = np.nan
    if invalid == "alpha": c["alpha"] = (0., .7, .7)
    if invalid == "opening": c["a"][8].flat[0] = 1.1
    if invalid == "chunk": c["chunk"] = 0
    if invalid == "direction": c["directions"] = (6, 2)
    original = [x.copy() for x in c["state"]]
    code, _, _, _, _ = native(c, **options)
    assert code == 1
    for actual, before in zip(c["state"], original):
        np.testing.assert_array_equal(actual, before)


def fluxes(c, velocities):
    a = c["a"]
    coef = a[2]*a[3]
    result = []
    for axis in range(3):
        field = np.moveaxis(coef, axis, 0)
        factor = np.empty((field.shape[0]+1, *field.shape[1:]))
        factor[0], factor[-1] = field[0], field[-1]
        factor[1:-1] = .5*(field[:-1]+field[1:])
        area = np.ones(c["shape"])
        for ax in range(3):
            if axis != ax:
                dims = [1, 1, 1]; dims[ax] = -1
                area *= c["widths"][ax].reshape(dims)
        area = np.take(area, [0], axis=axis)
        result.append(np.moveaxis(factor, 0, axis)*velocities[axis]*area)
    return result


def divergence(f):
    return f[0][1:]-f[0][:-1]+f[1][:, 1:]-f[1][:, :-1]+f[2][:, :, 1:]-f[2][:, :, :-1]


@pytest.mark.parametrize("shape", [(4, 3, 3), (1, 1, 3), (9, 8, 5), (4, 3, 1)])
def test_projection_neumann_mean_and_boundary(native, shape):
    c = case(shape=shape)
    a = c["a"]
    original = [x.copy() for x in a[4:7]]
    output, status, metrics = native.project(c)
    expected = energy._project_faces_div_free(*original, a[2], a[3], *c["widths"])
    assert status[0] == 0
    assert status[1] == 0
    assert metrics[1] <= 1.01e-10
    before = divergence(fluxes(c, original))
    after = divergence(fluxes(c, output[:3]))
    assert metrics[0] == pytest.approx(before.mean(), rel=2e-12, abs=1e-15)
    np.testing.assert_allclose(after, before.mean(), atol=2e-11, rtol=0)
    assert abs(output[3].mean()) < 1e-12
    for axis in range(3):
        np.testing.assert_allclose(output[axis], expected[axis], rtol=2e-9, atol=2e-11)
        np.testing.assert_array_equal(np.take(output[axis], [0, -1], axis=axis), np.take(original[axis], [0, -1], axis=axis))
        np.testing.assert_array_equal(a[4+axis], original[axis])


def test_projection_skip(native):
    c = case()
    c["a"][2][:] = .35
    c["a"][3][:] = 1200
    for velocity in c["a"][4:7]: velocity[:] = .1
    out, status, _ = native.project(c)
    assert status == (1, 0, 0)
    for actual, expected in zip(out[:3], c["a"][4:7]): np.testing.assert_array_equal(actual, expected)


def test_projection_z_reflection(native):
    c = case(shape=(8, 7, 6))
    reflected = copy.deepcopy(c)
    reflected["widths"][2] = reflected["widths"][2][::-1].copy()
    for index in (2, 3): reflected["a"][index] = reflected["a"][index][:, :, ::-1].copy()
    for axis in range(3): reflected["a"][4+axis] = ((-1 if axis == 2 else 1)*c["a"][4+axis][:, :, ::-1]).copy()
    first, _, _ = native.project(c)
    second, _, _ = native.project(reflected)
    for axis in range(3):
        np.testing.assert_allclose(second[axis], (-1 if axis == 2 else 1)*first[axis][:, :, ::-1], rtol=2e-9, atol=2e-11)
    np.testing.assert_allclose(second[3], first[3][:, :, ::-1], rtol=2e-9, atol=2e-11)


@pytest.mark.parametrize("shape", [(4, 3, 3), (9, 8, 5)])
def test_original_bordered_fallback_operator(native, shape):
    c = case(shape=shape)
    rhs = divergence(fluxes(c, c["a"][4:7]))
    out, _, _ = native.project(c, direct=rhs)
    lap = energy._laplacian_amg_cache(*shape)["L"]
    e = np.ones((rhs.size, 1))
    expected = spsolve(bmat([[lap, e], [e.T, None]], format="csr"), np.r_[rhs.ravel(), 0])[:-1]
    expected -= expected.mean()
    np.testing.assert_allclose(out[3].ravel(), expected, rtol=2e-11, atol=2e-12)
    np.testing.assert_allclose(lap@out[3].ravel(), rhs.ravel()-rhs.mean(), rtol=2e-10, atol=2e-12)


def test_independent_instances_and_arrays(native):
    cases = [case(), case(directions=(5, 1))]
    reference = [native(copy.deepcopy(c)) for c in cases]
    with ThreadPoolExecutor(2) as pool:
        actual = list(pool.map(native, cases))
    for a, b in zip(actual, reference):
        assert a[0:2] == b[0:2]
        np.testing.assert_array_equal(a[2], b[2])

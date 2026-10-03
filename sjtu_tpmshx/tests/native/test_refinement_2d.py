"""Original 2D Richardson transfer primitives, without thermal/Q acceptance.

Fixed tolerances: split widths/endpoints exact; RGI field rtol2e-14/atol2e-12;
signed integrated faces/capacity rtol2e-14/atol1e-14 and CV divergence1e-14.
"""
import ctypes
import os
from pathlib import Path
import sys

import numpy as np
import pytest
from scipy.interpolate import RegularGridInterpolator
from sjtu_tpmshx.models.grid import split_cells, _aligned_grid, _port_fractions_1d
from sjtu_tpmshx.solvers.simple_solver import _prolong_mass_faces_2d


@pytest.fixture(scope="module")
def native():
    root = Path(__file__).resolve().parents[3]
    platform = "windows-x64" if os.name == "nt" else "macos-arm64"
    suffix = ".dll" if os.name == "nt" else (".dylib" if sys.platform == "darwin" else ".so")
    default = root / ".cache/native-deps/build" / ("pilot-"+platform) / (("" if os.name == "nt" else "lib")+"refinement_2d_test"+suffix)
    override = os.environ.get("TPMSHX_REFINEMENT_2D_LIBRARY")
    path = Path(override) if override else default
    if not path.is_file():
        message = f"native 2D refinement library not built: {path}"
        if override or os.environ.get("TPMSHX_REQUIRE_NATIVE_DEPS_TESTS") == "1": pytest.fail(message)
        pytest.skip(message)
    library = ctypes.CDLL(str(path))
    function = library.test_refinement_2d
    dp, sp = ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_size_t)
    function.argtypes = [ctypes.c_int, ctypes.POINTER(dp), sp, ctypes.POINTER(ctypes.c_char), ctypes.c_size_t]
    function.restype = ctypes.c_int

    def run(operation, dx, dy=None, fx=None, fy=None, first=None, second=None, *, bad_size=None):
        nx, nf, mf = len(dx), len(fx) if fx is not None else 0, len(fy) if fy is not None else 0
        shapes = [(2*nx,), (nf, mf), (nf+1, mf), (nf,)]
        outputs = [np.full(shapes[operation], np.nan), np.full((nf, mf+1), np.nan) if operation == 2 else np.empty(0)]
        arrays = [np.require(np.asarray(x, dtype=np.float64), requirements=['C', 'A']) if x is not None else np.empty(0)
                  for x in (dx, dy, fx, fy, first, second)] + outputs
        pointers = (dp*8)(*(x.ctypes.data_as(dp) for x in arrays))
        sizes = (ctypes.c_size_t*8)(*(x.size for x in arrays))
        if bad_size is not None: sizes[bad_size] -= 1
        error = ctypes.create_string_buffer(512)
        code = function(operation, pointers, sizes, error, len(error))
        if code: raise ValueError(error.value.decode())
        return tuple(outputs) if operation == 2 else outputs[0]
    return run


@pytest.mark.parametrize("widths", [np.array([.02]), np.array([.01, .017, .008, .04]),
    np.geomspace(.0000002, .05, 90), np.array([.091, .091]), np.full(99, .1/99)])
def test_actual_cell_bisection_keeps_each_endpoint(native, widths):
    expected = split_cells(widths)
    actual = native(0, widths)
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(np.cumsum(actual)[1::2], np.cumsum(widths))


def interpolate(dx, dy, fx, fy, field):
    x, y, xf, yf = [np.cumsum(w)-w/2 for w in (dx, dy, fx, fy)]
    points = np.stack(np.meshgrid(xf, yf, indexing="ij"), axis=-1)
    return RegularGridInterpolator((x, y), field, method="linear", bounds_error=False, fill_value=None)(points)


@pytest.mark.parametrize("shape", [(1, 1), (1, 4), (4, 1), (2, 3), (7, 9)])
@pytest.mark.parametrize("kind", ["random", "affine", "constant"])
def test_nonuniform_cell_centres_and_thin_axis_extrapolation(native, shape, kind):
    rng = np.random.default_rng(1943)
    dx, dy = [rng.uniform(.003, .035, n) for n in shape]
    fx, fy = split_cells(dx), split_cells(dy)
    x, y = np.cumsum(dx)-dx/2, np.cumsum(dy)-dy/2
    values = rng.uniform(280, 500, shape) if kind == "random" else (
        12+300*x[:, None]-140*y[None, :] if kind == "affine" else np.full(shape, 317.2))
    actual = native(1, dx, dy, fx, fy, values)
    expected = interpolate(dx, dy, fx, fy, values)
    np.testing.assert_allclose(actual, expected, rtol=2e-14, atol=2e-12)
    if shape[0] == 1: np.testing.assert_array_equal(actual[0], actual[1])
    if shape[1] == 1: np.testing.assert_array_equal(actual[:, 0], actual[:, 1])


def test_cell_extrapolation_does_not_clip_to_original_range(native):
    dx, dy = np.array([.2, .8]), np.array([.3, .7])
    fx, fy = split_cells(dx), split_cells(dy)
    field = np.array([[0., 1.], [2., 3.]])
    actual = native(1, dx, dy, fx, fy, field)
    expected = interpolate(dx, dy, fx, fy, field)
    np.testing.assert_allclose(actual, expected, rtol=2e-14, atol=2e-12)
    assert actual.min() < field.min() and actual.max() > field.max()


@pytest.mark.skipif(sys.platform != 'darwin', reason='locked macOS SciPy arithmetic qualification')
@pytest.mark.parametrize('shape', [(1, 7), (7, 1), (7, 9)])
def test_locked_rgi_corner_accumulation_order(native, shape):
    rng = np.random.default_rng(1943)
    dx, dy = [rng.uniform(.003, .035, n) for n in shape]
    fx, fy = split_cells(dx), split_cells(dy)
    field = rng.uniform(280, 500, shape)
    np.testing.assert_array_equal(native(1, dx, dy, fx, fy, field),
                                  interpolate(dx, dy, fx, fy, field))


@pytest.mark.parametrize("sign", [-1., 1.])
@pytest.mark.parametrize("imbalance", [0., .07])
def test_nonnested_mass_overlap_preserves_divergence_and_wall_faces(native, sign, imbalance):
    dx, dy = np.array([.3, .7]), np.array([.2, .3, .5])
    fx, fy = np.array([.17, .13, .2, .5]), np.array([.2, .13, .17, .21, .29])
    psi = np.array([[0., 0., 1., 1.], [0., .1, .8, 1.], [0., 0., 1., 1.]])
    mx, my = sign*np.diff(psi, axis=1), -sign*np.diff(psi, axis=0)
    mx[1, 1] += imbalance
    actual = native(2, dx, dy, fx, fy, mx, my)
    expected = _prolong_mass_faces_2d((mx, my), dx, dy, fx, fy)
    for a, b in zip(actual, expected): np.testing.assert_allclose(a, b, rtol=2e-14, atol=1e-14)
    coarse_div = mx[1:]-mx[:-1]+my[:, 1:]-my[:, :-1]
    fine_div = actual[0][1:]-actual[0][:-1]+actual[1][:, 1:]-actual[1][:, :-1]
    x, y, xf, yf = [np.r_[0., np.cumsum(w)] for w in (dx, dy, fx, fy)]
    expected_div = np.zeros_like(fine_div)
    for i in range(len(fx)):
        for j in range(len(fy)):
            for a in range(len(dx)):
                for b in range(len(dy)):
                    area = max(0., min(xf[i+1], x[a+1])-max(xf[i], x[a]))*max(0., min(yf[j+1], y[b+1])-max(yf[j], y[b]))
                    expected_div[i, j] += area*coarse_div[a, b]/(dx[a]*dy[b])
    np.testing.assert_allclose(fine_div, expected_div, rtol=0, atol=1e-14)
    np.testing.assert_array_equal(actual[0][[0, -1]][:, [0, 3, 4]], 0.)


@pytest.mark.parametrize("shape", [(1, 1), (1, 4), (4, 1), (7, 9)])
def test_random_nested_signed_faces_and_identity(native, shape):
    rng = np.random.default_rng(6157)
    dx, dy = [rng.uniform(.003, .035, n) for n in shape]
    mass = [rng.uniform(-.3, .4, (shape[0]+1, shape[1])), rng.uniform(-.2, .7, (shape[0], shape[1]+1))]
    for fx, fy in ((dx, dy), (split_cells(dx), split_cells(dy))):
        actual = native(2, dx, dy, fx, fy, *mass)
        expected = _prolong_mass_faces_2d(mass, dx, dy, fx, fy)
        for a, b in zip(actual, expected): np.testing.assert_allclose(a, b, rtol=2e-14, atol=1e-14)


def test_mass_final_boundary_uses_original_isclose_and_pin(native):
    dx, dy = np.array([.3, .7]), np.array([.4, .6])
    fx, fy = np.array([.2, .8+5e-13]), np.array([.5, .5-5e-13])
    mx, my = np.arange(6.).reshape(3, 2), np.arange(6.).reshape(2, 3)
    actual = native(2, dx, dy, fx, fy, mx, my)
    expected = _prolong_mass_faces_2d((mx, my), dx, dy, fx, fy)
    for a, b in zip(actual, expected): np.testing.assert_allclose(a, b, rtol=2e-14, atol=1e-14)
    for far in (fx+1e-9, fx*.9):
        with pytest.raises(ValueError, match="same physical domain"):
            native(2, dx, dy, far, fy, mx, my)


def test_original_counter_port_does_not_gain_closed_patch_inflow(native):
    ports = ((.0126, .01092, .02835, .01302), (.0189, .01344, .01218, .015120000000000001))
    breaks = sorted({ctr+sign*width/2 for port in ports for ctr, width in (port[:2], port[2:]) for sign in (-1, 1)})
    lo, hi = ports[1][0]-ports[1][1]/2, ports[1][0]+ports[1][1]/2
    coarse, fine = (_aligned_grid(n, .042, breaks) for n in (40, 80))
    _, profile = _port_fractions_1d(coarse, lo, hi)
    raw_fine, _ = _port_fractions_1d(fine, lo, hi)
    dx = np.array([.091, .091])
    mass = np.tile(-profile*coarse, (3, 1)), np.zeros((2, 41))
    actual = native(2, dx, coarse, dx, fine, *mass)
    expected = _prolong_mass_faces_2d(mass, dx, coarse, dx, fine)
    for a, b in zip(actual, expected): np.testing.assert_allclose(a, b, rtol=2e-14, atol=1e-14)
    assert np.all(actual[0][-1, raw_fine == 0] == 0)
    np.testing.assert_allclose(actual[0].sum(axis=1), mass[0].sum(axis=1), rtol=1e-14, atol=0)


@pytest.mark.parametrize("fine", [np.array([.1, .2, .3, .4]), np.array([.17, .13, .2, .5]),
                                  np.array([.1, .15]), np.array([.5, .5000000000001])])
@pytest.mark.parametrize("flux", [np.array([1., -2., 3.]), np.array([0., 1., 0.]), np.array([1e-16, -1e-16, 0.])])
def test_signed_inlet_capacity_cumulative_transfer_and_endpoint_clamps(native, fine, flux):
    coarse = np.array([.2, .3, .5])
    expected = np.diff(np.interp(np.r_[0., np.cumsum(fine)], np.r_[0., np.cumsum(coarse)], np.r_[0., np.cumsum(flux)]))
    actual = native(3, coarse, fx=fine, first=flux)
    np.testing.assert_allclose(actual, expected, rtol=2e-14, atol=1e-14)


@pytest.mark.parametrize("operation", [1, 2, 3])
def test_nonfinite_field_evidence_remains_for_outer_guards(native, operation):
    dx, dy = np.array([.2, .8]), np.array([.3, .7])
    fx, fy = split_cells(dx), split_cells(dy)
    with np.errstate(invalid="ignore"):
        if operation == 1:
            field = np.array([[300., np.nan], [np.inf, 320.]])
            expected = interpolate(dx, dy, fx, fy, field)
            actual = native(1, dx, dy, fx, fy, field)
        elif operation == 2:
            mx, my = np.ones((3, 2)), np.ones((2, 3))
            mx[0, 0] = np.nan; my[1, 1] = np.inf
            expected = _prolong_mass_faces_2d((mx, my), dx, dy, fx, fy)
            actual = native(2, dx, dy, fx, fy, mx, my)
        else:
            flux = np.array([np.inf, np.inf])
            expected = np.diff(np.interp(np.r_[0., np.cumsum(fx)], np.r_[0., np.cumsum(dx)], np.r_[0., np.cumsum(flux)]))
            actual = native(3, dx, fx=fx, first=flux)
    if operation == 2:
        for a, b in zip(actual, expected): np.testing.assert_allclose(a, b, equal_nan=True)
    else:
        np.testing.assert_allclose(actual, expected, equal_nan=True)


@pytest.mark.parametrize("bad", ["empty", "negative", "nonfinite", "field_extent", "duplicate_centres"])
def test_invalid_geometry_or_extent_rejected(native, bad):
    dx, dy = np.array([.2, .8]), np.array([.3, .7])
    if bad == "empty": dx = np.empty(0)
    if bad == "negative": dx[0] = -.2
    if bad == "nonfinite": dx[0] = np.inf
    if bad == "duplicate_centres": dx = np.array([1., 1e-20, 1e-20])
    with pytest.raises(ValueError):
        native(1, dx, dy, np.array([.5, .5]), np.array([.5, .5]), np.ones((len(dx), len(dy))),
               bad_size=4 if bad == "field_extent" else None)

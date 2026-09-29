"""Chunk-local thermal coefficients preserve physical rows and input refresh."""
import numpy as np
import pytest

from sjtu_tpmshx.models.tpms_props import model_h_coefficients
from sjtu_tpmshx.solvers import ltne_energy as energy


@pytest.mark.parametrize('direction', range(4))
@pytest.mark.parametrize('solid', [False, True])
def test_fixed_diffusion_matches_independent_half_cell_resistances(direction, solid):
    dx, dy = np.array([.2, .7, .3]), np.array([.1, .4])
    K = np.array([[.4, 3.], [1.3, .8], [2.7, .2]])
    fractions = np.linspace(0., .6, K.shape[1-direction//2])
    actual = energy._thermal_diffusion_rows(K, dx, dy, direction, fractions, solid)
    # Separate physical oracle: sum half-cell thermal resistances, then
    # multiply by face area. Boundary solid self terms are intentionally kept.
    for i, j in np.ndindex(K.shape):
        for face, (di, dj) in enumerate([(-1, 0), (1, 0), (0, -1), (0, 1)]):
            ni, nj = i+di, j+dj
            axis = face//2
            area, width = (dy[j], dx[i]) if axis == 0 else (dx[i], dy[j])
            if 0 <= ni < len(dx) and 0 <= nj < len(dy):
                other_width = dx[ni] if axis == 0 else dy[nj]
                expected = area / (width/(2*K[i,j]) + other_width/(2*K[ni,nj]))
            elif solid:
                expected = K[i,j]*area/width
            elif face == direction:
                expected = 2*K[i,j]*area*fractions[j if axis == 0 else i]/width
            else:
                expected = 0.
            assert actual[i,j,face] == pytest.approx(expected, rel=3e-16, abs=0)


@pytest.mark.parametrize('direction', range(4))
@pytest.mark.parametrize('fluid', ['air', 'water'])
def test_fixed_model_h_rows_match_uncached_rows_through_repeated_refresh(direction, fluid):
    rng = np.random.default_rng(917)
    shape = (4, 3)
    dx, dy = np.array([.05, .3, .1, .6]), np.array([.2, .07, .4])
    K, hv = rng.uniform(.1, 3., shape), rng.uniform(2., 9., shape)
    T = rng.uniform(290., 360., shape)
    cached = T.copy()
    Ts = rng.uniform(305., 320., shape)
    mass = (rng.uniform(-.002, .003, (5, 3)), rng.uniform(-.001, .002, (4, 4)))
    Tin = np.linspace(320., 340., shape[1-direction//2])
    fractions = np.linspace(0., .8, len(Tin))
    cp = model_h_coefficients(fluid)
    for chunk in range(2):
        if chunk:
            # Inputs can change at a chunk boundary (e.g. progress callback).
            K *= 1.2
            hv *= .8
        rows = energy._thermal_diffusion_rows(K, dx, dy, direction, fractions)
        hv_volume = hv*(dx[:,None]*dy[None,:])
        for _ in range(3):
            cap, deferred = energy._model_h_faces(
                T.copy(), mass, cp, direction, Tin, fractions, True, dx, dy)
            cached_cap, cached_deferred = energy._model_h_faces(
                cached.copy(), mass, cp, direction, Tin, fractions, True, dx, dy)
            for i, j in np.ndindex(shape):
                T[i,j] = energy._model_h_cell(
                    T, Ts, K, hv, i, j, dx, dy, direction, Tin, fractions,
                    mass, cap, deferred)
                cached[i,j] = energy._model_h_cell(
                    cached, Ts, K, hv, i, j, dx, dy, direction, Tin, fractions,
                    mass, cached_cap, cached_deferred, rows, hv_volume)
            np.testing.assert_array_equal(cached, T)


@pytest.mark.parametrize('model_h', [False, True])
def test_progress_coefficient_changes_apply_to_next_chunk(model_h):
    shape = (3, 2)
    one = np.ones(shape)
    K, hv = one*.4, one*8.
    kwargs = dict(
        max_iter=2, conv_chunk=1, dx_arr=np.array([.2, .5, .3]),
        dy_arr=np.array([.1, .4]), Ta_init=one*315., Tb_init=one*295.,
        Ts_init=one*305.)
    if model_h:
        mass = (np.full((4, 2), .01), np.zeros((3, 3)))
        kwargs.update(model_fluids=('air', 'water'), mass_flux_A=mass, mass_flux_B=mass)

    def solve(**options):
        return energy.solve_full_domain(
            1., .5, *shape, 340., 290., K, K, K, hv, hv, 2., 3., .7,
            one*.02, one*0., one*.01, one*0., 0, 0, **options)

    calls = []

    def update(done, total):
        calls.append((done, total))
        if done == 1:
            K[:] = 1.7
            hv[:] = 3.

    actual = solve(**kwargs, progress_cb=update)
    assert calls == [(1, 2), (2, 2)]
    # Independent one-chunk calls see the same before/after inputs and supply
    # public warm starts; persistent coefficients would fail this comparison.
    K[:] = .4
    hv[:] = 8.
    single = dict(kwargs, max_iter=1)
    first = solve(**single)
    K[:] = 1.7
    hv[:] = 3.
    single.update(Ta_init=first[0], Tb_init=first[1], Ts_init=first[2])
    expected = solve(**single)
    for observed, reference in zip(actual, expected):
        np.testing.assert_array_equal(observed, reference)

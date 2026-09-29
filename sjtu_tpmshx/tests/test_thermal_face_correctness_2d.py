"""Independent shared-face, series-resistance and zero-load regressions."""
import numpy as np
import pytest

from sjtu_tpmshx.solvers import ltne_energy as energy


@pytest.mark.parametrize('axis', [0, 1])
def test_signed_turning_thermal_correction_cancels(axis):
    n = 9
    coordinate = np.arange(n, dtype=float)
    temperature = (coordinate + .1 * coordinate**2)[:, None]
    flux = np.r_[np.ones(4), -2*np.ones(5)][:, None]
    if axis:
        temperature, flux = temperature.T.copy(), flux.T.copy()
    correction = energy._sou_corr_y if axis else energy._sou_corr_x
    net = sum(correction(temperature, 0 if axis else p, p if axis else 0,
                         n, float(np.sign(flux[0, p] if axis else flux[p, 0])), flux)
              for p in range(n))
    assert net == pytest.approx(0., abs=1e-12)


def test_two_layers_use_their_own_half_cell_resistances():
    dx, dy = np.array([.25, .75]), np.ones(1)
    temperature = np.array([[300.], [400.]])
    solid, conductivity, hv = np.full((2, 1), 300.), np.array([[1.], [4.]]), np.ones((2, 1))
    no_flux = (np.zeros((3, 1)), np.zeros((2, 2)))
    updated = energy._model_h_cell(
        temperature, solid, conductivity, hv, 0, 0, dx, dy,
        2, np.zeros(2), np.zeros(2), no_flux, no_flux, no_flux)
    conductance = 1 / (.125/1 + .375/4)
    expected = (conductance * 400. + .25 * 300.) / (conductance + .25)
    assert updated == pytest.approx(300. + energy.MODEL_H_RELAXATION*(expected-300.), abs=1e-12)


@pytest.mark.parametrize('rb', [False, True])
def test_solid_sweep_uses_the_same_series_resistance(rb):
    one, zero = np.ones((2, 1)), np.zeros((2, 1))
    ta, tb, ts = 300*one, 300*one, np.array([[300.], [400.]])
    dx, dy = np.array([.25, .75]), np.ones(1)
    sweep = energy._gs_full_chunk_rb if rb else energy._gs_full_chunk
    sweep(ta, tb, ts, 2, 1, dx, dy, zero, zero, np.array([[1.], [4.]]),
          one, one, one, one, one, one, zero, zero, zero, zero,
          0, 0, np.array([300.]), np.array([300.]), np.ones(1), np.ones(1),
          1, 1, 0)
    face_g = 1 / (.125/1 + .375/4)
    # Three adiabatic ghost terms retain the old temperature during this sweep;
    # both fluid-solid exchanges contribute hv*volume = .25.
    other_diagonal = 1/.25 + 2*.25 + 2*.25
    expected = (face_g*400. + other_diagonal*300.) / (face_g+other_diagonal)
    assert ts[0, 0] == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize('axis', [0, 1])
@pytest.mark.parametrize('sign', [-1., 1.])
def test_model_h_reconstructs_physical_linear_field(axis, sign):
    widths = np.array([.1, .2, .7, 1.])
    edges = np.r_[0., widths.cumsum()]
    temperature = (300. + 10*(edges[:-1]+widths/2))[:, None]
    dx, dy = widths, np.ones(1)
    if axis:
        temperature = temperature.T.copy()
        dx, dy = dy, dx
    nx, ny = temperature.shape
    mass = (np.zeros((nx+1, ny)), np.zeros((nx, ny+1)))
    mass[axis].fill(sign)
    direction = 2*axis + int(sign < 0)
    capacity, deferred = energy._model_h_faces(
        temperature, mass, (1., 0., 0., 0., 0.), direction,
        np.array([300.]), np.ones(1), True, dx, dy)
    flux = energy._model_face_values(temperature, mass, capacity, deferred,
                                     direction, np.array([300.]), np.ones(1))
    face = flux[axis][0, 2] if axis else flux[axis][2, 0]
    assert face / sign == pytest.approx(300. + 10*edges[2], abs=1e-12)


def test_zero_load_can_converge_but_drifting_zero_duty_cannot():
    one, zero = np.ones((2, 2)), np.zeros((2, 2))
    arguments = (1., 1., 2, 2, 300., 300., 1., 1., 1., 1., 0.,
                 1., 1., .8, one, zero, -one, zero, 0, 1)
    *fields, info = energy.solve_full_domain(
        *arguments, max_iter=20, conv_chunk=5, return_info=True)
    assert info['converged'] and info['iterations'] <= 10
    for field in fields:
        np.testing.assert_allclose(field, 300., atol=1e-12, rtol=0)
    *_, drifting = energy.solve_full_domain(
        *arguments, Ta_init=300*one, Tb_init=300*one, Ts_init=400*one,
        max_iter=2, conv_chunk=1, return_info=True)
    assert not drifting['converged']

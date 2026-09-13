"""Screening ports, coefficients and transported mass share physical cells."""
from dataclasses import replace
import numpy as np
import pytest

from sjtu_tpmshx.domain.portable_data import mutable_data
from sjtu_tpmshx.models.continuous_field import ContinuousFieldConfig
from sjtu_tpmshx.preprocess.api import prepare_screening_2d
from sjtu_tpmshx.solvers.backends.python.screening.two_d import build_flow, run_case
from sjtu_tpmshx.solvers.backends.python.two_d.coupling import _face_mass_fluxes_2d
from sjtu_tpmshx.models.df_projection import project_fields_to_streamwise_K_cF
from sjtu_tpmshx.df_surrogate.predict import predict_K_cF
from sjtu_tpmshx.models.tpms_calc import geometry
from sjtu_tpmshx.postprocess.screening import pressure_drop


def _case():
    cfg = dict(L_domain=.1, H_domain=.05, Nx=12, Ny=10,
               u_A=5., u_B=5., T_inA=350., T_inB=300.,
               ports_A=(.006, .021, .029, .05), ports_B=(.013, .041, .06, .093))
    fc = ContinuousFieldConfig(np.linspace(0., .1, 4), np.linspace(0., .05, 4),
        np.linspace(4., 8., 16).reshape(4, 4), np.full((4, 4), .4),
        'Diamond', 17., .1, .05)
    return prepare_screening_2d(None, cfg, fc, case_id='shared-port-grid'), fc


def test_both_streams_and_coefficients_share_the_thermal_grid():
    case, fc = _case()
    dx, dy = np.asarray(case.grid['dx']), np.asarray(case.grid['dy'])
    expected = fc.evaluate_grid(len(dx), len(dy), dx, dy)
    for key, value in zip(('L_cell_m', 't_wall_m'), expected):
        np.testing.assert_allclose(case.metadata['geometry_fields'][key], value / 1000.)
    for side, direction in (('A', 0), ('B', 3)):
        s = build_flow(case.parameters['flow'][side])
        s._set_bc()
        expected_widths = (dy, dx) if side == 'A' else (dx, dy[::-1])
        for actual, expected_width in zip((s.dx_arr, s.dy_arr), expected_widths):
            np.testing.assert_array_equal(actual, expected_width)
        native_mass = np.sum(.5 * s.eps_field[:, 0] * s.rho_field[:, 0] * s.v[:, 0] * s.dx_arr)
        mx, my = _face_mass_fluxes_2d(s, direction, .5 * case.design_fields['eps_arr'], dx, dy)
        transferred_mass = mx[0, :].sum() if side == 'A' else -my[:, -1].sum()
        assert native_mass > 0.
        assert transferred_mass == pytest.approx(native_mass, rel=1e-13, abs=0.)


def test_same_count_and_length_do_not_hide_a_different_flow_grid():
    case, _ = _case()
    parameters = mutable_data(case.parameters)
    widths = parameters['flow']['A']['initial']['dx_arr']
    parameters['flow']['A']['initial']['dx_arr'] = np.full(len(widths), widths.sum() / len(widths))
    with pytest.raises(ValueError, match='flow cell widths'):
        run_case(replace(case, parameters=parameters))


@pytest.mark.parametrize('side', ['A', 'B'])
def test_drag_projection_uses_physical_source_cells(side):
    dx, dy = np.array([.01, .02, .07]), np.array([.002, .008, .04])
    L = np.array([[4., 5., 6.], [5., 6., 7.], [6., 7., 8.]])
    t = np.full((3, 3), .4)
    stream = dx if side == 'A' else dy[::-1]
    K, cF = project_fields_to_streamwise_K_cF(L, t, 'Diamond', 17., 3, 3, 3, side,
                                            streamwise_dx=stream, source_grid=(dx, dy))
    mean_l = (L @ dy / dy.sum()) if side == 'A' else (dx @ L / dx.sum())[::-1]
    expected = np.array([predict_K_cF('Diamond', length, .4,
                                     geometry('Diamond', length, .4, 17.)['epsilon'] / 2.)
                         for length in mean_l])
    np.testing.assert_allclose(K, expected[:, 0], rtol=1e-12)
    np.testing.assert_allclose(cF, expected[:, 1], rtol=1e-12)


def test_screening_pressure_mean_uses_physical_face_area():
    p = dict(P_gauge_Pa=np.array([[10., 0.], [20., 0.]]),
             inlet_fraction=np.ones(2), outlet_fraction=np.ones(2), dx_m=np.array([.01, .09]))
    assert pressure_drop(p) == pytest.approx(19.)

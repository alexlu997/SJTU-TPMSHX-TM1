"""Exact rectangular ports and once-only area in actual staggered fluxes."""

from sjtu_tpmshx.pipelines.run_stack_3d import _build_3d_problem
from types import SimpleNamespace

import numpy as np
import pytest

from sjtu_tpmshx.models.grid_3d import _resolve_axis_map
from sjtu_tpmshx.models.field_coordinates_3d import _build_partial_masks
from sjtu_tpmshx.solvers.backends.python.three_d.flux import _face_flux_weights
from sjtu_tpmshx.solvers.simple_solver_3d import (
    SIMPLESolver3D, _build_pp_sparsity_3d, _build_outlet_frac_taper,
    _sweep_v_jit_df_3d, _sweep_v_jit_df_3d_parallel, _correct_jit_3d,
)
from sjtu_tpmshx.solvers.ltne_enthalpy_3d import face_mass_fluxes


@pytest.mark.parametrize('direction', range(6))
def test_exact_rectangular_intersection_in_every_direction(direction):
    widths = [np.array([.003, .007, .008, .012]),
              np.array([.004, .009, .017]), np.array([.011, .019])]
    f = dict(dir=direction, in_ctr=.009, in_w=.010,
             out_ctr=.029, out_w=.006,
             in_z_ctr=.014, in_z_w=.013, out_z_ctr=.001, out_z_w=.004)
    a = _resolve_axis_map(f, 4, 3, 2, .03, .03, .03, *widths)
    fi, fo = _build_partial_masks(f, a['dcross1'], a['dcross2'],
                                 a['N_cross1'], a['N_cross2'], a['is_reverse'])
    area = a['dcross1'][:, None] * a['dcross2'][None, :]
    assert np.sum(fi * area) == pytest.approx(.010 * .013, rel=1e-13)
    assert np.sum(fo * area) == pytest.approx(.004 * .003, rel=1e-13)
    assert np.any((fi > 0) & (fi < 1))


def test_narrow_full_and_zero_overlap_ports():
    d = np.full(4, .03 / 4)
    f = dict(in_ctr=.015, in_w=.01, out_ctr=.015, out_w=.03)
    fi, fo = _build_partial_masks(f, d, d, 4, 4, False)
    assert np.sum(fi * d[:, None] * d[None, :]) == pytest.approx(.00030)
    np.testing.assert_allclose(fo, 1., rtol=0, atol=1e-15)
    f.update(in_ctr=.002, in_w=1e-8)
    fi, _ = _build_partial_masks(f, d, d, 4, 4, False)
    assert np.sum(fi * d[:, None] * d[None, :]) == pytest.approx(1e-8 * .03)
    f.update(in_ctr=.04, in_w=.001)
    with pytest.raises(ValueError, match='zero cells'):
        _build_partial_masks(f, d, d, 4, 4, False)


@pytest.mark.parametrize('stage', ['serial', 'parallel', 'correct'])
def test_fractional_outlet_support_and_local_continuity(stage):
    s = SIMPLESolver3D(.03, .02, .03, 3, 2, 3, 2., 1e-5, 300., 1.,
                      eps=.6, fluid_type='incompressible')
    f = np.tile(np.array([.2, .8, 0.])[:, None], (1, 3))
    s.apply_outlet_taper()
    s.set_ports(s.inlet_rect, (.008, .018, 0., .03))
    np.testing.assert_array_equal(s.outlet_mask_ij, f > 0)
    np.testing.assert_allclose(s.outlet_coeff, f * _build_outlet_frac_taper(3, 3))
    s._pp_sparsity = _build_pp_sparsity_3d(3, 2, 3, s.outlet_mask_ij)
    kind = s._pp_sparsity['cell_kind'].reshape(3, 2, 3)
    np.testing.assert_array_equal(kind[:, -1, :] == 1, f > 0)
    s.v[:, -2, :] = 2.
    s.rho_field[:, -1, :] = 4.
    s.eps_field[:, -1, :] = .4
    if stage == 'correct':
        _correct_jit_3d(s.u, s.v, s.w, s.P, s.Pp, s.d_u, s.d_v, s.d_w,
                        s.v_inlet_field, 3, 2, 3, .5, s.rho_field, s.eps_field,
                        s.outlet_mask_ij, s.dx, s.dy, s.dz)
    else:
        sweep = _sweep_v_jit_df_3d if stage == 'serial' else _sweep_v_jit_df_3d_parallel
        sweep(s.u, s.v, s.w, s.P, s.d_v, s.v_inlet_field, 3, 2, 3,
              s.dx, s.dy, s.dz, s.rho_field, s.eps_field, s._mu_eff_field,
              s.mu_field, np.ones((2, 3)), np.ones((2, 3)), .5, 0, 0, 1, s.outlet_mask_ij)
    # South face rho*eps=1.4, north=1.6; f must not rescale the closed flux.
    np.testing.assert_allclose(s.v[:, -1, :][f > 0], 2. * 1.4 / 1.6)
    np.testing.assert_array_equal(s.v[:, -1, :][f == 0], 0.)
    s.set_ports(s.inlet_rect, (0., .03, 0., .03))
    assert s._pp_sparsity is None


@pytest.mark.parametrize('direction', range(6))
def test_actual_flux_uses_area_once_and_matches_true_h(direction):
    f = np.array([[.2, .8], [0., 1.]])
    v = np.zeros((2, 3, 2)); v[:, 0, :] = f * 3.; v[:, -1, :] = -f * 2.
    s = SimpleNamespace(v=v, rho_field=np.full((2, 2, 2), 4.),
                        eps_field=np.full((2, 2, 2), .6),
                        inlet_frac=f, outlet_frac=f,
                        dx=np.array([.01, .02]), dz=np.array([.03, .01]))
    fy = face_mass_fluxes(np.zeros((3, 2, 2)), v, np.zeros((2, 2, 3)),
                          s.rho_field, .5 * s.eps_field,
                          s.dx, np.ones(2), s.dz)[1]
    for face, j in [('real_inlet', 0), ('real_outlet', -1)]:
        w = _face_flux_weights(s, direction, face)
        np.testing.assert_allclose(w, np.abs(fy[:, j, :]))
        np.testing.assert_allclose(_face_flux_weights(s, direction, face, 'physical'), w / .3)
        np.testing.assert_allclose(_face_flux_weights(s, direction, face,
                                  eps_side_override=.2),
                                  w * (.2 / .3))


def test_pressure_reductions_use_nonuniform_face_area():
    f = np.array([[.2, .8], [0., 1.]])
    pin = np.array([[10., 20.], [900., 40.]])
    s = SimpleNamespace(P=np.stack((pin, np.zeros_like(pin)), axis=1),
                        inlet_frac=f, outlet_frac=f,
                        dx=np.array([1., 3.]), dy=np.ones(2), dz=np.array([2., 5.]),
                        rho_field=np.ones((2, 2, 2)),
                        v=np.repeat(f[:, None, :], 3, axis=1))
    expected = (10. * .4 + 20. * 4. + 40. * 15.) / (.4 + 4. + 15.)
    assert SIMPLESolver3D.extract_dP_weighted(s) == pytest.approx(expected)
    assert SIMPLESolver3D.extract_dP_face_extrap(s) == pytest.approx(2. * expected)
    assert SIMPLESolver3D.extract_dP_mass_flux_weighted(s) == pytest.approx(expected)
    s.v[0, 0, 0] *= 10.
    expected_mass = (10. * 4. + 20. * 4. + 40. * 15.) / (4. + 4. + 15.)
    assert expected_mass != pytest.approx(expected)
    s.dx *= 1e-12
    assert SIMPLESolver3D.extract_dP_mass_flux_weighted(s) == pytest.approx(expected_mass)
    # A nonuniform outlet pressure separates historical taper and geometry.
    s.P[:, -1, :] = pin / 4.
    s.outlet_coeff = f * np.array([[.7, .8], [.9, 1.]])
    expected_out_taper = (2.5 * .4 * .7 + 5. * 4. * .8 + 10. * 15.) / (
        .4 * .7 + 4. * .8 + 15.)
    assert SIMPLESolver3D.extract_dP_weighted(s) == pytest.approx(.75 * expected)
    assert SIMPLESolver3D.extract_dP_weighted(s, numerical_taper=True) == pytest.approx(
        expected - expected_out_taper)
    assert SIMPLESolver3D.extract_dP_face_extrap(s, numerical_taper=True) == pytest.approx(
        1.375 * expected + .5 * expected_out_taper)


@pytest.mark.parametrize('fluid', ['air', 'water', 'sco2'])
def test_pipeline_inlets_preserve_opening_velocity_and_mass_target(monkeypatch, fluid):
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime as stages
    from sjtu_tpmshx.preprocess.three_d.preparation import _parse_inputs_3d_cfg
    from sjtu_tpmshx.tests.test_pipeline_3d_e2e import _small_air_cfg

    cfg = _parse_inputs_3d_cfg(_small_air_cfg())
    cfg.update(fluid_type_A=fluid, fluid_type_B=fluid, u_A=.02, u_B=.03,
               T_inA=350., T_inB=300., P_inA=1e7, P_inB=1e7)
    for key in ('fluid_A_cfg', 'fluid_B_cfg'):
        cfg[key].update(in_ctr=.013, in_w=.011, out_ctr=.017, out_w=.013,
                        in_z_ctr=.014, in_z_w=.009, out_z_ctr=.015, out_z_w=.012)
    # Exercise real setup, without launching a coupled temperature solve.
    monkeypatch.setattr(stages, '_run_two_simple', lambda *a, **kw: None)
    p = _build_3d_problem(cfg)
    for solver, u, rho in ((p.sA, .02, p.rho_A), (p.sB, .03, p.rho_B)):
        f = solver.inlet_frac
        assert np.any((f > 0.) & (f < 1.))
        np.testing.assert_allclose(solver.v_inlet_field, f * u)
        area = solver.dx[:, None] * solver.dz[None, :]
        assert np.sum(f * area) == pytest.approx(.011 * .009)
        if fluid == 'sco2':
            np.testing.assert_allclose(solver._massflux_target, rho * f * u)
            solver.rho_field[:, 0, :] = 2. * rho
            solver._apply_massflux_inlet()
            np.testing.assert_allclose(solver.rho_field[:, 0, :] * solver.v_inlet_field,
                                       rho * f * u)
        assert np.sum(solver.rho_field[:, 0, :] * solver.v_inlet_field * area) == pytest.approx(
            rho * u * .011 * .009)

"""Independent geometry/zero-load regressions for the 3D thermal routes."""
import numpy as np
import pytest

from sjtu_tpmshx.solvers import _kernels_ltne_3d as kernels
from sjtu_tpmshx.solvers import ltne_enthalpy_3d as enthalpy
from sjtu_tpmshx.solvers.ltne_energy_3d import solve_full_domain_3d


@pytest.mark.parametrize('axis', range(3))
@pytest.mark.parametrize('insulated', [False, True])
def test_true_h_two_layer_resistance_and_first_sweeps(axis, insulated):
    shape = [1, 1, 1]; shape[axis] = 2
    widths = [np.ones(n) for n in shape]; widths[axis] = np.array([1., 3.])
    one = np.ones(shape)
    T = np.array([300., 301.]).reshape(shape)
    K = np.array([1., 0. if insulated else 3.]).reshape(shape)
    # Independent series resistance: 0.5/1 + 1.5/3 = 1 K/W.
    conductance = 0. if insulated else 1.
    expected_flux = np.array([conductance, -conductance]).reshape(shape)
    np.testing.assert_allclose(enthalpy._conduction_source(T, K, *widths), expected_flux)
    zeros = tuple(np.zeros(tuple(n + (d == axis) for d, n in enumerate(shape)))
                  for axis in range(3))
    h = T.copy()
    clips = enthalpy._fluid_enthalpy_sweep(
        h, T, one*300., one, T, K, one, *zeros, 300., *widths, 1., 0., 1e6)
    expected_first = 300. + conductance/(1. + conductance)
    assert clips == 0
    assert h.flat[0] == pytest.approx(expected_first, abs=1e-12)
    solid = T.copy()
    enthalpy._solid_temperature_sweep(
        solid, one*300, one*300, one, one, one*300, one*300,
        one*300, one*300, one, one*0., K, *widths, 1.)
    assert solid.flat[0] == pytest.approx(expected_first, abs=1e-12)


@pytest.mark.parametrize('axis', range(3))
@pytest.mark.parametrize('sign', [-1., 1.])
def test_nonuniform_linear_temperature_reconstructs_actual_face(axis, sign):
    widths = [np.ones(2) for _ in range(3)]
    widths[axis] = np.array([.1, .2, .4, .3])
    shape = [len(w) for w in widths]
    reshaped = [1, 1, 1]; reshaped[axis] = 4
    centres = np.cumsum(widths[axis]) - widths[axis]/2.
    T = np.broadcast_to((300.+2*centres).reshape(reshaped), shape).copy()
    faces = tuple(np.zeros(tuple(n + (d == ax) for d, n in enumerate(shape)))
                  for ax in range(3))
    np.moveaxis(faces[axis], axis, 0)[2] = .1*sign
    up = 1 if sign > 0. else 2
    face_temperature = 300. + 2.*sum(widths[axis][:2])
    up_temperature = 300. + 2.*centres[up]
    face_fn = (kernels._sou_face_x_cons, kernels._sou_face_y_cons, kernels._sou_face_z_cons)[axis]
    left = [0, 0, 0]; left[axis] = 1
    right = left.copy(); right[axis] = 2
    actual = face_fn(T, *left, 4, 0., .1*sign, widths[axis])
    assert actual == pytest.approx(-.1*sign*(face_temperature-up_temperature), abs=1e-13)
    opposite = face_fn(T, *right, 4, .1*sign, 0., widths[axis])
    assert actual + opposite == pytest.approx(0., abs=1e-14)
    coeff = (2., 0., 0., 300., 300.)
    patch = tuple(n for d, n in enumerate(shape) if d != axis)
    capacity, deferred = kernels._model_h_faces(
        T, faces, coeff, axis*2, np.full(patch, 300.), np.ones(patch), *widths)
    actual_flux = np.moveaxis(capacity[axis], axis, 0)[2]*up_temperature + np.moveaxis(deferred[axis], axis, 0)[2]
    np.testing.assert_allclose(actual_flux, .1*sign*2.*(face_temperature-300.), rtol=0., atol=2e-14)


def _uniform_args(nz=2):
    shape = (2, 2, nz)
    zero = np.zeros(shape)
    return dict(L=1., H=1., D=1., Nx=2, Ny=2, Nz=nz, T_inA=300., T_inB=300.,
                K_ffA=.2, K_ffB=.2, K_ss=1., h_vA=1., h_vB=1.,
                rho_cp_fA=1., rho_cp_fB=1., epsilon=.7,
                ucA=zero, vcA=zero, wcA=zero, ucB=zero, vcB=zero, wcB=zero,
                dir_A=0, dir_B=1, max_iter=20, conv_chunk=2, return_info=True)


@pytest.mark.parametrize('axis', range(3))
@pytest.mark.parametrize('sign', [-1., 1.])
def test_end_cell_sou_reconstructs_linear_face_and_cancels(axis, sign):
    widths = np.array([.1, .2, .4, .3])
    centres = np.cumsum(widths) - widths/2.
    shape = [1, 1, 1]; shape[axis] = len(widths)
    temperature = (300.+2.*centres).reshape(shape)
    face = 1 if sign > 0 else 3
    up = 0 if sign > 0 else 3
    left = [0, 0, 0]; left[axis] = face-1
    right = left.copy(); right[axis] = face
    function = (kernels._sou_face_x_cons, kernels._sou_face_y_cons, kernels._sou_face_z_cons)[axis]
    expected = -.1*sign*2.*(widths[:face].sum()-centres[up])
    actual = function(temperature, *left, 4, 0., .1*sign, widths)
    assert actual == pytest.approx(expected, abs=1e-13)
    assert actual + function(temperature, *right, 4, .1*sign, 0., widths) == pytest.approx(0., abs=1e-14)
    # The separate nonconservative research stencil retains its end-cell FOU.
    assert function(temperature, *left, 4, 0., .1*sign, widths, False) == 0.
    peak = np.array([300., 310., 300., 310.]).reshape(shape)
    assert function(peak, *left, 4, 0., .1*sign, widths) == 0.


@pytest.mark.parametrize('hv_b', [0., 1., 1e-12])
def test_zero_load_requires_two_observations_then_converges(hv_b):
    args = _uniform_args(); args['h_vB'] = hv_b
    *fields, info = solve_full_domain_3d(**args)
    assert info['converged'] and info['iterations'] == 4
    for field in fields:
        np.testing.assert_allclose(field, 300., rtol=0., atol=1e-12)
    args['max_iter'] = 2
    assert not solve_full_domain_3d(**args)[3]['converged']


def test_zero_b_heat_duty_does_not_bypass_temperature_stability():
    args = _uniform_args()
    args.update(T_inA=400., h_vB=0., max_iter=4,
                Ta_init=np.full((2, 2, 2), 400.), Tb_init=np.full((2, 2, 2), 300.),
                Ts_init=np.full((2, 2, 2), 300.))
    assert not solve_full_domain_3d(**args)[3]['converged']


@pytest.mark.parametrize('option,value', [('alpha_T', .2), ('alpha_T', -1.),
                                         ('alpha_T_s', .2), ('alpha_T_fA', .2), ('alpha_T_fB', .2)])
def test_nz1_explicit_relaxation_is_rejected(option, value):
    args = _uniform_args(1); args[option] = value
    with pytest.raises(ValueError, match='Nz==1.*relaxation'):
        solve_full_domain_3d(**args)


@pytest.mark.parametrize('source', ['mms_S_A_field', 'mms_S_B_field', 'mms_S_s_field'])
def test_cell_centred_nonzero_source_is_rejected(source):
    args = _uniform_args(); args[source] = np.ones((2, 2, 2))
    with pytest.raises(ValueError, match='MMS sources require staggered'):
        solve_full_domain_3d(**args)
    args[source].fill(0.)
    assert solve_full_domain_3d(**args)[3]['converged']


def cold_water_case(swap=False):
    from sjtu_tpmshx.tests.enthalpy_3d_reference import uniform_face_mass_flux
    shape = (2, 1, 1)
    one = np.ones(shape)
    fluids = ('sco2', 'water') if swap else ('water', 'sco2')
    temperatures = (300., 273.5) if swap else (273.5, 300.)
    pressures = (12e6, 2e5) if swap else (2e5, 12e6)
    return dict(Nx=2, Ny=1, Nz=1, dx=np.full(2, .01), dy=np.array([.01]), dz=np.array([1.]),
                eps_arr=one*.7, K_ss=one*3.5, h_vA_field=one*1000., h_vB_field=one*1000.,
                T_inA=temperatures[0], T_inB=temperatures[1], P_A=pressures[0], P_B=pressures[1],
                fluid_A=fluids[0], fluid_B=fluids[1],
                mass_flux_A=uniform_face_mass_flux(shape, .1, 0),
                mass_flux_B=uniform_face_mass_flux(shape, .1, 1),
                Ta_init=one*temperatures[0], Tb_init=one*temperatures[1], Ts_init=one*np.mean(temperatures),
                n_outer=40, n_sweep=3, tol=1e-5, coupled_energy_tol=.001, equation_energy_tol=.001)


@pytest.mark.parametrize('swap', [False, True])
def test_legal_cold_water_converges_without_artificial_heating(swap):
    fields = enthalpy.solve_ltne_enthalpy_3d_pipeline(**cold_water_case(swap))
    water = fields[1 if swap else 0]
    info = fields[3]
    assert info['converged']
    assert 273.5 <= water.min() < water.max() < 274.
    assert sum(info['enthalpy_clip_counts']['total']) == 0
    assert info['equation_energy_balance']['ratio'] < .001


@pytest.mark.parametrize('swap', [False, True])
def test_legal_cold_warm_start_is_inside_numerical_bracket(swap):
    args = cold_water_case(swap)
    side = 'B' if swap else 'A'
    args['T_in'+side] = 274.5
    args.update(h_vA_field=args['eps_arr']*0., h_vB_field=args['eps_arr']*0., n_outer=1, n_sweep=1)
    args['mass_flux_A'] = tuple(f*0. for f in args['mass_flux_A'])
    args['mass_flux_B'] = tuple(f*0. for f in args['mass_flux_B'])
    *fields, info = enthalpy.solve_ltne_enthalpy_3d_pipeline(**args)
    np.testing.assert_allclose(fields[1 if swap else 0], 273.5, rtol=0., atol=1e-9)
    assert sum(info['enthalpy_clip_counts']['total']) == 0

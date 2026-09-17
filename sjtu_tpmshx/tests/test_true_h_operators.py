"""Controlled physical solutions for the production true-enthalpy operators."""
import numpy as np
import pytest

from sjtu_tpmshx.solvers import ltne_enthalpy_3d as ent
from sjtu_tpmshx.solvers.ltne_enthalpy_2d import solve_enthalpy_2d


def sweep(h, temperature, solid, cp, dh, hv, faces, inlet, widths):
    return ent._fluid_enthalpy_sweep(
        h, temperature, solid, cp, h.copy(), dh, hv, *faces,
        inlet, *widths, 1., -1e9, 1e9)


def test_isothermal_pressure_gradient_has_no_fourier_heat():
    t = np.full((2, 1, 1), 400.)
    pressure = np.array([9e6, 8.99e6]).reshape(t.shape)
    h = ent._prop_field('H', t, pressure, 'sco2')
    cp, k = ent._prop_field(('C', 'L'), t, pressure, 'sco2')
    initial = h.copy()
    assert abs(h[0,0,0] - h[1,0,0]) > 50.
    faces = ent._uniform_face_mass_flux(t.shape, 0., 0)
    for _ in range(4):
        sweep(h, t, t, cp, .337265*k/cp, np.zeros_like(t), faces,
              float(h[0,0,0]), (np.full(2,.0035), np.ones(1), np.ones(1)))
    np.testing.assert_allclose(h, initial, rtol=0, atol=1e-8)


def test_constant_property_fixed_solid_matches_exponential_and_energy():
    errors = []
    for n in (16, 32, 64):
        shape = (n, 1, 1)
        t = np.full(shape, 400.)
        h = 1000.*t
        widths = (np.full(n, .1/n), np.array([.1]), np.array([.1]))
        faces = ent._uniform_face_mass_flux(shape, .01, 0)
        sweep(h, t, np.full(shape, 300.), np.full(shape, 1000.),
              np.zeros(shape), np.full(shape, 20000.), faces, 400000., widths)
        tout = h[-1,0,0]/1000.
        # Continuous target derived from mdot*cp*dT/dx = -Hv*A*(T-Ts).
        expected = 300. + 100.*np.exp(-2.)
        errors.append(abs(tout-expected))
        q_source = np.sum(20000.*(h/1000.-300.)) * .1/n * .01
        assert q_source == pytest.approx(.01*(400000.-h[-1,0,0]), rel=1e-12)
    assert 1.8 < errors[0]/errors[1] < 2.1
    assert 1.8 < errors[1]/errors[2] < 2.1


def test_sweep_reports_actual_limited_updates():
    t=np.full((2,1,1),300.)
    h=1000.*t
    clips=ent._fluid_enthalpy_sweep(h,t,np.full_like(t,500.),np.full_like(t,1000.),
        h.copy(),np.zeros_like(t),np.ones_like(t),
        *ent._uniform_face_mass_flux(t.shape,0.,0),300000.,
        np.ones(2),np.ones(1),np.ones(1),1.,200000.,400000.)
    assert clips == 2
    np.testing.assert_array_equal(h,np.full_like(h,400000.))


@pytest.mark.parametrize('direction', range(6))
def test_adiabatic_variable_pressure_transports_constant_h(direction):
    shape = (3, 4, 2)
    pressure = np.linspace(9e6, 8.9e6, np.prod(shape)).reshape(shape)
    hin = ent._h_scalar(400., 9e6, 'sco2')
    h = np.full(shape, hin+5000.)
    cp = np.full(shape, 1400.)
    faces = ent._uniform_face_mass_flux(shape, .01, direction)
    widths = tuple(np.full(n,.01) for n in shape)
    for _ in range(5):
        sweep(h, np.full(shape,400.), np.full(shape,300.), cp,
              np.zeros(shape), np.zeros(shape), faces, hin, widths)
    np.testing.assert_allclose(h, hin, rtol=0, atol=1e-9)
    t = ent._T_of_h_field(h, pressure, 'sco2')
    assert np.ptp(t) > .1
    assert abs(ent._boundary_enthalpy_duty(h, hin, faces)) < 1e-8


def test_2d_extrusion_preserves_fields_and_scales_duty():
    shape = (4,3,1)
    thickness = .04
    dx,dy=np.full(4,.01),np.full(3,.01)
    fa=ent._uniform_face_mass_flux(shape,.01,0)
    fb=ent._uniform_face_mass_flux(shape,.01,1)
    cell=np.ones(shape)
    a=ent.solve_ltne_enthalpy_3d_pipeline(
        *shape,dx,dy,np.array([thickness]),cell*.7,cell*3.5,
        cell*1e5,cell*1e5,.01,.01,380.,340.,12e6,12e6,0,1,
        mass_flux_A=fa,mass_flux_B=fb,n_sweep=3,tol=1e-5,
        coupled_energy_tol=.001, equation_energy_tol=.001)
    b=solve_enthalpy_2d(
        380.,340.,12e6,12e6,
        tuple(f[...,0]/thickness for f in fa[:2]),
        tuple(f[...,0]/thickness for f in fb[:2]),
        1e5,1e5,3.5,.35,.35,dx,dy,P_inA=12e6,P_inB=12e6,
        max_iter=3000,tol=.001)
    assert a[3]['converged'] and b[3]['converged']
    for x,y in zip(a[:3],b[:3]):
        np.testing.assert_allclose(x[...,0],y,rtol=0,atol=1e-7)
    assert a[3]['Q_A'] == pytest.approx(thickness*b[3]['Q_A'],rel=1e-8)


def test_exact_energy_failure_finishes_on_heos_without_table_cycle(monkeypatch):
    real_eos=ent._T_of_h_field
    backends=[]
    def biased_lookup(*args,**kwargs):
        value=real_eos(*args,**kwargs)
        if 'iteration' in kwargs.get('where',''):
            table=kwargs.get('lookup') is not None
            backends.append(table)
            # Controlled interpolation error: final physics still uses HEOS.
            if table: value=value+.005
        return value
    monkeypatch.setattr(ent,'_T_of_h_field',biased_lookup)
    cell=np.ones((3,1,1))
    *_,info=ent.solve_ltne_enthalpy_3d_pipeline(
        3,1,1,np.full(3,.01),np.array([.01]),np.array([.01]),
        cell*.7,cell*3.5,cell*1e5,cell*1e5,.01,.01,
        380.,340.,12e6,12e6,0,1,n_sweep=25,n_outer=200,
        tol=1e-8,coupled_energy_tol=1e-6,equation_energy_tol=1e-6)
    assert info['converged'] and info['equation_energy_balance']['ratio'] <= 1e-6
    assert info['_native_state']['sco2_enthalpy_eos']['heos_polish']
    assert True in backends and False in backends
    assert not any(backends[backends.index(False):])

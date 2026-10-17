"""Explicit initial arrays for native SIMPLE test inputs."""
from types import SimpleNamespace

import numpy as np

from sjtu_tpmshx.models.grid import _port_fractions_1d, _port_overlap_1d
from sjtu_tpmshx.models.tpms_calc import air_viscosity


def make_2d(*, shape=(6, 10), fluid="incompressible", partial=False,
            variable=True, stretched=True, uniform_inlet=False):
    nx, ny = shape
    dx = np.linspace(.8, 1.2, nx) if stretched else np.ones(nx)
    dy = np.linspace(1.2, .8, ny) if stretched else np.ones(ny)
    dx *= .036 / dx.sum()
    dy *= .080 / dy.sum()
    rho, mu, velocity = (1.2, 1.8e-5, .7) if fluid == "ideal_gas" else (997., .0009, .004)
    s = SimpleNamespace(Nx=nx, Ny=ny, dx_arr=dx, dy_arr=dy, eps=.6,
        rho=rho, mu=mu, fluid_type=fluid, P_ref_abs=101325., R_gas=287.05,
        alpha_rho=.3, cf_aniso=0., v_inlet=velocity, _rho_inlet_ref=rho,
        _K_arr=np.full(ny, 1e-7), _cF_arr=np.full(ny, 35.),
        _K_field2d=None, _cF_field2d=None)
    for name, value in (("eps_field", .6), ("rho_field", rho),
                        ("mu_field", mu), ("T_field", 300.)):
        setattr(s, name, np.full(shape, value))
    s.rho = float(s.rho_field.mean())
    if fluid == "ideal_gas":
        s.mu_field = np.ascontiguousarray(air_viscosity(s.T_field))
    s._mu_eff_field = s.mu_field / s.eps_field
    for name in ("u", "d_u"):
        setattr(s, name, np.zeros((nx + 1, ny)))
    for name in ("v", "d_v"):
        setattr(s, name, np.zeros((nx, ny + 1)))
    s.P, s.Pp = np.zeros(shape), np.zeros(shape)
    inlet = (.004, .025) if partial else (0., .036)
    outlet = (.009, .031) if partial else (0., .036)
    s.inlet_geom_frac, s.inlet_frac = _port_fractions_1d(dx, *inlet, uniform=uniform_inlet)
    s.outlet_geom_frac, s.outlet_frac = _port_fractions_1d(dx, *outlet)
    s.outlet_u_frac = _port_overlap_1d(dx, *outlet, staggered=True)
    s._inlet_taper_flux_scale = 1.
    if np.any(s.inlet_frac != s.inlet_geom_frac):
        geometric = float(np.sum(s.inlet_geom_frac * dx))
        effective = float(np.sum(s.inlet_frac * dx))
        if effective > 1e-30 and geometric > 0.:
            s._inlet_taper_flux_scale = geometric / effective
    s.v_inlet_field = np.full(nx, velocity) * s._inlet_taper_flux_scale
    s.v[:, 0] = s.v_inlet_field * s.inlet_frac
    s.v[:, ny] = np.where(s.outlet_geom_frac > 0., s.v[:, ny-1], 0.)
    if variable:
        x, y = np.meshgrid(np.linspace(0., 1., nx), np.linspace(0., 1., ny), indexing="ij")
        s.eps_field = np.ascontiguousarray(.52 + .08*x + .025*y)
        s.rho_field *= 1. + .04*x - .02*y
        s.mu_field *= 1. + .05*x + .03*y
        s._mu_eff_field = np.ascontiguousarray(s.mu_field / s.eps_field)
        s._K_field2d = np.ascontiguousarray(1e-7*(.9+.2*x+.1*y))
        s._cF_field2d = np.ascontiguousarray(35.*(.9+.1*x+.2*y))
    return s


def make_3d(shape=(5, 7, 4), *, variable=True, partial=False,
            fluid="incompressible", sou=False):
    nx, ny, nz = shape
    widths = [np.linspace(.8, 1.2, n) for n in shape]
    for width, length in zip(widths, (.036, .080, .025)):
        width *= length / width.sum()
    dx, dy, dz = widths
    rho, mu, velocity = (1.2, 1.8e-5, .7) if fluid == "ideal_gas" else (997., .0009, .004)
    s = SimpleNamespace(Nx=nx, Ny=ny, Nz=nz, dx=dx, dy=dy, dz=dz,
        rho=rho, mu=mu, eps=.6, T_in=300., v_inlet=velocity,
        fluid_type=fluid, P_ref_abs=101325., R_gas=287.05,
        alpha_u=.5, alpha_p=.2, alpha_rho=.3, use_sou_momentum=sou,
        track_momentum_residual=True, pyamg_rebuild_every=100,
        pyamg_rebuild_drift_thresh=.05)
    for name, value in (("eps_field", .6), ("rho_field", rho), ("mu_field", mu),
                        ("T_field", 300.), ("K_arr", 1e-7), ("cF_arr", 35.)):
        setattr(s, name, np.full(shape, value))
    s._mu_eff_field = s.mu_field / s.eps_field
    for axis, velocity_name in enumerate("uvw"):
        extent = list(shape)
        extent[axis] += 1
        setattr(s, velocity_name, np.zeros(extent))
        setattr(s, "d_" + velocity_name, np.zeros(extent))
    s.P, s.Pp = np.zeros(shape), np.zeros(shape)
    full = (0., float(dx.sum()), 0., float(dz.sum()))
    inlet = (.004, .029, .002, .020) if partial else full
    outlet = (.008, .033, .005, .024) if partial else full
    xi, zi = (_port_overlap_1d(w, *p) for w, p in ((dx, inlet[:2]), (dz, inlet[2:])))
    xo, zo = (_port_overlap_1d(w, *p) for w, p in ((dx, outlet[:2]), (dz, outlet[2:])))
    s.inlet_frac, s.outlet_frac = np.outer(xi, zi), np.outer(xo, zo)
    s.v_inlet_field = velocity * s.inlet_frac
    s.v[:, 0, :] = s.v_inlet_field
    s.outlet_mask_ij = s.outlet_frac > 0.
    s.outlet_u_frac = np.outer(_port_overlap_1d(dx, *outlet[:2], staggered=True), zo)
    s.outlet_w_frac = np.outer(xo, _port_overlap_1d(dz, *outlet[2:], staggered=True))
    if variable:
        x, y, z = np.meshgrid(*(np.linspace(0., 1., n) for n in shape), indexing="ij")
        s.eps_field = np.ascontiguousarray(.52 + .06*x + .025*y + .015*z)
        s.rho_field *= 1. + .04*x - .02*y + .01*z
        s.mu_field *= 1. + .05*x + .03*y + .02*z
        s._mu_eff_field = np.ascontiguousarray(s.mu_field/s.eps_field)
        s.K_arr *= .9 + .2*x + .1*y + .05*z
        s.cF_arr *= .9 + .1*x + .2*y + .03*z
    return s


def f2_settings(solver):
    """Read controls for the native qualification bridge."""
    return SimpleNamespace(**{target: getattr(solver, source, default)
        for target, source, default in (
            ('mom_tol', 'mom_tol', 1e-4),
            ('mass_local_tol', 'mass_local_tol', 1e-6),
            ('mass_global_tol', 'mass_global_tol', 1e-6),
            ('backflow_max', 'f2_backflow_max', .01),
            ('n_confirm', 'f2_n_confirm', 2),
            ('mom_every', 'f2_mom_every', 5),
            ('vtol', 'f2_velocity_check_tol', 1e-4),
            ('stall_window', 'f2_stall_window', 60),
            ('stall_ratio', 'f2_stall_ratio', 1e-3))})

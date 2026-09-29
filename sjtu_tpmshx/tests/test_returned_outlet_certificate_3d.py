"""The final outlet closure and F2 certificate describe the returned state."""
import numpy as np
import pytest

from sjtu_tpmshx.solvers import simple_solver_3d as module
from sjtu_tpmshx.tests.test_f2_convergence_3d import _small_f2


def _outlet_net(s):
    """Independent six-face mass balance of the final streamwise cells."""
    er = s.rho_field * s.eps_field
    west = np.concatenate((er[:1, -1], .5*(er[:-1, -1]+er[1:, -1]))) * s.u[:-1, -1]
    east = np.concatenate((.5*(er[:-1, -1]+er[1:, -1]), er[-1:, -1])) * s.u[1:, -1]
    bottom = np.concatenate((er[:, -1, :1], .5*(er[:, -1, :-1]+er[:, -1, 1:])), axis=1) * s.w[:, -1, :-1]
    top = np.concatenate((.5*(er[:, -1, :-1]+er[:, -1, 1:]), er[:, -1, -1:]), axis=1) * s.w[:, -1, 1:]
    south = .5*(er[:, -2]+er[:, -1]) * s.v[:, -2]
    north = er[:, -1] * s.v[:, -1]
    return ((east-west)*s.dy[-1]*s.dz[None, :]
            +(top-bottom)*s.dx[:, None]*s.dy[-1]
            +(north-south)*s.dx[:, None]*s.dz[None, :])


def test_max_iter_return_closes_latest_density_and_remeasures_momentum(monkeypatch):
    s = _small_f2(3)
    s.eps_field[:] = np.linspace(.5, .8, s.P.size).reshape(s.P.shape)
    s.update_T_field(np.linspace(300., 500., s.P.size).reshape(s.P.shape))
    observed = {}
    update = s._update_density

    def density():
        update()
        observed['before_close_net'] = _outlet_net(s)
    monkeypatch.setattr(s, '_update_density', density)
    assert s.solve(max_iter=1, verbose=False) == (False, 1)
    assert np.max(np.abs(observed['before_close_net'])) > 1e-10
    np.testing.assert_allclose(_outlet_net(s), 0., atol=1e-18)
    momentum, _ = s._momentum_residual(s.Nx, s.Ny, s.Nz, s.dx, s.dy, s.dz, 0, 1)
    assert s.final_res_mom == pytest.approx(momentum, rel=1e-13)
    rho_eps = np.ascontiguousarray(s.rho_field*s.eps_field)
    local, _ = module._mass_res_solved_jit_3d(s.u, s.v, s.w, s.Nx, s.Ny, s.Nz,
        s.dx, s.dy, s.dz, rho_eps, np.zeros_like(s._pp_sparsity['cell_kind']))
    mi, mo, backflow = module._mass_global_jit_3d(s.v, s.Nx, s.Ny, s.Nz, s.dx, s.dz, rho_eps)
    assert s.final_res_mass_local == local
    assert s.final_res_mass_global == module.global_mass_residual(mi, mo)
    assert s.outlet_backflow_frac == backflow
    assert s.exit_reason == 'max_iter'


@pytest.mark.parametrize('reason,post_ok,expected', [
    ('stall', True, False), ('tol', False, False), ('tol', True, True),
])
def test_return_requires_original_and_post_closure_gates(monkeypatch, reason, post_ok, expected):
    s = _small_f2(3)
    monkeypatch.setattr(module.F2Monitor, 'should_eval_momentum', lambda *a: True)
    monkeypatch.setattr(module.F2Monitor, 'submit', lambda *a: reason)
    observations = iter([0., 0. if post_ok else 1.])
    monkeypatch.setattr(s, '_momentum_residual', lambda *a: (next(observations), {}))
    monkeypatch.setattr(module, '_mass_res_solved_jit_3d', lambda *a: (0., 0))
    monkeypatch.setattr(module, '_mass_global_jit_3d', lambda *a: (1., 1., 0.))
    assert s.solve(max_iter=1, verbose=False) == (expected, 1)
    assert s.exit_reason == ('post_closure' if reason == 'tol' and not post_ok else reason)
    assert s.f2_cert_post_rescale_ok is post_ok


@pytest.mark.parametrize('metric', ['mom', 'local', 'global', 'backflow'])
def test_nonfinite_post_closure_observation_is_not_success(monkeypatch, metric):
    s = _small_f2(3)
    monkeypatch.setattr(module.F2Monitor, 'should_eval_momentum', lambda *a: True)
    monkeypatch.setattr(module.F2Monitor, 'submit', lambda *a: 'tol')
    mom = iter([0., np.nan if metric == 'mom' else 0.])
    local = iter([0., np.nan if metric == 'local' else 0.])
    flux = iter([(1., 1., 0.), (1., np.nan if metric == 'global' else 1.,
                               np.nan if metric == 'backflow' else 0.)])
    monkeypatch.setattr(s, '_momentum_residual', lambda *a: (next(mom), {}))
    monkeypatch.setattr(module, '_mass_res_solved_jit_3d', lambda *a: (next(local), 1))
    monkeypatch.setattr(module, '_mass_global_jit_3d', lambda *a: next(flux))
    assert s.solve(max_iter=1, verbose=False) == (False, 1)
    assert s.exit_reason == 'nonfinite'
    assert s.f2_cert_post_rescale_ok is False

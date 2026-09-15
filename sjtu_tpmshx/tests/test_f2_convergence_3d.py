"""F2 convergence mode for the 3D SIMPLE solver (ledger C6 / C7).

`convergence_mode='f2'` replaces the legacy exit — `tol` on a mass residual that
ledger C6 showed to be an outlet-pin artifact, plus LowReExit's velocity
criterion — with three independent gates (momentum, solved-cell mass, global
boundary mass), each with its own tolerance, confirmed over consecutive checks.

The load-bearing test is `test_velocity_static_does_not_terminate`. It encodes
the single thing that was wrong with the first F2 design (caught in codex
review): LowReExit TERMINATES on a static velocity field, at a momentum residual
of 1.8e-3..1.5e-2 with the residual still falling. Simply flipping its verdict to
converged=False would have turned a premature SUCCESS into a premature FAILURE —
the solve would still stop at ~90 iterations and never reach the real gate. In
F2 a static field only TRIGGERS a check.
"""
import numpy as np
import pytest

from sjtu_tpmshx.solvers.simple_solver_3d import SIMPLESolver3D


def _make_solver(Nx=8, Ny=12, Nz=4, v_inlet=3.0, **kw):
    K = np.full((Ny, Nz), 3.0e-8)
    cF = np.full((Ny, Nz), 250.0)
    s = SIMPLESolver3D(
        Lx=0.02, Ly=0.03, Lz=0.01, Nx=Nx, Ny=Ny, Nz=Nz,
        rho=1.18, mu=1.85e-5, T_in=300.0, v_inlet=v_inlet,
        eps=0.72, K_arr=K, cF_arr=cF, fluid_type='ideal_gas')
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_f2_is_the_default():
    s = _make_solver()
    conv, n = s.solve(max_iter=3000, verbose=False)
    assert conv and s.convergence_mode == 'f2'
    assert len(s.mass_local_residuals) == n
    assert s.final_res_mom < 1e-4


def test_f2_exits_on_tol_with_all_three_gates_met():
    s = _make_solver(convergence_mode='f2', mom_tol=1e-4,
                     mass_local_tol=1e-6, mass_global_tol=1e-6)
    conv, n = s.solve(max_iter=3000, verbose=False)

    assert conv is True
    assert s.exit_reason == 'tol', \
        f"F2 must exit on the residual gate, got {s.exit_reason!r}"
    assert s.final_res_mom < 1e-4
    assert s.final_res_mass_local < 1e-6
    assert s.final_res_mass_global < 1e-6
    # Keep the separate legacy mass diagnostic; local outlet closure need not
    # leave its historical boundary-artifact floor.
    assert len(s.residuals) == n
    assert np.isfinite(s.final_res)


def test_velocity_static_does_not_terminate():
    # Force every iterate to count as velocity-static: it must trigger checks,
    # without stopping before the momentum and mass equations meet their gates.
    s = _make_solver(f2_velocity_check_tol=float('inf'), f2_stall_window=3000)
    conv, n = s.solve(max_iter=10, verbose=False)
    assert not conv and n == 10
    early_mom = s.final_res_mom
    assert early_mom > 1e-4
    conv, n = s.solve(max_iter=3000, verbose=False)
    assert conv and n > 10 and s.exit_reason == 'tol'
    assert s.final_res_mom < min(1e-4, early_mom / 10.)


def test_f2_rejects_anderson():
    """Anderson mutates u/v/w/P/rho after the Picard step, gates its candidate on
    the C6-falsified mass artifact, and its rollback does not restore rho_field
    exactly. None of that is compatible with a residual-gated exit — fail loud
    rather than silently produce a residual that describes a discarded state."""
    s = _make_solver(convergence_mode='f2', use_anderson=True)
    with pytest.raises(ValueError, match="use_anderson"):
        s.solve(max_iter=10)


@pytest.mark.parametrize('mode', ['legacy', 'momentum'])
def test_f2_rejects_retired_or_unknown_mode(mode):
    s = _make_solver(convergence_mode=mode)
    with pytest.raises(ValueError, match="convergence_mode"):
        s.solve(max_iter=10)


def test_each_gate_can_hold_the_exit_open():
    """All three gates are required. Driving any ONE of them to an unreachable
    tolerance must prevent the 'tol' exit — otherwise that gate is decorative.

    The unreachable value is 0.0, not a tiny number. All three residuals are
    non-negative, so `R < 0.0` is strictly impossible — whereas `R < 1e-30` is
    NOT: the global mass residual reaches EXACTLY zero at convergence (the
    outlet BC extrapolates a conserved eps*rho*v and the pp solve makes the
    interior telescope, so mdot_out == mdot_in bit-for-bit). A first draft of
    this test used 1e-30 and the global gate passed it legitimately — the
    residual really was zero, and the test was wrong, not the gate.
    """
    base = dict(convergence_mode='f2', mom_tol=1e-4,
                mass_local_tol=1e-6, mass_global_tol=1e-6)
    s = _make_solver(**base)
    s.solve(max_iter=1500)
    assert s.exit_reason == 'tol', "precondition: the base config converges"
    n_base = len(s.residuals)

    for gate in ('mom_tol', 'mass_local_tol', 'mass_global_tol'):
        cfg = dict(base)
        cfg[gate] = 0.0                        # strictly unreachable (R >= 0)
        s = _make_solver(**cfg)
        conv, n = s.solve(max_iter=400)
        assert conv is False, f"{gate} did not hold the exit open"
        assert s.exit_reason in ('max_iter', 'stall'), \
            f"{gate}: unexpected exit {s.exit_reason!r}"

    # Fourth gate (2026-07-13): outlet backflow. backflow_frac >= 0 always,
    # so a threshold of -1.0 is strictly unreachable — same pattern as the
    # 0.0 tolerances above. (The default 0.01 is inert on every measured
    # baseline: backflow is exactly 0 there.)
    cfg = dict(base)
    cfg['f2_backflow_max'] = -1.0
    s = _make_solver(**cfg)
    conv, n = s.solve(max_iter=400)
    assert conv is False, "f2_backflow_max did not hold the exit open"
    assert s.exit_reason in ('max_iter', 'stall'), \
        f"f2_backflow_max: unexpected exit {s.exit_reason!r}"

    # And each gate is load-bearing in the ordinary regime too: tightening it
    # (without making it impossible) must delay the exit, not be ignored.
    for gate, tight in (('mom_tol', 1e-9),
                        ('mass_local_tol', 1e-12),
                        ('mass_global_tol', 1e-30)):
        cfg = dict(base)
        cfg[gate] = tight
        s = _make_solver(**cfg)
        s.solve(max_iter=1500)
        assert len(s.residuals) > n_base, (
            f"tightening {gate} from {base[gate]:g} to {tight:g} did not delay "
            f"the exit ({len(s.residuals)} vs {n_base}) — the gate is being "
            "ignored")


def test_n_confirm_requires_consecutive_passes():
    """A single lucky iterate is not convergence. With n_confirm=1 the solve may
    stop on the first passing check; with n_confirm=3 it must take at least two
    more checks."""
    kw = dict(convergence_mode='f2', mom_tol=1e-4,
              mass_local_tol=1e-6, mass_global_tol=1e-6)
    s1 = _make_solver(f2_n_confirm=1, **kw)
    s1.solve(max_iter=3000)
    s3 = _make_solver(f2_n_confirm=3, **kw)
    s3.solve(max_iter=3000)

    assert s1.exit_reason == s3.exit_reason == 'tol'
    assert len(s3.residuals) >= len(s1.residuals) + 2, (
        f"n_confirm=3 exited after {len(s3.residuals)} iters vs "
        f"{len(s1.residuals)} for n_confirm=1 — the confirm streak is not "
        "actually being required")


def test_mom_every_does_not_change_the_answer():
    """The momentum residual is READ-ONLY, so evaluating it every iteration or
    every 5 must land on the same solution — the schedule can only shift WHEN we
    notice convergence, never what we converge to. Worst case: exiting up to
    (mom_every - 1) iterations late."""
    kw = dict(convergence_mode='f2', mom_tol=1e-4,
              mass_local_tol=1e-6, mass_global_tol=1e-6)
    s1 = _make_solver(f2_mom_every=1, **kw)
    s1.solve(max_iter=3000)
    s5 = _make_solver(f2_mom_every=5, **kw)
    s5.solve(max_iter=3000)

    assert s1.exit_reason == s5.exit_reason == 'tol'
    assert abs(len(s5.residuals) - len(s1.residuals)) <= 5
    # Same fixed point, to well inside the gate tolerance.
    for a, b in ((s1.u, s5.u), (s1.v, s5.v), (s1.w, s5.w)):
        scale = max(float(np.abs(a).max()), 1e-30)
        assert float(np.abs(a - b).max()) / scale < 1e-3


def test_backflow_fraction_is_reported():
    """The global mass gate is a single signed scalar: positive and negative
    outlet fluxes can cancel inside it and hide a recirculating outlet. The
    backflow fraction must be exposed alongside so that cancellation is visible.
    """
    s = _make_solver(convergence_mode='f2')
    s.solve(max_iter=1500)
    assert hasattr(s, 'outlet_backflow_frac')
    assert 0.0 <= s.outlet_backflow_frac <= 1.0
    assert s.outlet_backflow_frac == pytest.approx(0.0, abs=1e-12), \
        "a healthy forward outflow must show no backflow"


def test_solved_cell_mass_excludes_the_dirichlet_outlet_row():
    """The solved-cell mass residual must select on `cell_kind`, not on a row
    index: a partial / tapered outlet pins only SOME cells of the last row, and
    the unpinned ones DO have a continuity equation that must be counted."""
    from sjtu_tpmshx.solvers._kernels_simple_3d import _mass_res_solved_jit_3d
    s = _make_solver(convergence_mode='f2')
    # Block half the outlet face -> those cells are walls, not Dirichlet pins.
    s.set_ports(s.inlet_rect, (s.Lx / 2, s.Lx, 0., s.Lz))
    s.solve(max_iter=800)

    kind = s._pp_sparsity['cell_kind']
    n_pinned = int((kind == 1).sum())
    assert n_pinned == int(s.outlet_mask_ij.sum()), \
        "only the OPEN outlet cells may be pinned"
    assert n_pinned < s.Nx * s.Nz, "precondition: this is a partial outlet"

    rho_eps = np.ascontiguousarray(s.rho_field * s.eps_field)
    _, n_counted = _mass_res_solved_jit_3d(
        s.u, s.v, s.w, s.Nx, s.Ny, s.Nz, s.dx, s.dy, s.dz, rho_eps, kind)
    assert n_counted <= s.Nx * s.Ny * s.Nz - n_pinned
    # The blocked half of the last row is a WALL cell: still solved, still counted.
    assert n_counted > (s.Nx * s.Ny * s.Nz) - n_pinned - s.Nx * s.Nz


def _small_f2(dim):
    if dim == 2:
        from sjtu_tpmshx.tests.test_f2_convergence_2d import _make
        return _make(Nx=4, Ny=4, convergence_mode='f2')
    return _make_solver(Nx=4, Ny=4, Nz=3, convergence_mode='f2',
                        use_coarse_bootstrap=False)


def _solver_module(dim):
    from sjtu_tpmshx.solvers import simple_solver, simple_solver_3d
    return simple_solver if dim == 2 else simple_solver_3d


@pytest.mark.parametrize('dim,field', [
    (dim, field) for dim in (2, 3)
    for field in ('u', 'v', 'P', 'rho_field', 'T_field') + (('w',) if dim == 3 else ())])
@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
@pytest.mark.parametrize('stage', ['entry', 'iteration'])
def test_nonfinite_actual_state_cannot_be_certified(monkeypatch, dim, field, bad, stage):
    s = _small_f2(dim)
    closed = []
    if dim == 2:
        monkeypatch.setattr(s, '_enforce_mass_conservation', lambda **kw: closed.append(True))

    def corrupt():
        getattr(s, field).flat[0] = bad

    if stage == 'entry':
        corrupt()
        # Entry rejection must precede kernels, including the optional 3D bootstrap.
        def forbidden(*args, **kwargs):
            pytest.fail('invalid F2 input reached a solver kernel/bootstrap')
        module = _solver_module(dim)
        monkeypatch.setattr(module, '_sweep_u_jit_df' if dim == 2 else '_sweep_u_jit_df_3d', forbidden)
        if dim == 3:
            from sjtu_tpmshx.solvers import coarse_bootstrap_3d
            s.use_coarse_bootstrap = True
            monkeypatch.setattr(coarse_bootstrap_3d, 'bootstrap_simple_3d', forbidden)
    else:
        original = s._update_density

        def update():
            original()
            corrupt()

        monkeypatch.setattr(s, '_update_density', update)
    assert s.solve(max_iter=1, verbose=False) == (False, 0 if stage == 'entry' else 1)
    assert s.exit_reason == 'nonfinite'
    _assert_invalid_final_diagnostics(s)
    if dim == 2:
        assert s.f2_cert_post_rescale_ok is False
        assert not closed


@pytest.mark.parametrize('dim', [2, 3])
@pytest.mark.parametrize('index', range(5))
@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
def test_nonfinite_scalar_breaks_confirmation(dim, index, bad):
    from types import SimpleNamespace
    from sjtu_tpmshx.solvers._solve_common import F2Monitor
    monitor = F2Monitor(SimpleNamespace(), (np.zeros(2),)*dim, min_iter=0)
    assert monitor.submit(1, 0., 0., 0., 0., 0.) is None
    values = [0.]*5
    values[index] = bad
    assert monitor.submit(2, *values) == 'nonfinite'
    assert monitor.submit(3, 0., 0., 0., 0., 0.) is None
    assert monitor.submit(4, 0., 0., 0., 0., 0.) == 'tol'


@pytest.mark.parametrize('dim,index', [(dim, i) for dim in (2, 3) for i in range(2*dim)])
@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
def test_nonfinite_momentum_raw_is_not_a_zero(monkeypatch, dim, index, bad):
    s = _small_f2(dim)
    raw = [0., 1.]*dim
    raw[index] = bad
    monkeypatch.setattr(_solver_module(dim), f'_mom_res_jit_{dim}d', lambda *a: tuple(raw))
    if dim == 2:
        value, record = s._momentum_residual(s.Nx, s.Ny, s.dx_arr, s.dy_arr, None, None)
    else:
        value, record = s._momentum_residual(s.Nx, s.Ny, s.Nz, s.dx, s.dy, s.dz, 0, 0)
    assert not np.isfinite(value)
    np.testing.assert_equal(record['num'], raw[::2])
    np.testing.assert_equal(record['den'], raw[1::2])


@pytest.mark.parametrize('dim', [2, 3])
@pytest.mark.parametrize('index', range(3))
@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
def test_nonfinite_global_flux_stops_before_momentum_schedule(monkeypatch, dim, index, bad):
    s = _small_f2(dim)
    raw = [1., 1., 0.]
    raw[index] = bad
    monkeypatch.setattr(_solver_module(dim), f'_mass_global_jit_{dim}d', lambda *a: tuple(raw))
    assert s.solve(max_iter=1, verbose=False) == (False, 1)
    assert s.exit_reason == 'nonfinite'
    assert s.mom_residuals == []  # Do not force an unscheduled momentum assembly.
    _assert_invalid_final_diagnostics(s)
    if index == 2:
        np.testing.assert_equal(s.outlet_backflow_frac, bad)


@pytest.mark.parametrize('field', ['u', 'v', 'P', 'rho_field', 'T_field'])
@pytest.mark.parametrize('reason', ['tol', 'stall', None])
def test_nonfinite_after_2d_closeout_cannot_be_certified(monkeypatch, field, reason):
    s = _small_f2(2)
    module = _solver_module(2)
    monkeypatch.setattr(module.F2Monitor, 'should_eval_momentum', lambda *a: True)
    monkeypatch.setattr(module.F2Monitor, 'submit', lambda *a: reason)
    monkeypatch.setattr(s, '_momentum_residual', lambda *a: (0., {}))
    monkeypatch.setattr(module, '_mass_res_solved_jit_2d', lambda *a: (0., 1))
    monkeypatch.setattr(module, '_mass_global_jit_2d', lambda *a: (1., 1., 0.))

    def close(**kwargs):
        getattr(s, field).flat[-1] = np.nan

    monkeypatch.setattr(s, '_enforce_mass_conservation', close)
    assert s.solve(max_iter=1, verbose=False) == (False, 1)
    assert s.exit_reason == 'nonfinite'
    assert s.f2_cert_post_rescale_ok is False
    _assert_invalid_final_diagnostics(s)


@pytest.mark.parametrize('dim', [2, 3])
@pytest.mark.parametrize('mode', ['unknown', 'unsupported'])
def test_nonfinite_does_not_hide_configuration_error(dim, mode):
    s = _small_f2(dim)
    s.P.flat[0] = np.nan
    options = {}
    if mode == 'unknown':
        s.convergence_mode = 'invalid'
    elif dim == 2:
        options['coupling'] = 'simpler'
    else:
        s.use_anderson = True
    error = TypeError if dim == 2 and mode == 'unsupported' else ValueError
    with pytest.raises(error, match='convergence_mode|coupling|use_anderson'):
        s.solve(max_iter=1, verbose=False, **options)


@pytest.mark.parametrize('dim', [2, 3])
def test_nonfinite_input_does_not_poll_cancellation(dim):
    s = _small_f2(dim)
    s.P.flat[0] = np.nan
    calls = []

    def cancel():
        calls.append(True)
        return True

    assert s.solve(max_iter=1, verbose=False, cancel_check=cancel) == (False, 0)
    assert calls == []
    assert s.exit_reason == 'nonfinite'
    assert np.isnan(s.P.flat[0])
    _assert_invalid_final_diagnostics(s)


@pytest.mark.parametrize('dim', [2, 3])
@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
def test_nonfinite_momentum_observation_exits_solver(monkeypatch, dim, bad):
    s = _small_f2(dim)
    s.track_momentum_residual = True
    module = _solver_module(dim)
    monkeypatch.setattr(module.F2Monitor, 'should_eval_momentum', lambda *a: True)
    raw = (bad, 1.) * dim
    monkeypatch.setattr(module, f'_mom_res_jit_{dim}d', lambda *a: raw)
    assert s.solve(max_iter=1, verbose=False) == (False, 1)
    assert s.exit_reason == 'nonfinite'
    np.testing.assert_equal(s.mom_residuals[-1]['num'], raw[::2])
    _assert_invalid_final_diagnostics(s)


@pytest.mark.parametrize('metric', ['mom', 'local', 'global', 'backflow'])
def test_nonfinite_post_closeout_observation_rejects_2d(monkeypatch, metric):
    s = _small_f2(2)
    module = _solver_module(2)
    monkeypatch.setattr(module.F2Monitor, 'should_eval_momentum', lambda *a: True)
    monkeypatch.setattr(module.F2Monitor, 'submit', lambda *a: 'tol')
    mom = iter([0., np.nan if metric == 'mom' else 0.])
    local = iter([0., np.nan if metric == 'local' else 0.])
    fluxes = iter([(1., 1., 0.),
                   (1., np.nan if metric == 'global' else 1.,
                    np.nan if metric == 'backflow' else 0.)])
    monkeypatch.setattr(s, '_momentum_residual', lambda *a: (next(mom), {}))
    monkeypatch.setattr(module, '_mass_res_solved_jit_2d', lambda *a: (next(local), 1))
    monkeypatch.setattr(module, '_mass_global_jit_2d', lambda *a: next(fluxes))
    assert s.solve(max_iter=1, verbose=False) == (False, 1)
    assert s.exit_reason == 'nonfinite'
    assert s.f2_cert_post_rescale_ok is False
    _assert_invalid_final_diagnostics(s)


def test_nonfinite_exit_is_rejected_by_3d_result_consumer(monkeypatch):
    from sjtu_tpmshx.tests.test_convergence_truth_table import _cheap_3d, _run_3d_stack
    from sjtu_tpmshx.solvers._solve_common import f2_nonfinite_exit
    original = SIMPLESolver3D.solve

    def failed(self, *args, **kwargs):
        # Keep the existing finite flow; isolate the returned status only.
        _, iterations = original(self, *args, **kwargs)
        return f2_nonfinite_exit(self, iterations)

    monkeypatch.setattr(SIMPLESolver3D, 'solve', failed)
    result = _run_3d_stack(_cheap_3d())
    detail = result['convergence_detail']
    assert detail['simple_exit_A'] == 'nonfinite'
    assert detail['simple_ok'] is False
    assert result['solver_converged'] is False
    for key in ('final_res', 'final_res_mom', 'final_res_mass_local',
                'final_res_mass_global', 'outlet_backflow_frac', 'res_norm_ref'):
        assert np.isnan(detail['simple_A'][key])


def test_nonfinite_bootstrap_return_is_rejected_before_main_iteration(monkeypatch):
    from sjtu_tpmshx.solvers import coarse_bootstrap_3d
    s = _small_f2(3)
    s.use_coarse_bootstrap = True

    def bootstrap(solver, **kwargs):
        solver.P.flat[0] = np.nan
        return {'applied': False}

    def forbidden(*args, **kwargs):
        pytest.fail('invalid bootstrap return reached the main sweep')

    monkeypatch.setattr(coarse_bootstrap_3d, 'bootstrap_simple_3d', bootstrap)
    monkeypatch.setattr(_solver_module(3), '_sweep_u_jit_df_3d', forbidden)
    assert s.solve(max_iter=1, verbose=False) == (False, 0)
    assert s.exit_reason == 'nonfinite'
    _assert_invalid_final_diagnostics(s)


@pytest.mark.parametrize('dim,stage', [(2, 'entry'), (3, 'entry'), (3, 'bootstrap')])
@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
def test_nonfinite_restart_resets_current_diagnostics(monkeypatch, dim, stage, bad):
    import ast
    from pathlib import Path
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime as run_stack_3d_stages

    if dim == 2:
        from sjtu_tpmshx.tests.test_f2_convergence_2d import _make
        s = _make(convergence_mode='f2')
    else:
        s = _make_solver(convergence_mode='f2', use_coarse_bootstrap=False)
    assert s.solve(max_iter=3000, verbose=False)[0] is True
    assert s.exit_reason == 'tol'
    assert s.final_res_mom is not None
    history = list(s.mom_residuals)
    if stage == 'bootstrap':
        from sjtu_tpmshx.solvers import coarse_bootstrap_3d
        # Explicit cold-start request on the reused instance; retain diagnostics.
        s.residuals.clear()
        s.use_coarse_bootstrap = True

        def bootstrap(solver, **kwargs):
            solver.P.flat[0] = bad
            return {'applied': False}

        monkeypatch.setattr(coarse_bootstrap_3d, 'bootstrap_simple_3d', bootstrap)
    else:
        s.P.flat[0] = bad
    assert s.solve(max_iter=1, verbose=False) == (False, 0)
    assert s.exit_reason == 'nonfinite'
    assert np.isnan(s.final_res)
    np.testing.assert_equal(s.P.flat[0], bad)
    assert s.mom_residuals == history
    # Execute the actual nested result projection without rerunning thermal PDEs.
    tree = ast.parse(Path(run_stack_3d_stages.__file__).read_text(encoding='utf-8'))
    projection = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef) and n.name == '_simple_detail')
    namespace = {}
    exec(compile(ast.Module(body=[projection], type_ignores=[]), '<_simple_detail>', 'exec'), namespace)
    detail = namespace['_simple_detail'](s)
    assert detail['exit_reason'] == 'nonfinite'
    for key in ('final_res_mom', 'final_res_mass_local', 'final_res_mass_global',
                'outlet_backflow_frac', 'res_norm_ref'):
        assert np.isnan(detail[key])
    if dim == 2:
        assert s.f2_cert_post_rescale_ok is False


def _assert_invalid_final_diagnostics(s):
    for key in ('final_res', 'final_res_mom', 'final_res_mass_local',
                'final_res_mass_global', 'outlet_backflow_frac'):
        assert not np.isfinite(float(getattr(s, key))), key
    if hasattr(s, 'res_norm_ref'):
        assert not np.isfinite(s.res_norm_ref)


@pytest.mark.parametrize('dim,stage', [
    (2, 'density'), (3, 'density'), (2, 'momentum'), (3, 'momentum'),
    (2, 'tol'), (2, 'stall'), (2, 'max_iter')])
@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
def test_later_nonfinite_invalidates_final_diagnostics(monkeypatch, dim, stage, bad):
    from copy import deepcopy
    s = _small_f2(dim)
    s.track_momentum_residual = True
    module = _solver_module(dim)
    monkeypatch.setattr(module.F2Monitor, 'should_eval_momentum', lambda *a: True)
    saved = {}

    def snapshot():
        for key in ('final_res_mom', 'final_res_mass_local',
                    'final_res_mass_global', 'outlet_backflow_frac'):
            assert np.isfinite(getattr(s, key)), key
        assert s.mom_residuals  # A real earlier F2 evaluation, not seeded attributes.
        saved['mom'] = deepcopy(s.mom_residuals)
        saved['local'] = list(s.mass_local_residuals)
        saved['global'] = list(s.mass_global_residuals)

    if stage == 'density':
        original = s._update_density

        def update():
            original()
            if s.mom_residuals:
                snapshot()
                s.P.flat[0] = bad

        monkeypatch.setattr(s, '_update_density', update)
    elif stage == 'momentum':
        name = f'_mom_res_jit_{dim}d'
        original = getattr(module, name)

        def momentum(*args):
            if s.mom_residuals:
                snapshot()
                return (bad, 1.) * dim
            return original(*args)

        monkeypatch.setattr(module, name, momentum)
    else:
        if stage != 'max_iter':
            monkeypatch.setattr(module.F2Monitor, 'submit',
                                lambda self, it, *a: stage if it == 2 else None)
        original = s._enforce_mass_conservation

        def close(**kwargs):
            original(**kwargs)
            snapshot()
            s.P.flat[0] = bad

        monkeypatch.setattr(s, '_enforce_mass_conservation', close)

    assert s.solve(max_iter=2, verbose=False) == (False, 2)
    assert s.exit_reason == 'nonfinite'
    _assert_invalid_final_diagnostics(s)
    assert saved
    np.testing.assert_equal(s.mom_residuals[:len(saved['mom'])], saved['mom'])
    assert s.mass_local_residuals[:len(saved['local'])] == saved['local']
    assert s.mass_global_residuals[:len(saved['global'])] == saved['global']
    if stage == 'momentum':
        np.testing.assert_equal(s.mom_residuals[-1]['num'], (bad,) * dim)
    else:
        np.testing.assert_equal(s.P.flat[0], bad)
    if dim == 2:
        assert s.f2_cert_post_rescale_ok is False


@pytest.mark.parametrize('backend', ['2d', '3d', '3d_rb'])
@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
def test_pressure_invalid_after_correction_precedes_density(monkeypatch, backend, bad):
    dim = 2 if backend == '2d' else 3
    s = _small_f2(dim)
    assert s.fluid_type == 'ideal_gas'
    module = _solver_module(dim)
    if dim == 3:
        monkeypatch.setattr(module, '_should_parallelize', lambda *a: backend == '3d_rb')
    name = '_correct_jit' if dim == 2 else '_correct_jit_3d'
    original = getattr(module, name)

    def correct(*args):
        original(*args)
        for field in (s.u, s.v) + ((s.w,) if dim == 3 else ()):
            assert np.isfinite(field).all()
        s.P.flat[0] = bad

    reached = []
    update = s._update_density

    def density():
        update()
        reached.append((float(s.P.flat[0]), getattr(s, '_p_clip_hits', 0)))

    monkeypatch.setattr(module, name, correct)
    monkeypatch.setattr(s, '_update_density', density)
    result = s.solve(max_iter=1, verbose=False)
    assert not reached, f'density overwrote/consumed invalid pressure: {reached}'
    assert result == (False, 1)
    assert s.exit_reason == 'nonfinite'
    np.testing.assert_equal(s.P.flat[0], bad)
    assert s.residuals == []
    _assert_invalid_final_diagnostics(s)


@pytest.mark.parametrize('mode_source', ['attribute', 'environment'])
@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
@pytest.mark.parametrize('field', ['P', 'v_inlet', 'v_outlet'])
@pytest.mark.parametrize('fluid_type', ['ideal_gas', 'incompressible'])
def test_prolongated_nonfinite_reaches_parent_without_reset(
        monkeypatch, mode_source, bad, field, fluid_type):
    from sjtu_tpmshx.solvers import coarse_bootstrap_3d
    s = _make_solver(Nx=8, Ny=8, Nz=8, convergence_mode='f2', use_coarse_bootstrap=True,
                     fluid_type=fluid_type)
    if mode_source == 'environment':
        del s.convergence_mode
        monkeypatch.setenv('TPMSHX_CONV_MODE', 'f2')
    solve = SIMPLESolver3D.solve
    coarse = []

    def coarse_solve(self, **kwargs):
        # Keep the real bootstrap/prolongation, without a coarse PDE campaign.
        coarse.append(self)
        self.residuals.append(0.0)
        return True, 1

    zoom = coarse_bootstrap_3d._trilinear_zoom

    def prolongate(arr, shape):
        result = zoom(arr, shape)
        target = coarse[0].P if field == 'P' else coarse[0].v
        if arr is target:
            result[0, -1 if field == 'v_outlet' else 0, 0] = bad
        return result

    reached = []
    update = s._update_density

    def density():
        update()
        reached.append(float(s.P.flat[0]))

    monkeypatch.setattr(SIMPLESolver3D, 'solve', coarse_solve)
    monkeypatch.setattr(coarse_bootstrap_3d, '_trilinear_zoom', prolongate)
    monkeypatch.setattr(s, '_update_density', density)
    result = solve(s, max_iter=1, verbose=False)
    assert not reached, f'fine density consumed prolongated bad {field}: {reached}'
    assert result == (False, 0)
    assert s.exit_reason == 'nonfinite'
    target = s.P if field == 'P' else s.v
    np.testing.assert_equal(target[0, -1 if field == 'v_outlet' else 0, 0], bad)
    assert s.residuals == []
    assert s._coarse_bootstrap_info == dict(
        applied=True, coarse_iters=1, coarse_converged=True,
        coarse_residual=0.0, coarse_shape=(4, 4, 4))
    _assert_invalid_final_diagnostics(s)


@pytest.mark.parametrize('dim', [2, 3])
def test_nonfinite_iteration_does_not_add_cancel_checkpoint(monkeypatch, dim):
    s = _small_f2(dim)
    calls = []

    def cancel():
        calls.append(True)
        # 2D's original iteration checkpoint continues; another poll would cancel.
        return dim == 3 or len(calls) > 1

    update = s._update_density

    def density():
        update()
        s.P.flat[0] = np.nan

    monkeypatch.setattr(s, '_update_density', density)
    assert s.solve(max_iter=1, verbose=False, cancel_check=cancel) == (False, 1)
    assert len(calls) == (1 if dim == 2 else 0)
    assert s.exit_reason == 'nonfinite'
    assert np.isnan(s.P.flat[0])
    _assert_invalid_final_diagnostics(s)


@pytest.mark.parametrize('dim,completed', [(2, 0), (3, 24)])
def test_finite_f2_cancels_at_original_checkpoint(dim, completed):
    from sjtu_tpmshx.domain.cancellation import CancelledError
    from sjtu_tpmshx.solvers._solve_common import f2_state_is_finite
    s = _small_f2(dim)
    s.mom_tol = 0.0  # Hold convergence open until the original checkpoint.
    calls = []

    def cancel():
        calls.append(len(s.residuals))
        return True

    with pytest.raises(CancelledError):
        s.solve(max_iter=25, verbose=False, cancel_check=cancel)
    assert calls == [completed]
    assert len(s.residuals) == completed
    assert f2_state_is_finite(s, (s.u, s.v) + ((s.w,) if dim == 3 else ()))

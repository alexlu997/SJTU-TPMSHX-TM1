"""Convergence truth table — `ComputeResult.converged` must be an honest AND.

Before 2026-07-12 the verdict lied in several ways:

* 3D  — `run_outer_coupling`'s `(last_iter, converged)` was DISCARDED at the
  call site, so a run that burned every outer iteration with ΔT still bouncing
  reported success as long as SIMPLE and the final LTNE inner pass converged.
  (2D already captured the outer verdict; the two dims disagreed.)
* 3D  — `max_outer_ltne=0` → zero iterations → `_ltne_info` empty → the
  `not _ltne_info` short-circuit yielded True on a run that solved nothing.
* 3D  — the `Nz==1` delegation in `ltne_energy_3d` hard-coded
  `{'converged': True}` regardless of what the delegated 2D solve did.
* 2D  — `e_info['converged']` (the LTNE inner verdict) was captured from
  `solve_full_domain(..., return_info=True)` and then never read.
* 2D  — a NaN blow-up patched over with inlet T left `converged` untouched.
* both — the post-solve compressible envelope verdict lived on its own key and
  was not ANDed into the headline flag.

The gates, in both dims: SIMPLE ∧ LTNE-inner ∧ outer-coupling ∧ finite-fields
∧ envelope. Each is exposed individually under `convergence_detail` so a caller
can see WHICH gate failed.

These tests assert the *verdict wiring*, not physics numbers.
"""

import numpy as np
import pytest

from sjtu_tpmshx.runs._case_template import build_cfg          # noqa: E402
from sjtu_tpmshx.pipelines.stages_3d import _run_3d_stack      # noqa: E402
from sjtu_tpmshx.solvers.coupling_skeleton import run_outer_coupling  # noqa: E402

_GATES = ('simple_ok', 'ltne_ok', 'outer_converged', 'fields_finite',
          'envelope_ok')


def _cheap_3d(**over):
    """Small in-envelope 3D case (grid kept tiny — wiring, not physics)."""
    kw = dict(L=0.10, H=0.10, Lz=0.02, Nx=8, Ny=6, Nz=3,
              u_A=3.0, T_inA=400.0, u_B=1.0, T_inB=300.0)
    kw.update(over)
    cfg = build_cfg(**kw)
    cfg['sweep_profile'] = 'fast_sweep'
    return cfg


# ── skeleton: the contract the pipelines depend on ───────────────────────────

def test_skeleton_reports_cap_exit_as_not_converged():
    """run_outer_coupling must return converged=False when it hits the cap.

    3D used to throw this return value away; the whole fix depends on it.
    """
    calls = []
    last, conv = run_outer_coupling(
        max_iter=3, step=lambda it: (calls.append(it) or (False, None)),
        post=None)
    assert calls == [0, 1, 2]
    assert last == 2
    assert conv is False, "cap exit must report converged=False"


def test_skeleton_reports_converged_exit():
    last, conv = run_outer_coupling(
        max_iter=9, step=lambda it: (it == 2, None), post=None)
    assert (last, conv) == (2, True)


# ── 3D: every gate is exposed and ANDed ──────────────────────────────────────

def test_3d_exposes_every_gate_and_verdict_is_their_and():
    r = _run_3d_stack(_cheap_3d())
    cd = r['convergence_detail']
    for g in _GATES:
        assert g in cd, f"convergence_detail must expose the {g!r} gate"
    assert r['solver_converged'] == all(bool(cd[g]) for g in _GATES), (
        "solver_converged must be exactly the AND of the exposed gates")


def test_3d_outer_cap_forces_not_converged():
    """A run truncated to 1 outer iteration cannot have converged.

    OuterConvergence.check needs a previous field to diff against, so the first
    iteration is never 'converged' by construction — the loop necessarily exits
    on the cap. Before the fix this still reported solver_converged=True.
    """
    r = _run_3d_stack(_cheap_3d(), )  # baseline for the field-shape sanity
    assert 'outer_hit_cap' in r['convergence_detail']

    cfg = _cheap_3d()
    cfg['max_outer_ltne'] = 1
    r1 = _run_3d_stack(cfg)
    cd = r1['convergence_detail']
    assert cd['outer_iters'] == 1
    assert cd['outer_hit_cap'] is True
    assert cd['outer_converged'] is False
    assert r1['solver_converged'] is False, (
        "max_outer=1 can never converge the outer loop — the verdict must say "
        "so (it used to report True whenever SIMPLE + final LTNE were fine)")


def test_3d_zero_outer_iterations_fails_loud():
    """`max_outer_ltne=0` solves nothing — fail loud, don't report a result.

    It used to fall through and die far downstream with an opaque
    `TypeError: unsupported operand type(s) for -: 'NoneType' and 'NoneType'`
    (nothing had been solved, so the field vars were still None). And the OLD
    verdict expression would have short-circuited on `not _ltne_info` (empty
    history) → `converged=True` had it ever gotten that far.
    """
    cfg = _cheap_3d()
    cfg['max_outer_ltne'] = 0
    with pytest.raises(ValueError, match='max_outer_ltne'):
        _run_3d_stack(cfg)


def test_typed_config_rejects_non_converging_outer_budget():
    """The production boundary must reject max_outer_ltne < 2.

    A single outer pass can never satisfy the coupling criterion (nothing to
    diff against), so it could only ever report converged=False. Raw-dict
    screening (`_run_3d_stack` with max_outer_ltne=1) stays legal and honest.
    """
    from sjtu_tpmshx.domain.compute_config import (ComputeConfig, FluidConfig,
                                       GeometryConfig, SolverConfig)

    def _cc(mo):
        return ComputeConfig(
            fluid_A=FluidConfig(type='air', u_mps=3.0, T_in_K=400.0,
                                P_in_Pa=101325.0),
            fluid_B=FluidConfig(type='air', u_mps=1.0, T_in_K=300.0,
                                P_in_Pa=101325.0),
            geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0,
                                    t_wall_mm=0.6, k_s_W_mK=15.0,
                                    L_dom_m=0.1, H_dom_m=0.1, Lz_m=0.02),
            solver=SolverConfig(Nx=8, Ny=6, Nz=3, max_outer_ltne=mo))

    for bad in (0, 1):
        with pytest.raises(ValueError, match='max_outer_ltne'):
            _cc(bad).validate()
    _cc(2).validate()      # >= 2 is fine
    _cc(None).validate()   # None = dimension built-in


def test_typed_config_requires_explicit_lz_for_3d():
    """Nz>=2 selects the 3D path, which must not invent a domain depth.

    `stages_3d._parse_inputs_3d_cfg` silently substituted 0.042 m (the Shanghai
    HX depth) whenever Lz_m was None — every extensive 3D scalar (Q, mass,
    dP_B) then scaled with a constant the user never chose. The class's own
    GeometryConfig docstring already said the 3D path *requires* Lz_m.
    """
    from sjtu_tpmshx.domain.compute_config import (ComputeConfig, FluidConfig,
                                       GeometryConfig, SolverConfig)

    def _cc(Nz, Lz):
        return ComputeConfig(
            fluid_A=FluidConfig(type='air', u_mps=3.0, T_in_K=400.0,
                                P_in_Pa=101325.0),
            fluid_B=FluidConfig(type='air', u_mps=1.0, T_in_K=300.0,
                                P_in_Pa=101325.0),
            geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0,
                                    t_wall_mm=0.6, k_s_W_mK=15.0,
                                    L_dom_m=0.1, H_dom_m=0.1, Lz_m=Lz),
            solver=SolverConfig(Nx=8, Ny=6, Nz=Nz))

    with pytest.raises(ValueError, match='Lz_m'):
        _cc(Nz=3, Lz=None).validate()          # 3D without a depth
    _cc(Nz=3, Lz=0.02).validate()              # 3D with a depth
    _cc(Nz=1, Lz=None).validate()              # 2D: Lz legitimately unused

    # The pipeline entry must refuse it too (defence in depth: raw
    # ComputeConfig construction bypasses validate()).
    from sjtu_tpmshx.pipelines.stages_3d import _parse_inputs_3d_cfg
    with pytest.raises(ValueError, match='Lz_m'):
        _parse_inputs_3d_cfg(_cc(Nz=3, Lz=None))


def test_3d_initial_dual_fluid_simple_obeys_solver_config():
    """The FIRST (A‖B) SIMPLE solve used to ignore SolverConfig.

    `_run_two_simple_parallel` was called with neither max_iter nor tol, so it
    fell back to its signature defaults — a user-set max_iter_simple /
    tol_simple governed every SIMPLE solve EXCEPT the initial one. Assert the
    call site now forwards both.
    """
    import inspect
    from sjtu_tpmshx.solvers.backends.python.three_d import runtime as _r3
    # Seam-A extraction (P1.5, 2026-07-20): the initial dual-fluid solve now
    # lives in _build_3d_problem (problem setup/build), not _run_3d_stack.
    src = inspect.getsource(_r3.build_problem)
    assert '_run_two_simple_parallel(' in src
    # Take the call's argument region up to the terminating `cancel_check=`
    # kwarg (the inner _simple_max_iter(...) call has its own parens, so a
    # naive split on ')' truncates).
    call = src.split('_run_two_simple_parallel(')[1].split('cancel_check=')[0]
    assert 'max_iter=_simple_max_iter(cfg' in call, (
        "the initial dual-fluid SIMPLE solve must forward SolverConfig's "
        f"max_iter_simple (got: {call!r})")
    assert 'tol=_simple_tol_default(cfg' in call, (
        "the initial dual-fluid SIMPLE solve must forward SolverConfig's "
        f"tol_simple (got: {call!r})")


def test_typed_config_rejects_nonsense_numeric_settings():
    """validate() used to check NO solver numerical parameter at all."""
    from sjtu_tpmshx.domain.compute_config import (ComputeConfig, FluidConfig,
                                       GeometryConfig, SolverConfig)

    def _cc(**sk):
        return ComputeConfig(
            fluid_A=FluidConfig(type='air', u_mps=3.0, T_in_K=400.0,
                                P_in_Pa=101325.0),
            fluid_B=FluidConfig(type='air', u_mps=1.0, T_in_K=300.0,
                                P_in_Pa=101325.0),
            geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0,
                                    t_wall_mm=0.6, k_s_W_mK=15.0,
                                    L_dom_m=0.1, H_dom_m=0.1, Lz_m=0.02),
            solver=SolverConfig(Nx=8, Ny=6, Nz=3, **sk))

    for bad in (dict(outer_tol_K=-1.0), dict(outer_tol_K=0.0),
                dict(tol_simple=-1e-5), dict(tol_simple=0.0),
                dict(max_iter_simple=0)):
        with pytest.raises(ValueError):
            _cc(**bad).validate()
    _cc(outer_tol_K=0.5, tol_simple=1e-5, max_iter_simple=800).validate()


def test_3d_nz1_delegation_reports_the_real_ltne_verdict():
    """Nz==1 delegates to the 2D LTNE kernel; the verdict must be the real one.

    `ltne_energy_3d` used to hard-code {'converged': True, 'iterations': -1} on
    this path (it called the 2D solver with return_info=False), so ANY Nz==1
    run claimed a converged LTNE inner pass unconditionally — and that lie fed
    straight into solver_converged.
    """
    from sjtu_tpmshx.solvers.ltne_energy_3d import solve_full_domain_3d
    N = 6
    z = lambda v: np.full((N, N, 1), v, dtype=np.float64)  # noqa: E731
    out = solve_full_domain_3d(
        0.1, 0.1, 0.02, N, N, 1, 400.0, 300.0,
        z(0.03), z(0.03), z(15.0),          # K_ffA, K_ffB, K_ss
        z(500.0), z(500.0),                 # h_vA, h_vB
        z(1000.0), z(1000.0),               # rho_cp_fA, rho_cp_fB
        z(0.7),                             # epsilon
        z(1.0), z(0.0), z(0.0),             # ucA, vcA, wcA
        z(0.0), z(-1.0), z(0.0),            # ucB, vcB, wcB
        0, 3,                               # dir_A, dir_B
        max_iter=1,                         # force a NON-converged inner pass
        tol=1e-30,                          # unreachable
        return_info=True)
    info = out[3]
    assert info['delegated_to_2d'] is True
    assert info['converged'] is False, (
        "with max_iter=1 and tol=1e-30 the delegated 2D solve cannot have "
        "converged; the Nz==1 path used to hard-code converged=True")
    assert info['iterations'] != -1, "iterations must be the real count"


def test_3d_verdict_judges_the_final_simple_solve_not_the_warmup():
    """A superseded cold-start stall must not force converged=False.

    Outer iteration 0 can never satisfy the coupling criterion (nothing to diff
    against), so `post(0)` ALWAYS runs and ALWAYS re-solves SIMPLE — the
    cold-start velocity/pressure field is therefore ALWAYS superseded before
    anything is reported. The old verdict gated on a STICKY list of every
    failed solve, so a run whose every reported field came from a converged
    solve still said converged=False because a transient warm-up stalled.
    (Shanghai's u≈22 m/s cases: `A@init[stall]`, every re-solve 'velocity'.)

    The history must stay visible — it is split, not dropped.
    """
    r = _run_3d_stack(_cheap_3d())
    cd = r['convergence_detail']
    for k in ('simple_nonconv', 'simple_nonconv_final',
              'simple_nonconv_transient', 'simple_exit_A'):
        assert k in cd, f"convergence_detail must expose {k!r}"
    # The split is a partition of the sticky history — nothing is lost.
    assert (sorted(cd['simple_nonconv_final']
                   + cd['simple_nonconv_transient'])
            == sorted(cd['simple_nonconv']))
    # simple_ok gates on the FINAL solve, so it must agree with exit_reason.
    _ok = ('tol', 'velocity')
    assert cd['simple_ok'] == (
        (cd['simple_exit_A'] in _ok)
        and (cd['simple_exit_B'] is None or cd['simple_exit_B'] in _ok))
    # And an init-only stall must NOT be counted against the verdict.
    assert not any(t.startswith(('A@init', 'B@init'))
                   for t in cd['simple_nonconv_final'])


def test_2d_converged_resolve_supersedes_an_earlier_failure():
    """2D's `simple_warnings` dict was written on failure and never cleared.

    Keyed by side label, so a stalled warm-up solve stuck for the whole run.
    A later converged solve on the same side must clear it.
    """
    import inspect
    from sjtu_tpmshx.solvers.backends.python.two_d import runtime as _s2
    src = inspect.getsource(_s2)
    assert 'simple_warnings.pop(label, None)' in src, (
        "a converged re-solve must supersede an earlier failure on that side")




# ── 2D: same contract ────────────────────────────────────────────────────────



def test_2d_verdict_ands_the_ltne_inner_pass():
    """`e_info['converged']` must reach the 2D verdict (it was write-only)."""
    import inspect
    from sjtu_tpmshx.pipelines import solve_2d as _s2
    src = inspect.getsource(_s2.solve_2d_cfg if hasattr(_s2, 'solve_2d_cfg')
                            else _s2)
    assert "e_info.get('converged'" in src, (
        "the 2D LTNE inner verdict must be ANDed into solver_converged")
    assert "_energy_nan_hit" in src, (
        "a patched-over NaN must force the verdict False")

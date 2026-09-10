"""Port-BC + lateral-K wiring in the 2D optimizer evaluator (2026-07-10).

Contracts:
  1. Full-face default (ports=None, per_cell_K=False) is BIT-IDENTICAL to the
     pre-port evaluator — covered by test_evaluator_frozen_values (pins
     unchanged); here we pin the config contract itself.
  2. B-side ε orientation: SIMPLE-B's streamwise axis is flipped vs real y
     (dir_B=3). The evaluator push must mirror — a y-asymmetric field must
     land flipped on sB.eps_field (historical direct push was a latent bug,
     invisible under symmetric_y=True).
  3. per_cell_K pushes per-cell fields whose lateral means differ from the
     legacy per-row projection on laterally-varying designs (the contrast the
     port study needs), and is a value no-op on uniform designs.
  4. Port runs produce finite physical outputs and lower duty than full-face
     at the same design and v_inlet (1/4-open ports carry ~1/4 the mass).
"""

from __future__ import annotations

import numpy as np
import pytest

from sjtu_tpmshx.optimization.evaluator import (
    DEFAULT_CONFIG,
    evaluate_design,
)
from sjtu_tpmshx.preprocess.app_modes.screening_2d import _percell_K_cF, _resolve_grid, prepare_flow
from sjtu_tpmshx.solvers.backends.python.screening.two_d import build_flow


def _build_simple_A(cfg, fc, arrays, Nx, Ny):
    return build_flow(prepare_flow(cfg, fc, arrays, Nx, Ny, 'A'))


def _build_simple_B(cfg, fc, arrays, Nx, Ny):
    return build_flow(prepare_flow(cfg, fc, arrays, Nx, Ny, 'B'))


from sjtu_tpmshx.solvers.continuous_field import (
    encode_decision_vector,
    from_decision_vector,
)


_CFG_SMALL = {
    **DEFAULT_CONFIG,
    'tpms_type': 'Gyroid',
    'L_domain': 0.06,
    'H_domain': 0.06,
    'Nx': 20, 'Ny': 20,
    'n_ctrl_x': 4, 'n_ctrl_y': 4,
    'symmetric_y': False,
    'u_A': 6.0, 'u_B': 3.0,
    'T_inA': 380.0, 'T_inB': 300.0,
    'max_iter_simple': 400,
    'max_iter_energy': 800,
    'n_rho_loops': 1,
}


def _fc_arrays(cfg, L_ctrl, t_ctrl):
    x = encode_decision_vector(L_ctrl, t_ctrl, bool(cfg['symmetric_y']))
    fc = from_decision_vector(
        x, tpms_type=cfg['tpms_type'], k_s=cfg['k_s'],
        L_domain=cfg['L_domain'], H_domain=cfg['H_domain'],
        n_ctrl_x=cfg['n_ctrl_x'], n_ctrl_y=cfg['n_ctrl_y'],
        symmetric_y=cfg['symmetric_y'], spline_order=cfg['spline_order'],
        L_bounds=cfg['L_bounds'], t_bounds=cfg['t_bounds'])
    Nx, Ny = _resolve_grid(cfg, fc)
    arrays = fc.build_grid_arrays(
        Nx, Ny, u_A=cfg['u_A'], u_B=cfg['u_B'],
        T_inA=cfg['T_inA'], T_inB=cfg['T_inB'], P_in=cfg['P_inA'])
    return x, fc, arrays, Nx, Ny


def _graded_y_ctrl(cfg):
    """L rises with real y (y-ASYMMETRIC on purpose), t uniform."""
    ncx, ncy = cfg['n_ctrl_x'], cfg['n_ctrl_y']
    L_ctrl = np.tile(np.linspace(4.0, 6.5, ncy)[None, :], (ncx, 1))
    t_ctrl = np.full((ncx, ncy), 0.4)
    return L_ctrl, t_ctrl


def test_default_config_is_fullface_no_percell():
    """Contract pin: the default BC stays the M0–M3 full-face condition."""
    assert DEFAULT_CONFIG['ports_A'] is None
    assert DEFAULT_CONFIG['ports_B'] is None
    assert DEFAULT_CONFIG['per_cell_K'] is False


def test_energy_inlet_uses_same_physical_face_as_pipeline(monkeypatch):
    from sjtu_tpmshx.solvers.backends.python.screening import two_d as evaluator
    from sjtu_tpmshx.solvers.tpms_calc import air_cp
    from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver, _port_fractions_1d
    cfg = {**_CFG_SMALL, 'ports_A': (.015, .045, 0., .03),
           'ports_B': (.015, .045, .03, .06)}
    captured = []

    def face_only(s, **kwargs):
        s.rho_field[:, 0] = np.arange(2., s.Nx + 2.)
        s.v[:, 0] = np.arange(1., s.Nx + 1.) * s.inlet_frac
        s.v[:, 1] = .1 * s.v[:, 0]  # Centre and inlet face deliberately differ.
        captured.append(s)
        return True, 0

    class Captured(Exception):
        pass

    def energy(*args, **kwargs):
        eps = .5 * args[13]
        for side, s, eps_in, width in zip(
                ('A', 'B'), captured, (eps[0, :], eps[:, -1]),
                (kwargs['dy_arr'], kwargs['dx_arr'])):
            expected = (eps_in * np.arange(2., s.Nx + 2.) * s.v[:, 0]
                        * width * air_cp(cfg[f'T_in{side}']))
            np.testing.assert_allclose(kwargs[f'inlet_flux_{side}'], expected,
                                       rtol=1e-14, atol=0)
            port = cfg[f'ports_{side}']
            raw = _port_fractions_1d(s.dx_arr, port[0], port[1])[0]
            np.testing.assert_array_equal(kwargs[f'inlet_mask_{side}'], raw)
        raise Captured

    monkeypatch.setattr(SIMPLESolver, 'solve', face_only)
    monkeypatch.setattr(evaluator, 'solve_full_domain', energy)
    _, fc, _, _, _ = _fc_arrays(cfg, *_graded_y_ctrl(cfg))
    with pytest.raises(Captured):
        evaluate_design(None, cfg, fc=fc)


def test_b_side_eps_push_is_y_flipped():
    """Orientation fix: a y-graded ε field lands FLIPPED on SIMPLE B
    (j=0 ↔ real y=H), mirroring stages_2d._to_simple_coords d==3."""
    cfg = dict(_CFG_SMALL)
    _, fc, arrays, Nx, Ny = _fc_arrays(cfg, *_graded_y_ctrl(cfg))
    eps_real = arrays['eps_arr']
    assert not np.allclose(eps_real, eps_real[:, ::-1]), \
        "test premise broken: field must be y-asymmetric"
    sB = _build_simple_B(cfg, fc, arrays, Nx, Ny)
    np.testing.assert_array_equal(sB.eps_field, eps_real[:, ::-1])
    # A side unchanged: transpose, no flip (dir_A = 0)
    sA = _build_simple_A(cfg, fc, arrays, Nx, Ny)
    np.testing.assert_array_equal(sA.eps_field, eps_real.T)


def test_percell_K_matches_uniform_and_differs_graded():
    """Uniform design: per-cell K equals the per-row projection everywhere.
    Laterally-graded design: per-cell K varies along the lateral axis."""
    cfg = dict(_CFG_SMALL)
    # uniform
    ncx, ncy = cfg['n_ctrl_x'], cfg['n_ctrl_y']
    _, fc_u, arr_u, Nx, Ny = _fc_arrays(
        cfg, np.full((ncx, ncy), 5.0), np.full((ncx, ncy), 0.4))
    K_u, cF_u = _percell_K_cF(cfg, arr_u)
    # spline evaluation of a uniform ctrl grid is constant only to ~1e-15
    # relative, so the predicted K carries ULP-level ptp — bound relatively.
    assert float(np.ptp(K_u)) / float(K_u.mean()) < 1e-9
    assert float(np.ptp(cF_u)) / float(cF_u.mean()) < 1e-9
    # graded in y = lateral for fluid A
    _, fc_g, arr_g, _, _ = _fc_arrays(cfg, *_graded_y_ctrl(cfg))
    K_g, _ = _percell_K_cF(cfg, arr_g)
    lateral_rel = float(np.ptp(K_g, axis=1).max()) / float(K_g.mean())
    assert lateral_rel > 1e-3, (
        f"lateral K contrast missing on a y-graded design ({lateral_rel:.2e})")
    # per_cell_K=True installs the 2D override on both solvers (B flipped)
    cfg2 = {**cfg, 'per_cell_K': True}
    sA = _build_simple_A(cfg2, fc_g, arr_g, Nx, Ny)
    sB = _build_simple_B(cfg2, fc_g, arr_g, Nx, Ny)
    np.testing.assert_array_equal(sA._K_field2d, K_g.T)
    np.testing.assert_array_equal(sB._K_field2d, K_g[:, ::-1])


def test_port_run_finite_and_lower_throughput():
    """Port evaluation completes with finite physical outputs.

    Same design, same interstitial v_inlet: the port opening is 1/4 of the
    face, so the port run pushes ~1/4 the mass — duty Q must drop vs the
    full-face run (throughput contract; NOT a dP inequality — with less total
    mass the domain-average velocity falls and Forchheimer dP can go either
    way, empirically lower)."""
    cfg_ff = dict(_CFG_SMALL)
    side = cfg_ff['H_domain']; port = side / 4.0
    cfg_port = {
        **cfg_ff,
        'per_cell_K': True,
        'ports_A': (side - port, side, 0.0, port),
        'ports_B': (side - port, side, 0.0, port),
    }
    ncx, ncy = cfg_ff['n_ctrl_x'], cfg_ff['n_ctrl_y']
    x = encode_decision_vector(np.full((ncx, ncy), 5.0),
                               np.full((ncx, ncy), 0.4),
                               bool(cfg_ff['symmetric_y']))
    Qn_ff, dP_ff, m_ff = evaluate_design(x, cfg_ff)
    Qn_p, dP_p, m_p = evaluate_design(x, cfg_port)
    for v in (Qn_ff, dP_ff, Qn_p, dP_p):
        assert np.isfinite(v)
    assert -Qn_p > 0.0, "port run produced non-positive Q"
    assert dP_p > 0.0
    assert -Qn_p < -Qn_ff, (
        f"1/4-open ports must cut duty: Q_port={-Qn_p:.1f} >= "
        f"Q_fullface={-Qn_ff:.1f}")
    assert m_p == pytest.approx(m_ff), "mass must not depend on BC"


def test_cf_aniso_penalizes_turning_flow_only():
    """cf-aniso contract: the direction factor bites where the flow is
    oblique (port run — in-domain turning) and is near-inert where flow is
    axis-aligned (full-face run: ξ4 ≈ 0 everywhere)."""
    cfg_ff = dict(_CFG_SMALL)
    side = cfg_ff['H_domain']; port = side / 4.0
    ports = {
        'ports_A': (side - port, side, 0.0, port),
        'ports_B': (side - port, side, 0.0, port),
    }
    ncx, ncy = cfg_ff['n_ctrl_x'], cfg_ff['n_ctrl_y']
    x = encode_decision_vector(np.full((ncx, ncy), 5.0),
                               np.full((ncx, ncy), 0.4),
                               bool(cfg_ff['symmetric_y']))
    A = 0.8  # deliberately large so the effect is unambiguous
    # full-face: axis-aligned flow → factor ~inert (< 0.5 % on dP)
    _, dP_ff0, _ = evaluate_design(x, cfg_ff)
    _, dP_ffA, _ = evaluate_design(x, {**cfg_ff, 'cf_aniso': A})
    assert abs(dP_ffA - dP_ff0) / dP_ff0 < 5e-3, (
        f"cf_aniso leaked into axis-aligned flow: {dP_ff0:.2f} → {dP_ffA:.2f}")
    # ports: flow turns in-domain → positive factor must RAISE dP
    _, dP_p0, _ = evaluate_design(x, {**cfg_ff, **ports, 'per_cell_K': True})
    _, dP_pA, _ = evaluate_design(
        x, {**cfg_ff, **ports, 'per_cell_K': True, 'cf_aniso': A})
    assert dP_pA > dP_p0, (
        f"cf_aniso={A} did not penalize turning port flow: "
        f"{dP_p0:.2f} → {dP_pA:.2f}")


def _temperature_boundary(monkeypatch, fields, *, stop_after_return=False):
    """Exercise evaluator orchestration without SIMPLE or thermal sweeps."""
    from sjtu_tpmshx.solvers.backends.python.screening import two_d as evaluator
    from sjtu_tpmshx.postprocess import screening as post
    from sjtu_tpmshx.solvers.simple_solver import SIMPLESolver

    calls = []

    def unsolved(s, **kwargs):
        calls.append('simple')
        return False, kwargs['max_iter']

    def forbidden(*args, **kwargs):
        pytest.fail('non-finite temperature reached density or Q')

    def thermal(*args, **kwargs):
        calls.append('thermal')
        assert calls.count('thermal') == 1
        if stop_after_return:
            monkeypatch.setattr(evaluator, 'air_density', forbidden)
            monkeypatch.setattr(post, 'evaluate_metric', forbidden)
        return (*fields, {'converged': False})

    monkeypatch.setattr(SIMPLESolver, 'solve', unsolved)
    monkeypatch.setattr(evaluator, 'solve_full_domain', thermal)
    monkeypatch.setattr(post, 'pressure_drop', lambda evidence: 20.)
    return calls


@pytest.mark.parametrize('loops', [1, 3])
@pytest.mark.parametrize('side,label', [(0, 'A'), (1, 'B'), (2, 'solid')])
@pytest.mark.parametrize('bad', [np.nan, np.inf])
def test_optimizer_temperature_rejected_before_use(monkeypatch, loops, side, label, bad):
    fields = [np.full((20, 20), t) for t in (380., 300., 340.)]
    fields[side][-1, -1] = bad
    calls = _temperature_boundary(monkeypatch, fields, stop_after_return=True)
    with pytest.raises(ValueError) as error:
        evaluate_design(encode_decision_vector(np.full((4, 4), 5.), np.full((4, 4), .4), False), {**_CFG_SMALL, 'n_rho_loops': loops,
                                         'max_iter_simple': 1, 'max_iter_energy': 1})
    assert f'optimizer temperature return: {label} temperature index=(19, 19)' in str(error.value)
    assert calls == ['simple', 'simple', 'thermal']


@pytest.mark.parametrize('loops', [1, 3])
@pytest.mark.parametrize('cap', [30., 100.])
def test_optimizer_finite_low_budget_keeps_objectives(monkeypatch, loops, cap):
    fields = [np.full((20, 20), t) for t in (380., 300., 340.)]
    calls = _temperature_boundary(monkeypatch, fields)
    Qn, dp, mass = evaluate_design(encode_decision_vector(np.full((4, 4), 5.), np.full((4, 4), .4), False), {
        **_CFG_SMALL, 'n_rho_loops': loops, 'max_iter_simple': 1,
        'max_iter_energy': 1, 'penalty_enabled': False, 'dp_cap_pa': cap})
    assert DEFAULT_CONFIG['reject_unconverged'] is False
    assert np.isfinite(Qn) and Qn < 0 and np.isfinite(mass) and mass > 0
    assert dp == min(40., cap)
    if cap == 30.:
        assert Qn == -1e-6
    else:
        assert Qn < -1e-6
    assert calls == ['simple', 'simple', 'thermal']


def test_optimizer_worker_preserves_failure_penalties():
    from sjtu_tpmshx.optimization.optimizer_qnehvi import _eval_worker

    def invalid(*args):
        raise ValueError('optimizer temperature return')

    Q, dp, error = _eval_worker(None, {}, 100., invalid)
    assert (Q, dp) == (1e-6, 100.) and 'ValueError' in error
    assert _eval_worker(None, {}, 100., lambda *a: (np.nan, 20., 1.)) == (1e-6, 100., 'infeasible')
    assert _eval_worker(None, {}, 100., lambda *a: (-12., 20., 1.)) == (12., 20., None)

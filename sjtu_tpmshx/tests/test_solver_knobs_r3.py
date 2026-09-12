"""R3 (2026-07-07): SolverConfig/OptimizerConfig split + knob wiring.

Contract under test:
1. SolverConfig's four production knobs default to None (= dim-specific
   auto) so the default path is bit-identical to the old hardcodes; the
   goldens are the authoritative guard for that half.
2. OptimizerConfig carries the cheap-eval budget with the exact values
   the optimizer used to read from SolverConfig.
3. Legacy JSONs with the retired solver.alpha_T / solver.rough_mode keys
   still load (dropped with a warning, not TypeError).
4. EFFECTIVENESS: setting a knob actually changes solver behaviour in
   both dims — the whole point of R3 is that these were decorative.
"""
import json
import warnings as _warnings

import numpy as np
import pytest

from sjtu_tpmshx.domain.compute_config import (ComputeConfig, ExtrapPolicy, FeatureFlags,
                                   FluidConfig, GeometryConfig,
                                   OptimizerConfig, SolverConfig)


def test_solver_knobs_default_to_auto():
    s = SolverConfig()
    assert s.tol_simple is None
    assert s.max_iter_simple is None
    assert s.max_outer_ltne is None
    assert s.outer_tol_K is None
    assert not hasattr(s, 'alpha_T')
    assert not hasattr(s, 'rough_mode')


def test_optimizer_budget_matches_old_solver_defaults():
    """The optimizer must keep reading EXACTLY the values it always got."""
    o = OptimizerConfig()
    assert o.max_outer_ltne == 4
    assert o.outer_tol_K == 0.5
    assert o.max_iter_simple == 800
    assert o.tol_simple == 1e-2
    assert o.alpha_T == 0.7


def test_evaluator_mapping_reads_optimizer_block():
    from sjtu_tpmshx.optimization.evaluator import _compute_cfg_to_evaluator_dict
    cfg = ComputeConfig()
    cfg.optimizer.tol_simple = 0.123
    cfg.optimizer.max_iter_simple = 77
    cfg.solver.tol_simple = 1e-9        # must NOT leak into the evaluator
    d = _compute_cfg_to_evaluator_dict(cfg)
    assert d['tol_simple'] == 0.123
    assert d['max_iter_simple'] == 77


def test_legacy_json_with_retired_keys_loads(tmp_path):
    """Archived configs carry solver.alpha_T / rough_mode — must load."""
    blob = {
        'fluid_A': {'type': 'air', 'u_mps': 5.0},
        'solver': {'Nx': 12, 'Ny': 10, 'alpha_T': 0.7,
                   'rough_mode': 'norris_1a'},
    }
    p = tmp_path / 'legacy.json'
    p.write_text(json.dumps(blob), encoding='utf-8')
    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter('always')
        cfg = ComputeConfig.from_json(p)
    assert cfg.solver.Nx == 12
    assert any('retired' in str(w.message) for w in caught)


def test_roundtrip_carries_optimizer_section(tmp_path):
    cfg = ComputeConfig()
    cfg.optimizer.max_iter_simple = 512
    cfg.solver.tol_simple = 3e-6
    p = tmp_path / 'cfg.json'
    cfg.to_json(p)
    back = ComputeConfig.from_json(p)
    assert back.optimizer.max_iter_simple == 512
    assert back.solver.tol_simple == 3e-6
    assert back == cfg


# ── effectiveness: the knobs must actually turn ─────────────────────


def _small_2d_cfg(**solver_kw):
    return ComputeConfig(
        fluid_A=FluidConfig(type='air', u_mps=5.0, T_in_K=400.0),
        fluid_B=FluidConfig(type='air', u_mps=10.0, T_in_K=310.0),
        geometry=GeometryConfig(tpms='Gyroid', L_cell_mm=7.0, t_wall_mm=0.6,
                                k_s_W_mK=16.0, L_dom_m=0.06, H_dom_m=0.03),
        solver=SolverConfig(Nx=8, Ny=8, **solver_kw),
        extrap=ExtrapPolicy(allow=True),
        flags=FeatureFlags(),
    )


@pytest.mark.slow
def test_2d_max_outer_knob_turns():
    """Capping the SIMPLE↔LTNE coupling at 2 rounds must change the
    converged temperature field (this case needs 3+ rounds to settle),
    while identical settings reproduce bit-identically (determinism
    control — the difference is the KNOB, not noise). The cap is 2, not
    1: `Pipeline.run()` now enforces `ComputeConfig.validate()` (codex
    review 2026-07-13), whose deliberate rule is max_outer_ltne >= 2 (a
    single pass cannot even measure a dT change — the truth-table tests
    pin that rule). tol_simple gates the exit only under
    convergence_mode='legacy' (ledger C6/C9 — under the f2 pipeline
    default it drives nothing but the AMG scheduler), so its
    effectiveness is not asserted here."""
    from sjtu_tpmshx.controllers.compute_pipeline import Pipeline2D
    Ta_def = Pipeline2D(_small_2d_cfg()).run().fields['Ta']
    Ta_capped = Pipeline2D(_small_2d_cfg(max_outer_ltne=2)).run().fields['Ta']
    Ta_capped2 = Pipeline2D(_small_2d_cfg(max_outer_ltne=2)).run().fields['Ta']
    assert np.array_equal(Ta_capped, Ta_capped2), \
        "determinism control failed — cannot attribute differences to the knob"
    assert not np.array_equal(Ta_def, Ta_capped), (
        "max_outer_ltne=2 produced a bit-identical field to the default "
        "run — the knob is decorative again")


@pytest.mark.slow
def test_3d_knobs_turn():
    """max_outer_ltne must cap the 3D outer loop. (tol_simple is also passed
    but its exit-gating is legacy-only — ledger C6/C7; under the f2 pipeline
    default it only retunes the AMG scheduler, so no assertion hangs on it.)"""
    from sjtu_tpmshx.pipelines.run_stack_3d import _run_3d_stack
    from test_partial_bc_ghost_b import _partial_bc_air_air_cfg
    base = _partial_bc_air_air_cfg(Nx=8, Ny=6, Nz=6)
    r_def = _run_3d_stack(dict(base))
    r_knob = _run_3d_stack(dict(base, max_outer_ltne=1, tol_simple=5e-2))
    outer_def = len(r_def['convergence_detail']['outer_dT'])
    outer_knob = len(r_knob['convergence_detail']['outer_dT'])
    assert outer_knob == 1, \
        f"max_outer_ltne=1 did not cap the outer loop (got {outer_knob})"
    assert outer_def > 1

"""
optimization/evaluator_3d.py — 3D BO-compatible single-design evaluator.

Wraps ``core.evaluators.evaluate_3d`` (which already extrudes a
2D L(x,y), t(x,y) field along z, runs SIMPLE 3D × 2 + LTNE solve_full_domain_3d
with outer ρ(T) coupling) into the same (Q_neg, dP, mass) return contract as
``optimization.evaluator.evaluate_design`` so ``optimizer_qnehvi.run_qnehvi``
can drive it via ``evaluator_fn=evaluate_design_3d``.

Design choices:
  * Q is normalized to W per metre of HX depth (Q_3D / Lz) so the 3D Pareto
    sits in the same axis as the 2D Pareto — direct comparison.
  * ``DEFAULT_CONFIG_3D`` inherits ``optimization.evaluator.DEFAULT_CONFIG``
    plus 3D-only knobs: ``Nx_3d``, ``Ny_3d``, ``Nz_3d``, ``Lz``,
    ``max_outer_3d``, ``outer_tol_K``, ``alpha_outer``. Solver-tol overrides
    (``max_iter_simple``, ``max_iter_energy``, ``tol_energy``)
    flow through unchanged.
  * Errors caught in BO worker (_eval_worker) — this function raises on
    pathology so the worker tags it with the dp_cap fallback.

Public API::

    DEFAULT_CONFIG_3D : dict
    evaluate_design_3d(x, cfg) -> (Q_neg_per_m, dP_total, mass_per_m)
"""

from __future__ import annotations

import numpy as np

from sjtu_tpmshx.optimization.evaluator import DEFAULT_CONFIG as _EVAL_DEFAULT_CONFIG
# M4 (2026-05-28 audit): import via core.evaluators neutral layer instead of
# directly from validation.cases.verify_pareto_3d, breaking the
# optimization→validation direction anomaly. core.evaluators currently
# composes public module APIs; physical execution lives in the screening backend.
from sjtu_tpmshx.core.evaluators import evaluate_3d as _evaluate_3d_dict


# ─── Default cfg ────────────────────────────────────────────────────


DEFAULT_CONFIG_3D: dict = {
    **_EVAL_DEFAULT_CONFIG,

    # Screening grid and coupling budget; these do not certify convergence.
    'Nx_3d':         30,
    'Ny_3d':         12,
    'Nz_3d':         6,
    'Lz':            0.042,    # m  (Shanghai HX depth default)
    'max_outer_3d':  2,        # maximum coupling iterations; 1 is also a valid budget
    'outer_tol_K':   0.5,
    'alpha_outer':   0.6,

    # Override 2D defaults to match 3D fast-mode budget
    'max_iter_simple': 300,
    'max_iter_energy': 1000,
    'tol_energy':      0.5,

    # norris_1a is a friction no-op. Production K/cF use the fixed CFD
    # geometry table; the existing air-Gyroid Nu factor is unchanged.
    'roughness_mode':   'norris_1a',
    'roughness_eps_um': 100.0,        # only used by bhatti_shah_1b
}


# ─── Public API ─────────────────────────────────────────────────────


def _compute_cfg_to_evaluator_dict_3d(compute_cfg) -> dict:
    """Map :class:`controllers.ComputeConfig` → 3D-evaluator flat dict.

    Audit C3 (2026-05-28, L-a-1). Same overlap rules as the 2D
    counterpart in :mod:`optimization.evaluator`, plus the 3D-only
    ``Nx_3d`` / ``Ny_3d`` / ``Nz_3d`` / ``Lz`` overrides.
    """
    from sjtu_tpmshx.optimization.evaluator import _compute_cfg_to_evaluator_dict
    d = _compute_cfg_to_evaluator_dict(compute_cfg)
    for bc in (compute_cfg.bc_A, compute_cfg.bc_B):
        for centre, width in ((bc.in_z_ctr, bc.in_z_w), (bc.out_z_ctr, bc.out_z_w)):
            if centre is None and width is None:
                continue  # Each omitted z opening independently means full face.
            depth = compute_cfg.geometry.Lz_m
            if (depth is None or centre is None or width is None
                    or not np.allclose((centre, width), (depth / 2., depth),
                                       rtol=1e-12, atol=1e-15)):
                raise ValueError('3D screening supports full-face ports only')
    d['Nx_3d'] = compute_cfg.solver.Nx
    d['Ny_3d'] = compute_cfg.solver.Ny
    d['Nz_3d'] = compute_cfg.solver.Nz
    if compute_cfg.geometry.Lz_m is not None:
        d['Lz'] = compute_cfg.geometry.Lz_m
    # R3 (2026-07-07): budget knobs come from the optimizer block. The old
    # solver.rough_mode passthrough is dropped — its value always equalled
    # the EVAL3D_DEFAULTS 'norris_1a' (both friction no-ops); roughness
    # sweeps use the TPMSHX_ROUGH_MODE env escape hatch.
    d['max_outer_3d'] = compute_cfg.optimizer.max_outer_ltne
    d['outer_tol_K'] = compute_cfg.optimizer.outer_tol_K
    d['alpha_outer'] = compute_cfg.optimizer.alpha_T
    return d


def evaluate_design_3d(x: np.ndarray,
                       cfg: dict | None = None,
                       *, compute_cfg=None) -> tuple:
    """Evaluate one 3D design.

    Parameters
    ----------
    x : (D,) array — decision vector (D = decision_dim from cfg control grid).
    cfg : dict — overrides over DEFAULT_CONFIG_3D.
    compute_cfg : controllers.ComputeConfig, optional
        Strict-typed config (audit C3, L-a-1). When provided, its
        overlapping fields seed ``cfg_full`` underneath ``cfg`` so the
        explicit dict path keeps absolute precedence.

    Returns
    -------
    Q_neg_per_m : float — −Q in W/m of HX depth (BO maximizes ⇒ negate for
        min-form). Normalized by cfg['Lz'] so 3D Pareto comparable to 2D.
    dP_total : float — dP_A + dP_B in Pa.
    mass_per_m : float — solid mass kg per metre of HX depth.
    """
    if compute_cfg is not None:
        cc_dict = _compute_cfg_to_evaluator_dict_3d(compute_cfg)
        cfg_full = {**DEFAULT_CONFIG_3D, **cc_dict, **(cfg or {})}
    else:
        cfg_full = {**DEFAULT_CONFIG_3D, **(cfg or {})}

    Nx = int(cfg_full['Nx_3d'])
    Ny = int(cfg_full['Ny_3d'])
    Nz = int(cfg_full['Nz_3d'])
    Lz = float(cfg_full['Lz'])

    res = _evaluate_3d_dict(
        np.asarray(x, dtype=np.float64), cfg_full,
        Nx=Nx, Ny=Ny, Nz=Nz, Lz=Lz,
        max_outer=int(cfg_full['max_outer_3d']),
        outer_tol_K=float(cfg_full['outer_tol_K']),
        alpha_outer=float(cfg_full['alpha_outer']),
        max_iter_simple=int(cfg_full['max_iter_simple']),
        max_iter_energy=int(cfg_full['max_iter_energy']),
        tol_energy=float(cfg_full['tol_energy']),
        roughness_mode=str(cfg_full.get('roughness_mode', 'norris_1a')),
        roughness_eps_um=float(cfg_full.get('roughness_eps_um', 100.0)),
        verbose=False,
    )

    # Choke/invalid guard (ledger O1, closed 2026-07-13): evaluate_3d returns
    # NaN + `invalid` for choked operating points (strict validation
    # contract). This wrapper used to IGNORE the flag, letting the NaNs
    # propagate to the qNEHVI worker's bare `except` — return the bounded
    # dp_cap penalty here instead (same convention as the 2D evaluator's
    # blowup guard: keeps the GP input distribution bounded). mass_kg is real
    # geometry even on invalid returns, so the mass objective stays honest.
    if res.get('invalid', False):
        dp_cap = float(cfg_full.get('dp_cap_pa', 1.0e6))
        mass_kg = float(res.get('mass_kg', float('nan')))
        mass_per_m = (mass_kg / max(Lz, 1.0e-9)
                      if np.isfinite(mass_kg) else 0.0)
        return -1e-6, dp_cap, mass_per_m

    Q_per_m = float(res['Q_3D_W']) / max(Lz, 1.0e-9)       # W → W/m
    dP_total = float(res['dP_total_Pa'])
    mass_per_m = float(res['mass_kg']) / max(Lz, 1.0e-9)   # kg → kg/m

    return -Q_per_m, dP_total, mass_per_m

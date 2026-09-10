"""Offset-isosurface (δ) per-side void-fraction split — dimension-agnostic.

The asymmetric-porosity split ratio is pure TPMS geometry (it depends only on
the offset δ and the wall fraction C(t/L)), so it is shared by BOTH the 2D and
3D pipelines. It lives here, in ``solvers/``, rather than in ``stages_3d`` so the
2D path can import it WITHOUT dragging in the heavy 3D solver
(``SIMPLESolver3D`` / the numba 3D kernels) that ``stages_3d`` pulls in at
import time.

Single source of truth for:
  - ``_asym_split_A``        — fraction of total ε assigned to side A;
  - ``_per_side_eps_override`` — per-side single-channel void for ṁ / Q weighting;
  - ``_eps_sides_for_run``   — per-cell (ε_A, ε_B) void arrays for the LTNE kernel.

δ=0 is the symmetric path: ``_asym_split_A`` returns 0.5, the override returns
``(None, None)``, and ``_eps_sides_for_run`` returns the SAME ``eps_f_arr``
object for both sides → bit-identical to the legacy symmetric run.
"""


def _asym_split_A(cfg, tpms_type, Lcell, t_wall):
    """Fraction of total ε assigned to side A under offset-isosurface δ.

    Returns 0.5 at δ=0 (symmetric). δ≠0 → the geometry split ratio
    εA/(εA+εB) from ``asym_geometry.eps_sides`` at C = C(t/L).
    δ = ``cfg['delta_levelset']`` (φ-units). Shared by ``_eps_sides_for_run``
    (per-cell void arrays) and the per-side D-F κ closure so both consume one
    split definition.
    """
    delta = float(cfg.get('delta_levelset', 0.0))
    if delta == 0.0:
        return 0.5
    from sjtu_tpmshx.models.tpms_geometry import _phi_grid, _C_from_tL
    from sjtu_tpmshx.models import asym_geometry as _ag
    phi = _phi_grid(tpms_type, 128)
    C = _C_from_tL(tpms_type, float(t_wall) / float(Lcell))
    eA, eB, _etot = _ag.eps_sides(phi, C, delta)
    return eA / (eA + eB)


def _per_side_eps_override(cfg, tpms_type, Lcell, t_wall, eps):
    """Per-side single-channel void overrides for the LTNE m_dot / Q weighting
    under an offset-isosurface δ.

    Returns ``(None, None)`` at δ=0 → the symmetric 0.5·ε path (bit-identical);
    δ≠0 → ``(ε·split_A, ε·(1−split_A))`` so ṁ_A/ṁ_B weight by the actual channel
    void fraction, not 0.5·ε. ONE definition shared by the main duty extraction
    and the enthalpy-mode ṁ build, so both stay consistent (N4 audit 2026-06-28
    — the enthalpy block previously omitted the override and mis-scaled ṁ by
    split/0.5 on the asymmetric geometry)."""
    if float(cfg.get('delta_levelset', 0.0)) == 0.0:
        return None, None
    split_A = _asym_split_A(cfg, tpms_type, Lcell, t_wall)
    return float(eps) * split_A, float(eps) * (1.0 - split_A)


def _eps_sides_for_run(cfg, tpms_type, Lcell, t_wall, eps_arr, eps_f_arr):
    """Per-side single-channel void fractions for asymmetric offset-isosurface δ.

    δ=0 → returns the symmetric ``eps_f_arr`` (= eps_arr/2) object for BOTH
    sides → bit-identical to the legacy path. δ≠0 → split the run's total
    ``eps_arr`` by the geometry ratio (``_asym_split_A``), PRESERVING the total
    (so cfg['eps'] is honoured, not the calibration ε from C(t/L); the split
    *ratio* is the geometry signal). Returns ``(eps_fA_arr, eps_fB_arr)``.
    """
    if float(cfg.get('delta_levelset', 0.0)) == 0.0:
        return eps_f_arr, eps_f_arr
    s = _asym_split_A(cfg, tpms_type, Lcell, t_wall)
    return eps_arr * s, eps_arr * (1.0 - s)

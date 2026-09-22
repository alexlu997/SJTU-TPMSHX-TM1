"""Qt-free application result populated by the public-module GUI adapter."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ComputeResult:
    """Output of a single ``ComputePipeline`` run.

    Headline scalars (``Q_W``, ``dP_*_Pa``, ``T_out_*_K``) match the
    numbers shown in the UI result panel.  The rich
    sub-dictionaries hold the arrays / coefficients / residuals so the
    UI adapter (``Main_Menu.write_result``) and validation scripts can
    pluck whatever they need without re-running the solver.
    """

    # ── headline scalars (UI compute panel) ──
    Q_W: float = 0.0
    dP_A_Pa: float = 0.0
    dP_B_Pa: float = 0.0
    T_out_A_K: float = 0.0
    T_out_B_K: float = 0.0

    # ── convergence verdict (robustness-hardening, 2026-07-03) ──
    # False when a SIMPLE side stalled or the final LTNE/coupling pass
    # missed its residual target. Was previously buried in warning
    # strings, so diverged solves displayed Q/dP indistinguishably from
    # good ones. Default True keeps old-payload round-trips permissive.
    converged: bool = True

    # ── rich arrays ──
    # 2D keys: T_fA, T_fB, T_s, P_A, P_B, u_A, v_A, u_B, v_B, eps_arr,
    #          (+ axis_dir_A, axis_dir_B for plotting)
    # 3D keys: + w_A, w_B + z_centres
    fields: Dict[str, Any] = field(default_factory=dict)

    # ── porous + coupling coefficients ──
    # Keys: K_ffA, K_ffB, K_ss, h_vA, h_vB (scalar or array per zone mode)
    coeffs: Dict[str, Any] = field(default_factory=dict)

    # ── fluid + solid properties at iteration end ──
    # Keys: rho_A, rho_B, mu_A, mu_B, eps_A, D_h_m, A_0_m2
    props: Dict[str, Any] = field(default_factory=dict)

    # ── residuals ──
    # Keys: r_Q, r_dP_A, r_dP_B (relative deltas), simple_A, simple_B,
    #       ltne_outer (max-T outer iteration delta)
    residuals: Dict[str, float] = field(default_factory=dict)

    # ── zones (None when zones disabled) ──
    # Keys: axis_dir, stats, boundaries (list[float]),
    #       boundaries_x, boundaries_y (3D / grid mode)
    zones: Optional[Dict[str, Any]] = None

    # ── warnings + extrap reasons ──
    # ``warnings`` accumulates fluid-domain / zone-fallback messages.
    # ``extrap_reasons`` is the surrogate-domain audit trail consumed
    # by Main_Menu to display the watermark + status bar.
    warnings: List[str] = field(default_factory=list)
    extrap_reasons: List[str] = field(default_factory=list)

    # ── diagnostics ──
    # Keys: iter_outer, iter_simple_A, iter_simple_B, wall_time_s
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    # Reproducibility metadata. V3 records the CFD base and any applied
    # experiment-effective correction here without mixing it into coefficients.
    metadata: Dict[str, Any] = field(default_factory=dict)


__all__ = ['ComputeResult']

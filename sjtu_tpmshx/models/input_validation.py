"""Shared physical input validation used before numerical solving."""
from __future__ import annotations
from collections.abc import Iterable
from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.run_warnings import record_warning

# Defensive unit firewall (GUI labels L/H in METERS but L_cell/t in MM;
# mistyping the mm value into the metre field silently spawns a multi-metre
# domain and an hour-long hang instead of an error).
_DOMAIN_MAX_M = 10.0


def validate_domain_dims(pairs: Iterable[tuple[str, float]]) -> None:
    """Raise ValueError for any (name, value-in-m) pair above _DOMAIN_MAX_M.

    ``pairs`` is an iterable of ``(name, val)`` — 2D passes L/H, 3D adds Lz.
    """
    for name, val in pairs:
        if val > _DOMAIN_MAX_M:
            raise ValueError(
                f"Domain dimension {name!r}={val} m exceeds "
                f"{_DOMAIN_MAX_M} m. Likely unit slip — GUI expects "
                f"meters here, while L_cell and t use millimeters. "
                f"Re-check input.")


def surrogate_extrap_reasons(compute_cfg: ComputeConfig,
                             allow_extrap: bool) -> list[str]:
    """Validate both sides; return D-F geometry reasons and record Nu warnings.

    ImportError (surrogate_domain unavailable) → skip, return []. A
    ValueError from the check is a real domain violation and must propagate,
    so it is intentionally not caught. (The pre-dedup 2D copy swallowed
    AttributeError instead — a broken guard silently disabled extrapolation
    warnings; that hush is gone.)
    """
    try:
        from sjtu_tpmshx.df_surrogate.surrogate_domain import check_surrogate_domain_at_point
    except ImportError:
        return []
    geo = compute_cfg.geometry
    reasons = []
    for side, fl in (('A', compute_cfg.fluid_A), ('B', compute_cfg.fluid_B)):
        nu_reasons = []
        reasons += check_surrogate_domain_at_point(
            geo.tpms, geo.L_cell_mm, geo.t_wall_mm, geo.k_s_W_mK,
            fl.u_mps, fl.T_in_K, fl.P_in_Pa, side=side,
            allow_extrap=allow_extrap, fluid=fl.type, nu_reasons=nu_reasons) or []
        for reason in nu_reasons:
            record_warning(('nu_preflight', side), reason)
    return reasons


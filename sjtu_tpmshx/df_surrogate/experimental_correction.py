"""Approved experiment-effective corrections on the production CFD D-F base.

These selectors route to matching experiment campaigns; they are not fluid
physics.  The fitted differences may include rig, boundary, pressure-tap,
manifold, flow-area, instrument, and reduction effects that are not separated
by the available data.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from sjtu_tpmshx.domain.run_warnings import record_range

CFD_SMOOTH = "cfd_smooth"
EXPERIMENTAL = "experimental"
DF_MODES = (CFD_SMOOTH, EXPERIMENTAL)

# Fixed-K0 relative fits against data/raw_data/试验记录表_整理版.xlsx.
# Existing quality rule retained: only L={6,8}; L8 rows require Re>=1600.
_AIR_SF = {
    "Diamond": np.array([
        [3.2788759419747464, 2.9992364468561084, 3.0895675839867764],
        [3.4920497763293974, 2.7662611615506574, 2.5267470366296530],
    ]),
    "Gyroid": np.array([
        [2.5951033604672140, 2.6654645622107345, 2.7426283331795624],
        [1.4331707818978240, 1.4103961069169382, 1.3503861318521013],
    ]),
}
_AIR_L = np.array([6.0, 8.0])
_AIR_T = np.array([0.3, 0.4, 0.5])

# Fixed-K0 HX-effective fits.  Water and air share the D/G-7-6 water+air
# campaign; sCO2 uses the hot-side ok_dp rows from sCO2-Experient.xlsx.
# Bounds are the matching campaigns' measured inlet-velocity spans.
_HX_SF = {
    ("water", "Diamond"): 4.892779870412083,
    ("water", "Gyroid"): 4.198913430360186,
    ("air", "Diamond"): 1.8024228153853061,
    ("air", "Gyroid"): 2.0119682018983225,
    ("sco2", "Diamond"): 6.313005350332494,
    ("sco2", "Gyroid"): 7.608907691857889,
}
_HX_U_BOUNDS = {
    ("water", "Diamond"): (0.10, 0.25405479940574704),
    ("water", "Gyroid"): (0.10, 0.2232167044622796),
    ("air", "Diamond"): (7.656604926203154, 22.759887982116293),
    ("air", "Gyroid"): (7.5230599026715375, 24.54137550823153),
    # Same hot-side members, mdot and flow area; rho_in uses gauge + 101325 Pa.
    # Corrected 2026-09-06 with user approval; the sF values above stay frozen.
    ("sco2", "Diamond"): (0.5826657772921353, 2.53960962894522),
    ("sco2", "Gyroid"): (0.6119811082039116, 2.470456518760552),
}

# Approved 2026-09-09: production inlet density and voxel single-side area.
# Keep the calibration windows above: source audits and fit membership use them.
_HX_APPLICATION_U_BOUNDS = {
    ("water", "Diamond"): (0.013964829878811822, 0.25405479940574704),
    ("water", "Gyroid"): (0.01623408984155984, 0.22587576822423192),
    ("air", "Diamond"): (3.8832357133212434, 22.759887982116293),
    ("air", "Gyroid"): (3.912822900405603, 24.546710397710296),
    ("sco2", "Diamond"): (0.4349250602441561, 2.53960962894522),
    ("sco2", "Gyroid"): (0.3814083098626136, 2.470456518760552),
}
_HX_APPLICATION_SCOPE = (
    "7/0.6 mm, 0.182 x 0.042 x 0.042 m HX measured combinations and "
    "approved port validation; not an arbitrary T/P/mdot domain or "
    "independent cold-side sCO2 pressure-drop validation")


def _summary(value: Any) -> float | dict[str, float]:
    a = np.asarray(value, dtype=float)
    if a.ndim == 0 or a.size == 1:
        return float(a.reshape(-1)[0])
    return {"min": float(a.min()), "max": float(a.max())}


def _air_scale(tpms: str, L_mm: Any, t_mm: Any) -> np.ndarray:
    L, t = np.broadcast_arrays(np.asarray(L_mm, dtype=float),
                               np.asarray(t_mm, dtype=float))
    if np.any((L < 6.0) | (L > 8.0) | (t < 0.3) | (t > 0.5)):
        raise ValueError(
            "air experiment calibration is valid only for core specimens "
            "inside 6<=L<=8 mm and 0.3<=t<=0.5 mm; t=0.6 is not an "
            "experiment-supported extrapolation")
    table = _AIR_SF[tpms]
    lo = np.interp(t.ravel(), _AIR_T, table[0]).reshape(t.shape)
    hi = np.interp(t.ravel(), _AIR_T, table[1]).reshape(t.shape)
    return lo + (L - 6.0) * (hi - lo) / 2.0


def _is_hx_76(L_mm: Any, t_mm: Any) -> bool:
    L = np.asarray(L_mm, dtype=float)
    t = np.asarray(t_mm, dtype=float)
    return bool(np.all(np.isclose(L, 7.0, rtol=0.0, atol=1e-12))
                and np.all(np.isclose(t, 0.6, rtol=0.0, atol=1e-12)))


def hx_velocity_bounds(fluid: str, tpms: str) -> tuple[float, float]:
    """Return the original calibration window; preserve source members/audits."""
    return _HX_U_BOUNDS[(fluid, tpms)]


def hx_application_velocity_bounds(fluid: str, tpms: str) -> tuple[float, float]:
    """Return the approved production application window, with frozen sF."""
    return _HX_APPLICATION_U_BOUNDS[(fluid, tpms)]


def _hx_scale(tpms: str, fluid: str, L_mm: Any, t_mm: Any,
              u_mps: Any | None) -> tuple[Any, Any, str, str]:
    if not _is_hx_76(L_mm, t_mm):
        raise ValueError(
            f"{fluid} HX experiment calibration is valid only for the "
            "matching D/G-7-6 geometry (L=7 mm, t=0.6 mm)")
    if u_mps is None:
        raise ValueError(
            f"{fluid} HX experiment calibration requires inlet velocity")
    u = np.asarray(u_mps, dtype=float)
    lo, hi = hx_application_velocity_bounds(fluid, tpms)
    if np.any((u < lo - 1e-12) | (u > hi + 1e-12)):
        raise ValueError(
            f"{fluid} HX experiment calibration requires {lo:.6g}<=u<="
            f"{hi:.6g} m/s for {tpms}; got {_summary(u)}")
    shape = np.broadcast(np.asarray(L_mm), np.asarray(t_mm), u).shape
    sf = np.full(shape, _HX_SF[(fluid, tpms)])
    campaign = ("sco2-hx-hot-ok-dp" if fluid == "sco2"
                else "water-air-hx-7-6")
    return np.ones_like(sf), sf, campaign, "HX-effective"


def correction_scale(tpms: str, fluid: str, L_mm: Any,
                     t_mm: Any, u_mps: Any | None = None
                     ) -> tuple[Any, Any, str, str]:
    """Return ``(sK, sF, campaign, scope)`` for one matched dataset."""
    if fluid in ("water", "sco2"):
        return _hx_scale(tpms, fluid, L_mm, t_mm, u_mps)
    if fluid == "air":
        if _is_hx_76(L_mm, t_mm):
            return _hx_scale(tpms, fluid, L_mm, t_mm, u_mps)
        sf = _air_scale(tpms, L_mm, t_mm)
        return np.ones_like(sf), sf, "air-specimen-friction", "core-calibrated"
    raise ValueError(f"no approved experiment calibration for fluid {fluid!r}")


def apply_correction(tpms: str, fluid: str, L_mm: Any, t_mm: Any,
                     K_base: Any, cF_base: Any, u_mps: Any | None = None
                     ) -> tuple[Any, Any, dict[str, Any]]:
    """Apply one approved fixed correction and return audit metadata."""
    sK, sF, campaign, scope = correction_scale(
        tpms, fluid, L_mm, t_mm, u_mps)
    K0 = np.asarray(K_base, dtype=float)
    cF0 = np.asarray(cF_base, dtype=float)
    K = K0 * sK
    cF = cF0 * sF
    scalar = K.ndim == 0 and cF.ndim == 0
    K_out = float(K) if scalar else K
    cF_out = float(cF) if scalar else cF
    metadata = {
        "base_K": _summary(K0), "base_cF": _summary(cF0),
        "applied_K": _summary(K), "applied_cF": _summary(cF),
        "scale_K": _summary(sK), "scale_F": _summary(sF),
        "campaign": campaign, "scope": scope,
    }
    if scope == "HX-effective":
        lo, hi = hx_application_velocity_bounds(fluid, tpms)
        cal_lo, cal_hi = hx_velocity_bounds(fluid, tpms)
        u = np.asarray(u_mps, dtype=float)
        metadata.update(inlet_u_mps=_summary(u_mps),
                        velocity_window_mps={"min": lo, "max": hi},
                        calibration_velocity_window_mps={"min": cal_lo, "max": cal_hi},
                        application_scope=_HX_APPLICATION_SCOPE,
                        extrapolated=bool(np.any((u < cal_lo) | (u > cal_hi))))
        record_range(
            ('df-experimental', fluid, tpms), u, (cal_lo, cal_hi),
            label=(f"[D-F extrap] {fluid}/{tpms}; frozen sF; approved application "
                   f"window [{lo}, {hi}] m/s; {_HX_APPLICATION_SCOPE}"),
            quantity='inlet u', unit='m/s')
    return K_out, cF_out, metadata


def apply_prepared_correction(K_base, cF_base, metadata):
    """Apply already resolved scalar factors to the supplied physical fields."""
    sK, sF = metadata['scale_K'], metadata['scale_F']
    if not all(np.isscalar(v) and np.isfinite(v) and v > 0 for v in (sK, sF)):
        raise ValueError('prepared experimental correction requires positive finite scalar factors')
    K0, cF0 = np.asarray(K_base, dtype=float), np.asarray(cF_base, dtype=float)
    K, cF = K0 * sK, cF0 * sF
    info = {**metadata, 'base_K': _summary(K0), 'base_cF': _summary(cF0),
            'applied_K': _summary(K), 'applied_cF': _summary(cF)}
    return K, cF, info


def cfd_metadata(K: Any, cF: Any) -> dict[str, Any]:
    """Audit metadata for the unchanged production CFD mode."""
    return {
        "base_K": _summary(K), "base_cF": _summary(cF),
        "applied_K": _summary(K), "applied_cF": _summary(cF),
        "scale_K": 1.0, "scale_F": 1.0,
        "campaign": "water-sco2-cfd-fixed-v2", "scope": "CFD-smooth-wall",
    }


__all__ = [
    "CFD_SMOOTH", "EXPERIMENTAL", "DF_MODES", "correction_scale",
    "apply_correction", "cfd_metadata", "hx_velocity_bounds",
    "hx_application_velocity_bounds",
]

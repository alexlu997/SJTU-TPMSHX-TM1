"""Approved experiment-effective corrections on the production CFD D-F base.

These selectors route to matching experiment campaigns; they are not fluid
physics.  The fitted differences may include rig, boundary, pressure-tap,
manifold, flow-area, instrument, and reduction effects that are not separated
by the available data.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from sjtu_tpmshx.shared.domain.run_warnings import record_range

CFD_SMOOTH = "cfd_smooth"
EXPERIMENTAL = "experimental"
DF_MODES = (CFD_SMOOTH, EXPERIMENTAL)

# Numerical data and campaign provenance have one resource owner.
from sjtu_tpmshx.shared.configs.model_parameters import load_preparation_df_parameters
from sjtu_tpmshx.shared.models import _native_df

_PARAMETERS = load_preparation_df_parameters()
_HX = _PARAMETERS['hx']
_HX_U_BOUNDS = {(fluid, tp): tuple(window) for fluid, values in _HX['calibration_u_mps'].items()
                for tp, window in values.items()}
_HX_APPLICATION_U_BOUNDS = {(fluid, tp): tuple(window) for fluid, values in _HX['application_u_mps'].items()
                            for tp, window in values.items()}
_HX_APPLICATION_SCOPE = _HX['application_scope']
_GYROID_AIR_CALIBRATION = dict(_HX['gyroid_air_calibration'])
_GYROID_AIR_RUNTIME_CALIBRATION_U = tuple(_HX['runtime_u_mps']['air']['Gyroid'])


def _summary(value: Any) -> float | dict[str, float]:
    return _native_df.summary(value)


def hx_velocity_bounds(fluid: str, tpms: str) -> tuple[float, float]:
    """Return the active calibration's source-convention velocity window."""
    return _HX_U_BOUNDS[(fluid, tpms)]


def hx_application_velocity_bounds(fluid: str, tpms: str) -> tuple[float, float]:
    """Return the approved production application window, with frozen sF."""
    return _HX_APPLICATION_U_BOUNDS[(fluid, tpms)]


def _resolved_scale(tpms, fluid, L_mm, t_mm, u_mps, allow_hx_extrapolation):
    selected = _native_df.selection(tpms, fluid, L_mm, t_mm, u_mps,
                                    transfer=allow_hx_extrapolation)
    sK, sF = _native_df.scales(tpms, selected, L_mm, t_mm, u_mps)
    campaigns = ('air-specimen-friction', 'water-air-hx-7-6',
                 _GYROID_AIR_CALIBRATION['version'], 'sco2-hx-hot-ok-dp')
    scope = 'HX-effective' if selected.scope else 'core-calibrated'
    return sK, sF, campaigns[selected.campaign], scope, selected


def correction_scale(tpms: str, fluid: str, L_mm: Any,
                     t_mm: Any, u_mps: Any | None = None, *,
                     allow_hx_extrapolation: bool = False,
                     ) -> tuple[Any, Any, str, str]:
    """Return native factors and the matching experiment campaign."""
    return _resolved_scale(tpms, fluid, L_mm, t_mm, u_mps, allow_hx_extrapolation)[:4]


def apply_correction(tpms: str, fluid: str, L_mm: Any, t_mm: Any,
                     K_base: Any, cF_base: Any, u_mps: Any | None = None, *,
                     allow_hx_extrapolation: bool = False,
                     ) -> tuple[Any, Any, dict[str, Any]]:
    """Apply one approved fixed correction and return audit metadata."""
    sK, sF, campaign, scope, selected = _resolved_scale(
        tpms, fluid, L_mm, t_mm, u_mps, allow_hx_extrapolation)
    K0 = np.asarray(K_base, dtype=float)
    cF0 = np.asarray(cF_base, dtype=float)
    K = _native_df.apply_scale(K0, sK)
    cF = _native_df.apply_scale(cF0, sF)
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
        runtime_lo, runtime_hi = cal_lo, cal_hi
        if (fluid, tpms) == ("air", "Gyroid"):
            runtime_lo, runtime_hi = _GYROID_AIR_RUNTIME_CALIBRATION_U
            metadata["calibration"] = dict(_GYROID_AIR_CALIBRATION)
        u = np.asarray(u_mps, dtype=float)
        metadata.update(inlet_u_mps=_summary(u_mps),
                        velocity_window_mps={"min": lo, "max": hi},
                        calibration_velocity_window_mps={"min": cal_lo, "max": cal_hi},
                        calibration_runtime_velocity_window_mps={"min": runtime_lo, "max": runtime_hi},
                        application_scope=_HX_APPLICATION_SCOPE,
                        extrapolated=bool(selected.flags & 2))
        if allow_hx_extrapolation:
            metadata.update(transfer_policy='frozen-hx-7-0.6-trend',
                            application_scope='Exploratory Gyroid air/water geometry transfer of '
                                              'frozen 7/0.6 HX factors; accuracy unvalidated')
        record_range(
            ('df-experimental', fluid, tpms), u, (runtime_lo, runtime_hi),
            label=(f"[D-F extrap] {fluid}/{tpms}; frozen sF; "
                   f"{'research transfer' if allow_hx_extrapolation else 'approved application'}; "
                   f"reference window [{lo}, {hi}] m/s; {metadata['application_scope']}"),
            quantity='inlet u', unit='m/s')
    return K_out, cF_out, metadata


def apply_prepared_correction(K_base, cF_base, metadata):
    """Apply already resolved scalar factors to the supplied physical fields."""
    sK, sF = metadata['scale_K'], metadata['scale_F']
    if not all(np.isscalar(v) for v in (sK, sF)):
        raise ValueError('prepared experimental correction requires positive finite scalar factors')
    _native_df.apply_scale(1.0, sK, prepared=True)
    _native_df.apply_scale(1.0, sF, prepared=True)
    K0, cF0 = np.asarray(K_base, dtype=float), np.asarray(cF_base, dtype=float)
    K, cF = _native_df.apply_scale(K0, sK), _native_df.apply_scale(cF0, sF)
    info = {**metadata, 'base_K': _summary(K0), 'base_cF': _summary(cF0),
            'applied_K': _summary(K), 'applied_cF': _summary(cF)}
    return K[()] if K.ndim == 0 else K, cF[()] if cF.ndim == 0 else cF, info


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

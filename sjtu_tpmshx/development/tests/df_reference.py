"""Frozen DF/correction/projection numerical references from fda946ad.

No production predictor, correction, projection or native bridge supplies
expected values. The fixed CSV stays the authoritative coefficient resource.
Projection checks its numerical rows and DF only. Its ignored epsilon input
is not an independent geometry or physical-guard oracle.
"""
from __future__ import annotations
from typing import Any, Optional, Tuple
from math import sqrt
import warnings

from sjtu_tpmshx.shared.domain.run_warnings import record_range, record_warning

R_AIR = 287.05
_CHOKE_WARNED = set()

def pressure_gradient(rho, mu, u, K, cF):
    """Frozen tpms_calc._compute_cached expression from fda946ad."""
    return mu * u / K + rho * cF * u * u

def reset_choke_warn_registry():
    _CHOKE_WARNED.clear()




import csv
from bisect import bisect_left
from math import isfinite
from pathlib import Path

import numpy as np


METHOD = "cfd_full_core_3cell_fixed_v2"
TABLE_PATH = Path(__file__).resolve().parents[2] / "shared/df_surrogate/_prebuilt" / f"{METHOD}.csv"
_TOPOLOGIES = ("Diamond", "Gyroid")
_L_NODES = (4.0, 5.0, 6.0, 7.0, 8.0)
_T_NODES = (0.3, 0.4, 0.5, 0.6)


def _load_table() -> dict[str, dict[tuple[float, float], tuple[float, float]]]:
    tables = {topology: {} for topology in _TOPOLOGIES}
    with TABLE_PATH.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        required = {"tp", "L_mm", "t_mm", "K_m2", "cF_fixed_1_m"}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError("fixed sCO2 CFD coefficient schema mismatch")
        for row in reader:
            topology = row["tp"]
            if topology not in tables:
                raise ValueError(f"unsupported TPMS topology: {topology!r}")
            key = (float(row["L_mm"]), float(row["t_mm"]))
            values = (float(row["K_m2"]), float(row["cF_fixed_1_m"]))
            if key in tables[topology]:
                raise ValueError(f"duplicate fixed sCO2 CFD node: {topology} {key}")
            if key[0] not in _L_NODES or key[1] not in _T_NODES:
                raise ValueError(f"off-grid fixed sCO2 CFD node: {topology} {key}")
            if not all(isfinite(value) and value > 0.0 for value in values):
                raise ValueError(f"invalid fixed sCO2 CFD coefficients: {topology} {key}")
            tables[topology][key] = values

    expected = {(L_mm, t_mm) for L_mm in _L_NODES for t_mm in _T_NODES}
    if any(set(table) != expected for table in tables.values()):
        raise ValueError("fixed sCO2 CFD coefficient grid is incomplete")
    return tables


_TABLE = _load_table()


def _bracket(value: float, nodes: tuple[float, ...]) -> tuple[float, float, float]:
    value = float(value)
    tol = 1e-12 * max(1.0, abs(value))
    if value < nodes[0] - tol or value > nodes[-1] + tol:
        raise ValueError
    value = min(max(value, nodes[0]), nodes[-1])
    upper = bisect_left(nodes, value)
    if upper < len(nodes) and abs(value - nodes[upper]) <= tol:
        return nodes[upper], nodes[upper], 0.0
    lower = upper - 1
    lo, hi = nodes[lower], nodes[upper]
    return lo, hi, (value - lo) / (hi - lo)


def _bracket_batch(values, nodes):
    nodes = np.asarray(nodes, dtype=np.float64)
    tol = 1e-12 * np.maximum(1.0, np.abs(values))
    if np.any((values < nodes[0] - tol) | (values > nodes[-1] + tol)):
        raise ValueError
    values = np.clip(values, nodes[0], nodes[-1])
    # Match bisect_left, including its NaN insertion point and lower-side snap.
    upper = np.searchsorted(nodes, np.where(np.isnan(values), nodes[0], values))
    snapped = np.abs(values - nodes[upper]) <= tol
    lower = np.where(snapped, upper, upper - 1)
    weight = np.zeros(values.shape, dtype=np.float64)
    np.divide(values - nodes[lower], nodes[upper] - nodes[lower],
              out=weight, where=~snapped)
    return lower, upper, weight


class FullCore3CellFixedDFV2:
    """Return node values or bilinear ``(L, t)`` interpolation within the CFD grid."""

    def __init__(self, tpms: str):
        if tpms not in _TABLE:
            raise ValueError("fixed sCO2 CFD coefficients support Diamond/Gyroid only")
        self.tpms = tpms

    def predict(
        self, L_mm: float, t_mm: float, eps_f: float | None = None
    ) -> tuple[float, float]:
        del eps_f
        try:
            L0, L1, wL = _bracket(L_mm, _L_NODES)
            t0, t1, wt = _bracket(t_mm, _T_NODES)
        except ValueError as exc:
            raise ValueError(
                "geometry is outside the fixed sCO2 CFD grid: "
                "4 <= L <= 8 mm and 0.3 <= t <= 0.6 mm"
            ) from exc

        table = _TABLE[self.tpms]
        result = []
        for index in (0, 1):
            at_t0 = ((1.0 - wL) * table[L0, t0][index]
                     + wL * table[L1, t0][index])
            at_t1 = ((1.0 - wL) * table[L0, t1][index]
                     + wL * table[L1, t1][index])
            result.append((1.0 - wt) * at_t0 + wt * at_t1)
        return result[0], result[1]

    def predict_batch(self, L_mm, t_mm):
        """Evaluate matching arrays in the scalar interpolation's operation order."""
        try:
            L0, L1, wL = _bracket_batch(L_mm, _L_NODES)
            t0, t1, wt = _bracket_batch(t_mm, _T_NODES)
        except ValueError as exc:
            raise ValueError(
                "geometry is outside the fixed sCO2 CFD grid: "
                "4 <= L <= 8 mm and 0.3 <= t <= 0.6 mm"
            ) from exc
        values = np.asarray([[_TABLE[self.tpms][L, t] for t in _T_NODES]
                             for L in _L_NODES], dtype=np.float64)
        result = []
        for index in (0, 1):
            table = values[:, :, index]
            at_t0 = (1.0 - wL) * table[L0, t0] + wL * table[L1, t0]
            at_t1 = (1.0 - wL) * table[L0, t1] + wL * table[L1, t1]
            result.append((1.0 - wt) * at_t0 + wt * at_t1)
        return result[0], result[1]



SCO2_DF_METHOD = METHOD

def predict_K_cF(topology, L_mm, t_mm, eps_f, method=None):
    if method is not None and method != METHOD:
        raise ValueError('reference accepts the fixed method only')
    return FullCore3CellFixedDFV2(topology).predict(L_mm, t_mm, eps_f)

def predict_K_cF_vec(topology, L_mm, t_mm, eps_f, method=None):
    if method is not None and method != METHOD:
        raise ValueError('reference accepts the fixed method only')
    L = np.asarray(L_mm, dtype=np.float64)
    t = np.asarray(t_mm, dtype=np.float64)
    eps = np.asarray(eps_f, dtype=np.float64)
    shape = np.broadcast(L, t, eps).shape
    model = FullCore3CellFixedDFV2(topology)
    result = model.predict_batch(np.broadcast_to(L, shape).ravel(),
                                 np.broadcast_to(t, shape).ravel())
    return tuple(value.reshape(shape) for value in result)

def predict_dP(tpms_type: str, L_mm: float, t_mm: float, eps_f: float,
               u: float, rho: float, mu: float,
               L_channel_m: float, method: str | None = None) -> float:
    """Compute dP via incompressible D-F (backward-compatible interface).

    For compressible flow, use predict_dP_compressible instead.
    """
    K, c_F = predict_K_cF(tpms_type, L_mm, t_mm, eps_f, method=method)
    return (mu * u / K + rho * c_F * u ** 2) * L_channel_m


def predict_dP_compressible(tpms_type: str, L_mm: float, t_mm: float,
                            eps_f: float, G: float, T: float,
                            P_in: float, mu: float,
                            L: float, strict: bool = False,
                            method: str | None = None) -> float:
    """1D isothermal ideal-gas D-F pressure-drop approximation for air.

    P_out^2 = P_in^2 - 2*R*T*(mu*G/K + c_F*G^2)*L

    Parameters
    ----------
    G : mass flux [kg/(m^2 s)]
    T : temperature [K]
    P_in : inlet absolute pressure [Pa]
    mu : dynamic viscosity [Pa s]
    L : channel length [m]
    strict : if no positive outlet pressure solution exists, True returns NaN
        and False returns P_in as a fallback dP. Neither is a solved pressure.
    """
    K, c_F = predict_K_cF(tpms_type, L_mm, t_mm, eps_f, method=method)
    C = mu * G / K + c_F * G ** 2
    P_out_sq = P_in ** 2 - 2.0 * R_AIR * T * C * L
    if P_out_sq <= 0:
        # No positive P_out: preserve each return policy without interpreting
        # failure of this approximation as a physical choking diagnosis.
        _choke_key = (tpms_type, round(float(L_mm), 2), round(float(t_mm), 2),
                      bool(strict))
        return_policy = ("returning NaN (strict=True)." if strict else
                         "returning P_in as a fallback dP (strict=False).")
        message = (
            f"[D-F approximation] 1D isothermal air pressure model has no "
            f"positive outlet pressure solution (P_out^2={P_out_sq:.3e} <= 0); "
            f"{return_policy} This is not a physical choking diagnosis. "
            "Check mass flux, channel length and inlet pressure.")
        if (not record_warning(('df_choke', *_choke_key), message)
                and _choke_key not in _CHOKE_WARNED):
            _CHOKE_WARNED.add(_choke_key)
            warnings.warn(message, stacklevel=2)
        return float('nan') if strict else P_in
    return P_in - sqrt(P_out_sq)

CFD_SMOOTH = "cfd_smooth"
EXPERIMENTAL = "experimental"
DF_MODES = (CFD_SMOOTH, EXPERIMENTAL)

# Fixed-K0 relative fits against raw_data/experiments/air/
# air_DG_specimen_experiment_summary.xlsx.
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
_AIR_T = np.array([0.3, 0.4, 0.5])

# Fixed-K0 HX-effective fits. Gyroid air uses the April 1 straight-air
# campaign; water and Diamond air retain their original campaigns.
# sCO2 uses the hot-side ok_dp rows from sCO2-Experient.xlsx.
# Bounds are the matching campaigns' measured inlet-velocity spans.
_HX_SF = {
    ("water", "Diamond"): 4.892779870412083,
    ("water", "Gyroid"): 4.198913430360186,
    ("air", "Diamond"): 1.8024228153853061,
    ("air", "Gyroid"): 2.649010286988306,
    ("sco2", "Diamond"): 6.313005350332494,
    ("sco2", "Gyroid"): 7.608907691857889,
}
_HX_U_BOUNDS = {
    ("water", "Diamond"): (0.10, 0.25405479940574704),
    ("water", "Gyroid"): (0.10, 0.2232167044622796),
    ("air", "Diamond"): (7.656604926203154, 22.759887982116293),
    ("air", "Gyroid"): (8.026110584256458, 22.441995588974073),
    # Same hot-side members, mdot and flow area; rho_in uses gauge + 101325 Pa.
    # Corrected 2026-09-06 with user approval; the sF values above stay frozen.
    ("sco2", "Diamond"): (0.5826657772921353, 2.53960962894522),
    ("sco2", "Gyroid"): (0.6119811082039116, 2.470456518760552),
}

# Approved 2026-09-09: production inlet density and voxel single-side area.
# Keep active calibration windows separate: source audits and fit membership use them.
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

_GYROID_AIR_CALIBRATION = {
    "version": "shanghai-air-straight-20260401-v1",
    "source": "experiments/water_air/water-air_G7-t0p6_shanghai_experiment_20260401.xlsx",
    "sheet": "Sheet1", "excel_rows": "4:18", "cases": "2-16",
    "mass_flow": "F: nominal kg/s",
    "temperature": "mean of AC/AD, degC converted to K",
    "pressure": "AE/AF: gauge Pa; add 101325 Pa",
    "method": "fixed CFD K0; 1D compressible dP; mean squared relative error",
    "filter": "dP >= 2000 Pa and no duplicate row; case 1 reported separately",
    "accuracy_scope": "reviewed Shanghai air-water cases; other fluid pairs unvalidated",
    "report": "docs/model-resources.md",
}
# Same April 1 members in the production inlet-density convention. The 1D
# fit keeps R=287.05; using its source-audit speeds to check runtime speeds
# would incorrectly flag the upper calibration endpoint as extrapolation.
_GYROID_AIR_RUNTIME_CALIBRATION_U = (8.027855328062564, 22.446874107951544)


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
    """Return the active calibration's source-convention velocity window."""
    return _HX_U_BOUNDS[(fluid, tpms)]


def hx_application_velocity_bounds(fluid: str, tpms: str) -> tuple[float, float]:
    """Return the approved production application window, with frozen sF."""
    return _HX_APPLICATION_U_BOUNDS[(fluid, tpms)]


def _hx_scale(tpms: str, fluid: str, L_mm: Any, t_mm: Any,
              u_mps: Any | None, *, allow_hx_extrapolation: bool = False) -> tuple[Any, Any, str, str]:
    if not _is_hx_76(L_mm, t_mm):
        raise ValueError(
            f"{fluid} HX experiment calibration is valid only for the "
            "matching D/G-7-6 geometry (L=7 mm, t=0.6 mm)")
    if u_mps is None:
        raise ValueError(
            f"{fluid} HX experiment calibration requires inlet velocity")
    u = np.asarray(u_mps, dtype=float)
    if not np.all(np.isfinite(u) & (u > 0)):
        raise ValueError('HX experiment calibration requires finite positive inlet velocity')
    lo, hi = hx_application_velocity_bounds(fluid, tpms)
    if not allow_hx_extrapolation and np.any((u < lo - 1e-12) | (u > hi + 1e-12)):
        raise ValueError(
            f"{fluid} HX experiment calibration requires {lo:.6g}<=u<="
            f"{hi:.6g} m/s for {tpms}; got {_summary(u)}")
    shape = np.broadcast(np.asarray(L_mm), np.asarray(t_mm), u).shape
    sf = np.full(shape, _HX_SF[(fluid, tpms)])
    campaign = ("sco2-hx-hot-ok-dp" if fluid == "sco2"
                else "water-air-hx-7-6")
    if (fluid, tpms) == ("air", "Gyroid"):
        campaign = _GYROID_AIR_CALIBRATION["version"]
    return np.ones_like(sf), sf, campaign, "HX-effective"


def correction_scale(tpms: str, fluid: str, L_mm: Any,
                     t_mm: Any, u_mps: Any | None = None, *,
                     allow_hx_extrapolation: bool = False,
                     ) -> tuple[Any, Any, str, str]:
    """Return ``(sK, sF, campaign, scope)`` for one matched dataset."""
    if allow_hx_extrapolation:
        if tpms != 'Gyroid' or fluid not in ('air', 'water'):
            raise ValueError('HX trend extrapolation is limited to Gyroid air/water')
        return _hx_scale(tpms, fluid, L_mm, t_mm, u_mps, allow_hx_extrapolation=True)
    if fluid in ("water", "sco2"):
        return _hx_scale(tpms, fluid, L_mm, t_mm, u_mps)
    if fluid == "air":
        if _is_hx_76(L_mm, t_mm):
            return _hx_scale(tpms, fluid, L_mm, t_mm, u_mps)
        sf = _air_scale(tpms, L_mm, t_mm)
        return np.ones_like(sf), sf, "air-specimen-friction", "core-calibrated"
    raise ValueError(f"no approved experiment calibration for fluid {fluid!r}")


def apply_correction(tpms: str, fluid: str, L_mm: Any, t_mm: Any,
                     K_base: Any, cF_base: Any, u_mps: Any | None = None, *,
                     allow_hx_extrapolation: bool = False,
                     ) -> tuple[Any, Any, dict[str, Any]]:
    """Apply one approved fixed correction and return audit metadata."""
    sK, sF, campaign, scope = correction_scale(
        tpms, fluid, L_mm, t_mm, u_mps, allow_hx_extrapolation=allow_hx_extrapolation)
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
                        extrapolated=bool(np.any((u < runtime_lo) | (u > runtime_hi))))
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



def _cell_centre_fracs(n_target: int,
                       widths: Optional[np.ndarray]) -> np.ndarray:
    """Cell-centre fractional coordinates of a target axis. ``widths``
    None → uniform; else non-uniform cell widths (wall-refined grids)."""
    if widths is None:
        return (np.arange(n_target) + 0.5) / n_target
    w = np.asarray(widths, dtype=np.float64)
    cum = np.concatenate([[0.0], np.cumsum(w)])
    return 0.5 * (cum[:-1] + cum[1:]) / w.sum()


def _nearest_src_idx(fracs: np.ndarray, src_n: int) -> np.ndarray:
    """Nearest-neighbour source indices for fractional probe points."""
    return np.clip((fracs * src_n).astype(int), 0, src_n - 1)


def project_fields_to_streamwise_K_cF(L_field: np.ndarray,
                                       t_field: np.ndarray,
                                       tpms_type: str,
                                       k_s: float,
                                       Ny_sim: int,
                                       direction: int,
                                       streamwise_dx: Optional[np.ndarray] = None,
                                       *, source_grid=None
                                       ) -> Tuple[np.ndarray, np.ndarray]:
    """Project real XY L/t cells onto SIMPLE's inlet-to-outlet drag rows.

    direction is 0=+x, 1=-x, 2=+y or 3=-y. L/t are averaged across the
    physical transverse width before predicting K/cF; this retains the 1D
    row approximation rather than averaging the nonlinear drag coefficients.
    source_grid=(dx, dy) gives actual source widths. Omission means a uniform
    source mesh. streamwise_dx describes target rows in inlet-to-outlet order.
    """
    if direction not in (0, 1, 2, 3):
        raise ValueError(f"direction must be 0, 1, 2 or 3, got {direction!r}")
    stream_axis = 0 if direction in (0, 1) else 1
    cross_axis = 1 - stream_axis
    reverse = direction in (1, 3)
    src_n = L_field.shape[stream_axis]
    if source_grid is None:
        L_1d, t_1d = (f.mean(axis=cross_axis) for f in (L_field, t_field))
        stream_widths = None
    else:
        widths = tuple(np.asarray(w) for w in source_grid)
        L_1d, t_1d = (np.average(f, axis=cross_axis, weights=widths[cross_axis])
                       for f in (L_field, t_field))
        stream_widths = widths[stream_axis]
    if reverse:
        L_1d, t_1d = L_1d[::-1], t_1d[::-1]
        if stream_widths is not None:
            stream_widths = stream_widths[::-1]

    s_fracs = _cell_centre_fracs(Ny_sim, streamwise_dx)
    if stream_widths is None:
        src_idx = _nearest_src_idx(s_fracs, src_n)
    else:
        src_idx = np.minimum(np.searchsorted(np.cumsum(stream_widths),
                                             s_fracs * stream_widths.sum(), side='right'), src_n - 1)

    # Per-cell loop kept loop-form: eps_f derives from tpms_geometry per
    # (L, t) probe and the float evaluation order is gate-pinned.
    L_row = np.empty(Ny_sim, dtype=np.float64)
    t_row = np.empty(Ny_sim, dtype=np.float64)
    eps_f_row = np.empty(Ny_sim, dtype=np.float64)
    for j in range(Ny_sim):
        L_avg = float(L_1d[src_idx[j]]); t_avg = float(t_1d[src_idx[j]])
        # DF ignores epsilon. Geometry guards have separate regression checks.
        L_row[j] = L_avg; t_row[j] = t_avg; eps_f_row[j] = 0.35

    K_arr, cF_arr = predict_K_cF_vec(
        tpms_type, L_row, t_row, eps_f_row, method=SCO2_DF_METHOD)
    return K_arr.astype(np.float64), cF_arr.astype(np.float64)

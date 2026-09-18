"""State-local physical heat-transfer closure shared by dimensional backends."""
import numpy as np


def local_speed(uc, vc, wc=None):
    """Cell-centered pore speed for scalar local Re/Nu; no porosity rescaling.

    Face mass/enthalpy fluxes still use signed normal velocity components.
    """
    speed_squared = uc**2 + vc**2
    if wc is not None:
        speed_squared = speed_squared + wc**2
    return np.sqrt(speed_squared)


def _sco2_hv_local_field(T_field: np.ndarray, P_Pa: float,
                         u_abs: np.ndarray | float, A_0: float,
                         D_h_m: float, tpms_type: str,
                         L_cell_mm: float, *, sco2_nu=None, observation=None) -> np.ndarray:
    """Shared 2D/3D sCO2 h_v = A_0·Nu·k(T)/D_h with local properties.

    ρ, μ, k, cp — hence Re and Pr — are evaluated per cell at the local
    temperature field (fixed P), not frozen at the scalar inlet T. sCO2
    transport props swing 2-8× across the pseudocritical line, so freezing
    them at inlet biases fluid↔solid coupling wherever local T departs from
    inlet. Air/water property sampling belongs to each caller: 2D also uses
    field averages, including lagged-temperature properties on a mixed true-h
    side; 3D local air/water closure uses scalar inlet properties.
    """
    from sjtu_tpmshx.models import sco2_props as _s2
    from sjtu_tpmshx.models.tpms_calc import nu_sco2_topo as _nu_s2
    from sjtu_tpmshx.models.nu_correlations import NU_LAM_FLOOR as _floor
    from sjtu_tpmshx.models.nu_correlations import record_raw_nu_range
    T = np.asarray(T_field, dtype=np.float64)
    rho = _s2.sco2_density_field(T, P_Pa)
    mu = _s2.sco2_viscosity_field(T, P_Pa)
    k_f = _s2.sco2_conductivity_field(T, P_Pa)
    Pr = _s2.sco2_cp_field(T, P_Pa) * mu / np.maximum(k_f, 1e-30)
    Re_loc = rho * np.abs(u_abs) * D_h_m / np.maximum(mu, 1e-30)
    record_raw_nu_range('sco2', tpms_type, Re_loc)
    if sco2_nu is not None:
        sco2_nu.validate()
        if sco2_nu.mode == 'experimental':
            from functools import partial
            from sjtu_tpmshx.models.nu_correlations import nu_sco2_selected
            _nu_s2 = partial(nu_sco2_selected, settings=sco2_nu)
    Nu_raw = np.asarray(_nu_s2(tpms_type, np.maximum(Re_loc, 1.0), Pr,
                               L_cell_mm, D_h_m * 1000.0), dtype=np.float64)
    if observation is not None:
        observation.clear()
        observation.update(
            stage='last local h_v coefficient evaluation (lagged temperature)',
            shape=list(Nu_raw.shape), cells=int(Nu_raw.size),
            floor_cells=int(np.count_nonzero(Nu_raw < _floor)),
            floor_fraction=float(np.mean(Nu_raw < _floor)), floor=float(_floor),
            pre_floor_min=float(Nu_raw.min()), pre_floor_max=float(Nu_raw.max()),
            Re_min=float(Re_loc.min()), Re_max=float(Re_loc.max()),
            Pr_min=float(Pr.min()), Pr_max=float(Pr.max()),
            T_min_K=float(T.min()), T_max_K=float(T.max()),
            P_abs_Pa=float(P_Pa))
    Nu_loc = np.maximum(Nu_raw, _floor)
    return A_0 * Nu_loc * k_f / D_h_m

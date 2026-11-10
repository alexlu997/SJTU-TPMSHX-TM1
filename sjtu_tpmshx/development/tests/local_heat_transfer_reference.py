"""Local closure reference frozen from the retired test-only Python owner.

Property and Nu values come from independent development references. Generic
warning owners retain the original observation context. No native output is
used as the numerical reference.
"""
import numpy as np

from . import eos_reference
from .nu_reference import NU_LAM_FLOOR
from .property_reference import fluid_model


def local_speed(uc, vc, wc=None):
    speed_squared = uc**2 + vc**2
    if wc is not None:
        speed_squared = speed_squared + wc**2
    return np.sqrt(speed_squared)


def local_nusselt(model, tpms_type, Re, eps_f, L_mm, D_h_mm, Pr):
    Nu = model.nu(tpms_type, np.maximum(Re, 1.0), eps_f, L_mm, D_h_mm, Pr)
    return np.maximum(np.asarray(Nu, dtype=np.float64), NU_LAM_FLOOR * model.nu_floor_multiplier)


def real_fluid_hv_local_field(T_field, P_Pa, u_abs, A_0, D_h_m, tpms_type,
                              L_cell_mm, *, fluid='sco2', sco2_nu=None, observation=None):
    from sjtu_tpmshx.shared.models.nu_correlations import (
        record_raw_nu_range, _warn_sco2_nu,
    )
    from sjtu_tpmshx.shared.models.co2_correlations import _observe, RE_RANGE

    T = np.asarray(T_field, dtype=np.float64)
    model = fluid_model(fluid, sco2_nu=sco2_nu)
    properties = eos_reference.co2_prop if fluid == 'co2' else eos_reference.sco2_prop
    rho, mu, k_f, cp = properties(('D', 'V', 'L', 'C'), T, P_Pa)
    floor = NU_LAM_FLOOR * model.nu_floor_multiplier
    Pr = cp * mu / np.maximum(k_f, 1e-30)
    Re_loc = rho * np.abs(u_abs) * D_h_m / np.maximum(mu, 1e-30)
    record_raw_nu_range(fluid, tpms_type, Re_loc)
    prepared = np.maximum(Re_loc, 1.0)
    if fluid == 'sco2' and prepared.size:
        _warn_sco2_nu(float(prepared.min()), float(prepared.max()), tpms_type, prepared)
    elif fluid == 'co2':
        _observe(tpms_type, 'Re', prepared, RE_RANGE)
        _observe(tpms_type, 'Pr', Pr, (1.0137227801530173, 3.760086553568298))
    Nu_raw = np.asarray(model.nu(tpms_type, prepared, None, L_cell_mm, D_h_m * 1000.0, Pr), dtype=np.float64)
    if observation is not None:
        observation.clear()
        observation.update(
            stage='last local h_v coefficient evaluation (lagged temperature)',
            shape=list(Nu_raw.shape), cells=int(Nu_raw.size),
            floor_cells=int(np.count_nonzero(Nu_raw < floor)),
            floor_fraction=float(np.mean(Nu_raw < floor)), floor=float(floor),
            pre_floor_min=float(Nu_raw.min()), pre_floor_max=float(Nu_raw.max()),
            Re_min=float(Re_loc.min()), Re_max=float(Re_loc.max()),
            Pr_min=float(Pr.min()), Pr_max=float(Pr.max()),
            T_min_K=float(T.min()), T_max_K=float(T.max()), P_abs_Pa=float(P_Pa))
    Nu_loc = np.maximum(Nu_raw, floor)
    return A_0 * Nu_loc * k_f / D_h_m

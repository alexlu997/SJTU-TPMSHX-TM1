"""Independent Nu and roughness expressions frozen at fad54db1.

Fixed data and numerical expressions do not import production model owners.
Range-record policy has separate regression coverage.
"""
import numpy as np


Pr_AIR = 0.72
NU_ROUGHNESS_FACTOR = 1.28
NU_LAM_FLOOR = 4.36
NU_COEFFS = {
    'Diamond': {'c': 0.0944, 'a': 0.8273, 'd': 0.226},
    'Gyroid': {'c': 0.126, 'a': 0.7898, 'd': 0.2409},
}
WATER_NU_COEFFS = {
    'Diamond': {'c': 0.3201, 'a': 0.6679},
    'Gyroid': {'c': 0.3941, 'a': 0.6435},
}
SCO2_NU_COEFFS = {
    'Diamond': {'c': 0.184809, 'a': 0.707421, 'd': -0.281792},
    'Gyroid': {'c': 0.192994, 'a': 0.722221, 'd': -0.044313},
}
CO2_THETA = {
    'Diamond': (5.116529451028265, 0.7145279830193259, 0.3962239747502244,
                -0.13822384274620997, 0.037642668209224774),
    'Gyroid': (5.132632037826328, 0.7203859410190846, 0.4010670336041154,
               0.070960180613071, 0.038179175396474085),
}


def _smooth_nu(tpms_type, Re, L_mm, D_h_mm, *, Pr=Pr_AIR):
    c = NU_COEFFS[tpms_type]
    return c['c'] * Pr ** (1/3) * Re ** c['a'] * (D_h_mm / L_mm) ** c['d']


def nu_from_Re(tpms_type, Re, eps_f, L_mm, D_h_mm, *, Pr=Pr_AIR):
    del eps_f
    Re_arr = np.asarray(Re, dtype=np.float64)
    Re_value = float(Re_arr) if Re_arr.ndim == 0 else Re_arr
    return NU_ROUGHNESS_FACTOR * _smooth_nu(tpms_type, Re_value, L_mm, D_h_mm, Pr=Pr)


def nu_vec(tpms_type, Re, L_mm, D_h_mm, *, Re_floor=10.0, Pr=Pr_AIR):
    Re_arr = np.maximum(np.asarray(Re, dtype=np.float64), Re_floor)
    return NU_ROUGHNESS_FACTOR * _smooth_nu(tpms_type, Re_arr, L_mm, D_h_mm, Pr=Pr)


def nu_water_topo(tpms_type, Re, Pr_water):
    Re_safe = np.maximum(Re, 1.0)
    co = WATER_NU_COEFFS[tpms_type]
    return co['c'] * Re_safe ** co['a'] * Pr_water ** (1 / 3)


def nu_sco2_topo(tpms_type, Re, Pr_sco2, L_mm, D_h_mm):
    if tpms_type not in SCO2_NU_COEFFS:
        raise NotImplementedError(
            f'sCO2 Nu fit only available for {sorted(SCO2_NU_COEFFS)} '
            f'(2026-07 sCO2 CFD campaign); {tpms_type!r} unsupported.')
    Re_safe = np.maximum(Re, 1.0)
    co = SCO2_NU_COEFFS[tpms_type]
    return (co['c'] * Re_safe ** co['a'] * Pr_sco2 ** (1 / 3)
            * (D_h_mm / L_mm) ** co['d'])


def nu_sco2_selected(tpms_type, Re, Pr, L_mm, D_h_mm, *, settings):
    settings.validate()
    base = nu_sco2_topo(tpms_type, Re, Pr, L_mm, D_h_mm)
    if settings.mode == 'cfd_smooth':
        return base
    alpha = settings.alpha_D if tpms_type == 'Diamond' else settings.alpha_G
    return alpha * base


def co2_nusselt(tpms, Re, Pr, L_mm, Dh_mm):
    re, pr, cell, dh = np.broadcast_arrays(
        *(np.asarray(v, dtype=float) for v in (Re, Pr, L_mm, Dh_mm)))
    if not all(v.size and np.isfinite(v).all() and (v > 0).all()
               for v in (re, pr, cell, dh)):
        raise ValueError('CO2 closure inputs must be finite and positive')
    if tpms not in CO2_THETA:
        raise ValueError('CO2 supports Diamond and Gyroid only')
    b = CO2_THETA[tpms]
    x, y, z = np.log(re / 1e4), np.log(pr / 2.), np.log((dh / cell) / .5)
    result = 1.28 * np.exp(b[0] + b[1]*x + b[2]*y + b[3]*z + b[4]*x*x)
    return float(result) if result.ndim == 0 else result


def f_petukhov(Re):
    Re = np.asarray(Re, dtype=np.float64)
    return (0.79 * np.log(Re) - 1.64) ** (-2)


def f_haaland(Re, eps_over_Dh):
    Re = np.asarray(Re, dtype=np.float64)
    return (1.0 / (-1.8 * np.log10((eps_over_Dh / 3.7) ** 1.11 + 6.9 / Re))) ** 2


def f_enhancement(Re, mode='baseline', eps_um=None, D_h_mm=None):
    if mode in ('baseline', 'norris_1a'):
        return 1.0
    if mode == 'bhatti_shah_1b':
        if eps_um is None or D_h_mm is None:
            raise ValueError('bhatti_shah_1b needs eps_um + D_h_mm')
        eod = (eps_um * 1e-3) / D_h_mm
        return float(f_haaland(Re, eod) / f_petukhov(Re))
    raise ValueError(f'unknown roughness mode {mode!r}')


def nu_extra_factor(Re, mode='baseline', eps_um=None, D_h_mm=None):
    if mode in ('baseline', 'norris_1a'):
        return 1.0
    if mode == 'bhatti_shah_1b':
        f_gain = f_enhancement(Re, mode, eps_um, D_h_mm)
        g_nu = f_gain ** 0.68
        return float(g_nu / NU_ROUGHNESS_FACTOR)
    raise ValueError(f'unknown roughness mode {mode!r}')

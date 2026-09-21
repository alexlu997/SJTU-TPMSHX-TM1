"""Optional air-side roughness factors for diagnostic parameter sweeps.

``baseline`` and the retained configuration name ``norris_1a`` both return
unit friction and additional-Nu factors. The air Nu correlation already
contains its 1.28 factor; these modes add nothing to it. ``bhatti_shah_1b``
uses the Haaland/Petukhov friction ratio and its 0.68 power for heat transfer,
with an explicit roughness height. It is an optional model choice, not an
experimentally qualified correction for every TPMS case.

Current water Nu uses direct smooth-wall CFD coefficients, rather than the
retired Yan comparison. This helper is applied by callers to air only.
Current D-F calibration provenance and applicability are documented in
``docs/model-resources.md``. Earlier ConstDF and Shanghai error figures are
historical evidence, not the definition or accuracy of today's model.

Formula references: Haaland (1983), Petukhov (1970), Norris (1971), and
Bhatti & Shah (1987). Historical mode changes remain in Git history.
"""

from __future__ import annotations
import numpy as np


# ─── Smooth-wall friction baselines ─────────────────────────────────


def f_petukhov(Re):
    """Smooth-wall turbulent friction factor (Petukhov 1970).

    Range: Re ~ 3e3 - 5e6. Returns Darcy (Moody) f, not Fanning.
    """
    Re = np.asarray(Re, dtype=np.float64)
    return (0.790 * np.log(Re) - 1.64) ** (-2)


def f_haaland(Re, eps_over_Dh):
    """Rough-wall turbulent friction factor (Haaland 1983 explicit approx
    to Colebrook-White, <= 2 % error). Darcy f.
    """
    Re = np.asarray(Re, dtype=np.float64)
    return (1.0 / (-1.8 * np.log10(
        (eps_over_Dh / 3.7) ** 1.11 + 6.9 / Re))) ** 2


# ─── Public API ─────────────────────────────────────────────────────


def f_enhancement(Re, mode='baseline', eps_um=None, D_h_mm=None):
    """Roughness enhancement factor for friction: f_rough / f_smooth.

    Returns 1.0 for ``baseline`` so default state preserves prior behavior.
    """
    if mode == 'baseline':
        return 1.0
    if mode == 'norris_1a':
        # Retained configuration spelling; no additional correction.
        return 1.0
    if mode == 'bhatti_shah_1b':
        if eps_um is None or D_h_mm is None:
            raise ValueError("bhatti_shah_1b needs eps_um + D_h_mm")
        eod = (eps_um * 1e-3) / D_h_mm                  # both in mm now
        return float(f_haaland(Re, eod) / f_petukhov(Re))
    raise ValueError(f"unknown roughness mode {mode!r}")


def nu_extra_factor(Re, mode='baseline', eps_um=None, D_h_mm=None):
    """Multiplier ABOVE the existing ×1.28 baseline Nu in tpms_calc.

    Current `nu_from_Re` already returns ×1.28 × Nu_smooth for air. This
    helper returns the factor required ON TOP of that to reach the
    consistency target. ``baseline`` and ``norris_1a`` return 1.0 (no extra);
    ``bhatti_shah_1b`` returns g_Nu(Re,ε)/1.28 to override.
    """
    if mode in ('baseline', 'norris_1a'):
        return 1.0
    if mode == 'bhatti_shah_1b':
        f_gain = f_enhancement(Re, mode, eps_um, D_h_mm)
        g_nu = f_gain ** 0.68
        return float(g_nu / 1.28)
    raise ValueError(f"unknown roughness mode {mode!r}")


def apply_to_K_cF(K, cF, f_gain):
    """Apply friction enhancement to Darcy-Forchheimer K, cF arrays.

    Brinkman term μ/K scales linearly with f → K_new = K / f_gain.
    Forchheimer term cF ρ |v| v scales linearly with f → cF_new = cF × f_gain.
    """
    return K / float(f_gain), cF * float(f_gain)


def resolve_mode_from_env(default='baseline'):
    """Read mode + eps_um from environment for ad-hoc validation sweeps.

    Env vars:
      TPMSHX_ROUGH_MODE   = baseline | norris_1a | bhatti_shah_1b
      TPMSHX_ROUGH_EPS_UM = ε in micrometres (only used by bhatti_shah_1b)
    """
    import os
    mode = os.environ.get('TPMSHX_ROUGH_MODE', default).strip().lower()
    eps_um = float(os.environ.get('TPMSHX_ROUGH_EPS_UM', '100'))
    return mode, eps_um

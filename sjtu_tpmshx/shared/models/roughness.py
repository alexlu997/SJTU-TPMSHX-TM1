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
from . import _native_properties

# ─── Smooth-wall friction baselines ─────────────────────────────────


def f_petukhov(Re):
    """Smooth-wall turbulent friction factor (Petukhov 1970).

    Range: Re ~ 3e3 - 5e6. Returns Darcy (Moody) f, not Fanning.
    """
    return _native_properties.roughness(0, Re)


def f_haaland(Re, eps_over_Dh):
    """Rough-wall turbulent friction factor (Haaland 1983 explicit approx
    to Colebrook-White, <= 2 % error). Darcy f.
    """
    return _native_properties.roughness(1, Re, eps_over_Dh)


# ─── Public API ─────────────────────────────────────────────────────


def f_enhancement(Re, mode='baseline', eps_um=None, D_h_mm=None):
    """Roughness enhancement factor for friction: f_rough / f_smooth.

    Returns 1.0 for ``baseline`` so default state preserves prior behavior.
    """
    if mode == 'baseline':
        return _native_properties.roughness(5)
    if mode == 'norris_1a':
        # Retained configuration spelling; no additional correction.
        return _native_properties.roughness(5)
    if mode == 'bhatti_shah_1b':
        if eps_um is None or D_h_mm is None:
            raise ValueError("bhatti_shah_1b needs eps_um + D_h_mm")
        eod = _native_properties.roughness(2, eps_um, D_h_mm)
        return float(_native_properties.roughness(3, Re, eod))
    raise ValueError(f"unknown roughness mode {mode!r}")


def nu_extra_factor(Re, mode='baseline', eps_um=None, D_h_mm=None):
    """Multiplier ABOVE the existing ×1.28 baseline Nu in tpms_calc.

    Current `nu_from_Re` already returns ×1.28 × Nu_smooth for air. This
    helper returns the factor required ON TOP of that to reach the
    consistency target. ``baseline`` and ``norris_1a`` return 1.0 (no extra);
    ``bhatti_shah_1b`` returns g_Nu(Re,ε)/1.28 to override.
    """
    if mode in ('baseline', 'norris_1a'):
        return _native_properties.roughness(5)
    if mode == 'bhatti_shah_1b':
        f_gain = f_enhancement(Re, mode, eps_um, D_h_mm)
        return float(_native_properties.roughness(4, f_gain))
    raise ValueError(f"unknown roughness mode {mode!r}")




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

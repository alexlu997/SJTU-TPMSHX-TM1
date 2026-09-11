"""solvers/roughness.py — Re-dep / scalar wall-roughness correction factors
for air-side Nu and Darcy-Forchheimer friction.

⚠⚠⚠  PROVISIONAL / EXPECTED-TO-CHANGE  ⚠⚠⚠
══════════════════════════════════════════════════════════════════════════

2026-05-14 revision — symmetric Nu/f roughness pairing REMOVED.

Derivation chain rebuilt after a second user audit:

    1. 试验记录表 v3.1 AM SLM samples measured Sa ≈ 31 μm.
    2. ConstDF-v1 (K, c_F) was trained on the *real* SLM dP recorded
       in 试验记录表; the fitted c_F therefore already encodes the
       Sa-driven friction contribution implicitly.
    3. The empirical ×1.28 Nu multiplier (baked into tpms_calc air-
       Gyroid) was fit by comparing the same 试验记录表 Nu measurements
       to the smooth-wall Nu correlation; it lives only on the Q side.
    4. Applying *any* additional f-side multiplier therefore double-
       counts the SLM roughness on friction. `norris_1a` previously
       did this in two flavours (1.46 from Norris analogy, then 1.28
       paired with Nu); both were physically wrong and have been
       reverted to 1.0.

`norris_1a` is now a degenerate alias of `baseline` for friction.
The mode label is retained so existing config files / UI presets
keep parsing, but `f_enhancement('norris_1a') == 1.0`.

The remaining 3D Shanghai dP gap (≈ 47 % baseline RMSRE) is therefore
not a missing roughness multiplier — it is a closure gap from one or
more of:
    (a) t = 0.6 mm Shanghai geometry is *extrapolation* of the
        ConstDF-v1 training (t ∈ {0.3, 0.4, 0.5}). Closing it needs
        new smooth-wall CFD at t ≥ 0.55.
    (b) Shanghai prototype Sa may differ from 试验记录表 Sa = 31 μm.
        Closing it needs an independent Sa measurement plus a TPMS-
        fit rough-wall correlation.

══════════════════════════════════════════════════════════════════════════

Three modes:

  ``baseline``       no f-side correction; air Nu stays ×1.28 (production default).

  ``norris_1a``      equivalent to `baseline` for friction (multiplier = 1.0).
                     Retained as an alias so older configs don't break.
                     ⚠ Historical: earlier revisions applied f × 1.46 then
                     f × 1.28; both were reverted on 2026-05-14 because the
                     SLM dP used to train c_F already encodes Sa-driven
                     friction → any extra multiplier double-counts roughness.

  ``bhatti_shah_1b`` Re-dependent g(Re, ε/D_h) for BOTH f and Nu via Haaland
                    explicit Colebrook-White friction:
                        f_r/f_sm = f_haaland(Re, ε/D_h) / f_petukhov(Re)
                        Nu_r/Nu_sm = (f_r/f_sm)^0.68               (Norris)
                    Air Nu becomes Re-dependent (overrides ×1.28).
                    Single hyperparameter: ε (literature AM SLM value 50-200 μm).
                    No Shanghai fitting.

References
----------
- Bhatti & Shah 1987, Ch.4 in Kakac, Shah, Aung (eds), Handbook of Single-Phase
  Convective Heat Transfer (Wiley) — Re-dep roughness HT enhancement review.
- Norris 1971, "Some simple approximate heat-transfer correlations for
  turbulent flow in ducts with rough surfaces", ASME — n=0.68 exponent.
- Haaland 1983, "Simple and explicit formulas for the friction factor in
  turbulent pipe flow", J. Fluids Eng. — explicit Colebrook-White approx.
- Petukhov 1970, smooth-wall pipe friction.

Water-side Nu (Yan [6] 2024) ALREADY embeds AM surface roughness; do not
apply this module to water flow.
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
        # 2026-05-14 (2nd revision): friction multiplier set to 1.0
        # (no f-side enhancement). The 试验记录表 SLM dP used to
        # train ConstDF-v1 cF was already real experimental dP, so
        # cF already encodes the Sa-driven friction. Applying any
        # additional ×factor (the old 1.46 from Norris analogy or
        # the intermediate 1.28 from Nu-symmetric pairing) double-
        # counts the roughness on the f side. The ×1.28 stays only
        # on the Nu side (baked into tpms_compute air-Gyroid), which
        # is an empirical Shanghai-vs-Nu_smooth fit on the Q side.
        # `norris_1a` thus degenerates to identical behaviour with
        # `baseline` for friction; the mode label is retained for
        # backward compatibility with config files.
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

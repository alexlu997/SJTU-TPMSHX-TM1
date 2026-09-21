"""Historical water Nu comparisons; not selected by the production registry.

The formulas and original provenance are retained for the existing comparison
checks. Historical applicability statements below are not current acceptance.
"""
from sjtu_tpmshx.models.nu_correlations import nu_from_Re, Pr_AIR


def nu_water_gyroid_yan6(Re, Pr):
    """Water-side Nusselt number for Gyroid TPMS, Yan et al 2024 [6].

        Nu = 0.471 · Re^0.627 · Pr^(1/3)

    Source: K. Yan, H. Deng, Y. Xiao, J. Wang, Y. Luo,
    'Thermo-hydraulic performance evaluation through experiment and
    simulation of additive manufactured Gyroid-structured heat exchanger',
    Appl. Therm. Eng. 241 (2024) 122402.
    doi:10.1016/j.applthermaleng.2024.122402

    Validated range: 150 < Re < 3000 (water, AM Gyroid).

    Convention:
      Re = ρ·u·D_h / μ        (single-stream, D_h = 4·ε_A/A_0)
      Nu = h_sf · D_h / k_f   (face heat-transfer coefficient h_sf)
      Pr = μ·c_p / k_f

    Notes:
      * Experiment + CFD double-fit on AM gyroid sample (cell 20 mm).
      * Surface roughness from AM is naturally embedded; do not apply
        an extra ×1.28 roughness factor on top.
      * Project Shanghai cases 3-16 (Re 173-1146) fall in-range.
      * Cases 1-2 (Re 54, 108) extrapolate to lower Re, ≈ -9 % on Nu
        relative to Yan [58] in-range; acceptable since h_vB dominates U.
    """
    return 0.471 * Re ** 0.627 * Pr ** (1.0 / 3.0)


def nu_water_from_Re(tpms_type, Re, eps_f, L_mm, D_h_mm, Pr_water):
    """Water-side Nu via Pr-substitution onto the air-fit correlation
    (Reynolds analogy, Dittus-Boelter / Sieder-Tate basis).

    Legacy / cross-check only — NOT the production water path. Production
    water Nu now uses ``nu_water_topo`` (per-topology direct water-CFD fit,
    ``WATER_NU_COEFFS``). This function and ``nu_water_gyroid_yan6`` (Yan
    [6] 2024) are retained for cross-check / test only.
    """
    return nu_from_Re(tpms_type, Re, eps_f, L_mm, D_h_mm) \
           * (Pr_water / Pr_AIR) ** (1/3)

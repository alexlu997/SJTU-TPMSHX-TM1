"""流体分派 (design 工具薄适配层, B1 1.1 单源化后)。

物性原语与水侧拓扑专属 Nu 系数现单源于 models 层
(``models.fluid_props`` 注册表 + ``models.nu_correlations``);
本模块提供 design 工具的便捷接口，不重复定义物性数据。
"""
from __future__ import annotations
from sjtu_tpmshx.run_control.run_warnings import range_context

from sjtu_tpmshx.physical_models import fluid_props as _registry
from sjtu_tpmshx.physical_models.fluid_props import Props as Props
from sjtu_tpmshx.cpp_interface import _native_properties
from sjtu_tpmshx.physical_models.tpms_calc import nu_from_Re, nu_re_window as nu_re_window
from sjtu_tpmshx.physical_models.nu_correlations import (
    DESIGN_NU_REFERENCE_STATES as DESIGN_NU_REFERENCE_STATES,
    NU_RE_FIT_RANGE as NU_RE_FIT_RANGE,
    WATER_NU_RE_RANGE as WATER_NU_RE_RANGE,
    SCO2_NU_RE_RANGE as SCO2_NU_RE_RANGE,
    nu_water_topo,
    nu_sco2_topo,
    _warn_extrap, _warn_water_nu, _warn_sco2_nu, record_quick_sco2_pr_notice,
)
from sjtu_tpmshx.physical_models.tpms_props import record_temperature_ranges

def record_native_design_ranges(fluid, topo, temperature, reynolds):
    """Map returned native pass evidence through existing warning owners, without EOS calls."""
    record_temperature_ranges(fluid, temperature, source='property')
    if fluid in DESIGN_NU_REFERENCE_STATES:
        with range_context(stage='design-nu-representative-pr', layout='scalar'):
            record_temperature_ranges(fluid, DESIGN_NU_REFERENCE_STATES[fluid][0], source='property')
    if fluid == 'air':
        _warn_extrap(topo, reynolds, reynolds, reynolds)
    elif fluid == 'water':
        _warn_water_nu(max(reynolds, 1.), max(reynolds, 1.), topo, reynolds)
    elif fluid == 'sco2':
        record_quick_sco2_pr_notice()
        _warn_sco2_nu(max(reynolds, 1.), max(reynolds, 1.), topo, reynolds)
    else:
        raise ValueError(f'unknown fluid {fluid!r}')


def fluid_props(fluid: str, T_K: float, P_Pa: float) -> Props:
    # Absolute pressure enters air density and sCO2 properties. Current water
    # property primitives and the other air correlations depend on T only.
    m = _registry.get(fluid)            # raises ValueError on unknown
    _registry.check_water_state(m.name, T_K, P_Pa, where='quick-design properties')
    rho = m.rho(T_K, P_Pa); mu = m.mu(T_K, P_Pa)
    k = m.k(T_K, P_Pa); cp = m.cp(T_K, P_Pa)
    return Props(rho, mu, k, cp, _native_properties.prandtl(mu, cp, k))


def fluid_nu(fluid: str, topo: str, Re: float, eps_f: float,
             L_mm: float, D_h_mm: float) -> float:
    """单股 Nu。air: 项目幂律×f_rough; water: 拓扑专属 c·Re^a·Pr^(1/3);
    water 的 Pr 固定取 320 K / 0.2 MPa，const/mean 均如此；不是各工况物性态的 Pr。
    sco2: nu_sco2_topo (光滑壁 CFD, c·Re^a·Pr^⅓·(Dh/L)^d, Diamond+Gyroid).
    ⚠ design 工具是 plug LTNE，对 sco2 变-cp/近临界本就粗糙——sco2 正式定尺
    的旧焓基工程见 docs/history/retired-tools.md。此处 Pr 取代表性远离临界态。
    ⚠ sco2 为光滑壁值（粗糙度未标定, 2026-07-15）。"""
    if fluid == "air":
        return nu_from_Re(topo, Re, eps_f, L_mm, D_h_mm)
    if fluid == "water":
        with range_context(stage='design-nu-representative-pr', layout='scalar'):
            Pr_w = fluid_props("water", *DESIGN_NU_REFERENCE_STATES['water']).Pr
        return nu_water_topo(topo, Re, Pr_w)
    if fluid == "sco2":
        # representative far-from-critical sCO2 (D-7-6 mid ~480K/9MPa)
        with range_context(stage='design-nu-representative-pr', layout='scalar'):
            Pr_s = fluid_props("sco2", *DESIGN_NU_REFERENCE_STATES['sco2']).Pr
        record_quick_sco2_pr_notice()
        return nu_sco2_topo(topo, Re, Pr_s, L_mm, D_h_mm)
    raise ValueError(f"unknown fluid {fluid!r}")

"""流体分派 (design 工具薄适配层, B1 1.1 单源化后)。

物性原语与水侧拓扑专属 Nu 系数现单源于 models 层
(``models.fluid_props`` 注册表 + ``models.nu_correlations``);
本模块提供 design 工具的便捷接口，不重复定义物性数据。
"""
from __future__ import annotations
from dataclasses import dataclass
from sjtu_tpmshx.domain.run_warnings import range_context, record_warning

from sjtu_tpmshx.models import fluid_props as _registry
from sjtu_tpmshx.models.tpms_calc import nu_from_Re
from sjtu_tpmshx.models.nu_correlations import (
    NU_RE_FIT_RANGE,        # air 幂律拟合 Re 窗 (400,16000)
    WATER_NU_RE_RANGE,      # 拓扑专属水侧 Nu 关联式验证 Re 域 (新式)
    SCO2_NU_RE_RANGE,       # sCO2 CFD 拟合 Re 域 (2600,128000), Diamond+Gyroid
    nu_water_topo,
    nu_sco2_topo,
)


def nu_re_window(fluid: str):
    """该流体 Nu 关联式的验证 Re 域 (lo, hi)。域外 = 外推, 低置信。
    air → 项目幂律拟合窗 (400,16000); water → 拓扑专属 (90,51000);
    sco2 → 光滑壁单胞 CFD 拟合 (2600,128000), Diamond+Gyroid
    (2026-07-15, 局部体物性 Re_b 覆盖; 失效带见 nu_correlations)。"""
    if fluid == "water":
        return WATER_NU_RE_RANGE
    if fluid == "sco2":
        return SCO2_NU_RE_RANGE
    return NU_RE_FIT_RANGE


@dataclass
class Props:
    rho: float; mu: float; k: float; cp: float; Pr: float


def fluid_props(fluid: str, T_K: float, P_Pa: float) -> Props:
    # Absolute pressure enters air density and sCO2 properties. Current water
    # property primitives and the other air correlations depend on T only.
    m = _registry.get(fluid)            # raises ValueError on unknown
    rho = m.rho(T_K, P_Pa); mu = m.mu(T_K, P_Pa)
    k = m.k(T_K, P_Pa); cp = m.cp(T_K, P_Pa)
    return Props(rho, mu, k, cp, mu * cp / k)


def fluid_nu(fluid: str, topo: str, Re: float, eps_f: float,
             L_mm: float, D_h_mm: float) -> float:
    """单股 Nu。air: 项目幂律×f_rough; water: 拓扑专属 c·Re^a·Pr^(1/3);
    sco2: nu_sco2_topo (光滑壁 CFD, c·Re^a·Pr^⅓·(Dh/L)^d, Diamond+Gyroid).
    ⚠ design 工具是 plug LTNE，对 sco2 变-cp/近临界本就粗糙——sco2 正式定尺
    的旧焓基工程见 docs/history/retired-tools.md。此处 Pr 取代表性远离临界态。
    ⚠ sco2 为光滑壁值（粗糙度未标定, 2026-07-15）。"""
    if fluid == "air":
        return nu_from_Re(topo, Re, eps_f, L_mm, D_h_mm)
    if fluid == "water":
        with range_context(stage='design-nu-representative-pr', layout='scalar'):
            Pr_w = fluid_props("water", 320.0, 2e5).Pr
        return nu_water_topo(topo, Re, Pr_w)
    if fluid == "sco2":
        # representative far-from-critical sCO2 (D-7-6 mid ~480K/9MPa)
        with range_context(stage='design-nu-representative-pr', layout='scalar'):
            Pr_s = fluid_props("sco2", 480.0, 9.0e6).Pr
        record_warning(('design-sco2-representative-pr',),
                       'sCO2 Nu uses representative Pr queried at 480 K / 9 MPa, '
                       'not at this case inlet or mean state. The smooth-wall CFD '
                       'correlation joint qualification for this case is not established.')
        return nu_sco2_topo(topo, Re, Pr_s, L_mm, D_h_mm)
    raise ValueError(f"unknown fluid {fluid!r}")

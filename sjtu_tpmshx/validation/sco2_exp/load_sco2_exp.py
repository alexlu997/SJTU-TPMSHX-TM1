"""load_sco2_exp.py — sCO2 换热器实验数据入库（D-7-6 / G-7-6, 2026-07）.

数据源: data/raw_data/experiments/sco2/sco2_DG7-t0p6_hx_experiment_summary.xlsx
    实验数据处理-Diamond  51 工况（无差压计列）
    实验数据处理-Gyroid   44 工况（两侧测试块各多一列"差压计 MPa", 布局 +2 偏移
                          —— 两表列映射独立硬编码, 加表头断言守卫, 勿合并）

实验: sCO2–sCO2 逆流, 高温回路 ~9 MPa (入口 ~130°C) × 低温回路 ~10 MPa
(入口 ~100°C), 流量 180–720 kg/h 扫掠; 几何均为 7 mm / 0.6 mm。

约化口径（全部从原始测量列自算, 不信任表内已算的 Re/Pr/Nu/f 列——
其 f 口径与 repo 不一致, 差数倍）:
    压力        本批原 Pin/Pout 为表压 MPa，绝压 = 表压*1e6+101325 Pa
    焓/Q        CoolProp @ 各实测端点(T, P_abs)，保留旧 REFPROP 缓存
    物性        CoolProp @ (T̄, P̄_abs)（该侧进出口均温均绝压）
    Dh          tpms_calc 体素口径（与 CFD 关联式/求解器同源;
                表内特征长度另存 Dh_sheet_m 供对照）
    u           间隙流速 = ṁ / (ρ̄ · A_flow)（A_flow = 表内硬件流通面积）
    Re          ρ̄·u·Dh/μ̄
    f (Darcy)   ΔP·Dh / (L·ρ̄·u²/2)
    壁温        T_w = (T̄_hot + T̄_cold)/2（与 D-7-6 历史分析同款构造 ——
                Nu ∝ 1/ΔT_streams, ΔT 小时爆伪影, 拟合前须过滤）
    h           Q_side / (A_heat · |T̄_side − T_w|),  Nu = h·Dh/k̄

加载先按 mdot、Tin_C、Tout_C、Q_kW、dP_MPa 关键列执行 dropna。
对完成前置清洗的行只添加以下质量旗标，不再据旗标删行；下游按用途选：
    ok_dp   ΔP > 0（负压差 = 坏点, 用户裁决 2026-07-15 剔除）
    ok_dT   ΔT_streams = |T̄_h − T̄_c| > 10 K（Nu 构造伪影阈, 历史惯例）
    ok_hb   |热平衡| ≤ 0.15
    ok_done 完成情况列非 作废/重做（含“需重做”）
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_PKG_ROOT = _THIS.parent.parent.parent          # .../sjtu_tpmshx
from sjtu_tpmshx.models.tpms_props import (  # noqa: E402
    P_atm, geometry as tpms_geometry)
from sjtu_tpmshx.logutil import get_logger  # noqa: E402

_log = get_logger(__name__)

XLSX = _PKG_ROOT.parent / "data" / "raw_data" / 'experiments/sco2/sco2_DG7-t0p6_hx_experiment_summary.xlsx'
REFERENCE_VERSION = "coolprop-heos-gauge-101325-v1"

# 每表独立列映射（0-based）。header 断言字串取自 row3（含换行已压平）。
_MAPS = {
    "Diamond": dict(
        sheet="实验数据处理-Diamond",
        geo_row=4, L_ch=14, Dh_sheet=15, A_flow=16, A_heat=17,
        done=12,
        hot=dict(mdot=18, Tin=19, Pin=20, Tout=21, Pout=22,
                 hin=28, hout=29, Q=30, dP=31),
        cold=dict(mdot=23, Tin=24, Pin=25, Tout=26, Pout=27,
                  hin=32, hout=33, Q=34, dP=35),
        hb=36,
        guards={18: "质量流量", 30: "换热量", 31: "压差", 35: "压差",
                36: "热平衡"},
    ),
    "Gyroid": dict(
        sheet="实验数据处理-Gyroid",
        geo_row=4, L_ch=14, Dh_sheet=15, A_flow=16, A_heat=17,
        done=12,
        # 两侧测试块各多一列 差压计 MPa（21 / 27）, 其后 +2 偏移
        hot=dict(mdot=18, Tin=19, Pin=20, Tout=22, Pout=23,
                 hin=30, hout=31, Q=32, dP=33,
                 dP_gauge=21),
        cold=dict(mdot=24, Tin=25, Pin=26, Tout=28, Pout=29,
                  hin=34, hout=35, Q=36, dP=37,
                  dP_gauge=27),
        hb=38,
        guards={18: "质量流量", 21: "差压计", 32: "换热量", 33: "压差",
                37: "压差", 38: "热平衡"},
    ),
}

_DT_MIN_K = 10.0        # Nu 伪影过滤阈（历史 D-7-6 惯例）
_HB_MAX = 0.15
_K_S_DEFAULT = 16.0


def _check_guards(df: pd.DataFrame, mp: dict, topo: str) -> None:
    for col, key in mp["guards"].items():
        h = str(df.iloc[3, col]).replace("\n", "")
        if key not in h:
            raise ValueError(
                f"[{topo}] 列守卫失败: col {col} 表头为 {h!r}, 预期含 {key!r}"
                f" —— 表布局变了, 更新 _MAPS 后再跑。")


def load_exp(topo: str = "Diamond") -> pd.DataFrame:
    """One row per measured side; raw gauge/cached fields remain unchanged.

    Q_kW/HB and reduced properties use the corrected absolute pressure.
    The source's Q/HB and REFPROP enthalpies remain in *_cached columns.
    This conversion belongs only to this experiment, not generic fluid inputs.
    """
    from CoolProp import AbstractState, __version__
    from CoolProp.CoolProp import PropsSI

    mp = _MAPS[topo]
    raw = pd.read_excel(XLSX, sheet_name=mp["sheet"], header=None,
                        engine="openpyxl")
    _check_guards(raw, mp, topo)

    g = raw.iloc[mp["geo_row"]]
    L_ch = float(g[mp["L_ch"]])
    Dh_sheet = float(g[mp["Dh_sheet"]])
    A_flow = float(g[mp["A_flow"]])
    A_heat = float(g[mp["A_heat"]])
    geo = tpms_geometry(topo, 7.0, 0.6, _K_S_DEFAULT)
    Dh = float(geo["D_h"])                      # repo 体素口径

    d = raw.iloc[mp["geo_row"]:].reset_index(drop=True)
    done = d[mp["done"]].astype(str).str.strip()

    def side_frame(side: str) -> pd.DataFrame:
        c = mp[side]
        out = pd.DataFrame({
            "case": np.arange(1, len(d) + 1),
            "topo": topo, "side": side,
            "mdot": pd.to_numeric(d[c["mdot"]], errors="coerce"),
            "Tin_C": pd.to_numeric(d[c["Tin"]], errors="coerce"),
            "Pin_MPa": pd.to_numeric(d[c["Pin"]], errors="coerce"),
            "Tout_C": pd.to_numeric(d[c["Tout"]], errors="coerce"),
            "Pout_MPa": pd.to_numeric(d[c["Pout"]], errors="coerce"),
            "hin_cached_kJ_kg": pd.to_numeric(d[c["hin"]], errors="coerce"),
            "hout_cached_kJ_kg": pd.to_numeric(d[c["hout"]], errors="coerce"),
            "Q_cached_kW": pd.to_numeric(d[c["Q"]], errors="coerce"),
            "dP_MPa": pd.to_numeric(d[c["dP"]], errors="coerce"),
            "HB_cached": pd.to_numeric(d[mp["hb"]], errors="coerce"),
            "done": done,
        })
        if "dP_gauge" in c:
            out["dP_gauge_MPa"] = pd.to_numeric(d[c["dP_gauge"]],
                                                errors="coerce")
        return out

    hot, cold = side_frame("hot"), side_frame("cold")
    # 壁温构造需要对侧均温 → 先算两侧均温再并
    for s in (hot, cold):
        s["T_mean_K"] = (s["Tin_C"] + s["Tout_C"]) / 2 + 273.15
        s["Pin_abs_Pa"] = s["Pin_MPa"] * 1e6 + P_atm
        s["Pout_abs_Pa"] = s["Pout_MPa"] * 1e6 + P_atm
        s["P_mean_Pa"] = (s["Pin_abs_Pa"] + s["Pout_abs_Pa"]) / 2
        for endpoint in ("in", "out"):
            s[f"h{endpoint}_J_kg"] = PropsSI(
                "H", "T", s[f"T{endpoint}_C"].to_numpy() + 273.15,
                "P", s[f"P{endpoint}_abs_Pa"].to_numpy(), "CO2")
    hot["Q_kW"] = hot["mdot"] * (hot["hin_J_kg"] - hot["hout_J_kg"]) / 1e3
    cold["Q_kW"] = cold["mdot"] * (cold["hout_J_kg"] - cold["hin_J_kg"]) / 1e3
    hot["HB"] = cold["HB"] = (cold["Q_kW"] - hot["Q_kW"]) / hot["Q_kW"]
    hot["T_other_K"], cold["T_other_K"] = (cold["T_mean_K"].values,
                                           hot["T_mean_K"].values)
    df = pd.concat([hot, cold], ignore_index=True)
    df = df.dropna(subset=["mdot", "Tin_C", "Tout_C", "Q_kW", "dP_MPa"])
    df = df.reset_index(drop=True)

    T, P = df["T_mean_K"].to_numpy(), df["P_mean_Pa"].to_numpy()
    df["rho"] = PropsSI("D", "T", T, "P", P, "CO2")
    df["mu"] = PropsSI("V", "T", T, "P", P, "CO2")
    df["cp"] = PropsSI("C", "T", T, "P", P, "CO2")
    df["k"] = PropsSI("L", "T", T, "P", P, "CO2")
    df["Pr"] = df["mu"] * df["cp"] / df["k"]

    df["u"] = df["mdot"] / (df["rho"] * A_flow)
    df["Re"] = df["rho"] * df["u"] * Dh / df["mu"]
    df["f"] = (df["dP_MPa"] * 1e6) * Dh / (L_ch * 0.5 * df["rho"]
                                           * df["u"] ** 2)
    df["T_wall_K"] = 0.5 * (df["T_mean_K"] + df["T_other_K"])
    df["dT_streams_K"] = (df["T_mean_K"] - df["T_other_K"]).abs()
    dT_wall = (df["T_mean_K"] - df["T_wall_K"]).abs()      # = ΔT_streams/2
    df["h"] = df["Q_kW"].abs() * 1e3 / (A_heat * dT_wall)
    df["Nu"] = df["h"] * Dh / df["k"]

    df["ok_dp"] = df["dP_MPa"] > 0
    df["ok_dT"] = df["dT_streams_K"] > _DT_MIN_K
    df["ok_hb"] = df["HB"].abs() <= _HB_MAX
    df["ok_hb_cached"] = df["HB_cached"].abs() <= _HB_MAX
    df["ok_heat_flow"] = np.isfinite(df["Q_kW"]) & (df["Q_kW"] > 0)
    df["ok_done"] = ~df["done"].str.contains("作废|重做", na=False)

    df.attrs.update(dict(L_ch_m=L_ch, Dh_m=Dh, Dh_sheet_m=Dh_sheet,
                         A_flow_m2=A_flow, A_heat_m2=A_heat))
    df.attrs["reference"] = {
        "version": REFERENCE_VERSION,
        "source": str(XLSX), "sheet": mp["sheet"],
        "CoolProp_version": __version__,
        "backend": AbstractState("HEOS", "CO2").backend_name(),
        "fluid": "CO2", "REFPROP_cached_version": "unknown",
        "pressure": "Pin_MPa/Pout_MPa are measured gauge; *_abs_Pa = gauge*1e6+101325",
        "atmospheric_pressure_Pa": P_atm,
        "enthalpy": "measured endpoint T [K], absolute P [Pa] -> h [J/kg]",
        "Q": "hot mdot*(hin-hout), cold mdot*(hout-hin); mdot kg/s, Q_kW kW",
        "HB": "(Qcold-Qhot)/Qhot; abs(HB)<=0.15",
        "scope": "CoolProp derived reference; no solver outputs or EOS-independent validation",
    }
    _log.info(
        f"load_exp[{topo}]: {len(df)} 行 ({df['case'].nunique()} 工况×2 侧), "
        f"Dh repo {Dh*1e3:.3f} mm vs 表内 {Dh_sheet*1e3:.3f} mm; "
        f"过滤旗标 dp/dT/hb/done 通过率 "
        f"{df['ok_dp'].mean():.0%}/{df['ok_dT'].mean():.0%}/"
        f"{df['ok_hb'].mean():.0%}/{df['ok_done'].mean():.0%}")
    return df


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    for topo in ("Diamond", "Gyroid"):
        df = load_exp(topo)
        ok = df[df.ok_dp & df.ok_dT & df.ok_hb & df.ok_done]
        print(f"[{topo}] 全 {len(df)} 行 → 全过滤后 {len(ok)} 行")
        print(ok.groupby("side")[["Re", "Pr", "Nu", "f", "dT_streams_K"]]
              .agg(["min", "median", "max"]).round(3).to_string())
        print()

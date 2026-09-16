"""Shared readers and campaign conventions for the 7/0.6 water-air HX data.

No fitting or surrogate model is imported here. Raw columns, row-quality flags,
and the reviewed campaign area, length and reference Re convention are retained.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from sjtu_tpmshx.validation.water_exp import with_water_absolute_pressures
from sjtu_tpmshx.models.tpms_props import air_viscosity as air_mu  # noqa: F401 - shared HX property re-export
from sjtu_tpmshx.logutil import get_logger

_log = get_logger(__name__)
_REPO = Path(__file__).resolve().parents[2]

R_AIR = 287.05
P_ATM = 101325.0
L_FLOW = 0.182                    # 流道长度 m（D-7-6 工作簿 B 列，7-6 同芯）
# 整机每侧流通面积 = ε_side × 迎风面积（42×42mm=1.764e-3 m²）——三方自洽：
#   Diamond 5.94e-4（D-7-6 工作簿 D 列实测值；0.3373×1.764e-3=5.95e-4 ✓）
#   Gyroid  6.50e-4（G 表 密度/速度 列反推恒定值；0.3684×1.764e-3=6.50e-4 ✓）
# 首版曾给 G 误用 D 值（差 ×1.094 ⇒ Forchheimer 项 ×1.20），已纠。
A_FLOW = {"Diamond": 5.94e-4, "Gyroid": 6.50e-4}

AIR_BOOKS = {
    "Diamond": ('experiments/water_air/water-air_D7-t0p6_experiment_water-straight_20260609.xlsx', "Sheet1"),
    "Gyroid": ('experiments/water_air/water-air_G7-t0p6_shanghai_experiment_20260401.xlsx',
               "Sheet1"),
}
_AIR_NEED = ["样机空气流量kg/s", "空气进口温度/℃", "空气出口温度/℃",
             "空气进口压力/Pa", "空气出口压力/Pa"]

# Retain the original low-dP membership rule. It excludes case 1 in both
# Shanghai campaigns, including April 1 (1149 Pa); it is not a verified
# instrument-accuracy limit. Excluded rows remain available for full reporting.
DP_FLOOR_PA = 2000.0


def load_air_cases(topo: str, *, source: tuple[str, str] | None = None) -> pd.DataFrame:
    """Read the active calibration, or an explicit source for historical comparison."""
    book, sheet = AIR_BOOKS[topo] if source is None else source
    d = pd.read_excel(_REPO / "data" / "raw_data" / book,
                      sheet_name=sheet, header=1)
    missing = [c for c in _AIR_NEED if c not in d.columns]
    if missing:
        raise RuntimeError(f"{topo}: 列缺失 {missing} —— 表版式变了，重核列图")
    d["excel_row"] = d.index + 3  # Header is Excel row 2.
    d = d[d.iloc[:, 0].astype(str).str.startswith("工况")].copy()
    d = d.dropna(subset=_AIR_NEED)
    d = d[(d["样机空气流量kg/s"] > 0)
          & (d["空气进口压力/Pa"] > d["空气出口压力/Pa"])]
    d = d.reset_index(drop=True)
    d["case"] = d.iloc[:, 0].astype(str)
    dp = d["空气进口压力/Pa"] - d["空气出口压力/Pa"]
    # The existing low-dP fit exclusion does not suppress the reporting row.
    d["dp_floor"] = dp < DP_FLOOR_PA
    # D_7_6 air cases 10/11 duplicate temperatures and pressures at different
    # mass flows, as do the matching water rows; retain their quality flag.
    key = ["空气进口温度/℃", "空气出口温度/℃",
           "空气进口压力/Pa", "空气出口压力/Pa"]
    d["dup_row"] = d.duplicated(subset=key, keep=False)
    d["excluded"] = d.dp_floor | d.dup_row
    d.attrs.update(source=book, sheet=sheet)
    return d


WATER_BOOK = _REPO / "data" / "raw_data" / 'experiments/water_air/water-air_DG7-t0p6_hx_water-dp_with-air-temperature.xlsx'

# 表头行号逐 sheet 不同：G_7_6 首行是标题带（"水侧进口温度150℃"），
# D_7_6 首行即列名。写死并在 load_water_cases 里校验列名，版式变了立刻炸。
WATER_SHEETS = {"Diamond": ("D_7_6", 0), "Gyroid": ("G_7_6", 1)}
_WATER_NEED = ["样机水流量kg/s", "水进口温度/℃", "水出口温度/℃",
               "水进口压力/Pa", "水出口压力/Pa", "水侧压差/Pa"]
# 保留两侧对照的参考长度 2.599 mm；这是实验报告口径，不参与生产几何计算。
DH_REF = 2.599e-3


def load_water_cases(topo: str) -> pd.DataFrame:
    sheet, header = WATER_SHEETS[topo]
    d = pd.read_excel(WATER_BOOK, sheet_name=sheet, header=header)
    missing = [c for c in _WATER_NEED if c not in d.columns]
    if missing:
        raise RuntimeError(f"{topo}: 列缺失 {missing} —— 表版式变了，重核列图")
    d = d[d.iloc[:, 0].astype(str).str.startswith("工况")].copy()
    d = d.dropna(subset=_WATER_NEED)
    d = d[d["样机水流量kg/s"] > 0].reset_index(drop=True)
    d["case"] = d.iloc[:, 0].astype(str)

    # 缺陷 1：负压差（传感器地板）
    d["dp_nonphysical"] = d["水侧压差/Pa"] <= 0.0
    # 缺陷 2：除 ṁ 外逐位重复的行（原始表复制粘贴）
    key = ["水进口温度/℃", "水出口温度/℃", "水进口压力/Pa",
           "水出口压力/Pa", "水侧压差/Pa"]
    d["dup_row"] = d.duplicated(subset=key, keep=False)
    # 一致性自检：压差列 == 进口 − 出口（表若改为独立差压计读数，这里会亮）
    resid = (d["水侧压差/Pa"]
             - (d["水进口压力/Pa"] - d["水出口压力/Pa"])).abs().max()
    if resid > 1e-6:
        _log.warning("%s: 压差列与进出口差不一致（max %.3g Pa）——口径变了，"
                     "核实哪一列是原始读数", topo, resid)
    return with_water_absolute_pressures(
        d, source=WATER_BOOK, sheet=sheet, tin="水进口温度/℃", tout="水出口温度/℃",
        pin="水进口压力/Pa", pout="水出口压力/Pa")

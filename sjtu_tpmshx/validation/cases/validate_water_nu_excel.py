"""Validate fixed water Nu against the retained CFD Excel, without refitting.

Use actual historical mass flow with current N=128 geometry. The reference is
mean(Core2_Nu, Core3_Nu), converted from the Excel Dh to the same current Dh.
This is an explicit legacy-workbook check, not a replacement for load_water's
missing corrected-upload source.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from sjtu_tpmshx.df_surrogate.load_water_cfd import (
    FLOW_SUSPECT, LATTICES)
from sjtu_tpmshx.df_surrogate.cfd_geometry import attach_geometry
from sjtu_tpmshx.models.nu_correlations import (
    WATER_NU_COEFFS, WATER_NU_RE_RANGE, nu_water_topo)

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "data/raw_data/cfd/water/water_DG_cfd_results_legacy.xlsx"
RMSRE_GATE = 0.10
BIAS_GATE = 0.05
EXPECTED_COUNTS = {"D": 940, "G": 939}
_NUMERIC = ["cell_size_mm", "wall_thickness_mm", "rho_kg_m3", "mu_Pa_s",
            "cp_J_kgK", "k_W_mK", "Dh_m", "mdot_in_kg_s", "Core2_Nu", "Core3_Nu"]


def evaluate(raw: pd.DataFrame) -> pd.DataFrame:
    """Keep every input row; invalid required data fail instead of being dropped."""
    missing = set(_NUMERIC + ["geometry_id", "lattice"]) - set(raw.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    numeric = raw[_NUMERIC].apply(pd.to_numeric, errors="coerce")
    bad = (~np.isfinite(numeric) | (numeric <= 0)).any(axis=1)
    if bad.any():
        raise ValueError(f"invalid required numeric data at rows {raw.index[bad].tolist()}")
    if raw.empty or not raw.lattice.isin(["D", "G"]).all():
        raise ValueError("expected nonempty D/G data in lattice column")
    raw = raw.copy()
    raw[_NUMERIC] = numeric
    raw["topology"] = raw.lattice.map({"D": "Diamond", "G": "Gyroid"})
    rows = []
    for topo, group in raw.groupby("topology", sort=False):
        d = attach_geometry(group, topo)  # current geometry, default N=128
        d = d.rename(columns={"Re": "Re_nominal"})
        d["u_current_m_s"] = (d.mdot_in_kg_s
                               / (d.rho_kg_m3 * d.eps_f * (d.L_mm * 1e-3) ** 2))
        d["Re_current"] = d.rho_kg_m3 * d.u_current_m_s * d.Dh_m / d.mu_Pa_s
        d["Pr_current"] = d.mu_Pa_s * d.cp_J_kgK / d.k_W_mK
        d["Nu_ref"] = (d.Core2_Nu + d.Core3_Nu) / 2 * d.Dh_m / d.Dh_cfd_m
        d["Nu_pred"] = nu_water_topo(topo, d.Re_current, d.Pr_current)
        d["relative_error"] = d.Nu_pred / d.Nu_ref - 1
        d["abs_relative_error"] = d.relative_error.abs()
        d["geometry_note"] = d.geometry_id.isin(FLOW_SUSPECT)
        d["outside_Re_range"] = ~d.Re_current.between(*WATER_NU_RE_RANGE)
        rows.append(d)
    return pd.concat(rows).sort_index()


def metrics(d: pd.DataFrame) -> dict:
    error = d.relative_error.to_numpy(float)
    return dict(n=len(d), geometries=int(d.geometry_id.nunique()),
                Re_min=float(d.Re_current.min()), Re_max=float(d.Re_current.max()),
                rmsre=float(np.sqrt(np.mean(error ** 2))), bias=float(error.mean()),
                mape=float(np.mean(np.abs(error))),
                p95_abs_error=float(np.quantile(np.abs(error), 0.95)),
                max_abs_error=float(np.max(np.abs(error))),
                outside_Re_range=int(d.outside_Re_range.sum()))


def accepted(score: dict) -> bool:
    return score["rmsre"] <= RMSRE_GATE and abs(score["bias"]) <= BIAS_GATE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--out", type=Path,
                        default=ROOT / ".cache/water-nu-validation-20260912")
    args = parser.parse_args(argv)
    sheets = pd.read_excel(args.source, sheet_name=None)
    raw = pd.concat([d.assign(source_sheet=name, source_excel_row=np.arange(len(d)) + 2)
                     for name, d in sheets.items()], ignore_index=True)
    if raw.lattice.value_counts().to_dict() != EXPECTED_COUNTS or raw.geometry_id.nunique() != 40:
        raise ValueError("workbook membership changed: expected 940 Diamond + 939 Gyroid, 40 geometries")
    if raw.W.isna().any() or raw.W.duplicated().any():
        raise ValueError("missing or duplicated W case IDs")
    d = evaluate(raw)
    topology = {tp: metrics(d[d.topology == tp]) for tp in LATTICES}
    for score in topology.values():
        score["passed"] = accepted(score)
    passed = all(s["passed"] for s in topology.values())
    summary = dict(source=str(args.source.resolve()), coefficients=WATER_NU_COEFFS,
                   rmsre_gate=RMSRE_GATE, abs_bias_gate=BIAS_GATE,
                   geometry_N=128, n_planned=1880, n_evaluated=len(d),
                   missing_case="W01600: closed as missing; no imputation",
                   topology=topology, all_rows=metrics(d), passed=passed,
                   native_exit=0 if passed else 2)
    geometry = pd.DataFrame([
        dict(geometry_id=gid, topology=g.topology.iloc[0],
             geometry_note=gid in FLOW_SUSPECT, **metrics(g))
        for gid, g in d.groupby("geometry_id")])
    d["Re_bin"] = pd.cut(d.Re_current, [0, 500, 1000, 3000, 10000, 30000, np.inf], right=False)
    bins = pd.DataFrame([dict(topology=tp, Re_bin=str(b), **metrics(g))
                         for (tp, b), g in d.groupby(["topology", "Re_bin"], observed=True)])
    args.out.mkdir(parents=True, exist_ok=True)
    for name, frame in (("rows", d), ("by_geometry", geometry), ("by_Re", bins),
                        ("worst_20", d.nlargest(20, "abs_relative_error"))):
        frame.to_csv(args.out / f"{name}.csv", index=False)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    lines = ["# 水 Nu 现存 Excel 验证", "", f"结果：{'通过' if passed else '未通过'}；原生退出码 {summary['native_exit']}。",
             "", "固定关联式；每个拓扑 RMSRE ≤ 10%，|平均有符号相对误差| ≤ 5%。",
             "全部 1879/1880 条实有记录、40 个几何进入统计；W01600 按缺测结案。",
             "采用实际历史质量流量、当前 N=128 孔隙率和 Dh、表内参考物性，重算速度和 Re。",
             "参考 Nu = mean(Core2_Nu, Core3_Nu) × Dh_current / Dh_excel。", "",
             "| 拓扑 | 条数 | RMSRE | 平均偏差 | 最大绝对相对误差 | 通过 |",
             "|---|---:|---:|---:|---:|---|"]
    for tp, s in topology.items():
        lines.append(f"| {tp} | {s['n']} | {s['rmsre']:.4%} | {s['bias']:+.4%} | {s['max_abs_error']:.2%} | {s['passed']} |")
    lines += ["", "## Re 分段（使用重算后的实际 Re）", "",
              "| 拓扑 | Re 段 | 条数 | RMSRE | 平均偏差 |",
              "|---|---|---:|---:|---:|"]
    for _, s in bins.iterrows():
        lines.append(f"| {s.topology} | {s.Re_bin} | {s.n} | {s.rmsre:.2%} | {s.bias:+.2%} |")
    lines += ["", "## D_7_3 / D_7_4 / D_7_5（已包含在上述分母）", ""]
    for _, s in geometry[geometry.geometry_note].iterrows():
        lines.append(f"- {s.geometry_id}: n={s.n}, RMSRE {s.rmsre:.2%}, 平均偏差 {s.bias:+.2%}。")
    lines += ["", "逐行见 rows.csv，几何分组见 by_geometry.csv，Re 分段见 by_Re.csv，最差 20 行见 worst_20.csv。",
              "本报告检验现有关联式与现存数据的一致性，不构成独立实验验证或原 CFD 网格质量证明。",
              "未重新拟合，未改变生产系数、原始数据、成员或阈值。", ""]
    (args.out / "report.md").write_text("\n".join(lines))
    print(json.dumps(summary, indent=2))
    return summary["native_exit"]


if __name__ == "__main__":
    raise SystemExit(main())

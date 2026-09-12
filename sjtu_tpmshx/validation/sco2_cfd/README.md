# sco2_cfd — sCO2 单胞 CFD（双拓扑）：Nu 关联式构建 + D-F(cF) 标定

> 数据：`data/raw_data/cfd/sco2/{Diamond,Gyroid}/`（见该目录 README：
> Diamond 4000 + Gyroid 3000 例，光滑壁 RANS 无重力，Twall=Tref+50K，
> P∈{8,10,12,15} MPa 锚 T_pc(P)，每晶格计划 5400 例分批上传）。
> 加载统一走 `df_surrogate/load_sco2_cfd.py`（`lattice` 参数；重算 repo
> 口径 Dh/Re/Nu/f，压力映射带 CoolProp ρ 守卫）。台账条目：**SCO2-CFD**。

## 脚本

| 脚本 | 作用 | 输出 |
|---|---|---|
| `compare_smooth_df.py` | SmoothDF 跨流体检验 + 固定 K 逐几何重拟 B（双拓扑） | `reports/sco2_cfd/df_smoothdf_vs_sco2.csv` |
| `fit_nu_sco2.py` | Nu 关联式四变体逐拓扑拟合 + LOGO/压力留一验证 | `reports/sco2_cfd/nu_sco2_fit_coeffs.csv`, `nu_sco2_logo.csv` |
| `make_error_report.py` | 逐 case 误差 HTML 报告（parity/热图/明细表） | `reports/sco2_cfd/sco2_cfd_error_report.html` |

HTML 报告版式与公式渲染统一走 `validation/report_template.py`
（ivory/paper/clay 模板 + 原生 MathML 公式助手）；新报告脚本一律 import
该模块，公式禁止手搓 CSS 分式（规则与教训见其 docstring）。

## 结果快照（2026-07-15，Diamond 4000 + Gyroid 3000 例）

### D-F（详见 df_smoothdf_vs_sco2.csv）

| | Diamond | Gyroid |
|---|---|---|
| SmoothDF 直接预测 RMSRE/medAPE/中位偏置 | 15.1% / 11.8% / −4.2% | **7.9% / 5.2% / −2.0%** |
| 固定 K 逐几何重拟 B 后 RMSRE | 8.9% | 7.1% |
| B_sco2/B_smooth 中位 [范围] | 1.16 [0.91, 1.35] | **1.05 [1.01, 1.13]** |
| m（sCO2 池化 vs 水/air） | 0.181 vs 0.137 | 0.124 vs 0.106 |

- 两个拓扑都落在 SmoothDF 自报跨流体误差带（~19%）内——**光滑 D-F 面
  对 sCO2 可迁移；Gyroid 几乎无损**（重拟仅再降 0.8pp，无独立分层价值）。
- 固定 K 依据：本数据 Re≳2600，Darcy 份额 ≤4%，K 不可辨识（f=A/Re+B
  拟出的 A 吸收湍流斜率而非渗透率）。
- ⚠️ Diamond 的 B 比值模式与 CSV-Dh vs `tpms_calc`-Dh 出入（最大 12%，
  D_6_6/D_7_4/D_7_5）高度相关，而 Gyroid（Dh 出入小）B 比紧缩 ⇒
  Diamond 的"流体差异"大概率是 CFD 网格几何 vs 体素几何差异，
  归因待 D_7_6 到位后复核。
- f 对 27 个 (P,Tref) 物性态不敏感（均值比 1.000，个例散差 ±10–25%）。

### Nu（详见 nu_sco2_fit_coeffs.csv）

推荐形式 **V0b —— 纯体物性基形**（光滑壁，分段局部体物性，第 2/3 周期，
b 固定 1/3；**2026-07-15 用户裁决：弃用壁物性比项**——ΔT≡50K 使壁比指数
条件于该过热度、不具通用性，且求解器/设计工具用纯体物性形式更通用）：

    Diamond: Nu = 0.1667 · Re_b^0.7055 · Pr_b^(1/3) · (Dh/L)^(-0.4342)
    Gyroid : Nu = 0.1991 · Re_b^0.7195 · Pr_b^(1/3) · (Dh/L)^(-0.1090)

| V0b 指标 | Diamond | Gyroid |
|---|---|---|
| 全数据 RMSRE/medAPE | 19.1% / 9.5% | 19.1% / 8.2% |
| **P≥10 MPa 全温区（含近临界）** | **13.3% / 8.3%** | **10.6% / 7.1%** |
| 8 MPa（失效域，分域声明） | 32.0% / 19.4% | 35.2% / 19.4% |
| 远临界 | 9.6% / 6.3% | 7.5% / 5.4% |
| LOGO 中位 / 最差 | 18.5% / 24.3% (D_6_6) | 19.1% / 20.2% |
| 压力留一 (8/10/12→15 MPa) | 15.7% | 11.7% |

- **与带 μ_w/μ_b 的 V2 参考形式对比**（V2 系数保留在 CSV 里作参考）：
  P≥10 MPa 域两者相当；差距全部集中在 8 MPa 近临界（V0b 32–35% vs
  V2 ~25%——那里 V2 也失效）；远临界端 V0b 反而更准（μ 项曾把远端带偏）。
  弃 μ 项的实际代价 ≈ 零（在声明的有效域内）。
- 自由 Pr 指数两拓扑均 ≈0.38 ——**支持 1/3 惯例**。
- 可辨识性备注（留给后来者）：ΔT≡50K ⇒ log(k_w/k_b)、log(ρ_w/ρ_b) 与
  log(Pr_b) 相关 −1.00/−0.97，Jackson 型与 Pr 项不可分离；μ_w/μ_b
  （corr −0.69）是唯一有独立信息的壁比项。
- (Dh/L) 几何项：Diamond −0.43 显著，**Gyroid −0.11 近零**——与水侧 B1
  调研（Diamond 需要几何项、Gyroid 不需要）结论一致。
- 与产线实验拟合（`SCO2_NU_COEFFS` Diamond：0.28·Re^0.75·Pr^⅓，D-7-6
  粗糙件）重叠窗对照：Nu_exp/Nu_V0b 中位 **1.70** [1.52, 1.83]——量级与
  "SLM 粗糙度（空气侧 1.28）× D_7_6 几何外推 × 实验构造壁温口径"自洽。
  Gyroid 无实验拟合可对照。
- **有效域声明**（按 P × dT_pc 逐格 medAPE 核定）：
  **P ≥ 10 MPa 且 T_b ≥ T_pc − 2K：逐格 4–12%，可用**（含近临界与远临界）。
  两条失效带入产线时挂外推告警：① 8 MPa 近临界
  （T_b−T_pc ∈ [−2,+5]K，18–61%——物性梯度太陡，带 μ 比的 V2 也失效）；
  ② 类液侧 T_b ≤ T_pc−5K 随压力下降恶化（15/12/10 MPa 逐格
  12/14/27%——μ 项以前替这列兜底，弃 μ 后这里是唯一真让步）。

## 入产线（已完成，2026-07-15 用户裁决）

**V0b 关联式与 sCO2 CFD 的 cF 已是生产闭合**（用户决策：不加未标定的
粗糙度因子、直接覆写、退役 D-7-6 单几何实验拟合与 ×3.39）：

- Nu：`solvers/nu_correlations.py` `SCO2_NU_COEFFS`（双拓扑，含 (Dh/L)^d 项，
  `nu_sco2_topo(tpms, Re, Pr, L_mm, D_h_mm)` 新签名），Gyroid 同步解锁；
- cF：`df_surrogate/sco2_df.py`（预制表 `_prebuilt/sco2_df_coeffs.csv`，
  重建 `python -m df_surrogate.sco2_df`）；K 沿用生产 CFD-refit 面；
  管线经 `predict.sco2_cf_scale`（入口 Re 锚定）接入，`SCO2_CF_SCALE=3.39`
  退役（历史值留存于 projects/703-sCO2-D76 各脚本本地）；
- ⚠ **语义**：sCO2 的 Nu 与 Δp 输出均为**光滑壁估计**——D-7-6 实验表明
  真实 SLM 件 Δp ~3.4×、Nu ~1.7×（单几何证据）。实验数据到位标出 γ 前，
  不得用于选型定尺；D-7-6 实验 Gate（test_sco2_phase_a::test_gate_a）
  已挂起，重启触发 = γ 锚定完成。
- 后续联动：sCO2 近临界成为主力工况时触发台账 **SCO2-H**（焓模式转默认；
  注意 C11-L5：焓模式实体导热缺 χ_S，先修再切）。

## 续传数据后的重启清单（触发：新 CSV 上传）

- 重跑两脚本（加载守卫会自动拦截新压力档/新几何/错放文件夹的问题）。
- D_7_6 到位后：与 D-7-6 实验拟合做同几何直接对照（当前 1.55 比值
  含几何外推混杂）；顺带用 CFD 自己的 Dh 复核 Diamond B 比值的归因。
- Gyroid L=7 与 G_6_6 补全后：Gyroid 几何覆盖对齐 Diamond。
- 若有 ΔT≠50K 或冷却方向工况：解除壁比指数的 ΔT 条件化，
  重审 V2 vs Jackson 形式之争。
- 入口段异常（第 1 周期 Nu 低 13–17%，f 高 ~8%）当前按剔除处理，
  若续传含更长域算例可复核发展长度假设。

---
type: index
updated: 2026-04-15
---

# SJTU-TPMSHX reports — 索引

本索引沿用旧版项目的研究分类；文中的“当前 baseline”和精度结论属于
当时状态。当前默认模型见[架构说明](../docs/architecture.md)，TM1 实施与验收见
[Graph 状态](../docs/plans/three-module-graph/state/)。以下历史结论保留原状。旧模型和派生报告已归档，完整路径见
[历史模型索引](../docs/history/legacy-models.md)。

本目录按**工作话题**分组,不只是按日期排。所有报告文件名保留 `YYYY-MM-DD-` 日期前缀,
便于和 git 历史、devlog 对齐。

## 1. ConstDF-v1 代理模型（历史 baseline）

### 当时 baseline 的证据记录

| 文件 | 一句话结论 |
|---|---|
| [`2026-04-14-DF-re-independence-report.md`](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/constdf-v1/2026-04-14-DF-re-independence-report.md) | 24/24 几何通过 Pearson 残差-Re 检验 → 2 参数 D-F 在训练 Re 范围内**统计独立于 Re**,作为 ConstDF-v1 物理合法性的**论文级证据** |
| [`2026-04-14-DF-surrogate-loo-report.md`](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/constdf-v1/2026-04-14-DF-surrogate-loo-report.md) | ConstDF-v1 LOO 主结果:**Diamond 12.79% / Gyroid 16.95%**(由 `train_surrogate.py` 自动写入,跑训练即覆盖) |
| [`2026-04-15-DF-residual-structure-diagnostic.md`](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/constdf-v1/2026-04-15-DF-residual-structure-diagnostic.md) | 残差 vs Re 诊断:**U 形残差在 24 个几何上普遍存在**,谷底 Re ≈ 800-2000,论证 12-17% MAPE 是 2-term D-F 闭合形式的**结构下限**,不是模型容量问题 |

### 被否方案(负结果,作"为什么不选 X"的论据)

| 文件 | 被否原因 |
|---|---|
| [`2026-04-14-piedra-baseline.md`](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/constdf-v1/2026-04-14-piedra-baseline.md) | Piedra 4 参数幂律 LOO Diamond 33% / Gyroid 47%,远差于 3D MLP → 证明 $(L, t)$ 输入对代理有用,不只 $\varepsilon_f$ |
| [`2026-04-15-kim-k1-diagnostic.md`](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/constdf-v1/2026-04-15-kim-k1-diagnostic.md) | Kim 严格 $K_1$ 线性子集判据下,大多几何只剩 ≤ 2 个点,样本不够拟合 |
| [`2026-04-15-kim-adapted-diagnostic.md`](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/constdf-v1/2026-04-15-kim-adapted-diagnostic.md) | Kim 2-term 在低 Re 子集上的三种判据(固定 Re 阈、子集 MAPE、新点残差),没一个比全范围 $K_{Q1}$ 更好 |
| [`2026-04-15-kim-constrained-diagnostic.md`](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/constdf-v1/2026-04-15-kim-constrained-diagnostic.md) | Kim 固定 $c_F$、反推 $K_1$ 的方案,全范围 MAPE 比直接 $K_{Q1}$ **大** 0.3-8pp |

### baseline 一览

**ConstDF-v1** = 常系数 2 参数 Darcy-Forchheimer + 3 输入 $(L, t, \varepsilon_f)$ → $(K, c_F)$,
per-TPMS MLP ensemble(5×)。LOO ΔP MAPE **Diamond 12.79% / Gyroid 16.95%**。

代码在 `sjtu_tpmshx/df_fit/`,git baseline commit `ab7a39e`。方案详细论证和物理限制讨论
见 memory `project_thermonas_df_baseline.md`。

---

## 2. C-1 Shanghai 验证 + Re/Nu 约定修复

Shanghai 16-case 从"21.8% 高 Re Q 误差"的 C-1 遗留问题到"3.7% 已解决"的完整工作线。

| 文件 | 一句话结论 |
|---|---|
| [`2026-04-15-Re-Nu-convention-audit.md`](shanghai-validation/2026-04-15-Re-Nu-convention-audit.md) | Re/Nu 约定全链路审计(**上午**,第一轮):纯文档修正。发现 `_nu_diamond`/`_nu_gyroid` 的 docstring 写错了 $D_h$(应为 $r_h$),其他代码自洽。**数值零变化** |
| [`2026-04-15-shanghai-Q-calculation-flow.md`](shanghai-validation/2026-04-15-shanghai-Q-calculation-flow.md) | **⭐ Shanghai Q 验证完整计算流程**(Case 16 9 步每一步数值打出)+ 两次实质 bug 修复总结:(1) `rho_ref(P_atm)` → `rho_actual(P_in)`,(2) `r_h` → `D_h`。C-1 `max \|err_Q%\|` 从 **21.8% → 3.71%**(除 Case 12 异常)。**"C-1 高 Re 误差 = 热色散缺失"(Popov A1)假设被证否**,真正原因是 Re 约定 bug |

---

## 3. Scratch 探索(ConstDF-v1 之外的失败尝试)

[`scratch/`](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/d3ba040de0d43fce8e9b485396a5b660c2d87c5f/reports/scratch) 子目录下存了 **5 个** "绕开 ConstDF-v1 12-17% 下限"的实验记录——
全部不入主干但数值有参考价值,避免未来会话重跑。

- **EG-DIP Gompertz**(Singh 2026,2 个变体):filtered / fullL8
- **Direct-ΔP MLP**(Correa 2026,3 个变体):initial / regularized / wide

**最强的探索(Direct-ΔP wide)**:Diamond LOO **8.09%**,Gyroid LOO **9.17%**,**数值上打败 ConstDF-v1**。
但因失去物理可解释性、求解器集成难、外推风险未知,**选择保留 ConstDF-v1 作为 baseline**。
详情见 [`scratch/README.md`](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/d3ba040de0d43fce8e9b485396a5b660c2d87c5f/reports/scratch/README.md)。

---

## 4. SIMPLER 耦合实验(负结果)

[`simpler-coupling-2d/`](simpler-coupling-2d/) — pysimpler(Tao SIMPLER 蒸馏版)的算法移植实验,
openspec change `simpler-coupling-2d`。

| 文件 | 一句话结论 |
|---|---|
| [`CONCLUSIONS.md`](simpler-coupling-2d/CONCLUSIONS.md) | **SIMPLER 在 2D 生产求解器上是纯开销(0.5-0.6×)**:精确直接解 PP 的 SIMPLE 无压力外迭代瓶颈(质量残差 iter 1 即机器精度,收敛由 α_rho 密度松弛控制),Tao 的 3.3× 外迭代收益不可移植。`coupling='simpler'` 保留 experimental,不推广 3D |

后续 [`solver-efficiency-r1-r4/CONCLUSIONS.md`](solver-efficiency-r1-r4/CONCLUSIONS.md)(openspec `solver-efficiency-r1-r4`):**R1** 3D early-exit 判据回流 2D → golden 管线 47.6s→0.29s(164×,B 侧横流 10000 燃尽→26 iter),Shanghai 2D RMSRE 8.76% 复现;**R2** 密度更新零分配(bit-identical);**R3** 3D gate 剖析 → 求解器仅 3.2%,无行动;**R4** 3D 动量 SOU opt-in → DF 源主导下格式差 <0.01%,不扶正。附带发现:golden 3D 校验需 `PYTHONHASHSEED=0`。

---

## 相关产物(本目录外)

- **训练曲线 / LOO parity 图**:[`figs/df_fit/`](figs/df_fit/)
- **Shanghai 验证误差分析图**:[`figs/shanghai/shanghai_validation_post_fix.png`](figs/shanghai/shanghai_validation_post_fix.png)
- **模型 ckpt**:`../models/df_surrogate_{diamond,gyroid}.joblib`(gitignored,可重生)
- **原始 CFD 数据**:`../data/raw_data/`(gitignored)

## 缺失记录

- `2026-04-14-DF-vs-fRe-closure-experiment.md` — memory 引用过,全项目搜不到。可能从未
  写出或在 v2 实验过程中删掉。没法恢复(那段没进 git)

## 版本导航

对应的主 git commit(最新在上):
```
2dd4e7f fix(nu): use actual inlet pressure density and D_h for Re in tpms_compute
c01d45b docs(audit): Re/Nu convention audit + Nu docstring fix
a621755 feat(solver): add closure='df' path with ConstDF-v1 integration
568f834 diagnostic: ConstDF-v1 residual-vs-Re U-shape evidence
f9c3868 docs(reports): add README index and refresh v1 LOO report
ab7a39e baseline: ConstDF-v1 D-F surrogate (3D MLP ensemble)
```

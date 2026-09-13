# 历史模型退役与归档索引

2026-09-12 按用户确认退役已被现行模型替代的计算路线。
退役前的代码和系数固定在 [a82fc0a](https://github.com/alexlu997/SJTU-TPMSHX-TM1/commit/a82fc0a0ce71fd47333594fa053799ac8b263150)；
该提交已经包含新的数据路径和读取解耦，对应私有数据提交
`01b62ad09e487857b05b42c01c5c62288ebd0b4b`。

## 当前保留

- 联合水+sCO2 几何固定 K/cF：`full_core_3cell_fixed_v2.py` 及唯一现用预制表
  `cfd_full_core_3cell_fixed_v2.csv`；40 个节点、原系数及插值约定不变。
- 原水 Nu 关联式、sCO2 Nu 及其现用修正、实验 D-F 修正与适用范围不变。
- `load_data`、水/sCO2 CFD 读取器、`validation/hx_experiments.py`，
  现行 `fit_experimental_effective`、`cf_cross_fluid` 和 Nu 验证入口保留。
- `fit_nu_correction` 从旧 Nu/f 混合报告独立保留现用 sCO2 Nu 锚定复核；
  D/G 52/80 条 Nu 记录、原修正值和逐温度拟合逐值一致。
- B40、fixed-166、冻结物理参考和 Graph 验收留在原位；已结束的 M1/M2 试验见[退役工具索引](retired-tools.md)。
  `_data_df_projection_baseline.json` 保留原 γ 时代数字；当前投影检查改用
  可手算的几何场验证坐标、方向和非均匀重采样，不重写旧参考值。

## 已关闭的入口

`gamma_df`、`rbf` 不再注册，显式选择报错。旧 `sco2_cf_scale`、
RBF 残差/局部覆盖修正和 `preprocess.offline.publish_surrogate` 随专属模型退役。
旧环境开关 `TPMSHX_DF_OVERRIDES`、`TPMSHX_DF_RESIDUAL_CORR`、
`TPMSHX_SCO2_GAMMA_F` 不再参与计算。正式实验修正入口继续使用现行联合基线。

复现旧方法时使用上述完整历史提交和对应私有数据版本，不能将旧系数复制进当前
模型。旧 SmoothDF 所需的外部空气 CFD 工作簿、修订版水 CFD 等来源缺口仍以
原记录为准；代码保存不代表所有历史重建依赖都已找回。

## 移除的源码、测试和旧系数表（34 个路径）

| 原路径 | 固定历史入口 |
| --- | --- |
| `sjtu_tpmshx/df_surrogate/_prebuilt/Diamond_surrogate_ref.csv` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/df_surrogate/_prebuilt/Diamond_surrogate_ref.csv) |
| `sjtu_tpmshx/df_surrogate/_prebuilt/Gyroid_surrogate_ref.csv` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/df_surrogate/_prebuilt/Gyroid_surrogate_ref.csv) |
| `sjtu_tpmshx/df_surrogate/_prebuilt/df_cfd_coeffs.csv` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/df_surrogate/_prebuilt/df_cfd_coeffs.csv) |
| `sjtu_tpmshx/df_surrogate/_prebuilt/df_cfd_coeffs_dev.csv` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/df_surrogate/_prebuilt/df_cfd_coeffs_dev.csv) |
| `sjtu_tpmshx/df_surrogate/_prebuilt/sco2_df_coeffs.csv` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/df_surrogate/_prebuilt/sco2_df_coeffs.csv) |
| `sjtu_tpmshx/df_surrogate/_prebuilt/smooth_df_coeffs.csv` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/df_surrogate/_prebuilt/smooth_df_coeffs.csv) |
| `sjtu_tpmshx/df_surrogate/build_prebuilt_surrogate.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/df_surrogate/build_prebuilt_surrogate.py) |
| `sjtu_tpmshx/df_surrogate/gamma_df.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/df_surrogate/gamma_df.py) |
| `sjtu_tpmshx/df_surrogate/residual_correction.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/df_surrogate/residual_correction.py) |
| `sjtu_tpmshx/df_surrogate/sco2_df.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/df_surrogate/sco2_df.py) |
| `sjtu_tpmshx/df_surrogate/sco2_gamma_f.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/df_surrogate/sco2_gamma_f.py) |
| `sjtu_tpmshx/df_surrogate/smooth_df.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/df_surrogate/smooth_df.py) |
| `sjtu_tpmshx/df_surrogate/surrogate_v3.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/df_surrogate/surrogate_v3.py) |
| `sjtu_tpmshx/preprocess/offline/publish.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/preprocess/offline/publish.py) |
| `sjtu_tpmshx/tests/test_df_overrides.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/tests/test_df_overrides.py) |
| `sjtu_tpmshx/tests/test_gamma_df.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/tests/test_gamma_df.py) |
| `sjtu_tpmshx/tests/test_sco2_gamma_f.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/tests/test_sco2_gamma_f.py) |
| `sjtu_tpmshx/tests/test_smooth_df.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/tests/test_smooth_df.py) |
| `sjtu_tpmshx/validation/df_refit/anchor_health.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/validation/df_refit/anchor_health.py) |
| `sjtu_tpmshx/validation/df_refit/anchor_provenance.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/validation/df_refit/anchor_provenance.py) |
| `sjtu_tpmshx/validation/df_refit/bayes_exam.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/validation/df_refit/bayes_exam.py) |
| `sjtu_tpmshx/validation/df_refit/extract_dev_coeffs.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/validation/df_refit/extract_dev_coeffs.py) |
| `sjtu_tpmshx/validation/df_refit/gamma_hx_air.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/validation/df_refit/gamma_hx_air.py) |
| `sjtu_tpmshx/validation/df_refit/gamma_hx_water.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/validation/df_refit/gamma_hx_water.py) |
| `sjtu_tpmshx/validation/df_refit/gamma_specimen.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/validation/df_refit/gamma_specimen.py) |
| `sjtu_tpmshx/validation/df_refit/gamma_two_layer.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/validation/df_refit/gamma_two_layer.py) |
| `sjtu_tpmshx/validation/df_refit/loo_surfaces.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/validation/df_refit/loo_surfaces.py) |
| `sjtu_tpmshx/validation/df_refit/method_matrix.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/validation/df_refit/method_matrix.py) |
| `sjtu_tpmshx/validation/df_refit/shanghai_blind_exam.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/validation/df_refit/shanghai_blind_exam.py) |
| `sjtu_tpmshx/validation/sco2_cfd/compare_smooth_df.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/validation/sco2_cfd/compare_smooth_df.py) |
| `sjtu_tpmshx/validation/sco2_cfd/make_error_report.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/validation/sco2_cfd/make_error_report.py) |
| `sjtu_tpmshx/validation/sco2_exp/compare_exp_vs_cfd.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/validation/sco2_exp/compare_exp_vs_cfd.py) |
| `sjtu_tpmshx/validation/sco2_exp/exam_sco2.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/validation/sco2_exp/exam_sco2.py) |
| `sjtu_tpmshx/validation/sco2_exp/gamma_f_variants.py` | [原文件](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/validation/sco2_exp/gamma_f_variants.py) |

旧表为水整芯、水发展段、SmoothDF、旧 sCO2 B/m 和两张实验 RBF 锚点表。
它们没有被改名为现用表，也没有重新拟合后覆盖当前系数。

## 仍需正确理解的历史结果

- 旧 RBF 的 D7 外推失效、旧 γ 锚点及不同流量/压损定义的问题仍是历史证据，
  详见保留的 [2026-07 D-F 审计](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/docs/DF-CALIBRATION-AUDIT-2026-07.md)。
- 水 D_7_6 旧发展段 cF 的约 +28.5% 变化不是现行联合表的更改要求。
- 水 Nu 的新核验仍为 D 9.9965%、G 10.6243% RMSRE；G 未过原 10% 门槛，
  用户选择继续使用原关联式，未放宽门槛或删点，见[数据记录](../data-catalog.md)。
- W01600 缺测结案；修订版水表的来源缺口继续保留。原始实验/CFD 只在私有
  数据仓保存，公开索引不包含原始测量文件。

## 已移出当前树的派生报告（21 个路径）

这些文件与退役前提交逐字节核对一致后从当前树移除。原数据、失败点和被否原因
仍由下列固定链接访问；旧研究不再列为当前版本的日常重跑任务。

| 原路径 | 固定历史入口 |
| --- | --- |
| `reports/2026-04-16-surrogate-v3-method.md` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/2026-04-16-surrogate-v3-method.md) |
| `reports/constdf-v1/2026-04-14-DF-re-independence-report.md` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/constdf-v1/2026-04-14-DF-re-independence-report.md) |
| `reports/constdf-v1/2026-04-14-DF-surrogate-loo-report.md` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/constdf-v1/2026-04-14-DF-surrogate-loo-report.md) |
| `reports/constdf-v1/2026-04-14-piedra-baseline.md` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/constdf-v1/2026-04-14-piedra-baseline.md) |
| `reports/constdf-v1/2026-04-15-DF-residual-structure-diagnostic.md` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/constdf-v1/2026-04-15-DF-residual-structure-diagnostic.md) |
| `reports/constdf-v1/2026-04-15-kim-adapted-diagnostic.md` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/constdf-v1/2026-04-15-kim-adapted-diagnostic.md) |
| `reports/constdf-v1/2026-04-15-kim-constrained-diagnostic.md` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/constdf-v1/2026-04-15-kim-constrained-diagnostic.md) |
| `reports/constdf-v1/2026-04-15-kim-k1-diagnostic.md` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/constdf-v1/2026-04-15-kim-k1-diagnostic.md) |
| `reports/df_refit/anchor_health.csv` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/df_refit/anchor_health.csv) |
| `reports/df_refit/anchor_provenance.csv` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/df_refit/anchor_provenance.csv) |
| `reports/df_refit/bayes_exam.csv` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/df_refit/bayes_exam.csv) |
| `reports/df_refit/dev_vs_core_vs_smoothdf.csv` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/df_refit/dev_vs_core_vs_smoothdf.csv) |
| `reports/df_refit/gamma_hx_air.csv` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/df_refit/gamma_hx_air.csv) |
| `reports/df_refit/gamma_hx_water.csv` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/df_refit/gamma_hx_water.csv) |
| `reports/df_refit/gamma_specimen.csv` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/df_refit/gamma_specimen.csv) |
| `reports/df_refit/gamma_two_layer.csv` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/df_refit/gamma_two_layer.csv) |
| `reports/df_refit/gamma_two_layer_surface.csv` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/df_refit/gamma_two_layer_surface.csv) |
| `reports/df_refit/loo_surfaces.csv` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/df_refit/loo_surfaces.csv) |
| `reports/df_refit/method_matrix.csv` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/df_refit/method_matrix.csv) |
| `reports/df_refit/shanghai_blind_exam.csv` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/df_refit/shanghai_blind_exam.csv) |
| `reports/sco2_cfd/df_smoothdf_vs_sco2.csv` | [原文与数值](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/reports/sco2_cfd/df_smoothdf_vs_sco2.csv) |

ConstDF 的负结果保留：Piedra 的 LOO 33%/47%，Kim K1 样本不足，
Kim 子集和约束变体未优于当时基线。旧 γ/双层 γ/方法矩阵的失败行也未筛除。
现行 `reports/df_refit/cf_cross_fluid.csv`、四份 `experimental_effective_*`，
sCO2 Nu 系数/留一报告继续留在当前树。M1/M2 固定输入及消费者随后已退役，
见[工程与试验索引](retired-tools.md)，不再作为当前重跑入口。

## 私有原件归档

`raw_data/archive/` 保存 8 份非现用原件：普通 CO2 的 4 个 CSV、D76 公式/处理
工作簿及 REFPROP 附件、较旧的水压损整理表。数据提交由 `data-revision.txt`
固定，全部 24 份数据逐字节保留，路径详见[数据目录](../data-catalog.md)。

# sCO2 CFD：现行 Nu 工具与历史 D-F 归档

当前数据位于 `data/raw_data/cfd/sco2/{Diamond,Gyroid}/`；统一读取器为
`df_surrogate/load_sco2_cfd.py`，保留拓扑、布局、压力/密度和原始字段守卫。

`fit_nu_sco2.py` 保留 Nu 各变体拟合、几何/压力留一验证及
`.cache/reports/sco2_cfd/nu_sco2_fit_coeffs.csv`、`nu_sco2_logo.csv` 输出。
研究重拟合不自动更新 `models/nu_correlations.py` 的现行系数。

旧 `compare_smooth_df.py`、`make_error_report.py`、SmoothDF/sCO2 B/m 模型
随旧 D-F 路线退役。原 README 中的 2026-07-15 系数、适用域、失效带和重启
清单完整保留在[固定历史版本](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/a82fc0a0ce71fd47333594fa053799ac8b263150/sjtu_tpmshx/validation/sco2_cfd/README.md)，
它们是当时的结果，不能作为当前生产模型的新验收。

现行阻力采用联合水+sCO2 几何固定 K/cF 及已审查的实验修正，见
[架构](../../../docs/architecture.md)；旧模型完整入口见
[历史索引](../../../docs/history/legacy-models.md)。现行 sCO2 实验模式从
`configs/sco2_effective_nu.json` 读取总有效 Nu 系数，通过
`models.nu_correlations.sco2_effective_nu_config()` 显式选择；使用、标定来源及
有限验证范围见[模型资源](../../../docs/model-resources.md#sco2-有效-nu-系数)。
旧 `fit_nu_correction` 和 `nu_bytemp_report` 随原实验锚定 γ 路线退役，固定源码
见[历史入口](../../../docs/history/legacy-models.md#sco2-nu-旧锚定路线2026-09-20)，
不能用于重建现行系数。这里保留的 CFD 基础式拟合、读取和清洗不受该退役影响。

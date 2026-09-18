# 模型资源、离线拟合与标定来源

## 离线数据与正式准备流程

`sjtu_tpmshx.preprocess.offline` exposes the experiment, water CFD, sCO2 core
and sCO2 segment cleaners. Each accepts `source=`. The caller selects the
resource; a missing explicit input never triggers a search for an alternative.

Experiment cleaning retains col47 friction dP, L8 Re>=1600 and Shanghai
source/geometry exclusion guards. CFD cleaning retains raw Dh and nominal Re,
pressure-density guards, entrance exclusions and water flow-suspect flags.

```python
from sjtu_tpmshx.preprocess.offline import load_experiments, load_water

frame = load_experiments(source=training_workbook)
water = load_water('Diamond', source=water_workbook)
```

`fit_nu_sco2` reuses the existing log-space fit. The validation script retains
campaign splits, cross-validation, metrics and CSV reports. Returned research
coefficients need physical acceptance before promotion; this API never installs
them as production correlations. Importing offline modules does not refit data.

On 2026-09-12 the user approved retiring SurrogateV3/gamma research models and
`publish_surrogate`, together with `build_prebuilt_surrogate`. Their original
col43/alpha pressure convention, publication contract and tests are preserved
at the fixed Git state in the [history index](history/legacy-models.md).
The current col47 cleaner does not replace that historical calibration product.

Ordinary full preparation uses the fixed CFD resource and is tested with
workbook reading forbidden. Quick-design evaluates analytical inlet-pressure
fractions in preparation; the receiving solver uses the recorded fractions.
Only the fixed CFD method is now supported. Serialized preparation/solve and
postprocess boundaries are unchanged.

The matching private data commit is recorded by `data-revision.txt`; the
[data catalog](data-catalog.md) records active and historical paths.
`Water-CFD/水数值模拟数据.xlsx` remains missing. The explicit legacy-water Nu
check does not substitute that file or reconstruct its historical fit; its
measured error and the decision to retain the original Nu are in the catalog.

## 当前资源与研究输出

正式系数由 `sjtu_tpmshx/models/nu_correlations.py`、
`sjtu_tpmshx/df_surrogate/experimental_correction.py` 和
`sjtu_tpmshx/df_surrogate/_prebuilt/cfd_full_core_3cell_fixed_v2.csv` 提供。
该 CSV 是运行时输入；测试读取的 MMS 阶数/边界 CSV 也是有效验证资源，继续保留。

离线复核工具保留在 `validation/`，生成的拟合 CSV 默认写入本地
`.cache/reports/df_refit/` 和 `.cache/reports/sco2_cfd/`。调查脚本、阶段计划和
研究结果放在忽略的 `.cache/`；现行使用说明、模型来源、物理约束和有效测试随代码维护。
过去上传的阶段报告、任务图和拟合结果表见[历史索引](history/README.md#2026-09-18-历史材料整理)。
清理当前树不抹除 Git 历史，也不将研究候选自动设为生产模型。

## 上海 Gyroid 空气阻力标定

正式值为 `sF = 2.649010286988306`，版本为
`shanghai-air-straight-20260401-v1`。它修正固定 CFD 基线的惯性项：
`K0 = 5.370404288696783e-8 m²`，`cF0 = 199.05002405781562 m⁻¹`，
修正后 `cF = sF × cF0 = 527.2855613544234 m⁻¹`；K0 不变。

来源为本地 `data/raw_data/experiments/water_air/` 中的
`water-air_G7-t0p6_shanghai_experiment_20260401.xlsx`，`Sheet1` 第 4–18 行，
即第 2–16 工况。4 月 1 日空气沿 +x 直通，水沿 −y 错列开口流动；
4 月 7 日空气和水交换流道，试件及其他管路不变，只用于迁移验证，不参与本次拟合。

| 输入 | 原表字段与换算 |
| --- | --- |
| 质量流量 | F 列名义质量流量，kg/s |
| 温度 | AC/AD 列进出口摄氏温度，转换为 K 后取平均 |
| 压力 | AE/AF 列表压 Pa，均加 101325 Pa 得绝压 |
| 截面积与长度 | 单流道面积 A = 6.50e-4 m²，L = 0.182 m |
| 空气物性 | R = 287.05 J/(kg K)，μ 由现行 air_viscosity 在平均温度求值 |

令 `T̄ = (Tin + Tout)/2`，`G = ṁ/A`，一维可压缩公式为：

```text
Pout² = Pin² − 2 R T̄ L (μ G/K0 + sF cF0 G²)
Δp_pred = Pin − sqrt(Pout²)
目标函数 = mean((Δp_pred/Δp_exp − 1)²)
```

固定 K0，仅拟合 sF；沿用 Δp ≥ 2000 Pa 与重复行排除规则。第 1 个低流量
工况在标定范围外，保留计算、外推提示和单列误差，不混入第 2–16 项的拟合结论。
`python -m sjtu_tpmshx.validation.df_refit.fit_experimental_effective` 从原表重算，
输出源文件、工作表、行号和复核系数；不覆盖生产参数。

适用几何为均匀、对称 Gyroid 7/0.6 mm、182×42×42 mm 换热器，无分区、δ=0；
端口与其他物理范围仍受[架构约束](architecture.md)检查。此值是该实验和模型
口径下的有效阻力修正，不能当成与装置、面积和压力定义无关的通用工质常数。

| 速度口径 | 空气孔隙速度范围（m/s） |
| --- | --- |
| 原始一维标定口径 | 8.026110584256458–22.441995588974073 |
| 正式入口密度/孔隙面积口径，用于标定外推提示 | 8.027855328062564–22.446874107951544 |
| 已批准可计算范围 | 3.912822900405603–24.546710397710296 |

按空气侧选择系数，现有空气/水/sCO₂ 的九种有序配对仍按各侧物理校验决定能否
计算；实验精度仅确认已审查的空气—水工况，空气—空气、空气—sCO₂ 不据此宣称
同等精度。超出标定窗但仍在允许计算范围内时继续计算并提示外推。
修正在压力初值、SIMPLE 和准备好的 Case 资源中只应用一次；回放旧 Case 使用其
保存的模型参数，不再次套用新表。不采用旧研究中的额外共同倍率。其他拓扑和
工质的系数、范围与数值门槛不因本次文档整理改变。

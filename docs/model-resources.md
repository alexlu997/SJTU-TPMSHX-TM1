# 模型资源、离线拟合与标定来源

[中文](model-resources.md) | [English](model-resources.en.md)

## 离线数据与正式准备流程

`sjtu_tpmshx.preprocess.offline` 提供实验、水 CFD、sCO2 芯体和 sCO2 分段清洗入口。
各入口接受 `source=`，由调用方选择资源；显式输入缺失时不搜索替代来源。

实验清洗保留 col47 摩擦压降、L8 Re>=1600 和上海来源／几何排除检查。
CFD 清洗保留原始 Dh、名义 Re、压力／密度检查、入口段排除和水流量可疑标记。

```python
from sjtu_tpmshx.preprocess.offline import load_experiments, load_water

frame = load_experiments(source=training_workbook)
water = load_water('Diamond', source=water_workbook)
```

`fit_nu_sco2` 复用既有对数空间拟合。验证脚本保留批次划分、交叉验证、指标和 CSV 报告。
返回的研究系数须先经过物理验收才能采用；此 API 不将其安装为生产关联式。
导入离线模块不触发重新拟合。

2026-09-12 用户批准退役 SurrogateV3/gamma 研究模型、`publish_surrogate`
及 `build_prebuilt_surrogate`。原 col43/alpha 压力约定、发布契约和测试保留在
[历史索引](history/legacy-models.md)的固定 Git 版本中。
当前 col47 清洗器不替代该历史标定产物。

普通完整前处理使用固定 CFD 资源，并通过禁止工作簿读取的测试。
快速设计在前处理评估解析入口压降比例，接收求解器消费记录的比例。
当前只支持固定 CFD 方法，序列化前处理／求解及后处理边界不变。

匹配的私有数据提交由 `data-revision.txt` 记录；[数据目录](data-catalog.md)
记录当前和历史路径。`Water-CFD/水数值模拟数据.xlsx` 仍缺失。
显式 legacy 水 Nu 检查不代替该文件，也不重建其历史拟合；
实测误差与保留原 Nu 的决定见数据目录。

## 当前资源与研究输出

固定系数、范围和参考态的权威来源是
[model_parameters_v1.json](../sjtu_tpmshx/shared/configs/model_parameters_v1.json)。
仅依赖 Python 标准库的
[model_parameters.py](../sjtu_tpmshx/shared/configs/model_parameters.py) 读取并校验该资源。
Python 模型模块从同一数据构造常量，保留现有名称及 tuple/dict 类型。
C++ 头文件生成器直接读取资源，不再导入数值模型。
第一批统一数据来源；第二批将标准、CO2、非对称几何与 chi/Kss 计算迁入独立 C++ 几何核心。
第三批将网格、端口、连续 XY/XYZ 场、sigmoid、线性 LUT、分区和 Gaussian 平滑接入同一几何库。
数值公式由各自 C++ 核心负责；Python 保留配置、类型适配、数据对象、I/O、缓存和应用编排。
第四批将物性／闭合、固定 DF／实验修正、投影和准备数值迁入独立 preparation 库。
新资源只归集原值；既有模型身份、单位、拟合系数和实验结论不变。
第五批已接入独立结果核心，负责指标、物理平衡、分区统计和数值资格检查；数值与平台验收仍在进行。
六批迁移尚未完成，各批验收须包含平台 CI 和最终检查。

Python 几何接口保留类型、缓存与逐次调用的 chi 显式值／环境值／拟合选择，不保留数值 fallback。
修改 C++ 函数或资源中编入库的参数后，须重新构建各受影响原生库并重启进程。
构建、路径及四库运行边界见[原生准备核心](cpp-migration.zh-CN.md#native-preparation-core)和[独立结果核心](cpp-migration.zh-CN.md#native-result-core)。
XY、XYZ、LUT 与 Gaussian 的固定来源和局部数值处理见[设计场来源说明](../sjtu_tpmshx/solvers/native/geometry/fields-sources.md)。
贯通、扫描、Richardson 和目标 C 研究位于
`sjtu_tpmshx/development/runs/tools/asym_geometry_research.py`，shared 不保留旧转发入口。

[co2_segment2_v1.json](../sjtu_tpmshx/shared/configs/co2_segment2_v1.json)
继续提供 CO2 分段 Nu 和几何数据；
[sco2_effective_nu.json](../sjtu_tpmshx/shared/configs/sco2_effective_nu.json)
继续提供现行 sCO2 有效 Nu 参数。
固定 D-F 表仍由
`sjtu_tpmshx/shared/df_surrogate/_prebuilt/cfd_full_core_3cell_fixed_v2.csv` 提供。
这三个资源各自保持权威，新增资源不重复其中的数据。
[preparation_df_v1.json](../sjtu_tpmshx/shared/configs/preparation_df_v1.json) 统一持有固定方法标识、bracket 容差、
air specimen／HX 修正系数、几何与速度容差、来源标定／应用／运行三个速度窗口，以及标定 provenance。
`load_preparation_df_parameters()` 返回新的 mapping，Python 保留标定元数据和公开 tuple／dict 接口。
生成器直接读取该 JSON、固定 CSV 和既有模型资源，不导入数值模型，也不重新拟合。
CSV 五列 `tp/L_mm/t_mm/K_m2/cF_fixed_1_m` 是固定 DF 数值输入，不解释附加 eligibility 列。
正式推理由 C++ 使用编入库的节点和系数；Python 不在运行时解析 CSV 或保留插值 fallback。
`experimental_correction.py` 保留应用接口、元数据和警告；数值因子、窗口判定、插值、乘法和归约由原生 DF owner 负责。
CSV 继续服务构建和独立测试；测试读取的 MMS 阶数／边界 CSV 也继续保留。

原始经验 getter、带检查的 EOS 状态和 Nu 闭合保留各自合同，不统一增加状态检查。
离线清洗与拟合仍在 Python，不能作为正式数值 fallback。
Python wheel 包含代码、JSON 和 CSV 资源，不包含本机原生库。
物性表版本、模型资源身份和原生库构建身份分开记录；旧检查点仍要求匹配的求解运行库。

离线复核工具保留在 `development/validation/`，生成的拟合 CSV 默认写入本地
`.cache/reports/df_refit/` 和 `.cache/reports/sco2_cfd/`。调查脚本、阶段计划和
研究结果放在忽略的 `.cache/`；现行使用说明、模型来源、物理约束和有效测试随代码维护。
过去上传的阶段报告、任务图和拟合结果表见[历史索引](history/README.md#2026-09-18-历史材料整理)。
清理当前树不抹除 Git 历史，也不将研究候选自动设为生产模型。

完整求解器的范围策略以原始标定或关联式边界为准。正值区间 `[L,U]` 最多允许 `[0.9L,1.1U]`，历史应用许可不扩大该区间。保存的入口和最后一次局部观测支撑[架构文档](architecture.zh-CN.md#捕获的参数范围)中的独立范围结论，不替代几何、相态、模型范围或实验检查。

固定几何/D-F 表支持胞元 4–8 mm、壁厚 0.3–0.6 mm；Nu 关联式和实验修正各有
独立的证据范围，不能用几何表范围替代。水侧同样从固定 CFD 阻力基底开始，
只有显式实验模式才应用对应实验修正；跳过空气专用粗糙度算法不表示 CFD 已含
实验修正。一维等温 D-F 近似遇到非正出口压力平方时，只能说明该近似无正的
出口压力解，不能据此认定真实流动阻塞。该接口在 `strict=True` 时返回 NaN，
否则保留入口压力作为占位压降，并分别记录告警；占位值不是有效压降预测。

## sCO2 有效 Nu 系数

现行实验模式参数的唯一发布资源是
[sco2_effective_nu.json](../sjtu_tpmshx/shared/configs/sco2_effective_nu.json)，版本
`sco2-effective-nu-20260920-v1`。模型工厂
`shared.models.nu_correlations.sco2_effective_nu_config()` 读取该资源并返回经过校验的
`Sco2NuConfig`；调用方不另存一套现行默认系数。

| 字段 | 现行值 | 含义 |
| --- | ---: | --- |
| `alpha_G` | 2.4824 | Gyroid 相对当前 CFD 基础关联式的总有效系数 Ceff |
| `alpha_D` | 4.1064 | Diamond 相对当前 CFD 基础关联式的总有效系数 Ceff |

字段名 `alpha_D/alpha_G` 保留，但其语义都是**总 Ceff**。计算为
`Nu_selected = Ceff × Nu_base`，然后沿用现有 Nu 下限等约束；只乘一次。
没有生产 `beta` 字段，不再同时估计两个独立物理修正。它改变局部 Nu 和换热系数，
完整求解后才得到 Q，不是把输出 Q 乘以 Ceff。前后温度、物性和速度会变化，
所以两次完整求解的局部 h 场不必处处保持相同比值。

GUI 的“使用现行有效系数”按钮显式载入这一版本；“导入”仍可使用有版本、来源
和适用范围的自定义/历史参数。API 可在完整输入字典中显式选择：

```python
from dataclasses import asdict
from sjtu_tpmshx.shared.domain.compute_config import ComputeConfig
from sjtu_tpmshx.shared.models.nu_correlations import sco2_effective_nu_config

config_dict["sco2_nu"] = asdict(sco2_effective_nu_config())
config = ComputeConfig.from_dict(config_dict)
```

通用 `cfd_smooth` 默认值不变。保存的配置和已准备 Case 保留其实际模型参数；
加载旧文件不自动应用现行值，也不把历史 `alpha` 再乘一次现行 Ceff。
参数 JSON 只记录 Nu 模型选择与来源，不是完整算例，不会改变网格或求解容差。

### 标定来源与目标

2026-09-20 以本地
`data/raw_data/experiments/sco2/sco2_DG7-t0p6_hx_experiment_summary.xlsx`
中的 Gyroid 整机实验，重新标定**当前基础关联式**的幅度。仅使用 30 个开发工况，
目标是等工况权重的热侧相对 Q 误差平方均值：

```text
J(Ceff,G) = mean_i[(Q_model,i(Ceff,G) / Q_hot,exp,i − 1)²], i = 1..30
```

各候选都完整更新流动、物性与三相温度，正式选择依据为 104×24×12 网格的
真实求解目标。目标是相对 MSE，不是 MAPE，也不使用表观 h/平均局部 h 的比值。
搜索期间以历史幅度归一化得到相对倍率 2.32；发布时已合并为表中的总 Ceff。
旧幅度仅是这一搜索的坐标与对照，不再解释成另一层独立的物理修正。
Diamond 按用户指定共用相同相对调整，未参与 Gyroid 的参数选择，仍属于迁移假设。

30 个开发成员为 G2/4/5/6/7/8/9/11/12/13/14/15/17/18/19/20/21/23/24/25/26/28/29/31/32/34/35/36/38/40。
冻结参数后复核 G3/10/16/22/33/39/41/42 共 8 例；之前已经用于试探的 G27/G44
单列为 2 例旧试点；Diamond 仅检查 D8/D27/D50 三例迁移。
全部 Gyroid 历史结果此前已经查看，旧幅度的历史筛选也不足以保证与这批数据独立；
因此这属于回顾性分组复核，不是盲测或整个关联式的独立验证。

### 已有验证与剩余误差

下表记录 2026-09-20 的 H-FOU 对照，使用相同源码、104×24×12 网格和严格数值设置。
后续 SOU 结果采用不同数值方法，作为独立证据保留。
冷热两侧各保留自己的实验 Q 分母；MAPE 为平均绝对相对误差，不把两侧混成一个数。
“旧参数对照”是本次重新计算的配对基线，不替换原 83 工况历史结果。

| 分组 | 数量 | 热 Q MAPE，旧→现行（%） | 冷 Q MAPE，旧→现行（%） |
| --- | ---: | ---: | ---: |
| Gyroid 开发 | 30 | 16.304 → 3.414 | 23.224 → 8.458 |
| Gyroid 本轮留出复核 | 8 | 17.541 → 2.500 | 24.913 → 11.224 |
| Gyroid 已用试点 | 2 | 14.837 → 1.153 | 25.521 → 11.538 |
| Diamond 同倍率迁移 | 3 | 29.419 → 18.547 | 31.739 → 21.231 |

8 例复核中，6 个约 100 g/s 流量成员的现行热/冷 MAPE 为 1.035%/10.260%；
两个高冷侧入口温度成员 G41/G42 为 6.896%/14.116%，最差热侧误差为 G41 的
−9.333%。输入分组的差异不是温度的因果隔离证据，也未用于回调冻结系数。
不同的实验冷热 Q 无法被同一个守恒芯体输出同时精确匹配；热侧精度改善不意味着
冷侧偏差已消除。Diamond 三例仍有明显误差，不能据此宣称全部 43 例或其他拓扑获准。

固定现行系数，将 G8/G13 加密到 208×48×24，Q 分别增加 0.721%/0.522%；
对应实际搜索邻点的 Q 跨度为 0.668%/0.692%。只有两个开发工况做了这一对照，
不构成全组网格独立性证明，参数小数位也不是物理精度或统计置信区间。

上述验证使用外迭代温差 0.001 K，SIMPLE 动量 1e−5、局部/整体质量 1e−7；
焓更新 1e−6、耦合与三相方程能量各 1e−5，焓求解上限 1000×25、松弛 0.6，
逐轮收敛且无焓裁剪。数值合格与实验准确度分别判断；仅导入参数 JSON 并不会
自动启用这些严格设置，不能将其他默认网格/容差的输出当成上述实测数值。
原始输入、每次原生场和调查报告继续只存于本地忽略目录，不随使用说明发布。

### 物理范围与历史入口

适用依据为均匀、对称 D/G 7 mm 胞元、0.6 mm 壁厚、182×42×42 mm 芯体，
冷热均为 sCO2，现行变物性与压力处理，既有冷侧部分端口及 104×24×12 模型。
Gyroid 开发样本热/冷入口温度分别为 128.640–230.827 °C / 96.815–135.347 °C，
入口绝压分别为 8.278–9.116 MPa / 9.437–10.725 MPa；这些是已有样本边界，
不是所有范围内组合都已验证。D-F、焓、物性及原 CFD 关联式的适用限制仍需各自满足。

Ceff 是这一设备及均质模型的有效幅度，可能同时吸收关联式外推、内部温差分配、
离散及实验测量范围差异。本次拟合不能唯一分解这些来源，不能证明真实局部 Nu、
壁温或全温度场正确，也不能作为其他几何、混合工质或任意低 Pr 范围的通用修正。
更换网格、离散方法、装置或工况范围后需重新核查。

原 D/G=1.77/1.07，以及旧锚定 γ≈1.809/1.130，仅保留为历史模型和保存输入的
解释依据；旧 γ helper、环境开关及专属重拟合/逐温度工具已退役。固定历史入口见
[sCO2 Nu 旧锚定路线](history/legacy-models.md#sco2-nu-旧锚定路线2026-09-20)。
原 CFD 基础式、CFD 拟合/读取/清洗工具和实验 Q 诊断继续保留，D-F 系数不变。

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
`python -m sjtu_tpmshx.development.validation.df_refit.fit_experimental_effective` 从原表重算，
输出源文件、工作表、行号和复核系数；不覆盖生产参数。

适用几何为均匀、对称 Gyroid 7/0.6 mm、182×42×42 mm 换热器，无分区、δ=0；
端口与其他物理范围仍受[架构约束](architecture.zh-CN.md)检查。此值是该实验和模型
口径下的有效阻力修正，不能当成与装置、面积和压力定义无关的通用工质常数。

| 速度口径 | 空气孔隙速度范围（m/s） |
| --- | --- |
| 原始一维标定口径 | 8.026110584256458–22.441995588974073 |
| 正式入口密度/孔隙面积口径，用于标定外推提示 | 8.027855328062564–22.446874107951544 |
| 历史批准的可计算范围 | 3.912822900405603–24.546710397710296 |

按空气侧选择系数，现有空气/水/sCO₂ 的九种有序配对仍按各侧物理校验决定能否
计算；实验精度仅确认已审查的空气—水工况，空气—空气、空气—sCO₂ 不据此宣称
同等精度。超出标定窗但仍在允许计算范围内时继续计算并提示外推。
获准计算不代表资格通过；入口和局部观测仍使用当前原始范围判定规则。
修正在压力初值、SIMPLE 和准备好的 Case 资源中只应用一次；回放旧 Case 使用其
保存的模型参数，不再次套用新表。不采用旧研究中的额外共同倍率。其他拓扑和
工质的系数、范围与数值门槛不因本次文档整理改变。

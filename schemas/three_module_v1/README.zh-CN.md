<a id="tm1-public-data-contract"></a>

# TM1 公共数据契约

[中文](README.zh-CN.md) | [English](README.md)

本文定义公共数据契约。[能力清单](../../docs/capabilities.md)记录当前实现和验收状态。契约不表示每个生产者、后端或文件编解码器都已实现。[固定历史索引](../../docs/history/README.md)保留原始要求和节点证据。

<a id="shared-rules"></a>

## 共享规则

公共前处理在 `CaseData.metadata.provenance` 中记录软件包版本、源码仓库修订和跟踪文件修改标志。它还记录配置的原始数据仓库修订，以及独立的 `data-revision.txt` 声明。公共执行保留该前处理记录，并在 `FieldResult.metadata.provenance.execution` 中加入执行入口快照。模型版本仍位于 `model_refs`。后端标签和模式版本标签不是代码修订。YAML/HDF5 保留这些记录；加载和后处理时不查询 Git。

这些信息描述仓库上下文，不是逐文件的数据使用清单，也不表示未跟踪文件已纳入版本管理。没有 Git 的源码安装明确记录修订不可用，同时保留软件包版本。缺少原始前处理记录时，状态为 `not_recorded`。不得从之后的检出状态补填这两类信息，也不得静默改用声明的数据版本。

映射键必须为字符串。载荷仅包含标量数据、数值或布尔数组、序列和嵌套映射。禁止函数、活动实例和对象数组；模型参数与结果元数据也受此约束。数组复制到不可变存储；求解器工作数组使用独立副本。保留非有限诊断值，但可用的工程指标必须有限。缺失或无效指标不带数值，并给出原因。

`schema_version` 标识数据模式。模型版本与指标定义版本独立管理。对应的读取器或解析器必须拒绝未知版本。回调只属于 `RunControl`，不得写入文件。

## CaseData

| 字段 | 权威来源与使用方 |
| --- | --- |
| `case_id`, `schema_version` | 身份与受支持的数据模式。 |
| `config_snapshot` | 独立的输入来源快照，包括明确命名的历史 mm 字段；不能代替准备好的问题。 |
| `grid` | 真实坐标中的物理网格、SI 间距和边界支持信息。求解器可以重排轴，但不得另选网格。 |
| `design_fields` | 准备好的空间几何和固定系数。使用方必须消费受支持数据，或明确拒绝；不得忽略。 |
| `parameters` | 前处理解析的物理与数值设置，不含回调和活动模型或求解器实例。 |
| `model_refs` | 具名且带版本的模型资源，包含独立参数和适用范围；接收进程在运行时解析。 |
| `metadata` | 前处理来源、模式与能力声明、源码修订；不得成为隐式的替代输入通道。 |

`from_compute_config` 只捕获来源信息。具体前处理器必须提供并校验所声明模式所需的完整网格、参数、边界和模型数据，Case 才可执行。契约测试中的空容器是合成数据，不是可执行工况。

生产模块必须记录每个具体键的来源、单位、形状和使用方，之后才能声明契约验收通过。原始输入快照不能为准备态数据中的含糊单位提供依据。

## FieldResult

| 字段 | 权威来源与使用方 |
| --- | --- |
| 身份／后端／版本 | 运行身份、来源工况和实际后端。 |
| `grid` | 实际原生网格的真实坐标和拓扑。 |
| `fields` | 原生温度、压力和速度数据；显示场与细化场使用独立名称。 |
| `field_metadata` | 每个导出场的单位、位置、坐标和状态时点。 |
| `boundary_fluxes` | 实际边界上的有符号质量和能量输运，已包含面积；Q/Tout 摘要不能代替它。 |
| `pressure_evidence` | 复现每个压降所需的表压场、参考偏移、测量面、原生间距和提取规则。 |
| `run_status` | 执行、收敛、物理适用域、筛选或验证状态，以及残差和警告；这些结论彼此独立。 |
| `model_refs`, `metadata` | 模型及其来源、原始结果元数据、代码与数据修订，以及必要的已解析输入来源。 |

结果声明必须一致。存在 `grid.dimension` 时，以其为准；部分内存证据可使用 `metadata.dimension`。两者同时存在时必须相同。显式 `quantity_basis` 在二维中必须为 `per_unit_depth`，在三维中必须为 `total`；不得给存档补入原本省略的声明。

后处理要求已知的二维或三维维度，并支持 `full` 和 `quick_design`。已退役的 `screening_2d` 与 `screening_3d` 存档仍可读取，但不能执行或重算指标。只有省略 `mode` 时才默认使用 `full`。未知的显式模式可以原样存档，但当前后处理必须在归约任何指标前拒绝它。保存部分或未收敛结果不表示其可执行或已验证。各指标缺失证据时，保留原有的明确状态。

原生交错面必须对应一致、各维为正的单元形状，并匹配所有记录的网格轴。三维 model-h 要求六个形状正确的边界平面，包括零通量面。结构缺陷仅使消费该证据的指标无效。整组证据缺失仍属于数据不足；一致的部分内存证据和完整的零输运证据仍然有效。

完整二维和三维的出口温度使用主网格最后一次原始温度，以及真实开口上向外为正的有符号质量通量。回流仍保留在存储的有符号通量中，以用于守恒。不得再次乘以热容或面面积。原路径使用不同锚点时，压力状态和显示偏移必须明确区分。Richardson 数据与主求解分别标注。

<a id="metricspec-and-performanceresult"></a>

## MetricSpec 和 PerformanceResult

Q 支持 W（总热负荷）和 W/m（单位深度热负荷）；质量支持 kg 和 kg/m。Pa 与 K 保持通常含义。每个指标必须明确单位。二维热负荷仅在显式提供物理深度（m）后，才能乘以该深度得到总 W。只有应用明确请求单位深度值时，才将三维总量除以实际 Lz。不存在默认试样厚度。

已知的侧别名称遵循其指标族的单位契约：`dP_A/B` 要求 Pa，`T_out_A/B` 要求 K，热负荷要求 W 或 W/m。指标映射键必须匹配其 spec 名称或明确的指标族名称。例如，`dP_A` 接受 `dP_A` 或 `dP`，不能接受 `dP_B` 或 `T_out`。未知扩展指标保留自身匹配的键与 spec 名称。内存结果和 JSON 输入都必须通过这些检查。不兼容单位必须拒绝，不能转换或改标签。历史定义版本仍可读取。

指标定义版本还必须标识报告的侧别、符号、压力测量规则和热状态时点。未收敛运行的有限结果，不会因后处理完成而成为已验证指标。`available`、`insufficient_data`、`unsupported` 和 `invalid` 是指标状态；原运行结论仍在 FieldResult 中。

完整计算的 `native_boundary_v1` 将 `Q` 定义为主热状态边界输运的 `abs(Q_A)`。`Q_A`/`Q_B` 是有符号热损失，流体放热为正。`energy_imbalance_rel` 使用同一组原生热负荷。出口温度和质量流量使用匹配的有符号热状态质量面。独立命名的二维 `Q_richardson_A/B` 保留已接受的绝对热负荷外推，不能代替主网格指标。每项定义保存到 `MetricSpec.description` 和 `definition_version`，包括 JSON 导出。

完整计算压降采用 `pressure_face_v1`：将压力外推到物理入口面和出口面，以几何开口面积加权，再取差值。当前计算不支持显式请求旧的完整计算指标定义。已保存的旧指标仍按原定义读取；当前 GUI 映射需要重新评估原生结果。该消费检查也覆盖各侧热负荷、温度和显示的平衡指标。

多工况聚合也要求当前的有符号 `Q_B` 和物理面压降定义，即使两个比较记录使用同一旧定义也不例外。等价的指标族或侧别名称不改变指标含义。声明的结果维度约束原生热量单位；聚合不得推断缺失的物理厚度。

<a id="runcontrol-and-module-ports"></a>

## RunControl 和模块端口

公共函数端口为 `preprocess.api.prepare_case(config, case_id=...) -> CaseData`、`solvers.api.run_case(case, control) -> FieldResult` 和 `postprocess.api.evaluate(result, metric_spec) -> PerformanceResult`。运行进度和取消回调单独传入。显式取消抛出既有 `CancelledError`；无关的回调失败保留原错误。

`iteration(label: str)` 传递原有外迭代标签。`residual(side: str, index: int, value: float)` 传递二维 SIMPLE 观测。使用方可通过 RunControl 观察残差。这些观测不改变停止条件，也不写入 CaseData 或 FieldResult。正式 HDF5 编解码器和各模式的能力／字段表定义受支持的文件交接；参见当前架构和验收记录。

<a id="application-payload-current-v1-draft"></a>

## 应用载荷（当前 v1 草案）

Case 元数据中的 `model_metadata.sco2_nu` 和 `notices` 保存已解析模型的展示来源和说明文字。当前二维和三维生产者均输出这些字段。实验参数 `alpha_D/alpha_G` 是总有效 Nu 系数，仅应用于所选 CFD 基础模型一次。序列化数据中没有额外的 `beta` 因子。显式选择当前模型时，`sco2_effective_nu_config()` 解析 `configs/sco2_effective_nu.json`；版本、来源和适用范围随数值传递。

加载已保存配置或准备态 Case 时，保留它自己的参数，不替换为较新的资源。自定义和历史实验参数仍须提供自身来源。通用默认值 `cfd_smooth` 不变。参见[模型资源](../../docs/model-resources.md#sco2-有效-nu-系数)。本开发草案尚未作为稳定存档格式发布；早期草案夹具不能建立向后兼容承诺。

FieldResult 另记录 `design_mode`、上述模型字段和 `application`。其中 `coeffs` 包含 Kff、Kss（W/(m K)）和 hv（W/(m3 K)）；`props` 包含 rho（kg/m3）、mu（Pa s）、cp（J/(kg K)）、入口速度（m/s）和入口温度（K）。二维 `zones` 保留轴、原始统计和边界，以及既有明确字段名。值来自实际运行状态；历史三维审计系数缺失时保持 null。

原生系数字段仍可在 `fields` 中独立获取。此载荷只支持原有应用视图；数值后处理不使用它。原生数组与显示数组保留独立字段名和逐字段元数据。`outer_iteration(current, budget)` 是不持久化的 RunControl 回调，用于保留原生三维 UI 计数器。

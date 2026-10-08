<a id="3d-producer-contract--implementation-v1"></a>

# 三维生产者契约——实现 v1

[中文](three_d.zh-CN.md) | [English](three_d.md)

前处理输出实际 SI 网格，即包含细化的物理 `(x,y,z)` 单元宽度和边缘。`parameters.prepared` 包含轴映射、开口比例、几何和入口物性。后端对照给定网格校验并消费这些数据，不调用前处理。配置快照只记录来源。模型角色解析与二维相同的四个带版本资源；未知版本在执行前失败。

设计场形状为 `(Nx,Ny,Nz)`。`L_field_m/t_field_m` 单位为 m，`K_m2` 为 m²，`cF_per_m` 为 1/m，`K_ss` 为 W/(m K)，总孔隙率和各侧孔隙率无量纲。均匀几何必须与标量输入一致。离散网格分区使用 `design_mode="xy_extruded"`，不能引入 z 方向变化。分区边界按准备态网格的物理 x/y 单元中心选择，包括细化网格，不能按单元索引比例选择。保留原有默认值、后续分区覆盖顺序和 sigma=2 平滑。

对于 `zones.axis="continuous"`，原始样条控制量保留在 `parameters.continuous_field`。XY 控制量生成 `design_mode="continuous_xy_extruded"`。加入 `n_ctrl_z` 后，生成真实 L(x,y,z)/t(x,y,z)，并采用 `design_mode="continuous_xyz"`。样条在最终物理单元中心采样，包括细化网格，不使用离散分区的高斯滤波。执行器拒绝 XY 拉伸几何中的 z 变化；XYZ 模式必须记录 `n_ctrl_z`。连续场适用和标定限制仍见[架构](../../docs/architecture.zh-CN.md)。

FieldResult 包含最后一次原始热状态温度和输入换热系数，并记录场单位、物理轴和状态。true-h 热状态压力与最终 SIMPLE 表压、物性／报告压力分别捕获。最终表压保留在求解器坐标中，同时记录宽度、真实开口比例和轴映射，用于精确外推到面。

展示温度 `Ta/Tb/Ts_display` 与 `P_fA/P_fB_display` 从既有显示返回值复制，不使用物性压力场替换。各侧单元速度 `uc/vc/wc` 和 `vmag_A/B` 使用物理轴，单位为 m/s；`chi_B` 无量纲。各场都有显式元数据，并保存在同一结果存档中。这些显示场不决定指标。

热状态质量面采用物理轴，沿正 x/y/z 为正，单位为 kg/s，已包含完整面面积和各侧孔隙率。model-h 从既有热面算子捕获各侧六个向外边界能量数组，单位为 W。true-h 证据保存原生焓、入口焓（J/kg）和最后热状态的实际质量面。原有温度模式没有完整捕获的焓证据，该归约仍明确不受支持。

正式 `Q=abs(Q_A)` 使用最后热状态，即 `native_boundary_v1`。true-h 热负荷根据保存的原生焓、入口焓和实际热状态质量面计算。model-h 对原生向外能量数组积分，并在 `diagnostics.model_h_balance.sides` 中保留边界完整性检查。Tout 使用原始热状态温度，以及配置出口处向外为正的热状态质量通量。Q 和 Tout 都不能根据最终流动的物性压力状态重建。正式 dP 独立使用最终 SIMPLE 压力、物理面外推和几何开口面积权重，即 `pressure_face_v1`。

后端历史最终报告摘要和 `reporting_reference` 仍供既有使用方使用，与正式离线指标区分。保留的报告元数据提供出口方向，无需第二次重建质量或焓。

此处所有有量纲热负荷为 W，质量流量为 kg/s，不除以深度。数值收敛与指标可用性彼此独立。固体质量要求显式密度，不能由导热率提供。

<a id="fixed-thermal-geometry-and-calibration"></a>

## 固定热几何与标定

`parameters.thermal_geometry` 记录均匀几何；分区工况还记录物理 x/y/z 单元上的 A_0（1/m）、D_h（m）和 epsilon 场。它包含原有 128 点几何计算得到的非对称分配，以及各侧／参考 A_0/D_h 值。前处理保留入口范围观测，不存储冗余的初始 h_v 数组。当前速度／温度相关的 Nu 和物性仍在执行阶段评估。读取已保存 Case 时仍校验旧的可选 `air_bulk_hv.A/B`，但执行不消费这些字段。求解器不再次调用 tpms_compute。必需准备态执行字段缺失时明确失败；旧中间 Case 文件必须重新准备，不得在求解器内部静默重建。

`roughness_resolved` 记录所选模式和以 m 为单位的粗糙度 `eps_m`。接收方环境不能替换它。实验 `df_application.A/B` 记录已解析的正标量修正因子，以及试验批次／适用范围元数据；CFD 模式下为 null。运行时将固定因子应用于给定 K/cF 场，并报告实际基础系数和应用后系数，不重新选择或评估标定。修改有效 K 场仍会改变数值输入。

现有网格分区和连续设计都为两侧流体保留完整局部 K/cF 数组；系数均值只用于压力初始化。所有 SIMPLE 网格使用真实准备态宽度，包括均匀网格。物理场重排到各侧求解器轴。负向流动还反转流向宽度、孔隙率和局部 K/cF 数组，使局部入口索引零对应物理入口面。

受支持的实验连续场迁移将各侧固定因子应用于其局部 CFD 数组，并记录 `continuous-field-extrapolation`。它仍属于探索性趋势预测，不能代表已建立的梯度精度。已保存的历史结果不被改写。

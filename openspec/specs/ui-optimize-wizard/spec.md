# Spec: ui-optimize-wizard

[中文](spec.md) | [English](spec.en.md)

## Purpose
优化页三页向导（配置/运行/结果）：阶段按钮驱动翻页、内联参数、取消保样本。

## Requirements

### Requirement: Three-page wizard
优化页 SHALL 为 QStackedWidget 三页（配置/运行/结果），阶段票据 SHALL 可点击切页；`_set_stage_pill(key,'active')` SHALL 同步翻到对应页——启动→运行页、完成→结果页、错误→配置页均由引擎既有阶段流转驱动。

#### Scenario: Engine drives pages
- **WHEN** `_set_stage_pill('running','active')`
- **THEN** 栈当前页 = 1（运行）

### Requirement: Inline BO parameters
优化方法（qLogNEHVI/qLogNParEGO/qLogNEI/Sobol）及 n_init/n_iter/q_batch/seed SHALL 内联于配置页。
n_init 默认16，允许1–256；优化器 SHALL 继承当前计算配置的数值设置。启动 SHALL
读取内联值，不提供旧模态参数对话框；计划求解次数 SHALL 包含均匀基准和每个候选的
全部工况，剩余时间仅依据本次已完成样本的实测耗时估算。

#### Scenario: Launch consumes inline values
- **WHEN** 点击启动
- **THEN** worker 以内联 spinbox 值构造，无弹窗

### Requirement: Search space on page 1
配置页「搜索空间」卡 SHALL 提供连续场优化的 L/t 范围，并显示当前控制网格。
二维使用3×3控制点，三维使用3×3×3独立控制点；当前GUI不施加y对称约束。
单点计算的分区面板 SHALL 独立置于「单点计算分区（不参与优化搜索）」折叠卡；
旧 zones|canvas splitter SHALL 退役；结果页 SHALL 提供「Pareto 前沿」、「尺寸 / 壁厚场」
和「三维尺寸 / 壁厚场」页签，参数场页签 SHALL 在相应场数据可用时启用。

#### Scenario: Zone panel relocated
- **WHEN** 检查配置页
- **THEN** `_zone_panel` 位于单点计算分区卡；优化搜索空间独立，启动 CTA 在首屏可见

### Requirement: Constrained core mass
导入工况 JSON 可提供 `mass_requirements`，包含实体密度和每个工况的换热下限、两侧压降上限。
界面 SHALL 选择 qLogNEI 并显示芯体质量目标；Sobol 可使用相同约束。
会话与任务恢复 SHALL 保留要求。结果 SHALL 区分数值合格和约束可行。
最轻可行方案可选择和导出建模坐标；无可行方案时 SHALL 显示零个。
结果表和建模来源 SHALL 保留质量、限值及逐工况检查。

#### Scenario: One condition exceeds a limit
- **WHEN** 数值有效候选在任一工况超出任一限值
- **THEN** 它保留在观察数据中，但不能成为可选择的最轻可行方案

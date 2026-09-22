# Spec: ui-optimize-wizard

## Purpose
优化页三页向导（配置/运行/结果）：阶段按钮驱动翻页、内联参数、取消保样本。

## Requirements

### Requirement: Three-page wizard
优化页 SHALL 为 QStackedWidget 三页（配置/运行/结果），阶段票据 SHALL 可点击切页；`_set_stage_pill(key,'active')` SHALL 同步翻到对应页——启动→运行页、完成→结果页、错误→配置页均由引擎既有阶段流转驱动。

#### Scenario: Engine drives pages
- **WHEN** `_set_stage_pill('running','active')`
- **THEN** 栈当前页 = 1（运行）

### Requirement: Inline BO parameters
qNEHVI 参数（n_init/n_iter/q_batch/seed）SHALL 内联于配置页；二维显示 n_rho_loops，三维显示 max_outer_3d。`_launch` SHALL 读取内联值，不提供旧模态参数对话框；启动前可说明计划求解次数，剩余时间仅依据本次已完成样本的实测耗时估算。

#### Scenario: Launch consumes inline values
- **WHEN** 点击启动
- **THEN** worker 以内联 spinbox 值构造，无弹窗

### Requirement: Search space on page 1
配置页「搜索空间」卡 SHALL 提供连续场优化的 L/t 范围、控制网格与对称设置。
单点计算的分区面板 SHALL 独立置于「单点计算分区（不参与优化搜索）」折叠卡；
旧 zones|canvas splitter SHALL 退役；Pareto 画布 SHALL 独占结果页。

#### Scenario: Zone panel relocated
- **WHEN** 检查配置页
- **THEN** `_zone_panel` 位于单点计算分区卡；优化搜索空间独立，启动 CTA 在首屏可见

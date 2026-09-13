# Spec: ui-result-workbench

## Purpose
结果工作台：三页签工具栏、2D|3D 切换、诊断侧栏与诊断详情对话框。（结构修复 2026-07-03：补 Purpose 头，内容不变。）

## Requirements

### Requirement: Three-tab workbench
画布工具条 SHALL 只呈现 几何布局｜结果｜优化 三个页签；温度/压力/速度/3D/2D 的内部路由键继续由 `ui/mixins/tab_view.py` 解析，不依赖隐藏按钮对象；「结果」SHALL 在任一模式有结果时可用。

#### Scenario: Tabs collapsed
- **WHEN** 检查工具条可见按钮
- **THEN** 仅 几何布局/结果/优化（+右端动作）；`_switch_tab('temp')` 等 legacy 调用仍工作且把「结果」页点亮

### Requirement: 2D/3D view toggle inside 结果
「结果」页 SHALL 提供 2D｜3D 段控：2D 态显示场卡（温度/速度/压力由字段段控选）、3D 态显示体渲染面板；不可用侧 SHALL 禁用（如 2D 求解后 3D 段禁用）；计算完成的自动跳页 SHALL 落到对应视图态。

#### Scenario: Mode routing preserved
- **WHEN** 3D 求解完成（run_controller 自动 `_switch_tab('3d')`）
- **THEN** 结果页激活且段控处于 3D 态

### Requirement: Always-on diagnostics sidebar
「结果」页右侧 SHALL 常显 298px 侧栏：本次结果 KPI（与既有 `_res_chips` 数据同源）、可信度卡（能量闭合 %、包络有效性、外推计数——各带 ✓/⚠ 语义色）、收敛卡（残差历史火花线 + 外循环数 + 耗时 + 「诊断详情」按钮）；无结果或非结果页 SHALL 隐藏；顶部 KPI 横带 SHALL 退役。

#### Scenario: Credibility visible with the field
- **WHEN** 任一次计算完成并处于结果页
- **THEN** 能量闭合百分比与包络状态与场图同屏可见

### Requirement: Diagnostics detail dialog
「诊断详情」SHALL 弹出对话框：能量对账三行、闭合系数（K_ff/h_v/Nu/DF 后端）、迭代计数、警告与外推清单，及「复制诊断摘要」（纯文本，可贴报告）。

#### Scenario: Copy summary
- **WHEN** 点击复制诊断摘要
- **THEN** 剪贴板含含 Q/ΔP/闭合%/包络/迭代/耗时/警告的文本块

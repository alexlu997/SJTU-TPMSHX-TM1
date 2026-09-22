# Spec: ui-cta-and-shortcuts

## Purpose
计算 CTA、空状态预设入口与键盘/页签快捷键层的行为约定。
## Requirements
### Requirement: Sticky always-visible Compute CTA
Compute 主按钮 SHALL 常驻左面板底部固定条（不随参数滚动消失）；SHALL 是与原顶栏按钮同一 widget 对象（`window.btn_compute`），ticker 状态机、Ctrl+R、信号连接 SHALL 零改动；顶栏 SHALL 不再出现 Compute 按钮。

#### Scenario: CTA visible regardless of scroll
- **WHEN** 左面板滚动到任意位置
- **THEN** btn_compute 可见（位于滚动区外的固定条）

#### Scenario: Ticker still owns the button
- **WHEN** 离屏驱动一次真实 2D compute
- **THEN** 计算期间按钮文本变为 Cancel 计时样式，结束后恢复

### Requirement: Empty-state preset shortcut
空状态 SHALL 含"载入算例工况"按钮，点击 SHALL 调用既有 `_load_named_preset('Shanghai (3D Gyroid)')`（内部键保留历史拼写，显示层经 `ui.fmt.preset_display` 去品牌化）；空状态整体（文案+按钮）SHALL 在首次计算后隐藏（现行为保持）。

#### Scenario: One-click runnable config
- **WHEN** 点击空状态 preset 按钮
- **THEN** 输入字段被算例工况预设改写（`_active_preset_name` 置位）

### Requirement: Result summary
结果摘要 SHALL 显示当前已接受结果的 Q、ΔP_A、ΔP_B 和出口温度，使用一致的标签、单位及数值层级；不依赖隐藏的旧 KPI chip 或 delta 徽标。

#### Scenario: Hierarchy present
- **WHEN** 完成计算后显示结果摘要
- **THEN** 数值和单位来自本次结果，未收敛和诊断状态保持可见

### Requirement: Workbench-aligned tab shortcuts
键盘层 SHALL 与可见三页签工作台一致：Ctrl+1 → 几何布局，Ctrl+2 → 结果（经 `_result_view` 解析到 2D 场/3D），Ctrl+3 → 优化，Ctrl+4 → 结果页内 2D|3D 切换（无结果侧可切时为 no-op）。退役的 Ctrl+5 与直达 temp/pres/vel 的绑定 SHALL NOT 存在。`_cycle_tab`（Ctrl+↑/↓）SHALL 按 ('layout','result','pareto') 走，当前页签属结果家族（temp/pres/vel/3d）时视为 'result'。

#### Scenario: Ctrl+3 reaches 优化 without results
- **WHEN** 无任何计算结果，按 Ctrl+3
- **THEN** 优化页签激活（pareto 始终可用）

#### Scenario: Cycle skips hidden legacy views
- **WHEN** 当前在温度视图（结果家族），按 Ctrl+↓
- **THEN** 激活 pareto（不落在隐藏的 pres/vel 按钮上）

### Requirement: Shortcut docs and palette match visible chrome
快捷键速查表 SHALL 只列可见页签（几何布局/结果/优化 + 2D|3D 切换），SHALL NOT 列退役的 Temperature/Pressure/Velocity/3D View 行。命令面板页签词条 SHALL 用中文标签（保留英文关键词供搜索）。字段右键菜单 SHALL 用「恢复算例工况默认值」，状态栏消息同理（Shanghai 品牌词不出现在任何可见 UI 字符串）。页签 tooltip SHALL 全中文。

#### Scenario: Cheat sheet has no retired rows
- **WHEN** 打开快捷键速查（Ctrl+?）
- **THEN** 行含「几何布局/结果/优化」，不含 "Tab — Temperature"

#### Scenario: Field context menu de-branded
- **WHEN** 在任一参数输入框右键
- **THEN** 动作文本为「恢复算例工况默认值」，无 "Shanghai"

### Requirement: Workbench state persists across sessions
`_save_session` payload SHALL 含 `ui_state`：`active_tab`（结果家族存解析前的家族键）、`left_collapsed`（左栏折叠布尔）、`result_view`（'2d'|'3d'）。`_restore_session` SHALL 尽力恢复：先 `result_view`，再左栏折叠，最后 `active_tab`（若该页签被门控不可用，回落 layout —— 沿用 `_switch_tab` 既有回落，不新增逻辑）。缺失/损坏键 SHALL 静默跳过（与既有会话恢复同风格）。

#### Scenario: Reopen lands on the saved tab
- **WHEN** 用户在优化页关闭应用后重开
- **THEN** 优化页激活

#### Scenario: Saved result tab without results falls back
- **WHEN** 上次会话停在结果页，但新会话尚无结果
- **THEN** 回落 layout，不报错

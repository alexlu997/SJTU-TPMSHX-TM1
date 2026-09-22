# Spec: ui-layout-hygiene

## Purpose
左面板布局卫生（无横向滚动、响应式流体卡、结构化空状态）与纯布局变更的行为约束。
## Requirements
### Requirement: Parameter cards never scroll horizontally
面板宽 ≥360px 时，左侧几何／边界／求解页共用的外层 QScrollArea SHALL 无横向滚动（策略 AlwaysOff），行标签 SHALL 折行而非撑宽网格；输入控件 SHALL 完整可见。

#### Scenario: No horizontal scrollbar at default window size
- **WHEN** 1600×1000 离屏构造 Main_Menu
- **THEN** 可见参数滚动区域 `horizontalScrollBar().maximum() == 0`

### Requirement: Fluid A/B cards stack responsively
流体 A/B 卡 SHALL 置于 `ResponsiveRow`：可用宽 <640px 时竖排、≥640px 并排（实测默认窗宽下该行仅得 521px，520 阈值擦线导致并排挤压）；两种状态下均无裁切。

#### Scenario: Direction flips with width
- **WHEN** ResponsiveRow resize 到 400px / 800px
- **THEN** 布局方向分别为 TopToBottom / LeftToRight

### Requirement: Structured empty state
画布空状态 SHALL 提供三步引导（填参数 → 计算（含快捷键）→ 查看场图），文案动词开头、主题令牌取色。合法初始配置 SHALL 自动预览几何并隐藏空状态；已有几何或结果时 SHALL 不覆盖当前画布。

#### Scenario: Geometry preview replaces the initial empty state
- **WHEN** 使用合法初始配置构造窗口且尚未求解
- **THEN** 几何预览可见，`_empty_state_label` 隐藏但保留三步引导和载入预设入口

### Requirement: Layout preserves compute behavior
纯布局修改 SHALL 保留信号连接、字段默认值与求解语义；离屏 UI pytest 与全量 pytest SHALL 全绿。

#### Scenario: UI suite green
- **WHEN** 运行离屏 UI pytest 与 `test_ui_layout_hygiene.py`
- **THEN** 0 failed

### Requirement: Main_Menu UI ownership
`Main_Menu` 的快捷键、IO 动作与 ResultCache 属性桥分别由
`ui/mixins/shortcuts.py`、`io_actions.py`、`result_bridge.py` 维护。
底部结果摘要在 `ui/builders_sidebar.py`，`builders_canvas` 保留其现有导出。
画布和 3D 面板的组装按当前[架构说明](../../../docs/architecture.md#ui-structure)
组织；旧拆分方案的逐字迁移和“不拆分”决定属于历史，不限制后续已验证的维护。

#### Scenario: Window constructs with the extended MRO
- **WHEN** 离屏构造 Main_Menu（test_main_smoke）
- **THEN** 构造成功，快捷键/属性桥行为与拆分前一致（hygiene 锁全绿）

#### Scenario: Sidebar import surface unchanged
- **WHEN** 通过 `sjtu_tpmshx.ui.builders_canvas` 导入 `refresh_result_sidebar`
- **THEN** import 成功并解析到迁移后的实现

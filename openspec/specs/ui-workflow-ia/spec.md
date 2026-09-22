# Spec: ui-workflow-ia

## Purpose
左侧工况参数按几何、边界、求解分页；各页复用同一批输入控件和校验。

## Requirements

### Requirement: Three parameter pages
左侧 SHALL 提供“几何／边界／求解”三页。几何页包含“几何与结构”；边界页包含“流体”和“进出口边界”；求解页包含“网格与求解器”。页内仍可折叠分组；前三个分组默认展开，“进出口边界”默认折叠。切页 SHALL 保留输入与各页滚动位置，现有维度可见性门和求解语义不变。

#### Scenario: Default page and group states
- **WHEN** 离屏构造 Main_Menu
- **THEN** 默认显示几何页，三个页签存在；几何、流体、网格分组的展开状态为 True，进出口边界为 False

#### Scenario: Dimension gate survives navigation
- **WHEN** 选择 3D 并进入求解页
- **THEN** Nz 行可见；切回 2D 后不可见，其他页输入保留

### Requirement: One shared parameter scroll area
三页 SHALL 共用一个外层 QScrollArea，不嵌套页级滚动壳。开始计算与诊断入口 SHALL 位于固定底栏；参数栏收起后 SHALL 提供展开及诊断入口。

#### Scenario: Reach diagnostics in either sidebar state
- **WHEN** 参数栏展开或收起
- **THEN** 两种状态都能打开同一个诊断详情

### Requirement: Computed geometry is an ordinary section
TPMS 的 ε/A₀/D_h/K_ss SHALL 使用与几何页其他板块一致的常显分区，不单独折叠。未计算时显示空值；`compute_tpms` 成功后就地更新。

#### Scenario: Geometry values remain visible
- **WHEN** 显示几何页并执行合法的 TPMS 几何计算
- **THEN** 计算前后该分区均可见，计算后 `_v_eps` 显示数值

### Requirement: Gates
离屏 UI pytest（含布局卫生测试）与全量 pytest SHALL 0 failed；截图检查 SHALL 覆盖三页布局、分组展开和参数栏收起；CI SHALL 绿。

#### Scenario: Suite green
- **WHEN** 全量 pytest
- **THEN** 0 failed

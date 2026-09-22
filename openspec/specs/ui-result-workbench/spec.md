# Spec: ui-result-workbench

## Purpose
结果工作台：主导航、场图／三维切换、可收起的底部摘要及诊断详情。

## Requirements

### Requirement: Workbench navigation and quick design
顶部 SHALL 提供“工况设置／场图结果／优化设计”三个工作台入口，以及独立的“快速设计”入口。温度、压力、速度和三维内部路由由 `ui/mixins/tab_view.py` 解析，不依赖隐藏按钮对象；有受支持结果时 SHALL 启用“场图结果”。

#### Scenario: Field routing preserves result navigation
- **WHEN** 计算完成后调用 `_switch_tab('temp')` 等字段路由
- **THEN** “场图结果”入口激活并显示对应字段

### Requirement: Field and volume views
结果页 SHALL 提供“场图／三维”段控：场图态选择温度、速度或压力及相位；三维态显示体渲染面板。段控只改变显示方式，不改变计算维度。不可用侧 SHALL 禁用，例如二维计算后的三维视图；三维计算完成后仅在面板成功接收结果时进入三维态。

#### Scenario: Unavailable volume does not imply failed field results
- **WHEN** 三维数据存在但体渲染面板不可用
- **THEN** 保留可用场图并报告视图状态，不把未就绪的三维视图显示为可用

### Requirement: Collapsible result summary below the field
结果摘要 SHALL 位于画布下方，显示本次结果 Q、两侧压降、出口温度及能量闭合、包络、外推、迭代和耗时等已有诊断。无数据项显示缺失，不填造值。“摘要”按钮 SHALL 收起或恢复该区域，切换结果页时保留用户选择；无结果或非结果页隐藏。主界面 SHALL 不展示实时残差曲线或无数据残差占位，求解器收敛与守恒检查仍保留。

#### Scenario: Summary toggle preserves values
- **WHEN** 收起摘要、切换页面后返回结果
- **THEN** 摘要保持收起，恢复后数值仍属于本次已发布结果

### Requirement: Diagnostics detail dialog
“诊断详情” SHALL 展示当前结果已有的能量对账、闭合参数、迭代、警告与外推清单，并提供“复制诊断摘要”。缺失信息不得冒充验收通过。

#### Scenario: Copy summary
- **WHEN** 点击复制诊断摘要
- **THEN** 剪贴板包含当前结果的 Q、压降、闭合、包络、迭代、耗时与警告文本

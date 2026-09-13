# Spec: ui-design-tokens

## Purpose
设计令牌纪律：圆角/色值单一来源于 theme.py，锁测试禁散落 hex 与私设半径。（结构修复 2026-07-03：补 Purpose 头，内容不变。）

## Requirements

### Requirement: Shared control radii
常规输入、按钮和卡片 SHALL 使用 `theme.py` 的 6px 令牌
`RADIUS_INPUT` / `RADIUS_BTN` / `RADIUS_CARD`。滑块、复选框、滚动条、
进度条及语义胶囊按控件尺寸设置圆角；现有例外由布局卫生测试界定。
已删除的 `RADIUS_TAB` 不再作为实现要求。

#### Scenario: No stray radii
- **WHEN** 运行 `test_ui_layout_hygiene.py` 的圆角检查
- **THEN** 常规控件没有未经允许的 8/10/12px 圆角；保留明确的微型控件及胶囊例外

### Requirement: No hex outside theme
普通 UI 色值 SHALL 经 theme token 获取；红色错误边框与搜索高亮也使用 token。
token 查找的 fallback、色图和特殊渲染例外由现有布局卫生测试明确限定。

#### Scenario: Light theme inherits fixes
- **WHEN** 切亮色主题
- **THEN** 使用 token 的控件取亮色值，无固定暗色残留

### Requirement: Type scale closed
常规字号 SHALL 使用 `theme.py` 的 FONT_* 层级（状态/次要按钮 9pt、
标签/输入 10pt、区块 11pt、主计算按钮 12pt），保留已有紧凑模式调整和展示位字号。

#### Scenario: 13pt eliminated
- **WHEN** grep `font-size:13pt`
- **THEN** 零命中

### Requirement: Numeric inputs right-aligned
`FieldFactory.line_edit` 产出的数值输入 SHALL 右对齐（等宽已有）——小数点/量级对齐可扫读。

#### Scenario: Alignment set
- **WHEN** 检查任一参数输入框
- **THEN** alignment 含 AlignRight

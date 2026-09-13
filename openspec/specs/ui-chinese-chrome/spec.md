# Spec: ui-chinese-chrome

## Purpose
UI 表面中文化约定：可见文案中文、内部路由键保持英文。（结构修复 2026-07-03：补 Purpose 头，内容不变。）

## Requirements

### Requirement: Chinese chrome, untouched physics labels
界面 chrome（顶栏按钮、画布页签、手风琴组名、区块标题、空状态、导出菜单、CTA、onboarding）SHALL 为中文；物理量行标签、单位、符号（ε、D_h、ΔP、Nu、K/°C）、内部信号/属性名/key SHALL 保持原样；快捷键（Ctrl+R 等）SHALL 不变。

#### Scenario: No mixed chrome on one screen
- **WHEN** 检查顶栏 + 页签 + 组名
- **THEN** 无英文 chrome 文案（WS: A、K/°C 等标识符除外）

#### Scenario: Internal keys stable
- **WHEN** `_resolve_2d_view_card` / `_switch_tab` 运行
- **THEN** 仍以原英文串作 key 解析（combo 条目未改值，仅不可见）

计算完成后的结果页路由由 [ui-result-workbench](../ui-result-workbench/spec.md)
统一说明；原提案的撤销记录保留在 Git 历史中。

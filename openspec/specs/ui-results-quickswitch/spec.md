# Spec: ui-results-quickswitch

[中文](spec.md) | [English](spec.en.md)

## Purpose
结果快速切换：2D 视图聚合按钮 + 场选择、分屏/分离路由兼容。（结构修复 2026-07-03：补 Purpose 头，内容不变。）

## Requirements

### Requirement: One-click 2D field switch
2D 视图工具条 SHALL 提供「温度｜速度｜压力」分段按钮，单击 SHALL 直接切换显示场；`combo_2d_field` SHALL 保留为隐藏状态源（内部英文 key 不变），热键/代码路径改动 combo 时按钮态 SHALL 反向同步；门控 SHALL 与原 combo 一致（无数据禁用）。

#### Scenario: Single click switches field
- **WHEN** 2D 结果就绪且用户点「压力」
- **THEN** 画布切到压力场，按钮态更新，combo 索引同步

#### Scenario: Reverse sync
- **WHEN** 代码路径调 `_switch_tab('vel')`
- **THEN** 「速度」按钮呈激活态

### Requirement: Copy current figure to clipboard
导出菜单 SHALL 含「复制当前图像」，点击 SHALL 将当前激活画布图像放入系统剪贴板；无可复制画布时 SHALL 状态栏提示且不抛异常。

#### Scenario: Copy after compute
- **WHEN** 计算完成、任一场图激活、用户点复制
- **THEN** 剪贴板含该图像（QImage 非空）

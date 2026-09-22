# Spec: ui-group-badges

## Purpose
左面板分组徽标：必填缺失计数、防抖校验驱动、折叠存活。（结构修复 2026-07-03：补 Purpose 头，内容不变。）

## Requirements

### Requirement: Group-title invalid-field badges
各参数页内的分组标题 SHALL 在组内存在无效或空的会话字段时显示 `⚠N` 徽标（N = 计数）；判据 SHALL 与 preflight 一致（`inpError=='true'` 或空文本）；被当前维度可见性门隐藏的字段 SHALL 不计，单纯切页或折叠不清除计数；N=0 时 SHALL 无徽标。

#### Scenario: Hidden problem surfaces through collapse
- **WHEN** 折叠组内某字段被清空
- **THEN** 该组标题出现 `⚠N`（无需展开）

#### Scenario: Badge clears on fix
- **WHEN** 字段恢复有效值
- **THEN** 徽标在去抖窗口后消失

#### Scenario: Toggle preserves badge
- **WHEN** 带徽标的组被展开/折叠
- **THEN** 标题重渲染仍含徽标（chevron 与徽标同一渲染函数）

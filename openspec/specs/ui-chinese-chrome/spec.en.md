# Spec: ui-chinese-chrome

[中文](spec.md) | [English](spec.en.md)

## Purpose
Visible UI text uses Chinese. Internal route keys stay English. The structural repair on 2026-07-03 added the Purpose heading without changing the content.

## Requirements

### Requirement: Chinese chrome, untouched physics labels
Interface text MUST use Chinese for top-bar buttons, canvas tabs, accordion groups, section titles, empty states, export menus, primary actions, and onboarding. Physical labels, units, and symbols MUST stay unchanged. Examples include ε, D_h, ΔP, Nu, and K/°C. Internal signal names, property names, and keys MUST stay unchanged. Keyboard shortcuts such as Ctrl+R MUST stay unchanged.

#### Scenario: No mixed chrome on one screen
- **WHEN** the top bar, tabs, and group names are inspected
- **THEN** they contain no English interface text, except identifiers such as WS: A and K/°C

#### Scenario: Internal keys stable
- **WHEN** `_resolve_2d_view_card` or `_switch_tab` runs
- **THEN** it resolves the original English keys. Combo item values are unchanged. The items are only hidden.

[ui-result-workbench](../ui-result-workbench/spec.en.md) defines result routing after computation. Git history keeps the withdrawal record for the original proposal.

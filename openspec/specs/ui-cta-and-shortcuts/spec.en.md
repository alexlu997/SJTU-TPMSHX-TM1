# Spec: ui-cta-and-shortcuts

[中文](spec.md) | [English](spec.en.md)

## Purpose
Define Compute, empty-state preset access, and keyboard/tab shortcut behavior.

## Requirements

### Requirement: Sticky always-visible Compute CTA
The main Compute button MUST stay in the fixed bottom bar of the left rail. Parameter scrolling MUST NOT hide it. It MUST stay the original top-bar widget object, `window.btn_compute`. The ticker state machine, Ctrl+R, and signal connections MUST stay unchanged. The top bar MUST no longer contain Compute.

#### Scenario: CTA visible regardless of scroll
- **WHEN** the left rail scrolls to any position
- **THEN** btn_compute stays visible in the fixed bar outside the scroll area

#### Scenario: Ticker still owns the button
- **WHEN** a real 2D computation runs offscreen
- **THEN** the button shows Cancel with elapsed time during computation and returns to its initial state afterward

### Requirement: Empty-state preset shortcut
The empty state MUST contain Load Example Case. It MUST call the existing `_load_named_preset('Shanghai (3D Gyroid)')`. The internal key keeps its historical spelling. `ui.fmt.preset_display` removes the brand name from visible text. The complete empty state, including text and button, MUST disappear after the first computation, as before.

#### Scenario: One-click runnable config
- **WHEN** the user selects the empty-state preset button
- **THEN** the example preset updates input fields and sets `_active_preset_name`

### Requirement: Result summary
The summary MUST show Q, ΔP_A, ΔP_B, and outlet temperatures from the current accepted result. Labels, units, and numerical hierarchy MUST be consistent. It MUST NOT depend on hidden former KPI chips or delta badges.

#### Scenario: Hierarchy present
- **WHEN** the result summary appears after computation
- **THEN** values and units come from this result. Nonconvergence and diagnostic states stay visible.

### Requirement: Workbench-aligned tab shortcuts
Keyboard navigation MUST match the three visible workbench tabs. Ctrl+1 selects Geometry Layout. Ctrl+2 selects Results through `_result_view`, which resolves the 2D field or 3D view. Ctrl+3 selects Optimization. Ctrl+4 switches 2D|3D within Results and does nothing if no other result mode is available. Retired Ctrl+5 and direct temp/pres/vel bindings MUST NOT exist. `_cycle_tab`, bound to Ctrl+↑/↓, MUST follow ('layout','result','pareto'). A current temp/pres/vel/3d tab MUST count as 'result'.

#### Scenario: Ctrl+3 reaches 优化 without results
- **WHEN** no computation results exist and the user presses Ctrl+3
- **THEN** Optimization becomes active. Pareto is always available

#### Scenario: Cycle skips hidden legacy views
- **WHEN** Temperature is active and the user presses Ctrl+↓
- **THEN** pareto becomes active, without visiting hidden pres/vel buttons

### Requirement: Shortcut docs and palette match visible chrome
The shortcut reference MUST list only Geometry Layout, Results, Optimization, and 2D|3D switching. It MUST NOT list retired Temperature, Pressure, Velocity, or 3D View rows. Command-palette tab entries MUST use Chinese labels and keep English search keywords. Field context menus MUST say “恢复算例工况默认值”. Status messages MUST use equivalent wording. No visible UI string MUST contain the Shanghai brand name. Tab tooltips MUST use Chinese throughout.

#### Scenario: Cheat sheet has no retired rows
- **WHEN** the user opens the shortcut reference with Ctrl+?
- **THEN** it contains “几何布局/结果/优化” and no “Tab — Temperature” row

#### Scenario: Field context menu de-branded
- **WHEN** the user opens a parameter input's context menu
- **THEN** the action text is “恢复算例工况默认值” without “Shanghai”

### Requirement: Workbench state persists across sessions
The `_save_session` payload MUST contain `ui_state` with `active_tab`, `left_collapsed`, and `result_view`. Result tabs store their family key before resolution. `left_collapsed` is Boolean. `result_view` is '2d' or '3d'. `_restore_session` MUST restore available state in this order: result_view, left rail collapse, then active_tab. If a gate blocks the saved tab, existing `_switch_tab` behavior falls back to layout. No new fallback logic is required. Missing or damaged keys MUST be skipped silently, consistent with existing session restoration.

#### Scenario: Reopen lands on the saved tab
- **WHEN** the user closes the application on Optimization and opens it again
- **THEN** Optimization is active

#### Scenario: Saved result tab without results falls back
- **WHEN** the previous session ended on Results but the new session has no results
- **THEN** the application selects layout without an error

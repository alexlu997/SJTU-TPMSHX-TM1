# Spec: ui-layout-hygiene

[中文](spec.md) | [English](spec.en.md)

## Purpose
Define left-rail layout requirements: no horizontal scrolling, responsive fluid cards, and a structured empty state. Layout changes must keep behavior.

## Requirements

### Requirement: Parameter cards never scroll horizontally
At panel widths ≥360px, the shared Geometry/Boundary/Solver QScrollArea MUST have horizontal scrolling disabled with AlwaysOff. Row labels MUST wrap instead of widening the grid. Input widgets MUST stay fully visible.

#### Scenario: No horizontal scrollbar at default window size
- **WHEN** Main_Menu is constructed offscreen at 1600×1000
- **THEN** the visible parameter scroll area's `horizontalScrollBar().maximum() == 0`

### Requirement: Fluid A/B cards stack responsively
Fluid A/B cards MUST use `ResponsiveRow`. They stack vertically below 640px and sit side by side at ≥640px. The measured default row width is only 521px. A 520px threshold caused cramped side-by-side cards. Neither layout MUST clip content.

#### Scenario: Direction flips with width
- **WHEN** ResponsiveRow resizes to 400px / 800px
- **THEN** the directions are TopToBottom / LeftToRight respectively

### Requirement: Structured empty state
The canvas empty state MUST give three steps: enter parameters, compute with the shortcut, then inspect fields. Instructions MUST start with verbs and use theme colors. A valid initial configuration MUST automatically preview geometry and hide the empty state. Existing geometry or results MUST NOT be covered.

#### Scenario: Geometry preview replaces the initial empty state
- **WHEN** a window is constructed with valid initial settings before any solve
- **THEN** geometry is visible and `_empty_state_label` is hidden. Its three-step guidance and preset control stay available for the empty state.

### Requirement: Layout preserves compute behavior
Layout-only changes MUST keep signal connections, default field values, and solver behavior. Offscreen UI pytest and the full pytest suite MUST pass.

#### Scenario: UI suite green
- **WHEN** offscreen UI pytest and `test_ui_layout_hygiene.py` run
- **THEN** there are 0 failures

### Requirement: Main_Menu UI ownership
`ui/mixins/shortcuts.py` owns Main_Menu shortcuts. `io_actions.py` owns its IO actions. Field charts and exports read `ResultCache` directly without previous attribute bridges. Pareto images depend on their own canvas and optimization results, independently of the single-case field cache. `ui/builders_sidebar.py` owns the bottom summary and reads the current published scalar result. Consumers import directly from the owning module. Former compatibility re-exports are not maintained.

Canvas and 3D panel assembly follow the current [architecture](../../../docs/architecture.md#ui-structure). Earlier literal migration plans and decisions against splitting are historical. They do not restrict subsequent maintenance that passes its checks.

#### Scenario: Window constructs with the extended MRO
- **WHEN** Main_Menu is constructed offscreen by test_main_smoke
- **THEN** construction succeeds. Shortcuts, result display, and exports use the current published result.

#### Scenario: Sidebar uses the published result
- **WHEN** the bottom summary refreshes after computation
- **THEN** `builders_sidebar.refresh_result_sidebar` uses the current scalar snapshot. Its units match exports.

# Spec: ui-workflow-ia

[中文](spec.md) | [English](spec.en.md)

## Purpose
The left parameter rail has Geometry, Boundary, and Solver pages. These pages share the existing input widgets and validation.

## Requirements

### Requirement: Three parameter pages
The left rail MUST have three pages: Geometry, Boundary, and Solver. Geometry contains the geometry and structure group. Boundary contains the fluid and inlet/outlet boundary groups. Solver contains the grid and solver group. Groups can still collapse. The geometry, fluid, and grid groups start expanded. The inlet/outlet boundary group starts collapsed. Page changes MUST keep input values and each page's scroll position. Existing dimension visibility gates and solver behavior stay unchanged.

#### Scenario: Default page and group states
- **WHEN** Main_Menu is constructed offscreen
- **THEN** Geometry is active and all three page tabs exist. Geometry, fluid, and grid expansion states are True. Inlet/outlet boundary expansion is False.

#### Scenario: Dimension gate survives navigation
- **WHEN** the user selects 3D and opens Solver
- **THEN** the Nz row is visible. It becomes hidden after selection of 2D. Inputs on other pages stay unchanged.

### Requirement: One shared parameter scroll area
The three pages MUST share one outer QScrollArea. Pages MUST NOT have nested scroll containers. Compute and diagnostics controls MUST be in a fixed bottom bar. The collapsed rail MUST give expand and diagnostics controls.

#### Scenario: Reach diagnostics in either sidebar state
- **WHEN** the parameter rail is expanded or collapsed
- **THEN** both states can open the same diagnostics details

### Requirement: Computed geometry is an ordinary section
TPMS ε/A₀/D_h/K_ss MUST use an always-visible section that matches the other Geometry sections. It MUST NOT collapse separately. Values are empty before calculation. A successful `compute_tpms` updates them in place.

#### Scenario: Geometry values remain visible
- **WHEN** Geometry is visible and a valid TPMS geometry calculation runs
- **THEN** the section stays visible before and after calculation. After calculation, `_v_eps` shows a number.

### Requirement: Gates
Offscreen UI pytest, including layout hygiene tests, and the full pytest suite MUST have 0 failures. Screenshot checks MUST cover all three pages, expanded groups, and the collapsed rail. CI MUST pass.

#### Scenario: Suite green
- **WHEN** the full pytest suite runs
- **THEN** there are 0 failures

# Spec: ui-result-workbench

[中文](spec.md) | [English](spec.en.md)

## Purpose
The result workbench gives primary navigation, field/volume selection, a collapsible summary below the canvas, and diagnostics details.

## Requirements

### Requirement: Workbench navigation and quick design
The top bar MUST give Case Setup, Field Results, and Optimization workbench entries. It MUST also give a separate Quick Design entry. `ui/mixins/tab_view.py` resolves internal temperature, pressure, velocity, and 3D routes. These routes MUST NOT depend on hidden button objects. Field Results MUST become available when supported results exist.

#### Scenario: Field routing preserves result navigation
- **WHEN** a field route such as `_switch_tab('temp')` runs after computation
- **THEN** Field Results becomes active and shows the specified field

### Requirement: Field and volume views
The results page MUST give a Field/Volume segmented control. Field mode selects temperature, velocity, or pressure and a phase. Volume mode shows the volume rendering panel. This control changes only the view, not the computation dimension. Unavailable modes MUST be disabled, such as volume mode after a 2D computation. After a 3D computation, volume mode opens only when the panel successfully receives the result.

#### Scenario: Unavailable volume does not imply failed field results
- **WHEN** 3D data exists but the volume rendering panel is unavailable
- **THEN** available field plots stay accessible. The UI reports the view state and does not present an unready volume view as available.

### Requirement: Collapsible result summary below the field
The summary MUST appear below the canvas. It shows the current result's Q, both pressure drops, outlet temperatures, and existing diagnostics. These include energy closure, envelope status, extrapolation, iterations, and elapsed time. Missing data MUST be shown as missing, without invented values. Summary MUST collapse or restore this area. Page changes MUST keep that choice. The area is hidden without results or outside the results page. The main window MUST NOT show live residual curves or empty residual placeholders. Solver convergence and conservation checks stay active.

#### Scenario: Summary toggle preserves values
- **WHEN** the user collapses the summary, changes pages, and returns to results
- **THEN** the summary stays collapsed. Restored values still belong to the current published result.

### Requirement: Diagnostics detail dialog
Diagnostics Details MUST show available energy accounting, closure parameters, iterations, warnings, and extrapolation lists for the current result. It MUST give Copy Diagnostics Summary. Missing information MUST NOT imply successful acceptance.

#### Scenario: Copy summary
- **WHEN** the user selects Copy Diagnostics Summary
- **THEN** the clipboard contains the current result's Q, pressure drops, closure, envelope status, iterations, elapsed time, and warning text

# Spec: ui-optimize-wizard

[中文](spec.md) | [English](spec.en.md)

## Purpose
The optimization wizard has Configure, Run, and Results pages. Stage buttons select pages. Parameters are inline. Cancellation keeps samples.

## Requirements

### Requirement: Three-page wizard
Optimization MUST use a three-page QStackedWidget: Configure, Run, and Results. Stage indicators MUST allow page selection. `_set_stage_pill(key,'active')` MUST select the corresponding page. Existing engine transitions control navigation: start selects Run, completion selects Results, and errors select Configure.

#### Scenario: Engine drives pages
- **WHEN** `_set_stage_pill('running','active')` runs
- **THEN** the current stack page is 1, Run

### Requirement: Inline BO parameters
The configuration page MUST contain the optimization method and n_init/n_iter/q_batch/seed controls. Methods are qLogNEHVI, qLogNParEGO, and Sobol. The default n_init is 16. Its allowed range is 1–256. The optimizer MUST inherit numerical settings from the current computation configuration. Start MUST read the inline values without the former modal parameter dialog. The planned solve count MUST include the uniform baseline and each condition for each candidate. Remaining time MUST use only measured durations of completed samples from this run.

#### Scenario: Launch consumes inline values
- **WHEN** the user selects Start
- **THEN** inline spinbox values construct the worker, without a popup

### Requirement: Search space on page 1
The Search Space card MUST give continuous-field L/t ranges and show the current control grid. 2D uses 3×3 control points. 3D uses 3×3×3 independent control points. The current GUI applies no y-symmetry constraint. The single-case zone panel MUST occupy a separate collapsible card labeled as excluded from optimization search. The former zones|canvas splitter MUST be retired. Results MUST give Pareto Front, Size / Wall Thickness Field, and 3D Size / Wall Thickness Field tabs. Parameter-field tabs MUST be available when their corresponding field data exists.

#### Scenario: Zone panel relocated
- **WHEN** the configuration page is inspected
- **THEN** `_zone_panel` is in the single-case zone card. Optimization search space is separate, and Start is visible without scrolling.

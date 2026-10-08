# Spec: ui-design-tokens

[中文](spec.md) | [English](spec.en.md)

## Purpose
`theme.py` supplies shared control radii, colors, and font sizes.

## Requirements

### Requirement: Shared control radii
Shared inputs, buttons, and cards MUST use `theme.py` tokens: `RADIUS_INPUT=8`, `RADIUS_BTN=8`, and `RADIUS_CARD=12`, in px. Sliders, checkboxes, scrollbars, progress bars, and semantic capsules use radii suited to their size. Layout hygiene tests define existing exceptions. The removed `RADIUS_TAB` is no longer an implementation requirement.

#### Scenario: No stray radii
- **WHEN** the radius check in `test_ui_layout_hygiene.py` runs
- **THEN** new cards and controls get radii from tokens, without scattered 8/10/12px literals. Existing miniature-control and capsule exceptions stay.

### Requirement: No hex outside theme
Normal UI colors MUST come from theme tokens. Red error borders and search highlights also use tokens. Existing layout hygiene tests define exceptions for token lookup fallbacks, colormaps, and special rendering.

#### Scenario: Light theme inherits fixes
- **WHEN** the light theme is selected
- **THEN** controls use the light token values without fixed dark colors

### Requirement: Type scale closed
Shared font sizes MUST follow the `theme.py` FONT_* levels. Status uses 9pt. Labels and secondary buttons use 10pt. Inputs and sections use 11pt. The main Compute button uses 12pt. Existing density adjustments and display-specific sizes stay. Body text and inputs use regular weight. Headings, results, and primary actions use higher weights to distinguish hierarchy.

#### Scenario: 13pt eliminated
- **WHEN** the source is searched for `font-size:13pt`
- **THEN** there are no matches

### Requirement: Numeric inputs right-aligned
Numeric inputs from `FieldFactory.line_edit` MUST align right to support magnitude comparison. The interface MUST use system sans-serif fonts. macOS uses its system Latin font and PingFang. Windows uses Segoe UI and Microsoft YaHei. Linux uses available Noto Sans or system fallbacks. Charts and exported images keep their existing publication fonts independently. The UI MUST NOT depend on Office fonts. Proportional numerals MUST NOT be described as monospace.

#### Scenario: Alignment set
- **WHEN** a parameter input is inspected
- **THEN** its alignment contains AlignRight

### Requirement: Glass chrome and stable interaction
Navigation and a few floating elements MUST use shared gradients and thin borders for the glass appearance. Parameter and result areas keep solid backgrounds. Charts stay clear. Matplotlib/PyVista surfaces MUST NOT receive blur or continuous repaint effects. Hover and keyboard focus MUST keep content position and clear focus indication.

#### Scenario: Transient feedback
- **WHEN** a completion notice appears or a result highlight is triggered again
- **THEN** displacement and opacity change together. The hold phase stays still. Temporary effects are released afterward. An previous animation cannot clear a new effect.

#### Scenario: Form transitions
- **WHEN** the parameter page changes, the rail expands, or computation details expand
- **THEN** new content fades in from 0.72 opacity over 200 ms with OutCubic. Text stays clear. The effect is released afterward. Inputs and page indices take effect immediately. Repeated actions replace the previous animation. Same-page clicks, hidden-window initialization, and `QT_REDUCED_MOTION=1` do not start this animation.
- **AND** charts receive no blur. Rail width changes one time. Canvas switching commits in one repaint batch without processing another input between hiding and showing.
- **AND** the first window display plays the same fade one time on the visible parameter area. The effect is initialized beforehand. Later displays do not repeat it or change groups or values.

#### Scenario: High refresh displays
- **WHEN** a visible window animates parameters, notices, highlights, or preset 3D views
- **THEN** an independent 8 ms precise timer uses actual elapsed time. Late frames do not create a backlog. Cancellation or destruction stops the driver. Static notice holds suspend frequent wakeups. Timer intervals do not show the displayed frame rate.
- **AND** high-refresh acceptance records window scale, display refresh rate, drawing intervals, and first-response latency. Timer callbacks and offscreen tests do not replace displayed frame-rate evidence.
- **AND** 3D mouse rotation and preset transitions use VTK's native interaction budget. They adaptively reduce volume sampling detail during motion. After motion, they restore the original static budget and redraw. Computation fields and complete result exports stay unchanged. Mouse dragging cancels an previous preset transition. Hidden or closed views do not request more rendering.

### Requirement: Workbench parameter rail and canvas focus
The workbench MUST place parameters on the left and the canvas on the right. Computation status and result summary MUST appear below the canvas. The parameter rail allows width adjustment. Its title control or `Ctrl+\` collapses it to an icon rail with Geometry, Boundary, and Solver entries. Expansion MUST reuse the original widgets. It keeps values, active group, scroll position, and the previous expanded width. Focus and `F` MUST affect the current canvas. They temporarily hide parameters and the result summary. Exit restores the previous expansion states. Rail collapse and focus mode MUST keep the computation status card's Cancel control.

#### Scenario: Inspect results while editing the next case
- **WHEN** the user computes, collapses parameters, switches focus mode, expands parameters, and edits the next configuration
- **THEN** the run still uses its start-time input snapshot. Draft edits do not change result provenance or exports.

### Requirement: Truthful expandable compute status
The status card MUST reuse existing time and iteration callbacks. Expansion gives current diagnostics and log access. It MUST NOT show live A/B residual plots or empty residual placeholders. It MUST NOT invent progress or remaining time. After cancellation, it shows that the current computation step must finish. Terminal states distinguish completion, notices, nonconvergence, failure, and cancellation. If the solver finishes but the 3D view is unavailable, the card shows a notice. Existing results stay exportable. The complete run log becomes available only after computation finishes and captured content exists. A new computation clears the previous card contents.

#### Scenario: A terminal callback is not a validation verdict
- **WHEN** finished arrives but `ComputeResult.converged` is false or the result contains notices
- **THEN** the card keeps the nonconverged or notice state. Normal-completion styling MUST NOT hide it.

### Requirement: Scalable consistent icons
Workbench navigation and common actions MUST use the shared SVG icon entry point. Visual sizes and theme colors MUST be consistent. Rendering MUST use the target device pixel ratio. Icon-only buttons MUST have accessible names or clear tooltips. Critical actions keep text.

#### Scenario: Device scale changes
- **WHEN** the same icon is drawn at different device pixel ratios
- **THEN** its vector resource is rendered at the target scale, without enlarging a fixed low-resolution bitmap

# Use the graphical interface

[中文](gui-guide.md) · [English](gui-guide.en.md) · [Project home](../README.en.md)

## Load a case, run it and view results

1. Start `sjtu_tpmshx.main`. Select Load in the left navigation rail to choose a preset or file. Press `Ctrl+\` to expand the 232 px navigation rail for workspaces and recent runs. The right push inspector drawer shows Geometry, Boundary, and Solver tabs on the Case page. Toggle it with the header control or `Ctrl+]`; each page remembers its own open state and selected tab.
   For 3D, each inlet can prescribe velocity or total mass flow in kg/s.
   In mass-flow mode, velocity is read-only and shows its last resolved value.
   Auto-fill or the next compute resolves it from current inlet state,
   porosity, and actual openings. Geometry edits keep the prescribed kg/s.
   The 2D interface keeps velocity inputs. Imported optimization conditions
   independently prescribe each condition's total flows.
   Port coordinates display in mm and inlet pressures display in kPa when unfocused, and show exact m / Pa values while editing; explicit units such as `21 mm` convert to `0.021 m`.
   An inlet flow accepts `g/s` or `kg/s`. Solid conductivity accepts `W/(m·K)`.
   Press Enter to convert an input to the field unit.
2. Select Start Compute in the header, or press `Ctrl+R`. The status card below the canvas shows elapsed time. Expand Details for actual solver iterations and notices. Its separate Cancel control stays available when the inspector is closed.

Cancellation waits for the current native computation step. 3D coarse-grid initialization also responds.
There is no forced thread termination or fixed cancellation delay. The card does not predict remaining time.

   The main window shows neither live residual curves nor empty placeholders. Solvers still execute and record convergence/conservation checks. Terminal states distinguish completion, notices, nonconvergence, failure, and cancellation. Captured complete logs become available through Computation Log afterward. Nonconvergence or an unavailable 3D view is not styled as normal success.
3. Open Results (`Ctrl+2`) after computation. Select temperature, velocity, or pressure, choose Fluid A, Fluid B, Solid, or All, and adjust colormaps from Colormap. Move the z-slice slider for 3D fields.

   Field/3D (`Ctrl+4`) changes display mode only. Case parameters determine computation dimension. Press `Ctrl+5` to open Quick Design.

   The first 3D view prepares its modules while the interface remains responsive. Result display and optimization previews share this preparation.
   Compute controls stay locked until result display finishes. Closing waits for preparation to finish.
   Font setup, widget creation, and drawing can still cause a short pause on first use.

   The bottom readout strip shows duty, both pressure drops, outlet temperatures, and extrapolation notices. Summary toggles the strip. The Result drawer shows status, checks, click-sampled per-point three-phase readouts, and canvas actions. Open diagnostics from the header run-info badge, the Result drawer, or rail Settings → Diagnostics. Focus or `F` hides the inspector and bottom strip to enlarge the current canvas. Toggle again to restore previous states.

   Editing the next configuration keeps current-result provenance and units, and flags the bottom strip with an edited-inputs badge. Displayable values do not show acceptance.
4. Select Save in the left rail to store configuration. Select Export to store results or the current image. 2D results use CSV. 3D results use CSV plus field NPZ. Phase/slice choices affect display and image export only.

   The 3D NPZ stores available complete XYZ temperatures. It also stores both sides' three velocity components and magnitudes in m/s, and display `P_fA/P_fB` in Pa. Other arrays are `L_mm/t_mm` in mm and `dx/dy/dz` in m. Previous A-side `vmag/P_kPa` keys stay. Display pressure uses the current result's reference.

   `results.h5` keeps complete native thermal states and flux evidence. GUI sessions keep interface state. Formal module handoff uses `case.yaml` with HDF5 and `results.h5`. These serve different purposes. The command palette's Copy Inputs as Python Code uses the same complete case snapshot. It includes temperature scale, fluids/boundaries, zones, and model parameters.

   Execute it in a Python session with an existing `window` to restore inputs. The snippet neither starts a solve nor acts as a CLI ComputeConfig file.

Existing sessions restore custom fluids, directions, grids, and ports without Shanghai defaults overwriting them. Shanghai defaults apply only at first startup, in workspaces without saved sessions, or after explicit reset/preset loading. Each workspace saves its own zone axis, zone table, and continuous controls. Previous sessions without this data clear and disable zones. If the original enabled zones, a notice requests reconfiguration to prevent reuse of another workspace's zones.

Shanghai presets use the recorded flows and full temperature/pressure values of April 1 Gyroid case 8.
The 3D preset specifies total mass flow. Preparation calculates speed from the actual inlet pore area.
The 2D preset uses the corresponding speed at the 42 mm specimen depth.
Temperature-unit changes do not round inputs to two decimal places.
See the [preset input table](data-catalog.en.md#shanghai-case8-recorded-inputs) for sources, conversions and material assumptions.
Saved sessions keep their inputs. Load the Shanghai preset explicitly to use the corrected baseline.
The Diamond Shanghai preset had no corresponding experimental record and was removed. Manual Diamond models and saved configurations remain supported.

Startup displays all temperature inputs in K. The conversion keeps their physical temperatures.

Parameter-page changes, rail expansion, and computation-detail expansion use an approximately 200 ms fade. Text stays clear. Repeated actions replace previous animation, and inputs stay editable. First window display also fades the parameter area one time. Effects are initialized beforehand to reduce first-navigation delay.

UI animation and preset 3D views use independent precise timers for high-refresh interaction. Slow frames advance by actual elapsed time without a backlog. Actual 3D frame rate also depends on rendering load. Rotation and view transitions can reduce volume sampling detail adaptively. Static quality returns after motion.

This affects interactive display only. Computation fields and complete exports stay unchanged. Set the saved `reduced_motion` preference or `QT_REDUCED_MOTION=1` to disable these transitions and 3D view animations.

After computation, the visible field is drawn first. Other plots are generated and cached on first display or export. Phase/slice changes update the visible plot. New results clear previous plot caches. High-resolution 3D volumes are likewise generated per field on demand.

Original fields, static quality, and shared color scales stay. Ordinary solve notices stay in the status card and Diagnostics Details, without synchronous dialogs blocking results.

Diagnostics Details reports preparation, solve, postprocessing, and display times. Successful total time includes background work and result display. Compare terminal and GUI speed with matched configuration, threads, and cache state. Separate native builds and property-table initialization from later runs. Daily execution does not compile the solver.

More selects dark/light themes, effective after restart, and K/°C. The interface and on-screen charts use system sans-serif fonts: macOS system Latin/PingFang, Windows Segoe UI/Microsoft YaHei, and available Linux Noto Sans/system fallbacks. Body text and inputs use regular weight. Headings and primary actions use emphasis. Exported figures (PNG, SVG, and PDF) apply Times New Roman for Latin text, math, and ticks with Microsoft YaHei / PingFang Chinese fallback at export time, while keeping the color scales and layout consistent. macOS can register matching installed Office fonts in the current process without copying or distributing them.

Missing export fonts produce a notice and use available fonts. Interface and on-screen chart fonts are unaffected.

<a id="settings"></a>

## Grid, fluid and solver settings

For ordinary computation, set threads under Solver → Compute Resources. Grid settings select regular or port/wall refinement. Refined input counts include all refined cells. Assess accuracy against the actual grid and convergence after changing the scheme. Grid counts follow the physical coordinate axes. Mean cell widths are `Lx/Nx`, `Ly/Ny` and `Lz/Nz`.
If only the x length doubles, start with twice Nx and keep Ny and Nz. Then compare refined results.
For example, a checked 16×16×16 grid can suggest a 32×16×16 starting grid for the longer domain.
This rule does not guarantee accuracy. Port/wall refinement uses nonuniform widths. Check actual widths, port positions and both flow directions.
The 3D geometry calculation suggests counts from dimensions, hydraulic diameter, ports and a total cell limit. It keeps manual grid settings.
The cell limit controls resource use. For new geometry, compare Q, both pressure drops, outlet temperatures and peak solid temperature.
Keep the original convergence and physical checks. Check changed directions first. A case result applies only to its checked range.

The GUI uses uniform velocity inside openings and enables local-density thermal transport.

It no longer offers historical inlet smoothing or a local-density switch.
Extra 3D six-wall layers are retired from GUI and script inputs. Port/wall refinement stays supported.
Config import accepts an old disabled value. An enabled value requires an explicit choice of the current mesh scheme and total counts.
Prepared cases replay and resume on their saved grids. Historical results remain readable; see the [retirement record](history/README.en.md#six-wall-grid-retirement).
Local density also affects transport-route selection for limited air/water cases. It is not a general sCO₂ variable-property switch. Loading GUI configurations with different previous settings reports the update. Subsequent saves use current settings. Allowing inlet Nu extrapolation changes only inlet-Re rejection/warning behavior.

It does not relax property or geometry limits. The next calculation receives the thread setting.
C++ limits its pointwise property workers and paired 2D flow calls. A limit of one selects serial execution.
Small grids can use fewer threads. This setting does not limit the application, external math libraries, or the number of optimization tasks.
The CLI accepts `--cpu-threads N`. The API accepts `RunControl(cpu_threads=N)`. Both require a positive integer.
Without a setting, C++ uses at most eight logical CPUs on the host.
The thread count is not part of `CaseData`. It does not change physical models, iteration budgets, or stop conditions.
Resume can use a different thread count with the same native build.
Libraries retained by old runs keep their existing entries. Omit the thread setting if that library lacks a thread limit.
Select Auto in the GUI. An explicit limit is never silently ignored.

Fluid cards emphasize inlet conditions. Autofill expands the property preview. Collapsing it keeps values. sCO₂ heat-transfer options follow fluid selection. A selected experimental mode stays visible for review or switching. Use Current Effective Coefficients explicitly loads `sco2-effective-nu-20260920-v1`.

The separate single-phase CO₂ model supports either side of full 2D/3D uniform
and continuous-field calculations. It uses HEOS properties and the supplied CO₂
CFD geometry and Nu resource. Fixed factors give `K=K0/2.5`, `cF=2.5cF0`, and
`Nu=1.28Nu_base`. Each factor applies once within its closure, only on CO₂ sides,
independently of the global D-F mode. Both streams use the common symmetric CO₂
geometry. Results record the model versions and factors. These are specified
empirical inputs, not a new experimental fit. CO₂ and sCO₂ remain separate model
selections. State, Nu/Re/Pr, and geometry checks remain active. Extrapolation is
not enabled automatically. Two-phase states, the critical point, discrete zones,
nonzero level-set offset, and CO₂ Quick Design are outside this added path.

Custom or historical parameters can be imported with provenance, version, and applicability. Current `alpha_D=4.1064` and `alpha_G=2.4824` are total Nu amplitudes, applied one time without another historical multiplier. Generic `cfd_smooth` stays the default. Loading saved inputs does not silently replace their parameters. See [model resources](model-resources.en.md#sco2-有效-nu-系数) for selection, Gyroid calibration, and Diamond transfer limits.

Optimization uses continuous-field search settings. The original discrete zone table stays for single-case computation.

The built-in Shanghai preset selects experimental D-F calibration by default. Gyroid 7/0.6 mm air uses April 1 straight-flow `sF=2.649010286988306`. Water keeps its existing correction. Complete saved configurations keep the selected mode. Older sessions or presets without a resistance mode still use smooth CFD. Generic API/CLI defaults are unchanged.

Experimental corrections have geometry, operating, and calibration limits. They do not remove each pressure-drop error. [Model resources](model-resources.en.md) records coefficients and low-flow extrapolation rules. [History](history/README.en.md) keeps 2D/3D validation of both channel arrangements.

<a id="quick-design"></a>

## Quick Design

Quick Design opens in the main window. You can change pages while it runs. Complete and partial results record the case IDs, both pressure-drop limits and the elapsed time for this job.

Quick Design screens dimensions against fluid conditions, heat duty, and pressure-drop constraints using a prescribed-velocity approximation. Automatic Search / Fixed Cell map to `auto/fixed`. Crossflow / Counterflow map to `cross/counter`. Case tables use K, absolute kPa, kg/s, and kW. Pressure limits are fractions: enter `0.05` for 5%.

Since 2026-11-25, the GUI and the CLI (`python -m sjtu_tpmshx.applications.design.cli`) use the same defaults: `cross` flow, `mean` properties, and a square face. Default CLI and GUI results change when you omit these options. On 2026-11-25, the CLI default changed from `prop_model` `const` to `mean` (arrangement stays `cross`). The GUI default changed from Counterflow (`counter`) to Crossflow (`cross`), and its property model stays `mean`. To get the previous CLI default result, pass `--prop-model const`. To get the previous GUI default result, select Counterflow (`逆流`). Both flow and property options stay available in both interfaces (`--arrangement counter` on the CLI, and `const` in the GUI). To set a fixed rectangular face on the CLI, pass a positive finite `--height` value in mm. To set a fixed rectangular face in the GUI, select the fixed-height option.

Result tables place volume near the front for comparison. Selection/refinement errors stop immediately and keep completed candidates. Parallel execution keeps only complete preceding batches. GUI and Excel distinguish failure from cancellation. Best labels apply only to the completed set.

If candidates exist, Quick Design CLI saves a partial report to `--out`, then raises the original error and exits nonzero. Failure of the first candidate does not overwrite a previous report.

<a id="optimization"></a>

## Bayesian optimization

Optimization supports air A / water B and two-fluid pairs with a CO₂ or sCO₂ side. It searches continuous fields in the active dimension: L(x,y)/t(x,y) for 2D and L(x,y,z)/t(x,y,z) for 3D. The default objectives compare B-side heat-uptake improvement and equally weighted two-side relative pressure drop. Core-mass mode uses absolute per-condition limits instead. The heat metric stays `-Q_B`; the baseline must be positive. All conditions keep the same A/B fluid models. Pareto designs keep complete controls. The default mode supports Sobol, qLogNEHVI, and qLogNParEGO. Core-mass mode supports qLogNEI and Sobol. BO requires its separate locked environment.

Optimization Design → Results switches between Pareto and size/wall fields. Select a Pareto design to preview its continuous field. Use Load Selected Design to apply it to the case. If the uniform baseline fails, Results shows the reason. Set the 2D total-flow depth in the study. Optimization plots support separate copy/export.

The optimization page uses the full workbench width. Its configuration page shows common geometry, fluids, grid, objectives, variables, and solve count.
Select Edit Common Conditions to open the existing parameter controls. Page buttons support keyboard navigation.
The Results page keeps its export actions beside each other when space permits. A narrow window can scroll longer configuration and status text.
An active ordinary calculation keeps its progress and Cancel control visible.

The Run page shows the current stage, condition, evaluated candidates, usable candidates, and failures.
It separates model fitting, candidate selection, preparation, native solving, and saving.
The Results page updates its Pareto plot during the search. Design selection becomes available when the search stops.
The remaining time estimate uses observed batch and proposal durations.
The first BO proposal must finish before an estimate is available. Later candidates can take a different time.
Cancel keeps its pending state until the worker reaches a safe stop point and saves the record.
Select Pause and Save on the Run page to save active native checkpoints and the search state.
After a program restart, select Continue Existing Task on the configuration page and open `optimization.json`.
Recovery uses the saved conditions, design space, budget, method, and seed. It keeps the complete evidence in a new directory.
Completed candidates do not run again. Failed candidates keep their used budget. Saved proposals continue in their original order.
An unfinished condition continues from its native checkpoint. A condition with only prepared input starts again from that input.
The source directory stays unchanged. Cancel remains available while a pause request is pending.
Recovery requires the associated `optimization-input.json` and the same search dependency versions.
Older reports remain readable and exportable. A report without that fixed input cannot continue the search.

Set X/Y/Z control counts in the search space. Each axis defaults to 3 controls.
One control makes that axis constant; two controls use linear interpolation.
The interface shows the decision count. Sobol initialization rejects more than 21201 variables.
Export Pareto Data writes CSV or XLSX with usable points, original design IDs,
front membership, and run status. Select a front point to export modeling coordinates.
The export includes `geometry.csv`, original `controls.csv`, `Lfield.csv`,
`tfield.csv`, and provenance. All coordinates and L/t values use mm.
Rows vary x first, then y and z. Modeling samples include domain boundaries;
a single sample uses the midplane. The limit is one million sample points.
Export uses the archived design configuration, including after later input edits.
The API keeps cell-center sampling as its default.
The CSV files have headers. [nTop Import Scalar Point Map](https://support.ntop.com/hc/en-us/articles/1500008558501-How-to-import-and-use-a-Point-Map) requires headerless X,Y,Z,S rows.
Convert the archived samples for that input. XY fields require an explicit depth to construct a 3D body.
The fields do not define a complete TPMS body. Specify the cell-map phase, thickness meaning, outer trim, and selective port seals.
Check solid connectivity, both fluid networks, and actual wall thickness on the constructed body.

The 3D viewport uses one unified floating bottom toolbar (with no cut-away view).
In simplified geometry mode, Outer Surface (`外表面`) is the default view.
Switch to Slices (`截面`) to inspect three orthogonal x/y/z planes snapped to physical cell centres,
or Volume (`体渲染`) for ray-cast volume rendering with an opacity slider.
Camera presets (`xy`, `xz`, `yz`, `等轴`) obey the shared reduced-motion preference (`reduced_motion` or `QT_REDUCED_MOTION=1`).
Floating Qt overlays show the ISO 80000-1 colorbar card and camera-projected port chips (`A 入口/出口`, `B 入口/出口`).
Copy and Save PNG in Export use one composited capture of the 3D scene and its visible overlays.

Saved per-field 3D color ranges persist with the workspace session and apply to the 3D scene,
colorbar card, and exported PNG images without changing field data.
Both limits must be finite and Max must exceed Min.

For 3D designs, the 3D Size / Wall Thickness Field tab shows the full XYZ parameter field. Rotate, zoom, inspect `L`/`t` on outer surfaces, three orthogonal slices, or ray-cast volume with adjustable opacity. This samples the continuous design without another solve. It displays spatial cell size and wall thickness, not a CAD preview of the TPMS surface. Temperature maps default to `coolwarm`, speed and pressure maps default to `viridis`, and design size/wall and sensitivity maps default to `turbo`; per-quantity colormap choices (`coolwarm`, `turbo`, `viridis`, `cividis`) persist with appearance settings.
Speed uses each fluid's complete field range. Pressure shares the A/B range by default.
Clear the pressure shared-scale checkbox to use each fluid's range. These ranges stay fixed between slices.
With the temperature shared-scale checkbox selected, all three phases use the same complete field range, contour levels, and ticks.
The K/°C selector changes temperature units only.
Field plots use original cell values, with no Gaussian filter at partial ports.
Hover and Coordinate Inspector show original cell values. Contour colors interpolate between cell centres.
The 3D view uses the physical cell centres on both uniform and nonuniform grids.
Exterior half cells keep the nearest centre value. Each field's display data loads on first selection.
3D orthogonal slices snap each coordinate to the nearest physical cell centre.
Historical display arrays stay unchanged in saved files. The current GUI reads the original temperature, velocity, and report pressure fields.
Both 2D and 3D views use the active per-quantity colormaps and show absolute pressure fields in kPa, while pressure drops (ΔP), raw pressure arrays, and CSV/NPZ exports keep Pa (with the existing `P_kPa` key in kPa).
After a solve, the selected field appears first. The volume loads when you first select 3D.
Drag with the left mouse button anywhere on the geometry canvas to rotate it. Use the wheel to zoom.
The thread control accepts Auto or an explicit limit on macOS and Windows.
A rejected design shows its reason in the summary. Diagnostics show the recorded range evidence.
Permission to exceed inlet Nu limits does not change the design verdict.

Defaults are 16 initial designs and 8 rounds of 1 new design. Each design is evaluated across all conditions before forming one aggregate sample. Imported JSON contains a `conditions` list. Each row has `condition_id` and side-specific `T_in_A_K`, `P_in_A_Pa`, `mass_flow_A_kg_s`. Replace A with B for side B. Without import, the interface explicitly uses the current single condition.

<a id="mass"></a>

## Core mass with operating constraints

Core-mass optimization minimizes one objective. Every condition must meet its minimum heat duty and both pressure-drop limits.
Add `mass_requirements` to the condition JSON. Import selects qLogNEI; Sobol is also available.
Supply the material density as `solid_density_kg_m3`. Give three positive limits for each condition ID in `conditions`.
Each condition can also specify lower or upper outlet temperature and absolute-pressure limits for either side.
This example shows the input format. Its values are not acceptance limits for the water-air experiment:

```json
{
  "conditions": [{"condition_id": "one", "T_in_A_K": 400, "P_in_A_Pa": 130000,
    "mass_flow_A_kg_s": 0.003, "T_in_B_K": 295, "P_in_B_Pa": 120000,
    "mass_flow_B_kg_s": 0.015}],
  "mass_requirements": {
    "solid_density_kg_m3": 8000,
    "conditions": {"one": {"Q_min_W": 100, "dP_A_max_Pa": 2000, "dP_B_max_Pa": 500,
      "T_out_B_min_K": 296, "T_out_B_max_K": 310, "P_out_A_min_Pa": 128000}}
  }
}
```

Optional temperature fields are `T_out_A_min_K` and `T_out_A_max_K`. Replace A with B for side B.
Optional absolute-pressure fields are `P_out_A_min_Pa` and `P_out_A_max_Pa`. The same rule applies to side B.
Limits must be finite and positive. A lower limit must not exceed its upper limit. Omitted limits do not apply.
For a target with an allowed deviation, supply the resulting lower and upper limits.
These limits check results. They do not change inlet states, fixed mass flows or solver boundaries.
Outlet temperature uses positive outward native mass flux as weights. Outlet absolute pressure uses physical opening areas as weights.

Mass uses the porosity and grid integral from the full result. It includes TPMS core solid only, without the casing or manifolds.
Multiply 2D heat and mass by the specified physical depth to obtain W and kg. Pressure drop uses Pa.
A failure at one condition cannot be offset by another condition or the other pressure drop.
Numerically valid candidates that exceed limits train the search model. Only the lightest feasible candidates can be selected for geometry export.
The plot shows core mass and the worst relative constraint residual. A residual at or below zero meets the limits.
Zero feasible candidates remains an explicit result. Completion of the search budget does not guarantee a feasible design.
Sessions, search recovery, and exports retain density, per-condition requirements, and checks.
By default, every condition must pass the strict model-range checks.
Set `mass_requirements.allow_nu_re_extrapolation` to `true` only for a study that permits Nu Re extrapolation.
This accepts finite, nonnegative Re outside the air/water Gyroid or Diamond Nu range. All other required checks remain active.
The interface labels this choice. Saved results and exports retain the strict verdict and each accepted range observation.
This setting does not establish experimental accuracy. Recovery keeps the saved choice.

The API accepts the same `mass_requirements` object with `method='qlognei'` or `'sobol'`.
Set both L bounds to 7 mm to optimize only wall thickness at a fixed cell size. Saved sessions retain these bounds.
Search pure Diamond and pure Gyroid separately. Compare them with the same conditions, limits, material, and closure settings.
Model limits, numerical gates, and final solid connectivity, wall thickness, and fluid separation require separate checks.

2D requires an actual conversion depth. Frozen Shanghai Gyroid 7/.6 exchanger corrections can support explicit continuous-field trend exploration. Search results still require all-condition and mesh review. This is not experimental validation of graded structures.

Command-palette `Sensitivity sweep` is a local trend map for two A-side parameters, available only when A is air. It uses a fixed 40 K temperature difference and uncorrected CFD pressure-drop baseline. Fluid B does not enter this estimate. It neither resolves the complete current case nor replaces final computation. Fixed temperature, pressure, and unscanned inputs must be valid.

Empty A-side pressure uses 101325 Pa, matching the compute page. Invalid nonempty pressure blocks the sweep. Changed fixed inputs require another sweep. A previous map cannot be applied.

<a id="import"></a>

## Import configurations and sessions

There are three input families: CLI configurations such as `air_2d.json`/`air_3d.json`, GUI sessions/presets, and Quick Design `DesignCase`. Their fields and units differ. They are not interchangeable. See [tool examples](tools.en.md#公开模块扩展示例) for a minimal DesignCase and extensions.

GUI format 1 saves the case without a solid-density input. Loading an older GUI case discards `le_rho_s` or its flat-file key `rho_s`.
Quick Design and core-mass optimization use their own density inputs.

When the GUI imports `line_edits` JSON without `config_format` wrapping, only supplied fields change. The same rule applies to previous flat parameter files. Omitted temperature scale, resistance mode, grid, model parameters, continuous field, and optimization conditions keep current values. An explicit K/°C change converts omitted temperatures from their current physical values. It does not merely relabel unchanged text. Formal complete configurations, preset libraries, and startup sessions keep their own restoration rules.

In a previous flat file, `u_A` and `u_B` specify inlet velocity. Each supplied velocity selects that side's velocity input mode. A side without a supplied velocity keeps its current input mode.

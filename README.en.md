# SJTU-TPMSHX-TM1

[中文](README.md) | [English](README.en.md)

TM1 separates TPMS heat-exchanger preprocessing, solving, and postprocessing into independently maintained modules. The GUI, optimization, and Quick Design call their public interfaces. The target repository is [alexlu997/SJTU-TPMSHX-TM1](https://github.com/alexlu997/SJTU-TPMSHX-TM1). Original SJTU-TPMSHX/V2 is a source reference. This branch does not merge back into that repository.

**Main source is under [sjtu_tpmshx/](sjtu_tpmshx/).** It contains all three modules. Other root directories hold documentation, examples, auxiliary tools, and verification records.

Python/Numba and C++ are both maintained backends. Python stays the default. Both support existing full 2D/3D computation and Quick Design. Shared prepared-data and result interfaces connect them to GUI, CLI, and optimization. Maintenance in this round covers macOS arm64 and Windows x64. Linux server deployment is deferred.

M-A merge acceptance for the rectangular 2D/3D three-module mainline is recorded. M-B extensions stay separately tracked. Historical B40 failures and physical applicability limits stay. See [capabilities and open work](docs/capabilities.en.md) for current conclusions. The [fixed history index](docs/history/README.en.md) keeps original plans, handoff records, and node evidence.

<a id="从这里开始"></a>

## Start here

| Task | Entry |
| --- | --- |
| Run locally | [macOS / Windows first run](#first-run), including CLI cases and GUI startup |
| Use the GUI | [Common GUI workflow](#gui-use) |
| Read or modify code | [Source and module map](sjtu_tpmshx/README.en.md) |
| Understand module boundaries | [Architecture](docs/architecture.md), [three-module data contract](schemas/three_module_v1/README.md) |
| Build desktop software | [Separate build environment, user files, and delivery validation](docs/desktop.en.md) |
| Find documentation and directories | [Repository and document navigation](docs/README.en.md) |
| Consult older versions | [History index](docs/history/README.en.md) |

<a id="first-run"></a>

<a id="首次运行macos--windows"></a>

## First run on macOS / Windows

This is a Python source project. A fresh setup needs locked dependencies. Use macOS with Python 3.13, or Windows x64 with Python 3.12 / 3.13, matching [platform CI](.github/workflows/ci.yml). Install the applicable [Python version](https://www.python.org/downloads/) first. Cloning also requires Git.

Alternatively, select **Code → Download ZIP** on the repository page and extract it. ZIP users start inside the extracted repository and skip `git clone` and `cd` below. Other commands are unchanged.

Environment creation and installation below apply only to first setup. Reuse an existing compliant `.venv-path`. Do not overwrite a shared environment. Run commands individually from the repository root containing `pyproject.toml`. Resolve any command or environment-check error before continuing.

**macOS, Terminal with zsh / bash**

```bash
git clone https://github.com/alexlu997/SJTU-TPMSHX-TM1.git
cd SJTU-TPMSHX-TM1
python3.13 -m venv .venv
printf '%s\n' "$PWD/.venv/bin/python" > .venv-path
PYTHON="$(head -n 1 .venv-path)"
"$PYTHON" -m pip install -r requirements-lock.txt
"$PYTHON" -m sjtu_tpmshx.runs.tools.check_locked_environment
"$PYTHON" -m pip check
```

**Windows, PowerShell**

Python 3.12 and 3.13 use the same lock. This example uses 3.13. For 3.12, change only `-3.13` to `-3.12` in the environment creation command.

```powershell
git clone https://github.com/alexlu997/SJTU-TPMSHX-TM1.git
cd SJTU-TPMSHX-TM1
py -3.13 -m venv .venv
$tm1Python = (Resolve-Path .venv\Scripts\python.exe).Path
[System.IO.File]::WriteAllText((Join-Path $PWD '.venv-path'), $tm1Python + [Environment]::NewLine)
$tm1Python = Get-Content .venv-path -TotalCount 1
& $tm1Python -m pip install -r requirements-lock.txt
& $tm1Python -m sjtu_tpmshx.runs.tools.check_locked_environment
& $tm1Python -m pip check
```

These commands call the environment interpreter directly. No activation script or PowerShell execution-policy change is required. This is [supported venv usage](https://docs.python.org/3.13/library/venv.html#how-venvs-work). `.venv-path` stores a local absolute path and is not shared through Git. Read it again in each new terminal.

For a dependency upgrade, create and prewarm a separate environment. Keep the old environment and its source revision. The current locks keep NumPy 2.4.4, Numba 0.64 and llvmlite 0.46 to avoid the measured warm-solve slowdown. SciPy 1.18, pandas 3, CoolProp 8 and Qt 6.12 stay on the newer versions. BO and desktop packaging use their own complete locks. Do not install the new lock into a shared environment used by another worktree. After changing `.venv-path`, pass the lock check and `pip check` before computation or tests.

CO₂ interpolation tables are separated by CoolProp version. Python defaults to `XDG_CACHE_HOME/coolprop/CoolProp-8.0.0`. An explicit `COOLPROP_ALTERNATIVE_TABLES_DIRECTORY` or C++ table path supplies the cache root; the solver adds `CoolProp-8.0.0`. Previous tables stay in place. First use of a new version generates its tables locally.

<a id="跑通小算例"></a>

### Run small examples

The repository includes [air_2d.json](examples/three_module/air_2d.json) and [air_3d.json](examples/three_module/air_3d.json). They use bundled model resources without private `data/` or `.git`. The first solve includes Numba compilation and can take several minutes.

On macOS:

```bash
PYTHON="$(head -n 1 .venv-path)"
export MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg"
export NUMBA_CACHE_DIR="$PWD/.cache/numba"
"$PYTHON" -m sjtu_tpmshx.cli run examples/three_module/air_2d.json .cache/first-run-2d --case-id first-run-2d
"$PYTHON" -m sjtu_tpmshx.cli run examples/three_module/air_3d.json .cache/first-run-3d --case-id first-run-3d
"$PYTHON" -m sjtu_tpmshx.main
```

On Windows:

```powershell
$tm1Python = Get-Content .venv-path -TotalCount 1
$env:MPLCONFIGDIR = Join-Path $PWD '.cache/matplotlib'
$env:XDG_CACHE_HOME = Join-Path $PWD '.cache/xdg'
$env:NUMBA_CACHE_DIR = Join-Path $PWD '.cache/numba'
& $tm1Python -m sjtu_tpmshx.cli run examples/three_module/air_2d.json .cache/first-run-2d --case-id first-run-2d
& $tm1Python -m sjtu_tpmshx.cli run examples/three_module/air_3d.json .cache/first-run-3d --case-id first-run-3d
& $tm1Python -m sjtu_tpmshx.main
```

Each compute command writes `case.yaml`, accompanying `case.h5`, `results.h5`, and `metrics.json`. The final command starts the GUI. CLI inputs differ from GUI sessions. These JSON files are CLI inputs. Open each `metrics.json`. Five basic metrics should be `available`.

Approximate reference values below were compared with the implementation on 2026-10-02. Earlier 2D values stay in [history](docs/history/README.en.md).

| Case | Q | Δp A / B (Pa) | Outlet T A / B (K) |
| --- | --- | --- | --- |
| air_2d | 31131.52 W/m | 1626.03 / 1188.81 | 303.28 / 334.79 |
| air_3d | 338.33 W | 1944.17 / 3038.38 | 359.23 / 344.93 |

Air inlet absolute pressure is now calibrated against the actual port-face area average. This convergence condition requires error below 0.01%. See [architecture](docs/architecture.md) for pressure and thermal convergence definitions. [Model resources](docs/model-resources.en.md) defines current air resistance coefficients, calibration sources, and applicability. History keeps stage repairs and experimental comparisons.

Full-compute `Q` is the absolute A-side raw boundary enthalpy duty on the main grid. `Q_A` and `Q_B` keep signed side duties. Separate 2D Richardson values do not replace the main metric. Both dimensions use physical port-face pressures and geometric opening-area weights for pressure drops, version `pressure_face_v1`. Numerical grid accuracy and experimental prediction error are assessed separately.

Historical measurements describe only their recorded code, cases, and settings. Heat, temperature, and flow metrics use `native_boundary_v1`. Previous metric files keep their definitions. Previous native results can be postprocessed again.

Requested grid counts can change during preparation refinement. These examples validate installation and module handoff, not experimental accuracy. The 3D example explicitly permits correlation extrapolation and keeps native warnings. `run` returns 0 for convergence and available basic metrics, 2 for nonconvergence or unavailable metrics, and 130 for cooperative cancellation. Other input/file errors fail with an error.

Read the preceding command's exit code with `echo $?` on macOS or `$LASTEXITCODE` in PowerShell. Do not relax thresholds to remove failures.

The default lock includes GUI, file handoff, and test dependencies. It excludes Torch / BoTorch / GPyTorch. Windows CPU Bayesian optimization uses `requirements-lock-server.txt`. macOS arm64 / Python 3.13 uses `requirements-lock-bo-macos.txt`. Install BO only in a separately authorized environment.

BoTorch tries to compile its optional C++ kernel when it first constructs a multi-objective Log acquisition function. Set `TORCH_EXTENSIONS_DIR` to `.cache/torch-extensions` in the current worktree. Prepend the BO environment's `bin` directory (`Scripts` on Windows) to `PATH` for that run so the locked Ninja is available. Compilation also requires a local C++ toolchain. If compilation fails, BoTorch reports the failure and uses its Python implementation. Record performance separately for the two paths, and keep first compilation outside warm measurements.

Then do a check of the matching lock. Run `pip check`. Do not add optional dependencies to an active shared base environment. Small examples need no BO. Raw experimental regression and refitting need matching local data, described below.

<a id="macos-项目文件夹中的-c-候选库"></a>

### C++ candidate library in the macOS project folder

This delivery keeps the Python/Qt application and source in a project folder with a matching precompiled C++ library. It does not create an `.app`. The supplied library targets the local macOS 27 / arm64 host. Other systems, machines, and older macOS versions are not accepted. Reuse the existing locked environment in `.venv-path` and the checks above.

Double-click root `launch-macos.command`, or run:

```sh
./launch-macos.command
```

The launcher enters its own project directory and writes caches under `.cache/`. It explicitly loads `native/lib/macos-arm64/libtpmshx_solver_shared.dylib` with `--backend cpp` and passes `.cache/native-deps/tables`. The library, tables, and host `.venv-path` are local delivery resources, not automatically supplied by Git. A missing interpreter or library produces an explicit error. The launcher installs no dependencies, compiles no library, and does not switch to Python.

Existing legacy CO₂ BICUBIC routes use four tables in the current version's directory and generate missing tables locally. The new conservative temperature algorithm does not use them. Public APIs, CLI, and direct module calls still default to Python.

With the current locked native dependencies present and the relevant native regressions passed, explicitly publish the launcher library:

```sh
"$PYTHON" scripts/build_native_dependencies.py publish
```

The command builds current source offline, runs independent C/C++ callers and error checks, then replaces the host library. Missing dependencies or failed verification stop publication. Before replacing different library contents, it saves the old library and record under `previous/` in the same directory. Republishing identical contents keeps that backup. `build.json` records the source commit, uncommitted changes, build configuration and paths.

`native/lib/` is an ignored local delivery directory. To roll back, stop programs using the library, then copy the library and `build.json` from `previous/` to the parent directory. Restore the matching source, Python environment and property version as well. Publication checks do not replace numerical regressions or desktop acceptance. Daily startup performs no build, installation or download. To open the same interface with Python, run `"$PYTHON" -m sjtu_tpmshx.main --backend python`.

In the left rail, Solver → Solver → Compute Backend selects Python or C++ without restarting. Startup arguments determine the initial selection. Switching affects the next ordinary computation, Quick Design, and optimization. It is locked during work and cancellation cleanup. C++ uses the startup library or the matching local macOS or Windows delivery library.

Source GUI and CLI share the default lookup. macOS uses `native/lib/macos-arm64/libtpmshx_solver_shared.dylib`; Windows uses `native/lib/windows-x64/tpmshx_solver_shared.dll`. The default table directory is `.cache/native-deps/tables`. With the matching library published there, use `--backend cpp`. Explicit library and table paths take priority. Direct solver API calls still pass host paths in `RunControl`.

A missing library keeps the current selection and shows the reason. Python thread settings follow backend selection. C++ keeps its existing fixed parallel strategy. Selection is a window runtime setting. It is not saved in case files and does not change existing results.

The 2026-10-05 candidate evidence keeps these limits. Ceff43 passed 19/43 and timed out on 24/43. The fixed population failed overall. fixed230 execution and indexing completed 230/230 in 93 minutes 18.5 seconds. Independent saved-state checks passed 229/230.

The first row was not evaluated because of an audit-tool error and was not retried. These checks do not show complete native configuration, iteration-history, F2, or experimental accuracy qualification.

Source GUI evidence covers 2D/3D display and export. Visible checks for cancellation, recomputation, menu save/reload, restart restoration, and outer iteration counts still await an unlocked Mac. Full application acceptance is not claimed. Merged PR #136 baseline `298761d2` passed macOS/Windows native CI. See the [CI record](https://github.com/alexlu997/SJTU-TPMSHX-TM1/actions/runs/37713153292). Earlier numerical failures stay attached to their original versions.

Engineering comparison, strict local regression, experimental accuracy, complete performance, and visible desktop acceptance keep separate thresholds. Folder startup and limited regression passes do not show full native qualification.

Windows x64 users and macOS users without the local launcher should follow [project-folder instructions](docs/desktop.en.md#source-folder). Pass explicit library and writable table paths when using locations other than the defaults.

<a id="gui-use"></a>

<a id="gui-常用流程"></a>

## Common GUI workflow

1. Start `sjtu_tpmshx.main`. Select a preset with Load at the top. The left Case Parameters rail has Geometry, Boundary, and Solver pages. Enter structure/dimension, fluid inlets/openings, then grid/solver settings.

   Drag the divider to change rail width. Collapse it with the title control or `Ctrl+\`. Expand or select a group to restore parameters, values, scroll position, and width.
   For 3D, each inlet can prescribe velocity or total mass flow in kg/s.
   In mass-flow mode, velocity is read-only and shows its last resolved value.
   Auto-fill or the next compute resolves it from current inlet state,
   porosity, and actual openings. Geometry edits keep the prescribed kg/s.
   The 2D interface keeps velocity inputs. Imported optimization conditions
   independently prescribe each condition's total flows.
2. Select Start Compute at the rail bottom, or press Ctrl+R. The status card below the canvas shows elapsed time. Expand Details for actual solver iterations and notices. Its separate Cancel control stays available when the rail is collapsed.

Cancellation waits for the current computation step. 3D coarse-grid initialization also responds. Solver import no longer precompiles all paths. Each required kernel compiles on first use. Cancellation during compilation still waits for the step to return.

The compilation thread is not forcibly stopped. The card does not predict remaining time.

   The main window shows neither live residual curves nor empty placeholders. Solvers still execute and record convergence/conservation checks. Terminal states distinguish completion, notices, nonconvergence, failure, and cancellation. Captured complete logs become available through Computation Log afterward. Nonconvergence or an unavailable 3D view is not styled as normal success.
3. Open Field Results after computation. Select temperature, velocity, or pressure and fluid A/B. Temperature also supports the solid. Move the z-slice slider for 3D fields.

   Field/Volume changes display mode only. Case parameters determine computation dimension.

   Below the field, inspect duty, both pressure drops, outlet temperatures, and convergence diagnostics. Summary collapses the readings. More → Diagnostics Details opens diagnostics. Focus or `F` hides parameters and the summary to enlarge the current canvas. Toggle again to restore previous expansion states.

   Editing the next configuration keeps current-result provenance and units. Displayable values do not show acceptance.
4. Save stores configuration. Export stores results or the current image. 2D results use CSV. 3D results use CSV plus field NPZ. Phase/slice choices affect display and image export only.

   The 3D NPZ stores available complete XYZ temperatures. It also stores both sides' three velocity components and magnitudes in m/s, and display `P_fA/P_fB` in Pa. Other arrays are `L_mm/t_mm` in mm and `dx/dy/dz` in m. Previous A-side `vmag/P_kPa` keys stay. Display pressure uses the current result's reference.

   `results.h5` keeps complete native thermal states and flux evidence. GUI sessions keep interface state. Formal module handoff uses `case.yaml` with HDF5 and `results.h5`. These serve different purposes. The command palette's Copy Inputs as Python Code uses the same complete case snapshot. It includes temperature scale, fluids/boundaries, zones, and model parameters.

   Execute it in a Python session with an existing `window` to restore inputs. The snippet neither starts a solve nor acts as a CLI ComputeConfig file.

Existing sessions restore custom fluids, directions, grids, and ports without Shanghai defaults overwriting them. Shanghai defaults apply only at first startup, in workspaces without saved sessions, or after explicit reset/preset loading. Each workspace saves its own zone axis, zone table, and continuous controls. Previous sessions without this data clear and disable zones. If the original enabled zones, a notice requests reconfiguration to prevent reuse of another workspace's zones.

Startup displays all temperature inputs in K. The conversion keeps their physical temperatures.

Parameter-page changes, rail expansion, and computation-detail expansion use an approximately 200 ms fade. Text stays clear. Repeated actions replace previous animation, and inputs stay editable. First window display also fades the parameter area one time. Effects are initialized beforehand to reduce first-navigation delay.

UI animation and preset 3D views use independent precise timers for high-refresh interaction. Slow frames advance by actual elapsed time without a backlog. Actual 3D frame rate also depends on rendering load. Rotation and view transitions can reduce volume sampling detail adaptively. Static quality returns after motion.

This affects interactive display only. Computation fields and complete exports stay unchanged. Set `QT_REDUCED_MOTION=1` to disable these transitions and 3D view animations.

After computation, the visible field is drawn first. Other plots are generated and cached on first display or export. Phase/slice changes update the visible plot. New results clear previous plot caches. High-resolution 3D volumes are likewise generated per field on demand.

Original fields, static quality, and shared color scales stay. Ordinary solve notices stay in the status card and Diagnostics Details, without synchronous dialogs blocking results.

Diagnostics Details reports preparation, solve, postprocessing, and display times. Successful total time includes background work and result display. Compare terminal and GUI speed with matched configuration, threads, and cache state. Separate first compilation from later runs. Startup commands above place caches under `.cache/numba`. Keep that directory to reuse compiled kernels.

More selects dark/light themes, effective after restart, and K/°C. The interface uses system sans-serif fonts: macOS system Latin/PingFang, Windows Segoe UI/Microsoft YaHei, and available Linux Noto Sans/system fallbacks. Body text and inputs use regular weight. Headings and primary actions use emphasis. Charts and exports keep Times New Roman for Latin text/numbers and Microsoft YaHei for Chinese. macOS can register matching installed Office fonts in the current process without copying or distributing them.

Missing chart fonts produce a notice and use available fonts. Interface system fonts are unaffected.

For ordinary computation, set threads under Solver → Compute Resources. Grid settings select regular or port/wall refinement. Refined input counts include all refined cells. Assess accuracy against the actual grid and convergence after changing the scheme. The GUI uses uniform velocity inside openings and enables local-density thermal transport.

It no longer offers historical inlet smoothing, six-wall refinement, or a local-density switch. Local density also affects transport-route selection for limited air/water cases. It is not a general sCO₂ variable-property switch. Loading GUI configurations with different previous settings reports the update. Subsequent saves use current settings. Allowing inlet Nu extrapolation changes only inlet-Re rejection/warning behavior.

It does not relax property or geometry limits. Ordinary computation passes the thread count to its worker's Numba parallel kernels. Small grids can use serial kernels. Optimization has an independent parallel strategy. This value is not an application-wide CPU limit.

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

Custom or historical parameters can be imported with provenance, version, and applicability. Current `alpha_D=4.1064` and `alpha_G=2.4824` are total Nu amplitudes, applied one time without another historical multiplier. Generic `cfd_smooth` stays the default. Loading saved inputs does not silently replace their parameters. See [model resources](docs/model-resources.en.md#sco2-有效-nu-系数) for selection, Gyroid calibration, and Diamond transfer limits.

Optimization uses continuous-field search settings. The original discrete zone table stays for single-case computation.

The built-in Shanghai preset selects experimental D-F calibration by default. Gyroid 7/0.6 mm air uses April 1 straight-flow `sF=2.649010286988306`. Water keeps its existing correction. Complete saved configurations keep the selected mode. Older sessions or presets without a resistance mode still use smooth CFD. Generic API/CLI defaults are unchanged.

Experimental corrections have geometry, operating, and calibration limits. They do not remove each pressure-drop error. [Model resources](docs/model-resources.en.md) records coefficients and low-flow extrapolation rules. [History](docs/history/README.en.md) keeps 2D/3D validation of both channel arrangements.

Quick Design screens dimensions against fluid conditions, heat duty, and pressure-drop constraints using a prescribed-velocity approximation. Automatic Search / Fixed Cell map to `auto/fixed`. Counterflow / Crossflow map to `counter/cross`. Case tables use K, absolute kPa, kg/s, and kW. Pressure limits are fractions: enter `0.05` for 5%.

Result tables place volume near the front for comparison. Selection/refinement errors stop immediately and keep completed candidates. Parallel execution keeps only complete preceding batches. GUI and Excel distinguish failure from cancellation. Best labels apply only to the completed set.

If candidates exist, Quick Design CLI saves a partial report to `--out`, then raises the original error and exits nonzero. Failure of the first candidate does not overwrite an previous report.

Optimization supports air A / water B and two-fluid pairs with a CO₂ or sCO₂ side. It searches continuous fields in the active dimension: L(x,y)/t(x,y) for 2D and L(x,y,z)/t(x,y,z) for 3D. Objectives compare B-side heat-uptake improvement and equally weighted two-side relative pressure drop. The heat metric stays `-Q_B`; the baseline must be positive. All conditions keep the same A/B fluid models. Pareto designs keep complete controls. Methods are Sobol, qLogNEHVI, and qLogNParEGO. BO requires its separate locked environment.

Optimization Design → Results switches between Pareto and size/wall fields. Select a Pareto design to inspect its continuous field. The geometry canvas stays independent. Optimization plots support separate copy/export.

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

The 3D Range button cycles through Full, Slice, and Custom. Custom Min/Max
values are saved per field and restored with the workspace session. Volume,
slice, new slice popups, and their images use these limits. Values outside
the limits use endpoint colors. Display limits do not change field data.
Both limits must be finite and Max must exceed Min.

For 3D designs, the 3D Size / Wall Thickness Field tab shows the full XYZ parameter field. Rotate, zoom, select L/t, adjust opacity, or move XY/YZ/XZ slices. This samples the continuous design without another solve. It displays spatial cell size and wall thickness, not a CAD preview of the TPMS surface. Temperature, pressure, velocity, size/wall, and sensitivity maps share `ui.theme.FIELD_CMAP='turbo'` across 2D, 3D, and slice popups. Each quantity keeps its own units and range.

Defaults are 16 initial designs and 8 rounds of 1 new design. Each design is evaluated across all conditions before forming one aggregate sample. Imported JSON contains only a `conditions` list. Each row has `condition_id` and side-specific `T_in_A_K`, `P_in_A_Pa`, `mass_flow_A_kg_s`. Replace A with B for side B. Without import, the interface explicitly uses the current single condition.

2D requires an actual conversion depth. Frozen Shanghai Gyroid 7/.6 exchanger corrections can support explicit continuous-field trend exploration. Search results still require all-condition and mesh review. This is not experimental validation of graded structures.

Command-palette `Sensitivity sweep` is a local trend map for two A-side parameters, available only when A is air. It uses a fixed 40 K temperature difference and uncorrected CFD pressure-drop baseline. Fluid B does not enter this estimate. It neither resolves the complete current case nor replaces final computation. Fixed temperature, pressure, and unscanned inputs must be valid.

Empty A-side pressure uses 101325 Pa, matching the compute page. Invalid nonempty pressure blocks the sweep. Changed fixed inputs require another sweep. An previous map cannot be applied.

There are three input families: CLI configurations such as `air_2d.json`/`air_3d.json`, GUI sessions/presets, and Quick Design `DesignCase`. Their fields and units differ. They are not interchangeable. See [tool examples](docs/tools.en.md#公开模块扩展示例) for a minimal DesignCase and extensions.

When the GUI imports `line_edits` JSON without `config_format` wrapping, only supplied fields change. The same rule applies to previous flat parameter files. Omitted temperature scale, resistance mode, grid, model parameters, continuous field, and optimization conditions keep current values. An explicit K/°C change converts omitted temperatures from their current physical values. It does not merely relabel unchanged text. Formal complete configurations, preset libraries, and startup sessions keep their own restoration rules.

<a id="三个模块"></a>

## Three modules

```text
Application input → preprocess → CaseData → solvers → FieldResult → postprocess → PerformanceResult
                                YAML/HDF5             HDF5/VTK                   JSON
```

Preprocessing defines actual grids, boundaries, design fields, fixed geometry, model resources, and run settings. Solvers consume prepared CaseData and evaluate temperature-dependent properties and numerical iterations. Postprocessing computes metrics from native fields, fluxes, pressure, and status in FieldResult. Missing evidence produces a reason. It does not start solving or read GUI/live solver objects.

```python
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.postprocess.api import evaluate

case = prepare_case(config, case_id="example")
result = run_case(case)
metrics = evaluate(result)
```

In-process calls need not write files. Independent processes use formal handoff:

```bash
PYTHON="$(head -n 1 .venv-path)"
mkdir -p .cache/handoff
"$PYTHON" -m sjtu_tpmshx.cli prepare examples/three_module/air_2d.json .cache/handoff/case.yaml --case-id example
"$PYTHON" -m sjtu_tpmshx.cli solve .cache/handoff/case.yaml .cache/handoff/results.h5
"$PYTHON" -m sjtu_tpmshx.cli postprocess .cache/handoff/results.h5 .cache/handoff/metrics.json
```

In PowerShell, use the same arguments with `& $tm1Python` instead of `"$PYTHON"`. First create the directory with `New-Item -ItemType Directory -Force .cache/handoff`. Inspect each stage with commands such as `"$PYTHON" -m sjtu_tpmshx.cli prepare --help`. PowerShell again uses `& $tm1Python`.

Case YAML references accompanying HDF5. [Schemas](schemas/three_module_v1/README.md) define result/VTK export and strict metric JSON limits. CLI outputs must be separate from current inputs and accompanying Case HDF5. Overlapping paths fail before stage execution. Separate existing outputs can still be updated.

Cancellation and failure do not become completed results. Completed nonconverged results keep their original state. Finite metrics do not show numerical, energy, or experimental accuracy acceptance.

<a id="已接线能力与边界"></a>

## Connected capabilities and boundaries

| Use | Public entry | Quantity basis |
| --- | --- | --- |
| Rectangular full 2D/3D | `prepare_case`, then `run_case` / `evaluate` | 2D Q is W/m. 3D Q is W. |
| Continuous-field multi-condition 2D/3D optimization | `run_multi_condition_optimization`, through complete Case solves and numerical checks | Heat-transfer percentage improvement and two-side relative pressure drop. 2D total flow uses explicit depth. |
| Quick Design | `prepare_quick_design`, then the same APIs | Prescribed-velocity LTNE and analytical inlet loss, without full SIMPLE. Q is W. |
| Parameter scans and effective-field input | [Public examples](examples/) | No private solver members are changed. |
| Offline cleaning and Nu fitting | `preprocess.offline` | Explicit sources. No automatic production-model replacement. Previous RBF publication is retired. |

Current GUI continuous optimization keeps the full case's ports, fluids, and dimensional solver settings. It supports air A / water B and two-fluid pairs with CO₂/sCO₂. Default ranges are L=4–8 mm and t=0.3–0.6 mm. The solver validates each fluid's Nu applicability independently. `optimization.json` stores all conditions, controls, field definitions, failures, and native batch paths. It and `batch.json` record the selected `backend`, including failures and cancellation, without local library paths.

Only fully qualified numerical batches receive objective values. Model-h keeps its existing energy checks. True-h uses its own convergence, unclipped enthalpy, coupled-energy, and equation-energy evidence. GUI Pareto application keeps complete fields. Different current geometry, ports, or solver settings cause rejection. Arbitrary external CLI configurations are not GUI presets. Evaluation count is a search budget, not proof of algorithm convergence or experimental accuracy.

Previous air/air optimization screening, its 2D entry, and frozen-B 3D solving are retired. See [history](docs/history/retired-tools.md). Previous result archives stay readable. Pareto CSV geometry stays exportable with its original configuration. Retired screening modes cannot execute or recompute metrics.

Current domains support only **rectangular 2D / cuboid 3D**. The interface displays the shape directly without a one-option menu. Hexagonal/octagonal routes are retired. Previous polygon configurations fail before loading and keep current inputs/results. Polygon startup sessions are neither restored nor converted into rectangles.

Previous rectangular files still load. [Fixed history](docs/history/retired-tools.md) keeps polygon code. Reopening those routes requires implementation and verification of mainline physical rules and independent module handoff.

`models/`, `df_surrogate/`, and related layers give shared technical support, not a fourth business module. Previous pipeline/application entries call public modules in one direction. See [architecture](docs/architecture.md).

Python/Numba is the default. macOS arm64 and Windows x64 libraries support Quick Design and full 2D/3D through explicit `RunControl(backend='cpp', native_library=...)` or CLI `--backend cpp`. See [C++ migration](docs/cpp-migration.md) for paths, builds, and limits. Required native build, independent-call, and numerical-comparison CI passed on macOS/Python 3.13 and Windows/Python 3.12 and 3.13. Visible desktop delivery and complete performance acceptance stay separate.

Full 2D uses ABI 2. Distribute matching libraries, headers, and adapters. The former Python outer-loop/C++ sweep hybrid is retired. Select a complete Python or C++ backend. OpenFOAM, REFPROP, extended h/f/PEC definitions, and adjoints stay under M-B and original scope limits. Directories or interfaces do not show implementation.

<a id="环境与检查"></a>

## Environment and checks

Local Python commands must use the absolute interpreter on `.venv-path`'s first line. If absent, a compliant environment must be configured first. Agents do not automatically create, upgrade, or reinstall shared environments. Dependency declarations and exact locks change together. Shared environments contain locked dependencies only, without an editable project installation. Run from the current repository root.

```bash
PYTHON="$(head -n 1 .venv-path)"
"$PYTHON" -m sjtu_tpmshx.runs.tools.check_locked_environment
"$PYTHON" -m pip check
export MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg"
export QT_QPA_PLATFORM=offscreen PYTHONHASHSEED=0
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export NUMBA_NUM_THREADS=2
"$PYTHON" -m mypy @mypy-core-files.txt --config-file pyproject.toml
"$PYTHON" -m pytest sjtu_tpmshx/tests -q -ra -m "not slow and not heavy" --ignore=sjtu_tpmshx/tests/integration_tm1 -n 2 --dist loadscope --timeout=600 --timeout-method=thread --durations=30 --junitxml=.cache/ci/fast.xml
NUMBA_NUM_THREADS=1 "$PYTHON" -m pytest sjtu_tpmshx/tests/integration_tm1 -q -ra --timeout=600 --timeout-method=thread --durations=30 --junitxml=.cache/ci/integration.xml
# Complete local acceptance: no -m filter. Replace auto with a fixed worker count for available resources.
"$PYTHON" -m pytest sjtu_tpmshx/tests -q -n auto --dist loadscope --timeout=600 --timeout-method=thread
```

PowerShell uses the same pytest arguments. Set variables with forms such as `$env:NUMBA_NUM_THREADS='2'`. Then call `& $tm1Python`. Numba needs a limit of at least 2 because enthalpy transport tests explicitly use two threads. Independent integration uses 1. Restore 2 before the full suite.

CI fast tests split complete modules between two runners, each with two workers. Each worker has single-threaded BLAS/OMP and at most two Numba threads. Complete integration runs concurrently on a third runner.

Existing test helpers stay. `run_tests_fast.ps1` is development feedback only. Its `not heavy` subset differs from fast CI. The two PowerShell scripts validate the base lock by default. With an existing Windows BO environment, use `./scripts/run_tests_server.ps1 -LockFile requirements-lock-server.txt`.

The same parameter is accepted by `run_tests_fast.ps1`. Tests start only after the selected lock and `pip check` pass. Scripts install nothing. A server lock does not permit unlisted packages.

GitHub workflows use checkout v7, setup-python v7, upload-artifact v7, and download-artifact v8 for shard gates. Action runtimes do not change solver Python environments. `three-module` independently validates real file handoff from a complete environment to minimal postprocessing. Base and separate BO jobs cover macOS/Python 3.13 and Windows/Python 3.12 and 3.13. BO jobs install platform-specific locks, validate environments, and explicitly import Torch/BoTorch/GPyTorch.

They run multi-condition optimizer tests, including both real Log acquisition functions. Base jobs keep the lock without BO and test missing-optional-dependency behavior. BO uploads only JUnit reports for 7 days, without solve data or environments.

`mypy-core-files.txt` explicitly lists 18 files. Coverage includes configuration, controllers, CLI, current envelope implementation, three-module contracts/APIs, and the postprocessing metric entry. Deleted forwarding modules are excluded. `pyproject.toml` validates unannotated bodies in four boundary implementation modules. This does not show strict typing across each solver.

Fast `test_type_gate.py` runs the same list and validates the rejection of incorrect inputs by all three public APIs. The standalone mypy command is for local checks. CI does not add a duplicate step.

The first pytest command excludes slow/heavy and `integration_tm1`. The second runs that complete integration directory one time. Neither replaces the third, complete local gate. Local commands run the unsharded subsets. To reproduce a fast shard, append `-p sjtu_tpmshx.tests.ci_shard --ci-shard=0 --ci-manifest=.cache/ci/fast-0`.

For shard 1, use `--ci-shard=1` with its own manifest directory. `sjtu_tpmshx/tests/_ci_shard0.txt` lists complete modules for shard 0. Remaining modules enter shard 1. Sharding occurs after existing heavy markers and pytest filters, without changing selection or assertions. Run `"$PYTHON" scripts/check_ci_shards.py .cache/ci/fast-0 .cache/ci/fast-1` to validate worker-set agreement and complete, disjoint shards.

Native qualification uses three independent runners. Each shard runs serially. Modules with shared solver fixtures stay together. Independent, expensive backend-pair cases use exact node IDs. Repeat `--ci-shard-modules` with `sjtu_tpmshx/tests/native/_ci_shard0.txt` and `sjtu_tpmshx/tests/native/_ci_shard1.txt`, in that order. These lists select shards 0 and 1. All remaining cases enter shard 2. All numerical cases, precision and convergence assertions, and three platform/Python combinations stay unchanged.

Each platform/Python combination builds native libraries once and runs independent C/C++ callers. Its three shards reuse the same workflow's `native-build-<platform>-py<version>` artifact. The archive preserves executable permissions and includes runtime libraries, callers, and license notices. An exact CoolProp static-library cache key binds the platform, architecture, Python, hosted toolchain image version, native dependency lock, and build script. Project C++ and model coefficients rebuild on every run. Cache hits still require independent caller checks.

Build logs use `native-build-logs-<platform>-py<version>`. Each shard uploads `native-dependencies-<platform>-py<version>-shard-<0|1|2>` with JUnit and `native-manifest`. These artifacts are retained for 7 days.

The same set checker uses `--serial` for complete/disjoint verification. Native logs keep the 20 slowest tests and skip reasons.

Fast/integration logs keep the 30 slowest tests and skip reasons. Each shard publishes JUnit and collection manifests as `test-reports-<platform>-py<version>-<fast-0|fast-1|integration>` for 7 days. Manifests include each pytest process's separate peak RSS and cache counts for loaded Numba dispatchers. Process peaks cannot be summed as concurrent total peak. Statistics exclude ordinary child processes and destroyed dispatchers.

The three original `tests (<platform>, <version>)` required checks wait for all platforms' test shards, BO jobs, and native qualification shards. They require each job to succeed and all shard-set checks to pass. Failed, canceled, skipped, or missing shards cannot pass the gate. `minimal-postprocess` stays separately required. Compare fast, integration, and full-job speed separately with same-platform baselines.

Local timing does not promise CI speedups. Acceptance skips keep specific reasons. Skipped capabilities are not passed. Minimal-postprocess CI uses separate `requirements-lock-postprocess.txt`. It consumes real 2D/3D files from another complete environment. Files stay local to CI jobs without result-artifact uploads.

Configuration alone does not show a CI pass.

<a id="协作与合并"></a>

## Collaboration and merge

Public contract changes require downstream review. Solvers validate preprocessing configuration, units, and grids. Postprocessing validates native fields, boundary evidence, and states. Applications/file consumers validate metric definitions and file relationships. GUI and scheduling stay in `ui/` and `controllers/`. Model resources stay shared.

Each PR identifies affected interfaces, verification evidence, and reviewers. Current repository maintainer is `alexlu997`. Named module owners will be assigned when the additional colleague joins. Do not invent CODEOWNERS or describe model self-review as independent human approval.

The 2026-09-13 protection readback required PR updates, a branch current with main, and three GitHub Actions checks. They were `tests (macos-14, 3.13)`, `tests (windows-2022, 3.12)`, and `minimal-postprocess`. Rules also applied to administrators and prohibited force pushes/deletion. At least one non-author approval is planned when multiple people formally participate. At that recorded stage, required approval count was 0. GitHub is authoritative for actual state.

Windows supports Python 3.12 and 3.13. Protection keeps the preceding checks and adds `tests (windows-2022, 3.13)`, for four required checks. Other protections stay unchanged. Workflow edits do not automatically update GitHub protection settings. Before a merge, make sure that the required checks pass.

See [capabilities](docs/capabilities.en.md) for current/open scope and [tools](docs/tools.en.md) for measurements and reproduction boundaries.

<a id="数据与历史证据"></a>

## Data and historical evidence

Raw experiment/CFD data stays local under `data/raw_data/` and is not committed. [data-revision.txt](data-revision.txt) records the matching version. [Model resources](docs/model-resources.en.md) defines cleaning, fitting, and local output rules. Directories separate experiments, CFD results, and worklists. The [data catalog](docs/data-catalog.en.md) maps Excel names, purposes, and reader constraints. Moving data requires corresponding loader and pressure-convention updates.

Optimization research scripts, per-case results, and exploratory reports stay in ignored `.cache/`, without code-repository commits or uploads. Keep long-term research evidence in a separate private archive. Git ignore rules are not backups. Local environments and `.venv-path` are also untracked and are reconstructed from versioned declarations and locks. Production optimization modules, regressions, CI workflows, locks, and usage/architecture documentation stay tracked.

Previous γ/RBF, SmoothDF, water developing-region, and previous sCO2 resistance models are retired. [Fixed history](docs/history/legacy-models.md) keeps source/results. Current joint K/cF, original water Nu, and experimental D-F corrections stay. [Current effective coefficients](docs/model-resources.en.md#sco2-有效-nu-系数) replace the previous sCO₂ anchored-gamma route and dedicated reports. Historical experimental errors stay unchanged. Missing current water CFD workbooks are not replaced by older files.

The [V2 README archive](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/docs/history/v2-readme.md) keeps original accuracy and physics descriptions. Previous image links are fixed to historical commits. The [history index](docs/history/README.en.md) tracks removed images, optimization outputs, exploration, and Atlas snapshots. Those values do not show new acceptance of TM1 or current default CFD mode. Original B40 4/4 failures, nonconverged 3D screening, and other native failures stay. Thresholds and physical scope are not changed to fit results.

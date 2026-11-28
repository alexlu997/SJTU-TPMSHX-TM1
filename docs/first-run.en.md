# Run TM1 from source

[中文](first-run.md) · [English](first-run.en.md) · [Project home](../README.en.md)

Run the commands from the repository root. Set up the local environment before running an example.

<a id="first-run"></a>

## Install the locked environment

This is a Python source project. A fresh setup needs locked dependencies. Use macOS with Python 3.13, or Windows x64 with Python 3.12 / 3.13, matching [platform CI](../.github/workflows/ci.yml). Install the applicable [Python version](https://www.python.org/downloads/) first.
Full native dependency setup uses Git to fetch and verify third-party sources.

Alternatively, select **Code → Download ZIP** on the repository page and extract it. Run the commands from the extracted source root. Skip `git clone` and `cd` below.

Environment creation and installation below apply only to first setup. Reuse an existing compliant `.venv-path`. Do not overwrite a shared environment. Run commands individually from the repository root containing `pyproject.toml`. Resolve any command or environment-check error before continuing.

**macOS, Terminal with zsh / bash**

```bash
git clone https://github.com/alexlu997/SJTU-TPMSHX-TM1.git
cd SJTU-TPMSHX-TM1
python3.13 -m venv .venv
printf '%s\n' "$PWD/.venv/bin/python" > .venv-path
PYTHON="$(head -n 1 .venv-path)"
"$PYTHON" -m pip install -r engineering/requirements/base.txt
"$PYTHON" -m tm1.development.runs.tools.check_locked_environment
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
& $tm1Python -m pip install -r engineering/requirements/base.txt
& $tm1Python -m tm1.development.runs.tools.check_locked_environment
& $tm1Python -m pip check
```

These commands call the environment interpreter directly. No activation script or PowerShell execution-policy change is required. This is [supported venv usage](https://docs.python.org/3.13/library/venv.html#how-venvs-work). `.venv-path` stores a local absolute path and is not shared through Git. Read it again in each new terminal.

A standard wheel installation includes h5py and PyYAML for case and result files.
The `offline` extra supplies Python CoolProp for the sCO₂ CFD readers in `preprocess.offline`.
The `test` extra supplies SymPy, scikit-image, and Python CoolProp for reference calculations in the tests.
The base development lock already includes these packages.

For a dependency upgrade, create and prewarm a separate environment. Keep the old environment and its source revision. The 0.2 base lock removes Numba, llvmlite and PyAMG. It retains dependencies for preparation, postprocessing, optimization and the GUI. Native pressure code keeps its ported algorithms and license notices. It does not load Python PyAMG. BO and desktop packaging use their own complete locks. Do not install the new lock into a shared environment used by another worktree. After changing `.venv-path`, pass the lock check and `pip check` before computation or tests.

CO₂ interpolation tables are separated by CoolProp version. Python defaults to `XDG_CACHE_HOME/coolprop/CoolProp-8.0.0`. An explicit `COOLPROP_ALTERNATIVE_TABLES_DIRECTORY` or C++ table path supplies the cache root; the solver adds `CoolProp-8.0.0`. Previous tables stay in place. First use of a new version generates its tables locally.

<a id="跑通小算例"></a>

<a id="examples"></a>

## Run the 2D and 3D examples

The repository includes [air_2d.json](../examples/three_module/air_2d.json) and [air_3d.json](../examples/three_module/air_3d.json). They use bundled model resources without private `data/` or `.git`. First build geometry, preparation, solver and result libraries with the macOS C++ toolchain or a Windows x64 MSVC developer terminal. Record build and initial property-table times separately from solve time.

On macOS:

```bash
PYTHON="$(head -n 1 .venv-path)"
export MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg"
"$PYTHON" engineering/scripts/build_native_dependencies.py fetch
"$PYTHON" engineering/scripts/build_native_dependencies.py publish
"$PYTHON" -m tm1.cli run examples/three_module/air_2d.json .cache/first-run-2d --case-id first-run-2d
"$PYTHON" -m tm1.cli run examples/three_module/air_3d.json .cache/first-run-3d --case-id first-run-3d
"$PYTHON" -m tm1.main
```

On Windows:

```powershell
$tm1Python = Get-Content .venv-path -TotalCount 1
$env:MPLCONFIGDIR = Join-Path $PWD '.cache/matplotlib'
$env:XDG_CACHE_HOME = Join-Path $PWD '.cache/xdg'
& $tm1Python engineering/scripts/build_native_dependencies.py fetch
& $tm1Python engineering/scripts/build_native_dependencies.py publish
& $tm1Python -m tm1.cli run examples/three_module/air_2d.json .cache/first-run-2d --case-id first-run-2d
& $tm1Python -m tm1.cli run examples/three_module/air_3d.json .cache/first-run-3d --case-id first-run-3d
& $tm1Python -m tm1.main
```

Each compute command writes `case.yaml`, accompanying `case.h5`, `results.h5`, and `metrics.json`. The final command starts the GUI. CLI inputs differ from GUI sessions. These JSON files are CLI inputs. Open each `metrics.json`. Five basic metrics should be `available`.

Approximate reference values below were compared with the implementation on 2026-10-02. Earlier 2D values stay in [history](history/README.en.md).

| Case | Q | Δp A / B (Pa) | Outlet T A / B (K) |
| --- | --- | --- | --- |
| air_2d | 31131.52 W/m | 1626.03 / 1188.81 | 303.28 / 334.79 |
| air_3d | 338.33 W | 1944.17 / 3038.38 | 359.23 / 344.93 |

Air inlet absolute pressure is now calibrated against the actual port-face area average. This convergence condition requires error below 0.01%. See [architecture](architecture.md) for pressure and thermal convergence definitions. [Model resources](model-resources.en.md) defines current air resistance coefficients, calibration sources, and applicability. History keeps stage repairs and experimental comparisons.

Full-compute `Q` is the absolute A-side raw boundary enthalpy duty on the main grid. `Q_A` and `Q_B` keep signed side duties. Separate 2D Richardson values do not replace the main metric. Both dimensions use physical port-face pressures and geometric opening-area weights for pressure drops, version `pressure_face_v1`. Numerical grid accuracy and experimental prediction error are assessed separately.

Historical measurements describe only their recorded code, cases, and settings. Heat, temperature, and flow metrics use `native_boundary_v1`. Previous metric files keep their definitions. Previous native results can be postprocessed again.

Requested grid counts can change during preparation refinement. These examples validate installation and module handoff, not experimental accuracy. The 3D example explicitly permits correlation extrapolation and keeps native warnings. `run` returns 0 for convergence and available basic metrics, 2 for nonconvergence or unavailable metrics, and 130 for cooperative cancellation. Other input/file errors fail with an error.

Read the preceding command's exit code with `echo $?` on macOS or `$LASTEXITCODE` in PowerShell. Do not relax thresholds to remove failures.

The default lock includes GUI, file handoff, and test dependencies. It excludes Torch / BoTorch / GPyTorch. Windows CPU Bayesian optimization uses `engineering/requirements/bo-windows.txt`. macOS arm64 / Python 3.13 uses `engineering/requirements/bo-macos.txt`. Use a separate environment for an authorized BO task.

BoTorch tries to compile its optional C++ kernel when it first constructs a multi-objective Log acquisition function. Set `TORCH_EXTENSIONS_DIR` to `.cache/torch-extensions` in the current worktree. Prepend the BO environment's `bin` directory (`Scripts` on Windows) to `PATH` for that run so the locked Ninja is available. Compilation also requires a local C++ toolchain. If compilation fails, BoTorch reports the failure and uses its Python implementation. Record performance separately for the two paths, and keep first compilation outside warm measurements.

Then do a check of the matching lock. Run `pip check`. Do not add optional dependencies to an active shared base environment. Small examples need no BO. Raw experimental regression and refitting need [local data from the matching revision](verification.en.md#data-and-historical-evidence).

<a id="macos-项目文件夹中的-c-候选库"></a>

<a id="native-libraries"></a>

## Build, publish and locate the native libraries

This delivery keeps the Python/Qt application and source in a project folder with a matching precompiled C++ library. It does not create an `.app`. The supplied library targets the local macOS 27 / arm64 host. Other systems, machines, and older macOS versions are not accepted. Reuse the existing locked environment in `.venv-path` and the checks above.

Double-click root `launch-macos.command`, or run:

```sh
./launch-macos.command
```

The launcher enters its own project directory and writes caches under `.cache/`. It explicitly loads `sjtu_tpmshx/solvers/native/lib/macos-arm64/libtpmshx_solver_shared.dylib` with `--backend cpp` and passes `.cache/native-deps/tables`. The library, tables, and host `.venv-path` are local delivery resources, not automatically supplied by Git. A missing interpreter or library produces an explicit error. The launcher does not install dependencies or compile the library.

T-SOU uses checked HEOS PT properties and does not create EOS tables. The table-directory option remains for explicitly selected historical runtimes. Public APIs, CLI and direct module calls default to C++.

For dependencies configured under the current source layout, publish all four launcher libraries after the relevant native regressions pass.
For an old layout, first prepare a new cache as described below.

```sh
"$PYTHON" engineering/scripts/build_native_dependencies.py publish
```

When you upgrade from the root `native/` layout, keep the original libraries, `build.json` and `previous/` under `native/lib/`.
Old checkpoints still require their matching original library, selected explicitly.
Keep old caches and their absolute paths while consumers still use them.
The old pilot build directory records the previous source location. It cannot configure the new layout.

For an existing checkout, select an unused cache directory. These examples use `.cache/native-layout` and the base environment lock.
If `.venv-path` selects a BO environment, use `engineering/requirements/bo-macos.txt` or `engineering/requirements/bo-windows.txt` for publication instead.

macOS:

```sh
"$PYTHON" engineering/scripts/build_native_dependencies.py fetch --cache .cache/native-layout
"$PYTHON" engineering/scripts/build_native_dependencies.py publish --cache .cache/native-layout --python-lock engineering/requirements/base.txt
```

Windows (PowerShell):

```powershell
& $tm1Python engineering/scripts/build_native_dependencies.py fetch --cache .cache/native-layout
& $tm1Python engineering/scripts/build_native_dependencies.py publish --cache .cache/native-layout --python-lock engineering/requirements/base.txt
```

`publish` includes the build and verification steps.
Use the same `--cache` directory for later explicit `build`, `verify` and `publish` commands.
A fresh clone can use the default cache above.

The command builds and verifies solver, geometry, preparation and result libraries offline. It replaces all four host files in one transaction.
Missing dependencies or failed verification stop publication.
Before replacing different contents, it saves each old library and matching record under `previous/`.
Republishing identical contents keeps that backup. The solver uses `build.json`, geometry uses `geometry-build.json`, preparation uses `preparation-build.json`, and result uses `result-build.json`.
Each record includes its build configuration, paths and available Git source information.
A replacement failure restores selected files and metadata. A failed rollback keeps staging files and reports their recovery path.

`sjtu_tpmshx/solvers/native/lib/` is an ignored local delivery directory.
Stop related programs before rollback. Restore the selected library and its matching record from `previous/`.
Restore the matching source, Python environment and property version too.
Publication checks do not replace numerical regressions or desktop acceptance. Daily startup performs no build, installation or download.

For geometry alone, use the locked CMake tool and independent geometry target. The environment lock must match the configured interpreter:

```sh
"$PYTHON" engineering/scripts/build_native_dependencies.py fetch-cmake
"$PYTHON" engineering/scripts/build_native_dependencies.py publish --component geometry --python-lock engineering/requirements/base.txt
```

On Windows PowerShell:

```powershell
& $tm1Python engineering/scripts/build_native_dependencies.py fetch-cmake
& $tm1Python engineering/scripts/build_native_dependencies.py publish --component geometry --python-lock engineering/requirements/base.txt
```

Use the matching BO lock for a BO environment. Separate `build` and `verify` commands also accept `--component geometry`.
Geometry-only publication does not build or replace solver/run_state. Old checkpoints still need their exact retained solver runtime.
Use `TPMSHX_GEOMETRY_LIBRARY` to select a geometry file outside the default directory.
Historical result reading and independent postprocessing do not load geometry.
Preparation can also be published independently. First build locked CoolProp in the same cache. Then use `publish --component preparation`.
This command builds no solver or run_state. It publishes only preparation and `preparation-build.json`.
See the [preparation core](cpp-migration.md#native-preparation-core) for commands.
Use `TPMSHX_PREPARATION_LIBRARY` to select its runtime file. Historical result reading and independent postprocessing do not load preparation.
Use `publish --component result` to publish result independently without building solver or model libraries. Select the configured interpreter's exact lock.
Full 2D/3D evaluation and the three independent result queries need the current result stage image.
The native stage also evaluates Quick Design metrics from `float64` operands. Pure HDF/JSON reads load no native library.
Linux x86_64 supports independent result evaluation only. See [result core commands](cpp-migration.md#native-result-core).
The Python wheel includes runtime code, published development and validation tools, and model resources.
It contains no tests or native libraries. Git and source distributions keep the complete test tree, including native test bridges.
The source distribution also includes native source, build files, locks and source records.
Use `engineering/scripts/check_distributions.py` to check source and wheel contents.
Supply a new `--output-dir` under `.cache/`.
Native builds remain explicit steps after environment setup.

The GUI uses C++ for ordinary computation, Quick Design and optimization. It has no backend selector. It uses the selected libraries or matching libraries in the local macOS or Windows delivery folder.

Source GUI and CLI share the default lookup. macOS uses `sjtu_tpmshx/solvers/native/lib/macos-arm64/libtpmshx_solver_shared.dylib`; Windows uses `sjtu_tpmshx/solvers/native/lib/windows-x64/tpmshx_solver_shared.dll`. The default table directory is `.cache/native-deps/tables`. With a matching library in these locations, no backend argument is needed. Explicit library and table paths take priority. API callers can override host paths in `RunControl`.

A missing library produces an explicit error. Compute Threads controls the native run. Auto uses at most eight logical CPUs on the host. Selection is a window runtime setting. It is not saved in case files and does not change existing results.

Windows x64 users and macOS users without the local launcher should follow [project-folder instructions](desktop.en.md#source-folder). Pass explicit library and writable table paths when using locations other than the defaults.

<a id="stage-api"></a>

## Three modules

```text
Application input → preprocess → CaseData → solvers → FieldResult → postprocess → PerformanceResult
                                YAML/HDF5             HDF5/VTK                   JSON
```

Preprocessing defines actual grids, boundaries, design fields, fixed geometry, model resources, and run settings. Solvers consume prepared CaseData and evaluate temperature-dependent properties and numerical iterations. Postprocessing computes metrics from native fields, fluxes, pressure, and status in FieldResult. Missing evidence produces a reason. It does not start solving or read GUI/live solver objects.

```python
from tm1.preprocess.api import prepare_case
from tm1.solvers.api import run_case
from tm1.postprocess.api import evaluate

case = prepare_case(config, case_id="example")
result = run_case(case)
metrics = evaluate(result)
```

In-process calls need not write files. Independent processes use formal handoff:

```bash
PYTHON="$(head -n 1 .venv-path)"
mkdir -p .cache/handoff
"$PYTHON" -m tm1.cli prepare examples/three_module/air_2d.json .cache/handoff/case.yaml --case-id example
"$PYTHON" -m tm1.cli solve .cache/handoff/case.yaml .cache/handoff/results.h5
"$PYTHON" -m tm1.cli postprocess .cache/handoff/results.h5 .cache/handoff/metrics.json
```

In PowerShell, use the same arguments with `& $tm1Python` instead of `"$PYTHON"`. First create the directory with `New-Item -ItemType Directory -Force .cache/handoff`. Inspect each stage with commands such as `"$PYTHON" -m tm1.cli prepare --help`. PowerShell again uses `& $tm1Python`.

Case YAML references accompanying HDF5. [Schemas](contracts/three_module_v1/README.md) define result/VTK export and strict metric JSON limits. CLI outputs must be separate from current inputs and accompanying Case HDF5. Overlapping paths fail before stage execution. Separate existing outputs can still be updated. All CLI stages reject writes into directories with `run.json` or `checkpoint.h5`, including their subdirectories. Select a new directory to preserve the saved run and its native library.

Cancellation and failure do not become completed results. Completed nonconverged results keep their original state. Finite metrics do not show numerical, energy, or experimental accuracy acceptance.

Full C++ runs can save their iteration state in a new run directory:

```bash
"$PYTHON" -m tm1.cli run examples/three_module/air_2d.json .cache/run-01 --case-id example --backend cpp --checkpoint-interval 60
"$PYTHON" -m tm1.cli resume .cache/run-01/checkpoint.h5 .cache/run-02 --checkpoint-interval 60
```

The CLI interval is explicit. Saving waits for the next complete solver step.
With saving enabled, Ctrl+C requests a pause. The process returns code 3 after it saves the state.
A pause does not produce completed results. Cancellation still returns code 130.
The directory retains the prepared input, native library, checkpoint, and run status.
Completed runs also contain `results.h5` and `metrics.json`.

Repeated saves share fixed native libraries and archived baseline fields when hard links are available.
Each directory keeps its local file paths. Other filesystems use independent copies.
Treat shared snapshots as read-only; use TM1 writers to replace files instead of editing their contents in place.
Saved runs are not pruned automatically. Task evidence follows the [retention rules](collaboration.md#storage-retention).

Resume reads the saved prepared input and writes to a new directory. It preserves the source run.
Move the complete run directory together. Resume requires the same native build and platform.
Use `--native-library` to select a retained library explicitly when the current build differs.
The GUI load menu can continue a saved run with its recorded interval and input provenance.
New GUI full C++ runs request a save every 60 seconds in `development/runs/` under the user data directory.
The calculation details show the save location. Use Save and Pause, then continue from the load menu.
Lost work can also include the current complete step and file write.

## Connected capabilities and boundaries

| Use | Public entry | Quantity basis |
| --- | --- | --- |
| Rectangular full 2D/3D | `prepare_case`, then `run_case` / `evaluate` | 2D Q is W/m. 3D Q is W. |
| Continuous-field multi-condition 2D/3D optimization | `run_multi_condition_optimization`, through complete Case solves and numerical checks | Default: heat-transfer improvement and relative pressure drop. Core-mass mode: kg with per-condition heat and pressure limits. 2D totals use explicit depth. |
| Quick Design | `prepare_quick_design`, then the same APIs | Prescribed-velocity LTNE and analytical inlet loss, without full SIMPLE. Q is W. |
| Parameter scans and effective-field input | [Public examples](../examples/) | No private solver members are changed. |
| Offline cleaning and Nu fitting | `preprocess.offline` | Explicit sources. No automatic production-model replacement. Previous RBF publication is retired. |

Current GUI continuous optimization keeps the full case's ports, fluids, and dimensional solver settings. It supports air A / water B and two-fluid pairs with CO₂/sCO₂. Default ranges are L=4–8 mm and t=0.3–0.6 mm. The solver validates each fluid's Nu applicability independently. `optimization.json` stores all conditions, controls, field definitions, failures, and native batch paths. It and `batch.json` record the selected `backend`, including failures and cancellation, without local library paths.

Only fully qualified numerical batches receive objective values. Model-h keeps its existing energy checks. True-h uses its own convergence, unclipped enthalpy, coupled-energy, and equation-energy evidence. GUI Pareto application keeps complete fields. Different current geometry, ports, or solver settings cause rejection. Arbitrary external CLI configurations are not GUI presets. Evaluation count is a search budget, not proof of algorithm convergence or experimental accuracy.

Previous air/air optimization screening, its 2D entry, and frozen-B 3D solving are retired. See [history](history/retired-tools.md). Previous result archives stay readable. Pareto CSV geometry stays exportable with its original configuration. Retired screening modes cannot execute or recompute metrics.

Current domains support only **rectangular 2D / cuboid 3D**. The interface displays the shape directly without a one-option menu. Hexagonal/octagonal routes are retired. Previous polygon configurations fail before loading and keep current inputs/results. Polygon startup sessions are neither restored nor converted into rectangles.

Previous rectangular files still load. [Fixed history](history/retired-tools.md) keeps polygon code. Reopening those routes requires implementation and verification of mainline physical rules and independent module handoff.

`python/physical_models/`, `python/physical_models/df_surrogate/`, and related layers give shared technical support, not a fourth business module. Previous pipeline/application entries call public modules in one direction. See [architecture](architecture.md).

C++ is the only numerical backend. Quick Design and full 2D/3D use the matching local macOS arm64 or Windows x64 library. `RunControl(native_library=...)` or CLI `--native-library` can override its location. See [C++ migration](cpp-migration.md) for paths, builds, and limits.
See [C++ scope and delivery records](cpp-migration.md#cpp-core-scope) for each implementation boundary.
Visible desktop delivery, complete performance and experimental accuracy need separate checks.

Full 2D uses ABI 2. Distribute matching libraries, headers, and adapters. The former Python outer-loop/C++ sweep hybrid is retired. Python numerical and research-only entries are retired. Saved results remain readable; ordinary cases use current `ComputeConfig` preparation. OpenFOAM, REFPROP, extended h/f/PEC definitions, and adjoints stay under M-B and original scope limits. Directories or interfaces do not show implementation.

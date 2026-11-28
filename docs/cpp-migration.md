# C++ numerical backend and integration

[中文](cpp-migration.zh-CN.md) | [English](cpp-migration.md)

## Architecture and backend boundary

TM1 follows a three-stage computation flow:

```text
application -> preprocess.api -> CaseData -> solvers.api -> FieldResult
                                                           -> postprocess.api -> PerformanceResult
```

Version 0.2 uses C++ as the only numerical backend.
Python keeps public application APIs, configuration, DTOs, file I/O, caches, optimization, GUI, and CLI.
Full 2D, full 3D, and Quick Design run on macOS arm64 and Windows x64.
Linux x86_64 supports independent result evaluation only.
Public `RunControl` and CLI calls default to `backend="cpp"`.
The native library path is a host control and is not stored in `CaseData`.
Missing libraries, ABI mismatches, or missing required symbols fail explicitly with no numerical fallback.
See [C++ migration history](history/cpp-migration-history.md) for version 0.1–0.2 migration stages, retired `v1`–`v11` ABIs, and archived qualification records.

<a id="cpp-core-scope"></a>

## C++ core scope

Four independent C++ shared libraries own all production numerical calculations:

| Library | Source directory | Active ABI and role |
| --- | --- | --- |
| Geometry | [geometry](../geometry/) | Geometry ABI 2 and field ABI 3: cell geometry, chi/Kss, grids, ports, splines, sigmoid, LUTs, zones. |
| Preparation | [preprocess](../preprocess/) | Preparation ABI 3 and Quick Design preparation v2: properties, Nu closures, fixed D-F, 2D/3D and Quick preparation. |
| Solver | [solver](../solver/) | Saved 2D ABI 5, saved 3D ABI 3, capture ABI 2, and Quick Design run v2. |
| Result | [postprocess](../postprocess/) | Result ABI 3 (`float64` + `int32` labels): metrics, physical balances, applicability, zone statistics, and qualification. |

All active C++ stage interfaces normalize numeric buffers to `float64` and zone labels to `int32`.
The [source map](../python/README.en.md) lists C++ edit locations by responsibility.
See [kept Python responsibilities](architecture.md#retained-python-responsibilities) for the exact Python boundary.
Pure-formula test oracles remain under `tests/python/` as independent regression references.
PR CI, merged-main CI, desktop delivery, cell-cap memory checks, real 3D BO, performance, and experimental validation stay separate gates.

<a id="native-geometry-core"></a>

## Native geometry core

The independent geometry core in [geometry](../geometry/) calculates standard, CO2, and asymmetric cell geometry, plus chi and solid conductivity.
It also calculates grids, ports, six-direction axis maps, continuous XY/XYZ splines, sigmoid fields, linear LUTs, discrete zones, and Gaussian filtering.
One shared file (`tpmshx_geometry_shared`) provides all of these operations.
It uses only the C++ standard library, the marching-cubes port, and a restricted C17 FITPACK subset.
It does not link CoolProp, SuperLU, AMGCL, Eigen, or the solver runtime.
See [architecture](architecture.md#native-grids-and-design-fields) for grid and field ownership, and [fields-sources.md](../geometry/fields-sources.md) for provenance and BSD notices.

`python/cpp_interface/_native_geometry.py` loads `tpmshx_geometry_shared` on demand through ctypes.
Geometry, grid, and zone calls use geometry ABI 2, where status 2 reports a domain error.
Continuous, sigmoid, and LUT calls use field ABI 3, where status 2 reports an allocation failure.
Call buffers are borrowed with explicit element counts, and failure leaves caller outputs unchanged.
XY spline handles and LUT objects keep a reference to their creating library until release.

Use `libtpmshx_geometry_shared.dylib` on macOS arm64 or `tpmshx_geometry_shared.dll` on Windows x64.
Source checkouts load from `native/lib/<host>/`, and frozen desktop packages load from `native/`.
Set `TPMSHX_GEOMETRY_LIBRARY` to an absolute prebuilt path to select another geometry library.
Historical result reading and offline postprocessing do not load this library.
After any C++ or compiled model-data edit, rebuild the affected libraries and restart the process.

To fetch the locked CMake tool and publish geometry alone on macOS:

```sh
tm1_python="$(sed -n '1p' .venv-path)"
tm1_lock=engineering/requirements/base.txt
"$tm1_python" engineering/scripts/build_native_dependencies.py fetch-cmake
"$tm1_python" engineering/scripts/build_native_dependencies.py publish --component geometry --python-lock "$tm1_lock"
```

On Windows PowerShell:

```powershell
$tm1Python = Get-Content .venv-path -TotalCount 1
$tm1Lock = 'engineering/requirements/base.txt'
& $tm1Python engineering/scripts/build_native_dependencies.py fetch-cmake
& $tm1Python engineering/scripts/build_native_dependencies.py publish --component geometry --python-lock $tm1Lock
```

Select `bo-macos.txt` or `bo-windows.txt` when `.venv-path` points to a BO environment.
Use `build --component geometry` and `verify --component geometry` to run steps separately with the same `--cache`.
Standalone builds write to `.cache/native-deps/build/geometry-<host>` by default.
Geometry-only publication updates `geometry-build.json` and keeps previous differing libraries under `previous/`.
Default full publication builds and validates all four libraries before one transaction publishes them together.
Each library writes its own build record (`build.json`, `geometry-build.json`, `preparation-build.json`, `result-build.json`) with `source_commit` and `source_changes`.
Failed replacement rolls back staged files and reports recovery paths.
Old solver checkpoints still require their exact kept solver runtime, prepared inputs, and controls.

Full and application CI tiers build all four libraries and publish them as artifacts for downstream native and BO jobs.
The Python wheel includes Python modules and model resources, without native libraries.
Desktop packaging requires all four prebuilt libraries; see [desktop builds](desktop.en.md#可选冻结打包).

<a id="native-preparation-core"></a>

## Native preparation core

The independent preparation core in [preprocess](../preprocess/) calculates fluid properties, Nu closures, fixed D-F tables, experiment corrections, row projection, and complete 2D/3D/Quick preparation.
Its CMake targets (`tpmshx_preparation`, `tpmshx_preparation_c`, `tpmshx_preparation_shared`) reuse geometry and shared property implementations with the locked CoolProp static library.
This project needs no solver runtime, `run_state`, SuperLU, or AMG.

`python/cpp_interface/stage_libraries.py` loads preparation ABI 3 independently on demand.
Preparation ABI 3 uses flat `(abi_version, struct_size)` input structs, unified `tpmshx_preparation_callbacks_v1`, and clean `v1` family entry names.
Its status codes are 0 for success, 1 for invalid input, 2 for allocation, 3 for runtime error, and 10/11/12 for water/CO2/sCO2 state errors.
See [native stages](native-stages.md) for every active 2D, 3D, inlet-query, and Quick Design preparation entry:

- [Inlet-property query](native-stages.md#inlet-property-query): `tpmshx_query_inlet_properties_v2` returns 12 `float64` values with no grid or solver.
- [Spatial total mass flow](native-stages.md#spatial-total-mass-flow): capacity, flow resolution, and complete 2D preparation for uniform, continuous XY, discrete zone, and sigmoid inputs.
- [Spatial host cache interface](native-stages.md#spatial-host-cache-interface): `preparation_host.py` and `tpmshx_preparation_callbacks_v1` cache transport without numerical host callbacks.
- [Existing offset geometry](native-stages.md#existing-offset-geometry): nonzero `delta_levelset` nominal thermal-side geometry and split rules.
- [Uniform 3D preparation](native-stages.md#uniform-3d-preparation): uniform, continuous XY/XYZ, and XY grid-rectangle 3D preparation with `preparation_case_3d_c_api.h`.
- [Quick Design stage](native-stages.md#quick-design-stage): `tpmshx_prepare_quick_design_v2` and `tpmshx_quick_pressure_fractions_v2` with `tpmshx_quick_callbacks_v2`.

Shared JSON and CSV authorities live in [model-resources.en.md](model-resources.en.md#当前资源与研究输出).
2D and 3D preparation share `tpmshx_preparation_df_experiment_scope_v1` for layout and HX campaign-domain checks.
Private `scalar_range_samples.hpp` keeps at most eight air-field scalar observations per side (original notices, extrema, and last sample) while full raw-array records keep all cells.

Separate preparation publication needs locked sources, locked CMake, and a built CoolProp archive in the same cache.
Run `fetch` and `build --component coolprop` first if CoolProp is absent.
Then run on macOS:

```sh
tm1_python="$(sed -n '1p' .venv-path)"
tm1_lock=engineering/requirements/base.txt
"$tm1_python" engineering/scripts/build_native_dependencies.py publish --component preparation --python-lock "$tm1_lock"
```

On Windows PowerShell:

```powershell
$tm1Python = Get-Content .venv-path -TotalCount 1
$tm1Lock = 'engineering/requirements/base.txt'
& $tm1Python engineering/scripts/build_native_dependencies.py publish --component preparation --python-lock $tm1Lock
```

On macOS, preparation links `coolprop-preparation-macos-arm64/libCoolProp.a` compiled with `-Os`, while the solver links `coolprop-macos-arm64/libCoolProp.a`.
Windows links one locked `Release/CoolProp.lib` archive for both roles.
Each archive keeps a `coolprop-build.json` record that publication copies into library metadata.
The runtime file is `libtpmshx_preparation_shared.dylib` on macOS arm64 or `tpmshx_preparation_shared.dll` on Windows x64.
Set `TPMSHX_PREPARATION_LIBRARY` to select another prebuilt path, or `TPMSHX_NATIVE_PREPARATION_LIBRARY` for desktop packaging.
Use `engineering/scripts/check_distributions.py --output-dir .cache/<dir>` to build and validate source and wheel distributions.

<a id="native-result-core"></a>

## Native result core

The independent result core in [postprocess](../postprocess/) implements Result ABI 3.
It calculates engineering metrics, signed physical balances, zone statistics, applicability checks, and qualification verdicts in `float64` with `int32` zone labels.
The standalone `postprocess/` project uses only C++17 and system libraries.
It links no solver, preparation, geometry, CoolProp, Qt, or model-resource files.
See [postprocess/sources.md](../postprocess/sources.md) for buffer layouts, error codes, and notices.

The query in `python/cpp_interface/result_evaluation.py` loads the result library on demand through `_native_result.py`.
Pure Python imports and HDF5/JSON reads stay native-free.
`tpmshx_result_stage_query_v3` accepts flat `tpmshx_stage_input_v3` with borrowed `float64` arrays, `int32` labels, and raw C-string mode/unit labels.
Floating-point events emit fixed `RuntimeWarning` diagnostics for divide-by-zero, overflow, and invalid values.

The runtime image is `libtpmshx_result_shared.dylib` (macOS), `tpmshx_result_shared.dll` (Windows), or `libtpmshx_result_shared.so` (Linux x86_64).
Set `TPMSHX_RESULT_LIBRARY` to select an alternate absolute path.
Linux x86_64 permits `fetch-cmake`, `build`, `verify`, and `publish` with `--component result` only.
In a minimal postprocessing environment recorded in `.venv-path`:

```sh
tm1_python="$(sed -n '1p' .venv-path)"
"$tm1_python" engineering/scripts/build_native_dependencies.py fetch-cmake --component result
"$tm1_python" engineering/scripts/build_native_dependencies.py publish --component result --python-lock engineering/requirements/postprocess.txt
```

CI builds and tests the result library on Ubuntu 24.04 and 26.04 alongside full macOS/Windows builds.
The `minimal-postprocess` job runs on Ubuntu 24.04 with `result-build-linux-x86_64-ubuntu-24.04` and saved real 2D/3D handoff files from macOS.

## Solver cores and execution interfaces

The solver library in [solver](../solver/) implements full 2D, full 3D, Quick Design, SIMPLE flow, model-h, temperature, and T-SOU conservative energy drivers.
The saved stage-run lifecycle is the only solver execution interface for Python and for C and C++ callers.
The native bindings in `python/cpp_interface/` are `full_2d_stage.py`, `full_3d_stage.py`, and `quick_design.py`.
The solver hosts in `python/solvers/full_2d.py`, `python/solvers/full_3d.py`, and `python/solvers/quick_design.py` validate saved cases and build the public `FieldResult`.

- **Full 2D (`full_2d.hpp`, `stage_run_c_api.h`)**: saved stage ABI 5 (`tpmshx_run_saved_case_2d_v5`, `create_saved_v5`, `restore_saved_v5`). Owns SIMPLE with fixed-density Anderson, inlet pressure shooting, property/thermal coupling, Richardson refinement, and final certificates. Main heat duty uses W/m.
- **Full 3D (`full_3d.hpp`, `stage_run_3d_c_api.h`)**: saved stage ABI 3 (`tpmshx_run_saved_case_3d_v3`, `create_saved_v3`, `restore_saved_v3`) and capture ABI 2. Owns XYZ SIMPLE, optional coarse bootstrap (`tpmshx_full_3d_get_bootstrap_trace_v1`), thermal-first outer coupling, and final certificates. Main heat duty uses W.
- **Quick Design (`quick_design_driver.hpp`, `quick_design_stage_c_api.h`)**: `tpmshx_run_quick_design_v2` runs const or mean property passes on saved prepared fields with fixed analytical pressure fractions and `physical_validation=not_established`.
- **Raw result queries (`full_2d_c_api.h`, `full_3d_c_api.h`)**: `tpmshx_full_{2,3}d_get_*_v1` read the `raw` result that a stage result borrows. Release only the stage result. The [C++ migration history](history/cpp-migration-history.md) records the retired direct-solve and per-driver C entries.
- **Execution reports (`execution_report.cpp`)**: `tpmshx_stage_run_2d_report_v1` and `tpmshx_stage_run_3d_report_v1` publish resolved grids, fluids, states, property samples, and model-h balances.

See [run continuation](native-stages.md#run-continuation) and [native 3D execution](native-stages.md#native-3d-execution) for exact ownership, checkpoint restoration, and control defaults.

Public Python execution passes the library path through `RunControl`:

```python
from tm1.run_control.module_ports import RunControl
from tm1.solvers.api import run_case

result = run_case(prepared_case, RunControl(
    backend="cpp", native_library="/absolute/path/to/libtpmshx_solver_shared.dylib"))
```

Source CLI execution uses:

```bash
"$PYTHON" main.py solve case.h5 results.h5 --backend cpp \
  --native-library /absolute/path/to/libtpmshx_solver_shared.dylib
```

### T-SOU conservative energy and actual-state audit

`solve_enthalpy` in `enthalpy_driver.hpp` runs `EnthalpyAlgorithm::temperature_sou` (T-SOU) for two-fluid true-h routes.
Each nonlinear step freezes actual `h`, `T`, and `cp` arrays, then runs alternating A, B, and solid sweeps with minmod enthalpy face reconstruction.
The driver damps each completed block increment by `0.6`.
Guarded HEOS PT updates refresh actual enthalpy before residual and boundary-duty checks, with no BICUBIC table, H-to-T inversion, or enthalpy clipping.
SOU recipe 2 applies six-sample Anderson proposals and accepts a proposal only when it strictly lowers the normalized coupled and equation residual maximum.
Only a complete ordinary PT/audit block can converge.
`tpmshx_energy_algorithm_version_v1` reports the actual executed recipe version independently of the C ABI.

`thermal_energy_audit` in `solver/enthalpy_sweeps.cpp` computes actual-state A/B/solid cell residuals and six outward signed boundary enthalpy duties.
Its coupled and equation ratios use `max(abs(Q_A), abs(Q_B), 1)` in W/m (2D) or W (3D).
This operator applies no acceptance threshold; drivers enforce the `0.001` coupled and equation gates and the Kelvin update gate.
Portable candidate results set `thermal_mode=conservative_energy` and record `boundary_fluxes.true_h.boundary_power`; heat is `-sum(boundary_power)` per side with no fallback reconstruction.

<a id="shared-finite-volume-temperature-consumers"></a>

## Shared finite-volume temperature consumers

Private `energy_fv_rows.hpp` supplies shared finite-volume transport, Fourier conduction, LTNE exchange, and physical-source row assembly.
Each caller owns its fluid model, face preparation, EOS updates, iteration budget, and convergence policy.
CMake applies a source-local no-contraction floating-point setting to every source file that instantiates these shared rows.

| Consumer | Driver and kept contract |
| --- | --- |
| Quick Design const/mean and standalone CC | `solve_temperature` in `temperature_driver.cpp` uses fixed pass coefficients, capacity transport, and `<= 1e-7` complete-boundary ratio. Guarded-line steps run up to 4 point sweeps plus a `0.6`-damped line-Newton trial. |
| Air/water full 2D temperature and full 3D CC (`Nz = 1`) | Strict `solve_model_h_2d`: integral `h(T)`, A-SOU/B-FOU (`model_h_tface_sou_fou_strict_v3`), prepared mass/K/`h_v`, physical depth scaling for 3D `Nz = 1`, and `<= 1e-7` complete-boundary ledger. |
| Air/water full 3D CC (`Nz > 1`) | Strict `solve_model_h_3d`: integral `h(T)`, SOU on both sides (`model_h_tface_sou_sou_strict_v3`), prescribed B reservoir support, asymmetric geometry, strict water/water, and `<= 1e-7` complete-boundary ledger. |
| Product model-h | Non-strict `solve_model_h_2d` / `solve_model_h_3d` with original eligibility and stopping rules. |
| Full 3D true-h preparation | `true_h_preparation` validates CC inputs and projects staggered faces with zero temperature sweeps before the EOS solve. |
| Staggered/MAC research | Existing projection, cache, and capacity-face preparation without fullCC integral-h qualification. |
| True-h | T-SOU default in `enthalpy_driver.cpp` with independent EOS relations and physical gates. |

FullCC captures `model_enthalpy_temperature_v1` through `tpmshx_full_{2d,3d}_get_model_enthalpy_evidence_v1` before later flow updates.
Each solved fluid stores `[c0, c1, c2, Tbase, Tref]` for quadratic `cp(T)`, solved-phase flags, residuals, source/reservoir powers, and outward `m*h(T_face)` and Fourier planes.
Nonzero fullCC manufactured volume sources stay unsupported, and prescribed B has reservoir power without a solved B residual certificate.
See [C++ migration history](history/cpp-migration-history.md) for historical N3, N5, and pre-N3 qualification records.

## Build and run native qualification checks

Locked native dependencies are defined in [dependencies-lock.toml](../engineering/native_build/dependencies-lock.toml).
They include CoolProp 8.0.0 (nine pinned CPM headers) and SuperLU 7.0.1 (three SciPy 1.18.1 double-LU corrections).
They also include AMGCL 1.5.0, Eigen 5.0.1, and CMake 4.4.4.
Third-party notices are recorded in [THIRD_PARTY_NOTICES.md](../engineering/native_build/licenses/THIRD_PARTY_NOTICES.md).
`engineering/scripts/generate_native_model_coefficients.py` generates `tpmshx/model_coefficients.hpp` and `tpmshx/preparation_df_data.hpp` under `.cache/native-deps/generated/` using only the Python standard library.

### Standalone EOS-free thermal archive check

With an existing POSIX C++17 compiler, `make`, and locked Eigen headers under `.cache/native-deps/src/Eigen-5.0.1` (`fetch-eigen`):

```sh
make -f engineering/native_build/Makefile CXX=c++
make -f engineering/native_build/Makefile check
```

From an x64 Visual Studio developer command prompt on Windows:

```bat
nmake /f engineering\native_build\Makefile.msvc check
```

This builds `.cache/native/libtpmshx_thermal.a` (or `tpmshx_thermal.lib`) with `EIGEN_MPL2_ONLY` and runs independent C++ temperature and conservative-energy tests without Python, CoolProp, or Qt.

### Full dependency build and native pytest suite

When you configure a native component directly, `TPMSHX_BUILD_QUALIFICATION` defaults to `ON`.
It enables the component's test callers. The solver also builds Python test libraries, including the libraries that record model-h history.
The native dependency build enables qualification. The top-level SDK disables it for each component, including previously configured build directories.
`check-stages` uses separate SDK component directories under `build/stages-<host>/` in the selected cache.

Use the interpreter from `.venv-path` after passing environment checks:

```sh
tm1_python="$(head -n 1 .venv-path)"
"$tm1_python" -m tm1.development.runs.tools.check_locked_environment
"$tm1_python" -m pip check
"$tm1_python" engineering/scripts/build_native_dependencies.py fetch
"$tm1_python" engineering/scripts/build_native_dependencies.py build
"$tm1_python" engineering/scripts/build_native_dependencies.py verify
MPLCONFIGDIR="$PWD/.cache/matplotlib" \
XDG_CACHE_HOME="$PWD/.cache/xdg" \
TPMSHX_REQUIRE_NATIVE_DEPS_TESTS=1 \
"$tm1_python" -m pytest -q tests/python/native
```

`fetch` provisions locked archives; `build` and `verify` run offline and install no Python packages.
SuperLU calls run behind a pure-C error boundary with a thread-local allocation ledger so allocation failures and `ABORT` return bounded errors after cleanup.
macOS SuperLU links system Accelerate BLAS; Windows links locked portable CBLAS sources.
Pressure systems with at most 2,000 cells use SuperLU/COLAMD.
Larger 3D systems use classical algebraic multigrid with BiCGStab (200-iteration budget, L2-scaled retry on breakdown).
Every `TPMSHX_TRUE_H_KERNEL` override (`numba`, `cpp_sweeps_v1`) is retired and fails before flow execution.
`TPMSHX_REQUIRE_NATIVE_DEPS_TESTS=1` turns any missing native library or caller into a test failure.
A local macOS pass does not establish Windows compilation, execution, or desktop acceptance.

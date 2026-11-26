# SJTU-TPMSHX-TM1 architecture

[中文](architecture.zh-CN.md) | [English](architecture.md)

## System overview and three public stages

Version 0.2 uses C++ as the only numerical backend.
Full 2D, full 3D, and Quick Design run on macOS arm64 and Windows x64.
Linux x86_64 supports independent result evaluation only.
Production domain shapes are limited to rectangular 2D and cuboid 3D domains.
Three explicit public stages connect full runs:

```text
applications -> preprocess.api -> CaseData -> solvers.api -> FieldResult
                                                          -> postprocess.api -> PerformanceResult
                         data_types / physical_models / model_configs / file_io / run_control
```

Quick Design, saved-case runs, offline evaluation, and run recovery enter at their matching stage.
Missing native libraries, ABI mismatches, or missing active symbols fail explicitly with no numerical fallback.

## Four native libraries

Four independent C++ shared libraries own all production numerical work:

| Library | Source | Active ABI and role |
| --- | --- | --- |
| `tpmshx_geometry_shared` | [geometry/](../geometry/) | Geometry ABI 2 and field ABI 3: TPMS cell geometry, chi/Kss, grids, ports, splines, sigmoid fields, LUTs, and zones. |
| `tpmshx_preparation_shared` | [preprocess/](../preprocess/) | Preparation ABI 3 and Quick Design preparation v2: properties, Nu closures, fixed D-F, 2D/3D preparation, and scalar inlet queries. |
| `tpmshx_solver_shared` | [solver/](../solver/) | Saved 2D ABI 5, saved 3D ABI 3 (capture ABI 2), and Quick Design run v2: SIMPLE flow, model-h, temperature, and T-SOU conservative energy. |
| `tpmshx_result_shared` | [postprocess/](../postprocess/) | Result ABI 3 (`float64` arrays and `int32` zone labels): metrics, physical balances, applicability checks, zone statistics, and qualification. |

Shared coefficients, bounds, and defaults come from [model_parameters_v1.json](../python/model_configs/model_parameters_v1.json) and [preparation_df_v1.json](../python/model_configs/preparation_df_v1.json).
`engineering/scripts/generate_native_model_coefficients.py` generates native C++ headers from these files with the Python standard library only.
See [include/tpmshx/](../include/tpmshx/), [tests/cpp/](../tests/cpp/), [C++ integration](cpp-migration.md#cpp-core-scope), [native stage SDK](native-stages.md), and [C++ migration history](history/cpp-migration-history.md).

## Source, import, and native library name map

| Name or path | Role and consumers |
| --- | --- |
| Source folder [python/](../python/) | Contains the Python source tree. `[tool.setuptools.package-dir]` in [pyproject.toml](../pyproject.toml) maps `sjtu_tpmshx` to `python`. |
| Import name `sjtu_tpmshx` | Public package name used by every repository import and CLI module command. |
| Checkout loader [sjtu_tpmshx.py](../sjtu_tpmshx.py) | Loads `python/__init__.py` as `sjtu_tpmshx` when commands run from the repository root. |
| Installed wheel layout `sjtu_tpmshx/` | Packs Python modules and declared JSON, CSV, and icon resources from `pyproject.toml`, without native libraries. [check_types.py](../engineering/scripts/check_types.py) builds the same tree through [python_source.py](../engineering/packaging/python_source.py) for `mypy`. |
| Alias resolver [python/shared.py](../python/shared.py) | Resolves historical `sjtu_tpmshx.shared.*` and `sjtu_tpmshx.solvers.backends.cpp.*` paths to canonical owners without code duplication. [python/solvers/backends/cpp.py](../python/solvers/backends/cpp.py) imports its search path. [packaging_support.py](../tests/python/packaging_support.py), [test_three_module_imports.py](../tests/python/architecture/test_three_module_imports.py), and [test_distribution_contents.py](../tests/python/test_distribution_contents.py) test these aliases in checkouts and wheels. Local `.cache/` scripts also use them. |
| Live library directory `sjtu_tpmshx/solvers/native/lib/<host>/` | Git-ignored path where [build_native_dependencies.py](../engineering/scripts/build_native_dependencies.py) publishes the four libraries for source runs. `provenance.py` defines `PUBLISHED_LIBRARY_DIR`; `module_ports.py`, `stage_libraries.py`, `_native_geometry.py`, and `launch-macos.command` read it. Frozen desktop builds load `native/`. Run `build_native_dependencies.py verify-published` with the `.venv-path` interpreter for the [published native image check](verification.en.md#published-native-images). It compares published exports against the geometry, preparation, solver, and result manifests and prints each build record (`build.json` and `*-build.json`). |

## Directory owners

This table gives the contents of each directory. Do not duplicate correlations or physical constants between these layers.
The [Python layer owners](#python-layer-owners) table gives the responsibilities of the Python directories.

| Path | Contents |
| --- | --- |
| [preprocess/](../preprocess/), [solver/](../solver/), [postprocess/](../postprocess/) | C++ preparation, solving, and evaluation. |
| [geometry/](../geometry/) | C++ geometry. |
| [numerics/](../numerics/) | Common numerical functions. |
| [include/tpmshx/](../include/tpmshx/) | C and C++ headers. |
| [tests/cpp/](../tests/cpp/) | Native caller tests. |
| [python/applications/](../python/applications/) | Application workflows. GUI components are in `gui/ui/` and controllers are in `gui/controllers/`. |
| [python/preprocess/](../python/preprocess/) | Python preparation stage. It produces new `CaseData`. |
| [python/solvers/](../python/solvers/) | Python solver stage. It produces new `FieldResult`. |
| [python/postprocess/](../python/postprocess/) | Python evaluation stage. It produces new `PerformanceResult` and `MetricValue`. |
| [python/data_types/](../python/data_types/) | Portable types, including the stage data types. |
| [python/physical_models/](../python/physical_models/), [python/model_configs/](../python/model_configs/) | Models with standalone model queries and their caches, and model resources. |
| [python/file_io/](../python/file_io/), [python/run_control/](../python/run_control/) | File I/O and run controls. |
| [python/cpp_interface/](../python/cpp_interface/) | Native calls. |
| [tests/python/](../tests/python/) | Python tests. |
| [python/development/](../python/development/) | Validation and tools. |
| [engineering/](../engineering/) | Build scripts, packaging, and dependency locks. |

## Binding import limits

Bindings in `python/cpp_interface/` obey these import limits.
`python -m sjtu_tpmshx.development.runs.tools.audit_import_graph --fail-on-violations` checks them.

- A binding can import `run_control`, `model_configs`, and `data_types` modules, but not the modules of the stage data types.
- The stage data types are `CaseData`, `ModelRef`, `FieldResult`, `MetricSpec`, `MetricValue`, and `PerformanceResult`.
  A binding does not build these types. It imports them only under `TYPE_CHECKING`.
- The exception is `python/cpp_interface/preparation_host.py`. It imports `ModelRef` for the check of a saved model reference.
- A binding does not import stage, application, physical-model, file I/O, `compute`, or development modules.

<a id="retained-python-responsibilities"></a>

## Python layer owners

Python owns public APIs, configuration, immutable DTOs, file I/O, caches, warning formatting, and applications under [python/](../python/).
Numerical code stays free of Qt.
GUI code is in `python/applications/gui/ui/` (`Main_Menu` is in `main_window.py`) and `python/applications/gui/controllers/`. The launch entries are `python/applications/gui/main.py` and `python/desktop.py`.
The window creates `SingleRun`, `OptimizationPage` and `QuickDesignPage`. Each owner starts and cancels its job and tracks worker exit. `Workbench` selects views. `FieldResults` publishes results, `ResultExport` writes data and figures, and `CaseFiles` reads and writes cases, presets and workspace sessions. The Qt-free `applications/optimization/optimization_job.py` decodes study inputs and conditions.

| Layer | Owner path | Responsibility |
| --- | --- | --- |
| Public entries and apps | [compute.py](../python/compute.py), [applications/](../python/applications/) | Runs the three stages. Owns GUI, CLI, Quick Design sizing, multi-condition BO, `result_adapter`, and run recovery. |
| Stage APIs | [preprocess/](../python/preprocess/), [solvers/](../python/solvers/), [postprocess/](../python/postprocess/) | Defines `prepare_case`, `run_case`, and `evaluate`, plus offline fitting, `physical_ledger`, `result_math`, `result_display`, and export. |
| Native bindings | [cpp_interface/](../python/cpp_interface/) | Loads the four native libraries on demand, normalizes `float64`/`int32` buffers, and emits fixed `RuntimeWarning` diagnostics. |
| Models and resources | [physical_models/](../python/physical_models/), [model_configs/](../python/model_configs/) | Owns model queries, `preparation_cache.py`, `zone_units.py`, and versioned JSON and CSV resources. |
| Data, I/O, and controls | [data_types/](../python/data_types/), [file_io/](../python/file_io/), [run_control/](../python/run_control/) | Owns `ComputeConfig`, `CaseData`, `FieldResult`, `PerformanceResult`, `metric_spec`, file I/O, cancellation, and provenance. |
| Validation and oracles | [development/](../python/development/), [tests/python/](../tests/python/) | Owns validation and run tools. Keeps pure-formula test oracles outside runtime wheels. |

See [kept Python responsibilities](numerical-contracts.md#retained-python-responsibilities) for cache sizes and boundary rules, and [Python source map](../python/README.en.md) for module entry points.

## Cross-directory C++ edges

The four shipped shared libraries have no shared-library link cycle.
Each CMake scope builds an independent image.
Only `preprocess/` and `solver/` link separate static CoolProp archives; `geometry/` and `postprocess/` link no CoolProp.
Six compile-time source and header edges cross C++ directories:

| Edge | Source or header sites | Reason |
| --- | --- | --- |
| `preprocess/` <-> `numerics/` | `preprocess/preparation_properties.hpp` includes `../numerics/property_kernels.hpp`. `numerics/df_summary.cpp` includes `tpmshx/preparation_df.hpp`. | `preprocess/preparation_property_points.cpp` defines the six preparation adapter functions. `numerics/fluid_properties.cpp` defines the shared property kernels. The preparation and solver builds use the same D-F summary function. |
| `solver/` -> `postprocess/` | `solver/CMakeLists.txt` compiles `postprocess/result_{core,arithmetic,metrics,balance}.cpp` into hidden static target `tpmshx_capture_math`. `solver/stage_capture_2d.cpp` includes `../postprocess/result_zone_capture.hpp`. | Reuses exact result arithmetic during solver capture and keeps `tpmshx_result_shared` standalone with no solver dependency. |
| `solver/` -> `preprocess/` | `solver/CMakeLists.txt` compiles `preprocess/preparation_{df_corrections,flow}.cpp`. `solver/stage_saved_models.hpp` includes `../preprocess/preparation_nu.hpp`. `solver/quick_design_run.cpp` includes `../preprocess/preparation_c_boundary.hpp`. | Reuses D-F correction, `closure_geometry_ratio`, Nu-route, and C-boundary rules without linking `tpmshx_preparation_shared`, so static CoolProp registries stay separate. |
| `preprocess/`, `solver/` -> `geometry/` | Both CMake files add `geometry/` as a subdirectory. `preprocess/preparation_case.cpp` includes `../geometry/field_{continuous,lut,sigmoid}.hpp`. Five preparation and solver files include `../geometry/field_c_boundary.hpp`. | Compiles grid, port, field, and C-boundary helpers statically into each isolated stage build. |
| `geometry/` <-> `numerics/` | `include/tpmshx/geometry.hpp` includes `tpmshx/fluid_properties.hpp` for `Topology`. `geometry/{grid,zones}.cpp` include `../numerics/contiguous_sum.hpp`. `include/tpmshx/pressure_reference.hpp` includes `tpmshx/ports.hpp`; `pressure-reference.cmake` links `tpmshx_grid` directly and `models.cmake` links it transitively. | Shares the topology enum, deterministic summation helper, and physical port-fraction code across geometry and pressure-reference targets. |
| Stages -> `numerics/`, shared Quick header | `preprocess/` and `solver/` include `../numerics/contiguous_sum.hpp` and compile `numerics/df_summary.cpp`. `preprocess/` and `postprocess/` include `../numerics/scalar_range_samples.hpp`. `solver/` and `postprocess/` compile `numerics/recorded_report.cpp`. `include/tpmshx/quick_design_stage_c_api.h` includes preparation, solver, and result C headers. | Shares deterministic sums, range sampling, report encoding, and the single Quick Design stage C interface across stages. |

## Detailed contracts

Detailed numerical, runtime, UI, and physical contracts are in [numerical and runtime contracts](numerical-contracts.md):

- <a id="native-grids-and-design-fields"></a>**Grids, design fields, and geometry ABIs**: [native grids and design fields](numerical-contracts.md#native-grids-and-design-fields) (FITPACK, splines, ABI 2/3 status codes, CO2 factors, total mass flow).
- <a id="native-preparation-solver-and-evaluation-stages"></a>**Preparation, solver routes, and execution records**: [native stages and thermal routes](numerical-contracts.md#native-preparation-solver-and-evaluation-stages) (SIMPLE F2, Anderson settings, T-SOU, model-h, fullCC, Quick Design, `full_execution_v1`).
- <a id="result-qualification-by-route"></a>**Qualification and physical balances**: [result qualification by route](numerical-contracts.md#result-qualification-by-route) and [physical balance evidence](numerical-contracts.md#physical-balance-evidence).
- <a id="captured-parameter-limits"></a>**Applicability bounds and verdicts**: [captured parameter limits](numerical-contracts.md#captured-parameter-limits) (`[0.9 * L, 1.1 * U]` policy) and [common result verdict](numerical-contracts.md#common-result-verdict).
- <a id="native-3d-continuation"></a>**Interfaces, continuation, and optimization**: [persistent interfaces](numerical-contracts.md#persistent-interfaces-and-physical-state) and [2D/3D continuation, cancellation, and BO](numerical-contracts.md#native-3d-continuation).
- <a id="ui-structure"></a>**Desktop UI and result cache**: [UI structure](numerical-contracts.md#ui-structure) (user storage, preflight, workbench modules, `ResultCache`, exports).
- <a id="physical-invariants"></a>**Physical constraints and `sF` windows**: [physical invariants](numerical-contracts.md#physical-invariants) (12 core invariants, frozen `sF` constants, and calibration velocity windows).
- <a id="local-data"></a>**Raw data layout**: [local data](numerical-contracts.md#local-data) and the [data catalog](data-catalog.en.md).

Companion documents: [public data contract](contracts/three_module_v1/README.md), [capabilities](capabilities.en.md), [model resources](model-resources.en.md), and [verification guide](verification.en.md).

<a id="extension-points"></a>

## Extension points

Use the [contributor extension guide](extending.md) to find rule owners, public interfaces, downstream consumers, and tests.
It gives full routes for a fluid, Nu closure, or GUI panel or dialog, plus a short topology route.
Keep one production path for each dimension without extra wrappers for single implementations.

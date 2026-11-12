# Native stage interfaces

[中文](native-stages.zh-CN.md) | [English](native-stages.md)

## Scope

The native stage work adds independent preparation, execution and evaluation
interfaces. Python keeps the public entry points and their existing data contracts.
Symmetric uniform and canonical continuous XY 2D preparation use the native stage.
Nonzero-delta uniform, discrete zones, sigmoid and 3D use their explicit existing routes.
A native loading or execution error does not select another route. Preparation v1 supports
uniform, symmetric 2D air/air with prescribed inlet velocity and CFD drag.
Preparation v2 supports all 16 ordered pairs of air, water, sCO2 and CO2 in that
geometry and inlet mode. It keeps existing experimental DF and sCO2 Nu choices,
state checks and application limits. Each side retains its selected model evidence.
Run v2 consumes preparation v2 through the existing model-h or true-h driver.
Run v1 retains its air/air CFD scope and published layout.
Nonzero delta, zones, continuous fields and prescribed mass flow remain outside
this preparation v2 scope. These limits do not remove existing Python modes.
Quick Design keeps its native-double v1 preparation and run interfaces for air, water and sCO2.
Preparation v2 adds typed raw inputs and an independent pressure-fraction query.
Python uses v2 preparation with fixed named host operations for its existing value protocols.
The preparation/query fluid registry includes CO2; this does not expand the existing air/water/sCO2 LTNE run scope.

Full 2D/3D Python evaluation now calls the native result stage. Independent applicability, physical-balance and qualification queries use that stage.
The native result stage owns Quick Design metrics and retains typed intermediate values. V3 uses fixed named host operations for existing Python object, exact integer and final conversion protocols. The public Python entry points and saved formats stay available.
The host query uses borrowed typed evidence and preserves deferred input errors. It delivers NumPy events before each primitive returns.
A callback error is handled at the original metric or qualification boundary. An uncaught host error retains its original Python object.
Published v1 C layouts and queries remain available. Release every output through the library that created it.

Preparation v3 adds total mass flow for the same uniform symmetric 2D fluid matrix.
It provides separate capacity and inlet-flow resolution queries, plus complete preparation.
It preserves the existing physical depth, calibration and scalar arithmetic rules.
Continuous fields, zones and nonzero delta remain outside v3. The run interface is unchanged.

The C++ call sequence is `prepare_case`, `run_case`, then `evaluate`.
The caller supplies dimensions, design values, boundary conditions and controls.
The preparation library computes the physical fields. The solver library uses
that prepared state. The result library evaluates recorded evidence.

## Ownership and units

- Use the units in the input field names. The design input uses mm. Saved
  physical design fields use m. Preserve the existing mm-to-m-to-mm operations
  when the execution adapter makes its transport and closure inputs.
- The requested grid counts and the actual grid counts are different fields.
  Physical 2D fields have shape `(nx, ny)` and C order. Flow fields use the
  existing `(cross, stream)` order for each side.
- A successful call that returns owned arrays has one owner. Its array and text views belong to that owner.
  Release it through the same library after the last use. Do not copy owners or free their buffers with a caller allocator.
  Scalar-only queries, including Quick pressure fractions v2, return values and need no release.
- Callbacks receive borrowed event views on the caller thread. They do not
  perform numerical preparation. Keep event order, logger names and messages.
- Result v3 carries raw labels and typed Quick operands. C++ owns label comparisons and metric policy.
  Fixed named host callbacks retain Python value protocols at the selected operation.
  Object equality and inequality use separate callbacks; string subclasses keep their original operators.
- The host owns case IDs, timestamps, file paths and Python object conversion.
  The native stages own physical rules, numerical defaults and evidence.
- Preparation and solver libraries use their separate locked CoolProp builds.
  The result library does not link preparation, solver, CoolProp or Qt.
- Preparation v2 adds explicit scalar precision, strength and layout tags.
  Its buffers use double transport. Result tags retain the original field precision.
  The failure result retains state details and exception causes for the host.
  The host still owns Python-specific type and object checks.
- A CO2 side selects the common CO2 geometry for both sides. Its fixed drag
  and Nu factors apply only to CO2 sides. sCO2 remains a separate model.
  Experimental DF changes flow seeds and rows. Static inlet DF values keep
  their existing CFD values, including the CO2 factors where applicable.
- Existing low-level ABI versions remain available. A retained run library
  must not need a new preparation symbol to restore its saved run state.
- Run v2 records actual thermal mass, boundary power, energy settings and
  certificates for result evaluation. It copies preparation notices and keeps
  the current sCO2 scope limit. It does not certify an unverified model.
- Run v2 uses the v1 result owner and release function. Its cancellation
  status is 6; status 4 retains the full driver's envelope failure meaning.
  Run v1 keeps its original cancellation status of 4.

## Uniform total mass flow

`FlowInput2D` selects stored per-side targets or an explicit pair of total targets.
A stored target replaces only that side's speed and remains in the resolved input.
An explicit pair replaces both stored targets and clears them in the resolved input.
All total targets use kg/s and require a positive physical depth in m.
The prepared 2D fields and solver quantities retain their per-unit-depth basis.

`prepare_inlet_mass_capacities` uses the physical inlet pore area, profile and inlet density.
It does not use an obsolete speed or evaluate Nu. It calculates both side capacities.
`resolve_inlet_flow` divides each selected target by its capacity, then validates resolved speeds.
Without targets, it returns a copied input without physical validation or capacity work.
The Python adapter retains its existing no-target object identity rule.

`prepare_case(FlowInput2D)` reuses the physical inlet grid and geometry for final preparation.
Its preliminary flow records stay in `flow.evidence`. Final records stay in `prepared`.
Callbacks report both phases in execution order. A complete flow-case result owns both views.
Their nested owner fields are null; release only the complete result.
Depth and target tags retain the existing floating and integer scalar arithmetic.
Python object validation and configuration snapshots remain host responsibilities.

## Continuous XY fields

Preparation v4 uses `ContinuousInput2D` for canonical continuous XY controls.
It supports prescribed speed and the v3 total-flow queries and preparation.
It keeps all v1/v2/v3 C layouts. Python adapts its owned result to the existing CaseData schema.
The control input gives integer counts, order 1..3, a y-mirror flag, bounds and decisions.
Decisions contain L values followed by t values, in mm and C order.
With y mirroring, each field stores its lower half, including an odd central row.
The existing geometry bounds apply to controls and clipping bounds.

The existing spline core samples actual physical cell centres.
Fixed-flow preparation reuses those fields when it resolves inlet speeds.
The complete result carries the existing prepared and preliminary flow views.
It adds four physical-cell arrays: area density, original hydraulic diameter and two fluid conductivities.
Local permeability and Forchheimer arrays use each side's existing `(cross, stream)` view.
Rows retain their pressure-seed role. The complete local fields remain available to the run adapter.

CFD mode supports both topologies and all 16 ordered fluid pairs.
Experimental transfer retains the Shanghai Gyroid air-A/water-B contract at nominal 7/0.6 mm.
Its domain, velocity rules and exploratory evidence remain unchanged.
The CO2/CO2 fixed-factor path also remains available in experimental mode.
Early range labels retain their transfer context. Final metadata retains the continuous application scope and reference geometry.
These preparation interfaces do not change the run interface or certify gradient accuracy.

## Python preparation adapter

The public preparation, capacity and resolution entries use v3 or v4 for supported 2D inputs.
The adapter copies arrays, scalar types and evidence before it releases the native owner.
Stored cases keep their schema, SI fields, controls and model references.
Preliminary mass-flow records remain outside the final preparation warning scope.

V3/v4 calls can use `tpmshx_preparation_case_callbacks_v2` through its `values` member.
That member declares version 2 and the complete descriptor size.
The optional host hook runs at final preparation entry, nominal geometry and each side's inlet-property boundary.
It checks Python object rules at their original execution points. It supplies no numerical value.
A hook exception requests cancellation; Python raises the original exception after the C call returns.
The v1 callback descriptor and all input/result layouts remain unchanged.

The v3 callback descriptor extends v2 with named geometry and inlet-property cache exchanges.
Its range and notice hooks report each observation at its original calculation point.
The host keeps warning filters, source locations and completed observations when a later step fails.
Cached records do not repeat standalone notices. Warning exceptions stop the native operation.
Use `values.values`, version 3 and the complete descriptor size.
A cache miss uses the C++ calculation. The host can return a completed cached value and its raw range records.
Lookup views stay valid until the stage returns. Publication views stay valid only during the callback; copy them before return.
Nested views must not overlap result, failure or error storage. Invalid storage leaves those outputs unchanged.
The shared Python owners retain the 32768-entry geometry cache and 4096-entry inlet-property cache.
They preserve untyped keys, LRU order, statistics, clearing, concurrent publication and `__wrapped__` access.
Equal keys retain the first successful value's scalar types. Material conductivity and chi stay outside these caches.

Continuous-only Python field, local-drag and reused-spline branches are retired from production preparation.
The frozen 2026-11-11 reference under `development/tests/preparation_*_reference.py` qualifies the native stage and adapter.
It is not a production route. Retain it while independent preparation comparison requires that reference.

## Build and install

Use the setup and locked dependency commands in [README](../README.en.md).
The new CMake entry only uses prepared local dependencies. It does not fetch
sources, install Python packages or replace published runtime libraries.

Generate the two model headers with the interpreter from `.venv-path`:

```sh
"$PYTHON" -m engineering.scripts.generate_native_model_coefficients \
  --output .cache/stages/generated/tpmshx/model_coefficients.hpp \
  --df-output .cache/stages/generated/tpmshx/preparation_df_data.hpp
```

Use the locked CMake executable. On macOS, supply the distinct preparation and
solver archives from the accepted native dependency cache:

```sh
"$CMAKE" -S sjtu_tpmshx/solvers/native -B .cache/stages/build \
  -DTPMSHX_NATIVE_DEPS_ROOT="$PWD/.cache/native-deps" \
  -DTPMSHX_MODEL_INCLUDE_DIR="$PWD/.cache/stages/generated" \
  -DTPMSHX_PREPARATION_COOLPROP_LIBRARY="$PWD/.cache/native-deps/build/coolprop-preparation-macos-arm64/libCoolProp.a" \
  -DTPMSHX_SOLVER_COOLPROP_LIBRARY="$PWD/.cache/native-deps/build/coolprop-macos-arm64/libCoolProp.a" \
  -DCMAKE_INSTALL_PREFIX="$PWD/.cache/stages/install"
"$CMAKE" --build .cache/stages/build --config Release --parallel 1
"$CMAKE" --install .cache/stages/build --config Release
```

Windows uses `-A x64` and the locked `Release/CoolProp.lib` archive for both
roles. Use the paths in the accepted dependency cache. The separate component
projects keep their existing compiler options and exported symbols.

Set `-DTPMSHX_COMPONENTS=result` for an independent result-only build. It does
not require model headers or EOS dependencies. Linux supports this component
only. An installation contains the selected shared libraries, C ABI headers,
CMake package configuration and applicable source notices.

An external C++ project can use the installed package:

```cmake
find_package(tpmshx CONFIG REQUIRED COMPONENTS result)
target_link_libraries(my_program PRIVATE tpmshx::result)
```

The [external result client](../examples/cpp/result_client.cpp) checks arrays and evaluates historical evidence through public headers.
The [complete 2D example](../examples/cpp/air_2d.cpp) starts with raw dimensions, conditions and boundaries.
It prepares, solves and evaluates the case without numerical fields from Python.
It does not start or link Python.
The [fluid preparation example](../examples/cpp/prepare_fluids_2d.cpp) prepares a CO2/water case through v2.
It links only the preparation library and does not execute a solve.
The [uniform-fluid example](../examples/cpp/uniform_2d.cpp) executes all three
stages for CO2/water. Evaluation remains valid after the prepared owner is released.
The [Quick Design example](../examples/cpp/quick_design.cpp) starts with raw
operating points and dimensions. It calls `prepare_quick_design`, `run_case`
and `evaluate` through the existing v1 contract.
The [typed Quick preparation example](../examples/cpp/prepare_quick_design.cpp) uses `QuickDesignInputV2`.
It calls `pressure_fractions` and `prepare_quick_design`, with only the preparation library.
It does a check of owned fields and absent counterflow qtol/chunk controls without starting a solve.
The [mass-flow preparation example](../examples/cpp/prepare_mass_2d.cpp) queries capacities, resolves an explicit pair and prepares the case.
It also links only preparation and does not execute a solve.
The [continuous preparation example](../examples/cpp/prepare_continuous_2d.cpp) starts with XY decisions and total flow.
It exposes physical fields and local drag through v4, with only the preparation library.
These examples use only installed public headers and shared libraries.
The Windows build copies the required DLLs beside each executable.

```sh
"$CMAKE" -S examples/cpp -B .cache/stages/examples \
  -DCMAKE_PREFIX_PATH="$PWD/.cache/stages/install"
"$CMAKE" --build .cache/stages/examples --config Release
"$CTEST" --test-dir .cache/stages/examples -C Release --output-on-failure
```

C++ preparation, run and evaluation objects can move but cannot copy.
The run result owns all evidence needed for evaluation. The caller can release the prepared object after `run_case`.
The C headers specify ownership and borrowed views for direct C calls.
A null metric request returns all metrics for the mode.
A selected metric retains its units, definition version, status and reason.
Independent applicability, physical-balance and qualification queries use the same result library.

After the dependency build, this check reuses component build directories and installs a temporary SDK.
It builds and runs external callers outside the source tree:

```sh
"$PYTHON" engineering/scripts/build_native_dependencies.py check-stages
```

Use the applicable environment lock. A BO environment needs its matching `--python-lock` option.
On Linux, add `--component result --python-lock engineering/requirements/postprocess.txt`.
The check retains logs, 2D comparison fields and Quick Design comparison fields. It removes the temporary installation and external build directories.
The uniform run path does not establish stage migration for fixed flow, zones or 3D.
Python integration and checkpoint recovery have separate acceptance gates.

## Quick Design stage

`quick_design_stage_c_api.h` keeps the native-double v1 preparation and run contracts.
Its separate preparation v2 contract adds `tpmshx_prepare_quick_design_v2` and `tpmshx_quick_pressure_fractions_v2`.
No published v1 layout changes. `quick_design_prepare_v2.cpp` owns both new numerical sequences.
The preparation library reuses geometry, grid, property and analytical D-F implementations.
The solver library uses the existing Quick Design driver. The result library evaluates its recorded fields and final-pass scalars.

### Typed raw preparation and pressure query

The v2 input contains 13 typed scalars: cell length, wall thickness, span, length, height, conductivity, tolerance, two mass flows, two temperatures and two pressures.
Cell length and wall thickness use mm. Dimensions use m, temperature uses K, pressure uses Pa(abs), and mass flow uses kg/s.
Text fields have explicit byte lengths. Native callers supply all scalar slots; `have_height=0` replaces the height slot with span.
Without host hooks, the stage reads no environment variables and uses the fixed CFD D-F table.
The Python host keeps method, chi, raw object and snapshot protocols at their original boundaries.

Crossflow keeps `(60, 40, 1)` and counterflow keeps `(60, 1, 2)`.
The shared `model_parameters_v1.json` resource supplies grid counts, geometry resolution, conductivity, tolerance and arrangement controls.
Python reads this resource; native preparation uses generated constants.
The Python defaults remain 16 W/(m K), `1e-5` and geometry resolution 128.
V2 keeps absent counterflow qtol/chunk through `have_q_relative_tolerance=0` and `have_chunk_iterations=0`.
CaseData stores both as `None`. Execution resolves them with the existing kernel defaults.
V1 continues to return its resolved driver configuration, including `max(tol*10, 1e-4)` and chunk 250 for counterflow.

Full preparation keeps this sequence: warm-start checks, labels, positive inputs, shape, geometry/material, grids and operating snapshot.
It then evaluates A/B inlet properties, sections, A/B pressure states and pressure fractions.
The configuration snapshot follows pressure work. Design fields, mm-to-m conversions and final environment/model snapshots follow it.
This order keeps the point of each warning, error, conversion and cache observation.

The pressure query uses the geometry/material and inlet-pressure sequence only.
It skips full preparation validation, thermal grids, design-field arrays, configuration snapshots and final unit conversions.
Every non-`cross` arrangement uses counterflow sections in this query only.
The full preparation entry still validates its supported arrangement and property-mode labels.
The query keeps inlet property, liquid-water and analytical pressure checks. It does not execute a thermal solve.

Initialize v2 descriptors with ABI 2 and their exact `struct_size`. Initialize the full result with `owner=NULL`.
Failure leaves result storage unchanged. Input, output and error storage must be disjoint. Error storage must be writable and nonempty.
Full output owns widths, edges, copied initial fields and design fields, plus typed fractions and stored controls.
Array data uses double transport; precision tags keep the original field dtype for the host copy.
Release the full output with `tpmshx_quick_prepared_release_v2` from its creating library.
The pressure output contains only fractions and pressure evidence by value; it has no owner.
`stages.hpp` supplies `QuickDesignInputV2`, `PreparedQuickDesignV2`, `prepare_quick_design` and `pressure_fractions`.
The v2 output has no new run overload. Python maps it to CaseData for the existing run adapter.

### Fixed host operations

`tpmshx_quick_callbacks_v2` is optional for native typed input.
Set `raw_objects=0` for native inputs and observations. Set it to 1 for the Python raw-object protocol, which requires a host callback.
C++ selects every operation and numerical branch. A host operation can pack raw operands or perform its named object operation.
It cannot call geometry, property, pressure or solver numerical implementations.
Completed geometry-cache exchanges have their separate callback.
Requests and observation views are borrowed. Keep packed input buffers valid until the next callback or the end of the native call. Copy observations before the callback returns.
A nonzero callback return stops the stage with status 20. Python raises the saved original exception after the C call.
Completed warning and cache observations remain visible when a later step fails.

The table omits the `TPMSHX_QUICK_` prefix. `side` is 0 for A and 1 for B.
Property indices are rho, mu, k, cp and Pr. Scalar slots follow the order stated in each row.
Fields described as observations are read-only. Other listed fields carry raw packing or fixed operator results from the host.

| Operation | Host boundary and request fields |
| --- | --- |
| `WARM_CHECK`, `LABEL_CHECK` | Do checks of the original warm objects and labels; no numerical output. |
| `POSITIVE_SNAPSHOT`, `POSITIVE_CHECK` | Read inputs once in original order; `index` selects one of the 13 inputs, `flags[0]` returns its finite-positive result. |
| `SHAPE_CHECK` | Do a check of warm-field shape; `flags[0]` returns the crossflow selection. Native constants supply the grid counts. |
| `GEOMETRY_PACK` | Pack cell/wall in `scalars[0:2]`; `flags[0:3]` carry topology, cell precision and ratio precision. |
| `MATERIAL_PACK` | Observe `geometry`; pack conductivity and chi in `scalars[0:2]`, topology/chi-present/precision in `flags[0:3]`. `index=1` selects final conductivity with chi=1. |
| `WIDTH_PACK` | `index` selects x/y/z; pack raw length in `scalars[0]` and array precision in `flags[0]`. |
| `OPERATING_SNAPSHOT` | Capture original operating values and resolved DF options; no numerical output. |
| `PROPERTY_ENTRY` | Open the side's range scope; return the validated fluid label in `text`. |
| `STATE_PACK`, `PROPERTY_PACK` | Pack broadcast operands in `property_inputs`. `flags[0]` identifies the fluid; state `flags[1]` selects scalar EOS return shape. Property `index` selects the getter. |
| `EOS_CACHE_LOOKUP` | `flags[0]` identifies sCO2 or CO2. Return a hit in `flags[1]` and the completed scalar value or five-value bundle in `property_values`. The stage copies and checks the view. |
| `EOS_CACHE_STORE` | Observe a completed scalar result in `property_values` and publish it through the existing cache owner. No calculation is permitted. |
| `PROPERTY_RESULT` | Observe property arrays, kind, category and floating events. Restore the host scalar/array and deliver NumPy events. |
| `PRANDTL_PACK` | Pack mu, cp and k in `property_inputs`, with `imaginary_inputs` and `categories` for the original value protocols. |
| `SECTIONS_PACK` | Pack porosity, span, length and height in `scalars[0:4]`; `flags[0]` returns the original crossflow comparison. |
| `SECTIONS_RESULT` | Observe A area/length and B area/length in `scalars[0:4]`; keep original host length objects. |
| `PRESSURE_ENTRY` | Read the side's raw inlet values and copy DF options at the original pressure boundary. |
| `FLOW_PACK`, `FLOW_RESULT` | Pack mass flow, area and density in `scalars[0:3]`; `flags[0]` returns the original air comparison. Observe mass flux and velocity in result `scalars[0:2]`. |
| `PRESSURE_COMPARE` | `flags[0]` returns the separate original air comparison for pressure selection. |
| `PRESSURE_PACK` | `flags[0:3]` carry air, topology and strict. Air packs mass flux/T/P/mu/length in `scalars[0:5]`; other fluids pack velocity/rho/mu/length in `scalars[0:4]`. Cell length is `scalars[5]`; wall thickness is `property_kind`. |
| `PRESSURE_RESULT` | Observe `pressure`; deliver floating events and the existing pressure-limit warning or error. |
| `FRACTION_PACK` | Pack the saved pressure-drop value and original inlet pressure in `scalars[0:2]`; C++ performs division. |
| `CONFIG_SNAPSHOT` | Apply the original `asdict` conversion after pressure work. |
| `UNIT_PACK`, `UNIT_RESULT` | `index` selects cell/wall. Pack the raw scalar for native division; `flags[0]=1` keeps a custom object's division protocol in the host. Observe the native conversion when the flag is zero. |
| `FINAL_SNAPSHOT` | Capture environment and ModelRefs at their original final boundary. |
| `FAILURE` | Observe status, text, property failure and phase in `flags[1]`; deliver events and map the original exception and cause. |

The geometry cache callback uses action 0 for lookup and action 1 for publication.
A hit supplies a completed geometry value and sets `hit=1`; a miss sets `hit=0` and C++ computes the value.
Python keeps the shared cache key, hit/miss behavior and original stored value types. It does not add a Quick-only cache.
The EOS operations share `sco2_props._prop` and `co2_props._scalar`, including their original 4096-item limit and keys.
sCO2 looks up scalar entries before state validation; CO2 validates first. Arrays bypass both scalar caches.
Only successful native calculations publish values. External property calls and cache clearing use these same owners.
The replaced `shared/models/quick_design.py` is removed. Its frozen reference in `development/tests/quick_prepare_reference.py` remains for independent regression checks.
`preprocess/app_modes/quick_design.py` only assembles CaseData from copied native fields and host snapshots.

### Prepared execution and evidence

The existing v1 run stage copies supplied prepared fields without new preparation or mutation.
Constant properties use one thermal pass; mean properties use two. The second pass uses the first pass's returned temperatures.
Analytical inlet pressure fractions remain fixed through both passes.
The result owns all 15 fields, physical grid widths, pressure evidence, final-pass scalars and complete driver pass records.
Cancellation returns status 6 and publishes no result. The driver has no per-call CPU setting; existing process thread controls apply.

Python passes a borrowed view of saved CaseData and copies returned fields and declarations before releasing the native result.
The original grid, fixed-field dtypes, mass rates and inlet temperatures remain in the public result.
Python keeps saved-case validation, warning routing and exception mapping. The native result stage owns Quick Design evaluation.
A preparation example does not establish complete N12 delivery. Numerical, packaging, CI and independent review gates remain separate.
Quick Design remains a sizing approximation. Numerical convergence does not establish physical validation, applicability or design qualification.

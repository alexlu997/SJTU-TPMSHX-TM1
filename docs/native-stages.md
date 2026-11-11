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

Preparation v3 adds total mass flow for the same uniform symmetric 2D fluid matrix.
It provides separate capacity and inlet-flow resolution queries, plus complete preparation.
It preserves the existing physical depth, calibration and scalar arithmetic rules.
Continuous fields, zones and nonzero delta remain outside preparation v3.
Its resolved uniform prepared view uses run v2, including total-flow cases.

The separate 3D preparation v1 accepts raw symmetric uniform cases at prescribed inlet speeds.
It supports both topologies, all 16 ordered fluid pairs and the existing CFD and experimental DF selections.
Its physical grid, typed ports and field evidence do not change the Python 3D production route.
The [uniform 3D preparation contract](#uniform-3d-preparation) defines its inputs and remaining gates.

Full 2D/3D Python evaluation now calls the native result stage. Independent applicability, physical-balance and qualification queries use that stage.
Quick Design metric arithmetic retains its current protocol owner. The public Python entry points and saved formats stay available.
The host query uses borrowed typed evidence and preserves deferred input errors. It delivers NumPy events before each primitive returns.
A callback error is handled at the original metric or qualification boundary. An uncaught host error retains its original Python object.
Published v1 C layouts and queries remain available. Release every output through the library that created it.

The supported 2D C++ call sequence is `prepare_case`, `run_case`, then `evaluate`.
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
- A successful C call returns one owner. All array and text views belong to
  that owner. Release it through the same library after the last use.
  Do not copy owners or free their buffers with a caller allocator.
- Callbacks receive borrowed event views on the caller thread. They do not
  perform numerical preparation. Keep event order, logger names and messages.
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
  In 2D, experimental DF changes flow seeds and rows. Static inlet DF values keep
  their existing CFD values, including the CO2 factors where applicable.
- Existing low-level ABI versions remain available. A retained run library
  must not need a new preparation symbol to restore its saved run state.
- Run v2 records actual thermal mass, boundary power, energy settings and
  certificates for result evaluation. It copies preparation notices and keeps
  the current sCO2 scope limit. It does not certify an unverified model.
- Run v2 uses the v1 result owner and release function. Its cancellation
  status is 6; status 4 retains the full driver's envelope failure meaning.
  Run v1 keeps its original cancellation status of 4.

## Run continuation

`Run2D` accepts the uniform v2 or continuous v4 preparation view.
It supports creation, step advancement, phase queries, snapshots, restoration
and result transfer. It uses the existing full 2D state machine and typed state.
It does not reset consumed work. Restoration requires the same build, prepared
inputs and numerical controls. The positive CPU thread limit can change.

Keep the preparation owner alive and unchanged until result transfer or run release.
The run copies numerical inputs and controls. It borrows preparation evidence for capture.
Keep callback context alive until run release. Calls on one run must not overlap.
Snapshots own independent storage. A completed result also owns its evidence
after preparation and run release. Use the creating library for all queries and releases.
Cancellation cannot publish a successful stage result.

`RunRequest2Dv3` adds six independent optional energy controls and the optional
enthalpy-update gate. Missing values use the selected library's defaults.
These controls require the existing true-h route. They cannot be combined with
the complete explicit-energy pointer or active model-h controls.
Existing one-shot interfaces retain their layouts and behavior.
Symmetric uniform and continuous 2D Python runs and checkpoints use the saved-input interface.
`SavedCase2D` borrows a validated v2 view and saved thermal geometry. It does not prepare the case again.
Uniform saved inputs can include cell thermal geometry and local drag while keeping uniform closure mode.
Missing range records and empty records stay distinct. Uncaptured rows do not receive numerical samples.
Saved scalar and field kinds retain the original unit-conversion and closure-ratio precision.
With model-h controls, the saved interface checks the requested energy algorithm before execution.
It does not pass two sets of iteration controls to the numerical driver.
Keep inputs and range flags valid until result transfer or run release.

Python checks the selected library capability before execution. Archived libraries, nonzero delta and unported zone modes use their existing protocol.
An incomplete new protocol or a failed run is an error. All queries, state releases and result releases use that same selected library.
Saved formats, same-build restoration, CPU-change rules and public Python interfaces stay unchanged.

## Capture scalars

`capture_summary(result, application)` returns copied scalars from the completed stage.
It retains main and fine model-h area and cell counts, Nu floor observations,
main thermal pressure limits, signed duty sum, absolute duties and pressure clip counts.
The area and reductions reuse the existing result arithmetic, linked statically.
The solver has no new shared result-library dependency.

Supply the two saved application area densities and surface heat-transfer coefficients.
They are separate from the solver's thermal geometry and final h_v fields.
The query multiplies each pair after the existing nonnegative check.
NaN, infinity and signed zero retain their existing arithmetic behavior.
The copied summary owns no pointers and remains valid after result release.
Use existing raw evidence queries for fields, histories and numerical ledgers.
The Python production mapper and its historical-runtime route remain unchanged.

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
Run v3 consumes preparation v4 through the existing model-h or true-h driver.
It uses the supplied physical cell fields and local drag in their existing order.
The saved SI cell lengths first return to mm, then produce transport SI and closure ratios.
Nominal reference geometry remains separate from the actual physical fields.
Requests, cancellation status, result ownership and evaluation use the v2 run contracts.
This interface does not certify gradient accuracy.

## Uniform 3D preparation

`prepare_case(CaseInput3D)` calls `tpmshx_prepare_case_3d_v1` from
`preparation_case_3d_c_api.h`. It returns an owned `PreparedCase3D`.
Provide three positive physical lengths, three grid counts and an explicit cell cap.
Depth is required and `Nz` must be at least 2. The C++ input defaults the cap to 2,000,000 cells.
The host resolves configuration and environment limits before the call; the library does not read them.

Both sides require active ports. The interface supports all six flow directions,
full faces, partial ports and optional second transverse windows.
Port values retain their scalar tags. Uniform and `port_wall_refine` grids use the existing physical grid rules.
Fields have physical `(x,y,z)` shape and C order. Opening masks use physical `(cross1,cross2)` order.
Each side records its axis permutation and reverse flag without reversing the physical widths.

The owner retains nominal geometry, physical widths and edges, design fields,
inlet properties, model selections, ranges, notices and DF application evidence.
Side porosity already includes the symmetric split. Do not divide it again.
The returned K/cF fields retain the unscaled CFD values.
Side evidence records CO2 or experimental factors separately for later execution.
Keep the original state checks, calibration limits and sCO2 Nu selections.

This interface borrows its inputs and v1 event callbacks until return.
Success commits one owner; failure does not publish a prepared result.
Release the owner through the creating preparation library after the last use of its views.
Spatial fields, nonzero delta and total mass-flow targets are outside this interface.
Python 3D preparation, host cache hooks, native 3D run/capture integration,
memory checks near the cell cap and real 3D BO remain separate migration and acceptance gates.
Saved CaseData still uses its existing validators and must not be prepared again.

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
The [3D preparation example](../examples/cpp/prepare_3d.cpp) prepares raw CO2/water inputs with different physical lengths and grid counts on each axis.
It checks the reverse z-direction port and field evidence, with only the preparation library.
The [uniform-fluid example](../examples/cpp/uniform_2d.cpp) executes all three
stages for CO2/water. Evaluation remains valid after the prepared owner is released.
The [mass-flow preparation example](../examples/cpp/prepare_mass_2d.cpp) queries capacities, resolves an explicit pair and prepares the case.
It also links only preparation and does not execute a solve.
The [continuous preparation example](../examples/cpp/prepare_continuous_2d.cpp) starts with XY decisions and total flow.
It exposes physical fields and local drag through v4, with only the preparation library.
The [continuous run example](../examples/cpp/continuous_2d.cpp) starts with XY decisions and fixed mass flow.
It prepares, runs and evaluates the case, then releases the prepared owner before evaluation.
The [continuation example](../examples/cpp/resume_2d.cpp) creates a run from raw inputs,
retains a flow snapshot, releases the run and restores it with a different CPU limit.
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
The check retains logs and 2D comparison fields. It removes the temporary installation and external build directories.
These 2D run paths and raw 3D preparation do not complete migration for discrete zones, 3D or Quick Design.
Python integration and checkpoint recovery have separate acceptance gates.

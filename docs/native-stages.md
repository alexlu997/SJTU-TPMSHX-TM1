# Native stage interfaces

[中文](native-stages.zh-CN.md) | [English](native-stages.md)

## Scope

The native stage work adds independent preparation, execution and evaluation
interfaces. The existing Python entry points remain the production route until
the corresponding stage passes its acceptance checks. Preparation v1 supports
uniform, symmetric 2D air/air with prescribed inlet velocity and CFD drag.
Preparation v2 supports all 16 ordered pairs of air, water, sCO2 and CO2 in that
geometry and inlet mode. It keeps existing experimental DF and sCO2 Nu choices,
state checks and application limits. Each side retains its selected model evidence.
Run v2 consumes preparation v2 through the existing model-h or true-h driver.
Run v1 retains its air/air CFD scope and published layout.
Nonzero delta, zones, continuous fields and prescribed mass flow remain outside
this preparation v2 scope. These limits do not remove existing Python modes.
A separate Quick Design entry accepts native double operating points for
air, water and sCO2. It uses the existing prescribed-flow LTNE driver.

Preparation v3 adds total mass flow for the same uniform symmetric 2D fluid matrix.
It provides separate capacity and inlet-flow resolution queries, plus complete preparation.
It preserves the existing physical depth, calibration and scalar arithmetic rules.
Continuous fields, zones and nonzero delta remain outside v3. The run interface is unchanged.

Full 2D/3D Python evaluation now calls the native result stage. Independent applicability, physical-balance and qualification queries use that stage.
The native result stage owns Quick Design metrics and retains typed intermediate values. V3 uses fixed named host operations for existing Python object, exact integer and final conversion protocols. The public Python entry points and saved formats stay available.
The host query uses borrowed typed evidence and preserves deferred input errors. It delivers NumPy events before each primitive returns.
A callback error is handled at the original metric or qualification boundary. An uncaught host error retains its original Python object.
Callbacks do not own query state. Deferred errors keep their exception objects, cause/context links and group members. Earlier tracebacks on those objects are discarded. Query exit clears deferred error references, including input-packing failures; borrowed fields do not wait for cyclic garbage collection.
Published v1 C layouts and queries remain available. Release every output through the library that created it.
Result calls reject a wrong output size or an owner that was not released.
Those rejected calls preserve borrowed inputs, the old output and diagnostic storage.

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
- A successful C call returns one owner. All array and text views belong to
  that owner. Release it through the same library after the last use.
  Do not copy owners or free their buffers with a caller allocator.
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
It keeps v1/v2/v3 C layouts and the existing Python production routes.
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
The [mass-flow preparation example](../examples/cpp/prepare_mass_2d.cpp) queries capacities, resolves an explicit pair and prepares the case.
It also links only preparation and does not execute a solve.
The [continuous preparation example](../examples/cpp/prepare_continuous_2d.cpp) starts with XY decisions and total flow.
It exposes physical fields and local drag through v4, with only the preparation library.

The [uniform-fluid example](../examples/cpp/uniform_2d.cpp) executes all three
stages for CO2/water. Evaluation remains valid after the prepared owner is released.
The [Quick Design example](../examples/cpp/quick_design.cpp) starts with raw
operating points and dimensions. It calls `prepare_quick_design`, `run_case`
and `evaluate`.
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
These native paths do not establish stage migration for fixed flow, zones or 3D.
Python integration and checkpoint recovery have separate acceptance gates.

## Quick Design stage

`quick_design_stage_c_api.h` declares a separate version 1 contract.
It does not change an existing ABI. The preparation library owns geometry,
uniform grids, inlet-state properties and analytical D-F pressure fractions.
The solver library calls the existing Quick Design driver. It does not run SIMPLE.
The result library evaluates its recorded fields and final-pass scalars.

Raw cell length and wall thickness use mm. Dimensions use m, temperatures use K,
absolute pressures use Pa, and mass flows use kg/s. Cross flow keeps the
`(60, 40, 1)` grid. Counter flow keeps `(60, 1, 2)`. Optional flags distinguish
an omitted value from an invalid explicit value. Height defaults to span,
solid conductivity to 16 W/(m K), and tolerance to `1e-5`.
The current arrangement budgets, relaxation, chunk sizes and heat tolerance remain.
The fixed CFD table supplies D-F. The host resolves its environment selection
before it calls this native entry. This entry reads no environment variables.

Preparation copies an external warm start. The run copies the prepared fields
and does not change them. Constant properties use one thermal pass; mean
properties use two. The second pass uses the first pass's returned temperatures.
Analytical inlet pressure fractions remain fixed through both passes.
The result owns all 15 fields, physical grid widths, pressure evidence and
final-pass scalars. It also retains the complete driver pass records.
Cancellation returns status 6 and publishes no result. The driver has no
per-call CPU setting; process thread controls keep their existing behavior.

The native double path is distinct from Python's scalar and object protocols.
Python preparation, saved-case validation, warning routing and Quick Design
metric adapters remain active. Numeric arrays, NumPy error policy, arbitrary
integers and objects need their own boundary checks before production changes.
The native example does not establish those checks or complete N12 retirement.
Quick Design remains a sizing approximation. Numerical convergence does not
establish its physical validation, applicability or design qualification.

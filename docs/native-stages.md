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
Its physical grid, typed ports and field evidence do not change Python 3D preparation.
The separate 3D flow v2 adds capacity queries, flow resolution and complete preparation at the resolved speeds.
Continuous v3 adds XY/XYZ controls. Spatial v4 adds XY grid rectangles and the existing global offset rules.
The [uniform 3D preparation contract](#uniform-3d-preparation) defines its inputs and remaining gates.

Full 2D/3D Python evaluation now calls the native result stage. Independent applicability, physical-balance and qualification queries use that stage.
Quick Design metric arithmetic retains its current protocol owner. The public Python entry points and saved formats stay available.
The host query uses borrowed typed evidence and preserves deferred input errors. It delivers NumPy events before each primitive returns.
A callback error is handled at the original metric or qualification boundary. An uncaught host error retains its original Python object.
Published v1 C layouts and queries remain available. Release every output through the library that created it.

Preparation v8 adds capacity, flow resolution and complete preparation for raw air/air stripes, rectangles and sigmoid fields.
It keeps CFD drag, zero delta and separate typed domain and port inputs.
Python spatial routes and caches remain unchanged.

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
The v1 interface excludes total mass-flow targets. The separate `FlowInput3D` v2 supports
`prepare_inlet_mass_capacities`, `resolve_inlet_flow` and `prepare_case` for the same uniform geometry.
Capacity uses the actual physical inlet slice, its side porosity, open area and density.
It ignores old speeds and does not evaluate Nu or experimental velocity windows.
Explicit targets replace both configured mass inputs; mixed inputs retain the other side's velocity.
Resolution without a target copies the input without physical preparation.
Complete preparation builds geometry once, resolves both speeds, then applies the original speed and model checks.
Its final evidence retains static-property observations before resolved-speed preflight and final air/DF observations.
The combined owner exposes borrowed preparation and flow views with null nested owners.
`ContinuousInput3D` v3 adds canonical XY extrusion and true XYZ controls to all three flow operations.
`have_ctrl_z` selects XYZ even when its control count is one. Decisions store all L values, then all t values, with z fastest.
Sampling uses the final physical cell centres. XY and XYZ retain their separate spline rules and optional y symmetry.
The owner keeps raw design geometry and the separate thermal mm-to-m-to-mm path.
It returns full local K/cF, area density, hydraulic diameter and thermal porosity.
The existing continuous Shanghai transfer limits and CO2 factors remain unchanged.
`SpatialInput3D` v4 adds uniform or XY grid geometry with the existing global level-set offset rules.
It supports the same capacity, resolution and complete-preparation operations.
Set `geometry_mode=0` for uniform geometry or `geometry_mode=2` for a nonempty rectangle array.
Rectangle bounds use domain fractions with scalar tags. Each row supplies L/t in mm as doubles.
Assignment uses physical XY cell centres. Later rectangles replace earlier matches; uncovered cells use nominal L/t.
The existing fixed Gaussian filter smooths L and t separately in grid-index units before geometry evaluation.
The prepared fields then extend along z. Raw design geometry and thermal SI conversions remain separate.

Nonzero delta uses one nominal split for the complete domain.
Each side's porosity is the local total porosity multiplied by its global fraction.
Capacity uses that side's actual porosity. K/cF and solid conductivity retain their original symmetric geometry.
The result adds side-B porosity, thermal fields, the split fraction and both thermal side/reference tuples.
Each tuple contains area density, hydraulic diameter, reference area density and reference hydraulic diameter.
At delta zero, both side views share the symmetric array and no side tuple is present.
Uniform inputs have no local thermal arrays. Grid inputs retain complete thermal arrays.
Grid and offset geometry retain the existing air/water scope, state checks and experimental calibration restrictions.
In particular, grid experimental preparation remains unsupported; uniform air/air core calibration keeps its existing offset support.
The owner copies rectangle and text inputs. Nested prepared and flow views have null owners.
The v1/v2/v3 C layouts remain unchanged.
Python 3D preparation and host cache hooks remain separate gates.
Memory checks near the cell cap and real 3D BO also need separate acceptance.
Saved CaseData still uses its existing validators and must not be prepared again.

## Native 3D execution

`stage_run_3d_c_api.h` connects prepared v1/v2/v3/v4 views to the existing `Full3DRun`.
`run_case` overloads accept uniform, fixed-flow, continuous or spatial C++ preparation owners.
`Run3D` gives create, step, phase, snapshot, restore and result transfer through the same lifecycle.
It keeps the existing thermal-first order and safe phases 1, 2, 6, 7, 8, 9 and 10.
Prepared storage must stay alive and unchanged until result transfer or run release.
Numerical inputs and controls are copied. Callback functions and context must stay alive until run release.

`RunRequest3D` distinguishes absent controls from explicit values.
Default initial and warm SIMPLE budgets are 2000 and 600. The thermal budget is 20000.
An explicit SIMPLE budget sets both flow budgets. Supply saved profile budgets explicitly, including 50000 for full validation.
The stage does not change grid counts. The host resolves environment settings and supplies a positive CPU limit.
Model-h and EOS control conflicts retain their existing rejection rules.
Restore retains exact build, input and control identity. The positive CPU limit can change.

`SavedCase3D` accepts an existing `full3d_input_v1` and recorded preparation evidence.
It does not call raw preparation or replace saved grids, ports, models, K/cF, thermal geometry or solid conductivity.
Missing inlet evidence, an empty recorded set and uncaptured range samples remain distinct.
The Python adapter retains public saved-schema validation before it creates this view.

The result owns the complete raw 3D DTO, generic v1 evidence and a v2 evaluation input.
Use its `evaluation` member with `tpmshx_result_stage_query_v2`. The C++ `evaluate` overload does this.
The v2 input preserves explicit None mass-face records; v1 alone cannot express that state.
It remains valid after preparation and run release. All raw queries must use its creating solver library.
The raw view is borrowed from the stage result and must not be released separately.
Capture uses final SIMPLE fields for pressure and display.
Mass, thermal pressure and energy evidence use the last completed thermal inputs. Heat uses W and mass uses kg/s.
Display and true-h mass aliases have independent array headers and share immutable data buffers.
The independent result library owns metric definitions, reasons, applicability, physical balance and qualification.

C status 1, 2, 3 or 4 means invalid input, water state, arithmetic or native failure.
Status zero means a result was transferred; it does not establish convergence.
A cancelled result retains raw diagnostics with `raw.stop=2` and no completed evaluation evidence.
A successful result can be transferred only once. Output and error buffers must not overlap inputs or each other.
Python full 3D runs and checkpoints use this saved lifecycle after `prepared_3d` validates CaseData.
`full_3d_stage.py` packs recorded evidence and binds the owned run. It does not prepare raw inputs again.
The driver keeps one input pack, callback bridge and complete raw decoder for both protocols.
It selects the complete stage protocol before execution. A partial protocol is an error.
The capture ABI version and query jointly identify the current host protocol.
Archived libraries without both markers retain the existing direct run and restore interfaces, including the earlier raw 3D stage library.
A single missing marker is a partial protocol error.
A stage failure never starts a second run through another interface.

`capture_summary(result, include_audit)` returns cell count, heat-source sum, pressure clip count and Nu statistics.
The optional audit outlet arrays retain the historical display taper. They do not replace physical openings.
Python copies these values before the stage result is released, then uses the single `full_3d_capture.py` assembler.
Direct low-level DTO callers and archived runtimes retain their existing capture calculations.
Those calculations stay until these supported consumers have an accepted replacement.
Public schemas, model choices, warning order and immutable result buffers retain their existing contracts.
Python raw 3D preparation, its host cache hooks, real 3D BO and visible desktop acceptance remain separate gates.

## Discrete zones

Preparation v5 uses `ZonedInput2D` for raw stripes and rectangles.
It accepts air/air, prescribed inlet velocity, CFD drag and zero delta.
Configured or explicit mass targets, experimental drag and sigmoid controls stay outside this interface.
The Python production route and the run interface do not change.
Nonzero-delta uniform preparation also remains outside the native stage interfaces.

Each region gives bounds, a name, L/t and scalar kinds.
Stripes use the first two bounds along x or y and retain stable sorting.
Rectangles use x0/x1/y0/y1 and retain input order, overlaps and partial coverage.
Assignment keeps the existing first-match rule and each layout's gap rule.
The stage samples the requested grid, then the final physical grid.
It projects raw L/t with transverse physical widths before it predicts row D-F.
This order differs from the continuous field's local-coefficient route.

Design porosity, solid conductivity, both fluid conductivities and both volumetric transfer fields retain the existing Gaussian smoothing.
L/t, area density, hydraulic radius and zone IDs are not smoothed.
Separate thermal porosity, area density and diameter come from the raw float64 L/t fields.
The result owns copied region descriptions, per-region properties, physical fields, row drag, ports and ordered evidence.
Only the outer result has an owner. Release it through the matching v5 function.

A raw call starts with empty, bounded geometry and inlet-property caches.
Equal keys retain the first successful scalar types and their completed range records.
Material conductivity uses the current chi and solid conductivity on each call.
This interface accepts the event-only v1 callback. It does not use the shared Python caches or their host hooks.
The existing Python routes and every v1-v4 scope remain available.

## Sigmoid fields

Preparation v6 accepts the existing air/air grid sigmoid controls, prescribed speeds, CFD drag and zero delta.
The input contains at least 36 interleaved L/t values in mm, plus typed inlet and outlet transitions.
The stage uses the first 36 values and samples the requested grid, then the final physical grid.
It keeps the existing ordered blending, clipping, extrapolation notices and row D-F projection.
Sigmoid fields do not use discrete Gaussian smoothing.
Design geometry comes from the LUT; separate thermal geometry comes from raw L/t fields.
Mass targets, experimental drag and nonzero delta remain outside this v6 scope.
The Python production route and its cache policy remain unchanged.

`build_sigmoid_lut` creates an owned native table over the existing training bounds.
Its defaults are 41 cell-length nodes, 31 wall nodes and voxel resolution 256.
It uses raw geometry, including raw degenerate nodes, without Python or disk I/O.
A caller can reuse this resource or supply normalized axes and captured table values.
Each table has its own interpolation flag. In-place table NaNs retain the existing query behavior.
The complete preparation result owns copied controls, fields and evidence.
Its nested views have null owners. Release the LUT and prepared result with their separate v6 functions.
Releasing the LUT does not invalidate an already prepared result.
The event-only v1 callback and earlier ABI layouts remain unchanged.

## Typed domain and ports

Preparation v7 adds `GridKinds2D` for the existing domain lengths and four port values on each side.
It retains NumPy integer and float16/32/64 arithmetic in grids, openings, capacity and spatial sampling.
Pass this descriptor as the second C++ argument and preparation options as the third argument.
The [typed grid example](../examples/cpp/prepare_typed_grid_2d.cpp) checks mixed integer and float16 ports with fixed mass flow.
The C entries use the same descriptor with the existing v3-v6 input and output layouts.
Keep it with a resolved input when preparing that input again. Release results with their original functions.
Earlier C and C++ entries keep weak double domain and port values.
This interface changes no physical scope or saved-file format.

## Spatial total mass flow

Preparation v8 uses `ZonedFlowInput2D` or `SigmoidFlowInput2D` with `GridKinds2D` and preparation options.
Each input contains the existing raw spatial descriptor, depth and target kinds, and an optional explicit target pair.
The six C entries provide capacity, resolution and complete preparation for both spatial input types.
They accept air/air, CFD drag and zero delta. Existing v1-v7 layouts and scopes remain unchanged.

Capacity uses the actual physical inlet slice of design porosity, the opening profile, widths, density and physical depth.
Discrete design porosity retains Gaussian smoothing; sigmoid geometry has no Gaussian filter.
The query does not calculate Nu or transfer coefficients from obsolete inlet speeds.
Resolution applies configured one-side or two-side targets, or an explicit pair, with the existing scalar arithmetic.
Explicit targets clear stored targets. Without targets, resolution copies the raw input without physical preparation.

Complete fixed-flow preparation builds one physical grid and retains its geometry through speed resolution.
Final properties use the resolved speeds. Requested-grid observations, per-call cache order and row D-F projection remain in their original order.
Preliminary records are in `flow.flow.evidence`; final records remain in the prepared view.
These raw operations accept only the event callback. They do not use Python cache hooks.

Capacity and resolution results own copied region names, controls and LUT arrays in their `input` views.
Keep the matching grid descriptor and scalar kinds when using a resolved input again.
Nested owner fields are null. Release only the outer result with its matching v8 release function.
The [spatial flow example](../examples/cpp/prepare_spatial_flow_2d.cpp) uses all six operations and releases original inputs before complete preparation.
It checks ownership and typed ports with a small LUT for the smoke test; it does not qualify the LUT's physical accuracy.

## Python preparation adapter

The public preparation, capacity and resolution entries use v7 with v3/v4 payloads for supported 2D inputs.
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
Callback version 4 retains this layout and adds host validation at stage 3, side 2, before physical grid construction.
The Python adapter uses this point to preserve unsupported object errors after earlier geometry and property checks.
It returns no numerical values. Earlier callback versions do not receive stage 3.
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
The [3D run example](../examples/cpp/run_3d.cpp) prepares, pauses, restores, runs and evaluates a bounded case.
The installed plain-C smoke checks the same lifecycle and cancellation ownership.
The [3D preparation example](../examples/cpp/prepare_3d.cpp) prepares raw CO2/water inputs with different physical lengths and grid counts on each axis.
The [3D mass-flow example](../examples/cpp/prepare_mass_3d.cpp) resolves total flow on reverse inlet faces before complete preparation.
The [continuous 3D example](../examples/cpp/prepare_continuous_3d.cpp) prepares both XY extrusion and XYZ controls with resolved total flows.
It checks the reverse z-direction port and field evidence, with only the preparation library.
The [spatial 3D example](../examples/cpp/prepare_spatial_3d.cpp) prepares overlapping XY rectangles with a nonzero global offset.
It checks capacities, resolved flows, copied inputs and side geometry through the preparation library.
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
The [zoned preparation example](../examples/cpp/prepare_zoned_2d.cpp) starts with raw stripe bounds and per-region L/t.
It returns prepared fields and row drag through v5, with only the preparation library.
The [sigmoid preparation example](../examples/cpp/prepare_sigmoid_2d.cpp) creates the production-resolution LUT and prepares two cases from raw controls.
It reuses the LUT and links only preparation.
The [spatial flow example](../examples/cpp/prepare_spatial_flow_2d.cpp) queries, resolves and prepares zones and sigmoid fields through v8.
It also links only preparation and retains row drag and separate thermal geometry.
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
These interfaces do not complete production preparation migration for discrete zones, 3D or Quick Design.
Python integration and checkpoint recovery have separate acceptance gates.

# Native stage interfaces

[中文](native-stages.zh-CN.md) | [English](native-stages.md)

## Scope

The native stage work adds independent preparation, execution and evaluation
interfaces. Python keeps the public entry points and their existing data contracts.
Uniform, canonical continuous XY and air/air spatial 2D preparation use the native stage.
Preparation v10 includes the existing nonzero-delta uniform and air/air spatial modes.
All supported 3D preparation uses the native host stage.
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

Preparation v3 adds total mass flow for the same uniform symmetric 2D fluid matrix.
It provides separate capacity and inlet-flow resolution queries, plus complete preparation.
It preserves the existing physical depth, calibration and scalar arithmetic rules.
Continuous fields, zones and nonzero delta remain outside preparation v3.
Its resolved uniform prepared view uses run v2, including total-flow cases.

Preparation v8 adds capacity, flow resolution and complete preparation for raw air/air stripes, rectangles and sigmoid fields.
It keeps CFD drag, zero delta and separate typed domain and port inputs.
Preparation v9 connects these symmetric spatial Python routes to the native stage through typed cache hooks.
Preparation v10 retains those hooks and adds nominal asymmetric thermal-side geometry.
It preserves the existing restrictions on continuous fields, CO2/sCO2, experimental models and total mass flow.

The separate 3D preparation v1 accepts raw symmetric uniform cases at prescribed inlet speeds.
It supports both topologies, all 16 ordered fluid pairs and the existing CFD and experimental DF selections.
Its physical grid, typed ports and field evidence also serve Python 3D preparation through host v5.
The separate 3D flow v2 adds capacity queries, flow resolution and complete preparation at the resolved speeds.
Continuous v3 adds XY/XYZ controls. Spatial v4 adds XY grid rectangles and the existing global offset rules.
The [uniform 3D preparation contract](#uniform-3d-preparation) defines its inputs and remaining gates.

Full 2D/3D Python evaluation now calls the native result stage. Independent applicability, physical-balance and qualification queries use that stage.
The native result stage owns Quick Design metrics and retains typed intermediate values. V3 uses fixed named host operations for existing Python object, exact integer and final conversion protocols. The public Python entry points and saved formats stay available.
The host query uses borrowed typed evidence and preserves deferred input errors. It delivers NumPy events before each primitive returns.
A callback error is handled at the original metric or qualification boundary. An uncaught host error retains its original Python object.
Callbacks do not own query state. Deferred errors keep their exception objects, cause/context links and group members. Earlier tracebacks on those objects are discarded. Query exit clears deferred error references, including input-packing failures; borrowed fields do not wait for cyclic garbage collection.
Published v1 C layouts and queries remain available. Release each owned output through the library that created it.
Result calls reject a wrong output size or an owner that was not released.
Those rejected calls preserve borrowed inputs, the old output and diagnostic storage.

The supported 2D and 3D C++ call sequence is `prepare_case`, `run_case`, then `evaluate`.
The caller supplies dimensions, design values, boundary conditions and controls.
The preparation library computes the physical fields. The solver library uses
that prepared state. The result library evaluates recorded evidence.

Current public saved 2D/3D runs copy applicability groups and required records from existing C evidence before result release.
The API publishes these values without repeating classification.
Saved inlet rows keep host fields and scalar types in native order; native constraints replace recorded constraints when present.
Python combines case notices and run `nu-evidence` warning records for `scope_notes`.
It preserves complete strings and callback records, including embedded NUL characters.
It retains their order and removes duplicate messages.
Independent C++ stages use their native scope notes.
Direct and archived-runtime paths retain `capture_applicability`. A capture error does not select that path.
`execution_record.py` interprets actual execution identity and property sampling; the result stage decides qualification.

## Inlet-property query

`InletPropertyQuery` and `query_inlet_properties` in `stages.hpp` expose the existing scalar inlet combination.
The C entry is `tpmshx_query_inlet_properties_v1` in `preparation_case_c_api.h`.
Supply topology, L/t in mm, inlet velocity, temperature, pressure and optional sCO2 Nu selection.
Also supply hydraulic diameter in m and single-stream porosity from the selected geometry owner.
The query calculates no geometry, grid, ports or solver fields.
It uses the existing four-fluid property, Nu and fixed CFD drag rules in their original order.
`exact_co2_drag` selects the existing CO2 drag factors independently of the supplied geometry.

The result contains twelve inline values in this order:

| Index | Value | Unit |
| --- | --- | --- |
| 0 | rho | kg/m³ |
| 1 | mu | Pa·s |
| 2 | k_f | W/(m·K) |
| 3 | cp | J/(kg·K) |
| 4 | Pr | dimensionless |
| 5 | Re | dimensionless |
| 6 | Nu | dimensionless |
| 7 | K_df | m² |
| 8 | cF_df | 1/m |
| 9 | dP_per_L | Pa/m |
| 10 | H_sf | W/(m²·K) |
| 11 | K_ff | W/(m·K) |

Each value carries real and imaginary components, scalar kind and category.
Category 1 denotes a complex value. Raw Nu and H_sf retain existing complex intermediates.
This query does not change complete-case validation or add a physical mode.
It creates no owner. Copy the result freely; no release call is needed.
Failure preserves the result and returns the existing property diagnostics and Python cause code through the C failure structure.

Optional callbacks use the v3 layout, with both cache hooks set to NULL.
Range, notice and floating-point callbacks run synchronously in calculation order.
Host stage 4 defers object checks to the original operation; it supplies no numerical values.
A nonzero callback result stops the query. Result, failure and error storage must be mutually disjoint.
They must not overlap input, callbacks or borrowed input text.

Python `tpms_calc.compute` keeps its public fields, cache methods and fresh result copies.
It selects geometry before the query and calculates current K_ss with the existing material owner after the cache lookup.
Its binding shares range and warning transport with complete preparation.
The [fluid preparation example](../examples/cpp/prepare_fluids_2d.cpp) also queries all four fluids through installed headers.

## Ownership and units

- Use the units in the input field names. The design input uses mm. Saved
  physical design fields use m. Preserve the existing mm-to-m-to-mm operations
  when the execution adapter makes its transport and closure inputs.
- The requested grid counts and the actual grid counts are different fields.
  Physical 2D fields have shape `(nx, ny)` and C order. Flow fields use the
  existing `(cross, stream)` order for each side.
- A successful call that returns owned arrays has one owner. Its array and text views belong to that owner.
  Release it through the same library after the last use. Do not copy owners or free their buffers with a caller allocator.
  Scalar-only queries, including inlet properties v1 and Quick pressure fractions v2, return values and need no release.
- Diagnostic storage must be separate from every retained preparation view, including owned LUT arrays.
  An overlapping call returns invalid status without changing the result or diagnostic storage.
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

`Run2D` accepts the uniform v2 or continuous v4 preparation view, or a saved v1/v2 descriptor.
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
2D Python runs and checkpoints use the selected library's saved-input interface when its complete protocol is available.
`SavedCase2D` borrows a validated v2 view and saved thermal geometry. It does not prepare the case again.
Uniform saved inputs can include cell thermal geometry and local drag while keeping uniform closure mode.
Missing range records and empty records stay distinct. Uncaptured rows do not receive numerical samples.
Saved scalar and field kinds retain the original unit-conversion and closure-ratio precision.
With model-h controls, the saved interface checks the requested energy algorithm before execution.
It does not pass two sets of iteration controls to the numerical driver.
Keep inputs and range flags valid until result transfer or run release.

`SavedCase2Dv2` adds the two nominal thermal-side tuples for nonzero delta and accepts the existing discrete and sigmoid field views.
It keeps nominal side geometry separate from cell thermal geometry and design fields.
`saved_case` converts a v10 preparation owner to this borrowed descriptor.
Keep the descriptor and its preparation owner alive and unchanged until result transfer or run release.
The v10 `run_case` overloads keep the descriptor alive for the complete synchronous call.
The new create/restore entries use the existing lifecycle, snapshot and result owners; saved v1 layouts remain unchanged.
The saved descriptor version does not change result release.
Use `tpmshx_stage_run_2d_release_v1` for the transferred 2D result.

Python selects a complete saved v2 protocol first, then saved v1 for symmetric uniform or continuous inputs.
Archived libraries without the applicable saved protocol use their existing interface.
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
The scalar mapper and historical-runtime capture calculations keep their existing behavior.

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
Python 3D preparation uses host v5 with the existing v3/v4 inputs and owned results.
`tpmshx_preparation_host_3d_abi_version_v5` identifies this host contract.
The v9 callback descriptor supplies typed geometry and inlet cache keys. V1 event callbacks remain accepted.
The host keeps cache policy, scalar object types, warning filters and source locations.
Host stages 10 through 16 preserve domain, port, fluid, grid, cell-cap, roughness and grid-cell conversion validation order.
Stages 17 through 19 validate each count before its physical axis is built.
The library owns physical grid construction, local geometry, total-flow resolution and final preparation.
`preprocess/three_d/preparation.py` copies native views into immutable CaseData before releasing the owner.
Native failure preserves the original host exception and does not select another preparation route.
The old 3D numerical host route and its exclusive `shared/models/grid_3d.py` and `asym_split.py` helpers are retired.
`development/tests/preparation_3d_reference.py` keeps their independent comparison and synthetic saved-grid fixtures.
3D air-field scalar observations use at most eight selected values per side.
The selection keeps the original notices, extrema and last sample.
Raw-array range records still include every physical cell.
Preparation and result compile the same private selection rule separately.
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
Real 3D BO and visible desktop acceptance remain separate gates.

## Discrete zones

Preparation v5 uses `ZonedInput2D` for raw stripes and rectangles.
It accepts air/air, prescribed inlet velocity, CFD drag and zero delta.
Configured or explicit mass targets, experimental drag and sigmoid controls stay outside this interface.
Preparation v5 is a raw C/C++ interface with unchanged layouts and scope.
The Python spatial adapter uses the typed cache hooks described below.
The v5 interface does not change earlier run contracts.
Preparation v10 separately adds the existing nonzero-delta modes described below.

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
Diagnostic storage must not overlap any view of an owned result.
An overlapping call preserves the result and all diagnostic storage.

A raw call starts with empty, bounded geometry and inlet-property caches.
Equal keys retain the first successful scalar types and their completed range records.
Material conductivity uses the current chi and solid conductivity on each call.
This interface accepts the event-only v1 callback. It does not use the shared Python caches or their host hooks.
Earlier v1-v4 scopes remain unchanged. Public zone methods still support standalone and nonzero-delta callers.

## Sigmoid fields

Preparation v6 accepts the existing air/air grid sigmoid controls, prescribed speeds, CFD drag and zero delta.
The input contains at least 36 interleaved L/t values in mm, plus typed inlet and outlet transitions.
The stage uses the first 36 values and samples the requested grid, then the final physical grid.
It keeps the existing ordered blending, clipping, extrapolation notices and row D-F projection.
Sigmoid fields do not use discrete Gaussian smoothing.
Design geometry comes from the LUT; separate thermal geometry comes from raw L/t fields.
Mass targets, experimental drag and nonzero delta remain outside this v6 scope.
The host adapter below supplies the Python route and cache policy.

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
The [zoned](../examples/cpp/prepare_zoned_2d.cpp) and [sigmoid](../examples/cpp/prepare_sigmoid_2d.cpp) examples also check mixed integer and float16 ports.
Keep it with a resolved input when preparing that input again. Release results with their original functions.
Earlier C and C++ entries keep weak double domain and port values.
This interface changes no physical scope or saved-file format.

## Spatial total mass flow

Preparation v8 uses `ZonedFlowInput2D` or `SigmoidFlowInput2D` with `GridKinds2D` and preparation options.
Each input contains the existing raw spatial descriptor, depth and target kinds, and an optional explicit target pair.
The six C entries provide capacity, resolution and complete preparation for both spatial input types.
They accept air/air, CFD drag and zero delta. Existing v1-v7 layouts and scopes remain unchanged.

Capacity uses the actual physical inlet slice of design porosity, the opening profile, widths, density and physical depth.
Discrete design porosity keeps Gaussian smoothing; sigmoid geometry has no Gaussian filter.
The query does not calculate Nu or transfer coefficients from obsolete inlet speeds.
Resolution applies configured one-side or two-side targets, or an explicit pair, with the existing scalar arithmetic.
Explicit targets clear stored targets. Without targets, resolution copies the raw input without physical preparation.

Complete fixed-flow preparation builds one physical grid and keeps its geometry through speed resolution.
Final properties use the resolved speeds. Requested-grid observations, per-call cache order and row D-F projection remain in their original order.
Preliminary records are in `flow.flow.evidence`; final records remain in the prepared view.
These raw operations accept only the event callback. They do not use Python cache hooks.

Capacity and resolution results own copied region names, controls and LUT arrays in their `input` views.
Keep the matching grid descriptor and scalar kinds when using a resolved input again.
Nested owner fields are null. Release only the outer result with its matching v8 release function.
The [spatial flow example](../examples/cpp/prepare_spatial_flow_2d.cpp) uses all six operations and releases original inputs before complete preparation.
It uses a small LUT for checks of ownership and typed ports. This smoke test does not qualify the LUT's physical accuracy.

## Spatial host cache interface

Preparation v9 adds `ZonedFlowInput2Dv9` and `SigmoidFlowInput2Dv9` over the v8 inputs.
The `model` member carries the actual spatial conductivity, its scalar kind, geometry-extrapolation flag and default-LUT flag.
Public configuration retains its existing topology and conductivity comparison rules.
A narrow nominal scalar can compare equal to a different spatial value.
V9 preserves the actual spatial value and kind. Nominal calculations retain their original conductivity.
The optional default-LUT query runs at each path's original geometry checkpoint.
Prescribed-speed preparation keeps preflight before this query. Capacity uses geometry alone before speed resolution.
Python owns memory and disk lookup and publication. A miss builds the existing 41x31 native table at voxel resolution 256.

Use `tpmshx_preparation_case_callbacks_v9` with `values.values.values`, version 9 and the complete descriptor size.
Keep the earlier geometry and inlet slots null. Set `geometry_cache_at` and `inlet_cache_at` for typed cache exchange.
Geometry probes carry actual topology, L/t and scalar kinds. Inlet probes also carry fluid, u/T/P, their kinds and model selection.
An absent Nu selection remains distinct from the nominal default selection.
The host owns keys, lookup, LRU order and publication; native misses calculate all physical values.
Keys last for the callback. Returned cache arrays must remain valid until the stage returns.
Publication arrays are read-only and must be copied before callback return.
Returned cache and LUT views must not overlap result, failure or error storage.
The boundary checks these views before it uses the callback status.
The original observation and validation hooks retain their timing and failure behavior.
Spatial operations add host stage 4, side 2, before region preparation. It preserves missing configuration and canonical stripe-construction errors after earlier checks.
Notice kind 2 transports each geometry extrapolation reason. It remains separate from Nu warning records and retains per-side order.

All six v9 operations return one outer owner; nested owners are null.
Full results also expose `design_pore_porosity` for the Python CaseData field.
Diagnostic storage must stay separate from every view owned by an existing result.
This includes copied controls, LUTs and `design_pore_porosity`. Rejected overlap preserves the result and diagnostic storage.
Use the matching v9 release function. Earlier C layouts and v8 operations remain unchanged.
The [spatial cache example](../examples/cpp/prepare_spatial_cache_2d.cpp) exercises all six entries and typed callbacks outside Python.
It supplies a small LUT through the cache hook, then reuses the copied LUT after the original owner is released.
This is interface evidence, not a physical qualification of the small table.

## Existing offset geometry

Preparation v10 uses `prepare_offset_case` for uniform `FlowInput2D`, `ZonedFlowInput2Dv9` or `SigmoidFlowInput2Dv9` inputs.
It includes the existing nonzero-delta uniform air/water pairs and air/air stripes, rectangles and sigmoid fields at prescribed speed.
Zero-delta inputs keep their existing physical scope. Continuous fields and CO2/sCO2 still require zero delta.
Experimental model limits remain unchanged. Capacity queries and prescribed total-flow preparation still reject nonzero delta in the original validation order.
The spatial capacity and resolution entries also use v10; their result views and release functions remain v9.

The complete v10 result adds `thermal.have_side_geometry` and two four-value `side_geometry` tuples to the existing owned view.
Each tuple contains side area density, hydraulic diameter and their nominal reference values.
The nested prepared view retains `split_a`. The existing asymmetric geometry core uses its N128 index at the original thermal checkpoint.
Nominal side values stay separate from design porosity, solid conductivity and cell thermal geometry.
The stage does not calculate a new offset model for each zone.
Release only the outer complete result, through its matching v10 release function.
Earlier preparation layouts and scopes remain unchanged.
The [offset example](../examples/cpp/offset_2d.cpp) prepares, runs and evaluates uniform, stripe, rectangle and sigmoid cases through v10 and saved v2.
Its small sigmoid LUT checks the interface, not physical accuracy.

## Python preparation adapter

Public uniform 2D preparation uses v10; its capacity and flow-resolution queries retain v7 with v3 payloads.
Canonical continuous XY entries retain v7 with v4 payloads.
Air/air stripes, rectangles and sigmoid fields use v10 for preparation, capacity and flow resolution.
Capacity-only queries keep configuration validation and do not calculate drag. Complete spatial preparation still requires CFD drag.
`preprocess/native_preparation.py` transports shared cache values and evidence without numerical cache calls.
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

The replaced Python 2D preparation sequence and row D-F projection are retired.
`preprocess/two_d/preparation.py` is the retained native adapter; `shared/models/zone_units.py` owns the saved zone-unit conversion.
Nominal x/y grid warnings use separate host emission sites in that preparation adapter.
Frozen references under `development/tests/preparation_*_reference.py` retain the original sequence and complete row D-F projection.
They are not production routes. Retain them while independent preparation comparison requires those references.
Public ZoneConfig and sigmoid field queries still serve standalone callers.
Their remaining combination calculations require separate migration and acceptance before retirement.

## Build and install

Use the setup and locked dependency commands in [README](../README.en.md).
The new CMake entry only uses prepared local dependencies. It does not fetch
sources, install Python packages or replace published runtime libraries.

Generate the two model headers with the interpreter from `.venv-path`:

```sh
"$PYTHON" -m engineering.scripts.generate_native_model_coefficients \
  --output .cache/stages-sdk/generated/tpmshx/model_coefficients.hpp \
  --df-output .cache/stages-sdk/generated/tpmshx/preparation_df_data.hpp
```

Use a new build directory and install prefix when upgrading from the previous source layout.
Keep any installation that supplies a historical run.
Use the locked CMake executable. On macOS, supply the distinct preparation and
solver archives from the accepted native dependency cache:

```sh
"$CMAKE" -S . -B .cache/stages-sdk/build \
  -DTPMSHX_NATIVE_DEPS_ROOT="$PWD/.cache/native-deps" \
  -DTPMSHX_MODEL_INCLUDE_DIR="$PWD/.cache/stages-sdk/generated" \
  -DTPMSHX_PREPARATION_COOLPROP_LIBRARY="$PWD/.cache/native-deps/build/coolprop-preparation-macos-arm64/libCoolProp.a" \
  -DTPMSHX_SOLVER_COOLPROP_LIBRARY="$PWD/.cache/native-deps/build/coolprop-macos-arm64/libCoolProp.a" \
  -DCMAKE_INSTALL_PREFIX="$PWD/.cache/stages-sdk/install"
"$CMAKE" --build .cache/stages-sdk/build --config Release --parallel 1
"$CMAKE" --install .cache/stages-sdk/build --config Release
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
It checks the reverse z-direction port and field evidence, with only the preparation library.
The [3D mass-flow example](../examples/cpp/prepare_mass_3d.cpp) resolves total flow on reverse inlet faces before complete preparation.
The [continuous 3D example](../examples/cpp/prepare_continuous_3d.cpp) prepares both XY extrusion and XYZ controls with resolved total flows.
The [spatial 3D example](../examples/cpp/prepare_spatial_3d.cpp) prepares overlapping XY rectangles with a nonzero global offset.
It checks capacities, resolved flows, copied inputs and side geometry through the preparation library.
The [mass-flow preparation example](../examples/cpp/prepare_mass_2d.cpp) queries capacities, resolves an explicit pair and prepares the case.
It also links only preparation and does not execute a solve.
The [continuous preparation example](../examples/cpp/prepare_continuous_2d.cpp) starts with XY decisions and total flow.
It exposes physical fields and local drag through v4, with only the preparation library.
The [zoned preparation example](../examples/cpp/prepare_zoned_2d.cpp) starts with raw stripe bounds and per-region L/t.
It returns prepared fields and row drag through v5, with only the preparation library.
The [sigmoid preparation example](../examples/cpp/prepare_sigmoid_2d.cpp) creates the production-resolution LUT and prepares two cases from raw controls.
It reuses the LUT and links only preparation.
Diagnostic storage must stay separate from all owned prepared views and copied controls.
The [spatial flow example](../examples/cpp/prepare_spatial_flow_2d.cpp) queries, resolves and prepares zones and sigmoid fields through v8.
The [spatial cache example](../examples/cpp/prepare_spatial_cache_2d.cpp) adds v9 typed cache and LUT callbacks.
Both examples link only preparation and keep row drag and separate thermal geometry.
The [continuous run example](../examples/cpp/continuous_2d.cpp) starts with XY decisions and fixed mass flow.
It prepares and runs the case, releases the prepared owner, then evaluates the result.
The [continuation example](../examples/cpp/resume_2d.cpp) creates a run from raw inputs,
retains a flow snapshot, releases the run and restores it with a different CPU limit.

The [uniform-fluid example](../examples/cpp/uniform_2d.cpp) executes all three
stages for CO2/water. Evaluation remains valid after the prepared owner is released.
The [Quick Design example](../examples/cpp/quick_design.cpp) starts with raw
operating points and dimensions. It calls `prepare_quick_design`, `run_case`
and `evaluate` through the existing v1 contract.
The [typed Quick preparation example](../examples/cpp/prepare_quick_design.cpp) uses `QuickDesignInputV2`.
It calls `pressure_fractions` and `prepare_quick_design`, with only the preparation library.
It does a check of owned fields and absent counterflow qtol/chunk controls without starting a solve.
These examples use only installed public headers and shared libraries.
The Windows build copies the required DLLs beside each executable.

```sh
"$CMAKE" -S examples/cpp -B .cache/stages-sdk/examples \
  -DCMAKE_PREFIX_PATH="$PWD/.cache/stages-sdk/install"
"$CMAKE" --build .cache/stages-sdk/examples --config Release
"$CTEST" --test-dir .cache/stages-sdk/examples -C Release --output-on-failure
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
The SDK check covers the installed native interfaces.
Python integration, checkpoint recovery and platform delivery need their own recorded acceptance.

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

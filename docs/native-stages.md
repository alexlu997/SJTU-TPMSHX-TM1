# Native stage interfaces

[中文](native-stages.zh-CN.md) | [English](native-stages.md)

## Scope

The native stage work adds independent preparation, execution and evaluation
interfaces. Python keeps the public entry points and their existing data contracts.
Symmetric uniform, canonical continuous XY and air/air spatial 2D preparation use the native stage.
Nonzero-delta and 3D preparation use their explicit existing routes.
A native loading or execution error does not select another route. Preparation v1 supports
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

Preparation v8 adds capacity, flow resolution and complete preparation for raw air/air stripes, rectangles and sigmoid fields.
It keeps CFD drag, zero delta and separate typed domain and port inputs.
Preparation v9 connects these symmetric spatial Python routes to the native stage through typed cache hooks.

Full 2D/3D Python evaluation now calls the native result stage. Independent applicability, physical-balance and qualification queries use that stage.
The native result stage owns Quick Design metrics and retains typed intermediate values. V3 uses fixed named host operations for existing Python object, exact integer and final conversion protocols. The public Python entry points and saved formats stay available.
The host query uses borrowed typed evidence and preserves deferred input errors. It delivers NumPy events before each primitive returns.
A callback error is handled at the original metric or qualification boundary. An uncaught host error retains its original Python object.
Callbacks do not own query state. Deferred errors keep their exception objects, cause/context links and group members. Earlier tracebacks on those objects are discarded. Query exit clears deferred error references, including input-packing failures; borrowed fields do not wait for cyclic garbage collection.
Published v1 C layouts and queries remain available. Release every output through the library that created it.

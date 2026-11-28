# Preparation arithmetic sources

The preparation model keeps the original Python and NumPy operation order.
The native code does not call either runtime.
The physical coefficients remain in the project model resources.

| Source | Native use and changes | Notice |
| --- | --- | --- |
| [NumPy 2.5.4 maximum](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/umath/loops_minmax.dispatch.c.src#L45) | The Reynolds floor in `native/preprocess/preparation_properties.cpp` keeps the AArch64 mixed-zero rule and the x86 equal-value rule. It does not include a NumPy dispatch layer. | [BSD-3-Clause notice](../../engineering/native_build/licenses/numpy-LICENSE.txt) |

The original notice must accompany source and binary distributions that contain this subset.
Global floating-point options stay unchanged.
The independent pure formula references remain under `tests/python/`.
They do not call the native formulas that they check.

## Scalar inlet-property combination

`native/preprocess/preparation_case.cpp::inlet_property_values` owns the scalar sequence for standalone queries and complete preparation.
It calls the existing property, Re/Pr, Nu, surface-transfer, fixed DF, pressure-gradient and pore-conductivity implementations.
All real scalar inputs normalize to `float64` before native evaluation.
It keeps operation order, floating-point events and source range records.
Complete preparation keeps its existing physical guards.

`query_inlet_properties` accepts supplied geometry scalars and creates no mesh or solver state.
`native/preprocess/preparation_case_c_api.cpp` exposes `tpmshx_query_inlet_properties_v2` with `float64` inline values and no owner.
Optional `tpmshx_preparation_callbacks_v3` callbacks deliver synchronous observations and host validation. Direct inlet queries require `validate_grid_stage = 0`.
Standalone `tpms_calc.compute` calls `tpmshx_preparation_cached_inlet_v1`. The preparation image owns the shared inlet and geometry caches.
`python/physical_models/tpms_calc.py` selects the registered fluid and query route, calculates `K_ss` for each call, and handles warnings.
`python/cpp_interface/inlet_properties.py` packs the inlet query. It uses `python/cpp_interface/preparation_host.py` for range observations and callbacks.
The pure empirical fluid-property formulas in `tests/python/property_reference.py` and Nusselt correlation formulas in `tests/python/nu_reference.py` supply independent numerical expectations.
No physical model, coefficient source or external numerical dependency is added.

## Spatial flow stages

`native/preprocess/preparation_case.cpp` owns raw spatial capacity, resolution and complete fixed-flow preparation.
`spatial_inlet_prefix` and `finish_spatial_inlet` use the existing zone/sigmoid geometry and port cores before any speed-dependent closure.
`prepare_capacities` and `resolve_speeds` reuse `native/preprocess/preparation_flow.cpp` for capacity and target arithmetic.
Final preparation keeps the physical grid, spatial geometry and per-call cache, with the original requested-grid observations.
Discrete design smoothing, sigmoid LUT geometry, thermal geometry and row D-F keep their separate owners and operation order.
`native/preprocess/preparation_case_c_api.cpp` exposes the v10 inputs and owned views. The v8 and v9 input layouts stay nested in them.
The [external spatial cache caller](../../examples/cpp/prepare_spatial_cache_2d.cpp) uses installed headers and only the preparation library.

## Preparation caches

Preparation ABI 5 shares standard geometry, CO₂/sCO₂ scalar properties, full inlets and sigmoid tables.
The inlet key preserves the fluid and geometry choices, resolved velocity and optional Nu settings.
Each caller applies its own material and binds the saved source records to its warning scope.
The preparation image owns sigmoid tables and both interpolation flags.
Each table key contains the topology, both axes and the voxel resolution.
At a default-table miss, Python can load an NPZ and resume the retained preparation prefix.
The SDK can supply both grids directly. [Spatial preparation example](../../examples/cpp/prepare_spatial_cache_2d.cpp)

## Existing offset geometry

V10 adds the existing nonzero-delta uniform and spatial preparation modes.
`prepare_thermal_sides` calls the existing asymmetric geometry owner with its N128 index.
It runs at the original thermal checkpoint and keeps nominal sides separate from design and cell thermal geometry.
The owned complete result adds two thermal-side tuples and retains the existing split fraction.
Capacity and fixed-flow entries keep their previous delta rejection and validation order.
Earlier C layouts and scopes stay unchanged. No physical model is added.
The [external offset caller](../../examples/cpp/offset_2d.cpp) prepares, runs and evaluates the existing modes through installed headers.

## 3D preparation

The separate `prepare_case_3d` sequence in [preparation_case.cpp](preparation_case.cpp)
uses the existing grid, geometry, property and DF cores.
It retains the production 3D physical `(x,y,z)` order, six axis maps,
typed port arithmetic and the resolved cell cap.
Its uniform side porosity is already split. Base K/cF fields remain unscaled;
side evidence records the CO2 or experimental application factors.
The sequence keeps A then B inlet properties, air-only bulk Nu observations,
then DF application evidence. Existing state and calibration limits remain.
The raw C interface owns returned buffers and accepts v1 event callbacks.
The host receives ordered observations from the preparation image.
The separate 3D flow v2 uses the same static geometry and speed-dependent finish steps.
It reuses `inlet_capacity_3d` and `inlet_speed` from `preparation_flow.cpp`.
Capacity queries omit speed-dependent work. Complete preparation preserves one geometry and the original evidence order.
Continuous v3 samples raw XY or XYZ controls through `field_continuous.cpp` on the final physical grid.
`have_ctrl_z` preserves the XYZ rule when its control count is one.
Raw and thermal geometry retain separate evaluation order and unit conversions.
The existing geometry and DF owners provide full local fields without 2D row projection.
Air range observations reuse `reynolds_point` with the original scalar and array types.
Spatial v4 uses `zones::assign` on physical XY centres, then `gaussian_sigma2` on L and t separately.
It extends those fields along z and retains the separate thermal SI round trip.
`asym::prepare_from_index` supplies the existing nominal split and thermal side/reference geometry.
`asym::split_porosity` applies each fraction to local symmetric total porosity.
Capacity uses the corresponding side field. Base DF and solid conductivity keep the existing symmetric geometry.
The raw owner copies rectangle inputs and keeps borrowed nested views with null owners.
The v1/v2/v3 C layouts and their original scope remain unchanged.
These raw interfaces add no 3D solve or capture.
Python 3D preparation uses host v5 through the existing v3/v4 inputs and owned results.
The v9 descriptor transported typed geometry and inlet cache values and evidence.
The current image replays inlet range evidence in the active host scope.
Native code owns grid, geometry, flow resolution and final preparation.
Python keeps configuration conversion, warnings, environment parsing and immutable CaseData assembly.
The replaced 3D Python bodies and exclusive `shared/models/grid_3d.py` and `asym_split.py` helpers are removed.
The full-pipeline 3D Python reference is retired. Pure formula references and physical invariant checks remain in `tests/python/`.

3D air-field observations use `native/numerics/scalar_range_samples.hpp`, also used by result range queries.
The selection keeps the original scalar notices, extrema and last sample with at most eight host observations per side.
Full raw-array range records keep every cell and their original sample denominator.
Preparation and result compile this rule separately; preparation does not link the result library.

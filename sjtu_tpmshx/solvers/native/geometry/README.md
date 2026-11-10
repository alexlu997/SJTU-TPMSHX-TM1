# Native geometry and design-field library

This target owns the standard, CO2-table and asymmetric geometry calculations.
It also owns grids, physical ports, axis maps, continuous XY/XYZ fields, sigmoid, linear LUTs, zones and Gaussian filtering.
It has no link dependency on the full solver, CoolProp, Eigen, SuperLU or AMGCL.
The build uses generated model data, the C++ standard runtime and a restricted C17 FITPACK subset.
The library does not call Python, NumPy or scikit-image at runtime.
The Python application uses a thin C ABI binding.
There is no runtime compiler, source download or numerical fallback.

## Build and interfaces

The standalone entry is [CMakeLists.txt](CMakeLists.txt).
The full [dependency pilot](../dependency-pilot/CMakeLists.txt) adds the same target directory.
It does not define a second geometry implementation.

| Target | Interface or check |
| --- | --- |
| `tpmshx_grid` | Shared static grid/port owner, also used by the pressure solver. |
| `tpmshx_xy_fitpack` | Restricted C17 bivariate first-fit interpolation. |
| `tpmshx_fields` | Static continuous, sigmoid and LUT calculations. |
| `tpmshx_geometry` | Static C++ calculation core. |
| `tpmshx_geometry_c` | Static C ABI library linked to that core. |
| `tpmshx_geometry_shared` | Shared C ABI library linked to that core. |
| `geometry_c_static` | Independent C11 caller linked to the static C ABI. |
| `geometry_c_shared` | The same C11 caller linked to the shared C ABI. |
| `geometry_kernel_smoke` | C++ caller for direct geometry rules and synthetic inputs. |

The geometry C interface is [geometry_c_api.h](../include/tpmshx/geometry_c_api.h).
Grid and zone entries use [grid_c_api.h](../include/tpmshx/grid_c_api.h) and [zones_c_api.h](../include/tpmshx/zones_c_api.h).
Field entries use [field_continuous_c_api.h](../include/tpmshx/field_continuous_c_api.h),
[field_sigmoid_c_api.h](../include/tpmshx/field_sigmoid_c_api.h) and [field_lut_c_api.h](../include/tpmshx/field_lut_c_api.h).
Direct C++ interfaces include [geometry.hpp](../include/tpmshx/geometry.hpp), [grid.hpp](../include/tpmshx/grid.hpp) and [ports.hpp](../include/tpmshx/ports.hpp).
The [C caller](../tests/geometry_c_smoke.c) checks fields, ownership, errors and unchanged outputs after failure.
The [C++ caller](../tests/geometry_kernel_smoke.cpp) checks inclusive counts and injected model or node data.
A caller result is separate from full numerical, platform and desktop acceptance.

Use the [configured project interpreter](../../../../README.md) from the repository root.
The [build script](../../../../engineering/scripts/build_native_dependencies.py) has these actions:

| Action | Scope |
| --- | --- |
| `fetch-cmake` | Fetch and check only the existing locked CMake tool. |
| `build --component geometry` | Generate model data, then configure and build this standalone target. |
| `verify --component geometry` | Check the locked CMake version and run the three callers. |
| `publish --component geometry` | Build, verify and publish only geometry with `geometry-build.json`. |

Set `--python-lock` to the active interpreter's exact lock when it differs from the default base lock.
Build and CLI verification retain the lock and pip compatibility checks.
The build script uses Python for these checks and model-data generation.
The generated input is `.cache/native-deps/generated/tpmshx/model_coefficients.hpp` by default.
Set `TPMSHX_MODEL_INCLUDE_DIR` when configuring CMake with another generated include directory.
The geometry target does not configure or build the solver dependencies.

Standalone outputs go under `.cache/native-deps/build/geometry-<host>`.
Full pilot outputs go under `.cache/native-deps/build/pilot-<host>`.
The shared library is `libtpmshx_geometry_shared.dylib` on macOS arm64.
It is `tpmshx_geometry_shared.dll` on Windows x64.
Both C callers and the kernel caller are placed beside the shared library.

Source publication uses `sjtu_tpmshx/solvers/native/lib/<host>`.
A changed geometry library keeps its previous library and metadata under `previous/`.
Geometry-only publication does not replace solver or run-state files.
The runtime loader override is `TPMSHX_GEOMETRY_LIBRARY`.
Desktop packaging uses a separate prebuilt input, `TPMSHX_NATIVE_GEOMETRY_LIBRARY`.
It places geometry beside solver and preparation under the bundle's `native/` directory.
The new static targets do not add a distributed library or change these commands and paths.
Rebuild each affected library after changing C/C++ source or compiled model data. Then restart the process.

## Grid and design-field rules

Each migrated numerical rule has one native owner. Python keeps configuration, DTOs, array adaptation, I/O, caches, GUI and BO orchestration.
The replaced Python interpolation, overlap, zone and filter bodies are retired.
Independent references remain under `development/tests/`; production does not import them.
No numerical callback into Python, new framework or runtime fallback is used.

Grid construction keeps original scalar precision, mixed sum order, allocation ties and final-cell compensation.
GUI adaptive counts and three-dimensional count suggestions also use this native owner.
Staggered overlap keeps the narrow `np.r_` edge/width arithmetic; nonstaggered lower edges use the original float64 concatenation.
The same port loop serves typed preparation and full-solver double entries.
The latter retain their original physical input checks. Raw typed inputs keep original nonfinite and nonpositive arithmetic.
Python retains configuration `set`/`sorted`, control-axis `np.linspace` and Continuous coverage validation.

Nondegenerate XY uses the SciPy 1.18.1 first-fit, `s=0` FITPACK subset.
XYZ and singleton XY axes use sequential one-dimensional fitting and sampling.
The scalar band solve is not a bitwise LAPACK/BLAS replacement.
Sigmoid retains ordered blending. The LUT keeps separate fast64/general paths, singleton axes and end-cell extrapolation.
Zone selection retains its original order. Its sigma=2 Gaussian uses radius=8, reflect boundaries and axis 0 before axis 1.
The Gaussian length remains in grid-index units. Continuous splines do not use this filter.

Geometry ABI 1 and field ABI 2 share this library file. They have different status contracts:

| Protocol | Status 1 | Status 2 | Status 3 |
| --- | --- | --- | --- |
| Geometry, grid and zones | Invalid input | Domain error | Runtime error, including allocation |
| Continuous fields, sigmoid and LUT | Invalid input | Allocation failure | Numerical/runtime error |

The geometry mapper raises `ZeroDivisionError` for status 2. The field mapper raises `MemoryError` for status 2.
C buffers are borrowed for the call, with explicit element counts and alignment requirements.
Outputs belong to the caller and remain unchanged on failure. No C++ exception crosses the C boundary.
XY handles own fitted coefficients; release them once after their final query.
The Python owner retains the creating library until release.
LUT objects retain captured axes, table references and the creating binding; they do not own persistent native table handles.
In-place table changes remain visible. Attribute rebinding does not retarget a constructed LUT.
Each query selects each table's arithmetic path from its current dtype, byte order and writability before buffer conversion.
Returned arrays do not borrow native temporary storage.

See [field sources and local changes](fields-sources.md) for algorithms, fusion rules and license duties.
Source integration does not establish complete-case, Windows or final CI acceptance.
Stage four adds a separate [preparation core](../../../../docs/cpp-migration.md#native-preparation-core) for properties, DF and preparation mathematics.
Geometry ABI 1 and field ABI 2 remain unchanged. Preparation has its own ABI 1 and error mapping.
Stage five still requires an independent result core and result mathematics. Complete-case, platform and final acceptance remain separate gates.

## Upstream sources

The port uses the scikit-image **0.26.0** release:

- [Cython Lewiner implementation](https://github.com/scikit-image/scikit-image/blob/v0.26.0/src/skimage/measure/_marching_cubes_lewiner_cy.pyx).
- [Lookup tables](https://github.com/scikit-image/scikit-image/blob/v0.26.0/src/skimage/measure/_marching_cubes_lewiner_luts.py).
- [Input conversion, spacing and surface-area operations](https://github.com/scikit-image/scikit-image/blob/v0.26.0/src/skimage/measure/_marching_cubes_lewiner.py).
- [Release license](https://github.com/scikit-image/scikit-image/blob/v0.26.0/LICENSE.txt).

The algorithm is credited to Thomas Lewiner, Helio Lopes, Antonio Wilson Vieira and Geovan Tavares.
Thomas Lewiner wrote the original C++ implementation in 2002.
Almar Klein ported it to Cython in 2012. scikit-image adapted that port in 2016.
This project follows the 0.26.0 Cython implementation, not the older bundled C++ example.
That example has different near-zero and interpolation rules.

The area reduction uses NumPy **2.5.4** sources:

- [Real pairwise-sum helper](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/umath/loops_utils.h.src).
- [Addition reduction and its initial accumulator](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/umath/loops_arithm_fp.dispatch.c.src).
- [Array power dispatch](https://github.com/numpy/numpy/blob/v2.5.4/numpy/_core/src/multiarray/number.c).
- [Release license](https://github.com/numpy/numpy/blob/v2.5.4/LICENSE.txt).

The applicable license for both excerpts is BSD-3-Clause.
Copyright 2009-2022 the scikit-image team.
Copyright (c) 2005-2025, NumPy Developers.
The complete notices are retained unchanged as
[scikit-image-LICENSE.txt](../licenses/scikit-image-LICENSE.txt) and
[numpy-LICENSE.txt](../licenses/numpy-LICENSE.txt).
Source distributions must retain their copyright, conditions and disclaimers.
Binary distributions must provide these notices in accompanying materials.
Do not use upstream names to endorse a derived product without permission.
These duties also apply to a geometry-only binary distribution.

The field and filter subsets use SciPy **1.18.1** sources.
The [field source record](fields-sources.md) lists fixed FITPACK, basis, LUT and ndimage references and local changes.
Retain [scipy-LICENSE.txt](../licenses/scipy-LICENSE.txt) and [ndimage-LICENSE.txt](../licenses/ndimage-LICENSE.txt) unchanged with the NumPy notice.
These BSD-3-Clause notices also apply when only the geometry/design-field library is distributed.

## Local changes and numerical rules

The [scalar precision helper](../include/tpmshx/scalar_precision.hpp) keeps the original NumPy float16, float32 and float64 intermediate rounding in C++.
The binding sends cell, ratio and final-product precision metadata.
`standard_scalar_v1` rounds `L_mm/1000` and `L_m/N` at cell precision.
It rounds `t_mm/L_mm` and the first coefficient product at ratio precision.
The squared ratio term and the final threshold addition use double.
Batch L/t fields keep their existing float64 conversion.

Standard scalar porosity is a Python float.
Thus NumPy float16/32 conductivity can give `K_ss` the same dtype.
Array and CO2 porosity use float64, so their material results stay float64 for these conductivity inputs.
The core calculates `chi*(1-epsilon)` in double.
It casts that intermediate and conductivity to final-product precision before multiplication.
Python restores the output dtype and shape; it supplies no numerical fallback.
Formal nonzero asymmetric preparation keeps the original explicit Python-float conversion for L/t and length.
Its native arithmetic stays float64.

The local implementation is in [src/geometry](../src/geometry).
The cell state and ambiguity tests were translated from Cython to C++17.
Lookup data were decoded into signed-byte C++ tables without changing their dimensions or order.
The port keeps all 47 non-classic tables. It has no classic, mask, normal or value output mode.
It has no PLY support and does not remove degenerate faces.
C++ vectors own the internal mesh storage instead of the Cython allocation arrays.
The native pointer boundary adds explicit dimension checks.

The port retains cube order, corner numbering, vertex reuse and center-vertex weights.
Corner tests use strict positivity and double epsilon `2^-52`.
Upstream diagnostic branches still print and continue processing.
This includes the reachable near-zero case-13 diagnostic.
The internal mesh helper supports comparison; it is not an added public C mesh API.

The asymmetric wrapper first checks extrema from the original field values.
It skips MC when `level <= minimum` or `level >= maximum`.
Raw-array calls retain the original level scalar precision in that comparison.
The C ABI receives separate isosurface levels and array-comparison bounds.
The Python binding normalizes those scalars before it borrows a float64 buffer.
Masks, counts, surfaces, diameters and wall thickness remain native calculations.
Other inputs continue to the existing float32 conversion and MC logic.
The MC kernel performs its separate range check on the converted field.
This range comparison uses float32, as the original NumPy scalar comparison did.
The level remains double. Stored vertex coordinates remain float32.
The port restores NumPy axis order and the existing descent face order.
It retains duplicate vertices and zero-area triangles.
No periodic boundary is added.

Non-unit spacing promotes and scales vertex coordinates to double before area operations.
Exactly unit spacing retains the original float32 area path.
Each triangle uses the existing subtraction, cross product, square and square-root order.
The final sum keeps NumPy's eight lanes, 128-item blocks and recursive split aligned to eight elements.
The sum adds its subtotal to positive zero before division by two.
The port uses `std::sqrt`; NumPy can use a SIMD square-root operation.
Actual platform comparisons remain necessary.

CMake disables fast-math and implicit contraction for the C++ grid, field and geometry targets on Clang/GCC.
It also disables builtin pow, sin and cos substitutions for those targets.
The separate XY C target uses local `-ffp-contract=fast` and explicit `fma` directions in its Givens operations.
Gaussian uses explicit `std::fma` for the locked Apple-arm64 symmetric pair loop; other platforms keep separate multiply/add operations.
MSVC uses `/fp:strict`; explicit fused operations remain explicit.
These options preserve the intended arithmetic; they do not prove cross-platform identity.

# C++ solver migration under the V0.3 architecture

## Status and architecture decision

The supplied **TPMS 均质化换热器求解软件总体框架说明 V0.3** (2026-09-08)
describes a target architecture, not delivered capabilities. Its three business
modules match the existing TM1 public flow:

```text
application -> preprocess.api -> CaseData -> solvers.api -> FieldResult
                                                           -> postprocess.api
```

Keep those boundaries, the existing `domain` contracts, shared model resources,
and the Python backend. There is no need to rename every directory or divide
the project into repositories. V0.3's useful extension is an independently
qualified C++ backend inside the solver module, consuming the same physical
case and producing evidence usable by the existing postprocessor.

Python/Numba remains the default. The explicit `backend='cpp'` supports
complete prepared Quick Design and full 2D/3D execution on the qualified macOS
arm64 build. Windows native execution is not yet qualified. Installed desktop
visual acceptance and whole-application performance are separate gates.
The optional true-h sweep kernel inside the Python backend is a separate,
narrower capability.

The first connection (2026-09-22) follows full-budget Python reference checks.
It supports full two-fluid 2D/3D true-enthalpy runs containing sCO2, including
signed partial ports. Python still owns EOS, property updates, convergence,
independent energy checks and cancellation between sweep chunks. Model-h,
single-fluid and quick-design execution reject an explicit `cpp_sweeps_v1`
request; they never silently fall back to Numba.

## Complete Quick Design capability

`quick_design_driver.hpp` owns the complete prepared const/mean property-pass
calculation: original empirical air/water or HEOS sCO2 properties, existing Nu,
one or two temperature passes, full-field warm starts, water liquid-state
checks after each pass, iteration budgets, progress and cancellation. Prepared
inlet-state analytical pressure fractions remain fixed. This is the existing
prescribed-flow sizing approximation, with `physical_validation=not_established`.

`solver_c_api.h` provides the independent versioned C entry point and named
configuration/result structures. It borrows nine arrays with explicit sizes;
errors distinguish invalid inputs, water inlet/property states, water fields,
arithmetic failures and other native exceptions. Cancellation has its own
result status. Unsuccessful fields cannot be published as accepted results.
The build runs the same independent C caller against static and shared libraries.

The thin Python adapter reuses the shared prepared-input validation and
`FieldResult` mapper. Native pass evidence supplies fields, properties and the
original warning records without calling Python numerical kernels or property
functions. Host library location is an execution control, outside `CaseData`:

```python
from sjtu_tpmshx.domain.module_ports import RunControl
from sjtu_tpmshx.solvers.api import run_case

result = run_case(prepared_case, RunControl(
    backend="cpp", native_library="/absolute/path/to/libtpmshx_solver_shared.dylib"))
```

Use `tpmshx_solver_shared.dll` on Windows. The path must refer to a prebuilt
library on that host; missing libraries, wrong ABI or unsupported capabilities
fail explicitly. Public result saving, loading and offline evaluation use the
existing interfaces. macOS qualification includes fresh-process saved-case
replay without Numba/Python solver kernels, callback failures, cancellation,
recovery and concurrent runs. Windows has build/required-CI definitions but
still requires an actual native run; this is not a packaged application release.

## Complete full 2D capability

`full_2d.hpp` and `full_2d_c_api.h` provide the complete rectangular two-fluid
2D driver. It owns the existing SIMPLE flow updates, inlet pressure reference
and gas pressure shooting, property/closure updates, outer coupling, selected
temperature/model-h/true-h solve, Richardson transfer and final field/energy
certificates. Partial ports, spatial L/t fields, actual boundary fluxes and
distinct final-flow/thermal pressure states retain the prepared-case contract.
The main heat metric remains W/m; an explicit physical depth is still required
for total mass-flow optimization. Completed execution and convergence remain
separate, including capped iterations, failed certificates and cancellation.

Full 2D uses **ABI 2**: its 29th prepared array preserves the dimensionless
`(D_h_m * 1000) / L_mm` ratio from the original closure input. Reconstructing
that ratio from rounded SI lengths can change the last bits of graded-field
heat transfer coefficients. The C symbols and structures use `v2`, and the
adapter rejects an ABI 1 library before entering the numerical call. Distribute
the matching library, headers and adapter together; saved FieldResult files
continue to use the existing portable reader without loading a native library.

The public call above also accepts a full 2D `CaseData`; CLI, desktop and design
hosts carry the same `RunControl`. Source CLI execution uses, for example:

```bash
"$PYTHON" -m sjtu_tpmshx.cli solve case.h5 results.h5 --backend cpp \
  --native-library /absolute/path/to/libtpmshx_solver_shared.dylib
```

The binding performs prepared-input validation, passes borrowed input views,
copies result-owned arrays before release and maps native evidence into the
existing `FieldResult`. Host library/table directories are not serialized in
cases or results. Fresh-process CLI solve, save/reload and offline evaluation
load no Numba or Python numerical driver. Numerical qualification compares
full fields, statuses, budgets, pressure and energy evidence against the
corrected Python reference with fixed tolerances. Neither this opt-in nor a
successful macOS package run establishes Windows acceptance or changes the
default backend.

## Complete full 3D capability

`full_3d.hpp` and `full_3d_c_api.h` provide the rectangular two-fluid 3D outer
driver through ABI 1. It consumes the same prepared XYZ fields and partial-port
geometry, performs pressure-referenced SIMPLE flow and selected
temperature/model-h/true-h coupling, and returns the original final-state
certificates, warning evidence and field locations. The existing optional
coarse bootstrap preserves fine-grid pressure boundary values. No Python
numerical kernel supplies the native result.

Bootstrap diagnostics are an additive ABI 1 capability. The existing input,
result and first-coarse-level summary layouts are unchanged;
`tpmshx_full_3d_get_bootstrap_trace_v1(result, side, trace)` exposes a separate
read-only view for side 0/1. Its strings and layer array belong to the result
owner and remain valid only until `tpmshx_full_3d_release_v1`. A query performs
no numerical work or allocation. Existing C callers continue to use their
unchanged ABI 1 result layout. The current Python binding requires the new
query symbol and reports a capability error for an older library; it never
fabricates a trace or substitutes a Python solve.

The trace records explicit enable/disable, actual coarse shapes/depths and
per-layer caps, entered iterations and stop reasons. It preserves the current
recursive `count > 2000`, child cap 200, minimum-axis and stopping rules.
`started_cap_sum` is the sum of caps for layers that entered an iteration,
not a shared global bootstrap limit. An unstarted cancelled parent contributes
zero iterations and no cap to that sum. The binding copies the trace before
release into the same `diagnostics.coarse_bootstrap_trace` used by Python full
3D; saved results without this optional key remain readable.

The existing cooperative-cancellation result still owns its partial diagnostic
views, so a C caller can query them before release. The Python binding raises
`CancelledError` with the detached trace in `coarse_bootstrap_trace`, and does
not publish a partial FieldResult. Hard C API errors still leave the caller's
result untouched and publish no owner; a complete trace is consequently not
available through the query after such an error. Bootstrap-local failures
that the existing algorithm catches remain recorded without claiming an
applied seed or replacing actual charged work with a configured cap.

The shared physical-port pressure reduction preserves the reference masked
array order and contiguous pairwise summation for both weighted pressures
and open areas. This also fixes the inlet anchor used by pressure shooting:
changing its summation order can alter later SIMPLE stopping iterations even
when the initial pressure difference is only roundoff. Full-field checks must
therefore retain the original iteration budgets and comparison tolerances.

The same public `run_case` and CLI commands select it for a full 3D CaseData.
Numerical qualification includes the original 24³ case and full field/pressure/
thermal evidence, with unchanged budgets and comparison gates. That particular
capped case returns `converged=False` in both backends; agreement does not
convert it into a converged solution. Full 3D model-h heat remains W; the legacy
temperature route retains its existing unavailable-heat boundary when complete
enthalpy evidence is absent. Optimization still applies its independent
model-h physical-boundary and energy certificates.

## First implemented slice

`native/include/tpmshx/enthalpy_sweeps.hpp` and
`native/src/enthalpy_sweeps.cpp` implement the serial true-enthalpy LTNE
Gauss–Seidel sweeps from `solvers/ltne_enthalpy_3d.py`:

- Fluid A, fluid B, then solid, retaining the original increasing i/j/k order.
- Signed mass flow on all six faces, inward prescribed enthalpy, outward
  cell enthalpy, and zero-flow wall faces; no inferred uniform-flow shortcut.
- Nonuniform orthogonal cell widths and harmonic face conductivity.
- Fourier conduction using temperature linearized about frozen `(T*, h*, cp)`;
  differences in pressure-dependent enthalpy at equal temperature do not
  become spurious heat conduction.
- In-place under-relaxed enthalpy/solid-temperature updates and separate exact
  A/B enthalpy clipping counts, accumulated over the requested sweeps.

The library is C++17 and standard-library-only. It accepts borrowed contiguous
double arrays with explicit lengths, units and staggered locations. Inputs are
checked before mutation; the caller owns the arrays and must not alias mutable
state with other state or coefficient arrays. Arrays use `(i*ny+j)*nz+k` order.
Nonfinite equation diagonals, right-hand sides or updates caused by finite-input
arithmetic overflow throw `std::domain_error`; the partially updated state must
not be consumed after this exception, and is not silently clipped or accepted.
Single-cell axes are supported; a unit-depth 2D extrusion keeps the existing
2D driver's normalization rather than inventing a physical thickness.

This slice performs **no** EOS lookup, SIMPLE solve, mass-flux balancing,
Picard/property update, outer convergence/cancellation handling, CaseData
loading or FieldResult capture. Clip-free kernel execution alone cannot certify
a converged or physical result.

## Second implemented slice: actual-state energy audit

The same library now exposes `thermal_energy_audit`, reproducing the production
true-h energy operators from `ltne_enthalpy_3d.py` and `result_math.py`:

- Actual-state A/B cell residuals: Fourier conduction + solid exchange − signed
  upwind enthalpy divergence. The caller supplies actual EOS temperatures and
  effective fluid conductivities, not the sweep's frozen linearization.
- Adiabatic solid cell residuals and all six signed boundary enthalpy duties;
  inlet/backflow faces use prescribed inlet enthalpy, outflow uses cell enthalpy.
- The existing coupled and equation ratios, including the unchanged denominator
  `max(abs(Q_A), abs(Q_B), 1)`, fluid residual absolute sums/maxima and solid sum.
  Outputs are W per cell for 3D, W/m for the existing unit-depth 2D extrusion.

The operator applies **no acceptance threshold**. It does not evaluate EOS,
verify state applicability, balance mass, count prior clipping or establish
convergence. Those driver-owned checks remain mandatory. Invalid inputs are
rejected before residual output writes; arithmetic overflow raises an error and
invalidates all output buffers. State/coefficient arrays remain read-only.

Qualification compares actual residual fields and budgets to the Python
operators, not just the final ratio. Independent checks include six signed flow
directions, a one-cell 20 W exchange, internal-face cancellation, isothermal
pressure-dependent enthalpy and a deliberately unbalanced local temperature
field whose global/coupled budget is zero but equation residual is positive.

## Fixed-coefficient temperature driver

`temperature_driver.hpp` adds `solve_temperature` for 2D and 3D cell-centred
temperature equations. The native call owns cold/warm initialization,
prescribed B, the per-cell A/solid/B update order, chunk budgets, Q and field
stability, progress and cancellation. It accepts explicit per-side porosity,
variable coefficients, nonuniform widths, signed inlet capacity and partial
openings; conductivity already includes its side's porosity.

This is a fixed-coefficient driver, with no EOS, property passes, pressure
solve or physical energy certificate. The 3D staggered/projection, MMS,
model-h, true-h and red-black paths are not implemented by this entry point.
The production backend does not select it. Invalid dimensions, directions,
relaxation policies, extents and aliased state are rejected before updates;
arithmetic failures invalidate the partial state. Cancellation returns an
explicit cancelled status and cannot certify convergence.

Qualification compares complete A/B/solid fields, residuals, stopping status
and charged budgets, including real Quick Design inputs frozen after their
Python property preparation. Same-algorithm tolerances were fixed before
comparison: 2D `rtol=2e-12, atol=2e-10 K`; 3D
`rtol=2e-11, atol=2e-9 K` against its Numba fastmath reference. These are
arithmetic tolerances, not changes to PDE or experimental gates. A separate
C++ caller checks a hand-calculated single-cell phase update.

## Build and run the qualification checks

From the repository root, with an existing POSIX C++17 compiler and `make`:

```sh
make -f native/Makefile CXX=c++
make -f native/Makefile CXX=c++ shared
make -f native/Makefile check
```

This builds `.cache/native/libtpmshx_thermal.a`. Include `native/include` and
link that archive from a C++ caller. There is no Python, Qt, NumPy, CoolProp,
OpenMP, CMake or binding-library dependency in the native library itself.
The `check` target compiles and runs independent C static/shared callers and
C++ static callers for the energy-audit operator and temperature driver. The shared target
builds `.cache/native/libtpmshx_thermal.dylib` on macOS or
`.so` on other POSIX platforms. The library is not bundled with the Python
wheel or desktop application, discovered automatically, or built during a run.

From an existing x64 Visual Studio developer command prompt on Windows:

```bat
nmake /f native\Makefile.msvc check
```

This builds `tpmshx_thermal.lib`, `tpmshx_thermal.dll` and the separate
`tpmshx_thermal_import.lib` under `.cache/native`, then runs the same C/C++
callers. The C ABI uses explicit Windows exports/imports and `cdecl`; ctypes
uses the DLL path with `CDLL`. These commands do not install a compiler.

`thermal_c_api.h` exposes the versioned sweep ABI and bounded error messages;
exceptions do not cross the C boundary. The production ctypes adapter validates
shapes, contiguous float64 storage, alignment and nonaliasing mutable arrays.
Native errors invalidate the run; cancelled/failed runs are not finalized.
The energy-audit tests still use a test-only bridge.

Use the interpreter from `.venv-path`, after the normal environment checks:

```sh
tm1_python="$(head -n 1 .venv-path)"
"$tm1_python" -m sjtu_tpmshx.runs.tools.check_locked_environment
"$tm1_python" -m pip check
MPLCONFIGDIR="$PWD/.cache/matplotlib" \
XDG_CACHE_HOME="$PWD/.cache/xdg" \
NUMBA_CACHE_DIR="$PWD/.cache/numba" \
TPMSHX_REQUIRE_CPP_TESTS=1 \
"$tm1_python" -m pytest -q sjtu_tpmshx/tests/native
```

For an accepted full true-h case, set these before `prepare_case` or the CLI:

```sh
export TPMSHX_TRUE_H_KERNEL=cpp_sweeps_v1
export TPMSHX_THERMAL_LIBRARY="$PWD/.cache/native/libtpmshx_thermal.dylib"
"$tm1_python" -m sjtu_tpmshx.cli --help
```

Use the `.so` path on other POSIX hosts. `TPMSHX_TRUE_H_KERNEL=numba` selects
the default. Prepared cases freeze both values, including across save/load;
changing the receiving process environment does not change that case's kernel.
A native case requires its recorded absolute library path to exist on the
execution host. Missing libraries, wrong ABI and unsupported choices fail
before SIMPLE. `true_h_balance.effective_settings` records the selected kernel,
native ABI/path when used, and `energy_audit='python'`.

The required flag makes a missing compiler fail this qualification command.
General Python-only testing skips these tests when its platform compiler is
absent; that skip is not native acceptance. Native qualification is required
in the existing macOS 3.13 and Windows 3.12/3.13 fast CI lanes. A local macOS
pass does not establish Windows compilation, execution or distribution
acceptance. No compiler or Python dependency is installed by these tests.

Before comparison, the same-algorithm tolerances are fixed to `rtol=2e-13`,
`atol=2e-8 J/kg` for enthalpy and `atol=2e-11 K` for solid temperature. These
allow double-precision compiler/FMA ordering differences from Numba fastmath;
they are distinct from PDE convergence and experimental uncertainty. Clip
counts must match exactly. The native build does not enable fast-math.

Checks cover fixed-seed variable fields, signed/zero face flows, nonuniform
grids, all six flow directions, single-cell axes, zero diagonal, clipping and
rejection before mutation. Independent physical checks cover isothermal
pressure-dependent enthalpy and a constant-property exponential cooling
solution with first-order grid convergence and boundary/source energy balance.
This qualifies the sweep algorithm, not sCO2 system prediction or speedup.

For the energy audit, the fixed comparison tolerances are `rtol=2e-12`,
`atol=1e-9 W` per cell, `atol=1e-8 W` for reduced budgets, and `atol=1e-12`
for dimensionless ratios. The same source unit normalization applies in 2D.
These compare arithmetic implementations; they do not change production gates.
Performance qualification must include input checks/binding overhead and compare
equally warmed Numba sweeps and NumPy audit operators, separately from EOS,
compilation and end-to-end execution. A kernel result cannot prove application
speedup. The public execution tests compare 2D/3D sCO2/water and air/sCO2
fields, signed boundary fluxes, pressure evidence and metrics with fixed
`rtol=atol=1e-10`, alongside unchanged F2 and true-h physical gates. They also
exercise saved-case selection, cancellation and actual native error exits.
Neither native operator is automatically selected by production.

## Isolated EOS and pressure dependency qualification

The dependency pilot is an explicit build, separate from production backend
selection. Its inputs are locked in
[`native/dependencies-lock.toml`](../native/dependencies-lock.toml):
CoolProp 7.2.0 with its recursive submodules, the SuperLU 6.0.1 source commit
used by SciPy 1.17.1, AMGCL 1.4.4 and portable CMake 3.31.8. Source, binaries,
logs and tabular EOS files stay under the worktree's `.cache/native-deps`.
[`native/THIRD_PARTY_NOTICES.md`](../native/THIRD_PARTY_NOTICES.md) records the
linked components and their original license notices.

After explicit native-dependency provisioning authorization, use the configured
interpreter and the existing lock checks. `fetch` is the only network step;
`build` is offline and does not install Python packages or change the shared
environment:

```sh
"$tm1_python" scripts/build_native_dependencies.py fetch
"$tm1_python" scripts/build_native_dependencies.py build
"$tm1_python" scripts/build_native_dependencies.py verify
TPMSHX_REQUIRE_NATIVE_DEPS_TESTS=1 \
MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg" \
"$tm1_python" -m pytest -q -ra \
  sjtu_tpmshx/tests/native/test_native_eos.py \
  sjtu_tpmshx/tests/native/test_native_pressure.py \
  sjtu_tpmshx/tests/native/test_superlu_error_boundary.py \
  sjtu_tpmshx/tests/native/test_fluid_properties.py \
  sjtu_tpmshx/tests/native/test_quick_design_driver.py \
  sjtu_tpmshx/tests/native/test_cpp_quick_design.py
```

The EOS caller evaluates CO2 and Water with the same named backend as the
Python reference: HEOS or BICUBIC&HEOS. It checks forward properties, enthalpy
inversion, existing CO2 applicability bounds, stable liquid-water guards and
independent mutable states. It does **not** replace the project's empirical
air/water transport functions with CoolProp values. Each process uses an
explicit table directory; it does not change the parent Python EOS settings.
Property comparison tolerances are fixed in `test_native_eos.py` and are
separate from PDE acceptance and BICUBIC interpolation error versus HEOS.

The pressure caller consumes canonical 32-bit CSR with the original zero
Dirichlet rows and reports the original `Ax-b` residual and pin error. 2D and
3D systems with at most 2000 cells use SuperLU/COLAMD; larger 3D systems use
the original PyAMG 5.3 classical strength, splitting, modified interpolation,
Galerkin order and symmetric Gauss–Seidel cycle, with the original SciPy
BiCGStab stopping and breakdown policy. The 200-iteration budget, resolved
relative tolerance and current-matrix multiplication with reused preconditioners
remain unchanged. Only the original breakdown path retries with L2-scaled RHS;
qualification reports the unscaled equation residual. The initial AMGCL pressure
candidate failed full-case comparison and is replaced; AMGCL still supplies
the separate staggered-temperature projection. The build excludes MC64/ILU and uses
the three locked SciPy double-LU numerical corrections.

SuperLU calls now use a pure-C error boundary and a thread-local allocation
ledger. Allocation failures and ABORT return bounded errors after cleanup;
the jump never crosses a C++ frame. macOS qualification injects failure at
every observed allocation ordinal, checks same-process recovery, long ABORT
messages, singular info and simultaneous independent threads under release and
ASan/UBSan builds. Windows still needs native execution. Invalid input and
unknown backend errors do not silently fall back to LU. These pressure tests
do not by themselves establish complete native SIMPLE or outer coupling qualification.

Complete fixed-flow true-h, 2D/3D model-h, and 2D/3D SIMPLE drivers now have
independent C++ implementations, versioned C interfaces and explicit Python
bindings under `solvers/backends/cpp/`. Thermal bindings return the existing
energy and raw-boundary metadata; native model-h owns its audit arrays until
the C caller releases the result, and the Python binding copies those views
before release. Callback exceptions and cancellation discard partial states.
The SIMPLE interfaces own per-instance pressure caches and retain the original
F2, outlet, warm-state and raw-mass evidence. These independently callable
drivers also support the full 2D/3D outer-coupled backends described above.

The macOS SuperLU build uses the system Accelerate BLAS used by the pinned
SciPy reference, retaining its original CSR/transposed LU operation order for
2D SIMPLE. Windows uses the locked portable CBLAS sources pending native
qualification. A serial momentum loop does not imply a single-threaded BLAS;
thread policy and measured performance must be recorded separately.

The `native-dependencies` CI matrix builds and runs these callers and required
tests on macOS/Python 3.13 and Windows/Python 3.12/3.13. A missing executable
fails the required job. Ordinary Python-only runs may skip an unbuilt pilot;
that skip does not establish native qualification. Local macOS results and a
written Windows build configuration do not establish a Windows runtime pass.

## Remaining stages and acceptance gates

| Stage | Implementation boundary | Required evidence before advancing |
| --- | --- | --- |
| 0: thermal operators | Optional native sweeps inside the Python driver; native energy audit remains isolated. | Operator checks plus public field/flux/metric, handoff, cancellation and error comparisons. |
| 1: complete thermal driver | Port Picard state, property refresh, EOS inverse, residuals, warm starts and cooperative cancellation in the same order. Keep fluid properties separate from Nu/hv closure evaluation. | Fixed inlet/pressure/grid inputs; A/B/solid equation and boundary-energy criteria unchanged; clipped/invalid/cancelled runs retain their meaning; compare detached native fields and fluxes. |
| 2: flow and coupling | Port SIMPLE/Brinkman–Forchheimer operators, pressure and mass corrections, then the existing outer coupling order for a declared subset of rectangular cases. | Momentum and fresh-density local/global mass F2 gates; physical inlet-pressure, outlet/backflow and energy checks; directional and grid tests; same prepared geometry/closures, no coefficient retuning. |
| 3: actual C++ backend | Add the smallest solver-side adapter needed to consume CaseData and produce complete FieldResult; advertise only the accepted capability subset. | Run without the Python solver kernels; separate-process case/result handoff, state/units/field locations and model provenance; missing or unsupported capabilities explicitly rejected. |
| 4: application and release | Select the qualified backend through the existing public solver API, preserving GUI/design/optimization callers and offline postprocessing. | Fixed 2D/3D cases only where supported; cross-backend Q/pressure/temperature/flux checks with predetermined tolerances; build and packaging evidence on each supported platform. |

Before stage 1, choose the native property-library delivery and licensing/build
strategy explicitly. The current Python CoolProp installation is not evidence
of a complete portable C++ development/runtime package. Do not silently replace
HEOS with a fit or reuse the sCO2 calibration to absorb porting error. Common
closures must retain production versions, sources and validity rules across
languages, without separately refitting their coefficients.

The local CoolProp 7.2.0 wheel inspected on 2026-09-21 contains C++ headers and
an MIT license, but its binary is a CPython Mach-O bundle, not a separately
linkable `libCoolProp`. A standalone C++ link attempt fails with unsupported
Mach-O file type; no independent archive/dylib was found in that environment.
At that inspection no source was downloaded and no dependency was installed.
The subsequently authorized isolated build is described above. A complete
driver still requires qualified HEOS/final-state and BICUBIC iteration
semantics on each target platform, including actual Windows execution.

Freeze representative baseline cases and comparison tolerances **before each
stage's comparison**, preserving failed cases and their original denominators.
Run analytic/grid/conservation qualification separately from experiment
validation. The legacy 83-case record remains a historical record; a native
port does not inherit its experimental claims. Performance measurements must
separate compilation, EOS, flow, thermal sweeps and overall time and use
equally warmed runs with the same convergence gates.

OpenFOAM, a complete external solver ABI, general unstructured meshes, extra physical
models and a framework of abstract factories are not prerequisites for this
port. Add each only for a specified, separately qualified capability.

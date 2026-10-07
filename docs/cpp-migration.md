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
complete prepared Quick Design and full 2D/3D execution on macOS arm64 and
Windows x64. The required native CI suite passes on macOS/Python 3.13 and
Windows/Python 3.12 and 3.13. Delivery uses the
existing Python/Qt entry point and a precompiled C++ library in the project
folder. Source GUI acceptance and whole-application performance remain separate
gates; a packaged `.app` is outside this delivery scope. The macOS folder
launcher explicitly selects the supplied candidate library; it does not change
the public Python default or establish qualification for every case.
The earlier `cpp_sweeps_v1` connection, where Python owned the outer solve
and C++ supplied only sweep chunks, has been retired. Select the complete
Python or C++ backend through `RunControl` or `--backend`. The shared C++
sweep implementation and its low-level C ABI remain in use and are retained.

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
existing interfaces. Native CI on macOS and Windows includes fresh-process
saved-case replay without Numba/Python solver kernels, callback failures,
cancellation, recovery and concurrent runs. These runs qualify the tested
C ABI and command-line paths; visible desktop delivery remains a separate gate.

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

## Fixed-flow conservative temperature candidates

The C++ `solve_enthalpy` interface in `enthalpy_driver.hpp` accepts an explicit
`EnthalpyAlgorithm::temperature_fou` or `temperature_sou`. Existing calls default
to `legacy_h_fou`; the version-1 C interface continues to use that route.
The temperature candidates currently cover two solved fluids on a tensor grid,
including a unit-depth 2D extrusion, with supplied signed mass faces, local
absolute pressures, effective solid conductivity and volumetric exchange
coefficients. Each side must declare its scalar inlet direction; inflow through
any other exterior face is rejected. External conductive boundaries are
adiabatic. This entry does not prepare mass flow, solve SIMPLE or evaluate Nu.

Each nonlinear step freezes independent actual h, T and cp arrays, then performs
alternating forward/reverse A, B and solid sweeps. Fluid convection uses the
linearization h* + cp*(T-T*); diffusion uses temperature. SOU freezes a minmod
correction reconstructed directly from actual enthalpy on physical coordinates,
including the outlet face, and uses full solid relaxation. FOU uses the supplied
relaxation for all phases. SOU damps the completed three-phase block increment
by 0.6 before the actual state update, suppressing a demonstrated limiter-driven
oscillation on a stretched full-2D grid without changing its steady equation.
FOU uses no additional block damping. Guarded HEOS PT updates then replace the linearized
enthalpy with the actual state before residuals and duties are evaluated. No
BICUBIC table, H-to-T inversion, clipping or recovery fallback is used.

SOU recipe 2 uses six-sample Anderson proposals on this damped ordinary map.
It validates each proposal with actual HEOS PT properties and the original
energy audit before selecting it. A proposal must strictly reduce the maximum
of the equation and coupled ratios normalized by their original tolerances;
invalid or nonfinite proposals retain the ordinary update. Accepted proposals
continue iteration. First/final blocks and small ordinary temperature updates
use a complete ordinary PT/audit block, and only that block may converge.
`picard_relaxation=0.6` describes the ordinary map, not each Anderson increment.
The same loaded library's `tpmshx_energy_algorithm_version_v1` query reports
FOU recipe 1 or SOU recipe 2 from the actual returned algorithm. Python records
this identity in main/outer evidence, effective settings and boundary capture;
an old library without the query fails before conservative flow execution.
Saved SOU recipe 1 and recipe 2 boundary evidence remain readable, with no EOS
replay or version inference. Recipe versions are independent of the C ABI.

The candidates require positive coupled and equation tolerances and a positive
`temperature_update_tolerance` in K. Convergence requires all three tests on the
same actual state. `EnthalpyResult::algorithm` identifies the executed algorithm;
`temperature_update` is present only on these routes. The existing `residual`
still records the normalized actual enthalpy update. SOU final certificates
reconstruct its actual face corrections again and use them consistently in
boundary duty and local residuals. An iteration-limit result retains its actual
certificate; cancellation invalidates partial fields and clears that certificate.

`conservative_energy_smoke` checks independent frozen balances, six-direction
nonuniform face fluxes, reference-enthalpy invariance and invalid inputs.
`conservative_energy_driver_smoke` checks real EOS states, cold/warm consistency,
independently reconstructed outlet duty, cancellation, iteration limits and
physical-domain failures. The dependency-pilot verification runs both. Their
scope is fixed-flow numerical qualification; production flow/closure acceptance
and comparison with the legacy BICUBIC route remain separate requirements.

### Explicit full-flow candidate selection

Set `solver.enthalpy_algorithm` to `temperature_fou` or `temperature_sou`
and `solver.enthalpy_temperature_tol_K` to the required positive K tolerance
before `prepare_case`, then run the saved case with `backend='cpp'` and the
matching native library. The defaults remain `legacy_h_fou` and 1e-8 K.
The current candidates require the existing two-fluid true-h routes; selecting
them with Python, Quick Design or an unsupported thermal route fails explicitly.
This selection does not qualify new fluids, boiling, condensation or additional
Nu/Darcy-Forchheimer applicability. GUI selection is not yet exposed.

The complete driver retains its original SIMPLE, pressure, property, outer
coupling and final acceptance gates. Full3D also retains its two temperature
predictor sweeps and original mass preparation. Candidate recipes use five
sweeps per nonlinear step, fluid relaxation .6 for FOU and .2 for SOU, and
solid relaxation .6/1 respectively. Full3D saves resolved controls in prepared
cases; the 2D recipe is fixed by the algorithm version. Both retain their
previous iteration budgets and require actual coupled/equation energy ratios
no greater than .001 as well as the declared temperature update tolerance.
The native result records actual whole-block Picard relaxation (1 for FOU,
0.6 for SOU), separate from the fluid and solid row relaxation factors.

`tpmshx_solve_full_2d_v3` and `tpmshx_solve_full_3d_v2` accept the shared
`tpmshx_energy_options_v1`. They preserve the old result PODs and their release
functions. The corresponding `get_energy_evidence_v1` query borrows the same
owner and performs no solve: it exposes actual algorithm/temperature update,
final epsilon-times-HEOS conductivity, six outward signed enthalpy-power
planes and per-outer-step scalar identity. The previous entry points remain
available and retain their original numerical behavior.

The Python binding copies query views before release and records
`backend_version=full_2d_v3` or `full_3d_v2`. Candidate results have portable
`thermal_mode=conservative_energy`; `boundary_fluxes.true_h` contains the
existing actual h/inlet-h/mass arrays and the algorithm/version, six-face
`boundary_power`, its W/m or W units and a completeness flag. Heat is
`-sum(boundary_power)` for each side. SOU reconstructs physical enthalpy at
outlet faces, so older FOU cell-enthalpy reducers cannot supply that heat.
Missing or invalid face evidence makes the metric unavailable; no fallback
reconstruction occurs. Final post-flow pressure and velocity remain separate
from the accepted or capped last thermal state. 2D candidates retain the
true-h unit-depth convention and do not produce Richardson evidence.

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

## Shared finite-volume temperature consumers

The integrated fullCC candidate transports the
existing air/water integral h(T) using strict model-h drivers and actual
thermal mass faces. It replaces the earlier variable-cp m*cp*T proposal;
the earlier physical-contract failure is retained as history, not a description
of the current implementation. Earlier numerical and resource qualifications
remain tied to their recorded builds; final-library and application acceptance
remain separate gates. Fixed-cp Quick Design is a separate
approximation and is not a variable-cp integral-enthalpy claim.

The private `energy_fv_rows.hpp` supplies shared transport, Fourier conduction,
LTNE exchange and physical-source rows. It does not select a fluid model,
prepare SIMPLE/MAC faces, own an EOS or grant a consumer convergence policy.
CMake applies the same no-contraction floating-point policy to every source
that instantiates these shared rows, including the direct kernel smoke test.
This prevents link order from selecting differently rounded copies of the
same template. The policy is source-local; retained legacy thermal kernels
keep their existing compile options.
The actual caller boundaries are:

| Consumer | Driver and retained contract |
| --- | --- |
| Quick Design const/mean and standalone CC | `solve_temperature` in `temperature_driver.cpp`; fixed coefficients per pass, capacity transport, cold/warm start, bounded iteration and cancellation |
| Air/water full2D temperature main/fine and full3D CC Nz=1 | Strict `solve_model_h_2d`; existing air/water h(T), A-SOU/B-FOU, prepared mass/K/h_v and each caller's original budget |
| Air/water full3D CC Nz>1 | Strict `solve_model_h_3d`; SOU on both sides, prepared mass/K/h_v, prescribed B, asymmetric geometry and strict-only water/water support |
| Existing product model-h | Default non-strict model-h drivers and original eligibility/stopping rules; reuse by fullCC does not grant optimizer eligibility |
| Full3D true-h CC warm-up | Existing private `legacy_single_a_temperature` with empty prescribed B; original G4 two-sweep map for Nz=1, or Nz>1 with conservative=false and force_cell_centered=true. Both sides are solved; the following enthalpy driver retains its selected algorithm and physical gates |
| Single-A sCO2 CC | Same private G4 kernel with prescribed B and the original thermal budget; identity `legacy_frozen_cp_single_a_cc_v1`, preserving the prior single-fluid path without an integral h(P,T) ledger |
| Staggered/MAC temperature | Existing projection/cache and capacity-face preparation; retained nonconservative advective research correction has no fullCC integral-h qualification |
| True-h | Existing legacy H-FOU default or explicitly selected conservative T algorithms; EOS and their independent gates remain in the enthalpy driver |

The retained CC warm-up is a deterministic true-h caller contract, shared
with the existing single-A implementation. It adds no public selector or new
kernel copy. Its two-sweep result is only an initial state; the enthalpy
driver still validates every sCO2 warm temperature and supplies the final
thermal verdict. Nz>1 staggered warm-up keeps its existing shared-temperature
route. Full2D true-h does not consume this full3D warm-up.

FullCC uses the accepted thermal SIMPLE mass faces without multiplying them
by cp, reconstructing mass from cell velocity or applying porosity/opening
twice. The model-h driver evaluates the existing h(T) model on reconstructed
face temperatures and uses the original prepared Fourier conductivity and
exchange. Full2D rows/powers use unit depth and W/m. Full3D Nz=1 requires zero
active z-face mass, divides its physical mass by depth for the 2D solve, then
multiplies residual, source/reservoir and boundary powers by depth exactly once
to return W; temperature is unchanged.

Strict fullCC keeps duty/field stability and additionally requires a fresh
complete-boundary ledger: the larger of the phase sums of absolute cell
residuals and the coupled boundary/source imbalance must be <=1e-7 of the
interface exchange scale, with a one-native-power-unit floor. Failed
checks continue within the caller's budget; incomplete physical inflow cannot
converge. Strict SOU uses physical inlet distances and one-sided outflow
reconstruction; strict inlet Fourier conduction uses the resistance/moment
rule in both rows and audits. The non-strict product model-h boundary remains
unchanged. Nonzero fullCC manufactured volume sources remain unsupported.
Prescribed B remains an external temperature reservoir, is excluded from
updates/Anderson/solved equations, and has no fabricated B certificate.

The following guarded-line iteration describes only the fixed-coefficient
QD/standalone CC driver, not the strict fullCC model-h adapter. Standalone CC
reconstructs unique signed capacity faces from supplied cell fields; explicit
capacity inputs, where provided, already contain their porosity/area/depth
factors and override that reconstruction. It uses one T-minmod correction on
each internal face. With complete inflow,
active second-order transport and no red-black ordering, a block contains up
to four point sweeps and a guarded line-Newton trial. The trial is accepted
only when its actual-state physical error strictly decreases. Both comparison
states include the same 0.6 block damping; rejection retains the damped point
state. Point sweeps for A and SOU B use min(caller alpha,0.2); FOU B and
line trials use the caller alpha. Degenerate or red-black cases use point blocks. Budgets count every
requested step, and cancellation never certifies convergence.

In this fixed-coefficient driver, complete-boundary convergence requires
Q/field stability and fresh maximum phase residual/coupled boundary-source
balance <=1e-7, normalized by the larger
interface power with a 1 W or W/m floor. Direct-capacity calls cannot converge
with unidentified exterior inflow. Standalone reconstructed-capacity calls
retain their historical stability status for incomplete boundaries but expose
the missing boundary certificate explicitly. No EOS lookup occurs in this
fixed-coefficient driver. CC still rejects nonzero manufactured volume sources;
staggered/model-h retain their existing source capabilities. Prescribed B is
an external temperature reservoir and has no solved B residual certificate.

Read-only queries distinguish the executed fixed-coefficient guarded-line,
staggered and model-h recipes. FullCC identifies its spatial contract as
`model_h_tface_sou_fou_strict_v3` (2D/Nz=1) or
`model_h_tface_sou_sou_strict_v3` (Nz>1). The additive full2D/full3D
`get_model_enthalpy_evidence_v1` queries preserve existing solve-result layouts
and expose `tpmshx_model_enthalpy_evidence_v1`, not the former capacity-ledger
layout. Each solved fluid records [c0,c1,c2,Tbase,Tref] for the existing
quadratic cp(T) and its integral h(Tref)=0, alongside solved-phase flags,
physical residuals, source/reservoir power and outward m*h(T_face)/Fourier
planes. Views borrow the result owner; bindings copy them before release.
Main/fine 2D stages retain separate actual identities. The requested thermal
mode remains `temperature`; portable evidence declares
`model_enthalpy_temperature_v1`. Offline postprocessing validates and reduces
the captured powers without running a solver, EOS or new face reconstruction.
Availability is not convergence, and these records do not create product
model-h optimization eligibility. Missing declarations for new ledger fields
are invalid; historical files without new fields retain their original rules.

Current qualification is bounded. Sixty strict inlet resistance/moment smoke
configurations cover six directions and ten coefficient/boundary families;
they check local rows and ledgers, not a complete PDE grid-order result. The
defined N3 layered protocol separately passes independent operator/K=0
analytic checks, 84 accepted axial-order segments from 20 unique rows across
42 metrics, and the original absolute-error gates for six actual 64-cubed
manufactured-solution groups. It does not establish global second order for
arbitrary three-dimensional flows; 32-to-64 rates remain reported trends.
The original six-group MMS population passed zero of six groups. The original
axial population passed four of six groups and failed two. Those historical
results remain unchanged under the later protocol.

N5's twelve deliberately capped consumer requests returned successfully and
passed fourteen recorded-stage arithmetic audits, but zero of twelve product
requests converged and only two of fourteen thermal stages converged. The
separate normal-budget population passed all three complete steady consumers
(2D main/fine, 3D Nz=1 and 3D Nz>1) and all four thermal-stage audits. The prior
steady candidate's two-of-three result, including its failed 2D main/fine
gates, remains history. These fixed populations do not establish experimental
accuracy or N6 performance/memory acceptance; old fixed-capacity component
timings are not a same-operator h(T) full-driver cost comparison.

New native algorithms require independent matrix, analytic, grid-sequence,
actual-state balance and lifecycle qualification. Old-Python trajectory tests
remain historical same-algorithm evidence and cannot establish parity with a
changed native method. A native successful exit, complete physical ledger,
convergence and experimental accuracy are distinct facts. Python numerical
methods and the default backend remain separately controlled.

## Build and run the qualification checks

From the repository root, with an existing POSIX C++17 compiler and `make`:

```sh
make -f native/Makefile CXX=c++
make -f native/Makefile CXX=c++ shared
make -f native/Makefile check
```

This builds `.cache/native/libtpmshx_thermal.a`. Include `native/include` and
link that archive from a C++ caller. Building the temperature line solver
requires the existing locked Eigen headers, compiled with `EIGEN_MPL2_ONLY`.
`TPMSHX_EIGEN_INCLUDE` defaults to the locked CoolProp source's `externals/Eigen`
directory under `.cache/native-deps`; set it explicitly for an isolated source
tree. A missing directory fails the build without downloading dependencies.
The low-level archive links no Python, Qt, NumPy, CoolProp/EOS, OpenMP or
binding-library runtime. The complete dependency-pilot library retains its
separate EOS/pressure dependencies.
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
exceptions do not cross the C boundary. Independent C/C++ callers and direct
C ABI tests retain the buffer and physical-parameter checks. The retired
Python hybrid adapter is no longer part of the production execution path.
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

The old `TPMSHX_TRUE_H_KERNEL=cpp_sweeps_v1` setting no longer starts a
mixed solve. Python execution rejects that setting, including saved prepared
cases, before SIMPLE rather than silently changing the recorded algorithm.
The old selector is retained in environment snapshots only for this rejection;
unset or `numba` values use the unchanged Python kernel. New cases no longer
capture `TPMSHX_THERMAL_LIBRARY`. Use the complete native backend's
`--backend cpp --native-library /absolute/path/to/libtpmshx_solver_shared.dylib`
instead. Its host-local library path is supplied through `RunControl`.
Previously saved results remain readable and evaluable without a numerical
kernel or the former hybrid library. Python true-h evidence continues to
record `sweep_kernel='numba'` and `energy_audit='python'`.

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
ASan/UBSan builds. Windows required CI also passes the release allocation,
ABORT and recovery checks; this does not extend the sanitizer evidence to
Windows. Invalid input and
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
2D SIMPLE. Windows uses the locked portable CBLAS sources, exercised by the
required native CI suite. A serial momentum loop does not imply a single-threaded BLAS;
thread policy and measured performance must be recorded separately.

The `native-dependencies` CI matrix builds and runs these callers and required
tests on macOS/Python 3.13 and Windows/Python 3.12/3.13. A missing executable
fails the required job. Ordinary Python-only runs may skip an unbuilt pilot;
that skip does not establish native qualification. Both platforms have actual
required native CI passes; the evidence is bounded to those builds and cases.

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

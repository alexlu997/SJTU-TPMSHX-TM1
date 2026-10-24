# C++ solver migration under the V0.3 architecture

[中文](cpp-migration.zh-CN.md) | [English](cpp-migration.md)

## Status and architecture decision

The supplied **TPMS 均质化换热器求解软件总体框架说明 V0.3** (2026-09-08)
describes a target architecture, not delivered capabilities. Its three business
modules match the existing TM1 public flow:

```text
application -> preprocess.api -> CaseData -> solvers.api -> FieldResult
                                                           -> postprocess.api
```

Version 0.2 retains these boundaries and uses C++ as the only numerical backend.
Python keeps application interfaces, preparation, model resources, optimization
and postprocessing. Version 0.1 preserves both solver implementations.
The Python numerical backend and its extra research entries are retired in 0.2.
Shared temperature sweeps and energy audits remain in use. T-SOU is the default
for the existing conservative EOS route. H-FOU, T-FOU and the frozen H-sweep
C export are retired. Historical results and matching archived runtimes keep
their original algorithm identity.
Outer property Anderson is retired; fixed property relaxation and thermal
Anderson retain their existing rules.

Full 2D/3D and Quick Design use the matching library on macOS arm64 or Windows x64.
Public `RunControl` and CLI calls default to C++. The library path is a host
control and is not stored in `CaseData`. Missing libraries fail explicitly.
Delivery keeps the existing Python/Qt entry and a prebuilt library in the
project folder. Required CI, visible desktop acceptance, complete performance
and experimental accuracy remain separate gates.

Current numerical checks use independent formulas, discrete balances,
manufactured solutions, native component replay and fixed historical references.
Former Python/C++ comparisons remain evidence of their recorded builds in
[version 0.1](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/v0.1.0/docs/cpp-migration.md).
They are not rerun with a retained Python solver in 0.2.

## Complete Quick Design capability

`quick_design_driver.hpp` owns the complete prepared const/mean property-pass
calculation. This includes original empirical air/water or HEOS sCO2 properties,
existing Nu, one or two temperature passes, and full-field warm starts.
It also includes water liquid-state checks after each pass, iteration budgets,
progress and cancellation. Prepared
inlet-state analytical pressure fractions stay fixed. This is the existing
prescribed-flow sizing approximation, with `physical_validation=not_established`.

`solver_c_api.h` gives the independent versioned C entry point and named
configuration/result structures. It borrows nine arrays with explicit sizes.
Errors distinguish invalid inputs, water inlet/property states, water fields,
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
library on that host. Missing libraries, incorrect ABI or unsupported capabilities
fail explicitly. Public result saving, loading and offline evaluation use the
existing interfaces. Native CI on macOS and Windows includes fresh-process
saved-case replay without Numba/Python solver kernels, callback failures,
cancellation, recovery and concurrent runs.

These runs qualify the tested
C ABI and command-line paths. Visible desktop delivery stays a separate gate.

## Complete full 2D capability

`full_2d.hpp` and `full_2d_c_api.h` give the complete rectangular two-fluid
2D driver. It owns the existing SIMPLE flow updates, inlet pressure reference,
gas pressure shooting, property/closure updates, and outer coupling. It also owns
the selected temperature/model-h/true-h solve, Richardson transfer and final
field/energy certificates. Partial ports, spatial L/t fields, actual boundary fluxes and
distinct final-flow/thermal pressure states keep the prepared-case contract. The main heat metric stays W/m.

An explicit physical depth is still required
for total mass-flow optimization. Completed execution and convergence stay
separate, including capped iterations, failed certificates and cancellation.

Full 2D uses **ABI 2**: its 29th prepared array keeps the dimensionless
`(D_h_m * 1000) / L_mm` ratio from the original closure input. Reconstructing
that ratio from rounded SI lengths can change the last bits of graded-field
heat transfer coefficients. The C symbols and structures use `v2`, and the
adapter rejects an ABI 1 library before entering the numerical call. Distribute
the matching library, headers and adapter together. Saved FieldResult files
continue to use the existing portable reader without loading a native library.

The public call above also accepts a full 2D `CaseData`. CLI, desktop and design
hosts carry the same `RunControl`. Source CLI execution uses, for example:

```bash
"$PYTHON" -m sjtu_tpmshx.cli solve case.h5 results.h5 --backend cpp \
  --native-library /absolute/path/to/libtpmshx_solver_shared.dylib
```

The binding performs prepared-input validation, passes borrowed input views,
copies result-owned arrays before release and maps native evidence into the
existing `FieldResult`. Host library/table directories are not serialized in
cases or results. Fresh-process CLI solve, save/reload and offline evaluation
load no Numba or Python numerical driver. Current qualification checks full
fields, statuses, budgets, pressure and energy through independent audits and
native component replay. Historical Python comparisons keep their original
limits and verdicts. A macOS run does not establish Windows acceptance.

## Complete full 3D capability

`full_3d.hpp` and `full_3d_c_api.h` give the rectangular two-fluid 3D outer
driver through ABI 2. It consumes the same prepared XYZ fields and partial-port
geometry. It performs pressure-referenced SIMPLE flow and selected
temperature/model-h/true-h coupling. It returns the original final-state
certificates, warning evidence and field locations. The existing optional
coarse bootstrap keeps fine-grid pressure boundary values. No Python
numerical kernel supplies the native result.

Full 3D ABI 2 removes the outer property Anderson controls and result fields.
Use matching headers, libraries and bindings. The Python binding rejects ABI 1
before a numerical call. Fixed property relaxation and thermal Anderson remain.
Saved results remain readable; checkpoints still require the same build identity.

Bootstrap diagnostics use a separate query from the full result.
`tpmshx_full_3d_get_bootstrap_trace_v1(result, side, trace)` exposes a separate
read-only view for side 0/1. Its strings and layer array belong to the result
owner and stay valid only until `tpmshx_full_3d_release_v1`. A query performs
no numerical work or allocation. C callers must use the ABI 2 result layout.

The current Python binding requires the new
query symbol and reports a capability error for an older library. It never
fabricates a trace or substitutes a Python solve.

The trace records explicit enable/disable, actual coarse shapes/depths and
per-layer caps, entered iterations and stop reasons. It keeps the current
recursive `count > 2000`, child cap 200, minimum-axis and stopping rules.
`started_cap_sum` is the sum of caps for layers that entered an iteration,
not a shared global bootstrap limit. An unstarted cancelled parent contributes
zero iterations and no cap to that sum. The binding copies the trace before
release into `diagnostics.coarse_bootstrap_trace`. Saved results without this optional key stay readable.

The existing cooperative-cancellation result still owns its partial diagnostic
views, so a C caller can query them before release. The Python binding raises
`CancelledError` with the detached trace in `coarse_bootstrap_trace`, and does
not publish a partial FieldResult. Hard C API errors still leave the caller's
result untouched and publish no owner. A complete trace is consequently not
available through the query after such an error. Bootstrap-local failures
that the existing algorithm catches stay recorded without claiming an
applied seed or replacing actual charged work with a configured cap.

The shared physical-port pressure reduction keeps the reference masked
array order and contiguous pairwise summation for both weighted pressures
and open areas. This also fixes the inlet anchor used by pressure shooting.
Changing its summation order can change later SIMPLE stopping iterations even
when the initial pressure difference is only roundoff. Full-field checks must
therefore keep the original iteration budgets and comparison tolerances.

The same public `run_case` and CLI commands select it for a full 3D CaseData. Numerical qualification includes the original 24³ case and full field/pressure/
thermal evidence, with unchanged budgets and comparison gates. The historical
Python/native comparison of that capped case returned `converged=False`.
Agreement did not establish convergence. Full 3D model-h heat stays W.

The legacy
temperature route keeps its existing unavailable-heat boundary when complete
enthalpy evidence is absent. Optimization still applies its independent
model-h physical-boundary and energy certificates.

## Fixed-flow conservative temperature candidates

The C++ `solve_enthalpy` interface in `enthalpy_driver.hpp` uses
`EnthalpyAlgorithm::temperature_sou`. Both direct C entries use T-SOU.
Version 1 has a fixed 1e-8 K update gate; version 2 takes a positive K limit.
Both keep the strict normalized-h and boundary-imbalance gates.
The algorithm covers two solved fluids on a tensor grid,
including a unit-depth 2D extrusion. They require supplied signed mass faces,
local absolute pressures, effective solid conductivity and volumetric exchange
coefficients.

Directions 0 through 5 restrict inflow to the declared face.
Direction -1 assigns the scalar inlet state to every exterior inflow.
Full drivers keep their declared-port checks.

External conductive boundaries are
adiabatic. This entry does not prepare mass flow, solve SIMPLE or evaluate Nu.

Each nonlinear step freezes independent actual h, T and cp arrays, then performs
alternating forward/reverse A, B and solid sweeps. Fluid convection uses the
linearization h* + cp*(T-T*). Diffusion uses temperature. SOU freezes a minmod
correction reconstructed directly from actual enthalpy on physical coordinates,
including the outlet face, and uses full solid relaxation. SOU damps the completed three-phase block increment
by 0.6 before the actual state update.

This suppresses a demonstrated
limiter-driven oscillation on a stretched full-2D grid without changing its steady equation. Guarded HEOS PT updates then replace the linearized
enthalpy with the actual state before residuals and duties are evaluated. No
BICUBIC table, H-to-T inversion, clipping or recovery fallback is used.

SOU recipe 2 uses six-sample Anderson proposals on this damped ordinary map. It validates each proposal with actual HEOS PT properties and the original
energy audit before selecting it. A proposal must strictly reduce the maximum
of the equation and coupled ratios normalized by their original tolerances. Invalid or nonfinite proposals keep the ordinary update. Accepted proposals
continue iteration.

First/final blocks and small ordinary temperature updates
use a complete ordinary PT/audit block, and only that block can converge. `picard_relaxation=0.6` describes the ordinary map, not each Anderson increment. The same loaded library's `tpmshx_energy_algorithm_version_v1` query reports
SOU recipe 2 from the actual returned algorithm. Python records
this identity in main/outer evidence, effective settings and boundary capture.
A previous library without the query fails before conservative flow execution. Saved FOU recipe 1 and SOU recipe 1/2 boundary evidence stay readable, with no EOS
replay or version inference.

Recipe versions are independent of the C ABI.

The full drivers require positive coupled and equation tolerances and a positive
`temperature_update_tolerance` in K. Convergence requires all three tests on the
same actual state. `EnthalpyResult::algorithm` identifies the executed algorithm. `temperature_update` is present only on these routes. The existing `residual`
still records the normalized actual enthalpy update.

SOU final certificates
reconstruct its actual face corrections again and use them consistently in
boundary duty and local residuals. An iteration-limit result keeps its actual
certificate. Cancellation invalidates partial fields and clears that certificate.

`conservative_energy_smoke` validates independent frozen balances, six-direction
nonuniform face fluxes, reference-enthalpy invariance and invalid inputs.
`conservative_energy_driver_smoke` validates real EOS states, cold/warm consistency,
independently reconstructed outlet duty, cancellation, iteration limits and
physical-domain failures. The dependency-pilot verification runs both. Their
scope is fixed-flow numerical qualification. Full flow/closure acceptance,
stored historical comparisons and experimental applicability remain separate.

### Explicit full-flow candidate selection

Use the default `solver.enthalpy_algorithm=temperature_sou`
before `prepare_case`. Set `solver.enthalpy_temperature_tol_K` to the required
positive K tolerance before preparation. Then run the saved case with
`backend='cpp'` and the matching native library. The default K limit is 1e-8.
T-SOU applies to the existing two-fluid true-h routes. Model-h, other temperature
kernels and Quick Design keep their own physical routes. Explicit EOS controls
on incompatible routes fail before flow execution.

Full 3D candidates also support `port_wall_refine` on the prepared nonuniform
tensor grid, for full and partial openings. They use the actual cell widths and
port face masses. The model-h port-energy flag does not change this true-h path.
This support does not change the saved algorithm, defaults or acceptance gates.

This selection does not qualify new fluids, boiling, condensation or additional
Nu/Darcy-Forchheimer applicability. GUI selection is not yet exposed.

The complete driver keeps its original SIMPLE, pressure, property, outer
coupling and final acceptance gates. Full3D also keeps its two temperature
predictor sweeps and original mass preparation. The T-SOU recipe uses five
sweeps per nonlinear step, fluid relaxation .2 and solid relaxation 1. Full3D saves resolved controls in prepared
cases. Unset 2D controls use the recipe for the selected algorithm version.

With default controls, T-SOU keeps the full-driver iteration budgets.
Actual coupled and equation energy ratios must be no greater than .001.
The declared temperature update tolerance must also pass.
The native result records actual whole-block Picard relaxation 0.6.
It is separate from the fluid and solid row relaxation factors.

`tpmshx_solve_full_2d_v3` and `tpmshx_solve_full_3d_v2` accept the shared
`tpmshx_energy_options_v1`. They keep the previous result PODs and their release
functions. The corresponding `get_energy_evidence_v1` query borrows the same
owner and performs no solve. It exposes actual algorithm/temperature update,
final epsilon-times-HEOS conductivity, six outward signed enthalpy-power
planes and per-outer-step scalar identity. The previous entry points remain available and use the new T-SOU default.
Current libraries reject explicit retired algorithm IDs before flow. Old
checkpoints require their matching archived runtime and original controls.

Explicit controls use `tpmshx_solve_full_2d_v4` or `tpmshx_solve_full_3d_v3`.
They accept the same persisted EOS iteration, sweep, relaxation and convergence settings.
The 2D v4 control block also contains `tpmshx_energy_options_v2`.
It replaces the two thermal-control values in `config_v2`; other values retain their meaning.
The existing effective-settings query records the controls used by each thermal call.
Integral model-h routes reject these EOS overrides before flow execution.

The Python binding copies query views before release and records the entry used in `backend_version`.
Current libraries use `full_2d_v6` or `full_3d_v5`, which include the CPU thread limit.
Retained libraries can use the earlier energy or iteration-control entries when the requested controls are supported. Candidate results have portable
`thermal_mode=conservative_energy`. `boundary_fluxes.true_h` contains the
existing actual h/inlet-h/mass arrays and the algorithm/version, six-face
`boundary_power`, its W/m or W units and a completeness flag. Heat is
`-sum(boundary_power)` for each side. SOU reconstructs physical enthalpy at
outlet faces, so older FOU cell-enthalpy reducers cannot supply that heat.

Missing or invalid face evidence makes the metric unavailable. No fallback
reconstruction occurs. Final post-flow pressure and velocity stay separate
from the accepted or capped last thermal state. 2D candidates keep the
true-h unit-depth convention and do not produce Richardson evidence.

## First implemented slice

The frozen H-FOU sweep, its clipping rules and its low-level C export are retired.
Git history keeps the previous implementation. Shared `FluidView`, audit types
and `thermal_energy_audit` remain in `enthalpy_sweeps.hpp/.cpp` because the
conservative temperature kernels and actual-state audits consume them.
`conservative_energy_smoke` keeps independent frozen balances, pressure-offset
checks, diffusion lines, six-direction face powers and invalid-input checks.

## Second implemented slice: actual-state energy audit

The same library exposes `thermal_energy_audit` in
`native/src/enthalpy_sweeps.cpp`. It audits actual-state energy as follows:

- Actual-state A/B cell residuals: Fourier conduction + solid exchange − signed
  upwind enthalpy divergence. The caller supplies actual EOS temperatures and
  effective fluid conductivities, not the sweep's frozen linearization.
- Adiabatic solid cell residuals and all six signed boundary enthalpy duties.
  Inlet/backflow faces use prescribed inlet enthalpy, outflow uses cell enthalpy.
- The existing coupled and equation ratios, including the unchanged denominator
  `max(abs(Q_A), abs(Q_B), 1)`, fluid residual absolute sums/maxima and solid sum.
  Outputs are W per cell for 3D, W/m for the existing unit-depth 2D extrusion.

The operator applies **no acceptance threshold**. It does not evaluate EOS, validate state applicability, balance mass, count prior clipping or show
convergence. Those driver-owned checks stay mandatory. Invalid inputs are
rejected before residual output writes. Arithmetic overflow raises an error and
invalidates all output buffers. State/coefficient arrays stay read-only.

Qualification compares actual residual fields and budgets to independent
NumPy audit arithmetic, including the final ratio. Independent checks include six signed flow
directions, a one-cell 20 W exchange, internal-face cancellation, and isothermal
pressure-dependent enthalpy. They also include a deliberately unbalanced local
temperature field. Its global/coupled budget is zero, but its equation residual
is positive.

## Shared finite-volume temperature consumers

The integrated fullCC candidate transports the
existing air/water integral h(T) using strict model-h drivers and actual
thermal mass faces. It replaces the earlier variable-cp m*cp*T proposal.
The earlier physical-contract failure is kept as history, not a description
of the current implementation. Earlier numerical and resource qualifications
stay tied to their recorded builds. Final-library and application acceptance
stay separate gates. Fixed-cp Quick Design is a separate
approximation and is not a variable-cp integral-enthalpy claim.

The private `energy_fv_rows.hpp` supplies shared transport, Fourier conduction,
LTNE exchange and physical-source rows. It does not select a fluid model,
prepare SIMPLE/MAC faces, own an EOS or grant a consumer convergence policy. CMake applies the same no-contraction floating-point policy to each source
that instantiates these shared rows, including the direct kernel smoke test. This prevents link order from selecting differently rounded copies of the
same template. The policy is source-local.

Kept legacy thermal kernels
keep their existing compile options. The actual caller boundaries are:

| Consumer | Driver and kept contract |
| --- | --- |
| Quick Design const/mean and standalone CC | `solve_temperature` in `temperature_driver.cpp`. Fixed coefficients per pass, capacity transport, cold/warm start, bounded iteration and cancellation |
| Air/water full2D temperature main/fine and full3D CC Nz=1 | Strict `solve_model_h_2d`. Existing air/water h(T), A-SOU/B-FOU, prepared mass/K/h_v and each caller's original budget |
| Air/water full3D CC Nz>1 | Strict `solve_model_h_3d`. SOU on both sides, prepared mass/K/h_v, prescribed B, asymmetric geometry and strict-only water/water support |
| Existing product model-h | Default non-strict model-h drivers and original eligibility/stopping rules. Reuse by fullCC does not grant optimizer eligibility |
| Full3D true-h CC warm-up | Private `legacy_temperature_warmup`. Original G4 two-sweep map for Nz=1, or Nz>1 with conservative=false and force_cell_centered=true. Both sides are solved. The following enthalpy driver keeps its selected algorithm and physical gates |
| Staggered/MAC temperature | Existing projection/cache and capacity-face preparation. Kept nonconservative advective research correction has no fullCC integral-h qualification |
| True-h | T-SOU default. EOS relations and independent physical gates stay in the enthalpy driver |

The CC warm-up supplies coupled A, B and solid temperatures before each outer
enthalpy solve. The first call starts from inlet fluid temperatures and the
configured solid seed, or the mean inlet temperature. Later calls start from
the previous thermal fields. Two sweeps avoid a complete capacity-temperature
solve whose result the enthalpy solve would replace. The warm-up is a numerical
initialization for the steady solver. The existing evidence does not
show that two sweeps are necessary or faster than no warm-up.

The enthalpy driver validates the initial PT states and supplies the final
thermal verdict. The CC warm-up keeps its rows, order, relaxation and two-sweep
budget. Nz>1 staggered warm-up uses the shared temperature rows with
caller relaxation and live serial SOU corrections. Red-black corrections are
frozen for one sweep. The original exterior solid self terms stay in the
iteration diagonal. This call does not use standalone temperature block damping.
Full2D true-h does not consume this full3D warm-up.

Single-A sCO2 execution is retired. The native input boundary rejects an sCO2
A side with inactive B before numerical work. Air/water inactive-B validation
and its pause/restore coverage remain. Archived results with
`legacy_frozen_cp_single_a_cc_v1` keep their missing complete h(P,T) transport
status. They cannot acquire a model-enthalpy ledger. Old single-A sCO2
checkpoints require their matching archived runtime.

FullCC uses the accepted thermal SIMPLE mass faces without multiplying them
by cp, reconstructing mass from cell velocity or applying porosity/opening
two times. The model-h driver evaluates the existing h(T) model on reconstructed
face temperatures and uses the original prepared Fourier conductivity and
exchange. Full2D rows/powers use unit depth and W/m. Full3D Nz=1 requires zero
active z-face mass. It divides physical mass by depth for the 2D solve.

It then multiplies residual, source/reservoir and boundary powers by depth
exactly one time to return W. Temperature is unchanged.

Strict fullCC keeps duty/field stability and additionally requires a fresh
complete-boundary ledger. Its numerator is the larger of the phase sums of
absolute cell residuals and the coupled boundary/source imbalance. Its denominator
is the interface exchange scale, with a floor of one native power unit. This ratio must be <=1e-7. Failed
checks continue within the caller's budget. Incomplete physical inflow cannot
converge.

Strict SOU uses physical inlet distances and one-sided outflow
reconstruction. Strict inlet Fourier conduction uses the resistance/moment
rule in both rows and audits. The non-strict product model-h boundary stays
unchanged. Nonzero fullCC manufactured volume sources stay unsupported. Prescribed B stays an external temperature reservoir, is excluded from
updates/Anderson/solved equations, and has no fabricated B certificate.

The following guarded-line iteration describes only the fixed-coefficient
QD/standalone CC driver, not the strict fullCC model-h adapter. Standalone CC
reconstructs unique signed capacity faces from supplied cell fields. Explicit
capacity inputs, where given, already contain their porosity/area/depth
factors and override that reconstruction. It uses one T-minmod correction on
each internal face. With complete inflow,
active second-order transport and no red-black ordering, a block contains up
to four point sweeps and a guarded line-Newton trial. The trial is accepted
only when its actual-state physical error strictly decreases.

Both comparison
states include the same 0.6 block damping. Rejection keeps the damped point
state. Point sweeps for A and SOU B use min(caller alpha,0.2). FOU B and
line trials use the caller alpha. Degenerate or red-black cases use point blocks. Budgets count each
requested step, and cancellation never certifies convergence.

In this fixed-coefficient driver, complete-boundary convergence requires Q/field
stability. It also requires a fresh maximum phase residual/coupled boundary-source
balance ratio <=1e-7. The normalization uses the larger interface power with a
1 W or W/m floor. Direct-capacity calls cannot converge
with unidentified exterior inflow. Standalone reconstructed-capacity calls
keep their historical stability status for incomplete boundaries but expose
the missing boundary certificate explicitly.

No EOS lookup occurs in this
fixed-coefficient driver. CC still rejects nonzero manufactured volume sources.
Staggered/model-h keep their existing source capabilities. Prescribed B is
an external temperature reservoir and has no solved B residual certificate.

Read-only queries distinguish the executed fixed-coefficient guarded-line,
staggered and model-h recipes. FullCC identifies its spatial contract as
`model_h_tface_sou_fou_strict_v3` (2D/Nz=1) or
`model_h_tface_sou_sou_strict_v3` (Nz>1). The additive full2D/full3D
`get_model_enthalpy_evidence_v1` queries keep existing solve-result layouts
and expose `tpmshx_model_enthalpy_evidence_v1`, not the former capacity-ledger
layout. Each solved fluid records [c0,c1,c2,Tbase,Tref] for the existing
quadratic cp(T) and its integral h(Tref)=0, alongside solved-phase flags,
physical residuals, source/reservoir power and outward m*h(T_face)/Fourier
planes. Views borrow the result owner. Bindings copy them before release.

Main/fine 2D stages keep separate actual identities. The requested thermal
mode stays `temperature`. Portable evidence declares
`model_enthalpy_temperature_v1`. Offline postprocessing validates and reduces
the captured powers without running a solver, EOS or new face reconstruction. Availability is not convergence, and these records do not create product
model-h optimization eligibility.

Missing declarations for new ledger fields
are invalid. Historical files without new fields keep their original rules.

Current qualification is bounded. Sixty strict inlet resistance/moment smoke
configurations cover six directions and ten coefficient/boundary families.
They validate local rows and ledgers, not a complete PDE grid-order result. The
defined N3 layered protocol separately passes independent operator/K=0
analytic checks. It passes 84 accepted axial-order segments from 20 unique rows
across 42 metrics. It also passes the original absolute-error gates for six
actual 64-cubed manufactured-solution groups.

It does not show global second order for
arbitrary three-dimensional flows. 32-to-64 rates stay reported trends. The original six-group MMS population passed zero of six groups. The original
axial population passed four of six groups and failed two. Those historical
results stay unchanged under the later protocol.

N5's twelve deliberately capped consumer requests returned successfully and
passed fourteen recorded-stage arithmetic audits. Zero of twelve product
requests converged. Only two of fourteen thermal stages converged. The
separate normal-budget population passed all three complete steady consumers
(2D main/fine, 3D Nz=1 and 3D Nz>1) and all four thermal-stage audits. The prior
steady candidate's two-of-three result, including its failed 2D main/fine
gates, stays history.

These fixed populations do not show experimental
accuracy or N6 performance/memory acceptance. Previous fixed-capacity component
timings are not a same-operator h(T) full-driver cost comparison.

New native algorithms require independent matrix, analytic, grid-sequence,
actual-state balance and lifecycle qualification. Previous-Python trajectory tests
stay historical same-algorithm evidence and cannot show parity with a
changed native method. A native successful exit, complete physical ledger,
convergence and experimental accuracy are distinct facts. The native default does not expand physical applicability.

## Build and run the qualification checks

From the repository root, with an existing POSIX C++17 compiler and `make`:

```sh
make -f native/Makefile CXX=c++
make -f native/Makefile check
```

This builds `.cache/native/libtpmshx_thermal.a`. Include `native/include`. Link that archive from a C++ caller. Building the temperature line solver
requires the existing locked Eigen headers, compiled with `EIGEN_MPL2_ONLY`. `TPMSHX_EIGEN_INCLUDE` defaults to the locked Eigen source
under `.cache/native-deps/src/Eigen-5.0.1`. Set it explicitly for an isolated source
tree.

A missing directory fails the build without downloading dependencies. The low-level archive links no Python, Qt, NumPy, CoolProp/EOS, OpenMP or
binding-library runtime. The complete dependency-pilot library keeps its
separate EOS/pressure dependencies. The `check` target builds and runs independent C++ temperature and conservative-energy callers.
The old pure thermal shared target exported only the retired H sweep and is removed.
The complete dependency build keeps C static/shared callers for direct T-SOU,
full 2D/3D, model-h, temperature and flow interfaces on both target platforms.

The library is not bundled with the Python
wheel or desktop application, discovered automatically, or built during a run.

From an existing x64 Visual Studio developer command prompt on Windows:

```bat
nmake /f native\Makefile.msvc check
```

This builds `tpmshx_thermal.lib` under `.cache/native` and runs the same C++ callers.
These commands do not install a compiler. The full solver C ABI keeps explicit
Windows exports/imports and `cdecl`; ctypes loads its DLL through `CDLL`.

`thermal_c_api.h` keeps shared export and calling-convention macros.
Its frozen H-sweep export is retired. Complete C interfaces keep bounded
errors and buffer/physical checks. Exceptions do not cross the C boundary.
The energy-audit tests keep a test-only bridge.

Use the interpreter from `.venv-path`, after the normal environment checks:

```sh
tm1_python="$(head -n 1 .venv-path)"
"$tm1_python" -m sjtu_tpmshx.runs.tools.check_locked_environment
"$tm1_python" -m pip check
MPLCONFIGDIR="$PWD/.cache/matplotlib" \
XDG_CACHE_HOME="$PWD/.cache/xdg" \
TPMSHX_REQUIRE_CPP_TESTS=1 TPMSHX_REQUIRE_NATIVE_DEPS_TESTS=1 \
"$tm1_python" -m pytest -q sjtu_tpmshx/tests/native
```

Every explicit `TPMSHX_TRUE_H_KERNEL` override is retired, including `numba`
and `cpp_sweeps_v1`. Saved prepared requests fail before flow execution.
Remove the override to use native execution. The key remains in environment
snapshots only for this explicit rejection. New cases do not capture
`TPMSHX_THERMAL_LIBRARY`; native library selection belongs to `RunControl`.
Saved results remain readable without loading a solver library. Historical
Python `sweep_kernel` and `energy_audit` records retain their original meaning.

The required flag makes a missing compiler fail this qualification command.
Optional local component tests can skip when the platform compiler is
absent. That skip is not native acceptance. Native qualification is required
in the existing macOS 3.13 and Windows 3.12/3.13 fast CI lanes. A local macOS
pass does not show Windows compilation, execution or distribution
acceptance. No compiler or Python dependency is installed by these tests.

Native enthalpy sweep tests retain fixed-seed variable fields, signed and zero
face flows, nonuniform grids, six directions, single-cell axes, zero diagonal,
clipping and rejection before mutation. Independent physical checks cover
isothermal pressure-dependent enthalpy and exponential cooling, including
first-order grid convergence and boundary/source energy balance.
Zero-change references retain `atol=2e-8 J/kg` and `atol=2e-11 K`.
Clipping counts stay within the charged sweep budget. Native builds do not
enable fast-math. These checks qualify numerical operators, not experimental
sCO2 prediction or application speed.

For the energy audit, the fixed comparison tolerances are `rtol=2e-12`,
`atol=1e-9 W` per cell, `atol=1e-8 W` for reduced budgets, and `atol=1e-12`
for dimensionless ratios. The same source unit normalization applies in 2D. These compare arithmetic implementations. They do not change production gates. Performance qualification includes input checks and binding overhead. Separate
EOS initialization, native builds, kernel execution and complete solve time.
Historical Numba timings remain tied to version 0.1 and their matched routes.

Public execution tests retain physical-field, signed boundary-flux, pressure,
metric, file-handoff, cancellation and actual native-error checks. Native
engineering cases keep the original F2, convergence and energy gates.

## Isolated EOS and pressure dependency qualification

Native dependencies require an explicit build, separate from production backend
selection. `native/dependency-pilot/` is the build project for the current native backends.
Its inputs are locked in
[`native/dependencies-lock.toml`](../native/dependencies-lock.toml).
These include CoolProp 8.0.0, its nine required CPM header dependencies at fixed
commits, and SuperLU 7.0.1 with three selected SciPy 1.18.1 double-LU corrections.
The SuperLU source is not identical to SciPy's bundled revision. They also
include AMGCL 1.5.0 and portable CMake 4.4.4. Source, binaries,
logs and tabular EOS files stay under the worktree's `.cache/native-deps`.
[`native/THIRD_PARTY_NOTICES.md`](../native/THIRD_PARTY_NOTICES.md) records the
linked components and their original license notices.

After explicit native-dependency provisioning authorization, use the configured
interpreter and the existing lock checks. `fetch` provisions the complete dependencies.
`build` is offline and does not install Python packages or change the shared
environment. `fetch-eigen` fetches only the fixed Eigen 5.0.1 headers for the
EOS-free thermal library. The CoolProp build uses explicit local CPM paths with
FetchContent disconnected; it does not fetch optional test or wrapper modules:

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
Python reference: HEOS or BICUBIC&HEOS. It validates forward properties, enthalpy
inversion, existing CO2 applicability bounds, stable liquid-water guards and
independent mutable states. It does **not** replace the project's empirical
air/water transport functions with CoolProp values. Each process uses an
explicit table directory. It does not change the parent Python EOS settings.
Property comparison tolerances are fixed in `test_native_eos.py` and are
separate from PDE acceptance and BICUBIC interpolation error versus HEOS.

The pressure caller consumes canonical 32-bit CSR with the original zero
Dirichlet rows and reports the original `Ax-b` residual and pin error. 2D and
3D systems with at most 2000 cells use SuperLU/COLAMD. Larger 3D systems use
the original PyAMG 5.3 classical strength, splitting, modified interpolation,
Galerkin order and symmetric Gauss–Seidel cycle. They keep the original SciPy
BiCGStab stopping and breakdown policy. The 200-iteration budget, resolved
relative tolerance and current-matrix multiplication with reused preconditioners
stay unchanged.

Only the original breakdown path retries with L2-scaled RHS.
Qualification reports the unscaled equation residual. The initial AMGCL pressure
candidate failed full-case comparison and is replaced. AMGCL still supplies
the separate staggered-temperature projection. The build excludes MC64/ILU and uses
the three locked SciPy double-LU numerical corrections.

SuperLU calls now use a pure-C error boundary and a thread-local allocation
ledger. Allocation failures and ABORT return bounded errors after cleanup. The jump never crosses a C++ frame. macOS qualification injects failure at
each observed allocation ordinal under release and ASan/UBSan builds. It validates same-process recovery, long ABORT messages, singular info and
simultaneous independent threads in those builds.

Windows required CI also passes the release allocation,
ABORT and recovery checks. This does not extend the sanitizer evidence to
Windows.

Invalid input and
unknown backend errors do not silently fall back to LU. These pressure tests
do not by themselves show complete native SIMPLE or outer coupling qualification.

Complete fixed-flow true-h, 2D/3D model-h, and 2D/3D SIMPLE drivers now have
independent C++ implementations, versioned C interfaces and explicit Python
bindings under `solvers/backends/cpp/`. Thermal bindings return the existing
energy and raw-boundary metadata. Native model-h owns its audit arrays until
the C caller releases the result. The Python binding copies those views
before release. Callback exceptions and cancellation discard partial states.

The SIMPLE interfaces own per-instance pressure caches and keep the original
F2, outlet, warm-state and raw-mass evidence. These independently callable
drivers also support the full 2D/3D outer-coupled backends described above.

The macOS SuperLU build uses the system Accelerate BLAS used by the pinned SciPy reference. It keeps the original CSR/transposed LU operation order for 2D SIMPLE. Windows uses the locked portable CBLAS sources, exercised by the
required native CI suite. A serial momentum loop does not imply a single-threaded BLAS.
Thread policy and measured performance must be recorded separately.

The `native-dependencies` CI matrix builds and runs these callers and required
tests on macOS/Python 3.13 and Windows/Python 3.12/3.13. A missing executable
fails the required job. Optional local component runs can skip an unbuilt pilot.
That skip does not show native qualification. Both platforms have actual
required native CI passes. The evidence is bounded to those builds and cases.

<a id="remaining-stages-and-acceptance-gates"></a>

## Migration stages and remaining acceptance gates

The table records the original migration stages and their acceptance requirements.
Version 0.2 has retired Python numerical execution and uses C++ for all public solve routes.
Historical comparisons keep their original results. Current execution and recovery are described in [architecture](architecture.md).
Platform CI, visible desktop acceptance, performance, and experimental accuracy remain separate checks.

| Stage | Implementation boundary | Required evidence before advancing |
| --- | --- | --- |
| 0: thermal operators | Independent native sweeps and energy-audit operators. The Python/C++ hybrid selector is retired. | Operator checks plus public field/flux/metric, handoff, cancellation and error comparisons. |
| 1: complete thermal driver | Port Picard state, property refresh, EOS inverse, residuals, warm starts and cooperative cancellation in the same order. Keep fluid properties separate from Nu/hv closure evaluation. | Fixed inlet/pressure/grid inputs. A/B/solid equation and boundary-energy criteria unchanged. Clipped/invalid/cancelled runs keep their meaning. Compare detached native fields and fluxes. |
| 2: flow and coupling | Port SIMPLE/Brinkman–Forchheimer operators, pressure and mass corrections, then the existing outer coupling order for a declared subset of rectangular cases. | Momentum and fresh-density local/global mass F2 gates. Physical inlet-pressure, outlet/backflow and energy checks. Directional and grid tests. Same prepared geometry/closures, no coefficient retuning. |
| 3: actual C++ backend | Add the smallest solver-side adapter needed to consume CaseData and produce complete FieldResult. Advertise only the accepted capability subset. | Run without the Python solver kernels. Separate-process case/result handoff, state/units/field locations and model provenance. Missing or unsupported capabilities explicitly rejected. |
| 4: application and release | Select the qualified backend through the existing public solver API, keeping GUI/design/optimization callers and offline postprocessing. | Fixed 2D/3D cases only where supported. Cross-backend Q/pressure/temperature/flux checks with predetermined tolerances. Build and packaging evidence on each supported platform. |

Before stage 1, select the native property-library delivery and licensing/build
strategy explicitly. The current Python CoolProp installation is not evidence
of a complete portable C++ development/runtime package. Do not silently replace
HEOS with a fit or reuse the sCO2 calibration to absorb porting error. Common
closures must keep production versions, sources and validity rules across
languages, without separately refitting their coefficients.

The local CoolProp 7.2.0 wheel inspected on 2026-09-21 contains C++ headers and
an MIT license. Its binary is a CPython Mach-O bundle, not a separately
linkable `libCoolProp`. A standalone C++ link attempt fails with unsupported
Mach-O file type. No independent archive/dylib was found in that environment. At that inspection no source was downloaded and no dependency was installed.

The subsequently authorized isolated build is described above. The current full driver requires qualified HEOS PT states, actual energy
and recovery on each target platform, including actual Windows execution.
Historical BICUBIC records keep their original meaning.

Freeze representative baseline cases and comparison tolerances **before each stage's comparison**. Keep failed cases and their original denominators.
Run analytic/grid/conservation qualification separately from experiment
validation. The legacy 83-case record stays a historical record. A native
port does not inherit its experimental claims. Performance measurements must
separate compilation, EOS, flow, thermal sweeps and overall time and use
equally warmed runs with the same convergence gates.

OpenFOAM, a complete external solver ABI, general unstructured meshes, extra physical
models and a framework of abstract factories are not prerequisites for this
port. Add each only for a specified, separately qualified capability.

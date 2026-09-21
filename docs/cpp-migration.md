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

**The native library is an unconnected thermal-kernel pilot. It is not
a complete C++ solver backend.** The production solver still uses Python/Numba;
no `backend='cpp'` capability is advertised or enabled. Replacing only an inner
kernel would also remain acceleration of the Python backend under V0.3 §3.2.1.

The agreed sequence (2026-09-22) is to finish Python solver cleanup and qualify
repeatable case/field/flux comparisons and cancellation/error handling first.
Keep the existing pilot and its tests during that work; defer connecting a new
C++ execution path until the Python reference and its physical scope are stable.

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

## Build and run the qualification checks

From the repository root, with an existing POSIX C++17 compiler and `make`:

```sh
make -f native/Makefile CXX=c++
```

This builds `.cache/native/libtpmshx_thermal.a`. Include `native/include` and
link that archive from a C++ caller. There is no Python, Qt, NumPy, CoolProp,
OpenMP, CMake or binding-library dependency in the native library itself.
The pilot is not included in the Python wheel or desktop application.

The tests compile a temporary shared library and use **a test-only ctypes
bridge**. That bridge is not a stable C ABI or a production backend adapter.
Use the interpreter from `.venv-path`, after the normal environment checks:

```sh
tm1_python="$(head -n 1 .venv-path)"
"$tm1_python" -m sjtu_tpmshx.runs.tools.check_locked_environment
"$tm1_python" -m pip check
MPLCONFIGDIR="$PWD/.cache/matplotlib" \
XDG_CACHE_HOME="$PWD/.cache/xdg" \
NUMBA_CACHE_DIR="$PWD/.cache/numba" \
TPMSHX_REQUIRE_CPP_TESTS=1 \
"$tm1_python" -m pytest -q sjtu_tpmshx/tests/native/test_enthalpy_sweeps.py
```

The required flag makes a missing compiler fail this qualification command.
General Python-only testing skips these tests when the POSIX compiler is absent;
that skip is not native acceptance. Windows build/distribution qualification
is outstanding. No compiler or Python dependency is installed by these tests.

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
speedup, and neither slice is automatically selected by production.

## Remaining stages and acceptance gates

| Stage | Implementation boundary | Required evidence before advancing |
| --- | --- | --- |
| 0: thermal operators | The native sweeps and actual-state energy audit above; production remains Python. | Compile and same-algorithm/physical operator checks. |
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
No source was downloaded and no dependency was installed. Before a complete
driver, provision and qualify an independent native CoolProp build, preserve its
license notices, and verify the same HEOS/final-state and BICUBIC iteration
semantics on each target platform. This delivery requirement is still open.

Freeze representative baseline cases and comparison tolerances **before each
stage's comparison**, preserving failed cases and their original denominators.
Run analytic/grid/conservation qualification separately from experiment
validation. The legacy 83-case record remains a historical record; a native
port does not inherit its experimental claims. Performance measurements must
separate compilation, EOS, flow, thermal sweeps and overall time and use
equally warmed runs with the same convergence gates.

OpenFOAM, a stable external C ABI, general unstructured meshes, extra physical
models and a framework of abstract factories are not prerequisites for this
port. Add each only for a specified, separately qualified capability.

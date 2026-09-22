# SJTU-TPMSHX-TM1 architecture

This is the current architectural and physical contract for the repository.
Historical audits and reports explain how the project reached this state, but
they do not override the running code or this document.

## Runtime flow

```text
applications -> preprocess.api -> CaseData -> solvers.api -> FieldResult
                                                          -> postprocess.api -> PerformanceResult
                         domain / models / versioned resources / file I/O
```

- `domain/` owns immutable CaseData, FieldResult, metric definitions and
  runtime control ports; it is Qt-free.
- `preprocess/` owns physical grid/boundary preparation, fixed geometry and
  coefficients, model/resource selection and portable execution inputs.
- `solvers/backends/python/` owns prepared numerical execution, current-state
  property evaluation and native result capture; SIMPLE/LTNE kernels remain
  under `solvers/`. It does not import preprocessing or formal postprocessing.
  The 2D loop reads prepared properties directly, reports through `RunControl`,
  and returns application coefficients and zone statistics with its native
  result; it has no window-shaped runtime adapter or attribute-write hooks.
- `postprocess/` reduces recorded fields, fluxes and pressure states. It never
  reruns a solver or reads a private runtime object to recover missing evidence.
  Full-compute evaluation reuses successful heat and mass reductions only within
  that call, lazily by side and by coarse/fine evidence. Each requested metric
  retains its own missing/unsupported/invalid status handling.
- `models/` and `df_surrogate/` own shared pure closures and versioned resources.
  Explicit cleaning/calibration entry points live under `preprocess/offline/`.
- `io/` owns strict YAML/HDF5/JSON interchange. VTK export is a postprocessing
  view of recorded data, not a new numerical state.
- `configs/` owns packaged case configuration.
- `pipelines/` retains explicit scripted stage entry points. Callers import
  shared models and numerical backends directly; there are no `sys.modules`
  aliases or import-time function injection into the numerical backend.
  The retained dictionary-based 3D entry is `run_stack_3d._run_3d_stack`.
  Research and conservation tools still use it for single-fluid and manufactured
  source cases outside `ComputeConfig`; it shares the prepared numerical backend
  rather than carrying another solver. It is not a compatibility alias to remove
  before those physical cases have an equivalent public contract.
  It and `_build_3d_problem` accept keyword-only `control=RunControl(...)`,
  forwarded to initial SIMPLE and outer coupling. Runtime callbacks do not
  belong in `cfg`: `_cancel_check`, `_progress_cb` and `_iter_cb` are rejected
  with a migration error. Use `RunControl.cancel_check`, `.progress` and
  `.outer_iteration(current, total)` respectively; `.iteration(message)` is
  the separate text callback. Existing calls without controls remain valid.
  Former `stages_2d`, `stages_3d` and `_stage_common` import facades are retired;
  preparation and shared helpers are imported from their owning modules.
  The former `solvers.envelope` and `solvers.roughness` facades are also retired.
  Grid and projection helpers come from `models.grid` and `models.df_projection`;
  `solvers.df_projection` retains its active pressure reductions only.
- `controllers/compute_pipeline.py` sequences the public modules; the module
  adapter maps their results to the historical GUI ComputeResult contract.
  It is the sole production result mapper. The old 2D/3D mappings remain only
  as frozen test oracles for the real native-result integration comparison.
- `ui/` owns PySide6 and PyVista presentation only.
  Its canvas workbench reuses the existing parameter widgets in a left-hand
  geometry/boundary/solver inspector. Field phase and 3D z-slice selections
  read the accepted result snapshot; draft edits do not replace that source.
  Figure exports follow the selected view, while CSV/NPZ exports retain the
  complete result. `ui/typography.py` uses native sans-serif fonts for Qt and
  keeps publication fonts for Matplotlib/VTK, without bundling font files or
  importing Qt into lower layers. Ordinary GUI computations capture the
  launch thread's Numba mask and apply/restore it in the reused Qt worker;
  optimization retains its independent process/thread resource policy.
  Desktop inputs use uniform velocity over each inlet opening, local-density
  thermal transport enabled, and no additional six-wall refinement. Port/wall
  refinement is selected through the mesh scheme. Loading a GUI preset or
  session with different retired settings reports the conversion and saves
  the current explicit settings; scripted solver configuration remains separate.
- `validation/` and `runs/` are executable research and verification tools,
  not alternative production implementations.

The GUI entry point is `python -m sjtu_tpmshx.main`; source-based headless
work uses `python -m sjtu_tpmshx.cli`. Parameter optimization and design use
the same public contracts with their explicitly named approximation modes.
M-A review, CI and merged-main acceptance for the rectangular 2D/3D module
flow are retained in [fixed history](history/README.md). Current M-B extensions
and their unmet acceptance conditions are listed in [capabilities](capabilities.md);
historical baseline failures retain their original status.

Production domain shapes are currently limited to **Rectangle**, in 2D and 3D.
The desktop displays a fixed rectangle/cuboid label, with no polygon controls.
Saved polygon presets are rejected before modifying inputs or results; polygon
startup sessions are not restored, with an explicit notice. Saved rectangular
files remain supported and write shape index 0 explicitly. The historical
`ui/polygon_calc.py`, polygon kernels and triangular meshing are retired. Original code
is linked in the [history index](history/retired-tools.md).
Reopening polygon compute requires the mainline physical rules and real
CaseData/FieldResult/PerformanceResult handoff, not just relocating the GUI code.

The 2D momentum solver uses SIMPLE. The experimental SIMPLER branch is retired;
its original benchmark and negative result remain in the history index.

The B-side partial-opening experiments (M4 area scaling, per-cell participation
mask, temperature freezing and H2 outlet conductivity suppression) are retired.
Explicit retired settings are rejected before execution, including in research
dictionaries and directly prepared inputs. Real port locations, dimensions,
directions and physical mass/energy checks remain active. The default model
applies no extra B-side participation correction. The independent
`TPMSHX_SCO2_COMPRESSIBLE` A-side pressure/property experiment remains separate;
it is not the GUI's local-density thermal-transport setting.
Historical experimental cases and their original results are indexed in
[retired tools](history/retired-tools.md); rerunning their geometry under the
current model produces a new comparison, not a reproduction of that experiment.

Historical water-Nu comparisons and the old full-face 2D enthalpy reference now
live in `tests/water_nu_reference.py` and `tests/enthalpy_2d_reference.py`.
Production keeps the direct water CFD closure and shared 3D enthalpy adapter.
The unused `postprocess.report` and `postprocess.visualization` helpers are
retired; public evaluation, recorded-field plots and exports remain supported.

### Shared solver implementation

All supported fluids use `SIMPLESolver` in 2D and `SIMPLESolver3D` in 3D.
`solvers/_solve_common.py` owns F2 configuration and the common convergence
monitor: momentum, fresh-density local/global mass and outlet backflow must
pass consecutive checks. Full compute, screening and raw solver calls now
use this same criterion. `convergence_mode=None` resolves to `f2`; explicit
`legacy` is rejected. A static field triggers a check and never certifies
convergence alone. The mass-only/velocity exit and its inner SIMPLE Anderson
implementation are retired. Thermal and outer-coupling Anderson remain active.

`tol_simple`, SIMPLE's `solve(tol=...)` argument and `TPMSHX_SIMPLE_TOL` are
retired: they did not set F2 tolerances. Old configuration-file import discards
`solver.tol_simple` and `optimizer.tol_simple` with an explicit notice; new
configurations omit them. Use `mom_tol`, `mass_local_tol` and `mass_global_tol`
for the independent F2 gates. The pressure-subproblem residual history retains
its definition because adaptive AMG consumes it. Runtime/accuracy comparisons
between full compute and screening must compare actual inputs, approximation
modes, grids, iteration budgets and F2 settings.
Coarse bootstrap supplies a bounded initial guess, not a convergence certificate.
Old result files remain readable; rerunning an explicit legacy configuration
requires selecting F2 and accepting the independently measured result.

Both backends consume `models/fluid_props.FluidModel`. Correlations, property
sources and validity checks stay in their owning model modules. Shared outer
iteration and temperature-delta tracking live in `coupling_skeleton.py`; both
full-compute drivers track Ta, Tb and Ts, with the existing extra 2D density
gate. Dimension-specific solve order and native flux capture remain explicit.

The 2D SIMPLE constructor consumes prepared drag arrays for zoned geometry;
its former `zone_config` row-prediction path is retired. Arguments following
`P_ref` are keyword-only, so old positional zone arguments cannot be silently
reinterpreted. Residual callbacks propagate their original exceptions through
both full compute and screening; they are not best-effort UI notifications.

The 3D outer loop owns one live `_OuterState`, returned after iteration without
a second synchronized state copy. Its steps prepare local heat transfer and
transport inputs, run temperature/model-h or the true-h warm start and solve,
detach native thermal evidence, then record diagnostics and check convergence.
The nonconverged post step refreshes A flow, thermal properties, then B flow;
A and B retain their distinct temperature/property update order. Model-h mass
faces are captured before temperature-face balancing; true-h separately
balances and projects its mass transport. Per-call transport inputs do not
become persistent iteration state. The native thermal snapshot stays detached
from the conductivity, capacity and final SIMPLE arrays updated by post.

Iteration labels, the 3D progress fraction and SIMPLE cap logs use the effective
per-run limits. The 3D default outer budget is 12 (3 for `fast_sweep`); progress
marks iteration entry and is not elapsed-time progress or proof of convergence.
The application pipeline reserves separate progress intervals for preparation
and publication, then reports completion after the required stages return.

The 3D initial A/B SIMPLE dispatch uses one level of parallelism. If either
side reaches the existing parallel-sweep grid threshold, A and B run in order
on the caller thread and retain their parallel sweeps. Otherwise the two sides
run on separate threads with serial sweeps. This shared rule applies to all
supported fluid pairs and avoids concurrent launches into Numba workqueue;
outer property-refresh solves already run in side order. Thread counts and
numerical convergence gates remain independent of this scheduling decision.
Opt-in momentum SOU uses serial sweeps: its distance-two stencil reads cells
of the same red-black color, so the live-field parallel sweep is unsafe.
FOU retains the existing parallel threshold. Thermal SOU scheduling is separate.

The 2D loop keeps one live `_OuterState2D`. Its flow step rebuilds both SIMPLE
objects and joins both workers before propagating failures. It then prepares
thermal inputs, solves the selected energy route, validates the return,
refreshes properties, and checks convergence. Fatal-flow classification uses
the temperatures consumed by that iteration's SIMPLE calls. The post step
rebinds the four density/capacity fields; Richardson retains the inputs of the
last main thermal call even when that final post runs. Per-call thermal inputs
borrow arrays, while display smoothing stays separate from raw evidence.
Nonfinite thermal returns fail before property refresh or result capture.
The unreachable NaN-to-inlet replacement and its `energy_nan_hit` state and
new-result diagnostic are retired. Existing saved diagnostic dictionaries
remain readable without rewriting their historical values. True-h duty comes
from recorded face mass/enthalpy fluxes; the old scalar-pressure h(T) option
is retained only as an independent test reference.

Thermal routes are selected by their present qualification conditions:

| Route | Shared implementation and retained differences |
|---|---|
| True enthalpy | Pairs containing sCO2 use signed mass/enthalpy transport; the 2D adapter calls the shared 3D enthalpy kernel. Existing zone/route constraints remain. |
| Model enthalpy | Existing air/water h(T) transport; 2D includes water/water when unzoned and symmetric. 3D currently includes air/air, air/water and water/air with its Nz, variable-property, dual-flow, conservative and mask conditions. |
| Temperature | Existing remaining cases and approximation modes keep their current discretization and property sampling. |

The true-enthalpy fluid diffusion term is Fourier conduction on temperature,
linearized consistently in the enthalpy unknown on each shared internal face.
A pressure-dependent enthalpy difference is not itself a temperature gradient.
Both production adapters require fresh HEOS fluid and solid equation residuals:
the largest per-phase sum of absolute cell residuals, together with the boundary
energy imbalance, must be <=0.001 of `max(abs(Q_A), abs(Q_B), 1)` in native units.
The enthalpy-update criterion remains independent. A final chunk containing
clipped enthalpy updates cannot certify convergence. The true-h ledger records
the effective settings, residual budgets, clip counts and exit reason.

Model-h uses signed mass faces and minmod SOU on **both** fluid sides in both
dimensions. Its fluid Picard update uses the shared `MODEL_H_RELAXATION=0.2`
policy, including outlet cells; 3D retains explicitly smaller relaxation values.
The earlier 2D B-side first-order default and 3D fluid-name relaxation choice
do not apply to this route. Damping changes the iteration, not its steady
energy equation. Q/field convergence, physical boundary energy, solid energy
and mass checks remain separate and retain their thresholds. The turning-flow
regression covers serial/red-black execution and physical A/B label invariance.
The 3D model-h inner `converged` flag checks duty and temperature changes;
its recorded equation/solid/boundary budgets are additional diagnostics, not
the true-h route's independent 0.001 equation gate. The conservation tests
check their declared budgets separately. Do not infer identical acceptance
criteria from the shared word `converged` across thermal routes.
Model-h Richardson refinement has a 12000-sweep ceiling so the finer grid can
meet those same criteria; temperature-form refinement retains 5000. See the
[air/water convergence and validation record](history/README.md#2026-09-18-历史材料整理).

Changing a shared convergence rule affects both dimensions. Changing a
dimensional momentum or heat kernel affects every fluid using that route.
Changing an EOS or Nu correlation belongs in the fluid/model owner, not in
another per-fluid solver. Cross-route method changes require separate numerical
qualification. See the [implementation and validation record](history/README.md#2026-09-18-历史材料整理).

### Persistent interfaces and physical state

CaseData contains the actual prepared grid, design fields, boundary inputs,
fixed thermal/flow geometry, model versions and resolved settings. A config
snapshot is provenance, not instructions for rebuilding the case in a receiver.
Runtime controls (progress/cancellation callbacks) are separate and never
serialized. Unknown modes/resources and incomplete prepared inputs fail.

FieldResult contains native field locations/units, original flux and pressure
evidence, execution/convergence status and diagnostic metadata. Display
pressure/temperature fields do not replace the raw numerical state. NaN in
diagnostic arrays and unconverged completed runs remain visible; strict JSON
metrics report unavailable values with reasons. Cancelled/failed execution
does not return a fabricated completed archive.

Each full-compute backend explicitly produces its display/flow fields and
final diagnostics, passing diagnostics directly to native result capture.
Capture does not infer diagnostic ownership from value types. The retained
3D dictionary entry still returns the flattened compatibility mapping, including
optional audit exports and absent-field placeholders. Final report diagnostics
remain separate from the detached last-thermal snapshot; reporting references
do not replace formal reductions from native evidence.

Full 2D heat duty is W/m with no fabricated thickness or z-wall loss. Full 3D
is W before any application normalization. The optimizer divides 3D duty/mass
by actual Lz once at its boundary. Quick design is a prescribed-flow LTNE
model with prepared analytical inlet-pressure fractions, not a SIMPLE solve.
Its offline metrics need no EOS or calibration call. Screening retains its
own frozen-B/nonconvergence and unsupported-metric limits.

Full-compute thermal metrics use definition `native_boundary_v1`: `Q` is
the absolute A-side main-grid boundary heat loss, and `Q_A`/`Q_B` retain
signed heat loss (positive when a stream releases heat). Energy imbalance
uses these same native side duties. Outlet temperature uses the raw main
thermal temperature weighted by positive outward signed thermal mass flux;
mass flow reports total inward thermal boundary mass. 2D Richardson duties
are separately named `Q_richardson_A/B` and never replace main-grid `Q`.
Their extra solve and physical/convergence checks remain in force.
Full-compute pressure drops use `pressure_face_v1`: extrapolate the final
SIMPLE pressure to physical inlet/outlet faces and weight by geometric open
area. Both dimensions share the same reduction. Air inlet-pressure correction
also uses these physical faces: the outlet-cell anchor is iterated until the
inlet open-area mean meets the specified absolute pressure within `1e-4`
relative error. Both dimensions share pressure initialization and a bounded
P-squared update in `solvers/_solve_common.py`. A positive 1D estimate above
the existing pressure floor is used as the initial outlet-cell anchor; an
unusable isothermal estimate starts at the specified inlet pressure. Downward
updates consume at most half the remaining squared-pressure distance to the
face/cell floor, then the coupled flow is recomputed. The original proposal,
accepted step and initial method are retained in each inlet state's `iterations`.
These numerical choices do not determine physical validity.
This inlet check joins the outer convergence gate. Correction is on
by default; explicit `p_in_shooting=False` / `TPMSHX_P_IN_SHOOT=0` remains a
diagnostic override and cannot certify a mismatched inlet as converged.
The 2D air property, thermal and report fields use that same SIMPLE absolute
state; they do not shift it again to pin the inlet cell row. Numerical and
experimental before/after evidence is in
[the pressure-boundary diagnosis](history/README.md#2026-09-18-历史材料整理).
Water and the current frozen-pressure sCO₂ route retain their property-pressure
convention. Postprocessing does not reconstruct thermal enthalpy at a new state.
Pressure drop retains the final SIMPLE pressure convention and its distinct
recorded state. Metric definitions survive JSON and GUI export metadata.
Old metrics files retain their definitions; re-evaluate their native result
before mapping it to the current GUI contract. Frozen backend reporting
references are historical numerical oracles, not the current metric contract.

`PartialBCConfig.uniform_inlet_2d` selects geometric overlap without the
historical four-cell inlet taper. Preparation records the selected profile,
and the 2D solver consumes and checks that same profile. The desktop fixes
this flag to true for both fluids and reports conversion of retired settings
when loading GUI files; it has no inlet-profile switch. The lower-level API
retains the historical profile for scripted configurations with the flag
false. Total mass flow and port geometry are unchanged by profile selection,
and the flag does not alter 3D flow.

Continuous screening uses `models.screening.build_field` for preparation,
preview and export. Saved decision vectors must be decoded with their original
bounds, control grid, symmetry and spline order. The current geometry window
is L=4..8 mm, t=0.3..0.6 mm; this does not extend any Nu correlation's evidence.
Screening accepts air/air with A:+x and B:-y only. Its GUI uses full-face ports;
explicit 2D API port intervals remain supported, while 3D screening rejects
partial ports. Pareto-to-Compute loading supplies only mean L/t as a uniform
seed, not a complete graded-design recomputation.

For 2D partial-port screening, preparation owns a shared physical mesh:
geometry sampling, flow, thermal transport and pressure-face averages use
the same cell widths, including the B-side coordinate reversal. GUI probes
locate cells from those widths; display velocity copies stay separate from
the raw transport fields.

Full-compute zoning also uses the prepared physical cell centres. In 2D, every
zoned mode projects its thermal L/t fields into flow rows using transverse
cell-width weights and the actual direction, including reversal. D-F is still
evaluated after averaging L/t. In 3D, discrete xy zones select cells by physical
coordinates, with their existing overwrite and smoothing rules; the B-side
uniform D-F closure is unchanged.

Quick sizing accepts a candidate only after every final case converges and
meets its duty/temperature and pressure limits with finite results. BO keeps
bounded penalty objectives for training, but excludes failed evaluations
from reported Pareto fronts and hypervolume. History rows retain their status
and failure reason; a completed screening run is not experimental validation.

Separate processes use case.yaml + case.h5, results.h5, VTK views and
metrics.json. Exact contracts and mode-specific restrictions are in
`schemas/three_module_v1/`. Minimal postprocessing has a distinct dependency
lock and actual import/runtime checks; the full environment is not evidence
of minimal installation. Parallel run warnings and control state are local
to each invocation, and arrays crossing contracts are detached and immutable.

### Cooperative cancellation

Pipelines and solvers share `domain.cancellation.CancelledError`, an
`InterruptedError` subclass re-exported by `controllers.compute_pipeline`.
Only explicit cancellation checkpoints raise it; unrelated exceptions remain
errors even when a cancellation request is pending. Both SIMPLE workers are
joined before propagation, with real failures taking precedence over cancellation.
The GUI adapter maps this exception to the orchestrator's cancelled terminal state.

2D polls each SIMPLE iteration and at the existing LTNE chunk boundaries,
including the Richardson refined solve. 3D retains its 25-iteration SIMPLE
polling interval and LTNE chunk boundaries. The shared true-enthalpy driver
polls each property/sweep iteration. A native linear solve, JIT compilation,
LTNE chunk (2D defaults to 500 sweeps), or enthalpy property/sweep iteration
must finish before its next checkpoint; there is no forced thread termination
or fixed wall-time cancellation guarantee. Cancelled runs do not publish results.

### UI structure

Desktop preferences and session/history files use platform user directories,
not the installed package. `controllers/user_storage.py` owns these paths.
It imports missing known session/input files without deleting their originals;
appearance settings are read only from the current user configuration directory.
`desktop.py` configures writable caches before loading the GUI and supplies the
installed entry point; standalone packaging is described in [desktop builds](desktop.md).

Existing sessions restore the complete input snapshot, including fluid types,
flow directions, grids and ports, without reapplying a preset. Shanghai defaults
apply to a new workspace without a saved session or an explicit reset/load.
Each workspace saves its own partition axis, tables and continuous-field control
points. Older sessions missing partition data clear and disable partitions, with
a notice if they had been enabled; another workspace's partitions are never
reused. Startup converts temperature inputs to K while preserving their physical
values.

Copy-as-Python and reproducible links use the same complete GUI preset capture
and restore path as saved inputs, including temperature units, partition rows,
continuous-field inputs and custom model parameters. The Python snippet expects
an existing `window`; it restores inputs without launching a solve. This preset
format is distinct from the public module's `ComputeConfig` input.

- `ui/builders_canvas.py` assembles the visible geometry, result, and
  optimization workbench. `build_canvas_area()` only coordinates its named
  same-file builders.
- `ui/mixins/tab_view.py` owns workbench availability and routing, including
  the 2D/3D result switch. Hidden widgets are not used as navigation state.
- `ui/panel_vis_3d.py` owns the PyVista presentation. Its constructor delegates
  toolbar, controls, viewport, state, and timer setup to focused methods while
  rendering behavior stays in the same widget class.

The result footer and history format the published scalar snapshot directly;
there are no hidden result labels, duplicate chip strip or percentage-delta calculation.
Changing draft inputs does not replace the accepted run or its recorded units.
Only the latest published result owns the field cache, scalar summary and export.
Pareto image readiness belongs to its own canvas: copying/exporting that image
does not require a single-point field result. Saved-input menu loading and JSON
drag-and-drop share one decoder for current and supported old GUI files.
Failed or cancelled attempts retain that complete snapshot. A rendering failure
after publication retains the new numerical result and its provenance, while
unavailable views and stale plot/probe contents are invalidated.
Optimization budgets are dimension-specific: 2D uses `n_rho_loops`, while 3D
uses `max_outer_3d`. Inline controls show the effective
default until edited, then preserve explicit choices separately per dimension.
These are iteration budgets, not convergence certificates; the solver retains
its existing convergence and physical checks.

## Physical invariants

These constraints protect demonstrated solver behavior. Change them only as an
explicit numerical-model change with directly relevant validation.

1. **Compressible air.** Air uses the ideal-gas density path. Do not replace it
   with a constant-density or isothermal shortcut.
2. **Porosity is split once.** Symmetric LTNE callers pass the full porosity;
   the energy solver forms the two half-porosity streams. For an offset
   isosurface, `models/asym_split.py` computes the upstream `eps_A`/`eps_B`
   split, whose sides sum to the full porosity, and the kernel does not halve
   those values again.
3. **Mass-flux inlet.** Compressible air uses the mass-flux inlet in both 2D
   and 3D. Solver velocities are interstitial, not superficial.
4. **Darcy-Forchheimer ownership.** `df_surrogate.predict_K_cF()` remains the
   pure geometry baseline: one water+sCO2 CFD table for both sides and every
   fluid. Base K0 and cF0 depend only on topology, L, and t, are bilinearly
   interpolated inside 4–8 mm by 0.3–0.6 mm, and never depend on Re or fluid.
   The UI exposes exactly two production methods. **CFD smooth-wall** remains
   the generic `ComputeConfig` default and is V2-compatible. Built-in Shanghai
   presets default to **Experiment calibration**; saved inputs preserve their
   choice, and legacy saved inputs missing the selector retain smooth CFD.
   **Experiment calibration** applies one fixed,
   reviewed effective correction per side after pipeline assembly and before
   pressure seeding/SIMPLE; K/cF stay fixed for the solve. The selector routes
   to a dataset whose campaign, boundary, pressure-drop definition, and
   geometry match the run. It is not evidence of fluid-intrinsic D-F physics.
   Differences may absorb pressure-tap location, contractions/expansions,
   manifolds/distribution regions, whole-HX losses, flow-area/channel-count
   definitions, instrument zero, and data reduction; these contributions are
   not separately modelled. Without a same-rig comparison they must not be
   attributed to fluid. The superseded `gamma_df` and `rbf` research modes
   are retired; selecting them explicitly now raises an error. Their code,
   tables and results remain available through the [history index](history/legacy-models.md).
5. **Nusselt ownership.** Air, water, and sCO2 base correlations belong to
   `models/nu_correlations.py`. The sole current sCO2 effective-parameter
   resource is `configs/sco2_effective_nu.json`, loaded by
   `sco2_effective_nu_config()` as a validated `Sco2NuConfig`. The retained
   `alpha_D/alpha_G` fields are total Ceff, applied once to the current base
   before the existing final Nu floor; there is no additional beta layer or
   output-Q scaling. The generic `cfd_smooth` default and run-owned saved
   parameters are unchanged: explicit selection loads the current resource,
   while old Cases continue to replay their recorded parameters. The retired
   experimental-gamma helper and environment switch are not a second route.
   Calibration evidence and physical scope are in [model resources](model-resources.md#sco2-有效-nu-系数).
   Full 2D/3D solves rebuild each side's local
   scalar Re/Nu from `models/local_heat_transfer.local_speed`: the current
   cell-centered pore-velocity magnitude, sqrt(uc² + vc² [+ wc²]). Do not
   select a fixed inlet-axis component or apply porosity a second time.
   Signed normal components still own face mass/enthalpy fluxes. The existing
   Re/Nu floors apply to genuinely low speeds. Initial inlet-range observations
   remain, but redundant bulk h_v arrays are no longer stored before the first
   local refresh. Prescribed-velocity approximate modes retain their definitions.
   Using bulk-fitted scalar Nu locally in turning flow remains a modelling
   assumption, distinct from this velocity consistency requirement. See the
   [implementation and paired validation](history/README.md#2026-09-18-历史材料整理).
6. **Compressible envelope.** `models/envelope.py` checks the actual final
   pressure and local Mach fields. Nonfinite states, pressure at/below the
   existing 1000 Pa floor and Mach >= 1 remain invalid. Positive/subsonic
   fields must also meet the specified physical inlet pressure to converge.
   An unusable isothermal 1D initial estimate is a numerical startup issue,
   not a proof that the coupled non-isothermal problem has no solution.
   Do not bypass the final-field or inlet-pressure gates by widening a clip
   or forcing a numerical answer.
7. **Pressure reference.** On ideal-gas sides, `P_ref_abs` anchors the outlet
   cells, and local absolute pressure is `P_ref_abs + P`. The physical outlet
   face can have nonzero extrapolated gauge pressure; `P_ref_abs + dP` is not
   the realized inlet pressure. Use geometric area means at actual port faces
   for inlet-pressure correction and its convergence diagnostic.
8. **Units.** Prepared contract quantities use K, Pa and m. Legacy closure calls that
   accept cell size/wall thickness in mm receive an explicit boundary conversion;
   those internal units do not change persisted SI fields.
9. **Port boundary.** `ComputeConfig.validate()` normalizes both ports and
   calls the shared validator. 2D supports every ±x/±y direction; 3D also
   supports ±z, with both transverse extents validated against the correct
   domain axes. Non-opening exterior surfaces are stationary no-slip walls:
   tangential momentum has half-cell viscous wall flux, including z± in 3D;
   there is no volume wall penalty or post-solve velocity attenuation. 2D has
   no finite-thickness z term; Nz=1 3D momentum still has two z walls.
   Raw primary and staggered opening fractions come directly from the original
   rectangle on the final actual grid, never from averaged primary fractions.
   Positive raw overlap owns normal outlet flow and PPE support; taper remains
   a separate numerical profile. The inlet mass normalization and local outlet
   mass closure remain in force. Coarse bootstrap rebuilds the original ports,
   transfers inlet mass by physical open-area intersection, and reapplies the
   fine outlet support after prolongation; its budget and initial-guess role
   are unchanged. Richardson does not add a fine SIMPLE solve.
10. **True-enthalpy ownership.** Any ordered fluid pair containing sCO2 uses
    the conservative enthalpy kernel. It consumes SIMPLE's signed staggered
    face mass flows and computes duty from boundary enthalpy fluxes; it must
    not reconstruct a full-face x-flow from a scalar mass rate.
    The shared kernel requires both face-flow tuples explicitly. Uniform-flow
    construction for numerical reference tests lives only in the test helpers.
    Every sCO2 side in 2D/3D uses the shared property-wrapper range
    **280–700 K, 7.9–16 MPa absolute**, at inlets and actual local states.
    The 2026-09-09 pressure-floor extension leaves the EOS backend and the
    independent Nu/D-F applicability and acceptance gates unchanged; it does
    not establish experimental accuracy in the added range.
    Production Picard iterations use CoolProp BICUBIC only for CO2 T(h,P).
    Final temperatures, coupled-energy checks, outlet inversion and all other
    properties remain HEOS. If an exact-EOS energy check fails, the remaining
    iterations finish on HEOS; returning to the table can cycle between two
    different fixed points. Each thermal solve owns its mutable table state;
    HEOS enthalpy limits at local pressure keep domain-boundary checks on HEOS.
    Results record `sco2_enthalpy_eos` in model metadata when the table is used,
    including the `bicubic_iteration_heos_polish_v2` algorithm and whether
    exact-EOS finishing was needed.
    This is an approximate iteration algorithm, not an experimental calibration.
    The separate experimental `TPMSHX_SCO2_COMPRESSIBLE` switch enables
    local-pressure density/viscosity updates only on the 3D A side and changes
    that side's pressure initialization/envelope handling. B-side sCO2 flow
    properties retain the inlet-pressure convention. This switch does not
    implement a full compressible continuity equation or qualify a symmetric
    two-sided compressible model; it is off by default. Its A-side flow-property
    pressure uses `P_ref_abs + P`, while true-h uses `P_in - dP_face + P`;
    these anchors are not guaranteed equal. The ideal-gas inlet-pressure
    correction does not certify this sCO2 research branch. Compare actual
    inlet pressure and both anchors alongside mass/energy budgets before
    interpreting an ON/OFF difference as improved accuracy.
11. **Current TM1 limit.** sCO2 zones and offset level sets remain rejected;
    air/water-only runs retain the qualified model-enthalpy and temperature
    routes listed above. For Nz>1, their end-cell treatment covers every
    physical fluid and solid end control volume. Tin is imposed at the open
    inlet face with half-cell conduction;
    outlet zero-gradient applies at the external face. Explicit CC callers
    with SIMPLE supply actual inlet capacity transport while retaining the CC
    interior scheme. Prescribed B remains an external thermal reservoir.
12. **Experiment-correction applicability.** The air core-specimen branch uses
    L=6..8 mm, t=0.3..0.5 mm interpolation; t=0.6 uses the separate HX campaign.
    sCO2 uses only D/G-7-6 hot-side `ok_dp` evidence, keeps K=K0, and is
    HX-effective: uniform symmetric core, no zones, delta, other L/t, or
    independent cold-side fit. Its measured inlet-velocity windows are
    0.5827..2.5396 m/s (Diamond) and 0.6120..2.4705 m/s (Gyroid), corrected
    at absolute pressure for the same hot-side `ok_dp` members, measured mass
    flows and experimental flow areas. sF remains frozen at 6.313005350332494
    (Diamond) and 7.608907691857889 (Gyroid). The fitted
    D-F parameters are a porous-region
    closure and may be used with valid custom port centres, widths, and every
    solver-supported flow direction; only the full-face x-direction calibration
    boundary has direct experimental evidence. The
    water+air D/G-7-6 experiment consists of two complete, disconnected TPMS
    networks with
    delta=0. Shanghai's April 1 air path is straight/full-face while water
    uses staggered local openings; April 7 exchanges the fluid networks.
    Water and air use the same
    topology-derived single-side flow area (D 5.94e-4 / G 6.50e-4 m²), with no
    28/34 channel-count scale or geometric-face shortcut. After excluding
    G/water case 1 (`dp_nonphysical`) and D/water cases 10/11
    (`duplicate_row`), the production water fit uses the declared high-flow
    window `u>=0.10 m/s`; this original calibration membership is unchanged. Fixed-K0 water RMSRE is 6.84% D / 0.93% G with sF 4.8928 / 4.1989.
    The measured upper bounds are 0.2541 / 0.2232 m/s. Matching HX-air uses its
    own sF: Diamond 1.8024228153853061 retains its original campaign;
    Gyroid 2.649010286988306 uses April 1 straight-air cases 2–16,
    fixed CFD K0, experimental endpoint mean temperature and the original
    1D compressible pressure-drop relative-error fit. April 7 is used for
    connection-transfer evaluation, not fitting this coefficient. Full 2D/3D
    results do not tune another multiplier. Source, columns, row membership,
    velocity conventions and measured errors are recorded in the
    [straight-air calibration source and scope](model-resources.md).
    `ComputeConfig`
    selects each side independently, allowing all nine ordered air/water/sCO2
    pairs and every valid 2D/3D flow direction. A mixed pair may therefore combine
    corrections from different campaigns; that is a model composition, not joint
    experimental validation of the pair. Each HX-effective side still requires its
    own velocity window, the matching 0.182 x 0.042 x 0.042 m domain, and delta=0.
    Custom inlet/outlet positions and sizes remain supported. Every active side
    must match its own applicability rules; there is no silent fallback.
    `hx_velocity_bounds()` retains active calibration/source-audit windows.
    `hx_application_velocity_bounds()` separately supplies the approved
    production windows (Diamond/Gyroid, m/s): water 0.0139648..0.254055 /
    0.0162341..0.225876; air 3.88324..22.7599 / 3.91282..24.5467; sCO2
    0.434925..2.53961 / 0.381408..2.47046. Full precision is in the selector.
    These windows cover reviewed 7/0.6 mm full-HX measured combinations and
    approved port validation, not arbitrary T/P/mdot combinations. Both ranges,
    actual inlet u and approved purpose are retained in correction metadata.
    Gyroid air records campaign `shanghai-air-straight-20260401-v1` and a
    `calibration` object with source workbook, sheet, rows, columns, method
    and accuracy scope. Its source-convention calibration span is
    8.026110584256458..22.441995588974073 m/s; the same members in production
    inlet-density units span 8.027855328062564..22.446874107951544 m/s.
    The latter is saved as `calibration_runtime_velocity_window_mps` and
    used for the warning and `extrapolated` flag, avoiding a false warning
    at the source upper endpoint. Other campaign warning bounds are unchanged.
    Leaving the calibration window emits a run-local side-specific warning
    through the existing cache/UI/export path. Water's lower-speed extension
    is substantial approved extrapolation; water coefficients are unchanged.
    Gyroid air retains the approved low-flow application window and computes
    those cases with extrapolation notices. Full 16-case statistics retain
    case 1, separately from the accepted 15-case comparison. Air-water
    pressure-error evidence does not qualify air-air or air-sCO2 accuracy.
    Each side applies its frozen sF exactly once before pressure seeding and
    SIMPLE, with K unchanged. Explicit CFD mode and independent Nu selection
    retain their defaults. D-F permission does not relax water-state, sCO2
    property-domain, nonfinite, numerical or energy guards.

## Extension points

- Add a fluid through `models/fluid_props.py`; keep its Nu implementation in
  `models/nu_correlations.py` and record its versioned resource and use it through the public module APIs.
- Add a user-facing configuration field to the `domain/compute_config.py`
  dataclasses first, then adapt it once at the UI boundary.
- Add a solver behavior behind an existing configuration boundary only when a
  current use case requires it. Do not introduce a factory or interface for a
  single implementation.
- Keep one production path per dimension. Validation code must call that path
  unless it is explicitly testing a lower-level kernel.

## Local data

Raw data is intentionally outside Git and is resolved relative to the
repository:

```text
data/raw_data/
├── experiments/{air,water_air,sco2}/
├── cfd/
│   ├── water/
│   └── sco2/{Diamond,Gyroid}/
├── archive/{co2,water_air,sco2}/
└── plans/water/
```

Do not rename dataset directories without first updating the loader that names
that exact path. Generated reports must not become a second source of truth for
raw measurements.
The [data catalog](data-catalog.md) maps original filenames to this layout.
Workbook names also select the explicitly confirmed water pressure convention;
renaming them requires updating that registry and its caller tests together.

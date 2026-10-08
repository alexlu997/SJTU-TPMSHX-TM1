# SJTU-TPMSHX-TM1 architecture

[中文](architecture.zh-CN.md) | [English](architecture.md)

The integrated native full-compute CC candidate uses the existing
air/water integral h(T) model through the strict model-h drivers. This replaces
the earlier variable-cp m*cp*T adapter. That candidate's failures stay in the
historical record. Earlier numerical and resource qualifications stay tied
to their recorded builds. The final shared-row compilation policy requires
affected numerical/resource checks and application acceptance. Fixed-coefficient
Quick Design/standalone temperature, the kept
true-h CC warm-up and single-A sCO2 paths, and staggered research routes have
separate contracts.

Conservative staggered temperature transport uses the same end-cell SOU
reconstruction in Python and C++.
Internal faces next to a domain end use the two available one-sided slopes.
Minmod limits these slopes in physical distances.
External faces keep their prescribed boundary treatment. Axes with fewer
than three cells stay first order. Product model-h and the nonconservative
research stencil keep their separate reconstruction contracts.

Engineering backend parity requires one prepared case and independent convergence
and energy gates. Relative differences in duty, pressure drop and mass flow must
be at most 0.1%. Absolute differences in outlet and full-field temperatures must
be at most 0.01 K. `test_backend_engineering_parity.py` covers eight fluid pairings
in 2D and 3D. Complete iterative comparisons use these limits, with 0.01% relative
tolerance for intermediate fields and explicit absolute tolerances for
near-zero residual ratios.

Actual iteration and roundoff-clipping counts can
differ across backends. Each count must respect its own run's budget, records
and stopping reason. Shapes, states, sources and physical gates stay separate
assertions. A different extremum location must still identify an
extremum in the original observed field. Save/replay, independent formula and
assembly checks keep their tighter tolerances. These comparisons do not
qualify unsupported metrics or untested physical conditions.

SIMPLE momentum residuals near convergence are audited against each run's own
returned field after outlet closure and the original F2 gate. Their histories
keep the actual raw numerator, denominator and normalized residual. A capped
2D solve keeps its last pre-closure observation without a new certificate. Complete 2D SIMPLE mass-history comparisons use a dimensionless absolute floor
of 1e-8. This is 1% of the default 1e-6 F2 mass gate.

Final mass and F2 checks keep their original limits. Progress samples must equal that run's own recorded residuals.

A capped outer run stays nonconverged. Its returned thermal state is validated with its actual last inputs and original energy gates. It is not accepted as
a converged engineering-accuracy result.

Full-driver capture and component ABI tests use the current thermal component
to validate that algorithm's fields, iteration counts and residual records.
They do not require the kept Python thermal iterator to follow the same
trajectory. Public backend engineering tests still run both complete backends
independently. The fullCC capture compares its integral-h(T) boundary powers with the component ledger, separately from the kept Python cp*T report.

This is the current architectural and physical contract for the repository.
Historical audits and reports explain how the project reached this state, but
they do not override the running code or this document.

## Result qualification by route

Execution completion, solver convergence, metric availability and optimization
eligibility are distinct. `run_case` records the native convergence verdict.
`evaluate` reports if each metric has sufficient recorded evidence. An
available metric is not an experimental accuracy certificate.

| Route | Native convergence and final evidence | Additional consumer requirements |
| --- | --- | --- |
| 2D model-h | SIMPLE, outer coupling, main/fine thermal convergence and energy certificates, Richardson eligibility and pressure envelope | Multi-condition batches require both physical-boundary ledgers and the existing main/fine gates. Q is W/m and total-flow studies need an explicit depth |
| 3D model-h | Final SIMPLE checks, thermal/outer convergence, finite fields and pressure envelope. Source-free thermal passes also require the existing strict energy gates | Multi-condition batches independently check the archived `compute_phase2a` global/cell, source and boundary certificates, including results produced before energy finishing was added |
| 2D/3D true-h | Native enthalpy solve with final-state equation/boundary budgets and property checks. Returned thermal evidence is captured before any failed final post-update | Inspect the route's `true_h_balance` and convergence detail. This route is outside the air/water model-h optimizer contract |
| Native full-compute CC (G5 candidate) | Strict model-h on the accepted thermal mass faces. Actual integral h(T_face) advective powers, Fourier powers and phase residuals. Complete-boundary error ratio at most 1e-7 | Declared `model_enthalpy_temperature_v1` supports captured heat in W/m for 2D or W for physical 3D. The requested temperature route stays distinct from product model-h optimization eligibility |
| Other temperature and low-level research routes | Existing route-specific stopping rules, coefficient sampling and recorded state | Fixed-coefficient capacity transport, staggered/MAC research and kept single-A sCO2 do not inherit the fullCC integral-enthalpy qualification. Historical files keep their original reductions |
| Quick design | Explicit prescribed-flow approximate mode | Its metrics and feasibility checks do not certify a full SIMPLE solve |

GUI and CLI keep their native convergence meaning. Failed/cancelled GUI
attempts keep the previous accepted result. Batch optimization rejects a
failed member or energy gate and keeps its failure row. Saving and reopening
keeps evidence and status. It does not promote an unqualified result. The first water model-h thermal pass yields to the flow update after at most
one existing 250-sweep interval.

If that initial trial leaves the liquid-water
range, it retries from the unchanged valid input with a halved interval, within
the original thermal iteration budget. Nonfinite states, later phase violations,
and invalid final-pressure states still fail their original checks.

For 2D model-h, stable heat and temperature changes trigger the actual nonlinear
A/B/solid cell balances as well as the existing global energy checks. Each
fluid's maximum cell residual is normalized by its own integrated exchange
divided by the cell count, with a 1 W/m exchange floor. The solid uses the larger side exchange. All three ratios must be at most 1%. This average-cell
load scale is not a claim of invariance under arbitrary local mesh refinement.

Failed checks continue within the original budget. Outer field stability
cannot stop the loop while its last thermal pass stays unconverged. Both main and refined full-compute model-h passes use the existing Anderson
GS acceleration, including grids without extra port refinement. Trial sweeps
count against the same budget and must reduce the GS update residual. Final
acceptance still requires the independent actual-state equation certificate.

For source-free 3D model-h, stable heat and temperature changes trigger the
shared energy certificate. A failed residual or source-balance gate continues
thermal sweeps within the existing budget. Missing physical inflow data returns
an unconverged thermal pass for a flow update. More sweeps cannot repair its
fixed mass faces. An unconverged thermal pass cannot end the outer iteration as
converged. Final certificate data are reused without another numerical solve.

Manufactured-source tests keep their stopping rule because their external
sources do not obey the source-free LTNE exchange balance. See [capabilities](capabilities.en.md), [model applicability](model-resources.en.md)
and [data provenance](data-catalog.en.md) for the separate physical scope.

## Runtime flow

```text
applications -> preprocess.api -> CaseData -> solvers.api -> FieldResult
                                                          -> postprocess.api -> PerformanceResult
                         domain / models / versioned resources / file I/O
```

- `domain/` owns immutable CaseData, FieldResult, metric definitions and
  runtime control ports. It is Qt-free.
- `preprocess/` owns physical grid/boundary preparation, fixed geometry and
  coefficients, model/resource selection and portable execution inputs.
- `solvers/backends/python/` owns prepared numerical execution, current-state
  property evaluation and native result capture. SIMPLE/LTNE kernels stay
  under `solvers/`. It does not import preprocessing or formal postprocessing. Importing the public solver API does not initialize Numba. Its thread
  environment is applied one time when Python numerical kernels or explicit
  thread controls are loaded.

  Later runs keep the caller/worker mask. The 2D loop reads prepared properties directly, reports through `RunControl`,
  and returns application coefficients and zone statistics with its native
  result.

  It has no window-shaped runtime adapter or attribute-write hooks. The mixed Python-outer/C++-sweep route is retired. Python runs use the
  original Numba kernel. Saved explicit mixed-kernel requests fail before
  SIMPLE. Complete native execution is selected separately with `RunControl`.
- `solvers/backends/cpp/` exposes the independent prepared Quick Design and
  full 2D/3D drivers through an explicit `RunControl(backend='cpp', native_library=...)`. The host library path is not serialized in CaseData. Shared QD validation and
  result mapping belong to `solvers/backends/quick_design.py`. Numerical property
  passes, liquid-state guards and thermal iteration belong to the C++ driver. Its returned scalar pass evidence is expanded into the same fields and warning
  records for postprocessing.

  Full 2D/3D own SIMPLE, pressure references, outer
  property/thermal coupling and final certificates in C++. 2D also owns
  Richardson refinement.

  The binding packs prepared arrays and maps native
  evidence into the same `FieldResult`. It does not call Python numerical
  kernels. Full 2D ABI 2 keeps the original prepared Nu geometry ratio rather
  than reconstructing it after a unit conversion. Python stays the default.
  The required native CI suite passes on macOS arm64/Python 3.13 and Windows
  x64/Python 3.12 and 3.13. Visible desktop delivery and full performance
  qualification stay separate gates.
- The C++ fixed-flow `solve_enthalpy` also has explicit `temperature_fou`
  and `temperature_sou` candidates. Both solve conservative enthalpy transport
  with temperature as the nonlinear unknown, guarded HEOS PT state updates,
  Fourier conduction and LTNE exchange. `conservative_energy` owns the frozen
  finite-volume sweeps and direct enthalpy face reconstruction. The driver owns
  EOS refresh, stopping and actual-state certificates. These candidates require
  declared scalar inlets and adiabatic external boundaries. Their SOU outlet
  reconstruction differs from model-h.

  They require a maximum temperature
  update in K and both explicit energy gates. Ordinary invalid PT states fail
  without clipping. SOU recipe 2 proposes six-sample Anderson updates before ordinary PT evaluation. It accepts only actual-PT/audit merit improvement. A rejected proposal keeps
  the ordinary path.

  Only a complete
  ordinary block can converge or give the final budget certificate. The legacy H algorithm stays the default. Full C++ 2D/3D can explicitly select these candidates on their existing
  two-fluid true-h routes. The persisted `SolverConfig.enthalpy_algorithm`
  and `enthalpy_temperature_tol_K` select the algorithm and update gate.
  Incompatible routes fail before flow execution. Python numerical methods
  and production fluid applicability are unchanged.

Additive full2D v3/full3D v2 entry points reuse the previous result layouts
  and owner release functions. Read-only queries expose the executed algorithm,
  actual thermal conductivity and six outward boundary enthalpy-power planes. The same loaded binary's energy recipe query identifies FOU1/SOU2 from each
  actual returned algorithm. Bindings copy that version into main, outer and
  boundary evidence. Missing query capability fails before conservative flow
  execution.

Offline boundary readers keep both saved SOU1 and SOU2, while
  rejecting unsupported algorithm/version pairs. Result PODs and ABIs do not
  change with the recipe.

  Portable candidate results use `thermal_mode=conservative_energy`. Their
  heat is the negative sum of these captured planes, in W/m for 2D and W for
  3D. Offline readers validate this evidence without reconstructing SOU or
  calling an EOS. Thermal mass/temperature evidence stays separate from a
  subsequent final flow update, including iteration-limit returns.
- Native CC/QD, staggered temperature, model-h and conservative-energy
  consumers share finite-volume rows. They keep their physical models and caller-owned face preparation. Air/water full2D CC main/fine and full3D CC with Nz=1
  call strict `solve_model_h_2d`. Full3D CC with Nz>1 calls strict
  `solve_model_h_3d`. They use accepted thermal SIMPLE mass faces and the existing air/water integral h(T).

  They keep the prepared K and h_v. The 2D/Nz=1 adapter selects A-SOU/B-FOU.

  Nz>1 selects SOU on both sides. Additive `get_model_enthalpy_evidence_v1` queries capture that thermal state
  before later flow/property updates and owner release.

Portable
  `model_enthalpy_temperature_v1` records the h(T) coefficients, solved-phase
  flags, residuals, source/reservoir powers and outward advective/Fourier planes,
  with separate 2D main/fine identities. It does not use the previous capacity-ledger
  layout. Missing declarations for new fields are invalid. Historical files
  without a new ledger keep their original reductions. Physical 3D Nz=1
  divides mass by depth for the 2D solve and multiplies integrated powers by
  depth one time.

Temperature is not scaled. FullCC nonzero sources stay
  unsupported, and prescribed B is an external reservoir without a solved B
  certificate.

  QD/standalone CC keep fixed-coefficient capacity transport. Full3D true-h CC warm-up keeps the private G4 temperature kernel for Nz=1
  and for Nz>1 when conservative=false and force_cell_centered=true. Its two
  sweeps solve both sides before the selected enthalpy algorithm and its
  property/conservation gates. Single-A sCO2 uses the same private kernel with
  prescribed B and its original thermal budget. These kept rows and the
  staggered/MAC projection/capacity research contract do not acquire this
  fullCC qualification.

  See [native consumer contracts](cpp-migration.md#shared-finite-volume-temperature-consumers)
  for iteration, incomplete-boundary and build requirements.
- `postprocess/` reduces recorded fields, fluxes and pressure states. It never
  reruns a solver or reads a private runtime object to recover missing evidence.
  Full-compute evaluation reuses successful heat and mass reductions only within
  that call, lazily by side and by coarse/fine evidence. Each requested metric
  keeps its own missing/unsupported/invalid status handling.
- `models/` and `df_surrogate/` own shared pure closures and versioned resources.
  Explicit cleaning/calibration entry points live under `preprocess/offline/`.
- `io/` owns strict YAML/HDF5/JSON interchange. Its `cli_options` module maps
  shared host execution arguments into `RunControl` without adding host paths
  to saved cases/configuration or coupling CLI consumers to workflows.
  VTK export is a postprocessing
  view of recorded data, not a new numerical state.
- `configs/` owns packaged case configuration.
- `pipelines/` keeps explicit scripted stage entry points. Callers import
  shared models and numerical backends directly. There are no `sys.modules`
  aliases or import-time function injection into the numerical backend. The kept dictionary-based 3D entry is `run_stack_3d._run_3d_stack`. Research and conservation tools still use it for single-fluid and manufactured
  source cases outside `ComputeConfig`. It shares the prepared numerical backend
  rather than carrying another solver.

  It is not a compatibility alias to remove
  before those physical cases have an equivalent public contract. It and `_build_3d_problem` accept keyword-only `control=RunControl(...)`,
  forwarded to initial SIMPLE and outer coupling. Runtime callbacks do not
  belong in `cfg`: `_cancel_check`, `_progress_cb` and `_iter_cb` are rejected
  with a migration error. Use `RunControl.cancel_check`, `.progress` and
  `.outer_iteration(current, total)` respectively. `.iteration(message)` is
  the separate text callback. Existing calls without controls stay valid.

  Former `stages_2d`, `stages_3d` and `_stage_common` import facades are retired.
  Preparation and shared helpers are imported from their owning modules. The former `solvers.envelope` and `solvers.roughness` facades are also retired. Grid and projection helpers come from `models.grid` and `models.df_projection`.
  Formal pressure reductions use the recorded physical port faces in postprocessing.
- `controllers/compute_pipeline.py` sequences the public modules. The module
  adapter maps their results to the historical GUI ComputeResult contract.
  It is the sole production result mapper. The previous 2D/3D mappings stay only
  as frozen test oracles for the real native-result integration comparison.
- `ui/` owns PySide6 and PyVista presentation only. Both dimensions use `ComputeResult` in the result cache. The 2D publication
  snapshots scalars, metadata, warnings and exported status while sharing field
  arrays. 3D keeps the published object. A failed or cancelled attempt keeps
  the last accepted result for display and export, independently of current inputs. Its canvas workbench reuses the existing parameter widgets in a left-hand
  geometry/boundary/solver inspector.

  Field phase and 3D z-slice selections
  read the accepted result snapshot. Draft edits do not replace that source. Figure exports follow the selected view. CSV exports keep the summary. 3D NPZ exports keep available full physical-XYZ display fields. These include
  temperatures (K) and both sides' velocity components and magnitudes (m/s).

They also include display pressures `P_fA/P_fB` (Pa), `L_mm/t_mm` (mm),
  and `dx/dy/dz` widths (m). Legacy `vmag/P_kPa` keys stay aliases for A-side magnitude and pressure in
  kPa. The display pressure reference is unchanged. Full native thermal states
  and flux evidence belong to `results.h5`. `ui/typography.py` uses native sans-serif fonts for Qt and
  keeps publication fonts for Matplotlib/VTK, without bundling font files or
  importing Qt into lower layers.

Ordinary GUI computations capture the
  launch thread's Numba mask and apply/restore it in the reused Qt worker. Optimization keeps its independent process/thread resource policy.

  Desktop inputs use uniform velocity over each inlet opening, local-density
  thermal transport enabled, and no additional six-wall refinement. Port/wall
  refinement is selected through the mesh scheme. Loading a GUI preset or
  session with different retired settings reports the conversion and saves
  the current explicit settings. Scripted solver configuration stays separate.
- `validation/` and `runs/` are executable research and verification tools,
  not alternative production implementations.

The experimental-Q runner (`validation.cases.validate_sco2_exp_q`) freezes
all selected topology/case/dimension members before the first solve. Its CLI
writes `partial.csv` and `state.json` after each member using the existing
staged sibling-file publisher. Failed, cancelled and numerically unqualified
members stay recorded. Execution completion is separate from Q acceptance.
The state keeps prior attempts and their exact CSV records so a mismatched
or incomplete pair cannot silently supply resumed results. The publisher's
single-writer and Python-exception recovery limits still apply.

`--out-dir` requires a new/empty directory. The default is a new directory
under `.cache/validation`. `--csv` stays the optional final summary export. To continue, repeat the original selection and `--csv` arguments and replace `--out-dir`
with `--resume-run` pointing at the prior directory. Resume requires the same
clean identified code, actual Python/dependency versions, model environment,
settings, full member list and exact selected reference-data snapshot.

An
unverified external data revision stays labelled unverified. The stored input
snapshot shows only equality of the inputs actually used.

Only completed
numerically/reference-qualified members are skipped. All other members rerun,
and the final Q verdict uses the original denominator and thresholds. A
programmatic `run()` without `checkpoint_dir` keeps its in-memory interface
and does not create files. Cancellation keeps evidence and returns CLI status 130.

The GUI entry point is `python -m sjtu_tpmshx.main`. Source-based headless
work uses `python -m sjtu_tpmshx.cli`. Parameter optimization and design use
the same public contracts with their explicitly named approximation modes. The macOS project-folder launcher passes `backend=cpp`, the supplied library
under `native/lib/macos-arm64/`, and the project table directory to this same
GUI entry point. Python keeps UI, prepared-input assembly, optimization
orchestration and result processing.

The explicit native selection leaves
public defaults and research-only Python routes unchanged. Previous numerical
implementations stay until their individual replacement gates pass.

M-A review, CI and merged-main acceptance for the rectangular 2D/3D module
flow are kept in [fixed history](history/README.en.md). Current M-B extensions
and their unmet acceptance conditions are listed in [capabilities](capabilities.en.md).
Historical baseline failures keep their original status.

Production domain shapes are currently limited to **Rectangle**, in 2D and 3D. The desktop displays a fixed rectangle/cuboid label, with no polygon controls. Saved polygon presets are rejected before modifying inputs or results. Polygon
startup sessions are not restored, with an explicit notice. Saved rectangular
files stay supported and write shape index 0 explicitly. The historical
`ui/polygon_calc.py`, polygon kernels and triangular meshing are retired.

Original code
is linked in the [history index](history/retired-tools.md). Reopening polygon compute requires the mainline physical rules and real
CaseData/FieldResult/PerformanceResult handoff, not just relocating the GUI code.

The 2D momentum solver uses SIMPLE. The experimental SIMPLER branch is retired.
Its original benchmark and negative result stay in the history index.

The B-side partial-opening experiments (M4 area scaling, per-cell participation
mask, temperature freezing and H2 outlet conductivity suppression) are retired. Explicit retired settings are rejected before execution, including in research
dictionaries and directly prepared inputs. Real port locations, dimensions,
directions and physical mass/energy checks stay active. The default model
applies no extra B-side participation correction. The independent
`TPMSHX_SCO2_COMPRESSIBLE` A-side pressure/property experiment stays separate.
It is not the GUI's local-density thermal-transport setting.

Historical experimental cases and their original results are indexed in
[retired tools](history/retired-tools.md). Rerunning their geometry under the
current model produces a new comparison, not a reproduction of that experiment.

Historical water-Nu comparisons and the previous full-face 2D enthalpy reference now
live in `tests/water_nu_reference.py` and `tests/enthalpy_2d_reference.py`.
Production keeps the direct water CFD closure and shared 3D enthalpy adapter.
The unused `postprocess.report` and `postprocess.visualization` helpers are
retired. Public evaluation, recorded-field plots and exports stay supported.

### Shared solver implementation

All supported fluids use `SIMPLESolver` in 2D and `SIMPLESolver3D` in 3D. `solvers/_solve_common.py` owns F2 configuration and the common convergence
monitor: momentum, fresh-density local/global mass and outlet backflow must
pass consecutive checks. Full compute and raw solver calls
use this same criterion. `convergence_mode=None` resolves to `f2`. Explicit
`legacy` is rejected. A static field triggers a check and never certifies
convergence alone.

The mass-only/velocity exit and its inner SIMPLE Anderson
implementation are retired. Thermal and outer-coupling Anderson stay active.

The 3D return path closes outlet fluxes again after the last density update and
remeasures all four gates on that returned state. Its local mass check includes
the pressure-pinned outlet cells. If a provisional `tol` fails this certificate,
the solver discards its passing streak and continues within the original budget.
The next ordinary iteration measures the velocity change including outlet closure
before applying the existing stall rule. A rejected final-step certificate is
`post_closure`. Stalled or exhausted solves stay failures.

Momentum faces use the continuity equation's signed mass fluxes integrated over
the staggered control-volume faces. Viscous transverse faces sum the two
half-cell strips, each using its own series resistance. The existing division
by control-volume porosity and D-F drag convention stay. A mass-deficit
iteration adds the same deferred diagonal term to both sides of the predictor
equation. It cancels at the fixed point and is excluded from the physical F2
residual.

Pressure correction uses the actual predictor diagonal. For active SOU limiters, the predictor also bounds their negative local source derivative. It uses a monotone stencil, fixed face mass fluxes and physical grid distances. This is not a bound on the full nonlinear Jacobian. The term prevents
two-sweep oscillation on stretched grids. It likewise cancels at the fixed
point without changing the requested relaxation or F2 tolerances.

`tol_simple`, SIMPLE's `solve(tol=...)` argument and `TPMSHX_SIMPLE_TOL` are
retired: they did not set F2 tolerances. Previous configuration-file import discards
`solver.tol_simple` and `optimizer.tol_simple` with an explicit notice. New
configurations omit them. Use `mom_tol`, `mass_local_tol` and `mass_global_tol`
for the independent F2 gates. The pressure-subproblem residual history keeps
its definition because adaptive AMG consumes it. Runtime/accuracy comparisons
between runs must compare actual inputs, approximation
modes, grids, iteration budgets and F2 settings.

Coarse bootstrap supplies a bounded initial guess, not a convergence certificate. Formal full 3D execution keeps bootstrap disabled by default. An explicit
enable uses the configured first coarse-level cap. Standalone `None` keeps
the existing cell-count selection (`_AMG_GATE`, currently 2000). Each constructed
coarse solver keeps its original automatic recursive selection and 200-step
child cap. These are per-level limits, not a shared 200-step bootstrap budget.

The half-grid minimum of four cells per axis, warm-start skip and fine pressure
boundary restoration are unchanged.

Both full backends save `diagnostics.coarse_bootstrap_trace` by side. It records
the effective policy, threshold, first/recursive caps, attempted coarse shapes,
depth and each layer's actual stop, charged iterations and seed application. `solve_started` means at least one iteration of that layer was entered.
`actual_levels` counts those layers and `started_cap_sum` sums only their caps. `total_charged_iterations` sums entered iterations, including a failing one. A skipped layer, or a parent cancelled while a child runs, can keep its
configured cap with zero charge.

These records never control or extend a solve. The historical bootstrap summary still describes the first coarse level. Previous result files stay readable. Rerunning an explicit legacy configuration
requires selecting F2 and accepting the independently measured result.

The staggered Python energy projection's `_LAPLACIAN_AMG_CACHE` belongs to the
Python backend process, keyed by grid shape. It keeps the graph operator and
AMG hierarchy rather than case fields or a case RHS. PyAMG can lazily construct its coarse
pseudoinverse on first use. Its formal consumers leave production
with the corresponding Python capability when that capability is retired. Kept research/MMS consumers keep an explicit process/reset lifecycle:
production does not call the reset hook, and research resets must wait until
active consumers finish.

Clearing the cache does not prove that the allocator
has returned pages to the OS. This ownership does not introduce an LRU policy
or rebuild the hierarchy for each case.

Both backends consume `models/fluid_props.FluidModel`. The registry imports
air/water primitives from `tpms_props` and Nu functions from `nu_correlations`
directly. `tpms_calc` keeps its public re-exports without a return dependency
from the registry. Correlations, property sources and validity checks stay in
their owning model modules. Shared outer
iteration and temperature-delta tracking live in `coupling_skeleton.py`.

Both
full-compute drivers track Ta, Tb and Ts, with the existing extra 2D density
gate. Dimension-specific solve order and native flux capture stay explicit.

The 2D SIMPLE constructor consumes prepared drag arrays for zoned geometry.
Its former `zone_config` row-prediction path is retired. Arguments following
`P_ref` are keyword-only, so previous positional zone arguments cannot be silently
reinterpreted. Residual callbacks propagate their original exceptions through
full compute. They are not best-effort UI notifications.

Full 2D and 3D preparation accept `zones.axis="continuous"` with a JSON `config`. This contains `x_decision` (L controls followed by t controls, in mm). It also contains `n_ctrl_x`, `n_ctrl_y`, `symmetric_y`, `spline_order`,
`L_bounds`, and `t_bounds`. The main geometry owns topology, material and domain dimensions. Two-dimensional controls describe L(x,y)/t(x,y).

Adding `n_ctrl_z` describes
true L(x,y,z)/t(x,y,z) controls. They are rejected by the 2D backend. The
spline is sampled at final physical cell centres, including nonuniform grids,
without quantization or the discrete zone mode's Gaussian filter. Historical
XY controls in 3D still mean extrusion along z. CaseData keeps
both the original controls and SI fields.

Execution consumes those fields. Both fluid sides keep complete local K/cF arrays in their own SIMPLE
coordinates.

This also applies to existing 3D grid zones: side A no longer
averages transverse drag and side B no longer replaces it with uniform drag. Recomputing an previous nonuniform grid-zone case can therefore change its results. Saved historical results are not rewritten. The 3D constructor also accepts row arrays and broadcasts them
along its first axis. Its existing momentum sampling stays: adjacent-x
averages at u faces, downstream-cell samples at v/w faces.

Geometry gradients
still require independent physical validation. Parameter smoothness does not
show TPMS surface connectivity or manufacturability.

Continuous fields
require symmetric channels. For Shanghai Gyroid air-A/water-B,
`df_mode="experimental"` also supports continuous fields with the original
7/0.6 mm reference geometry and campaign domain. It transfers the frozen
uniform-HX factors to each cell's local CFD K/cF, using the same factors for
baseline and candidate. Result metadata marks this as
`continuous-field-extrapolation`, for exploratory trend prediction. No gradient
accuracy is implied. This explicitly enabled transfer also permits inlet velocity outside the previous
uniform-HX window when porosity changes at fixed mass flow.

The original window
and extrapolation status stay in metadata. Uniform calibration requests keep their velocity limits. Other spatial
calibration restrictions and the sCO2 spatial restriction stay.

`preprocess.api.prepare_fixed_mass_flow_case` owns fixed-flow preparation.
The existing `optimization.multi_condition` imports remain available. For each
inlet, preparation integrates local single-channel porosity times the actual
normalized inlet velocity profile over the opening. It multiplies this integral
by inlet density, then divides prescribed total mass flow by that product to set
inlet velocity. In 3D, it builds geometry, the grid, ports and inlet properties
once. It validates the resolved speeds, then completes range observations,
D-F application and the Case snapshot from that same prepared data. Ordinary
and fixed-flow preparation share these final steps. The 2D path keeps its
existing geometry and final preparation stages. The 2D taper normalization uses geometric open area independently
of the spatial porosity field, exactly as the SIMPLE boundary does.

Its snapshot records the
candidate's correct velocity. A 2D study must supply its physical depth for
total-mass-flow conversion. Native results keep their per-unit-depth units. `preprocess.api.prepare_inlet_mass_capacities` reuses the native geometry,
mesh and port construction without evaluating speed-dependent closures. Its
static-input validation does not qualify an executable case: the resolved
speeds must pass full configuration and case preparation checks. Ordinary
preparation keeps those same full checks.

Imported-flow optimization records
the actual uniform-reference Case configuration for replay, and each candidate
resolves its own inlet speeds again using its local porosity field. `aggregate_multi_condition` compares useful water
uptake (`-Q_B`) and both relative pressure drops with paired baseline conditions.
It requires complete converged results. Heat and pressure stay separate
objectives. Each condition has equal weight, with 50/50 pressure-side weights. These helpers do not qualify a closure or start an optimization run.

`evaluate_condition_batch` runs a fixed design's air-A/water-B conditions
serially into a new directory. Each member keeps its input, prepared Case,
native result and metrics as soon as that stage succeeds. `batch.json` keeps
all requested members, failure stages and reasons, unrun members after
cancellation, and the baseline metric values/definitions and source IDs. Cancellation propagates. Ordinary condition failures continue without fabricated
penalties. If saving a failure/cancellation checkpoint also fails, the original exception
propagates with the saving error attached as a note.

Existing files stay the
last successfully written evidence, not a completed final archive. A saving error without an active exception stays an error. The desktop exposes
these notes and does not present a stale running checkpoint as a cancelled result. Baseline comparison validates the uniform reference, paired conditions,
ports, model resources, D-F mode, frozen run overrides, resolved roughness,
prescribed total flows, grids and solver settings. The raw conditions must
share geometry and numerical settings.

The public batch API returns all in-memory FieldResults. The optimizer uses the
same batch implementation but keeps only validated metrics, identities, paths
and configuration snapshots. Each candidate loads one archived baseline result,
runs the same identity, input and energy checks, and releases it before solving.
Each completed or failed member leaves the active scope after its checkpoint is
saved. Full fields remain in the existing archives. Missing or invalid baseline
files fail at the comparison stage. This bounds retained completed fields to one
active condition, at the cost of one baseline file read per candidate condition.
Public and optimizer batches use the same objective calculation and weights.

Only a complete numerically accepted batch can publish the two objectives. In addition to native convergence, 3D reuses the existing full-control-volume
certificate from `postprocess.conservation.compute_phase2a`. Each fluid's
global/cellmax residual and the LTNE source imbalance must stay below 1%. The physical boundary ledger must be complete. Native 3D finishing and the
conservation audit use this same pure function, owned by `result_math` and
re-exported through the existing postprocessing entry.

The 2D branch requires the native main/fine
model-h balances, complete physical boundaries and Richardson acceptance. This is separate from experimental accuracy,
the formal convective `energy_imbalance_rel` metric and gradient applicability.
These stay evidence needed for physical predictions. They do not prevent
an explicitly labeled exploratory search using frozen reference corrections.

`optimization.multi_condition_optimizer.run_multi_condition_optimization`
compares qLogNEHVI, qLogNParEGO and Sobol using the same seeded initial
designs and evaluation budget. It fits only complete accepted batches, maximizes
`(heat_gain_percent, -pressure_ratio)` and stores the full decision vector,
field specification, conditions, failures and native batch paths. BO dependencies are optional. The optimizer validates them before physical evaluations. The desktop inherits the
current ComputeConfig, accepts a fixed-mass-flow condition table and restores
selected full fields without averaging. A finite-budget Pareto set is a model
trend result.

Final candidates need all-condition and grid verification with
objectives recomputed on those results. The nTop CSV API exports XY or XYZ
coordinates and full control provenance with round-trip float precision.

The 3D outer loop owns one live `_OuterState`, returned after iteration without
a second synchronized state copy. It first prepares local heat transfer and
transport inputs. It runs temperature/model-h or the true-h warm start and solve. It then detaches native thermal evidence, records diagnostics and does convergence checks. The nonconverged post step refreshes A flow, thermal properties, then B flow.
A and B keep their distinct temperature/property update order.

Model-h mass
faces are captured before temperature-face balancing. True-h separately
balances and projects its mass transport. Per-call transport inputs do not
become persistent iteration state. The native thermal snapshot stays detached
from the conductivity, capacity and final SIMPLE arrays updated by post.

Iteration labels, the 3D progress fraction and SIMPLE cap logs use the effective
per-run limits. The 3D default outer budget is 12 (3 for `fast_sweep`). Progress
marks iteration entry and is not elapsed-time progress or proof of convergence.
The application pipeline reserves separate progress intervals for preparation
and publication, then reports completion after the required stages return.

The 3D initial A/B SIMPLE dispatch uses one level of parallelism. If either
side reaches the existing parallel-sweep grid threshold, A and B run in order
on the caller thread and keep their parallel sweeps. Otherwise the two sides
run on separate threads with serial sweeps. This shared rule applies to all
supported fluid pairs and avoids concurrent launches into Numba workqueue.
Outer property-refresh solves already run in side order. Thread counts and
numerical convergence gates stay independent of this scheduling decision.

Opt-in momentum SOU uses serial sweeps: its distance-two stencil reads cells
of the same red-black color, so the live-field parallel sweep is unsafe. FOU keeps the existing parallel threshold. Thermal SOU scheduling is separate.

The 2D loop keeps one live `_OuterState2D`. Its flow step rebuilds both SIMPLE
objects and joins both workers before propagating failures. It then prepares
thermal inputs, solves the selected energy route, validates the return,
refreshes properties, and does convergence checks. Fatal-flow classification uses
the temperatures consumed by that iteration's SIMPLE calls. The post step
rebinds the four density/capacity fields. Richardson keeps the inputs of the
last main thermal call even when that final post runs.

Per-call thermal inputs
borrow arrays, while display smoothing stays separate from raw evidence. Nonfinite thermal returns fail before property refresh or result capture. The unreachable NaN-to-inlet replacement and its `energy_nan_hit` state and
new-result diagnostic are retired. Existing saved diagnostic dictionaries
stay readable without rewriting their historical values. True-h duty comes
from recorded face mass/enthalpy fluxes. The previous scalar-pressure h(T) option
is kept only as an independent test reference.

Thermal routes are selected by their present qualification conditions:

| Route | Shared implementation and kept differences |
|---|---|
| True enthalpy | Pairs containing sCO2 use signed mass/enthalpy transport. The 2D adapter calls the shared 3D enthalpy kernel. Full3D CC uses the kept G4 two-sweep warm-up before the selected enthalpy solve. Existing zone/route constraints stay. |
| Model enthalpy | Existing air/water h(T) transport. 2D includes water/water when unzoned and symmetric. 3D currently includes air/air, air/water and water/air with its Nz, variable-property, dual-flow, conservative and mask conditions. |
| Temperature | The native fullCC air/water candidate reuses strict integral-h(T) model-h drivers while keeping the requested temperature route. Python temperature, QD/standalone fixed-coefficient, staggered research and private single-A sCO2 routes keep their separately stated contracts. |

The sCO2 restriction applies to geometry combinations, not the other stream's fluid.
sCO2/water, sCO2/air and sCO2/sCO2 pairs can use the true-enthalpy route.
Either stream can be in A or B. Public configuration currently rejects enabled
zones and nonzero level-set offset when either stream is sCO2. Each stream
still has to satisfy its own property and correlation applicability checks.

Internal thermal face conductance uses the two actual centre-to-face
resistances in series, `G = area / (distance_left/K_left + distance_right/K_right)`.
SOU reconstruction limits gradients in physical coordinates and extrapolates
from the upwind centre to the shared face. On stretched grids, a half index
step is not a half physical cell width. The sweep and its energy ledger use
the same face definitions. An independently computed analytic flux stays
necessary to validate them.

The 2D GS and red-black thermal kernels prepare diffusion conductances,
volume-weighted fluid-solid exchange and the solid diagonal one time per chunk. These arrays stay local to that call. A subsequent chunk sees any changed
coefficients. Model-h capacities and deferred fluxes still refresh each sweep,
and the cell order stays A, solid, B. The model-h cell row is inlined into
the strict-math kernels.

Unused temperature-form SOU work is skipped only on
that route. Its own signed model-h SOU reconstruction stays active.

Temperature/model-h stopping compares two observed heat duties, including
zero duty. A scale of one native heat unit (W/m in 2D, W in 3D) bounds the
relative-change denominator near zero. The existing duty tolerance and
temperature-stability test are both required. Zero duty alone cannot certify
a drifting temperature field.

The true-enthalpy fluid diffusion term is Fourier conduction on temperature,
linearized consistently in the enthalpy unknown on each shared internal face. A pressure-dependent enthalpy difference is not itself a temperature gradient. Both production adapters require fresh HEOS fluid and solid equation residuals. The largest per-phase sum of absolute cell residuals must be <=0.001 of
`max(abs(Q_A), abs(Q_B), 1)` in native units. The boundary energy imbalance must
meet the same limit.

The enthalpy-update criterion stays independent. A final chunk containing
clipped enthalpy updates cannot certify convergence. The true-h ledger records
the effective settings, residual budgets, clip counts and exit reason.

The existing product model-h route uses signed mass faces and minmod SOU on
**both** fluid sides in both dimensions. Its fluid Picard update uses the shared `MODEL_H_RELAXATION=0.2`
policy, including outlet cells. 3D keeps explicitly smaller relaxation values. The earlier 2D B-side first-order default and 3D fluid-name relaxation choice
do not apply to this route. Damping changes the iteration, not its steady
energy equation. Q/field convergence, physical boundary energy, solid energy
and mass checks stay separate and keep their thresholds.

The turning-flow
regression covers serial/red-black execution and physical A/B label invariance. For source-free 3D model-h, duty and temperature stability trigger the shared
actual-state energy certificate. The inner pass is converged only when that certificate passes. Failed checks
continue within the original budget. Missing physical inflow data returns an
unconverged pass for a flow update.

Manufactured-source cases keep their separate stopping rule. The model-h
residual definitions and budgets differ from the true-h route's independent
0.001 equation gate. Do not infer identical acceptance criteria from the shared
word `converged` across thermal routes.

The strict fullCC adapter has a separate stopping and boundary contract within
the model-h drivers. Full2D main/fine and full3D Nz=1 use A-SOU/B-FOU. Full3D
Nz>1 uses SOU on both sides. The native identities are respectively
`model_h_tface_sou_fou_strict_v3` and `model_h_tface_sou_sou_strict_v3`. Faces transport the existing integral h(T_face), with physical-distance
reconstruction at inlet/outlet cells.

Strict inlet Fourier conduction uses
the resistance/moment reconstruction shared by the row and audit. The original
non-strict model-h boundary rule is unchanged.

Duty and field stability must also pass a fresh complete-boundary ledger. Its numerator is the larger of the phase sums of absolute cell residuals and
the coupled boundary/source imbalance. Its denominator is the interface exchange
scale, with a floor of one native power unit. This ratio must be at most 1e-7. Failure continues within the original budget. Unavailable inflow
does not certify convergence.

Prescribed B has reservoir power but no solved
B residual. This strict path supports its existing fullCC asymmetric and 3D
water/water consumers without extending the non-strict product model-h route
or granting optimizer eligibility.

Product model-h Richardson refinement has a 12000-sweep ceiling so the finer
grid can meet its criteria. The fullCC temperature-role refinement keeps its
5000-sweep budget with the strict h(T) driver. See the
[air/water convergence and validation record](history/README.en.md#2026-09-18-历史材料整理).

Changing a shared convergence rule affects both dimensions. Changing a
dimensional momentum or heat kernel affects each fluid using that route.
Changing an EOS or Nu correlation belongs in the fluid/model owner, not in
another per-fluid solver. Cross-route method changes require separate numerical
qualification. See the [implementation and validation record](history/README.en.md#2026-09-18-历史材料整理).

### Persistent interfaces and physical state

CaseData contains the actual prepared grid, design fields, boundary inputs,
fixed thermal/flow geometry, model versions and resolved settings. A config
snapshot is provenance, not instructions for rebuilding the case in a receiver.
Runtime controls (progress/cancellation callbacks) are separate and never
serialized. Unknown modes/resources and incomplete prepared inputs fail.
Full 2D/3D execution and file interchange use the same physical grid checks:
canonical XY/XYZ axis order, SI widths and consistent cell edges. Backend
domain lengths and flow-coordinate checks stay additional execution constraints.

FieldResult contains native field locations/units, original flux and pressure
evidence, execution/convergence status and diagnostic metadata. Display
pressure/temperature fields do not replace the raw numerical state. NaN in
diagnostic arrays and unconverged completed runs stay visible. Strict JSON
metrics report unavailable values with reasons. Cancelled/failed execution
does not return a fabricated completed archive.

Each full-compute backend explicitly produces its display/flow fields and
final diagnostics, passing diagnostics directly to native result capture.
Capture does not infer diagnostic ownership from value types. The kept
3D dictionary entry still returns the flattened compatibility mapping, including
optional audit exports and absent-field placeholders. Final report diagnostics
stay separate from the detached last-thermal snapshot. Reporting references
do not replace formal reductions from native evidence.

Full 2D heat duty is W/m with no fabricated thickness or z-wall loss. Full 3D
is W before any application normalization. Quick design is a prescribed-flow LTNE
model with prepared analytical inlet-pressure fractions, not a SIMPLE solve.
Its offline metrics need no EOS or calibration call.

Full-compute thermal metrics use definition `native_boundary_v1`. `Q` is
the absolute A-side main-grid boundary heat loss. `Q_A`/`Q_B` keep
signed heat loss (positive when a stream releases heat). Energy imbalance
uses these same native side duties. Outlet temperature uses the raw main
thermal temperature weighted by positive outward signed thermal mass flux.
Mass flow reports total inward thermal boundary mass.

2D Richardson duties
are separately named `Q_richardson_A/B` and never replace main-grid `Q`. Their extra solve and physical/convergence checks stay in force. Full-compute pressure drops use `pressure_face_v1`: extrapolate the final
SIMPLE pressure to physical inlet/outlet faces and weight by geometric open
area. Both dimensions share the same reduction. Air inlet-pressure correction also uses these physical faces.

The outlet-cell
anchor is iterated until the inlet open-area mean meets the specified absolute
pressure within `1e-4` relative error. Both dimensions share pressure initialization and a bounded
P-squared update in `solvers/_solve_common.py`. A positive 1D estimate above
the existing pressure floor is used as the initial outlet-cell anchor. An unusable isothermal estimate starts at the
specified inlet pressure. Downward
updates consume at most half the remaining squared-pressure distance to the
face/cell floor, then the coupled flow is recomputed.

The original proposal,
accepted step and initial method are kept in each inlet state's `iterations`. These numerical choices do not determine physical validity. This inlet check joins the outer convergence gate. Correction is on
by default. Explicit `p_in_shooting=False` / `TPMSHX_P_IN_SHOOT=0` stays a
diagnostic override and cannot certify a mismatched inlet as converged. The 2D/3D air property, thermal and report fields use that same SIMPLE absolute state.

They do not shift it again to pin the inlet cell row. Numerical and
experimental before/after evidence is in
[the pressure-boundary diagnosis](history/README.en.md#2026-09-18-历史材料整理). The incompressible routes freeze density within each SIMPLE solve. The 3D
water and default sCO₂ routes keep their inlet-pressure density/viscosity
convention. The existing 2D outer refresh uses the local absolute field. In both dimensions the incompressible absolute pressure
reference anchors the physical inlet faces' open-area-weighted arithmetic
mean to the specified inlet pressure.

Thermal EOS and phase checks consume their
iteration's absolute field. The detached last-thermal pressure is kept even if a
failed final outer post-step produces a different final flow pressure. Postprocessing does not reconstruct thermal enthalpy at a new state. Pressure drop keeps the final SIMPLE pressure convention and its distinct
recorded state. Metric definitions survive JSON and GUI export metadata.

Previous metrics files keep their definitions. Re-evaluate their native result
before mapping it to the current GUI contract. Frozen backend reporting
references are historical numerical oracles, not the current metric contract. `domain.metric_spec` owns explicit metric families, units and full-compute
definition versions. `PerformanceResult` requires each key to match its spec's
side-specific name or family.

JSON loading uses the same check. The GUI validates all consumed metric definitions and dimension-dependent heat units before
assigning values to its Pa/K/duty fields.

Multi-condition aggregation requires
current signed heat and pressure definitions rather than merely accepting two
identically mislabeled records. These boundaries reject incompatible meaning
without unit conversion or modification of historical files.

`PartialBCConfig.uniform_inlet_2d` selects geometric overlap without the
historical four-cell inlet taper. Preparation records the selected profile,
and the 2D solver consumes and validates that same profile. The desktop fixes
this flag to true for both fluids and reports conversion of retired settings
when loading GUI files. It has no inlet-profile switch. The lower-level API
keeps the historical profile for scripted configurations with the flag
false. Total mass flow and port geometry are unchanged by profile selection,
and the flag does not change 3D flow.

The previous air/air screening optimizer, preparation, frozen-B backend and metric
reducers are retired. The [history index](history/retired-tools.md) identifies
their original code and numerical references. Current multi-condition search
uses full preparation and execution. `models.continuous_field` keeps XY/XYZ
interpolation for this path, preview and nTop export. Saved decisions must be
decoded with their original bounds, control grid, symmetry and spline order.

The current geometry window is L=4..8 mm, t=0.3..0.6 mm. This does not extend
any Nu correlation's evidence or show explicit graded-surface connectivity.

Historical screening result files stay readable with their original units
and status, but current execution and metric evaluation reject their modes. New configurations omit `optimizer`. `ComputeConfig.to_dict()` and `to_json()`
keep this retired section only when it was explicitly given or loaded
from an existing archive. Case snapshots and optimization records use the same
serialization. Its values are archive-only. Current optimization solve budgets
use `ComputeConfig.solver`.

Candidate counts
are the optimizer's separate `n_init`, `n_iter` and `q_batch` arguments. Historical Pareto CSV geometry
export still requires its original configuration and keeps failure status.

Full-compute zoning also uses the prepared physical cell centres. In 2D, each
zoned mode projects its thermal L/t fields into flow rows using transverse
cell-width weights and the actual direction, including reversal. D-F is still
evaluated after averaging L/t. In 3D, discrete xy zones select cells by physical
coordinates, with their existing overwrite and smoothing rules. The B-side and
A-side momentum solvers both consume their local D-F arrays.

Quick sizing accepts a candidate only after each final case converges and
meets its duty/temperature and pressure limits with finite results. Length
search uses the returned heat duty for a Q requirement, including mean-property
passes. A temperature-drop requirement uses the outlet temperature. An explicit
`solve_Lx(target=...)` stays an outlet-temperature override in kelvin. The inlet-cp temperature estimate only ranks the preliminary governing case.

The independent final cold-start evaluation still determines feasibility. Final-case
records, GUI diagnostics and Excel also keep hot/cold duties and the existing
energy-imbalance metric with its availability and reason.

This diagnostic does
not participate in feasibility filtering. Unavailable values are not zero. Design property lookups apply the shared liquid-water state guard to the inlet,
representative mean-property state and external warm start. They also validate each returned water temperature cell after each const/mean thermal pass. All use the declared
inlet pressure: quick design has no solved local pressure field.

Invalid input
states fail immediately. An invalid trial field is an inadmissible sizing
sample, not an invented signed root residual.

A bounded cold search can recover
an interior liquid candidate when an endpoint leaves the supported water state. It accepts only cold, tight candidates with successful checks and reports search exhaustion
without claiming physical infeasibility or a global minimum between samples. Analytical pressure drop keeps its existing meaning. In both
const and mean modes, water Nu keeps Pr at 320 K / 0.2 MPa. The mean pass
updates the other water properties, Re and conductivity used in volumetric heat
transfer.

`metadata.properties.Pr` records the actual pass state, not Nu's
representative Pr. The separate sCO2 reference-Pr convention stays unchanged.

Separate processes use case.yaml + case.h5, results.h5, VTK views and
metrics.json. Exact contracts and mode-specific restrictions are in
`schemas/three_module_v1/`. Minimal postprocessing has a distinct dependency
lock and actual import/runtime checks. The full environment is not evidence
of minimal installation. Parallel run warnings and control state are local
to each invocation. Arrays crossing contracts are detached from mutable input
storage and immutable.

A metadata-only case or result update can reuse a complete,
contiguous immutable bytes buffer with a separate array header. Changing the new
array's shape or dtype cannot change the original. Sliced fields that would keep
a larger parent buffer are copied into compact storage.

The C++ full 3D binding detaches native evidence before it releases the native
owner. `full_3d_capture` maps that evidence to FieldResult. The application path
copies only arrays needed for this contract; opt-in flow audit arrays are copied
when requested. `NativeFull3DDriver.run_prepared` retains its complete, detached
return for direct callers. Both paths share native execution and owner release.
The three temperature/display pairs, two report/display pressure pairs and
true-h thermal mass-face aliases share immutable buffers with separate array
headers. Thermal pressure and final flow pressure remain separate states.
GUI consumers still receive their required writable copies.

### Cooperative cancellation

Full Python and C++ entry points do cancellation checks before they prepare execution inputs or load a native library. Host-selection validation still applies.
A valid pre-cancelled request raises `CancelledError`, including when the selected
absolute library path does not exist. An uncancelled missing-library request
keeps its original error.

Pipelines, solvers and the GUI orchestrator share `domain.cancellation.CancelledError`,
an `InterruptedError` subclass re-exported by `controllers.compute_pipeline`
and `ComputeOrchestrator.CancelledError`.
Only explicit cancellation checkpoints raise it. Unrelated exceptions stay
errors even when a cancellation request is pending. Both SIMPLE workers are
joined before propagation, with real failures taking precedence over cancellation.
The orchestrator handles this exception directly as its cancelled terminal state.
The GUI adapter only binds pipeline arguments and keeps the original exception.

2D polls each SIMPLE iteration and at the existing LTNE chunk boundaries,
including the Richardson refined solve. 3D keeps its 25-iteration SIMPLE
polling interval and LTNE chunk boundaries. The shared true-enthalpy driver
polls each property/sweep iteration. Each active operation must finish before its next checkpoint. These operations
include native linear solves, JIT compilation, LTNE chunks (2D defaults to 500
sweeps), and enthalpy property/sweep iterations.

There is no forced thread
termination or fixed wall-time cancellation guarantee. Cancelled runs do not publish results.

### UI structure

Desktop preferences and session/history files use platform user directories,
not the installed package. `controllers/user_storage.py` owns these paths. It imports missing known session/input files without deleting their originals. Appearance settings are read only from the current user configuration directory. Session, preset/configuration and workspace-marker saves use a unique temporary
file in the destination directory before atomic replacement.

Concurrent saves
are last-successful-replacement-wins. A failed write keeps the previous
complete target and cleans up only its own temporary file.

This does not merge
simultaneous edits or give a transaction across separate files. `desktop.py` configures writable caches before loading the GUI and supplies the
installed entry point. Standalone packaging is described in [desktop builds](desktop.en.md).

Existing sessions restore the complete input snapshot, including fluid types,
flow directions, grids and ports, without reapplying a preset. Shanghai defaults
apply to a new workspace without a saved session or an explicit reset/load. Each workspace saves its own partition axis, tables and continuous-field control
points. Older sessions missing partition data clear and disable partitions, with
a notice if they had been enabled. Another workspace's partitions are never
reused.

Startup converts temperature inputs to K. The conversion keeps their physical values.

Copy-as-Python and reproducible links use the same complete GUI preset capture
and restore path as saved inputs. This includes temperature units, partition rows,
continuous-field inputs and custom model parameters. The Python snippet expects
an existing `window`. It restores inputs without launching a solve. This preset
format is distinct from the public module's `ComputeConfig` input.

Unwrapped `line_edits` JSON and legacy flat configuration files are partial
imports: the common preset application path merges only supplied fields into
the captured current inputs. An explicit temperature-unit change converts omitted inlet temperatures. The conversion keeps their physical values. Omitted
model choices, controls and optimization conditions stay in the snapshot. Cross-field validation uses the merged input before changing widgets or cached
results. An incompatible field dimension or zone-table layout rejects the patch.

Versioned complete files, preset libraries and startup sessions keep their
full-restore/historical-default rules. Partial import does not redefine them.

- `ui/builders_canvas.py` assembles the visible geometry, result, and
  optimization workbench. `build_canvas_area()` only coordinates its named
  same-file builders.
- `ui/mixins/tab_view.py` owns workbench availability and routing, including
  the 2D/3D result switch. Hidden widgets are not used as navigation state.
- `ui/panel_vis_3d.py` owns the PyVista presentation. Its constructor delegates
  toolbar, controls, viewport, state, and timer setup to focused methods while
  rendering behavior stays in the same widget class.

The result footer and history format the published scalar snapshot directly.
There are no hidden result labels, duplicate chip strip or percentage-delta calculation. Changing draft inputs does not replace the accepted run or its recorded units. Only the latest published result owns the field cache, scalar summary and export. Pareto image readiness belongs to its own canvas: copying/exporting that image
does not require a single-point field result. Saved-input menu loading and JSON
drag-and-drop share one decoder for current and supported previous GUI files.

Failed or cancelled attempts keep that complete snapshot. A rendering failure
after publication keeps the new numerical result and its provenance, while
unavailable views and stale plot/probe contents are invalidated. The current multi-condition optimizer keeps each dimension's full
ComputeConfig solver settings. Its initial and subsequent design counts are
search budgets, not convergence certificates. The solver keeps its existing convergence and physical checks.

External CLI
studies with settings not represented by GUI controls cannot be silently
restored into a different GUI case. The handoff rejects that mismatch.

## Physical invariants

These constraints protect demonstrated solver behavior. Change them only as an
explicit numerical-model change with directly relevant validation.

1. **Compressible air.** Air uses the ideal-gas density path. Do not replace it
   with a constant-density or isothermal shortcut.
2. **Porosity is split one time.** Symmetric LTNE callers pass the full porosity.
   The energy solver forms the two half-porosity streams. For an offset
   isosurface, `models/asym_split.py` computes the upstream `eps_A`/`eps_B`
   split. Its sides sum to the full porosity. The kernel does not halve those
   values again.

   Effective fluid conductivity is `K_ff_i = eps_i * k_i`
   for each stream. The symmetric prepared coefficient is therefore
   `eps_total/2 * k_i`. Offset factors `2*split_i` apply one time to that baseline. Existing prepared files keep their frozen coefficients. Reprepare the
   original configuration to get corrected coefficients, without rewriting
   historical inputs or results.
3. **Mass-flux inlet.** Compressible air uses the mass-flux inlet in both 2D
   and 3D. Solver velocities are interstitial, not superficial.
4. **Darcy-Forchheimer ownership.** `df_surrogate.predict_K_cF()` stays the
   pure geometry baseline: one water+sCO2 CFD table for both sides and each
   fluid. Base K0 and cF0 depend only on topology, L, and t. They are bilinearly
   interpolated inside 4–8 mm by 0.3–0.6 mm. They never depend on Re or fluid.

The UI exposes exactly two production methods. **CFD smooth-wall** stays
   the generic `ComputeConfig` default and is V2-compatible. Built-in Shanghai
   presets default to **Experiment calibration**. Saved inputs keep their
   choice, and legacy saved inputs missing the selector keep smooth CFD. **Experiment calibration** applies one fixed,
   reviewed effective correction per side after pipeline assembly and before
   pressure seeding/SIMPLE.

K/cF stay fixed for the solve. The selector routes
   to a dataset whose campaign, boundary, pressure-drop definition, and
   geometry match the run.

It is not evidence of fluid-intrinsic D-F physics. Differences can absorb pressure-tap location, contractions/expansions,
   manifolds/distribution regions, whole-HX losses, flow-area/channel-count
   definitions, instrument zero, and data reduction. These contributions are
   not separately modelled. Without a same-rig comparison they must not be
   attributed to fluid. The superseded `gamma_df` and `rbf` research modes
   are retired.

Selecting them explicitly now raises an error. Their code,
   tables and results stay available through the [history index](history/legacy-models.md).
5. **Nusselt ownership.** Air, water, and sCO2 base correlations belong to
   `models/nu_correlations.py`. The sole current sCO2 effective-parameter
   resource is `configs/sco2_effective_nu.json`, loaded by
   `sco2_effective_nu_config()` as a validated `Sco2NuConfig`. The kept
   `alpha_D/alpha_G` fields are total Ceff, applied one time to the current base
   before the existing final Nu floor. There is no additional beta layer or
   output-Q scaling.

   The generic `cfd_smooth` default and run-owned saved
   parameters are unchanged: explicit selection loads the current resource,
   while previous Cases continue to replay their recorded parameters. The retired
   experimental-gamma helper and environment switch are not a second route. Calibration evidence and physical scope are in [model resources](model-resources.en.md#sco2-有效-nu-系数). Full 2D/3D solves rebuild each side's local
   scalar Re/Nu from `models/local_heat_transfer.local_speed`: the current
   cell-centered pore-velocity magnitude, sqrt(uc² + vc² [+ wc²]). Do not
   select a fixed inlet-axis component or apply porosity a second time.

   Signed normal components still own face mass/enthalpy fluxes. The existing
   Re/Nu floors apply to genuinely low speeds. Initial inlet-range observations
   stay, but redundant bulk h_v arrays are no longer stored before the first
   local refresh. Prescribed-velocity approximate modes keep their definitions. Using bulk-fitted scalar Nu locally in turning flow stays a modelling
   assumption, distinct from this velocity consistency requirement.

   See the
   [implementation and paired validation](history/README.en.md#2026-09-18-历史材料整理).
6. **Compressible envelope.** `models/envelope.py` validates the actual final pressure and local Mach fields. Nonfinite states, pressure at/below the
   existing 1000 Pa floor and Mach >= 1 stay invalid. Positive/subsonic
   fields must also meet the specified physical inlet pressure to converge.
   An unusable isothermal 1D initial estimate is a numerical startup issue,
   not a proof that the coupled non-isothermal problem has no solution.
   Do not bypass the final-field or inlet-pressure gates by widening a clip
   or forcing a numerical answer.
7. **Pressure reference.** On ideal-gas sides, `P_ref_abs` anchors the outlet
   cells, and local absolute pressure is `P_ref_abs + P`. The physical outlet
   face can have nonzero extrapolated gauge pressure. `P_ref_abs + dP` is not
   the realized inlet pressure. Use geometric area means at actual port faces
   for inlet-pressure correction and its convergence diagnostic.
8. **Units.** Prepared contract quantities use K, Pa and m. Legacy closure calls that
   accept cell size/wall thickness in mm receive an explicit boundary conversion.
   Those internal units do not change persisted SI fields.
9. **Port boundary.** `ComputeConfig.validate()` normalizes both ports and
   calls the shared validator. 2D supports each ±x/±y direction. 3D also
   supports ±z, with both transverse extents validated against the correct
   domain axes. Non-opening exterior surfaces are stationary no-slip walls. Tangential momentum
   has half-cell viscous wall flux, including z± in 3D.

There is no volume wall
   penalty or post-solve velocity attenuation. 2D has
   no finite-thickness z term. Nz=1 3D momentum still has two z walls. Raw primary and staggered opening fractions come directly from the original
   rectangle on the final actual grid, never from averaged primary fractions. Positive raw overlap owns normal outlet flow and PPE support.

Taper stays
   a separate numerical profile. The inlet mass normalization and local outlet
   mass closure stay in force.

   Coarse bootstrap rebuilds the original ports,
   transfers inlet mass by physical open-area intersection, and reapplies the
   fine outlet support after prolongation. Its budget and initial-guess role are
   unchanged. Richardson does not add a fine SIMPLE solve.
10. **True-enthalpy ownership.** Any ordered fluid pair containing sCO2 uses
    the conservative enthalpy kernel. It consumes SIMPLE's signed staggered
    face mass flows and computes duty from boundary enthalpy fluxes. It must
    not reconstruct a full-face x-flow from a scalar mass rate. The shared kernel requires both face-flow tuples explicitly.

    Uniform-flow
    construction for numerical reference tests lives only in the test helpers. Each sCO2 side in 2D/3D uses the shared property-wrapper range
    **280–700 K, 7.9–16 MPa absolute**, at inlets and actual local states. The 2026-09-09 pressure-floor extension leaves the EOS backend and the
    independent Nu/D-F applicability and acceptance gates unchanged. It does
    not show experimental accuracy in the added range. Production Picard iterations use CoolProp BICUBIC only for CO2 T(h,P).

Final temperatures, coupled-energy checks, outlet inversion and all other
    properties stay HEOS. If an exact-EOS energy check fails, the remaining
    iterations finish on HEOS. Returning to the table can cycle between two
    different fixed points. Each thermal solve owns its mutable table state. HEOS enthalpy limits at local pressure keep domain-boundary checks on HEOS.

Results record `sco2_enthalpy_eos` in model metadata when the table is used,
    including the `bicubic_iteration_heos_polish_v2` algorithm and if
    exact-EOS finishing was needed. This is an approximate iteration algorithm, not an experimental calibration.

The separate experimental `TPMSHX_SCO2_COMPRESSIBLE` switch enables
    local-pressure density/viscosity updates only on the 3D A side and changes
    that side's pressure initialization/envelope handling. B-side sCO2 flow
    properties keep the inlet-pressure convention. This switch does not
    implement a full compressible continuity equation or qualify a symmetric
    two-sided compressible model. It is off by default. Its A-side flow-property
    pressure uses `P_ref_abs + P`, while true-h uses `P_in - dP_face + P`.

These anchors are not guaranteed equal. The ideal-gas inlet-pressure
    correction does not certify this sCO2 research branch.

    Compare actual
    inlet pressure and both anchors alongside mass/energy budgets before
    interpreting an ON/OFF difference as improved accuracy.
11. **Current TM1 limit.** sCO2 zones and offset level sets stay rejected. Air/water-only runs keep the qualified model-enthalpy and temperature
    routes listed above. For Nz>1, their end-cell treatment covers each
    physical fluid and solid end control volume. Tin is imposed at the open
    inlet face with half-cell conduction.

    Outlet zero-gradient applies at the external face. Explicit CC callers
    with SIMPLE supply actual inlet capacity transport. They keep the CC interior scheme. Prescribed B stays an external thermal reservoir.
12. **Experiment-correction applicability.** The air core-specimen branch uses
    L=6..8 mm, t=0.3..0.5 mm interpolation. T=0.6 uses the separate HX campaign. sCO2 uses only D/G-7-6 hot-side `ok_dp` evidence, keeps K=K0, and is
    HX-effective: uniform symmetric core, no zones, delta, other L/t, or
    independent cold-side fit. Its measured inlet-velocity windows are
    0.5827..2.5396 m/s (Diamond) and 0.6120..2.4705 m/s (Gyroid). These use
    absolute-pressure correction with the same hot-side `ok_dp` members, measured
    mass flows and experimental flow areas.

    sF stays frozen at 6.313005350332494
    (Diamond) and 7.608907691857889 (Gyroid). The fitted D-F parameters form a porous-region closure. They support valid custom
    port centres, widths, and each solver-supported flow direction. Only the
    full-face x-direction calibration boundary has direct experimental evidence. The
    water+air D/G-7-6 experiment consists of two complete, disconnected TPMS
    networks with
    delta=0.

    Shanghai's April 1 air path is straight/full-face while water
    uses staggered local openings. April 7 exchanges the fluid networks. Water and air use the same
    topology-derived single-side flow area (D 5.94e-4 / G 6.50e-4 m²), with no
    28/34 channel-count scale or geometric-face shortcut. The production water fit excludes G/water case 1 (`dp_nonphysical`) and D/water
    cases 10/11 (`duplicate_row`). It uses the declared high-flow window
    `u>=0.10 m/s`. This original calibration membership is unchanged.

    Fixed-K0 water RMSRE is 6.84% D / 0.93% G with sF 4.8928 / 4.1989. The measured upper bounds are 0.2541 / 0.2232 m/s. Matching HX-air uses its own sF. Diamond 1.8024228153853061 keeps its original
    campaign. Gyroid 2.649010286988306 uses April 1 straight-air cases 2–16.

    It uses fixed CFD K0, experimental endpoint mean temperature and the original
    1D compressible pressure-drop relative-error fit. April 7 is used for
    connection-transfer evaluation, not fitting this coefficient. Full 2D/3D
    results do not tune another multiplier. Source, columns, row membership,
    velocity conventions and measured errors are recorded in the
    [straight-air calibration source and scope](model-resources.en.md). `ComputeConfig`
    selects each side independently, allowing all nine ordered air/water/sCO2
    pairs and each valid 2D/3D flow direction.

A mixed pair can therefore combine
    corrections from different campaigns. That is a model composition, not joint
    experimental validation of the pair. Each HX-effective side still requires its
    own velocity window, the matching 0.182 x 0.042 x 0.042 m domain, and delta=0. Custom inlet/outlet positions and sizes stay supported. Each active side
    must match its own applicability rules.

There is no silent fallback. `hx_velocity_bounds()` keeps active calibration/source-audit windows.

`hx_application_velocity_bounds()` separately supplies the approved
    production windows (Diamond/Gyroid, m/s): water 0.0139648..0.254055 /
    0.0162341..0.225876. Air 3.88324..22.7599 / 3.91282..24.5467. SCO2
    0.434925..2.53961 / 0.381408..2.47046. Full precision is in the selector. These windows cover reviewed 7/0.6 mm full-HX measured combinations and
    approved port validation, not arbitrary T/P/mdot combinations.

Both ranges,
    actual inlet u and approved purpose are kept in correction metadata. Gyroid air records campaign `shanghai-air-straight-20260401-v1` and a
    `calibration` object with source workbook, sheet, rows, columns, method
    and accuracy scope.

Its source-convention calibration span is
    8.026110584256458..22.441995588974073 m/s. The same members in production
    inlet-density units span 8.027855328062564..22.446874107951544 m/s. The latter is saved as `calibration_runtime_velocity_window_mps` and
    used for the warning and `extrapolated` flag, avoiding a false warning
    at the source upper endpoint. Other campaign warning bounds are unchanged. Leaving the calibration window emits a run-local side-specific warning
    through the existing cache/UI/export path.

Water's lower-speed extension
    is substantial approved extrapolation. Water coefficients are unchanged.

    Gyroid air keeps the approved low-flow application window and computes
    those cases with extrapolation notices. Full 16-case statistics keep
    case 1, separately from the accepted 15-case comparison. Air-water
    pressure-error evidence does not qualify air-air or air-sCO2 accuracy. Each side applies its frozen sF exactly one time before pressure seeding and
    SIMPLE, with K unchanged. Explicit CFD mode and independent Nu selection
    keep their defaults.

    D-F permission does not relax water-state, sCO2
    property-domain, nonfinite, numerical or energy guards.

## Extension points

- Add a fluid through `models/fluid_props.py`.
  Keep its Nu implementation in `models/nu_correlations.py`.
  Record its versioned resource. Use it through the public module APIs.
- Add a user-facing configuration field to the `domain/compute_config.py`
  dataclasses first. Adapt it one time at the UI boundary.
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
The [data catalog](data-catalog.en.md) maps original filenames to this layout.
Workbook names also select the explicitly approved water pressure convention.
Renaming them requires updating that registry and its caller tests together.

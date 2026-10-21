# SJTU-TPMSHX-TM1 architecture

[中文](architecture.zh-CN.md) | [English](architecture.md)

Version 0.2 uses C++ as the only numerical backend. Python keeps the GUI,
CLI, preparation, model resources, optimization, result mapping and postprocessing.
The public `ComputeConfig` flow supports full 2D/3D.
Quick Design uses `prepare_quick_design` with its own operating-point input.
It then calls the same `run_case` and `evaluate` APIs.
Python numerical iterators, Numba/PyAMG dependencies and Python-only research
entries are retired. Saved research cases cannot execute; saved results remain readable.
T-SOU (`temperature_sou`) is the default conservative EOS energy algorithm.
H-FOU and T-FOU execution is retired. Historical IDs remain for saved evidence
and explicitly selected archived runtimes. Current libraries reject retired
algorithm IDs before flow execution. Old checkpoints require their matching
runtime; changing the requested algorithm starts a new computation.
Outer property Anderson is retired. Fixed property relaxation, thermal Anderson
and qualified flow acceleration keep their existing rules.

The native full-compute CC route uses the existing air/water integral h(T)
model through strict model-h drivers. Earlier variable-cp m*cp*T failures
remain in the historical record. Fixed-coefficient Quick Design, standalone
temperature, true-h warm-up and private C++ component routes retain their
separate contracts. Removing a Python entry does not expand these contracts.
Conservative staggered temperature retains its physical-distance minmod
reconstruction and original boundary treatment. Axes with fewer than three
cells stay first order.

`tests/native/test_native_engineering_acceptance.py` covers ordered air,
water, CO2 and sCO2 pairs in 2D and 3D. It checks selected physical models,
convergence, finite fields, mass and energy with the existing limits.
Independent formulas, discrete balances, manufactured solutions, component
replay and stored historical references replace Python solver comparisons.
No retired numerical iterator supplies the current reference result.

Version 0.1 preserves the former two-backend implementation and comparison
criteria in [its architecture document](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/v0.1.0/docs/architecture.md).
Those criteria included 0.1% duty/pressure/mass, 0.01 K temperature and
`1e-6 m/s + 1e-5 * u_inlet` velocity differences for matched models.
Those comparisons are historical evidence, not current two-backend execution.

SIMPLE residuals are audited against each run's returned field and F2 gates.
Progress samples must match its recorded residuals. Iterations and clipping
must respect the actual budget and stop reason. A capped outer run remains
nonconverged. Its last thermal state can pass its own physical checks without
qualifying the complete result for engineering use.
Full-driver and component tests check fields, iterations, boundary powers
and residual records against the selected native thermal algorithm.
Numerical qualification, desktop acceptance and experimental accuracy remain
separate results. Historical failures retain their original status.

Conservative temperature updates share fluid and solid row assembly in `energy_fv_rows.hpp`.
The caller owns input checks, EOS state updates, iteration budgets and stopping gates.
The actual-state audit keeps independent physical balances and signed boundary duties.
The coupled-only audit keeps unavailable fluid residuals as NaN and does not read fluid conductivity.
The frozen H sweep and its low-level C export are retired. Shared audit types and functions remain.

The 2D and 3D model-h drivers share one accelerated chunk owner.
Strict 3D calls use five sweeps per block and sixteen Anderson samples.
Other calls retain 25 sweeps per block and six samples.
Both policies charge two proposal probes and keep separate history for each chunk.
The strict policy meets the original energy gate in the tested graded-grid case.
Full 3D results record whether acceleration was enabled, the block size, and the history limit.
Snapshots retain the block size and complete history. Restore rejects a different policy.
A complete selection boundary can export the consumed budget and an independent history copy.
A failed partial step cannot export or resume that chunk.
`ModelHRun2D` and `ModelHRun3D` own the thermal iteration state.
The existing one-shot entries use these same owners.
Snapshots copy temperatures, stopping history, active chunk history, 2D linearization and 3D carry fields.
Restore rebuilds derived face buffers and conductances with the same input and controls.
It validates saved state before it writes destination temperatures.
An accelerated advance completes one block and any proposal probes. A nonaccelerated advance keeps the original complete chunk.
Callbacks keep their original sequence. A callback cannot save or advance an unfinished step.
Cancelled, failed and completed runs cannot publish a new thermal snapshot.
The caller receives the final physical ledger through the original output argument.
Both full controllers archive their active model-h state.
See [native continuation](#native-3d-continuation) for full-controller and application recovery.

## Completed execution records

Public full solves add `metadata.execution_record` with version `full_execution_v1`.
It records each side's flow and heat-transfer resource separately from its energy relation.
An EOS energy relation records the HEOS fluid and the actual thermal pressure field.
Integral h(T), capacity temperature transport and prescribed temperatures remain distinct.
The record copies returned algorithm identifiers, effective settings and state labels.
A missing algorithm identifier stays null; requested settings do not establish execution.
For CO2 and sCO2, the initial inverse backend applies only to its listed sides.
The HEOS finishing flag remains explicit.
The nonlinear unknown and face reconstruction remain separate fields.
A temperature unknown can use enthalpy face reconstruction.

Thermal and final-flow state labels remain separate after an outer post-update.
This record describes the completed execution; it is not a new quality certificate.
Rejected runs and Quick Design keep their existing contracts.
Saved records retain this metadata. Reading a historical result does not add it.
The prepared builders also return `input_resolution`, with version `prepared_input_v1`.
This record identifies validated resources, physical grid sizes, active sides, directions and cell-length units.
Its input source is `CaseData.parameters`; an edited GUI draft does not change it.

The numerical owners record property sampling under `property_sampling`, with version `full_sampling_v1`.
Each entry identifies the side, outer index, stage, quantity, provider, temperature source, pressure source and operation.
The last thermal and flow operations remain separate from initialization and property updates.
Entries distinguish inlet values, local values, volume averages, relaxation and transfer to a refined thermal grid.
The 3D true-h record includes its temperature warm-up and its EOS energy solve.
An inactive B side has no flow or heat-transfer sampling operation.
The record preserves the different 2D and 3D sampling rules and each recorded energy relation.
The native query borrows views from the result owner; Python copies these views before release.
Current bindings require the added query and report an explicit error for an older native library.
Saved results retain both records. Historical results retain their original metadata.
Final applicability and physical quality remain separate decisions.

The native full drivers resolve each side's physics before iteration.
`SidePhysics` keeps the transport fluid, energy relation, conductivity source and heat-transfer sampling rule.
The 2D owner passes these choices to its main and refined thermal calls.
The 3D owner keeps them for the run and derives them again from matched inputs on restore.
Current input validation, phase guards and sampled-state records stay at their existing owners.
The selected rules retain the differences between dimensions, EOS warm-up, prescribed B and research routes.
Two-fluid full runs that use the conservative EOS driver now select energy by fluid.
Air and water use their existing integral h(T); CO2 and sCO2 use HEOS h(T,P).
The air/water conductivity comes from prepared fields in 2D and the outer transport state in 3D.
CO2 and sCO2 keep local HEOS conductivity.
In 2D, air/water heat transfer uses the outer mean density and viscosity, with inlet conductivity and Pr.
CO2 and sCO2 use local properties at the lagged temperature and inlet pressure.
These choices no longer depend on the other fluid. The 3D sampling rules stay unchanged.
Direct component C entries keep their existing models.
Explicit fixed-capacity, prescribed-side and research routes retain their separate contracts.

The full 3D owner keeps raw transport properties at each side's inlet pressure.
It reuses a cell's values only when that cell's temperature is equal to the sampled temperature.
The fluid, provider, inlet pressure and grid are fixed for this runtime.
Flow updates use the existing physical-to-solver coordinate mapping.
The A-side local-pressure sCO2 experiment keeps its direct property evaluation.
Relaxed density and viscosity are not cached. Water-state checks and range observations keep their original call sites.
The derived values are not saved; restore starts with empty buffers.
The buffers add 48 bytes per sampled side and cell, or 3 MiB for both sides on a 32 cubed grid.

Each full conservative run normalizes the h update separately for each fluid.
Its scale is inlet cp times the absolute inlet temperature difference, with a 1 J/kg minimum.
This scale does not depend on the fluids' enthalpy origins.
The additive full-driver `get_energy_update_scale_v1` queries return the actual scales.
Existing C structure layouts stay unchanged. Python bindings require the matching native library.
The execution record stores `enthalpy_update_normalization`; checkpoints retain its values and definition.
Historical saved results retain their original models, normalization and metrics.

Full C++ 2D EOS runs also accept the optional thermal controls in `SolverConfig`.
The additive `full_2d_v4` entry passes the iteration and sweep budgets, relaxation,
normalized h-update tolerance, Kelvin update tolerance and both energy gates.
The optional h-update check on a temperature solve remains a separate gate.
Unset controls retain native route defaults. Integral model-h routes
reject these EOS-only overrides before flow execution. Existing v2/v3 C callers
keep their original layouts and defaults. Saved effective settings identify the
controls used by each completed thermal call.

Full C++ integral h(T) routes accept three optional `SolverConfig` controls:
`model_h_max_iterations`, `model_h_temperature_tol_K` and `model_h_q_relative_tol`.
The iteration budget counts sweeps, including charged startup trials.
The Kelvin tolerance limits the field change between thermal chunks.
The relative Q tolerance compares the existing observed heat duties.
Unset controls keep each route's defaults, including the 0.01 K field-change gate.
Chunk sizes, phase checks and physical energy gates stay unchanged.
Explicit controls apply to both 2D main and refined thermal calls.
They also apply to 3D model-h, integral full CC and the integral `Nz=1` delegate.
Quick Design and other thermal routes reject these controls before flow execution.

The additive `full_2d_v5` and `full_3d_v4` C entries use the existing engines.
Their option fields use zero for an unset override; public Python values use `None`.
Existing C entry layouts and defaults stay unchanged.
Native queries return actual call settings as `model_h_iterations_v1`.
Each record identifies its outer index, attempt, main or refined stage, call cap and total budget.
It also records the chunk size and both tolerances, including rejected startup trials.
The result and execution record retain these owned settings through file storage.
Historical files keep their original metadata.
The 3D continuation owner also receives these controls through its additive v2 create and restore entries.
Typed checkpoints retain the overrides and actual call records.
Restore rejects changed controls before numerical work.

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

The C++ 3D model-h driver computes fixed mesh/conductivity face conductances
once per thermal call. Numerical line and red-black sweeps reuse these values,
including the inlet Fourier reconstruction. Temperature-dependent face
transport, exchange, sources and row accumulation order stay unchanged.
Physical audits recompute conductances from the original inputs. The cache is
local to the call and adds 216 bytes per cell when both fluids are solved
(about 2.85 MiB for 24 cubed cells); prescribed B uses 144 bytes per cell.

For source-free 3D model-h, stable heat and temperature changes trigger the
shared energy certificate. A failed residual or source-balance gate continues
thermal sweeps within the existing budget. Missing physical inflow data returns
an unconverged thermal pass for a flow update. More sweeps cannot repair its
fixed mass faces. An unconverged thermal pass cannot end the outer iteration as
converged. Final certificate data are reused without another numerical solve.

Manufactured-source tests keep their stopping rule because their external
sources do not obey the source-free LTNE exchange balance. See [capabilities](capabilities.en.md), [model applicability](model-resources.en.md)
and [data provenance](data-catalog.en.md) for the separate physical scope.

## Physical balance evidence

Full results retain available physical heat audits under `boundary_fluxes.energy`.
The record version is `physical_heat_ledger_v1`. The existing
`boundary_fluxes.temperature` record provides the same arrays for its declared transport.
These records retain signed outward advection and diffusion, source integrals,
phase residuals, solved-phase flags and prescribed-B reservoir power.
Residuals use physical RHS minus diagonal times state.
Units are W/m for 2D and W for 3D. The last thermal state stays separate from later flow updates.
The refined 2D thermal audit stays under `boundary_fluxes.fine`.

`postprocess.api.evaluate_physical_balance` reads this evidence without solver or EOS calls.
It returns mass inflow, outflow and divergence, phase residual norms, signed external power,
and the difference between summed residuals and external power.
Its diagnostic power scale is the maximum absolute phase net boundary power,
phase source integral, prescribed reservoir power and one native power unit.
The output retains this scale and its definition. It does not replace any existing route's acceptance denominator or tolerance.
An available audit does not establish convergence, applicability or design acceptance.

Native queries borrow arrays from the existing full-result owner.
The bindings copy these arrays before release. Missing or released owners return an error.
Cancelled results and routes without a complete captured audit report unavailable evidence.
True-h retains a ledger only when the existing final audit computed all phase equations.
Historical files keep missing evidence as missing; the reader does not create a zero balance.

## Captured parameter limits

Prepared cases store original model bounds and inlet samples in
`applicability_inputs`. Completed full solves store `applicability_evidence_v1`.
Preparation and native execution keep the last actual source call for each side, stage, layout
and array shape. The existing warning record keeps extrema from all calls.
The additive C queries borrow the existing result owner. The bindings copy
their values before release and require a current library.

`postprocess.api.evaluate_applicability(result)` reads this evidence without
an EOS or solver call. It checks the inlet and last local correlation inputs,
including Re before its floor. Missing required evidence returns an unverified
state. An old file without evidence returns an unavailable state.

For positive original bounds `[L,U]`, the allowed parameter interval is
`[0.9L,1.1U]`. Any sample beyond that interval fails the range check.
The limit is not a fraction of cells. Zero or signed boundaries require a
specified domain rule for extrapolation. Geometry bounds stay fixed.
The water HX calibration lower speed of 0.10 m/s permits 0.09 m/s.
A broader historical application window does not change this limit.

This range result does not grant convergence, experimental acceptance or
full design qualification. It retains model-scope notices, including unresolved
joint sCO2 correlation coverage. Existing compute permissions, hard property
and phase checks, frozen coefficients and numerical stopping rules stay in effect.

## Common result verdict

`postprocess.api.evaluate` stores `result_qualification_v1` in
`PerformanceResult.qualification`. `evaluate_qualification(result, metrics)`
can reproduce it from saved evidence without a solver or EOS call.
Execution, convergence, physical evidence, parameter limits, metric availability
and design eligibility have separate states and source paths.
Unknown evidence remains unverified. A failed gate remains failed.
The physical conclusion keeps the existing route-specific tolerances and
requires complete captured heat and active-side mass evidence.
Only 2D model-h and integral-temperature routes require a refined thermal ledger.
Its thermal state stays separate from the final SIMPLE pressure state.

The design conclusion requires all recorded gates to pass.
Original model bounds use the agreed 10 percent parameter allowance.
The unresolved joint sCO2 P/T/Pr and wall heating or cooling scope remains unverified.
Quick Design and historical records without the required evidence do not gain full design eligibility.
Experimental, mesh-accuracy and desktop acceptance remain separate from this result verdict.

GUI summaries, history, CLI output, exports and full-compute measurements retain the same conclusion.
CLI exit codes retain their stage-success meaning; read the design state separately.
Optimization recomputes the common verdict from the supplied native result and metrics.
Its separate `optimization` verdict permits sCO2 studies while model accuracy remains unverified.
Only the known sCO2 model-scope gap is deferred, with complete execution records for both sides.
The user must assess correlation applicability before they rely on a selected design.
Execution, convergence, physical evidence, parameter limits, metrics and full-solve gates must all pass.
A failed or unknown required gate prevents both baseline and candidate objectives.
The `model_scope` and `design` conclusions stay unverified; optimization permission does not validate the model.
The batch keeps its diagnostic result, available metrics and failure reason.
Saved qualification records retain their original values until explicit reevaluation.
The former optimizer-only energy evaluator is now part of common postprocessing.

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
- `solvers/backends/cpp/` exposes the independent prepared Quick Design and
  full 2D/3D drivers through `RunControl`, which defaults to C++. The host library path is not serialized in CaseData. Shared QD validation and
  result mapping belong to `solvers/backends/quick_design.py`. Numerical property
  passes, liquid-state guards and thermal iteration belong to the C++ driver. Its returned scalar pass evidence is expanded into the same fields and warning
  records for postprocessing.

  Full 2D/3D own SIMPLE, pressure references, outer
  property/thermal coupling and final certificates in C++. 2D also owns
  Richardson refinement.

  The binding borrows immutable prepared design arrays for its synchronous
  native call. It keeps strong references through the call and result capture.
  The existing dtype, alignment and unit conversions still allocate when required.
  Public Python input builders return independent, writable design arrays.
  The binding maps native evidence into the same `FieldResult`. It does not call Python numerical
  kernels. Full 3D ABI 2 removes outer property Anderson controls and state; fixed property relaxation and thermal Anderson remain.
  Full 2D ABI 2 keeps the original prepared Nu geometry ratio rather
  than reconstructing it after a unit conversion. C++ is the only numerical backend.
  The required native CI suite passes on macOS arm64/Python 3.13 and Windows
  x64/Python 3.12 and 3.13. Visible desktop delivery and full performance
  qualification stay separate gates.
- `Simple2DSolver` and `Simple3DSolver` retain each active flow call.
  `start` begins the call. `advance` completes an ordinary step and any enabled 2D proposal before the F2 check.
  The existing one-shot entries use these operations.
  Active snapshots own the fields, F2 confirmation and stall state, result,
  histories, inlet target, clip count and pressure hierarchy construction state.
  Restore preserves the original iteration budget, momentum schedule and pressure
  rebuild cadence. It validates saved state before it writes caller fields.
  Initial correction arrays keep their original unused-value rules.
  Warm-call snapshots stay separate from active-call snapshots. Callbacks cannot
  save or re-enter an unfinished step. Cancellation is checked before each ordinary or proposal step.
  Physical equations and final boundary certificates stay unchanged.
  Both full controllers archive active flow state for application recovery.
- `EnthalpyRun` owns the T-SOU Picard iteration state.
  Each advance completes one original iteration, including its SOU proposal.
  Initialization uses the existing property lanes and keeps the same physical checks.
  Completed runs transfer final effective conductivity to the full controllers.
  This removes repeated EOS evaluation at the same thermal state.
  An active snapshot owns five solution fields, transport values, result
  evidence and Anderson history. Exclusive H bounds, table bounds and inverse
  work arrays are retired.
  Restore requires the same inputs and controls. It validates saved state before
  it writes caller arrays. EOS evaluators and temporary arrays are built again.
  Failed or cancelled runs cannot export an active snapshot. Callbacks cannot
  save or re-enter an unfinished step. The existing `solve_enthalpy` entry uses
  this owner; the two separate stack-only iteration loops are retired.
  Physical checks, final audits, iteration budgets and cancellation points stay
  unchanged. This component interface does not provide file or application recovery.
  Direct `EnthalpyRun` calls can set `inlet_direction=-1` for each side.
  This assigns that side's scalar inlet state to every exterior inflow.
  Directions 0 through 5 retain the single-face inflow check.
  Full 2D/3D drivers retain their port checks.
  Direct T components can omit either coupled or equation stopping tolerance.
  They still compute full energy evidence for ordinary and proposal states.
  Supplied gates, the Kelvin gate and the optional normalized-h gate control stopping.
  Full 2D/3D T controllers still require both physical energy gates.
  Direct C `tpmshx_solve_enthalpy_v2` selects T-SOU and returns its actual
  algorithm, Kelvin update and Picard relaxation. It takes a separate positive
  Kelvin limit. The existing configuration retains its normalized-h update
  limit as a strict less-than stopping gate. The v1 relative boundary imbalance
  limit remains below 0.05. Coupled and equation gates remain
  individually optional. Internal full-equation evidence does not publish an
  unrequested audit. `NativeEnthalpyDriver` requires this entry and the recipe
  query before execution. It reports the returned algorithm and K update.
  Its `tol` remains dimensionless; `temperature_tol_K` is a separate limit.
  The direct T-SOU call uses HEOS PT and does not create BICUBIC tables.
  The v1 POD layouts and symbol remain. The v1 entry now uses T-SOU with
  a fixed 1e-8 K gate and its original strict h and boundary gates.
  Table-directory fields and historical clip/table result fields remain in
  the C layout. T-SOU does not use tables or clip enthalpy.
- `TemperatureRun` owns fixed-capacity cell-centered temperature state.
  `StaggeredTemperatureDriver` also retains an active temperature call.
  Each advance completes one original thermal chunk. The existing one-shot
  entries use these owners. Snapshots own the three temperature fields and
  the last result. Staggered snapshots also retain the actual projected face
  velocities and MAC evidence. Restore does not repeat that projection.
  The previous fields and heat value are rebuilt at the saved chunk boundary.
  Inputs and controls must be unchanged. Invalid saved state is rejected before
  caller arrays are written. Cancelled or failed calls have no save boundary.
  Callbacks cannot save or re-enter a partial chunk. The existing sweeps,
  prescribed B, sources, stopping gates, budgets and cancellation points remain.
  The cell-centered zero-budget call returns no heat audit. The conservative
  staggered zero-budget call retains its projection and final audit.
  Staggered result transfer releases the active face and field buffers; only
  its original pressure hierarchy cache remains. The replaced stack-only
  control loops are retired. The full 3D controller archives the active staggered state.
  See [native continuation](#native-3d-continuation) for full-controller and application recovery.
- The C++ fixed-flow `solve_enthalpy` uses `temperature_sou`. It solves conservative enthalpy transport
  with temperature as the nonlinear unknown, guarded HEOS PT state updates,
  Fourier conduction and LTNE exchange. `conservative_energy` owns the frozen
  finite-volume sweeps and direct enthalpy face reconstruction. The driver owns
  EOS refresh, stopping and actual-state certificates. This algorithm requires
  declared scalar inlets and adiabatic external boundaries. Its SOU outlet
  reconstruction differs from model-h.

  The full 2D/3D controllers require a maximum temperature
  update in K and both explicit energy gates. Ordinary invalid PT states fail
  without clipping. SOU recipe 2 proposes six-sample Anderson updates before ordinary PT evaluation. It accepts only actual-PT/audit merit improvement. A rejected proposal keeps
  the ordinary path.

  Only a complete
  ordinary block can converge or give the final budget certificate. T-SOU is the default on the existing two-fluid true-h routes.
  Other physical routes keep their original kernels. The persisted `SolverConfig.enthalpy_algorithm`
  and `enthalpy_temperature_tol_K` select the algorithm and update gate.
  Full 3D candidates accept prepared `port_wall_refine` grids with full or
  partial openings. They retain the actual cell widths and port face masses.
  Explicit EOS controls on incompatible routes fail before flow execution. Production fluid applicability stays unchanged.

Additive full2D v3/full3D v2 entry points reuse the previous result layouts
  and owner release functions. Read-only queries expose the executed algorithm,
  actual thermal conductivity and six outward boundary enthalpy-power planes. The same loaded binary's energy recipe query identifies SOU2 from each
  actual returned algorithm. Bindings copy that version into main, outer and
  boundary evidence. Missing query capability fails before conservative flow
  execution.

Offline boundary readers keep saved FOU1, SOU1 and SOU2, while
  rejecting unsupported algorithm/version pairs. Result PODs and ABIs do not
  change with the recipe.

  Portable candidate results use `thermal_mode=conservative_energy`. Their
  heat is the negative sum of these captured planes, in W/m for 2D and W for
  3D. Offline readers validate this evidence without reconstructing SOU or
  calling an EOS. Thermal mass/temperature evidence stays separate from a
  subsequent final flow update, including iteration-limit returns.
- Full C++ 2D/3D true-h drivers use the same `EnthalpyControl` and native default resolver.
  The bindings read defaults from the loaded library, then apply explicit caller controls.
  Preparation keeps unspecified true-h controls unset. The T-SOU defaults are:

  | Route | Maximum iterations | Sweeps per iteration | Fluid relaxation |
  | --- | --- | --- | --- |
  | 2D T-SOU | 12000 with water; otherwise 5000 | 5 | 0.2 |
  | 3D T-SOU | 1500 | 5 | 0.2 |

  Zero sweeps retain the initialized or warm-up thermal state. The actual
  energy audits and requested stopping gates still apply. A failed gate keeps
  the iteration-limit return; zero updates do not certify physical convergence.

  The default normalized h-update tolerance and both energy tolerances are 0.001.
  The temperature update tolerance is 1e-8 K; its optional extra h gate is off.
  Full 3D explicit controls keep their existing precedence and supported scope.
  Read-only result queries provide actual settings for the last thermal call and each outer iteration.
  `available` requires a completed true-h call, including a budget-limited call; it does not certify convergence.
  Cancellation and other thermal routes have `available=0`.
  The bindings require these queries before execution; rebuild older libraries for the current bindings.
  C input/result layouts, owner lifetimes, and existing entry points remain unchanged.
  The 2D flow-first order and 3D thermal-first outer order remain separate.
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
- Public conservation tools prepare a `ComputeConfig` with `preprocess.api.prepare_case`
  and execute it with `solvers.api.run_case`. The Python-only `prepare_research_case`
  entry and `research_three_d_v1` execution are retired. Native component tests retain
  manufactured sources and boundary checks without a second public research interface.
  `RunControl` supplies progress, cancellation and other host callbacks.
  Prepared dictionaries cannot contain runtime callbacks. Saved results preserve
  recorded units, axes and the distinction between final flow and last thermal state.
  Retired pipeline facades and mixed-kernel entries remain absent.
- `workflows/compute.py` owns configuration validation and the common prepare, solve and evaluate sequence.
  It checks cancellation between stages and after postprocessing. It records stage times and warnings in the returned `FieldResult` metadata.
  The result identity and immutable array storage stay unchanged. The workflow returns `CaseData`, `FieldResult` and `PerformanceResult`.
  Overall progress uses this workflow. `RunControl` keeps raw solver progress, backend selection and host callbacks.
  `controllers/module_adapter.compute_result` calls this workflow and the sole application result mapper, `to_compute_result`.
  The GUI, direct-summary CLI and validation tools use this entry. The file CLI uses the same workflow and portable results.
  The previous 2D/3D mappings stay only as frozen test references for real native-result comparisons.
- `solvers/backends/prepared_2d.py` and `prepared_3d.py` validate execution inputs for native execution.
  Callers can request writable design copies; the binding borrows immutable arrays through the same checks.
  `solvers/backends/capture_2d.py` captures portable native 2D evidence. Numerical drivers remain in C++.
- `ui/` owns PySide6 and PyVista presentation only. `ResultCache` owns one published `ComputeResult` for the accepted dimension.
  Both dimensions publish separate scalar, metadata, diagnostic and warning containers while sharing field arrays.
  The footer, history, diagnostic text, plots and exports read this result. Display timing is added to its metadata after publication.
  A failed or cancelled attempt keeps
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

GUI computations pass the selected native thread limit through `RunControl`.
  Optimization keeps its separate process/thread resource policy.

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

All public execution uses C++. Python numerical and research-only entries are retired.
A missing native library fails explicitly before numerical execution.

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

Historical water-Nu comparisons remain in `tests/water_nu_reference.py`.
The independent one-dimensional enthalpy reference remains in
`tests/enthalpy_1d_reference.py` for its focused regression tests.
The former full 2D/3D Python enthalpy iterators are retired.
Native audits and component replay cover their retained physical contracts.
Production keeps the direct water CFD closure and native enthalpy driver.
The unused `postprocess.report` and `postprocess.visualization` helpers are
retired. Public evaluation, recorded-field plots and exports stay supported.

### Shared solver implementation

All supported fluids use the native `Simple2DSolver` or `Simple3DSolver`.
The native F2 monitor requires consecutive momentum, fresh-density local/global
mass and outlet-backflow checks. Full and component calls use this criterion.
`convergence_mode=None` resolves to `f2`; explicit `legacy` is rejected.
A static field triggers a check and cannot alone establish convergence.

The mass-only/velocity exit and its associated inner SIMPLE implementation are retired.
Full native 2D calls use `simple_2d_fixed_density_anderson_v1` for fixed-density sides.
The shared Anderson helper proposes normalized velocity and pressure fields.
Each proposal completes a pressure correction and consumes one step from the original budget.
Acceptance requires no larger momentum residual, both original mass gates, and zero outlet backflow.
A rejected proposal restores the ordinary fields and pressure cache.
The original F2 confirmation, stall checks, and final outlet certificate still apply.
If a proposal crosses a scheduled momentum check, the selected fields receive that check.
Each advance records one residual sample for the selected fields.
Iteration counts include all proposal steps.
The saved state includes Anderson history, pressure scale, and proposal counts.
`metadata.simple_flow` and the execution record identify each final flow call and its actual proposal counts.
Standalone component defaults keep ordinary SIMPLE.
Thermal Anderson remains active; outer property Anderson is retired.

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

Full C++ 2D/3D accepts optional `SolverConfig.simple_velocity_relaxation` in `(0, 1]`.
Unset values retain 0.7 in 2D and 0.5 in 3D. This setting does not change F2 gates.
Prepared cases retain the explicit value. Quick Design rejects this override.
The full execution record keeps the velocity relaxation passed to the completed native call.
The 3D continuation owner rejects a changed value on restore.

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

Native full 3D saves `diagnostics.coarse_bootstrap_trace` by side. It records
the effective policy, threshold, first/recursive caps, attempted coarse shapes,
depth and each layer's actual stop, charged iterations and seed application. `solve_started` means at least one iteration of that layer was entered.
`actual_levels` counts those layers and `started_cap_sum` sums only their caps. `total_charged_iterations` sums entered iterations, including a failing one. A skipped layer, or a parent cancelled while a child runs, can keep its
configured cap with zero charge.

These records never control or extend a solve. The historical bootstrap summary still describes the first coarse level. Previous result files stay readable. Rerunning an explicit legacy configuration
requires selecting F2 and accepting the independently measured result.

Preparation and model references use `models/fluid_props.FluidModel`. The registry imports
air/water primitives from `tpms_props` and Nu functions from `nu_correlations`
directly. `tpms_calc` keeps its public re-exports without a return dependency
from the registry. Correlations, property sources and validity checks stay in
their owning model modules. Native full controllers own outer iteration and temperature-delta tracking.

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
averages transverse drag and side B no longer replaces it with uniform drag. Recomputing a previous nonuniform grid-zone case can therefore change its results. Saved historical results are not rewritten. The 3D constructor also accepts row arrays and broadcasts them
along its first axis. Its existing momentum sampling stays: adjacent-x
averages at u faces, downstream-cell samples at v/w faces.

Geometry gradients
still require independent physical validation. Parameter smoothness does not
show TPMS surface connectivity or manufacturability.

TPMS geometry uses an exact count index for repeated level-set thresholds.
Sorted absolute phi values give the occupied voxel count. Cumulative edge
changes give the exposed face count. The inclusive threshold, sampled grid,
domain edges and area correction stay the same. The cache retains two
topology/resolution pairs. At N=128, each index uses 32 MiB in addition to the
16 MiB phi grid. The first query builds the index. Calibration, sigmoid tables
and asymmetric geometry keep their existing scan functions.

Each continuous-field axis accepts at least one control. A singleton is
recorded at the domain midpoint and stays constant along that axis. Other
axes use degree `min(spline_order, control_count - 1)`. Existing XY fields
with at least two controls per axis keep their original bivariate spline.
Solver cell centers and modeling boundary samples share `evaluate_axes`.
Geometry exports preserve original controls and use one staged file set.
The sampling limit is one million points; optimization checks the installed
Sobol dimension limit before allocating its decision bounds.

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
calibration restrictions stay. CO2 and sCO2 support symmetric continuous fields;
discrete zones and nonzero level-set offsets remain unsupported. This does not
extend sCO2's uniform experimental D-F calibration to a gradient.

The separate `co2` model uses the versioned `co2_segment2_v1.json` Nu and
symmetric geometry resource. Shared preparation gives both streams that geometry.
Only CO2 sides receive fixed drag factors `K=K0/2.5`, `cF=2.5cF0` and the
Nu factor 1.28, including the Nu floor. These apply once, independently of
`df_mode`, and survive Case/FieldResult archives as model references and metadata.
CO2 keeps the HEOS physical relation and its single-phase checks.
T-SOU evaluates checked HEOS PT states. Model reference inverses keep HEOS. Native execution evaluates CO2/sCO2 local h_v with the
lagged temperature and local L/D_h/A_0 fields. Air/water retain their existing
property-sampling rules. Native coefficients come from the shared generator.
The native fluid enum appends CO2 as value 3; existing values and POD layouts
stay unchanged. CO2 execution requires a library built with this model.

`preprocess.api.prepare_fixed_mass_flow_case` owns fixed-flow preparation.
`FluidConfig.mass_flow_kg_s=None` keeps velocity input. A positive value
prescribes total inlet flow. The public `prepare_case` resolves only those
sides through the same inlet integral, before checking their velocity and
calibration limits with `validate(resolved_inlet_speeds=True)`. Other sides
keep their velocity inputs. Input validation does not inspect an inactive
cached velocity. Case snapshots save both the target and resolved speed;
`parameters.inlet_inputs` carries them into native and application results.
Explicit batch flow arguments override saved inlet modes on a run copy.
The 3D GUI exposes the two input modes. Programmatic 2D total-flow inputs
still require an explicit physical depth and retain per-depth solver units.
The 3D mass-imbalance diagnostic integrates signed inlet and outlet fluxes
with local porosity, consistent with the SIMPLE continuity operator. An
unweighted intrinsic-velocity integral is not a mass-conservation test for
a spatially varying porosity field.

The existing `optimization.multi_condition` imports remain available. For each
inlet, preparation integrates local single-channel porosity times the actual
normalized inlet velocity profile over the opening. It multiplies this integral
by inlet density, then divides prescribed total mass flow by that product to set
inlet velocity. In 3D, it builds geometry, the grid, ports and inlet properties
once. It validates the resolved speeds, then completes range observations,
D-F application and the Case snapshot from that same prepared data. Ordinary
and fixed-flow preparation share these final steps. The 2D path reuses the final
mesh from inlet capacity preparation. For spline designs, it also reuses that
mesh's geometry and then adds inlet fluid conductivity. The original nominal-grid
validation stays. Legacy stripes, rectangles and sigmoid fields keep their final
property construction and original smoothing rules. All speed-dependent steps use
the resolved inlet speeds. The 2D taper normalization uses geometric open area independently
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
resolves its own inlet speeds again using its local porosity field. `aggregate_multi_condition` compares useful B-side
uptake (`-Q_B`) and both relative pressure drops with paired baseline conditions.
It requires complete converged results. Heat and pressure stay separate
objectives. Each condition has equal weight, with 50/50 pressure-side weights. These helpers do not qualify a closure or start an optimization run.

`evaluate_condition_batch` supports air-A/water-B and pairs with CO2 or sCO2.
All conditions keep the same ordered fluid pair and design. Each batch uses
a new directory and records all requested members in `batch.json`.
The `workers=None` default selects at most four native processes.
Automatic allocation keeps at least two CPU slots per process when the total limit permits.
The condition count also limits the number of processes. `workers=1` selects serial execution.
An explicit positive count remains subject to the condition and total CPU limits.
The total native CPU limit is split between the active workers.
New batches, recovery and optimization use the same allocation rule.
Each native worker has its own EOS tables.
Progress and other host callbacks run in the parent process.
Returned results keep the input order, even when workers finish out of order.

Native members use `workflows.recovery.compute_prepared_run` with their saved
fixed-flow input. They do not repeat case preparation. Each member requests
an iteration checkpoint every 60 seconds, at an available safe boundary.
The batch keeps its original inputs, selected native library and baseline files.
After postprocess, `results.h5` and `metrics.json` are published together.
If a later stage fails, `failed-result.h5` keeps completed solver fields when no result pair was published.
The failure record keeps the original exception.

`resume_condition_batch` reads a native batch into a new output directory.
It checks and copies completed members without solving them again.
It continues unfinished members from their latest valid native checkpoint.
A member with no checkpoint starts from its saved prepared input, when available.
The record distinguishes this restart from checkpoint continuation.
Input, baseline, qualification and native build checks still apply.
The caller must select an explicit native library. The source batch stays intact.

Both `batch.json` and `optimization.json` record the requested backend.
The batch keeps failure stages, reasons, unrun members and baseline metric identities.
Ordinary condition failures allow later members to run. No penalty value replaces a failed result.
Cancellation stops new submissions, stops active workers and propagates `CancelledError`.
A worker process exit stops the batch; completed files and checkpoints remain available.
If a status write also fails, the original exception keeps the storage error as a note.

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

Only a complete numerically accepted batch can publish the two objectives.
The baseline must have positive B-side heat uptake `-Q_B` and positive pressure
drops; objective signs and equal weights do not change for CO2/sCO2.
In addition to native convergence, model-h 3D reuses the existing full-control-volume
certificate from `postprocess.conservation.compute_phase2a`. Each fluid's
global/cellmax residual and the LTNE source imbalance must stay below 1%.
The source ratio uses `max(abs(Q_sA), abs(Q_sB), 1 W)`, the existing
strict-energy zero-duty scale. Thus the absolute source residual must stay
below 0.01 W near zero duty. The native result uses this rule.
The physical boundary ledger must be complete. Native 3D finishing and the
conservation audit use the same pure certificate function in `result_math`.
The public postprocessing entry accepts `FieldResult` only and extracts its
recorded certificate; numerical kernels pass their local evidence directly to
the pure function.

The 2D branch requires the native main/fine
model-h balances, complete physical boundaries and Richardson acceptance.
True-h and its explicit conservative-energy candidates use their own native
certificate: thermal convergence, no enthalpy clipping, and finite coupled and
equation energy ratios within the recorded solver tolerances. They do not use
the model-h certificate or Richardson. Algorithm and temperature-update settings
must match the baseline. This is separate from experimental accuracy,
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

New searches save fixed inputs in `optimization-input.json` before numerical work.
`resume_multi_condition_optimization` compares that input with the search record and the current dependency versions.
It checks the initial Sobol sequence, saved proposals, history order, objectives, and fixed initial reference point.
Recovery copies the complete source archive to a new directory before execution.
The same search loop checks completed batch evidence without another solve.
It retains failed observations and continues incomplete conditions through batch recovery.
An incomplete condition uses a new condition directory within the copied batch.
Previous checkpoints stay available if another pause occurs during preparation.
Saved proposals keep their decisions and budget. Only an unsaved proposal is generated again.
Pause uses a separate event from cancellation. The parent stops new submissions and waits for active workers to save checkpoints.
Cancellation takes precedence while a pause is pending. Terminal publication must succeed before the UI reports a saved pause.

Final candidates need all-condition and grid verification with
objectives recomputed on those results. The nTop CSV API exports XY or XYZ
coordinates and full control provenance with round-trip float precision.

The native full 3D controller owns the active outer state. It prepares local
heat-transfer and transport inputs, runs the selected thermal route, captures
its evidence and checks convergence. A nonconverged step refreshes A flow,
thermal properties and B flow in that order.

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

The native full 2D controller completes both flow calls before it propagates
failures. It prepares thermal inputs, solves the selected energy route,
validates the return, refreshes properties and checks convergence.
Richardson retains the inputs of the last main thermal call, including when
a final property update follows it.

Per-call thermal inputs
borrow arrays, while display smoothing stays separate from raw evidence. Nonfinite thermal returns fail before property refresh or result capture. The unreachable NaN-to-inlet replacement and its `energy_nan_hit` state and
new-result diagnostic are retired. Existing saved diagnostic dictionaries
stay readable without rewriting their historical values. True-h duty comes
from recorded face mass/enthalpy fluxes. The previous scalar-pressure h(T) option
is kept only as an independent test reference.

Thermal routes are selected by their present qualification conditions:

| Route | Shared implementation and kept differences |
|---|---|
| True enthalpy | Pairs containing CO2 or sCO2 use signed mass/enthalpy transport for uniform and continuous geometry. The 2D adapter calls the shared 3D enthalpy kernel. Full3D CC uses the kept G4 two-sweep warm-up before the selected enthalpy solve. Discrete-zone and offset constraints stay. |
| Model enthalpy | Existing air/water h(T) transport. 2D includes water/water when unzoned and symmetric. Native 3D includes every ordered air/water pair with Nz>1, variable properties, two solved sides and conservative transport. Water/water and asymmetric geometry use the strict boundary contract. |
| Temperature | The native fullCC air/water candidate reuses strict integral-h(T) model-h drivers while keeping the requested temperature route. QD/standalone fixed-coefficient, staggered research and private single-A sCO2 routes keep their separately stated contracts. |

Full3D true-h keeps its original two temperature sweeps before each enthalpy call.
The staggered warm-up uses caller relaxation and live serial SOU corrections.
Red-black warm-up freezes those corrections for one sweep.
The solid keeps the original exterior self terms in its iteration diagonal.
These terms have zero wall heat flux. Standalone temperature keeps its own
block schedule and convergence checks. The warm-up does not certify true-h
convergence; the selected enthalpy driver applies its original physical gates.

The CO2/sCO2 restrictions apply to geometry combinations, not the other stream's fluid.
Either stream can be in A or B. Public configuration rejects discrete
zones and nonzero level-set offset when either stream is CO2/sCO2. Each stream
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
evaluated from the temperature unknown on each shared internal face.
A pressure-dependent enthalpy difference is not itself a temperature gradient.
Both production adapters require fresh fluid and solid equation residuals.
These residuals use each side's selected energy relation and conductivity.
The largest per-phase sum of absolute cell residuals must be <=0.001 of
`max(abs(Q_A), abs(Q_B), 1)` in native units. The boundary energy imbalance must
meet the same limit.

The optional normalized enthalpy-update gate stays separate from the Kelvin gate.
The true-h ledger records actual settings, residual budgets and exit reason.
Historical clip and table fields keep their original meaning when old results are read.
Current T-SOU uses checked PT updates; it does not perform H-to-T inversion,
enthalpy clipping, BICUBIC initialization or HEOS finishing iterations.

Each native EOS evaluator uses one HEOS state for PT checks and property reads.
Water and CO2 guards update that state before its HEOS properties are read.
Integral air/water energy properties come from the existing model resource.
This removes a duplicate PT update within the same call.
All phase, melting, pressure and corrected H/P checks remain at their existing locations.
Air and sCO2 domain checks do not add HEOS updates.
Water transport keeps its existing separate physical check.
Mathematical enthalpy brackets keep their separate validation contract.

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
B residual. Native 3D water/water and asymmetric air/water runs use this strict
path under the model-h selection conditions above. They consume completed
SIMPLE mass faces without the former capacity-flux projection.
Their results record the strict face algorithm, common physical ledger and
model-h reporting audit. The original non-strict model-h boundary rule stays
active for symmetric air/air, air/water and water/air runs.
Explicit fixed-capacity, prescribed-side and research consumers retain their
separate contracts. Applicability and optimizer eligibility remain separate checks.

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
Capture does not infer diagnostic ownership from value types. The native 2D binding
passes display/flow fields, native evidence, application data and diagnostics
separately to shared capture. The flattened intermediate dictionary and optional
native-capture switch are retired. Native evidence is always recorded, and
absent display-velocity copies retain their existing diagnostic placeholders.
The 3D backend
passes its problem, outer state, reporting metrics and diagnostics directly to
`FieldResult` capture. Its flattened intermediate dictionary and public
dictionary entry are retired. Optional audit exports and absent-field
diagnostic placeholders retain their contracts. Final report diagnostics stay
separate from the detached last-thermal snapshot. Reporting references
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
P-squared update in `native/src/pressure_reference.cpp`. A positive 1D estimate above
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

<a id="native-3d-continuation"></a>

### Native 2D and 3D continuation

`Full3DRun.advance_step` completes one SIMPLE step, thermal block, or controller transition.
The existing one-shot entry uses these same steps.
The original `advance` operation still returns at a complete initialization or outer boundary.
Both operations use one numerical implementation.
Snapshots also cover initial and post-update SIMPLE calls on either side.
They retain F2 confirmation, stall history, pressure construction state, and the current iteration result.
Restore rebuilds each pressure hierarchy from its original construction matrix.
Coarse bootstrap stays atomic before the first fine SIMPLE boundary.

Thermal snapshots cover model-h selections, original temperature chunks, and complete EOS Picard iterations.
They retain active Anderson history, HEOS finishing state, and actual projected face velocities.
The planar integral delegate keeps its physical depth conversion.
The private single-A sCO2 and true-h CC warm-up owner retains its original temperature rows.
Its former stack loop and unused private one-shot entry are removed.
Water startup retries retain the initial fields, rejected attempts, remaining budget, and actual call settings.
Restore does not repeat a completed retry or reset its charged iterations.
Active component records reuse the controller solution arrays. Restore uses those arrays to rebuild component views.
The controller preserves A flow, thermal property refresh, then B flow.
Completed thermal evidence stays separate from later flow updates, including the final capped post update.
Snapshots and re-entry are rejected while a step is unfinished.

`Full2DRun.advance_step` completes a paired SIMPLE step, thermal selection, or controller transition.
Two side workers stay active through each flow call.
The operation returns after both current steps complete.
The existing `advance` and one-shot entries drain the same flow owners concurrently, without a barrier after each SIMPLE step.
Snapshots retain each side's active pressure and F2 state, including a side that has already finished.
The previous completed flow stays separate until both new flow calls finish.
Pressure shooting keeps the reference chosen for the current outer call.
Main thermal snapshots retain model-h selection history or the complete EOS iteration state.
Refinement snapshots own the actual fine grid, interpolated inputs, prolonged mass faces, and active thermal state.
Restore rebuilds views and immutable inputs. It does not repeat interpolation, property observations, or charged iterations.
The original capped property update, refinement budgets, and result capture remain in the controller.
The former stack-only flow, main thermal, and refinement loops are removed.
Both dimensions use the shared typed archive in `full_run_state.cpp`.

`full_2d_run_c_api.h` and `full_3d_run_c_api.h` expose owned run and snapshot handles.
The C entry copies prepared arrays and the callback table.
The caller keeps callback functions and their context alive until run release.
Snapshot fields own their numeric arrays and UTF-8 strings.
The additive `advance_step_v1` entries expose inner boundaries in both dimensions.
Native state format 2 records these states.
Restore requires the same format, native build, platform, prepared input, and numerical controls.
Each native build receives a new identity. Host paths, callback addresses, and runtime thread limits are excluded.
A cancelled or failed run cannot publish a new snapshot.
The result is transferred once; its views remain valid until result release.

`RunControl.cpu_threads` is an optional positive runtime limit. It is not a physical or numerical input.
The native default is at most eight logical CPUs on the host. Explicit requests are capped by that availability.
The temperature energy driver partitions independent cells and gives each worker separate ordinary and trial EOS objects.
It caps the property worker count by the cell count. Maxima are combined after all workers finish.
With two available threads, each temperature sweep runs its independent fluids together, then runs the solid sweep.
Each fluid keeps its cell order. A one-thread budget keeps sequential fluid sweeps. Final audits keep their original order.
The owner alone polls callbacks. Ordinary updates finish before a callback can observe them; trial callbacks see the retained ordinary state.
All workers finish before an exception leaves the call. A one-thread budget also serializes the existing paired 2D flow calls.
`runtime_resources` records the applied limit separately from numerical method evidence. Saved run status records the requested limit.
Full 2D entry v6 and full 3D entry v5 accept the budget without changing result layouts.
Owned 2D create/restore v2 and owned 3D create/restore v3 carry the same budget.
The earlier entries and their binding branches remain for retained run libraries and direct C callers.
They can be removed only after those consumers no longer require them. An old library rejects an explicit thread limit that it cannot apply.

The public solver entry and native Python binding accept `checkpoint`, `checkpoint_due`, and `resume_state` keyword arguments.
`checkpoint` receives detached typed fields at an available boundary.
An optional `checkpoint_due` predicate prevents state export when no save is due.
`SolverCheckpoint` stores those fields with the absolute prepared-case path and model references.
Use `full_2d_continuation_v1` for 2D state; 3D retains `full_3d_continuation_v1`.
The functions in `io/solver_checkpoint_io.py` use the existing typed HDF5 record writer.
The writer closes a temporary file before atomic replacement.
A failed write or process interruption before replacement preserves the previous checkpoint.
This contract does not claim recovery from power loss.

`workflows.recovery` uses the existing `workflows.compute` stages for start and resume.
Each run owns a new directory with prepared input, a retained native library, checkpoint, and status.
Each run retains its own library file. The process reuses a previously retained file only when its bytes match the selected library.
This avoids repeated native initialization and retained property tables. A changed or moved runtime uses the new retained file.
The run record identifies the file used for execution. Completed results and metrics are written only after postprocessing.
`compute_prepared_run` uses supplied `CaseData` without repeating preparation.
If a later stage fails, `failed-result.h5` keeps completed solver fields when no result pair was published.
The original exception stays active if saving those fields or recording status also fails.
Resume reads the saved `CaseData`; it does not repeat preparation or change the source run.
The complete directory can move. Its local input replaces the previous absolute case path during loading.
Native restore still verifies the prepared input, controls, format, platform, and build.
The caller selects a native library explicitly. The workflow does not load a saved library implicitly.

`PausedRun` reports a saved checkpoint separately from cancellation, failure, and completed results.
CLI saved runs convert Ctrl+C into a pause request and return code 3 after saving.
The Qt orchestrator has a separate pause signal and retains the previous accepted result.
GUI resume preserves saved input provenance without changing the current draft.
A CLI-origin run has no GUI preset and cannot replace the draft through recent-run loading.

This stage covers native 2D and 3D inner and outer boundaries, including 2D thermal refinement.
The CLI interval is explicit. New GUI full C++ runs request a save every 60 seconds.
They capture input provenance on the GUI thread and use a new directory under the existing user data directory.
GUI resume uses the recorded interval. A failed start clears the pending directory and provenance.
The longest complete step or bootstrap limits when saving can occur.
Saving frequency and full timing, memory, and desktop acceptance remain separate checks.

### Cooperative cancellation

Full native entry points do cancellation checks before they prepare execution inputs or load a native library. Host-selection validation still applies.
A valid pre-cancelled request raises `CancelledError`, including when the selected
absolute library path does not exist. An uncancelled missing-library request
keeps its original error.

Workflows, solvers and the GUI orchestrator share `domain.cancellation.CancelledError`.
It is an `InterruptedError` subclass, also available through `ComputeOrchestrator.CancelledError`.
Only explicit cancellation checkpoints raise it. Unrelated exceptions stay
errors even when a cancellation request is pending. Both SIMPLE workers are
joined before propagation, with real failures taking precedence over cancellation.
The orchestrator handles this exception directly as its cancelled terminal state.
The GUI adapter binds workflow controls and keeps the original exception.

2D polls each SIMPLE iteration and at the existing LTNE chunk boundaries,
including the Richardson refined solve. 3D polls each SIMPLE iteration and
between its momentum sweeps, pressure solve, and correction. A request during
one of these calls stops before starting the next kernel. Its LTNE
chunk boundaries remain unchanged. The shared true-enthalpy driver
polls each property/sweep iteration. Each active operation must finish before its next checkpoint. These operations
include native linear solves, LTNE chunks, and enthalpy property/sweep iterations.
Chunk sizes depend on the selected route and controls.

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

`ui/background_tasks.py` prepares 3D modules in one window-owned QThread.
Result display, optimization preview, and optional preinitialization share that preparation.
Queued GUI callbacks create widgets and render the current data after imports finish.
Compute controls stay locked until result publication and display finish.
Close, restart, workspace changes, and CPU controls use the existing task-lifetime gate.
An import error keeps numerical results available for export and marks the view unavailable.
Widget creation, font setup, Matplotlib, and OpenGL stay on the GUI thread.

The result footer and history format scalar values from the published result.
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
10. **True-enthalpy ownership.** Any ordered fluid pair containing CO2 or sCO2 uses
    the conservative enthalpy kernel. It consumes SIMPLE's signed staggered
    face mass flows and computes duty from boundary enthalpy fluxes. It must
    not reconstruct a full-face x-flow from a scalar mass rate. The shared kernel requires both face-flow tuples explicitly.

    Uniform-flow
    construction for numerical reference tests lives only in the test helpers. Each sCO2 side in 2D/3D uses the shared property-wrapper range
    **280–700 K, 7.9–16 MPa absolute**, at inlets and actual local states. The 2026-09-09 pressure-floor extension leaves the EOS backend and the
    independent Nu/D-F applicability and acceptance gates unchanged. It does
    not show experimental accuracy in the added range. T-SOU uses checked HEOS PT updates.
    The kept CO2 model reference uses HEOS. Full 3D T-SOU accepts the existing dispersion inputs.
    Integral air/water sides keep outer effective conductivity, including dispersion.
    EOS sides keep local EOS conductivity. The warm-up keeps its dispersion term.
    Historical `enthalpy_eos` and `sco2_enthalpy_eos` records remain readable with their original meaning.
    Current T-SOU does not create table-use evidence. This algorithm change does not alter experimental calibration.

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
11. **Current TM1 limit.** CO2/sCO2 discrete zones and offset level sets stay rejected; symmetric continuous fields are supported. Air/water-only runs keep the qualified model-enthalpy and temperature
    routes listed above. For Nz>1, their end-cell treatment covers each
    physical fluid and solid end control volume. Tin is imposed at the open
    inlet face with half-cell conduction.

    Outlet zero-gradient applies at the external face. Explicit CC callers
    with SIMPLE supply actual inlet capacity transport. They keep the CC interior scheme. Prescribed B stays an external thermal reservoir.
12. **Experiment-correction applicability.** The air core-specimen branch uses
    L=6..8 mm, t=0.3..0.5 mm interpolation. t=0.6 mm uses the separate HX campaign. sCO2 uses only D/G-7-6 hot-side `ok_dp` evidence, keeps K=K0, and is
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

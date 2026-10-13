# Unified steady single-phase solver design

[中文](unified-solver.zh-CN.md) | [English](unified-solver.md)

Status: authorized target design, 2026-10-13. Implementation and acceptance have separate node records.
The source baseline is `c96a3e8117af570c70dd7a13c3d1959ff2aa3396`.
The [current architecture](architecture.md) remains the description of delivered behavior.
Local measurements and the task ledger stay in ignored `.cache/`.

## 1. Scope and decisions

- Use one C++ solve system for the existing steady single-phase models.
- Keep independent physical implementations for each fluid side.
- Improve complete single-case time before increasing batch concurrency.
- Continue a long case from saved iteration state in a new process.
- Keep Python as the existing numerical reference and development backend.
- Keep macOS arm64, Windows x64, and the current public backend selection.
- Keep inputs, runs, checkpoints, and results associated with their project.
- Keep current GUI input and result flows where their behavior remains valid.

Transient and two-phase equations are outside this change.
The task does not change calibration coefficients or raw data.
New numerical methods are implemented in C++. Python callers and file readers change when the interface requires it.
The [collaboration workflow](collaboration.md) applies to each implementation PR.

## 2. Three separate decisions

| Decision | Recorded meaning | Selection rule |
| --- | --- | --- |
| Physical model | Transport properties, energy relation, pressure sampling, Nu and D-F closures, resources, limits | Resolve each side explicitly. Keep its actual physical meaning during migration. |
| Numerical method | H or T unknown, face reconstruction, iteration order, linear solver, update and conservation gates | Compare at fixed physical definitions before changing a default. |
| Execution policy | Thread budget, property evaluation method, progress, cancellation, save and resume | Improve elapsed time within the accepted numerical and physical limits. |

`model-h` uses the selected integral h(T) relation. `true-h` uses the selected EOS h(T,P) relation.
These physical relations remain distinct within the common solve system.
The H/T unknown and FOU/SOU face rule are separate numerical choices.
Current model-h SOU reconstructs temperature before h(T). True-h SOU reconstructs enthalpy.
Their common SOU label does not establish numerical equivalence.

Current transport and energy properties can use different implementations on one side.
For example, a true-h pair uses EOS energy states while air/water transport keeps its recorded transport model.
Record both implementations and their pressure sampling.
Do not infer a single property implementation from the fluid name.

Initially, the prepared execution specification makes the existing route choices explicit.
Later, N12/N29 establish qualified per-fluid defaults that do not depend on the other side's fluid.
The air/water default energy relation needs the N08-N11 comparison evidence.
A new table approximates its selected physical relation; it does not select a different relation.

## 3. Responsibilities and ownership

| Responsibility | Existing code to use | Target boundary |
| --- | --- | --- |
| Prepare and execute a case | `preprocess/api.py`, `workflows/compute.py`, `solvers/api.py` | One prepared case and explicit run controls reach the selected backend. |
| Resolve side physics | `native/src/fluid_properties.cpp`, `enthalpy_eos.cpp`, generated coefficients | Resolve the actual transport, energy and closure implementations before cell loops. |
| Assemble conservative equations | `energy_fv_rows.hpp`, `conservative_energy.cpp`, current thermal drivers | Share face and cell operations. Keep required dimensional and reconstruction differences explicit. |
| Advance the coupled solve | `native/src/full_2d.cpp`, `full_3d.cpp` | A run owns a phase cursor, iteration budgets and mutable state. |
| Check physical quality | Existing SIMPLE F2, thermal ledgers, range observations and postprocessing certificates | Use evidence from identified states and record each verdict separately. |
| Save and restore | `io/hdf5_data.py`, prepared-case and result storage | Python writes owned typed snapshots. C++ exports and restores numerical state. |
| Serve consumers | Full C APIs, Python bindings, GUI, CLI, optimization and offline readers | Keep useful public entry points and migrate their implementations and consumers together. |

Paths in this table are relative to the package or repository as applicable.
No new dependency is required by this design.
Keep numerical kernels free of Qt and file-system policy.
Use contiguous existing arrays where their layout meets the consumer contract.
Each run owns mutable EOS objects and solver workspaces.
Share immutable data only after its thread-safety and memory costs are established.

### Inputs, working state and results

The prepared case owns immutable physical inputs, grid data, model resources and resolved settings.
Runtime callbacks and host paths remain outside its persistent physical identity.
The run owns arrays and histories used by subsequent iterations.
An exported snapshot owns its data and cannot alias an active writer.
The published result owns the accepted evidence or the explicitly unqualified completed evidence.
Draft GUI changes do not change that result's source.

The common controller must initially keep the current phase order:

| Route | Current order to preserve during structural migration |
| --- | --- |
| 2D | Initialize; solve both flows; prepare and solve heat; refresh properties; check outer convergence; apply required post-update; refine and finalize. |
| 3D | Initialize flows; prepare and solve heat; save thermal evidence; check outer convergence; apply property, flow and pressure post-updates when required; finalize. |

2D already runs independent A/B flow solves concurrently.
3D currently keeps per-run flow solvers, property evaluators and thermal workspaces.
Neither fact establishes a general thread policy or restart contract.
Do not change iteration order as an incidental effect of moving code.

### Controller operations

The C++ controller provides create, advance, snapshot, restore, finish and release operations.
Advance completes a specified amount of work and returns at an identified safe boundary.
Its status distinguishes running, paused, cancelled, failed and completed execution.
Finish produces a result only under the existing completed-result contract.
The ordinary solve entry repeatedly advances this same controller.
Python schedules work and transports snapshots; numerical phase selection remains in C++.

Use an opaque run handle at the C boundary. Version the new state-transfer interface.
Copy snapshot arrays into owned storage before the run can advance again.
Keep one release operation for each exported owner; borrowed views cannot outlive that owner.
Existing useful one-call C entry points use the common controller after migration.
Their callers do not keep a second numerical implementation.
Confirm concrete symbol names and layouts in A03 with a C caller and the Python binding.

## 4. Checkpoint contract

A checkpoint continues the current run. It is not a completed `FieldResult`.
The first supported restore contract requires a matching native build, state schema, physical resources and numerical settings.
Each supported platform must pass its own restart tests.
Cross-build and cross-platform checkpoint conversion is outside the first implementation.
Old input files can still start a new qualified calculation with a new execution record.

### State that must be saved

| State group | Required content |
| --- | --- |
| Identity and layout | Prepared inputs or their exact local reference, model versions, units, dimensions, coordinates, phase labels, algorithm and state-schema versions. |
| Continuation cursor | Active phase, side, grid level, outer/thermal/SIMPLE iteration positions, consumed budgets and the next operation. |
| Physical fields | Required T/h, velocity, pressure/correction, density, transport coefficients, boundary mass targets and pressure anchors. |
| Convergence state | Previous fields, update measurements, F2 confirmation streak, stall window and comparison snapshots when a SIMPLE call is active. |
| Acceleration state | Required thermal and outer Anderson samples, scales, residual minimum, patience counters and reset state. |
| Property iteration state | Actual physical implementation and approximation policy, including the irreversible HEOS finishing choice within the current thermal solve. |
| Evidence | Completed iteration records and separately identified last-thermal and current-flow evidence. |

The initial source inventory identifies these continuation owners:

- `full_2d.cpp`: flow/thermal state, previous temperatures, relaxed properties, outer history and refinement position.
- `full_3d.cpp`: `Runtime` arrays, flow solvers, pressure anchors, previous temperatures and distinct thermal evidence.
- `simple_convergence.hpp`: F2 previous velocities, confirmation streak and stall-window state during an active solve.
- `model_h_common.hpp` and `outer_anderson.cpp`: sample queues, scales, minimum residual and patience state.
- `enthalpy_driver.cpp`: thermal iteration position, acceleration history and the `heos_polish` transition.

Determine exact array membership from reads after each restore boundary.
Rebuild derived matrices, preconditioners and EOS objects only where this preserves the specified continuation behavior.
Do not serialize native pointers, callbacks, threads or object memory layouts.
Do not reset consumed iterations or convergence history on restore.
Retain the finite-value rules for each field; diagnostic NaN values are distinct from invalid physical fields.

### Save boundaries and publication

Use complete outer coupling steps, thermal iteration blocks and SIMPLE iteration steps as candidate safe boundaries.
Save a SIMPLE step only after its required density and boundary updates are complete.
Do not save a partial cell sweep or linear solve as a complete step.
Record any coarse initialization that must finish before its first safe snapshot.
Measure the longest interval between safe boundaries and the work lost after interruption.

Use the existing typed HDF5 array storage and sibling temporary-file publisher where applicable.
Add a checkpoint record kind and state-schema validation.
Publish only a complete snapshot. A failed write must leave the previous valid checkpoint available.
Report save errors with the original execution status.
Cancellation and incomplete checkpoints must not replace a previously published accepted result.
Process-interruption tests are required; atomic rename alone is not evidence of power-loss durability.

Select periodic save intervals from measured snapshot cost and lost-work exposure.
Add asynchronous writing only if measurement justifies its extra memory and ownership cost.

## 5. Common quality and performance rules

Keep execution completion, convergence, applicability, metric availability and design eligibility separate.
Each verdict identifies its source state and definition version.
Keep final SIMPLE evidence separate from thermal evidence saved before a later failed post-update.
An incomplete boundary ledger is not a zero residual.
Keep signed advective and diffusive powers, sources, phase residuals and normalization scales.
2D quantities keep W/m and per-unit-depth mass flow. 3D quantities keep their physical units.
Existing stricter formula and replay checks remain in force.

The agreed correlation policy checks the inlet and all final local states where a correlation is actually used.
Each limited parameter may extend at most 10% beyond its own applicable boundary.
For a positive interval [L,U], this permits [0.9L,1.1U].
Zero or signed bounds require an explicit domain rule; do not invent a relative denominator.
This is not a fraction of cells, a clamp, an EOS extension or an interpolation-error allowance.
Intermediate observations remain diagnostic. Final design eligibility uses the required final local evaluation.
Keep geometry, campaign, phase and hard property-domain restrictions separate.
The user confirmed that N06 uses the original calibration or correlation validity range as its 10% reference.
Previous wider application allowances do not qualify an out-of-range design or optimization candidate.
Keep those historical results as explicitly identified diagnostic evidence.
For example, the water HX calibration lower velocity bound of 0.10 m/s becomes 0.09 m/s under this rule.
The former lower application bounds of approximately 0.014-0.016 m/s do not override this decision.

N08-N11 set the common accuracy budget using fixed-model comparisons and at least three complete grids for the primary cases.
Existing thermal-only Richardson refinement does not replace full flow-and-heat grid refinement.
Keep discretization, iteration, interpolation and experiment errors separate.
An experimental comparison keeps its fixed coefficients and data membership.

For performance, first measure complete single-case time and stage costs.
Reuse the existing state reuse and shared energy operations before adding another mechanism.
Evaluate table interpolation, fewer nonlinear/linear iterations, workspace reuse and valid parallel work against the observed bottleneck.
Keep direct EOS checks and any required exact-EOS finishing in the measured solve.
Use independent mutable property states for concurrent work.
Use one resource budget for case threads and batch concurrency.
Record wall time, CPU time, peak RSS, initialization, table costs and save/restore costs.
Separate empty-cache, retained-cache new-process and repeated warm solves.
Compare both the same grid and the total cost to reach the same accepted accuracy.
Choose defaults from qualified complete results, not property-call microbenchmarks.

## 6. Consumer and retirement map

| Existing item | Consumer and required behavior | Retirement condition |
| --- | --- | --- |
| Full 2D/3D controllers | C APIs, bindings, public run API, GUI, CLI, batches and validation | The new controller covers each supported phase, failure and evidence contract; move callers and remove replaced drivers in the same PR. |
| Model-h and true-h loops | Full solves and direct numerical tests | Shared core has equivalent recorded physics and required distinct schemes; move tests before deleting exclusive loops. |
| Temperature kernels | Quick Design, standalone calls, true-h warm-up, single-A and research consumers | Migrate each actual consumer with its physical meaning and acceptance. Keep required operations while those consumers remain. |
| SIMPLE 2D/3D kernels | Complete flow solves and standalone contracts | Keep dimension-specific operations. Only replace duplicated control after both consumers pass. |
| Python backend | Reference, existing GUI/CLI and tests | Keep as a supported backend. No retirement is planned. |
| Historical file readers | Saved cases, results, sessions, exports and optimization records | Keep valid reads and definition versions; report incompatible reruns explicitly. |
| Build and binding lists | Native C/C++ callers, ctypes layouts and platform packages | Update symbols, ownership, versions and packaged artifacts in the same change as the interface. |

Check public headers, documented external examples and actual known consumers before removing an entry point.
Unknown external use does not justify keeping a duplicate numerical engine.
Keep a retained item's consumer, reason and removal condition in the task record.
Detailed search results and source locations stay in the private evidence directory.

## 7. Ordered task nodes

| Stage | Nodes and work | Exit condition |
| --- | --- | --- |
| Baseline | N01 environment/source/native identity; N02 directory/configuration/routes/consumers; N03 frozen cases and complete measurements | Reproducible inputs, actual execution identity, recorded gates and performance evidence. |
| Architecture | A01 requirements; A02 boundaries/ownership/interfaces; R01 restart state contract | Explicit reuse, replacement, state membership and restore boundaries. |
| Quality | N04 physical/numerical execution records; N05 physical ledgers; N06 range policy; N07 shared result verdicts | Consumers use consistent definitions and state-specific evidence. |
| Accuracy | N08 H-FOU/T-FOU; N09 T-FOU/T-SOU; N10 iteration/full-grid studies; N11 error budgets | Supported accuracy recommendations and a qualified reference. |
| Design trial | A03 representative end-to-end trial; A04 whole review | Demonstrated physical coverage, state ownership and migration feasibility. |
| Common core | N12 side physics; N13 conservative operations; N14 numerical parts; N15 controller migration/retirement | One solve system with complete consumer and retirement evidence. |
| Resume | R02 state save/restore; R03 workflow and GUI/CLI integration; R04 restart/failure/performance checks | New-process continuation meets the same result and quality requirements. |
| Single-case speed | N16 repeated work; N17 property tables; N20 iteration/linear solve; N18 parallel work; N21 candidate combinations | Repeated complete-run gains within the accepted accuracy and resource limits. |
| Consumers | N22 input paths; N23 C API/bindings/builds; N24 optimization/postprocess/export; N25 historical read/rerun | Complete project input/run/result handoff and compatible consumers. |
| Batch speed | N19 measured concurrency and recovery | More qualified cases per unit time within one resource budget. |
| Qualification | N26 full case coverage; N27 experiments; N28 both desktops and recovery; N29 C++ internal defaults | Separate numerical, experimental, performance and application verdicts. |
| Delivery | N30 review/PR CI/merge; N31 main CI/synchronization; N32 recoverable archive and retirement | Required checks and cleanup have direct evidence. |

N30/N31 apply to every implementation PR. Interface callers, tests, fixtures, configuration, exports and documentation change with their owning PR.
The later consumer stage is a complete integration check, not permission to leave an earlier caller broken.
The order within single-case optimization follows the measured bottleneck.
CI cost changes follow the solver and recovery work; they do not reduce required solver acceptance.

## 8. Baseline and acceptance matrix

Freeze all 16 ordered pairs of air, water, CO2 and sCO2 in both dimensions.
An input that passes preparation still needs numerical and applicability checks.
Use CO2-air, sCO2-water, water-air and water-CO2 as the primary paired families in 2D and 3D.
Keep air-air model-h controls and the existing 30x10x10 partial-port true-h and temperature-SOU cases.
Add A/B swaps, nonuniform grids, partial ports, supported directions and valid domain-boundary cases at the relevant nodes.
Mark Python-unsupported numerical candidates explicitly; compare them to a qualified same-physics reference.
Do not calculate a backend speed ratio across different algorithms.

For the initial structural baseline, keep the existing engineering comparison limits: 0.01 K for temperatures and 0.1% for Q, pressure and flow.
These are backend comparison limits, not the final discretization-error or experiment-accuracy target.
Require each backend's existing physical gates independently.
N11 supplies later accuracy budgets from the reference studies.

Restore acceptance includes uninterrupted versus interrupted runs, new-process restore, multiple save points, exhausted budgets and invalid state rejection.
Also test write failure, process interruption during publication, cancellation, original-error retention and unchanged accepted GUI results.
Repeat affected restore checks after changing iteration order or parallel work.
Measure save/reload time and checkpoint memory/disk cost.
Do not require bitwise equality across different floating-point execution orders; use the accepted numerical criteria and record the differences.

## 9. Decisions that need evidence

N11 recommends numerical and property-approximation error budgets before requesting an engineering tradeoff.
N12/N29 recommend per-fluid physical defaults when the current definitions differ.
R01/R04 recommend save intervals after measuring the longest step and snapshot cost.
The original-range rule in section 5 resolves N06's conflict with the previous wider empirical application allowance.
Bring evidence, options and a recommendation when another physical decision remains unresolved by the current model documents.
Continue independent authorized work while a physical decision is pending.

Record each node as not started, running, waiting on a named condition, verified, or delivered.
Record its owner, tested commit, runtime, evidence, remaining conditions and next action.
The shared PR carries the handoff; private paths and numerical reports remain local.

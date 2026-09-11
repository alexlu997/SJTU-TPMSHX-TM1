# TM1 takeover and repair record — 2026-09-10

The user requested implementation of all findings in the takeover review.
The final objective remains M-A three-module independence and V0.1 M-B
tracking. The source plan, its 45 nodes and 110 dependencies are preserved;
the copied task cards describe requirements, not delivery evidence.

This directory's `state/*.json` records execution after takeover. The original
Downloads package remains a planning reference. The previous Codex task
`01a0871b-3d91-7c53-9f89-053a5a346b7f` remains historical evidence; this task
`01a08af6-c928-75a1-ba06-ba522bbd97a0` coordinates the requested repairs.

## Baseline and ownership

- Original numerical baseline: `5f1cafb0c7e461a8c30a8ea96920ce03a828e412`.
- TM1 main: `c7f013869e7127b35ac0c305376c13b3a834131b` (PRs 1–5 merged).
- Original PR 6: `c8cfb4664b3f1667e09fdf86f86f09445de2651c`, open and retained.
- Main CI run `34465137939`: success. PR 6 run `34465172896`: success.
  These are fast-subset CI results, not M-A acceptance.
- All six original TM1 worktrees were clean at takeover. The original
  SJTU-TPMSHX checkout and V2 remain read-only; TM1 changes never merge there.
- G10 repairs start in `codex/tm1/g10-repair`. The controller is the sole
  current writer. Node ownership from the original graph remains in force;
  old shared numerical files are changed only at their integration steps.
- One local numerical job at a time. No shared environment rebuild or
  dependency installation is included in an ordinary source patch.

## Corrections to earlier progress claims

PR 6 replays the old complete pipeline and ignores prepared grids, design
fields and model references. It is not independent solving. Its summary-only
conversion loses model metadata and cannot support independent postprocessing.
Its 2D heat-duty label must be W/m, not W. It has no production application
callers. The original implementation remains on its branch as review evidence;
it must not be merged as M-A delivery.

G10, E00 and B20/B30/B40 have useful partial work, not complete acceptance.
The new state records reopen only these affected baseline/contract tasks;
no node is marked done on the strength of an earlier summary or a merged PR.
M-A and M-B remain incomplete. Promises to keep working and repeated unchanged
CI snapshots are not implementation evidence.

## Evidence retained

- B20/B30 observation tables and their original inputs and budgets.
- B40 frozen regression: 4 failures out of 4, with original pins/tolerances.
- B30 NaN enthalpy diagnostics and 2D/3D mixed-fluid nonconvergence.
- Historical 3D adapter run without a verified native exit: unverified.
- Main run `34462326406` at `44cd551`: cancelled, never counted as success.

Repair order follows the graph: G10 and baseline/CI gaps, model and module
leaves, dimensional/application integration, formal file and independent
process verification, application routing, then Z00. M-B retains its original
required and staged capabilities; no requirement is removed to fit existing code.

## Shared model extraction ownership

The sole controller coordinates M00 with the I55 source reconnection in
`codex/tm1/m00-repair`. This bounded integration moves the existing pure model
implementations to `models` and reconnects their existing public module paths;
there is no second formula implementation. Numerical kernels and thread
initialization retain their existing behavior. This is partial M00/I55 work,
not acceptance of either node or of dependent module integration.

## 2D preparation extraction ownership

The sole controller coordinates P20 with I20 and the remaining I55 pure helper
moves in `codex/tm1/p20-repair`. The integration extracts input preparation and
grid construction from the old pipeline and reconnects the old stage entry
points to these same functions. Numerical SIMPLE construction remains runtime
work. Shared grid primitives and sigmoid model extraction retain existing
formulas, grid rules and the existing default geometry-cache location.

## Prepared-only 2D execution ownership

The controller coordinates S20, R20 and I20 in `codex/tm1/s20-repair`.
The old runtime closure and coupling implementation move to the Python backend;
old pipeline imports delegate to it. Prepared execution receives physical grids
explicitly and cannot call preprocessing. R20 captures raw thermal, mass-flux
and pressure evidence at its producer, preserving display copies separately.

The same coordinated integration also owns H10's first 2D implementation and
the shared `result_math.py` extraction. Data-only outlet/duty/pressure helpers
are moved once and re-exported to existing numerical callers. The true-h kernel
adds its native h/face state to returned evidence, without changing its solve.

## 3D integration ownership

The controller coordinates P30/S30/R30/I30 and the required I55 helper moves
in `codex/tm1/s30-repair`. Pure grid/coordinate/geometry functions move once;
existing paths re-export them. The Python backend receives the prepared grid,
design and physical inputs, and its runtime construction cannot call the
preprocessor. Existing scalar and unit-depth application conventions remain
separate until their public application adapters are connected.

## File and independent-process integration ownership

The controller coordinates D10/D20/E00/Q10 and the necessary A10/I51/I56
public entry points in `codex/tm1/io-repair`. The shared HDF5 data codec is
used by both actual record types; normal files never contain Python objects.
The workflow only dispatches public preparation, execution and evaluation.
Real file and three-process acceptance is recorded under V20/V30; the separate
minimal-install CI acceptance remains pending.

The same file-boundary integration coordinates H20 export/report code and the
shared run-environment snapshot required by D10/V20/V30. Environment overrides
are recorded in prepared data and read per execution; no process-global
mutation is used to replay a Case. The user explicitly authorized the new
73-package local environment, which passed exact-lock and pip checks.

## Application control integration ownership

The controller coordinates G10/A20/I51/I52 control changes. The user explicitly
authorized local commits for this class of repair; controls were committed as
`ebec9db`. RunControl gains non-persistent
iteration-label and residual callbacks required by the existing GUI. The
Python backend emits the same existing iteration/residual observations;
CaseData and FieldResult cannot contain those callbacks. GUI buffer ownership
stays in the GUI adapter. No numerical stopping rule changes.

## Public application adapter ownership

`codex/tm1/apps-repair` coordinates A20/I51/I52/I56 with the required
R20/R30 evidence fields. The application adapter consumes only FieldResult
and PerformanceResult, maps existing display/diagnostic slots, and does not
invoke legacy pipelines. Backend producers retain the coefficients and zone
statistics needed by existing displays as data. Prepared model notices and
metadata travel with each result. The existing SI-to-legacy zone spelling
conversion moves once to shared models for the numerical and display callers.
I52 also owns the necessary unit-label, history, overview, CSV and 3D
temperature-label corrections in the existing GUI files. A completed 3D run
must refresh the same Kelvin outlet cache as 2D; otherwise a subsequent unit
toggle can resurrect the preceding 2D temperatures. Display changes do not
recompute engineering metrics or alter current solver inputs.

## Quick-design mode integration ownership

`codex/tm1/quick-design-repair` coordinates S40/A40/I54 with its required
G10/M00/H10 public mode, shared closure and result-contract changes. Preparation
owns the actual uniform grid, geometry, initial fields and resolved controls;
the quick-design backend owns the existing plug-flow LTNE passes. Postprocessing
owns the final temperature/duty and analytical pressure-state reductions.
Design retains sizing, constraints, warm-start sequencing and output rules.
The controller also owns the necessary shared D-F explicit-option parameters so
prepared execution preserves the existing method/override/residual-correction
choices without changing process environment. Shared source formulas are moved
or reused once. Other application modes and frozen B40 pins remain unchanged.

### Coordinated screening extraction: S40 / A30 / I40 / I53

The controller continues from 961fbb6 in the isolated optimization-repair branch.
This joint batch owns the old evaluator delegation, pure model projections and
roughness/envelope authorities, prepared SIMPLE inputs, native screening
execution and offline metrics, plus the public parameter/effective-field
examples. G10/D20's coordinated schema consequence is an explicit rejected
result archive (false convergence, reason and known stage); cancellation and
failures remain outside completed archives. The mode schema is documented in
`schemas/three_module_v1/screening.md`. No old B40 pin or tolerance changes.
The current same-source numeric comparison supplements that failed historical
gate; it does not relabel it green. The shared constructor still has legacy
callers in the full-model runtime; their remaining runtime geometry/drag
preparation must be addressed separately before overall M-A acceptance.

### Full-mode preparation continuation: S20 / I20

From f406357, the controller owns the full-preparation-repair worktree and the
necessary G10 Case parameter changes. Full 2D fixed flow coefficients and actual
SIMPLE grids now cross the prepared boundary. Thermal/asymmetric geometry in
both dimensions remains under this continuation. Earlier evidence and B40
failure provenance remain intact; no node is marked complete by this subset.

### Thermal preparation and frozen correction ownership

The same controller continuation coordinates P20/P30/S20/S30/I20/I30,
with the necessary G10/D10 validation and R30 result-capture consequences.
It owns the shared prepared thermal geometry, two-dimensional boundary
openings, three-dimensional initial air exchange, resolved roughness and
experimental correction metadata. Solver-time fluid properties and local Nu
remain numerical work. Supplied three-dimensional K fields remain operative;
only the fixed experimental scale is resolved before execution. Existing
warning tests now inject prepared geometry when constructing synthetic
fixtures. No numerical tolerance or physical applicability is changed.

### V40 real minimal-environment handoff

The controller owns V40's isolation tests and the necessary E00/I55 workflow
extension. A full locked CI environment runs the existing real three-process
tests. A separate minimal environment in the same job then verifies their
offline metrics, with no installed numerical runtime or Qt. Result files stay
on the job-local filesystem; there is no artifact upload. This supplements
artificial I/O tests. Workflow configuration alone is not minimal acceptance.

### P40 explicit offline resources

The controller coordinates P40 with M00's existing data loaders and surrogate
implementation. Optional explicit input paths are added at those existing
authorities; formulas, filters, default legacy source selection and production
coefficients stay unchanged. The offline namespace exposes the existing
cleaners and publishes calibrated points plus source/revision metadata only
to a caller-selected local directory. Water cleaning's obsolete solver import
is redirected to the already extracted shared geometry authority.
The existing sCO2 log-space fit is moved unchanged from its validation report
script to offline preparation; the report delegates to it and keeps all
campaign splits, metrics and publication decisions.

P40's continuation also coordinates G10/S40/A40/I54: quick-design analytical
pressure fractions depend only on prepared geometry and inlet conditions.
Their existing evaluation moves to preparation, keeping selected D-F options
and warnings, so no legacy calibration can be started after a thermal solve.
The solver consumes the two supplied fractions and retains pressure states;
offline pressure reduction is unchanged.

### Z00 documentation continuation

The controller owns README, architecture and architecture acceptance mapping.
The inherited README is retained verbatim as docs/history/v2-readme.md;
current entry-point documentation does not present old headline accuracy as
TM1 acceptance. This is documentation preparation while release gates remain
open, not a done transition for Z00 or its predecessors.
The same documentation pass maintains Z10's V0.1 capability tracking table;
unimplemented M-B providers/backends and undefined engineering metrics remain
explicit gaps. It does not activate or claim completion of those implementations.
H20/I20/I30's real application test also exports and reads every native scalar
field through VTK in the independent postprocess process. The reader explicitly
loads all scalars, rather than its default first scalar only.

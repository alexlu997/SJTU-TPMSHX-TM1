# Optimization public-mode extraction

Local implementation on codex/tm1/optimization-repair, source base
961fbb6edc8ded29e13d80456fc20495c4bd5552. S40/A30/I40/I53 remain running;
independent review, remote CI, merge and the B40 decision remain outstanding.

## Implemented boundary

The 2D and 3D application routes now call public preparation, solve and
postprocess APIs. Pure D-F projection, envelope and roughness authorities were
moved once into models, with historical solver imports delegating to them.
Preparation creates the actual thermal/flow grids, drag, porosity and initial
pressure seeds. Execution consumes those arrays and keeps the original 2D
variable-density B mapping, 3D frozen-B loop, hot reseed and envelope gates.
Native fields, transport, drag, pressure, state and model provenance are
archived. Offline Q, dP and mass reductions use only FieldResult. Objective
signs, manufacturability/caps and 3D physical-depth normalization remain in the
application. See `schemas/three_module_v1/screening.md` for exact supported
fields, units and rejected-run semantics.

## B40 and source comparisons, L2

`optimization-before-extraction.json` records all four unchanged configurations
from test_evaluator_frozen_values.py at 961fbb6. They exactly match the observed
values in B40's original matched-lock failure record, which was inspected again
for this comparison. They do **not** match its old pins. No frozen test or
tolerance is changed, and the historical 4/4 failures remain failures.

The source capture process exited 0. Native Ta/Tb/Ts were copied after every
thermal call into ignored `.cache/tm1-optimization/{case}.npz` (one outer call
per 2D case, two per 3D case). Both after-extraction comparison processes exited
0: all twelve scalar outputs exactly equal the before values; all **12 final
native temperature arrays are element-by-element equal**. Comparison assertions
used rtol=1e-12 for scalar values and array_equal for native temperatures.
The two 2D isothermal screens satisfy their chosen legacy numerical criteria;
the two 3D screens retain `converged=false`, because their outer loop is capped
at two. None is claimed physically validated.

The initial capture launcher used `python -m runpy` with a file path and failed
before project execution (native exit 1, relative module names unsupported).
The corrected `runpy.run_path` launcher completed all four cases, native exit 0.
The configured isolated interpreter passed the 73-package exact lock and pip
check before execution. No environment or raw data was modified.

## File handoff, L3

- Initial 2D handoff plus actual low-budget/rejection control: 3 passed in
  5.61 s, native exit 0.
- Four real prepare/solve/postprocess cases: 4 passed in 9.14 s, native exit 0.
- After explicitly freezing the 2D convergence mode, all four handoffs plus
  relevant 2D/3D field/error controls: 38 passed in 10.68 s, native exit 0.

Each stage is a fresh process. Original input JSON and then Case YAML/HDF5 are
deleted before the next stage. The solver process has no preprocess,
optimization, pipeline or Qt import. Postprocess additionally has no solver or
Numba import. Receiver settings deliberately change D-F method, override and
residual switches, solid-geometry factor and convergence mode; the recorded
case still produces the reference outputs. Native solve exits remain 0 for 2D
and **2 for unconverged 3D**; postprocess exits 0 for available screening core
metrics. Temperature/outlet/balance quantities not defined by this model remain
explicitly unsupported.

## Regression and failure provenance

Prepared SIMPLE grid/drag test: 1 passed in 0.41 s, native exit 0. It prohibits
rebuilding geometry or querying drag and checks equal initial fields, copied
input arrays and rejected invalid inputs.

First affected regression: **19 failed, 34 passed** in 6.18 s, native exit 1.
Failures were old monkeypatch/source locations after the implementation moved.
Tests now target the actual producer/kernel/postprocessor seams and retain
nonfinite rejection order, call counts, pressure penalties, physical inlet
fluxes and density conventions. Corrected 2D subset: 29 passed in 1.43 s,
native exit 0. Corrected 3D envelope/porosity/layer subset: 21 passed in 2.01 s,
native exit 0. The old structural porosity check is now an actual asymmetric
prepared-field-to-SIMPLE check, stopping before the thermal kernel.

The explicit rejected archive test preserves absent temperature fields, false
convergence and the choke reason, while offline geometry mass stays available.
A real one-iteration screen remains completed but unconverged with available Q.
Cancelled execution still raises and cannot be archived as completed.

Final fast regression: **2962 passed, 19 skipped, 90 deselected**, 266 warnings
in 455.64 s, native exit 0 (`fast-suite.log`). This excludes slow/heavy cases;
historical frozen pins are never counted as a fast-suite pass.

Final complete `integration_tm1` plus the new offline screening reductions and
screening controls: **21 passed**, 5 warnings in 59.60 s, native exit 0
(`final-integration.log`). This includes full 2D/3D, application, quick-design
and screening file handoffs. The final four screening handoffs retain all
12 native temperature arrays element-for-element against the source capture
(separate array comparison native exit 0). Synthetic offline tests change the
native solid temperature and check that Q changes despite a fake cached Q;
unsupported/rejected quantities retain their explicit status.

Configured seven-file mypy gate and full source/example Ruff checks passed.
CI now explicitly runs the real integration directory on both existing OS /
Python matrix entries; this is configured, not a claim that remote CI ran.

## Public examples, L2

Both examples ran without private solver mutation and exited 0:

- `parameter_scan`: u_A 1 -> 2 m/s changes Q from 806.6068426960455 to
  1250.2285559048382 W/m.
- `design_field_call`: a supplied nonuniform effective solid conductivity
  changes Q from 806.6068426960455 to 813.5753395377444 W/m. The original
  immutable Case remains unchanged; geometry is not silently rebuilt.

Each writes independent Case YAML/HDF5, native results.h5 and strict
metrics.json, with numerical status and `physical_validation=unestablished`.
Gradients/adjoints are explicitly unimplemented. Test elapsed times above are
execution records, not a formal performance comparison or P3 acceptance.

Final examples were rerun with the final six-field Case contract into ignored
`parameter-scan-final` and `design-field-final` directories. The earlier
artifacts remain preserved. Both retained the values above and exited 0.

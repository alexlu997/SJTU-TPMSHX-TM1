# Quick-design public-mode repair

Status: local implementation/acceptance in progress. No PR, remote CI, merge or
complete S40/I40 claim. Base aea7234, branch codex/tm1/quick-design-repair.
Current interpreter /private/tmp/sjtu-tm1-io-venv/bin/python passed the exact
73-package lock and pip check. Shared venv and raw data remain unchanged.

## Preserved model and source

Original design.forward on aea7234 supplies the numerical reference. Its pure
fluid/heat-transfer/analytical-dP functions were moved once to models; preparation
and LTNE execution are separate. The existing forward/sizing/CLI route now uses
public APIs. Mean still uses two passes and carries first-pass temperature arrays
into the second. Sizing warm starts cross immutable data boundaries with equal
values rather than object identity. Budgets, geometry resolution, physical height,
pressure fractions, inlet-state analytical pressure closure and reporting signs
are unchanged. New per-case convergence data does not change feasibility rules.
See schemas/three_module_v1/quick_design.md and the runnable external_design example.

## Evidence and failures

L2 baseline: cross/counter × const/mean at Diamond 7/.5 mm, s=.084 m,
Lx=.05 m and height=.07 m with the existing test_forward DesignCase. All eight
outputs and complete Ta/Tb/Ts arrays were captured before source extraction;
.cache/tm1-quick-design/baseline.json and {mode}.npz retain those observations.
This is a new quick-design source comparison, not a replacement for B40's four
failed optimization pins or their unchanged tolerances.

First numerical follow-up failed 3/3 because the LTNE progress callback takes
(done, budget), not a single percent. Corrected callback mapping: 3 passed in
0.99 s, native exit 0. Initial ruff reported 9 re-export-only unused imports;
explicit historical aliases fixed those diagnostics without removing the API.

Existing design fast suite: 55 passed, 2 deselected, 157 warnings in 21.47 s,
native exit 0 before final warning delivery changed from repeated console
emission to returned warning data and active-scope propagation. Nonfinite
property/thermal-error and warm-start fixtures now patch the actual moved
producer/solver seams; all original call-count, failure-identity and brentq
checks remain. Copy semantics replace identity assertions only at persisted-data
boundaries. Real field comparisons below establish actual numeric preservation.

Architecture/import and existing D-F override checks: 7 passed in 1.50 s,
native exit 0. L3 real prepare/solve/postprocess processes: 4 passed in 7.22 s,
native exit 0. The solve process has no preprocessing import; postprocessing has
no solver/preprocess/pipeline/Numba/Qt import. Original JSON and then prepared
Case files are deleted between stages. Receiver D-F environment is changed to
rbf / overrides off / residual correction on; prepared fixed-CFD execution is
unchanged. All four solves report native convergence true and native exit 0.
Eight original outputs agree at 1e-10, and the **12 native temperature arrays
are exactly equal element by element** to the before-extraction arrays.

Actual low-budget/cancellation/unsupported-field control test: 1 passed in
0.90 s, native exit 0. The one-iteration result is completed but converged=false;
its finite Q remains available in W with the unestablished physical-validation
status. No invalid state was relabelled success.

Public example produced Q_hot=83919.87442033271 W, convergence true, YAML/HDF5
Case, native results.h5 and strict metrics.json. Example native exit and final
combined regression will be appended after collection.
No formal performance comparison is claimed by these test elapsed times.

Final local L1/L2 regression: full fast subset **2959 passed, 19 skipped,
86 deselected**, 268 warnings in 490.71 s, native exit 0. The excluded design
slow/heavy subset separately completed **2 passed, 55 deselected**, 25 warnings
in 28.51 s, native exit 0. This includes serial/parallel enumeration and the
warm-start optimization behavior exercised by the existing design tests.

The additional offline-native-Q test passed 1/1 in 0.07 s, native exit 0:
changing native outlet temperature changes Q even when a contradictory cached
metric is present, and converged=false remains false. This test was added after
full-suite collection and is reported separately. Ruff checks passed for the
changed design/model/preparation/execution/postprocessing and new test files;
the configured seven-file mypy gate passed. The public example exited 0.

These are local stage results. Optimization screening extraction, independent
review, remote CI and merge remain outstanding; S40/A40/I40/I54 remain running.

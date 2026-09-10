# Fixed quick-design pressure preparation

Continuation of 657a7bf in the same isolated P40 worktree, coordinated with
G10/S40/A40/I54. The original `_dp_fractions` depends on geometry and inlet
conditions, not final temperatures. It now executes during preparation with
the original resolved method/override/residual options. Both dimensionless
fractions travel in CaseData. Runtime validates and consumes them, preserving
absolute boundary pressures and choked flags. Offline metric reductions are
unchanged. Missing old intermediate fields require re-preparation.

This closes a runtime path that could initialize legacy RBF calibration after
the thermal solve. Source/model selection and production coefficients have
not changed; explicit research choices may still require their offline inputs
while preparing a Case.

Configured interpreter and lock match the preceding offline evidence. With
OPENBLAS/OMP/NUMBA_NUM_THREADS=1 and local caches:
`python -m pytest sjtu_tpmshx/tests/solver_tm1/test_quick_design_controls.py
sjtu_tpmshx/tests/integration_tm1/test_public_design.py
sjtu_tpmshx/tests/design/test_forward.py -q --timeout=600 --timeout-method=thread`
completed 8 passed in 11.36 s, native exit 0 (`.cache/p40/quick-pressure.log`).
Four real three-process design cases retain source numerical references.
A guard forbids rebuilding pressure during actual execution, and invalid
prepared fractions fail before solving. Ruff and diff check passed.

Initial full fast regression with NUMBA_NUM_THREADS=1: 285 failed, 2687 passed,
20 skipped, 91 deselected, native exit 1. Of those failures, 280 explicitly
requested two Numba threads, conflicting with this invocation's one-thread
maximum. The remaining five asserted the old property-call timing. Their
exact counts, values, warning labels and nonfinite guards remain; the expected
fixed inlet evaluation now precedes thermal passes. Targeted follow-up:
19 passed in 4.69 s, native exit 0.

The corrected full command omitted that one-thread environment cap, preserving
the existing tests' thread requirements:
`python -m pytest sjtu_tpmshx/tests/ -q -m 'not slow and not heavy'
--timeout=600 --timeout-method=thread` completed 2972 passed, 20 skipped,
91 deselected, 267 warnings in 312.88 s, native exit 0
(`.cache/p40/fast-corrected.log`). The prior failed command remains in
`fast-final.log`; it is not relabelled successful. Remote CI, independent
review and merge remain pending; this is not a physical Q acceptance claim.

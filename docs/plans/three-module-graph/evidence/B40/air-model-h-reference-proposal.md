# Air integral-enthalpy reference proposal — approved 2026-09-11

The user explicitly approved these two Q updates. No other value or criterion
is authorized to change by this decision. The original proposal follows.

Applied validation: four frozen tests plus four saved-field energy tests pass,
8 passed in 3.79 s, native exit 0. Log:
`.cache/b40-approved-model-h-frozen.log`. Inputs, budgets and tolerances remain
unchanged; broader public screening/control validation is recorded separately.

The public three-process check initially returned 2 failed / 3 passed with the
runtime-control test, native exit 1: its two 2D comparisons still loaded the
historical S40 temperature-form Q. Those two active comparisons now reuse the
approved frozen tuples; the historical S40 file remains untouched. All four
real YAML/HDF5/JSON screening handoffs then pass in 11.51 s, native exit 0
(`.cache/model-h-public-screening-approved.log`). The initial failure remains
in `.cache/model-h-public-screening-controls.log`.

After the user-approved cp(T) integral-enthalpy repair, the unchanged original
budget test returns 2 failed / 2 passed, native exit 1. Only the two 2D Q
objectives differ; 3D references still pass. The explicit objective rerun
returns native exit 0 and confirms both pressure and mass values are unchanged.
Logs: `.cache/b40-air-model-h-original-budget-frozen.log` and
`.cache/b40-model-h-original-tuples.log`. Solver source is `ae6f236`; later
`e50b3b6` changes only evidence. No active reference is changed by this proposal.

| Original-budget case | Previously approved Q W/m | Proposed Q W/m |
| --- | ---: | ---: |
| 2D uniform | -8085.955349708075 | -8019.434130581629 |
| 2D nonuniform | -7561.252334176324 | -7507.811193372061 |

Keep dP, material mass, both 3D tuples, all inputs and budgets, and the existing
`pytest.approx(rel=1e-12)` unchanged. Preserve both original 4/4 failures and
this subsequent 2/4 failure as historical observations. The proposed values
come from the original budget, not from the independent F2 engineering runs.

The reason is the demonstrated native-mass/thermal-capacity mismatch and the
approved conservative air enthalpy repair, supported by independently reduced
native boundary energy and F2/Q-change evidence in `air-model-h.md`. Returning
to the previous values would restore the known transport defect. Reference
approval does not establish physical accuracy, multi-loop outer convergence,
M-A completion or permission to bypass final CI/review.

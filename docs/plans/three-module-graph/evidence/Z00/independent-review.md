# Independent review record

2026-09-11; source candidate `3650fcf9c289c15a3c11b63de9295231ccf79f49`,
PR #7 base `c7f013869e7127b35ac0c305376c13b3a834131b`.
Independent read-only reviewer: `b40_review`. This is an internal review,
not a formal GitHub approval or a declaration of complete M-A acceptance.

## Completed directed review

- Public preparation → CaseData → solver dispatch, prepared full 2D/3D
  builders and quick-design execution.
- FieldResult → metrics, screening and quick-design reducers.
- RunControl cancellation/progress and the documented 2D-only SIMPLE
  residual callback contract.
- Case YAML/HDF5, result HDF5, metrics JSON and VTK handoff semantics.
- B40 input/pin ancestry, actual evaluator call paths and recorded same-source
  comparison evidence; findings are in `../B40/failure-triage.md`.

No demonstrable new implementation blocker was found in these inspected
paths. Raw HDF5 NaNs remain possible and do not imply available finite JSON
metrics; MetricValue guards the latter. CLI solve retains exit 2 for an
unconverged result. These are static observations, not a new numerical run.

The reviewer identified a misleading causal interpretation to avoid:
production report-enthalpy changes are not the screening evaluator's call
path. The B40 supplement distinguishes that from the reachable complete
end-control-volume change `5adb61d`, whose contribution remains unquantified.

## Remaining review and gates

Offline resource preparation/publication and public application wiring are
covered by a separate directed pass, which found one concrete issue below.
This record does not cover every changed file
or prove all physical modes. Full acceptance remains open while B40's
four failures lack resolved causes/exit conditions and current matrix CI and
merge verification remain outstanding. No original failure, threshold,
convergence requirement or dependency edge is removed by this review.

## Offline training finding and correction

The reviewer found that publish_surrogate → SurrogateV3._build bypassed the
existing Shanghai holdout guard in load_data. There is no evidence that
production resources were contaminated. A synthetic workbook copied to
shanghai.xlsx reproduced the defect: the new rejection assertion failed
(1 failed, native exit 1), because publication proceeded.

The shared workbook-training path now invokes the existing guard on its
numeric L/t rows and actual source path before filtering or fitting. It
retains col43/alpha calibration; it does not route through the distinct
col47 cleaning formula. Direct training and publication reject L=7 or t=0.6
workbooks, and rejected publication creates no output directory.

Offline/source/import regression: 19 passed, 1 skipped in 2.82 s, native exit
0; changed-file Ruff passed. The skip is not a source-data validation pass.
The reviewer separately confirmed that this correction closes the reported
bypass and found no import cycle; that review did not rerun the tests.
No new PDE was run.

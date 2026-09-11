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

## Explicit CFD input-path follow-up

At `60417cf`, the reviewer compared the complete new source-path diff of
load_sco2_cfd and load_water_cfd against `c7f0138`, including resolver,
pressure/geometry calls and the artificial water test. No demonstrated
regression was found: lattice and density checks still run; entrance-period
filtering is unchanged; water flow_suspect marks rather than deletes rows;
Dh_cfd_m and Re_nominal retain the source values. Unit conversions were not
changed. This is a static review of the new source option, not comprehensive
validation of the pre-existing correlations or missing real water dataset.

## Final M-A requirement review, 2026-09-11

Independent reviewer `b40_review` checked the original V0.1/REQUIREMENTS and
all 37 architecture task cards against current implementation and evidence at
code candidate `0ba1657`. No additional demonstrated M-A implementation gap
was found. The review confirmed real GUI worker/slice/CSV evidence and actual
2D/3D HDF5 production followed by evaluation without Numba/Qt in minimal CI.
P40 explicitly permits recording the missing real water CFD dataset; synthetic
tests are not substituted for that missing physical dataset. M-B remains open
for real C++/OpenFOAM, providers/REFPROP, tensors, internal SI and H30 metrics.

The reviewer identified stale/empty node evidence and next-action records,
which are now linked to current evidence. The remaining release work is final
combined acceptance, authorized merge and post-merge verification. No new
multi-density-loop convergence requirement is inferred: 2D single-loop outer
false remains explicit; F2, chunk Q-change, mass and native boundary energy
have separate evidence. Interactive GPU volume rendering and multi-loop outer
convergence are not claimed. This review did not rerun tests or PDE.

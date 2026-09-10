# Prepared thermal geometry and fixed correction

Source base: 71f83a8f652039f6b8477c27a8b43678efac95ff; isolated
`codex/tm1/full-preparation-repair` continuation. Independent review, remote
CI and merge remain outstanding. B40's historical failed gate is unchanged.

Preparation owns uniform/zoned A0, Dh and porosity, asymmetric side geometry,
2D boundary openings, and initial 3D air bulk exchange. Runtime consumes these
values while retaining current-temperature fluid properties and local Nu.
Three-dimensional roughness is frozen at preparation. Experimental correction
scales are prepared once; execution still projects the supplied physical K
field, so changing CaseData K changes the actual SIMPLE input. Invalid geometry
is rejected at persistence/execution boundaries. No thresholds, campaign bounds,
coefficients or numerical stopping criteria were changed.

Environment: `/private/tmp/sjtu-tm1-io-venv/bin/python`, configured by
`.venv-path`; the preceding exact 73-entry lock and pip checks passed.
Caches/logs are worktree-local under `.cache/tm1-full-preparation/`.

## Actual checks and failure provenance

- L2/L3: `python -m pytest sjtu_tpmshx/tests/integration_tm1` completed
  18 passed, 5 warnings in 50.71 s, native exit 0 (`thermal-integration-final.log`).
  This includes real full-mode numerical comparison and independent file
  prepare/solve/postprocess processes, with changed receiver roughness settings.
- L2 initial-state comparison (`compare-thermal-3d-final.log`) matched source
  h_v, local h_v and asymmetric ratios exactly for uniform, zoned and asymmetric
  inputs; native exit 0. This check deliberately stops at initial SIMPLE and
  is not a separate converged PDE acceptance.
- Initial integration failed 2/18 because the new no-geometry guard also covered
  legacy reference finalization. The guard now encloses only actual public
  execution; reference comparison remains outside and all comparisons remain.
- Initial targeted regression: 12 failed, 101 passed. Synthetic warning fixtures
  changed geometry after preparation; they now supply prepared geometry directly.
  Follow-up: 67 passed, native exit 0. Experimental fixture initially violated
  the existing campaign size/port scope; corrected fixture: 2 passed, native 0.
- Initial full fast run: 160 failed, 2807 passed, 19 skipped, 90 deselected,
  native exit 1. Removed aliases broke old fixture constructors; other synthetic
  fixtures lacked newly prepared fields. One source-inspection test encountered
  a file edited during its run. Relevant follow-up: 238 passed, native exit 0.
  No assertion or numerical acceptance threshold was relaxed. The final full
  run used stable source files: `python -m pytest -m 'not slow and not heavy'
  --timeout=600 --timeout-method=thread` completed 2967 passed, 19 skipped,
  90 deselected, 267 warnings in 170.97 s, native exit 0
  (`fast-suite-final.log`).
- L0 Ruff, configured seven-file mypy and diff check passed before the final
  numerical runs. No local environment installation or raw-data modification.

Historical failures remain evidence of the first attempts; targeted repairs
do not retroactively make those commands successful. Skipped raw-data checks
and absent remote CI cannot establish physical calibration or M-A completion.

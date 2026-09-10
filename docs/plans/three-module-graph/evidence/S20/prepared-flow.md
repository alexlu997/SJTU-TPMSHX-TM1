# Full 2D prepared flow repair

Source base: f4063579410806eb7143a9592dd66fdc4dfe6cf1. Work is local;
full thermal-geometry cleanup, independent review, remote CI and merge remain
outstanding. This does not close M-A or change B40's historical failures.

The producer now resolves the actual cross/stream widths and row K/cF once,
including source zone sampling, field projection and experimental correction.
It records separate scalar coefficients for the original uniform pressure seed.
Runtime consumes these arrays directly through the existing prepared SIMPLE
constructor. It no longer constructs a throwaway grid, queries drag, projects
geometry, or calculates ignored zone_arrays. Current-temperature properties,
graded pressure reseeding and measured-pressure inlet shooting remain unchanged.
The receiver validates shape, sign, finiteness and agreement with the thermal
grid. The two sides retain D-F applicability metadata and warning side labels.

The configured isolated interpreter matched all 73 active lock entries; pip
check passed. No environment was rebuilt or modified.

## Evidence

- Eight initial SIMPLE states (uniform / 1D zones, all four flow directions)
  matched the source runtime exactly for grid, drag, u/v/P, density, Brinkman
  coefficient, porosity, port profiles and pressure reference. Native exit 0.
  The source runtime copy and comparison log are in ignored
  `.cache/tm1-full-preparation/`.
- A runnable frozen-input test forbids grid construction, D-F prediction and
  projection after preparation, changes the receiver method, and verifies both
  sides consume their arrays. It rejects inconsistent supplied grids:
  1 passed in 0.86 s, native exit 0.
- Real B20 air, both mixed-fluid cases, and 2D/3D file handoff:
  5 passed, 5 warnings in 103.40 s, native exit 0 (`real-2d.log`).
- First regression command used a nonexistent architecture directory: no tests
  ran, native exit 4. Corrected directory: 2 failed, 84 passed, 3 skipped,
  4 warnings in 81.67 s, native exit 1. Both failures were loss of side labels
  on experimental D-F warnings when moving their producer. Coefficients and
  pressure assertions passed. The producer now supplies side/stage context;
  the unchanged four application coefficient tests passed on rerun, native 0
  (`df-warning-fixed.log`). This is a repaired targeted result, not a claim
  that the original regression run passed.
- Ruff and the configured seven-file mypy gate passed; diff check passed.

No full new fast suite or remote CI is claimed by this intermediate evidence.
The next full-mode work still includes fixed thermal geometry and asymmetric
geometry preparation in both dimensions.

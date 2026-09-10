# B40 application-path map

Baseline commit: `5f1cafb` (TM1 `main` when this record was created).

This is a source-derived map, not a numerical acceptance result.  It records
the existing interfaces before later adapters route them through `CaseData` /
`FieldResult`; it does not change an evaluator, a correlation, or a threshold.

## Paths and contracts

| Mode | Public route | Current kernel route | Returned/consumed quantities |
| --- | --- | --- | --- |
| 2D qNEHVI | `ui/optimize_panel.py` worker -> `optimizer_qnehvi.run_qnehvi` (default evaluator) | `optimization.evaluator.evaluate_design` -> 2D SIMPLE for both sides -> `solve_full_domain` | `(-Q, dP + manufacturability penalty, mass)` = `(W/m, Pa, kg/m)`; minimization uses the negative heat duty. |
| 3D qNEHVI | same worker, with `evaluator_fn=evaluate_design_3d` | `optimization.evaluator_3d.evaluate_design_3d` -> `core.evaluators.evaluate_3d` | Core output is `Q_3D_W`, `dP_total_Pa`, `mass_kg`; wrapper divides Q and mass by `Lz`, then returns `(-Q/Lz, dP, mass/Lz)` = `(W/m, Pa, kg/m)`. |
| quick design | `design.sizing` -> `design.forward.forward` -> `design.report` | LTNE `solve_full_domain_3d`; pressure loss is analytic `dP_fracs` | `ForwardResult` has `Q_hot/Q_cold` in W, pressure-drop fractions (not Pa), Reynolds numbers, and optional warm-start fields. Crossflow uses `Nz=1`; counterflow uses `Nz=2`. |

## State and budget boundaries

- 2D choke before solve, configured rejection of unconverged SIMPLE, and a
  non-finite/over-cap objective all return `(-1e-6, dp_cap_pa, real mass)`.
- 3D `invalid` returns the same bounded heat/pressure penalty while preserving
  geometry mass before the per-depth conversion.  `optimizer_qnehvi` also
  guards non-finite worker outputs.
- The 2D evaluator creates cold starts.  The 3D evaluator supplies its
  fast-mode `Nx_3d`, `Ny_3d`, `Nz_3d`, outer-loop, SIMPLE, and LTNE budgets.
  Quick design may accept and return LTNE fields as a warm start; it is not an
  optimizer low-accuracy switch.

## Existing verification anchors

- 2D/3D objective normalization and representative fixed values:
  `sjtu_tpmshx/tests/test_evaluator_frozen_values.py`.
- 3D evaluator conservative path: `test_evaluator_3d_conservative.py`.
- Application wiring: `test_optimize_panel_wiring.py`.
- Quick-design result and pressure-fraction behavior:
  `sjtu_tpmshx/tests/design/test_forward.py`,
  `test_height_decouple.py`, and `test_converge_fast.py`.

Numerical execution and captured values remain pending B40's matched-lock run;
this map must not be read as a solver or physical-accuracy baseline.

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

## First matched-lock execution (not an acceptance pass)

On baseline `5f1cafb`, CPython 3.13 from the checked `.venv-path` passed the
exact lock check (71 active packages) and `pip check`.  The following command
then completed in 92.34 s:

```
MPLCONFIGDIR=.cache/matplotlib XDG_CACHE_HOME=.cache/xdg \
  /Users/luwenhuan/.venvs/sjtu-tpmshx-py313/bin/python -m pytest \
  sjtu_tpmshx/tests/test_evaluator_frozen_values.py -q \
  --timeout=600 --timeout-method=thread
```

It failed 4/4.  This is evidence, not permission to revise the pins or their
tolerance:

| case | observed `(Q_neg, dP, mass)` | pinned `(Q_neg, dP, mass)` |
| --- | --- | --- |
| 2D uniform | `(-8085.955349708075, 4675.147979229178, 3.446685791015626)` | `(-8085.955568764836, 4675.147100112292, 3.446685791015626)` |
| 2D nonuniform | `(-7561.252334176324, 4052.0456347246245, 3.6729327392578126)` | `(-7561.25242589901, 4052.044538218606, 3.6729327392578126)` |
| 3D uniform | `(-7209.103274428575, 7519.596015609637, 6.323593139648438)` | `(-9968.92699806532, 7546.892661221464, 6.323593139648438)` |
| 3D nonuniform | `(-8672.919843820628, 2871.31457245229, 3.675970458984375)` | `(-10850.753888768157, 2879.2941880943804, 3.675970458984375)` |

All geometry masses agree exactly.  The test is marked `slow`, so the current
E00 CI command (`not slow and not heavy`) does not cover it.  Its source
history itself records that the pins became stale after later production
closure changes; B40 leaves the mismatch open for provenance reconciliation
rather than converting this historical pin into a passing threshold.

The current baseline is not the pin-capture parent: the ancestry from
`dafdc92` to `5f1cafb` contains `a9da65f` (physical 3D inlet capacity and
synchronized air density), `ee14cbd` / `df40880` (conserved 3D enthalpy and
reported heat duty), `81dbccd` (conservative 2D thermal transport),
`136ff16` (nonuniform 3D face-pressure extrapolation), and `d61e341`
(no-slip walls/scoped experimental D-F windows).  Those later physics and
reporting changes are a concrete provenance gap for the material 3D drift;
they do not establish an environment-only explanation, nor authorize a new
frozen value.

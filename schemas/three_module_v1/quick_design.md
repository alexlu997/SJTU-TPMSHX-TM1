# Quick-design mode in the current v1 draft

Mode: `metadata.mode=quick_design`, composite model
`plug_ltne_analytic_dp_v1`, backend `python/quick_design_v1`. This is the
existing prescribed-velocity LTNE sizing approximation with analytical
inlet-state D-F pressure loss. It does not run SIMPLE. The original sCO2
representative-Pr caveat remains part of the emitted source warnings.

## Prepared input

`preprocess.api.prepare_quick_design` accepts an existing DesignCase plus
geometry and sizing options. `config_snapshot` records the original DesignCase
and is not used by execution. The prepared data has:

- Physical `grid`: dimension 3, x/y/z axes, widths and cumulative edges in m.
  Crossflow uses 60 × 40 × 1 and the existing 2D kernel delegation; counterflow
  uses 60 × 1 × 2. Actual physical height is retained in both modes. The output
  heat duties are total W, not per-depth W/m despite the Nz=1 delegation.
- `design_fields`: uniform full porosity `eps`, one-side `eps_A=eps/2`, and
  effective solid conductivity `K_ss` in W/(m K), each on the prepared grid.
  Nonuniform or unconsumed fields are rejected in this mode.
- `parameters.operating_point`: fluid identifiers, inlet T in K, absolute P
  in Pa and prescribed mass rates in kg/s for the hot/cold streams.
- Geometry: `L_cell_m`, `t_wall_m`, `Lx`, `s`, `height`, `D_h` in m;
  `A_0` in 1/m and `k_s` in W/(m K). The existing geometry resolution is 128.
- `controls`: existing direction, under-relaxation, maximum iterations,
  heat-duty tolerance and chunk size. Crossflow retains alpha 0.7, 8000,
  qtol 1e-4 and chunk 100; counterflow retains alpha 0.3, 20000 and the kernel
  qtol/chunk defaults. The requested thermal `tol` remains separate.
- `initial_fields`: absent or three finite cell temperature arrays in K.
  Copies cross the contract boundary; the receiving solve uses their values.
- `df_options`: the resolved `method` only (`cfd_full_core_3cell_fixed_v2`). It takes
  precedence over the receiving-process environment without process-global
  replay. Former override and residual-correction flags are retired.
- `inlet_pressure_fractions`: prepared A/B analytical dP/P_in, dimensionless,
  finite and nonnegative. The producer evaluates the existing inlet-state D-F
  calculation with `df_options`; execution cannot start calibration or reload
  training data. These fixed values must be prepared again when changing inlet
  conditions or geometry. Older intermediate Cases lacking them are rejected.
- `prop_model`: const (one inlet-property pass) or mean (one additional pass
  evaluated at inlet/outlet mean temperatures). Runtime property evaluation is
  part of the model's execution. No geometry or grid is rebuilt at execution.

The quick-design ModelRef version `v2-5f1cafb` identifies the extracted composite
closure and numerical-budget conventions. Separate fluid ModelRefs identify
both actual fluid providers. Unknown versions and mismatching fluid identities
are rejected. Model versions identify formulas, not experimental accuracy.

## Native result and independent evaluation

Temperature, prescribed velocity, fluid/solid conductivity, volumetric coupling
and porosity fields have explicit units, x/y/z cell placement and final-pass
state metadata. `boundary_fluxes.A/B` retain prescribed mass rates (kg/s), inlet
T (K), pass cp (J/(kg K)), density (kg/m3) and velocity (m/s). The original
outlet arithmetic mean over the appropriate full face is preserved.
`pressure_evidence` contains inlet/outlet absolute pressure states from the
analytical D-F solve, its model identity and the existing choked-pressure
rescue flag. These are analytical boundary states, not a fabricated pressure
PDE field. All resolved model inputs remain in result metadata.

The independent postprocessor computes hot/cold duty from prescribed mass
rate × final-pass cp × native outlet/inlet temperature difference; Q means
hot-side heat release in W. It subtracts the analytical boundary pressure
states for dP in Pa and computes Re from recorded properties/velocity/geometry.
The design application divides dP by each original absolute inlet pressure to
retain its fraction output. No model/EOS/solver call is needed offline.
The energy comparison is |Q_hot−Q_cold| / max(|Q_hot|, |Q_cold|, 1e-30).
Mass and full boundary mass-imbalance metrics are explicitly unsupported here.

Execution/convergence, each pass's native info and unestablished physical
validation stay separate. A finite metric from an unconverged completed solve
remains available with that original run status. ForwardResult adds run_status
and warnings; sizing's final per-case records and report retain them. Source
messages also enter any active legacy warning scope. They are returned as data
rather than emitted again for every intermediate standalone search evaluation.
Nonfinite thermal returns still raise before outlet/duty/pressure reporting.

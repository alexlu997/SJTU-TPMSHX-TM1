# 2D producer contract — implementation v1

[中文](two_d.zh-CN.md) | [English](two_d.md)

`CaseData.grid` records physical `(x,y)` axes, metre-valued `dx`, `dy`, edge
arrays and breakpoint coordinates. Shapes are effective cell counts, including
wall refinement, not requested counts. The solver validates positive finite
widths, domain extent and matching edges. It never calls preparation.

`parameters` carries parsed inlet temperatures (K), velocities (m/s), dimensions
(m), per-side port centre/width (m), and directions (0:+x, 1:-x, 2:+y, 3:-y). It also carries `L_cell_m`, `t_wall_m`, conductivity (W/(m K)), porosity and
hydraulic radius (m). `run_settings` is the existing numerical/control dataclass data, with
geometry in metres and zones removed because prepared zone data owns that
input. `static_properties` contains the evaluated inlet material properties
and geometry so runtime does not re-read the solid homogenization environment. `flow_inputs.A/B` records the actual SIMPLE cross/stream widths in m,
`K_m2/cF_per_m` row coefficients, scalar `seed_K_m2/seed_cF_per_m`, and D-F
applicability metadata.

Non-continuous zones (1D, discrete grid and the legacy
grid sigmoid path) keep the row model. This model averages physical L/t fields
across the transverse width with physical cell-width weights. It then evaluates
the fixed D-F model and orders rows in the actual flow direction. For `zones.axis="continuous"`, each side additionally records complete local
`K_field_m2/cF_field_per_m` arrays in its SIMPLE `(cross, stream)` coordinates. These are evaluated from each physical L/t cell, with streamwise reversal for
negative flow.

Their crosswise means populate the row arrays for pressure
initialization only. Momentum consumes the complete local arrays. Where
experimental continuous-field transfer is supported, preparation applies the
resolved fixed correction factors to the local CFD arrays and records
`continuous-field-extrapolation`. Execution consumes those corrected arrays. The executor validates the grids and coefficients, including required local
arrays for continuous cases, against the physical grid.

Receiver D-F
environment settings cannot replace them. Temperature-dependent properties,
graded pressure re-seeding and inlet shooting stay numerical execution steps.

`thermal_geometry` contains the fixed scalar or cell-wise A_0 (1/m), D_h
(m), epsilon, the asymmetric side split and each side's area/diameter versus
its symmetric reference. These are explicit prepared inputs. Geometry changes
require a coherent newly prepared Case. Runtime evaluates current-state Nu and
transport against them, and consumes the saved inlet geometric opening. The separate `config_snapshot` is historical provenance.

Deleting it does not
change execution. No callback or runtime model is stored in CaseData.

`boundary_openings.A/B` records geometric overlap and the existing tapered
profile for inlet and outlet. These are different quantities. Tout selects
positive geometric overlap and uses signed native mass, never the taper as an
extra factor. Existing numerical constructors keep their physical port rules.

`design_fields` uses physical cell shape. `eps_arr` is total porosity. `r_h_arr` is m. `K_ffA_arr/K_ffB_arr/K_ss_arr` are W/(m K). `h_vA_arr/h_vB_arr` are W/(m3 K).

`A_0_arr` is interface area per volume (1/m). `L_field_m/t_field_m`, zone `L_m/t_m` and grid-cell `L_m/t_m` are metres. `zone_id` is a dimensionless integer. For 1D-zone, discrete 2D-grid and sigmoid
designs, cell/wall geometry is sampled at the final physical cell centres,
including nonuniform meshes.

Their per-cell `thermal_geometry` is required and
consumed by the local heat-transfer calculation. A zoned prepared archive
missing these fields is rejected: prepare its original configuration again. `zones.axis="continuous"` samples L(x,y)/t(x,y) at those physical centres
without the discrete-zone Gaussian filter. The original spline controls stay
in `parameters.continuous_field`, alongside the prepared SI fields. The 2D
backend rejects `n_ctrl_z`. Uniform arrays must agree with their scalar geometry
inputs.

Continuous-field applicability and calibration limits stay those in
the [architecture](../../docs/architecture.md). Smooth controls alone do not
show gradient accuracy or manufacturability.

Four `ModelRef` records identify fluid A, fluid B, geometry and the fixed CFD
D-F table, with indices in `metadata.model_roles`. Fluid references keep the
run-owned sCO2 Nu parameters and their source/applicability. Unknown resource
versions and inconsistent fluid/topology declarations fail before execution.
Experimental `alpha_D/alpha_G` are total Ceff, not a historical coefficient
plus an independent multiplier. The same one-application rule holds in 3D.
Replaying this prepared Case does not reload the current parameter resource.

`FieldResult.fields` separates raw last-main `Ta/Tb/Ts` from `*_display` copies. `P_thermal_A/B` is the local absolute pressure used by the last thermal solve.
`P_report_A/B` is the unsmoothed final reporting pressure, a distinct state. `field_metadata` declares units, location, axes and state for each array. Pressure evidence additionally stores final SIMPLE inlet/outlet gauge rows,
profile weights and absolute reference for the kept backend summaries. Formal dP uses `P_report_A/B`, the physical cell widths and geometric opening
fractions.

It uses `pressure_face_v1` to extrapolate to physical port faces and
then average by open face area (unit depth). It does not use the previous profile weights
or a smoothed pressure field.

`boundary_fluxes.mass_A/B` are `(x-face,y-face)` arrays on `(Nx+1,Ny)` and
`(Nx,Ny+1)`, positive along physical axes, kg/(s m), already including open
face area and porosity. `model_h` keeps complete signed h-flux faces in W/m
and inlet conduction faces. `true_h` keeps native h (J/kg), prescribed inlet
h and signed face masses, with the original one-cell z adapter explicit in
array shape. `fine` is a separately identified refined thermal return.
`run_status` keeps numerical convergence and any final flow update after
the last thermal return. It does not recast a nonconverged run as accepted.

Postprocessing reads native evidence only. Formal `Q=abs(Q_A)` uses the last
main-grid thermal state (`native_boundary_v1`). Model-h integrates signed h
faces. True-h uses native boundary enthalpy duty. Temperature-form keeps
its rho-cp/velocity/profile convention.

Accepted per-side Richardson duties
are separate `Q_richardson_A/B` metrics and never replace main-grid Q. Backend
summaries and `reporting_reference` keep their historical definitions for
existing consumers. Tout uses raw main T and positive outward mass over true
openings. Q is W/m. Missing evidence yields
an unavailable metric. It never invokes a solver.

A finite metric does not
change the source run's numerical or physical status. Solid mass additionally
requires an explicitly supplied solid density. It is not inferred from k_s.
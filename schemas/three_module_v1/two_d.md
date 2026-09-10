# 2D producer contract — implementation v1

`CaseData.grid` records physical `(x,y)` axes, metre-valued `dx`, `dy`, edge
arrays and breakpoint coordinates. Shapes are effective cell counts, including
wall refinement, not requested counts. The solver validates positive finite
widths, domain extent and matching edges; it never calls preparation.

`parameters` carries parsed inlet temperatures (K), velocities (m/s), dimensions
(m), per-side port centre/width (m), directions (0:+x, 1:-x, 2:+y, 3:-y),
`L_cell_m`, `t_wall_m`, conductivity (W/(m K)), porosity and hydraulic radius
(m). `run_settings` is the existing numerical/control dataclass data, with
geometry in metres and zones removed because prepared zone data owns that
input. `static_properties` contains the evaluated inlet material properties
and geometry so runtime does not re-read the solid homogenization environment.
`flow_inputs.A/B` records the actual SIMPLE cross/stream widths in m,
`K_m2/cF_per_m` row coefficients, scalar `seed_K_m2/seed_cF_per_m`, and D-F
applicability metadata. The producer preserves the existing zone sampling and
projection conventions, including reverse-flow ordering. The executor validates
these grids against the physical grid and consumes these coefficients directly;
receiver D-F environment settings cannot replace them. Temperature-dependent
properties, graded pressure re-seeding and inlet shooting remain numerical
execution steps.
The separate `config_snapshot` is historical provenance; deleting it does not
change execution. No callback or runtime model is stored in CaseData.

`boundary_openings.A/B` records geometric overlap and the existing tapered
profile for inlet and outlet. These are different quantities; Tout selects
positive geometric overlap and uses signed native mass, never the taper as an
extra factor. Existing numerical constructors retain their physical port rules.

`design_fields` uses physical cell shape. `eps_arr` is total porosity;
`r_h_arr` is m; `K_ffA_arr/K_ffB_arr/K_ss_arr` are W/(m K);
`h_vA_arr/h_vB_arr` are W/(m3 K); `A_0_arr` is interface area per volume (1/m).
`L_field_m/t_field_m`, zone `L_m/t_m` and grid-cell `L_m/t_m` are metres.
`zone_id` is a dimensionless integer. The existing uniform, 1D-zone, discrete
2D-grid and sigmoid conventions remain; no new design family is introduced.
Uniform arrays must agree with their scalar geometry inputs.

Four `ModelRef` records identify fluid A, fluid B, geometry and the fixed CFD
D-F table, with indices in `metadata.model_roles`. Fluid references retain the
run-owned sCO2 Nu parameters and their source/applicability. Unknown resource
versions and inconsistent fluid/topology declarations fail before execution.

`FieldResult.fields` separates raw last-main `Ta/Tb/Ts` from `*_display` copies.
`P_thermal_A/B` is the local absolute pressure used by the last thermal solve;
`P_report_A/B` is the unsmoothed final reporting pressure, a distinct state.
`field_metadata` declares units, location, axes and state for each array.
Pressure evidence additionally stores final SIMPLE inlet/outlet gauge rows,
profile weights and absolute reference. dP uses these row weights exactly;
it is not area-weighted or inferred from a smoothed pressure field.

`boundary_fluxes.mass_A/B` are `(x-face,y-face)` arrays on `(Nx+1,Ny)` and
`(Nx,Ny+1)`, positive along physical axes, kg/(s m), already including open
face area and porosity. `model_h` retains complete signed h-flux faces in W/m
and inlet conduction faces. `true_h` retains native h (J/kg), prescribed inlet
h and signed face masses, with the original one-cell z adapter explicit in
array shape. `fine` is a separately identified refined thermal return.
`run_status` preserves numerical convergence and any final flow update after
the last thermal return; it does not recast a nonconverged run as accepted.

Postprocessing reads native evidence only. Model-h Q integrates signed h faces
and applies the existing per-side Richardson formula if its original status
permits it; true-h Q uses fluid A boundary enthalpy duty; temperature-form Q
uses its original rho-cp/velocity/profile convention. Tout uses raw main T and
positive outward mass over true openings. Q is W/m. Missing evidence yields
an unavailable metric; it never invokes a solver. A finite metric does not
change the source run's numerical or physical status. Solid mass additionally
requires an explicitly supplied solid density; it is not inferred from k_s.

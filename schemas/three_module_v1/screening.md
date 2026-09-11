# Prepared screening modes

`preprocess.api.prepare_screening_2d` and `prepare_screening_3d` expose the
existing air/air optimization models. Their CaseData `mode` values are
`screening_2d` and `screening_3d`; model identities are respectively
`air_air_volume_ltne_v1` and `air_air_frozen_b_volume_ltne_v1`. These are screening
models with their original convergence budgets, not full-model substitutes.
Both use recorded `screening@v2-5f1cafb` and `fluid@v2-5f1cafb` (air) resources.

## CaseData

- `grid`: physical x/y[/z] widths and edges in m, explicit dimension and axis
  order. 2D quantities use unit depth and retain W/m and kg/m conventions.
- `design_fields`: exactly `eps_arr` (full porosity, dimensionless),
  `K_ffA_arr`, `K_ffB_arr`, `K_ss_arr` (effective conductivities, W/(m K)),
  `h_vA_arr`, `h_vB_arr` (volumetric exchange coefficients, W/(m³ K)). Arrays
  match the physical grid; unsupported fields and nonfinite coefficients fail
  before execution. These are consumed inputs, not requests to regenerate
  geometry. Effective-conductivity updates can use immutable dataclass
  replacement as shown in `examples/three_module/design_field_call.py`.
- `parameters.compute`: resolved inlet temperatures K, pressures Pa, speeds
  m/s where applicable, density kg/m³, domain lengths m, iterations/tolerances
  and the original density/temperature relaxation settings. 3D also records
  the cold A seed's mass flux and mean drag for its hot-state reseed. Optimizer
  penalties/caps are not numerical backend controls.
- `parameters.flow.A/B`: resolved SIMPLE constructor data: physical lengths
  and grid widths m, initial density kg/m³, viscosity Pa s, temperatures K,
  pressure reference Pa, velocities m/s, full porosity, K in m² and cF in 1/m.
  2D additionally records hydraulic radius m, mean cell/wall lengths m, inlet
  reference density, port extents m, prepared geometric thermal inlet masks,
  optional cell drag, and the environment-resolved convergence mode. The
  numerical constructor receives converted legacy length keywords only after
  geometry/drag prediction has been bypassed. A maps physical x onto SIMPLE y;
  B reverses physical y. The flow mesh can have port-aligned transverse widths
  even where the original thermal screening mesh is uniform. This inherited
  distinction is preserved explicitly.
- `parameters.rejection`: null, or the original cold 1D choke reason. A rejected
  preparation still contains real geometry and coefficients and can cross a
  file boundary; execution does not invent a thermal state for it.
- `metadata`: actual D-F method/override settings and, for 3D, resolved roughness
  mode and roughness in m. `geometry_fields` contains source cell/wall lengths
  in m for provenance; changing geometry must go through preparation to update
  all dependent coefficients. `config_snapshot` is provenance only and may be
  deleted before solving. No solver consults it.

The 2D model retains its warning when a caller labels a fluid as non-air: its
actual physics remains air/air and the warning is also stored in the result.
The supported flow mapping is +x A / -y B. This extraction does not introduce
other orientations or 3D partial ports. The 3D B flow remains frozen after the
cold solve. Its hot A seed and post-solve envelope gates retain their original
rejection semantics. No refinement or surrogate prediction occurs in execution.

## FieldResult and metrics

Fields contain raw last-return Ta/Tb/Ts in K when thermal execution occurred,
and the six prepared thermal coefficients with units and physical axes.
`pressure_evidence` records native gauge P, absolute reference, SIMPLE-axis
widths, and the original inlet/outlet averaging fractions. `boundary_fluxes`
records native staggered velocities, density and geometric fractions;
`metadata.thermal_transport` records the actual last thermal cp-density/face
inputs. `metadata.flow_coefficients` holds the drag, porosity and viscosity
actually present on each flow solver. Model configuration and resolved physical
inputs are retained even when the Case files are removed.

The 2D air screen declares `energy_formulation=conservative_air_model_h`.
All density-loop counts use the existing air cp(T) integral enthalpy kernel
with full native staggered mass fluxes, including cross-flow. The recorded
thermal transport includes `model_fluids` and `mass_flux_A/B`, each face pair
in physical x/y axes and kg/(m s) for unit depth. B-side temperature and density
updates reverse the physical y axis when mapped to the SIMPLE stream axis.
This model choice was approved on 2026-09-11; historical temperature-form
screening evidence and frozen references are retained separately.

The 3D air-air frozen-B screen also declares this formulation, following the
explicit 2026-09-11 screening-only approval. Its three native mass-face arrays
per side are in physical x/y/z axes, kg/s. B's cold flow/density remains frozen;
the existing air integral-enthalpy kernel consumes both native mass-face tuples.
This does not change other fluids or the full experimental calculation routes.

The postprocessor independently computes:

- Q = sum(h_vB × (Ts − Tb) × cell measure), W/m in 2D and W in 3D.
- dP_A/B from native P with the original 2D fraction thresholds or 3D geometric
  area weights, Pa. No pressure-face extrapolation is substituted.
- Solid mass = sum((1 − eps) × rho_s × cell measure), kg/m or kg.

Screening has no newly asserted Tout, boundary heat-balance or mass-imbalance
metric. Those return `unsupported`. The CLI screening postprocess success gate
requires Q, both dP values and solid mass; the full-model gate is unchanged.
3D W and kg are divided by the original physical `Lz` only in the application.
The original 2D manufacturability addition, dP cap and failure tuples stay in
`optimization.evaluator`; the 3D bounded invalid tuple stays in its wrapper.

`run_status` retains native SIMPLE/thermal/outer verdicts and the configured
screening identity. A one-sweep 2D isothermal screen has no required outer check;
a capped 3D outer loop remains unconverged. `physical_validation` remains
`unestablished` even when the chosen numerical criteria pass. Legacy core
results additionally apply their original finite-metric conjunction.

An archive may have `execution='rejected'` only with false convergence, a reason
and a rejection stage (`pre_solve`, `initial_flow`, `hot_reseed`, or
`post_solve_envelope`). Available fields keep their actual state; absent thermal
fields stay absent. Hot-reseed density/viscosity are labelled as refreshed but
not re-solved. Q/dP are invalid, while real geometry mass is still available.
Cancelled/failed runs are not accepted as completed or rejected archives.
The core facade maps unavailable rejected Q/dP back to its historical NaNs;
JSON metrics use null plus explicit status/reason.

Gradients and adjoints are not implemented. The examples exercise public forward
calls and explicitly supplied effective fields, without private solver mutation.

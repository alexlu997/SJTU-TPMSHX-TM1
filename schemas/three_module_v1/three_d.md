# 3D producer contract — implementation v1

Preparation emits the actual SI grid: physical `(x,y,z)` cell widths and edges,
including refinement. `parameters.prepared` contains axis maps, opening
fractions, geometry and inlet properties. The backend validates these against
the supplied grid and consumes them without calling preprocessing. The
configuration snapshot is provenance only. Model roles resolve the same four
versioned resources as 2D; unknown versions fail before execution.

Design fields have `(Nx,Ny,Nz)` shape: `L_field_m/t_field_m` in m, `K_m2` in
m², `cF_per_m` in 1/m, `K_ss` in W/(m K), and dimensionless total/per-side
porosity. Existing uniform and xy-extruded zoning are supported. Uniform
geometry must agree with scalar inputs; xy zoning cannot introduce z variation.
Discrete zone bounds select physical x/y cell centres on the prepared mesh,
including refined grids, rather than a fraction of cell indices. Existing
default values, later-zone overwrite order and sigma=2 smoothing are retained.
The existing B-side uniform D-F closure remains unchanged. This contract does
not introduce arbitrary spatial D-F behavior for that side.

FieldResult contains the last raw thermal temperatures and input heat-transfer
coefficients, with field units, physical axes and state. True-h thermal
pressure is captured separately from final SIMPLE gauge and property/report
pressure. Final gauge pressure is retained in solver coordinates together with
widths, true opening fractions and the axis map for exact face extrapolation.

Presentation temperatures (`Ta/Tb/Ts_display`) and `P_fA/P_fB_display` are
copied from the existing display return, without substituting property-pressure
fields. Cell velocities `uc/vc/wc` for each side and `vmag_A/B` use m/s in
physical axes; `chi_B` is dimensionless. Each has explicit field metadata and
survives the same result archive. These display fields never determine metrics.

Thermal mass faces use physical axes, signed along positive x/y/z, kg/s, with
full face area and per-side porosity already included. Model-h evidence stores
six outward boundary energy arrays per side in W, captured from the existing
thermal face operator. True-h evidence stores native h, inlet h (J/kg) and the
actual last thermal mass faces. Legacy temperature mode has no complete
captured enthalpy certificate and that reduction remains explicitly unsupported.

Formal `Q=abs(Q_A)` uses the last thermal state (`native_boundary_v1`). True-h
duty is computed from saved native h, inlet h and the actual thermal mass
faces. Model-h duty integrates the native outward energy arrays and retains
the boundary-completeness check in `diagnostics.model_h_balance.sides`.
Tout uses raw thermal temperature and positive outward thermal mass at the
configured outlet. Neither Q nor Tout is reconstructed from the final flow's
property-pressure state. Formal dP separately uses final SIMPLE pressure,
physical-face extrapolation and geometric open-area weights (`pressure_face_v1`).

The backend's historical final-report summaries and `reporting_reference`
remain available to their existing consumers. They are distinct from formal
offline metrics; retained report metadata supplies outlet direction without
requiring a second mass or enthalpy reconstruction.

All dimensional duties here are W and mass flows kg/s. No division by depth
occurs. Numerical convergence remains independent from metric availability.
Solid mass requires an explicit density; conductivity cannot supply it.

## Fixed thermal geometry and calibration

`parameters.thermal_geometry` records uniform geometry and (for zoned cases)
A_0 (1/m), D_h (m) and epsilon fields on physical x/y/z cells. It includes the
asymmetric split and side/reference A_0/D_h values from the existing 128-point
geometry calculation. Preparation retains inlet-range observations without
storing redundant initial h_v arrays; current velocity/temperature-dependent
Nu and property evaluations remain in execution. Older optional
`air_bulk_hv.A/B` fields are still validated when reading a saved Case but are
not consumed by execution; the solver does not invoke tpms_compute again.
Missing prepared execution fields fail explicitly; old intermediate Case files
must be prepared again rather than silently rebuilt inside the solver.

`roughness_resolved` records the selected mode and roughness length `eps_m` in
metres. Receiver environment settings cannot replace it. Experimental
`df_application.A/B` records the resolved positive scalar correction factors
and campaign/applicability metadata, or is null in CFD mode. Runtime applies
those fixed factors to the supplied K/cF fields and reports the actual base and
applied coefficients; it does not reselect or reevaluate calibration. Changing a
valid K field remains an effective numerical input. The original A projection
and scalar-mean B convention are preserved. All SIMPLE grids receive the actual
prepared widths, including uniform grids. Physical fields are permuted into
each side's solver axes; negative flow also reverses the streamwise widths,
porosity and A-side projected K/cF rows so local inlet index zero corresponds
to the physical inlet face.

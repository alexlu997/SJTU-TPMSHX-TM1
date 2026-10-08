# TM1 public data contract

[中文](README.zh-CN.md) | [English](README.md)

This document defines the public data contract. Current implementation and
acceptance status are tracked in [capabilities](../../docs/capabilities.en.md).
The contract does not claim that each producer, backend or file codec is implemented.
Original requirements and node evidence stay in [fixed history](../../docs/history/README.en.md).

## Shared rules

Public preparation records `CaseData.metadata.provenance`: package version,
source repository revision and tracked-change flag, plus configured raw-data
repository revision and the separate `data-revision.txt` declaration. Public
execution keeps that preparation record and adds its own entry snapshot
under `FieldResult.metadata.provenance.execution`. Model versions stay in
`model_refs`. Backend/schema labels are not code revisions. YAML/HDF5 keep
these records without querying Git during loading or postprocessing.

This is repository context, not a per-file data-use manifest or a claim that
untracked files are versioned. Source installs without Git explicitly record revision unavailable. They keep package version. A missing original preparation record is `not_recorded`. Neither condition is filled from a later
checkout or silently replaced with the declared data pin.

Mappings have string keys. Payloads contain only scalar data, numeric/boolean
arrays, sequences and nested mappings. Functions, live instances and object
arrays are rejected, including inside model parameters and result metadata. Arrays are detached onto immutable storage. Solver work arrays are separate
copies.

Nonfinite diagnostics are kept, but an available engineering
metric must be finite. Missing/invalid metrics have no value and a reason.

`schema_version` identifies the data schema. Model and metric definition
versions are separate. Unknown versions must be rejected at the corresponding
reader/resolver. Callbacks belong exclusively to `RunControl`, never to files.

## CaseData

| Field | Authority and consumer |
| --- | --- |
| `case_id`, `schema_version` | Identity and supported schema. |
| `config_snapshot` | Detached input provenance, including explicitly named legacy mm fields. It is not a replacement for the prepared problem. |
| `grid` | Prepared physical grid in real coordinates, SI spacings and boundary support. The solver can reorder axes but can not select a different mesh. |
| `design_fields` | Prepared spatial geometry and fixed coefficients. Consumers must use supported data or explicitly reject it, never ignore it. |
| `parameters` | Resolved physical and numerical settings produced by preprocessing, excluding callbacks and live model/solver instances. |
| `model_refs` | Named, versioned model resources with detached parameters and applicability. Runtime resolution occurs in the receiving process. |
| `metadata` | Preparation provenance, mode/capability declaration and source revisions. Not an implicit alternative input channel. |

`from_compute_config` captures provenance only. A case becomes runnable only
after a concrete preprocessor supplies and validates the complete prepared
grid, parameters, boundary and model data for its declared mode. Empty
containers used by contract tests are synthetic, not runnable cases.

The producing module must document each concrete key, its source, units,
shape and consumer before it can claim contract acceptance. Raw input
snapshots do not authorize ambiguous units in prepared data.

## FieldResult

| Field | Authority and consumer |
| --- | --- |
| Identity/backend/version | Run identity plus source case and actual backend. |
| `grid` | Actual native real-coordinate grid and topology. |
| `fields` | Native temperature, pressure and velocity data. Display/refined fields use separate names. |
| `field_metadata` | For each exported field: unit, location, coordinates and state time point. |
| `boundary_fluxes` | Signed mass and energy transport on the actual boundary. Areas are already included. Summary Q/Tout are not substitutes. |
| `pressure_evidence` | Gauge fields/reference offsets, measurement faces, native spacing and extraction rule needed to reproduce each reported pressure drop. |
| `run_status` | Execution, convergence, physical-domain and screening/validation state, residuals and warnings. These verdicts stay distinct. |
| `model_refs`, `metadata` | Models and their provenance, original result metadata, code/data revision and required resolved input provenance. |

Result declarations must agree: `grid.dimension` is authoritative when present,
with `metadata.dimension` usable for partial in-memory evidence. If both are
present they must match. An explicit `quantity_basis` must be `per_unit_depth`
for 2D or `total` for 3D. Omitted declarations are not added to archived data. Postprocessing requires a known 2D/3D dimension and supports `full` and
`quick_design`. The retired `screening_2d` and `screening_3d` modes stay
readable in archives but cannot execute or recompute metrics.

Only an omitted `mode` defaults to `full`. Unknown explicit modes can be archived unchanged, but current
postprocessing rejects them before reducing any metrics. Archiving a partial
or unconverged result does not show that it is executable or validated.
Missing evidence for individual metrics keeps its existing explicit status.

Native staggered faces must describe one coherent positive cell shape and
match each recorded grid axis. 3D model-h requires all six shaped boundary
planes, including zero faces. Structural defects invalidate only metrics that
consume that evidence. Missing whole evidence stays insufficient data.
Coherent partial in-memory evidence and complete zero transport stay valid.

The full 2D/3D outlet temperature uses last-main raw temperature and positive outward
signed mass over true openings. Backflow stays in the stored signed flux for
conservation. Never multiply by heat capacity or face area again. Pressure
state and display offsets stay explicitly different when the previous path used
different anchors. Richardson data is labelled separately from the main solve.

## MetricSpec and PerformanceResult

Q supports W (total duty) and W/m (per-depth duty). Mass supports kg and kg/m. Pa and K keep their usual meaning. Unit choice is explicit in each metric. 2D duty becomes total W only by multiplication by an explicitly supplied
physical depth in metres.

3D totals are divided by actual Lz only when an
application requests per-depth values. There is no default specimen thickness.

Known side-specific names use the same unit contract as their family:
`dP_A/B` require Pa, `T_out_A/B` require K, and heat duties require W or W/m.
Each metrics mapping key must match its spec name or its explicit family name
(for example, `dP_A` accepts `dP_A` or `dP`, never `dP_B` or `T_out`).
Unknown extension metrics keep their own matching key/spec name. These checks
apply to in-memory results and JSON input. Incompatible units are rejected,
not converted or relabeled. Historical definition versions stay readable.

Metric definition versions must also identify the reported side/sign,
pressure measurement rule and thermal time point. A finite result from an
unconverged run does not become a validated metric merely because evaluation
finished. `available`, `insufficient_data`, `unsupported` and `invalid` are
metric statuses. The original run verdict stays in FieldResult.

Full-compute `native_boundary_v1` defines `Q` as `abs(Q_A)` from the main
thermal boundary transport. `Q_A`/`Q_B` are signed heat loss, positive for a
stream releasing heat. `energy_imbalance_rel` uses those same native duties. Outlet temperature and mass flow use the matching signed thermal mass faces. The separately named 2D `Q_richardson_A/B` keep the accepted absolute-duty
extrapolation.

They do not replace main-grid metrics. Each definition is saved
in `MetricSpec.description` and `definition_version`, including JSON exports.

Full-compute pressure drops use `pressure_face_v1`, the geometric-area-weighted
difference between extrapolated physical inlet and outlet face pressures. An explicit request for the former full-compute metric definition is unsupported
by current evaluation. Previous saved metrics stay readable with their original
definition. Re-evaluate the native result for the current GUI mapping. This consumption check includes side duties, temperatures and displayed
balance metrics. Multi-condition aggregation also requires the current signed
`Q_B` and physical-face pressure definitions, even when both compared records
share the same previous definition.

Equivalent family/side names do not change
the metric's meaning. Declared result dimensions constrain native heat units.
Aggregation never infers a missing physical thickness.

## RunControl and module ports

The public function ports are `preprocess.api.prepare_case(config, case_id=...)
-> CaseData`, `solvers.api.run_case(case, control) -> FieldResult`, and
`postprocess.api.evaluate(result, metric_spec) -> PerformanceResult`. Runtime progress/cancellation
callbacks are passed separately. Explicit cancellation raises the existing
`CancelledError`. Unrelated callback failures stay their original errors. `iteration(label: str)` carries the existing outer-iteration label.

`residual(side: str, index: int, value: float)` carries 2D SIMPLE observations. Consumers can observe residuals through RunControl.

These observations do not change
stopping criteria and are never persisted into CaseData or FieldResult. The formal HDF5 codecs and per-mode capability/field tables define the
supported file handoff. See the current architecture and acceptance records.

## Application payload (current v1 draft)

Case metadata `model_metadata.sco2_nu` and `notices` carry the resolved model's
presentation provenance and explanatory strings. Current 2D/3D producers emit
these fields. Experimental `alpha_D/alpha_G` are the total effective Nu
coefficients applied one time to the selected CFD base. There is no serialized
extra `beta` factor. Explicit current-model selection resolves
`configs/sco2_effective_nu.json` through `sco2_effective_nu_config()`. Its version,
source and applicability travel with the values.

Loading a saved configuration
or prepared Case keeps its own parameters rather than substituting a newer
resource. Custom and historical experimental parameters still require their
own provenance. The generic `cfd_smooth` default is unchanged. See
[model resources](../../docs/model-resources.en.md#sco2-有效-nu-系数). This development draft has not been released as a stable archive
format. Earlier draft fixtures do not show backward compatibility.

FieldResult additionally records `design_mode`, those model fields, and
`application`. The `application` mapping contains:

- `coeffs`: Kff in W/(m K), Kss in W/(m K), and hv in W/(m3 K).
- `props`: rho in kg/m3, mu in Pa s, and cp in J/(kg K).
  It also records inlet speed in m/s and inlet T in K.
- 2D `zones`: axis, original statistics and bounds, with their existing explicit field spellings.

Values come from the actual runtime state. Absent historical
3D audit coefficients stay null. Native coefficient fields stay separately
available under `fields`. This payload only supports the legacy application
view. Numerical postprocessing does not use it.

Native and display arrays keep
separate field names and per-field metadata. `outer_iteration(current, budget)`
is a nonpersistent RunControl callback. It keeps the native 3D UI counter.
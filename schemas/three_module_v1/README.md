# TM1 public data contract

Status: G10 repair in progress. This is the contract for the module work;
it is not a claim that every producer, backend or file codec is implemented.
The source requirements remain in `docs/plans/three-module-graph`.

## Shared rules

Public preparation records `CaseData.metadata.provenance`: package version,
source repository revision and tracked-change flag, plus configured raw-data
repository revision and the separate `data-revision.txt` declaration. Public
execution preserves that preparation record and adds its own entry snapshot
under `FieldResult.metadata.provenance.execution`. Model versions remain in
`model_refs`; backend/schema labels are not code revisions. YAML/HDF5 preserve
these records without querying Git during loading or postprocessing.

This is repository context, not a per-file data-use manifest or a claim that
untracked files are versioned. Source installs without Git explicitly record
revision unavailable (while retaining package version), and a missing original
preparation record is `not_recorded`. Neither condition is filled from a later
checkout or silently replaced with the declared data pin.

Mappings have string keys. Payloads contain only scalar data, numeric/boolean
arrays, sequences and nested mappings. Functions, live instances and object
arrays are rejected, including inside model parameters and result metadata.
Arrays are detached onto immutable storage. Solver work arrays are separate
copies. Nonfinite diagnostics are retained, but an available engineering
metric must be finite; missing/invalid metrics have no value and a reason.

`schema_version` identifies the data schema. Model and metric definition
versions are separate. Unknown versions must be rejected at the corresponding
reader/resolver. Callbacks belong exclusively to `RunControl`, never to files.

## CaseData

| Field | Authority and consumer |
| --- | --- |
| `case_id`, `schema_version` | Identity and supported schema. |
| `config_snapshot` | Detached input provenance, including explicitly named legacy mm fields. It is not a replacement for the prepared problem. |
| `grid` | Prepared physical grid in real coordinates, SI spacings and boundary support. The solver may reorder axes but may not choose a different mesh. |
| `design_fields` | Prepared spatial geometry and fixed coefficients. Consumers must use supported data or explicitly reject it, never ignore it. |
| `parameters` | Resolved physical and numerical settings produced by preprocessing, excluding callbacks and live model/solver instances. |
| `model_refs` | Named, versioned model resources with detached parameters and applicability. Runtime resolution occurs in the receiving process. |
| `metadata` | Preparation provenance, mode/capability declaration and source revisions; not an implicit alternative input channel. |

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
| `fields` | Native temperature, pressure and velocity data; display/refined fields use separate names. |
| `field_metadata` | For each exported field: unit, location, coordinates and state time point. |
| `boundary_fluxes` | Signed mass and energy transport on the actual boundary; areas are already included. Summary Q/Tout are not substitutes. |
| `pressure_evidence` | Gauge fields/reference offsets, measurement faces, native spacing and extraction rule needed to reproduce each reported pressure drop. |
| `run_status` | Execution, convergence, physical-domain and screening/validation state, residuals and warnings. These verdicts remain distinct. |
| `model_refs`, `metadata` | Models and their provenance, original result metadata, code/data revision and required resolved input provenance. |

The 2D outlet temperature uses last-main raw temperature and positive outward
signed mass over true openings. Backflow stays in the stored signed flux for
conservation. Never multiply by heat capacity or face area again. Pressure
state and display offsets remain explicitly different when the old path used
different anchors. Richardson data is labelled separately from the main solve.

## MetricSpec and PerformanceResult

Q supports W (total duty) and W/m (per-depth duty); mass supports kg and kg/m.
Pa and K retain their usual meaning. Unit choice is explicit in each metric.
2D duty becomes total W only by multiplication by an explicitly supplied
physical depth in metres. 3D totals are divided by actual Lz only when an
application requests per-depth values. There is no default specimen thickness.

Metric definition versions must also identify the reported side/sign,
pressure measurement rule and thermal time point. A finite result from an
unconverged run does not become a validated metric merely because evaluation
finished. `available`, `insufficient_data`, `unsupported` and `invalid` are
metric statuses; the original run verdict remains in FieldResult.

## RunControl and module ports

`Preprocessor.build(config) -> CaseData`, `Solver.run(case, control) ->
FieldResult`, and `Postprocessor.evaluate(result, metric_spec) ->
PerformanceResult` are independent ports. Runtime progress/cancellation
callbacks are passed separately. Explicit cancellation raises the existing
`CancelledError`; unrelated callback failures remain their original errors.
`iteration(label: str)` carries the existing outer-iteration label;
`residual(side: str, index: int, value: float)` carries 2D SIMPLE observations.
The GUI adapter owns its display buffer. These observations do not alter
stopping criteria and are never persisted into CaseData or FieldResult.
Formal codecs and per-mode capability/field tables remain required before
G10 consumers and D/I/V nodes can be accepted.

## Application payload (current v1 draft)

Case metadata `model_metadata.sco2_nu` and `notices` carry the resolved model's
presentation provenance and explanatory strings. Current 2D/3D producers emit
these fields. This development draft has not been released as a stable archive
format; earlier draft fixtures do not establish backward compatibility.
FieldResult additionally records `design_mode`, those model fields, and
`application`: `coeffs` (Kff in W/(m K), Kss in W/(m K), hv in W/(m3 K)), `props`
(rho in kg/m3, mu in Pa s, cp in J/(kg K), inlet speed in m/s, inlet T in K), and
2D `zones` (axis, original statistics and bounds with their existing explicit
field spellings). Values come from the actual runtime state; absent historical
3D audit coefficients stay null. Native coefficient fields remain separately
available under `fields`. This payload only supports the legacy application
view; numerical postprocessing does not use it. Native and display arrays retain
separate field names and per-field metadata. `outer_iteration(current, budget)`
is a nonpersistent RunControl callback preserving the native 3D UI counter.

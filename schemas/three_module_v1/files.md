# File transport v1

`case.yaml` is a safe YAML manifest with schema version, record kind, Case ID
and a sibling `case.h5` filename. The HDF5 file is authoritative prepared data;
copy both files together. A direct `.h5` entry is also supported. YAML/JSON
source configuration is a different input to the public preparation stage.
No file loader reruns preparation or reconstructs a Case from its snapshot.

HDF5 stores root schema/kind attributes, a UTF-8 JSON descriptor and numeric
array datasets under `/arrays`. The descriptor tags mappings, sequences,
ModelRef records, bytes and nonfinite diagnostic scalars. Arrays carry exact
dtype/shape descriptors and are actual HDF5 datasets, not pickle/NPZ payloads.
Unknown versions, missing record fields, changed dtype/shape, object arrays,
external links and virtual/external datasets are rejected. Restored arrays
have immutable backing buffers. Physical grid axes, SI widths/edges and field
metadata are checked at the file boundary.

`results.h5` archives completed execution, including `converged=False`; failed
or cancelled partial data cannot be saved as a normal completed result.
`metrics.json` uses standard JSON: unavailable values are null with an explicit
reason and status, finite available values retain MetricSpec units/version.
Nonfinite diagnostics remain in HDF5, never converted to a valid metric.

The public stage commands are:

```
python -m sjtu_tpmshx.cli prepare config.json case.yaml --case-id example
python -m sjtu_tpmshx.cli solve case.yaml results.h5
python -m sjtu_tpmshx.cli postprocess results.h5 metrics.json
python -m sjtu_tpmshx.cli run config.json output-directory --case-id example
```

Use the interpreter in the worktree's `.venv-path` for these commands.
Exit 0 means that stage completed its stated checks; solve/run returns 2 for
nonconvergence, postprocess returns 2 if a core requested metric is unavailable,
and cancellation returns 130. Postprocess exit 0 does not change the archived
run's numerical or physical status. Stage exceptions propagate as failures.

`results.vtk` is a legacy ASCII rectilinear grid: physical coordinates in m,
cell data in native order and an embedded UTF-8 JSON field-data array storing
units, axes, states and run status. 2D uses a single z coordinate, without
inventing an extrusion depth. Field and metric interchange uses HDF5, VTK and
JSON; visualization reads the recorded fields and their physical axes.

Prepared `_environment` records the active SIMPLE convergence mode,
pressure shooting, variable rho-cp, sCO2 compressibility, acceleration flags
and solid-tortuosity override provenance. Runtime reads frozen overrides rather
than the receiver's environment. The prepared solid conductivity owns its
actual values. Profiling/CPU scheduling settings are execution concerns.

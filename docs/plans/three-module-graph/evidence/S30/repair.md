# Prepared 3D execution and native result extraction

Local integration on `codex/tm1/s30-repair`, following `2768a5c`.
P30/S30/R30/I30/I55 and H10 are coordinated here; full graph acceptance,
formal I/O, public application routing and remote CI remain pending.

The pure preprocessor owns the actual grid, design fields, coordinate maps,
opening fractions and inlet properties. Numerical construction consumes them.
Existing pipeline imports call the same implementation. Offline evaluation
imports no numerical solver and recomputes metrics from captured field data.

## Baseline observations

All five standard B30 values match its historical record exactly:
Q=338.48590825124325 W; dP_A=1945.2469619113485 Pa;
dP_B=3044.9340885522665 Pa; Tout_A=359.19558834036184 K;
Tout_B=344.9435887813375 K. Converged=True, final outer index=2.
Offline reductions produced those same values from native arrays.
The historical enthalpy_imbalance_rel=NaN remains a separate original record;
new native model-h duty imbalance=8.106955909100542e-06 does not replace it.

The B30 local z/x-port mixed members also match their historical records:

| pair | Q W | dP_A Pa | dP_B Pa | Tout_A K | Tout_B K | converged |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| sCO2/water | 446.18297095154264 | 10.830560496870033 | 77.41486070349472 | 397.8906942537216 | 306.47625593626805 | False |
| air/sCO2 | 55.016463347870655 | 21.036659508491287 | 39.14516252410696 | 344.11382065585707 | 301.4963718953477 | False |

Offline Q/dP/Tout assertions used rtol=1e-12, atol=1e-12. Both passed;
no convergence threshold or extrapolation policy changed. Existing Nu-domain
and sCO2 qualification warnings remain present. Solid mass is unavailable
without density; it is not silently assigned a material.

## Failure provenance and local checks

- Initial typed entry import failed twice, native exit 1: moved
  `_per_side_eps_override` and `_real_outlet_slice` were still imported from
  the flux module. Corrected to their pure model owners before any solve ran.
- Initial targeted suite: 1 failed, 32 passed, native exit 1. The import graph
  found models/asym_split importing solvers/asym_geometry on its offset path.
  Corrected the import; no graph sanction or relaxation added.
- Standard typed B30 run and mixed-member script: native exit 0.
- Prepared 3D isolation and execution-data checks: 2 passed, native exit 0.
- Follow-up layering, existing pipeline reexports and prior 2D postprocessing:
  9 passed in 10.38 s, native exit 0.

The configured 71-package lock and pip check passed before this integration.
No dependency or shared environment was installed or changed.

- Native 3D model-h transport, asymmetry and hand-calculated offline metrics:
  72 passed, 7 retained warnings in 129.12 s, native exit 0.
- Final prepared-data checks after consistency validation: 2 passed in 1.26 s,
  native exit 0. Ruff selected changed files: all checks passed.

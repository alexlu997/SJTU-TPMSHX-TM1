# B20 2D baseline selection

Baseline commit: `5f1cafb` (TM1 `main` at selection time).

This selection intentionally uses existing small, representative cases rather
than a Cartesian product.  It makes no solver, correlation, data, or threshold
change.

| coverage | existing anchor | planned evidence |
| --- | --- | --- |
| Standard 2D pipeline, air/air, full faces | `test_pipeline_2d_smoke.py::test_pipeline2d_run_returns_compute_result` | `20x40`, Gyroid 7 mm / 0.4 mm, A `+x`, B `-y`; capture Q, both dP, outlets, field shapes, convergence and energy imbalance. |
| Physical port alignment and flow orientation | `test_port_grid_alignment_2d.py` | retain direction pairs `(0,2)`, `(2,0)`, `(1,3)`, `(3,1)` plus the existing partial-port construction; capture resolved grid and port-edge placement. |
| Mixed fluids and local ports | `test_pipeline_2d_smoke.py::test_pipeline2d_mixed_sco2_custom_ports` | retain one sCO2/water member and one air/sCO2 member, `8x6`, `max_outer_ltne=3`, `max_iter_simple=500`; record extrapolation policy and terminal validity. |
| Rejection path | `test_pressure_invalid_flag.py` and `test_robustness_gates.py` | retain strict `P_out^2 <= 0` invalid detection plus config/port validation; rejected inputs must remain rejected. |

The three pipeline members are marked `slow`; they are not included in the
current E00 `not slow and not heavy` CI gate.  Matched-lock numerical runs,
their output values, and comparison tolerances remain pending.  A passing
synthetic/unit check is not evidence for a physical pipeline baseline.

## First execution: standard air/air member

At `5f1cafb`, the checked Python 3.13 environment passed the exact lock check
(71 active packages) and `pip check`.  The existing smoke test passed:

```
MPLCONFIGDIR=.cache/matplotlib XDG_CACHE_HOME=.cache/xdg \
  /Users/luwenhuan/.venvs/sjtu-tpmshx-py313/bin/python -m pytest \
  sjtu_tpmshx/tests/test_pipeline_2d_smoke.py::test_pipeline2d_run_returns_compute_result \
  -q --timeout=600 --timeout-method=thread
```

Result: `1 passed in 17.84s`.  A second direct run of the same configured
pipeline produced the following current behavior record:

| quantity | observed value |
| --- | --- |
| grid | wall-refined `36 x 56` from nominal `20 x 40` |
| `Q_W` | `31084.383039293898` |
| `dP_A_Pa` / `dP_B_Pa` | `1665.684133288371` / `1212.2971501411819` |
| `T_out_A_K` / `T_out_B_K` | `304.2430037398466` / `334.69721144655796` |
| converged | `True` after five density/thermal coupling steps |
| `energy_imbalance_rel` | `0.00020528272309235557` |

This is a captured behavior point, not an experimental-accuracy claim.  The
mixed-fluid/partial-port and rejected-input members remain pending and must not
be inferred from this air/air run.

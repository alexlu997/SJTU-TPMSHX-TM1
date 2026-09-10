# B30 3D baseline selection

Baseline commit: `5f1cafb` (TM1 `main` at selection time).

This selection preserves distinct 3D behaviors rather than treating `Nz=1` as
a substitute for the physical 3D path.  It makes no numerical-code change.

| coverage | existing anchor | planned evidence |
| --- | --- | --- |
| Standard 3D orchestration | `test_pipeline_3d_e2e.py::test_pipeline3d_run_end_to_end` | `8x6x4`, air/air, full z-face ports; capture Q, both dP, outlets, field presence and terminal status. |
| Incompressible-side dispatch | `test_pipeline_3d_e2e.py::test_pipeline3d_water_a_runs_through_incompressible_path` | water/air with the same 3D grid; preserve its separate property path. |
| Local z/x ports and mixed fluids | `test_pipeline_3d_e2e.py::test_pipeline3d_mixed_sco2_z_and_x_ports` | retain sCO2/water and air/sCO2 members at `4x4x4`; record extrapolation policy and validity. |
| Optimizer kernel | `test_evaluator_3d_conservative.py` | retain the conservative 3D evaluator, its `Q/Lz` normalization and nontrivial finite outputs. |
| Port geometry and rejection | `test_port_face_area_3d.py`; `test_envelope_integration_3d.py` | retain six-direction face-area/mass-target behavior and choke raise/warn validity states. |

All pipeline and evaluator members above are currently marked `slow`; they are
outside E00's `not slow and not heavy` CI gate.  Matched-lock execution,
captured values and comparison tolerance selection remain pending.  Unit-only
port geometry checks are not a physical 3D-solve baseline.

## First execution: standard air/air 3D orchestration

At `5f1cafb`, the checked Python 3.13 environment passed the exact lock check
(71 active packages) and `pip check`.  The selected existing smoke passed:

```
MPLCONFIGDIR=.cache/matplotlib XDG_CACHE_HOME=.cache/xdg \
  /Users/luwenhuan/.venvs/sjtu-tpmshx-py313/bin/python -m pytest \
  sjtu_tpmshx/tests/test_pipeline_3d_e2e.py::test_pipeline3d_run_end_to_end \
  -q --timeout=600 --timeout-method=thread
```

Result: `1 passed in 89.23s`.  A second direct run of the same `8x6x4`
configuration produced:

| quantity | observed value |
| --- | --- |
| `Q_W` | `338.48590825124325` |
| `dP_A_Pa` / `dP_B_Pa` | `1945.2469619113485` / `3044.9340885522665` |
| `T_out_A_K` / `T_out_B_K` | `359.19558834036184` / `344.9435887813375` |
| field shape | `(8, 6, 4)` |
| `converged` | `True` |
| `enthalpy_imbalance_rel` | `NaN` |

The existing smoke does not assert that residual slot.  Its `NaN` is retained
as an observed output and is not converted into a passing energy certificate.
Mixed-fluid/local-port, water-side, optimizer, and envelope members remain
separate evidence tasks.

## First execution: optimizer conservative-kernel route

`sjtu_tpmshx/tests/test_evaluator_3d_conservative.py` passed `1/1` in
`5.93 s` under the same lock.  This verifies the selected 3D optimizer route
returns finite, nontrivial per-depth heat duty, finite positive total pressure
drop, and finite positive per-depth mass using the conservative kernel.  It is
an application-path check, not a replacement for the pipeline result above.

## First execution: incompressible-side route

`test_pipeline3d_water_a_runs_through_incompressible_path` passed `1/1` in
`1.02 s` under the same lock.  Direct output for its `8x6x4` water/air member
was `Q_W=380.9425177465455`, `dP_A_Pa=3063.3582674551412`,
`dP_B_Pa=831.7037900623513`, `T_out_A_K=359.4307787916567`,
`T_out_B_K=340.7120087942667`, and `converged=True`.  As with the standard
air/air member, its `enthalpy_imbalance_rel` slot was `NaN`; it remains an
observed non-certificate rather than being masked by the test's finite-output
assertions.

## First execution: choked-input rejection

`test_choked_case_raises_by_default` passed `1/1` in `0.90 s` under the same
lock.  Its intentionally over-driven 3D air case raised `ChokedFlowError`
before a doomed solve, preserving the selected default rejection contract.
Warn-mode and B-side post-solve members remain unrun and are not implied by
this single rejection result.

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

# Follow a 2D heat exchanger case through the solver

[中文](README.md)

Start with the [2D air example](../examples/cpp/air_2d.cpp#L15-L17). It supplies the two inlet speeds, temperatures, pressures and core geometry. It prepares the case, solves it and reports engineering metrics.

| Step | Source | What to look for |
| --- | --- | --- |
| 1. Prepare the case | [2D prepare_case](../preprocess/preparation_case.cpp#L1083) | Geometry supplies porosity and hydraulic diameter. Preparation sets the ports and drag for both sides on the physical grid. For continuous 2D fields, it also calculates fluid pore porosity. |
| 2. Advance the solution | [Full2DRun::advance_impl](full_2d.cpp#L1095) | Follow outer_boundary, flow_boundary and thermal_boundary. The solver updates flow, advances temperature and checks convergence or the outer iteration limit. See the [2D SIMPLE implementation](simple_2d.cpp) for the velocity and pressure iterations. |
| 3. Evaluate the fields | [evaluate](../postprocess/result_stage.cpp#L1254) | The fields and their recorded data determine which metrics apply. The [metric functions](../postprocess/result_metrics.cpp) calculate heat duty and other quantities. The [balance functions](../postprocess/result_balance.cpp) check mass and energy conservation. |

**Where other runs branch**

- **3D** uses the same three stages. Follow the [3D example](../examples/cpp/run_3d.cpp) into [Full3DRun::advance_step](full_3d.cpp#L1505).
- **Quick Design** uses the [single-candidate example](../examples/cpp/quick_design.cpp) and the [Quick Design solver](quick_design_run.cpp), then evaluates the candidate result.
- **Pause and resume** use [Full2DRun::snapshot](full_2d.cpp#L1320) to read the iteration state. The [resume example](../examples/cpp/resume_2d.cpp) shows native state recovery. The desktop application resumes a saved run through [resume_loaded_run](../python/applications/execution/recovery.py#L78).

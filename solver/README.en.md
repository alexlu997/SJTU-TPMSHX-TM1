# Where to start in the solver

[中文](README.md)

| Calculation | Start with the caller | Follow the C++ solution |
| --- | --- | --- |
| Full 2D | [2D air case](../examples/cpp/air_2d.cpp#L32-L34) | [Full2DRun::advance_impl](full_2d.cpp#L1095) advances through the outer, flow and thermal iteration boundaries. Start in [simple_2d.cpp](simple_2d.cpp) for changes to the velocity or pressure iterations. |
| Full 3D | [3D case](../examples/cpp/run_3d.cpp#L20) | [Full3DRun::advance_step](full_3d.cpp#L1505) solves the initial flow on both sides, then updates temperature and flow. See [simple_3d.cpp](simple_3d.cpp) for 3D SIMPLE. |
| Quick Design | [Single candidate](../examples/cpp/quick_design.cpp#L13) | [solve_quick_design](quick_design_driver.cpp#L116) updates fluid properties on both sides and [calls the common temperature solver](quick_design_driver.cpp#L206). |

**Follow a complete 2D case.** Start in [preparation](../preprocess/preparation_case.cpp#L1021) for ports and drag on the grid. See [geometry](../geometry/geometry.cpp#L182) for porosity and hydraulic diameter. Follow the 2D solver above. Then open [evaluation](../postprocess/result_stage.cpp#L1164) for [heat duty and other metrics](../postprocess/result_metrics.cpp) and [mass and energy balances](../postprocess/result_balance.cpp).

## File tree by maintenance task

Each group gives a reading order. All files in the tree are directly under `solver/`.

<details>
<summary>Change a model or the solution procedure</summary>

For the velocity used in local Re and Nu, see the [2D](full_2d.cpp#L539) and [3D](full_3d.cpp#L877) implementations. For changes to a Nu correlation, read the common [nu_point](../numerics/fluid_properties.cpp#L371) function.

- Iteration order for full runs
  - [full_2d.cpp](full_2d.cpp) · [full_3d.cpp](full_3d.cpp)
- Property updates and thermal solution for one Quick candidate
  - [quick_design_driver.cpp](quick_design_driver.cpp)
- SIMPLE velocity and pressure iterations
  - [simple_2d.cpp](simple_2d.cpp) · [simple_3d.cpp](simple_3d.cpp)
- Pressure correction, candidate selection and convergence
  - [simple_pressure.cpp](simple_pressure.cpp) · [pressure_candidate.cpp](pressure_candidate.cpp) · [simple_convergence.cpp](simple_convergence.cpp)
- Model-h thermal equations
  - [model_h_2d.cpp](model_h_2d.cpp) · [model_h_3d.cpp](model_h_3d.cpp) · [model_h_common.hpp](model_h_common.hpp)
- Enthalpy driver, equation of state and sweeps
  - [enthalpy_driver.cpp](enthalpy_driver.cpp) · [enthalpy_eos.cpp](enthalpy_eos.cpp) · [enthalpy_sweeps.cpp](enthalpy_sweeps.cpp)
- Temperature equations and staggered discretization
  - [temperature_driver.cpp](temperature_driver.cpp) · [temperature_staggered.cpp](temperature_staggered.cpp) · [temperature_faces.hpp](temperature_faces.hpp) · [temperature_active_line.hpp](temperature_active_line.hpp)
- Finite-volume discretization for conservative energy
  - [conservative_energy.cpp](conservative_energy.cpp) · [energy_fv_rows.hpp](energy_fv_rows.hpp)
- Input checks for true-h
  - [true_h_preparation.cpp](true_h_preparation.cpp) · [true_h_preparation.hpp](true_h_preparation.hpp)
- 2D refinement and 3D field operations
  - [refinement_2d.cpp](refinement_2d.cpp) · [full_3d_fields.hpp](full_3d_fields.hpp)
- Iteration acceleration and linear solvers
  - [anderson.hpp](anderson.hpp) · [anderson_lapack.hpp](anderson_lapack.hpp) · [classical_amg.cpp](classical_amg.cpp) · [classical_amg.hpp](classical_amg.hpp) · [classical_amg_kernels.hpp](classical_amg_kernels.hpp) · [classical_amg_svd_lp64.cpp](classical_amg_svd_lp64.cpp) · [classical_amg_svd_lp64.hpp](classical_amg_svd_lp64.hpp) · [superlu_solve.c](superlu_solve.c) · [superlu_hooks.h](superlu_hooks.h)

</details>

<details>
<summary>Trace a caller into the solver</summary>

External C++ programs call the [public stage interface](../include/tpmshx/stages.hpp).

- Stage entries for 2D, 3D and Quick, respectively
  - [stage_run.cpp](stage_run.cpp) · [stage_run_3d.cpp](stage_run_3d.cpp) · [quick_design_run.cpp](quick_design_run.cpp)
- Prepared meshes and saved model parameters
  - [prepared_mesh.cpp](prepared_mesh.cpp) · [stage_saved_models.hpp](stage_saved_models.hpp)
- Full-run entries behind the stages and raw result queries
  - [full_2d_c_api.cpp](full_2d_c_api.cpp) · [full_3d_c_api.cpp](full_3d_c_api.cpp) · [stage_entries.hpp](stage_entries.hpp)
- Recipe identity and default queries
  - [model_h_algorithm_c_api.cpp](model_h_algorithm_c_api.cpp) · [energy_algorithm_c_api.cpp](energy_algorithm_c_api.cpp) · [temperature_algorithm_c_api.cpp](temperature_algorithm_c_api.cpp)
- Solver ABI version and the internal Quick Design solve
  - [solver_c_api.cpp](solver_c_api.cpp)

</details>

<details>
<summary>Find returned fields, run records and diagnostics</summary>

For the definition of heat duty, see the [metric functions](../postprocess/result_metrics.cpp).

- Capture of 2D and 3D field results
  - [stage_capture_2d.cpp](stage_capture_2d.cpp) · [stage_capture_2d.hpp](stage_capture_2d.hpp) · [stage_capture_3d.cpp](stage_capture_3d.cpp) · [stage_capture_3d.hpp](stage_capture_3d.hpp)
- Execution reports and stage records
  - [execution_report.cpp](execution_report.cpp) · [execution_report.hpp](execution_report.hpp) · [stage_records.hpp](stage_records.hpp)
- Closure ranges, property samples and physical balances
  - [closure_ranges.hpp](closure_ranges.hpp) · [closure_evidence_c_views.hpp](closure_evidence_c_views.hpp) · [property_sampling_c_views.hpp](property_sampling_c_views.hpp) · [physical_ledger_c_views.hpp](physical_ledger_c_views.hpp)
- Flow and thermal data views in full results
  - [simple_2d_c_views.hpp](simple_2d_c_views.hpp) · [simple_3d_c_views.hpp](simple_3d_c_views.hpp) · [model_h_c_views.hpp](model_h_c_views.hpp) · [enthalpy_c_views.hpp](enthalpy_c_views.hpp) · [temperature_c_views.hpp](temperature_c_views.hpp)

</details>

<details>
<summary>Trace a pause, checkpoint or resume</summary>

See the [2D snapshot](full_2d.cpp#L1320) or [3D snapshot](full_3d.cpp#L1767) for the iteration state. The [2D resume example](../examples/cpp/resume_2d.cpp) restores a native run. The desktop application calls [resume_loaded_run](../python/applications/execution/recovery.py#L78) to resume from disk.

- Encoding and decoding of full run state
  - [full_run_state.cpp](full_run_state.cpp)
- C interface and views for run state
  - [run_state_c_api.cpp](run_state_c_api.cpp) · [run_state_c_views.hpp](run_state_c_views.hpp)
- Validation of saved temperature state
  - [temperature_run_state.hpp](temperature_run_state.hpp)
- Build identifier for saved state
  - [write_state_build_id.cmake](write_state_build_id.cmake)

</details>

<details>
<summary>Find build and export settings</summary>

- Solver build, SuperLU configuration and exported symbols
  - [CMakeLists.txt](CMakeLists.txt) · [superlu-lu-only.cmake](superlu-lu-only.cmake) · [solver.exports](solver.exports)

</details>

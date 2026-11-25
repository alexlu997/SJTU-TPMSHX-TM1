# 从哪里读求解器

[English](README.en.md)

| 要读的计算 | 先看算例里的调用 | 再看 C++ 如何推进 |
| --- | --- | --- |
| 完整二维 | [二维空气工况](../examples/cpp/air_2d.cpp#L32-L34) | [Full2DRun::advance_impl](full_2d.cpp#L1095) 按外迭代、流动、热学三个边界推进。改速度或压力迭代，从 [simple_2d.cpp](simple_2d.cpp) 读起。 |
| 完整三维 | [三维工况](../examples/cpp/run_3d.cpp#L20) | [Full3DRun::advance_step](full_3d.cpp#L1505) 先求两侧初始流场，再推进热学和流场更新。三维 SIMPLE 在 [simple_3d.cpp](simple_3d.cpp)。 |
| 快速设计（Quick） | [单候选工况](../examples/cpp/quick_design.cpp#L13) | [solve_quick_design](quick_design_driver.cpp#L116) 按候选工况更新两侧物性，并[调用共用温度求解器](quick_design_driver.cpp#L206)。 |

**把二维工况读完整。** 从[前处理](../preprocess/preparation_case.cpp#L1021)看两侧端口和阻力如何落到网格上，从[几何计算](../geometry/geometry.cpp#L182)看孔隙率和水力直径。接着读表中的二维求解。最后进入[后处理](../postprocess/result_stage.cpp#L1164)，查看[换热量等指标](../postprocess/result_metrics.cpp)及[质量与能量收支](../postprocess/result_balance.cpp)。

## 按维护任务展开目录树

下面按阅读顺序分组。组内文件都在同一层 `solver/` 目录。

<details>
<summary>改模型或求解流程</summary>

局部 Re 和 Nu 取用的速度见[二维](full_2d.cpp#L539)和[三维](full_3d.cpp#L877)实现。改 Nu 关联式时，读共用的 [nu_point](../numerics/fluid_properties.cpp#L364)。

- 完整求解的迭代顺序
  - [full_2d.cpp](full_2d.cpp) · [full_3d.cpp](full_3d.cpp)
- Quick 单候选的物性更新与热求解
  - [quick_design_driver.cpp](quick_design_driver.cpp)
- 速度与压力的 SIMPLE 迭代
  - [simple_2d.cpp](simple_2d.cpp) · [simple_3d.cpp](simple_3d.cpp)
- 压力修正、候选解与收敛判据
  - [simple_pressure.cpp](simple_pressure.cpp) · [pressure_candidate.cpp](pressure_candidate.cpp) · [simple_convergence.cpp](simple_convergence.cpp)
- model-h 热方程
  - [model_h_2d.cpp](model_h_2d.cpp) · [model_h_3d.cpp](model_h_3d.cpp) · [model_h_common.hpp](model_h_common.hpp)
- 焓方程、状态方程和扫掠
  - [enthalpy_driver.cpp](enthalpy_driver.cpp) · [enthalpy_eos.cpp](enthalpy_eos.cpp) · [enthalpy_sweeps.cpp](enthalpy_sweeps.cpp)
- 温度方程与交错网格离散
  - [temperature_driver.cpp](temperature_driver.cpp) · [temperature_staggered.cpp](temperature_staggered.cpp) · [temperature_faces.hpp](temperature_faces.hpp) · [temperature_active_line.hpp](temperature_active_line.hpp)
- 守恒能量方程的有限体积离散
  - [conservative_energy.cpp](conservative_energy.cpp) · [energy_fv_rows.hpp](energy_fv_rows.hpp)
- true-h 输入检查
  - [true_h_preparation.cpp](true_h_preparation.cpp) · [true_h_preparation.hpp](true_h_preparation.hpp)
- 二维细化与三维场辅助函数
  - [refinement_2d.cpp](refinement_2d.cpp) · [full_3d_fields.hpp](full_3d_fields.hpp)
- 迭代加速与线性求解器（改数值方法时展开读）
  - [anderson.hpp](anderson.hpp) · [anderson_lapack.hpp](anderson_lapack.hpp) · [classical_amg.cpp](classical_amg.cpp) · [classical_amg.hpp](classical_amg.hpp) · [classical_amg_kernels.hpp](classical_amg_kernels.hpp) · [classical_amg_svd_lp64.cpp](classical_amg_svd_lp64.cpp) · [classical_amg_svd_lp64.hpp](classical_amg_svd_lp64.hpp) · [superlu_solve.c](superlu_solve.c) · [superlu_hooks.h](superlu_hooks.h)

</details>

<details>
<summary>查调用接口</summary>

外部 C++ 程序从[公开阶段接口](../include/tpmshx/stages.hpp)进入。

- 阶段入口，依次为二维、三维和 Quick
  - [stage_run.cpp](stage_run.cpp) · [stage_run_3d.cpp](stage_run_3d.cpp) · [quick_design_run.cpp](quick_design_run.cpp)
- 准备好的网格与保存的模型参数
  - [prepared_mesh.cpp](prepared_mesh.cpp) · [stage_saved_models.hpp](stage_saved_models.hpp)
- 阶段内部的完整求解入口与原始结果查询
  - [full_2d_c_api.cpp](full_2d_c_api.cpp) · [full_3d_c_api.cpp](full_3d_c_api.cpp) · [stage_entries.hpp](stage_entries.hpp)
- 算法标识与默认值查询
  - [model_h_algorithm_c_api.cpp](model_h_algorithm_c_api.cpp) · [energy_algorithm_c_api.cpp](energy_algorithm_c_api.cpp) · [temperature_algorithm_c_api.cpp](temperature_algorithm_c_api.cpp)
- 求解库 ABI 版本与内部 Quick Design 求解
  - [solver_c_api.cpp](solver_c_api.cpp)

</details>

<details>
<summary>查返回的场、求解记录和诊断</summary>

要改换热量的定义，直接看[后处理指标公式](../postprocess/result_metrics.cpp)。

- 二维和三维场结果的采集
  - [stage_capture_2d.cpp](stage_capture_2d.cpp) · [stage_capture_2d.hpp](stage_capture_2d.hpp) · [stage_capture_3d.cpp](stage_capture_3d.cpp) · [stage_capture_3d.hpp](stage_capture_3d.hpp)
- 执行报告与阶段记录
  - [execution_report.cpp](execution_report.cpp) · [execution_report.hpp](execution_report.hpp) · [stage_records.hpp](stage_records.hpp)
- 闭合关系的适用范围、物性采样与物理收支
  - [closure_ranges.hpp](closure_ranges.hpp) · [closure_evidence_c_views.hpp](closure_evidence_c_views.hpp) · [property_sampling_c_views.hpp](property_sampling_c_views.hpp) · [physical_ledger_c_views.hpp](physical_ledger_c_views.hpp)
- 完整结果中的流动和热学数据视图
  - [simple_2d_c_views.hpp](simple_2d_c_views.hpp) · [simple_3d_c_views.hpp](simple_3d_c_views.hpp) · [model_h_c_views.hpp](model_h_c_views.hpp) · [enthalpy_c_views.hpp](enthalpy_c_views.hpp) · [temperature_c_views.hpp](temperature_c_views.hpp)

</details>

<details>
<summary>查暂停、检查点和续算</summary>

从[二维快照](full_2d.cpp#L1320)或[三维快照](full_3d.cpp#L1767)看要保存哪些迭代量。[二维续算算例](../examples/cpp/resume_2d.cpp)演示原生恢复，桌面应用从 [resume_loaded_run](../python/applications/execution/recovery.py#L78) 恢复磁盘上的记录。

- 完整求解状态的编码与解码
  - [full_run_state.cpp](full_run_state.cpp)
- 状态的 C 接口和数据视图
  - [run_state_c_api.cpp](run_state_c_api.cpp) · [run_state_c_views.hpp](run_state_c_views.hpp)
- 温度迭代状态的校验
  - [temperature_run_state.hpp](temperature_run_state.hpp)
- 生成状态格式使用的构建标识
  - [write_state_build_id.cmake](write_state_build_id.cmake)

</details>

<details>
<summary>查构建与导出</summary>

- 求解库构建、SuperLU 配置和导出符号
  - [CMakeLists.txt](CMakeLists.txt) · [superlu-lu-only.cmake](superlu-lu-only.cmake) · [solver.exports](solver.exports)

</details>

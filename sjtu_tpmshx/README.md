# 主体源码：sjtu_tpmshx

[中文](README.md) | [English](README.en.md)

全部核心源码位于这个包内。首次配置、公开算例和启动步骤见[项目 README](../README.md#first-run)。
命令均从仓库根目录执行。完整模块边界和物理约束见[架构说明](../docs/architecture.zh-CN.md)。

## 四个计算入口

| 文件 | 公开入口 | 职责 |
| --- | --- | --- |
| [compute.py](compute.py) | `compute` | 主计算入口，校验配置并统一组织三个阶段；返回 CaseData、FieldResult 和 PerformanceResult |
| [preprocess/api.py](preprocess/api.py) | `prepare_case` | 准备实际网格、边界、设计场、模型资源和可移植运行输入 |
| [solvers/api.py](solvers/api.py) | `run_case` | 消费 CaseData，经 Python 绑定执行 C++ 数值求解，返回原生场和运行状态 |
| [postprocess/api.py](postprocess/api.py) | `evaluate` | 从 FieldResult 组织指标评估与资格结论，不重跑求解 |

```text
compute -> preprocess.api.prepare_case -> CaseData -> solvers.api.run_case -> FieldResult
                                                                       -> postprocess.api.evaluate -> PerformanceResult
```

`compute` 同时处理阶段进度、取消、耗时与警告。`postprocess/api.py` 将完整 2D/3D、Quick Design 评估及独立查询交给原生结果阶段。
`shared/_native_result_stage.py` 适配证据、NumPy 事件与返回对象；`postprocess/export.py` 负责导出。
当前正式计算支持矩形二维与长方体三维。公开输入和文件交接见[示例](../examples/three_module/)与[数据契约](../docs/contracts/three_module_v1/README.zh-CN.md)。
近似模式和扩展状态见[能力范围](../docs/capabilities.md)。

[原生阶段 SDK](../docs/native-stages.zh-CN.md)提供独立的 C++ 调用流程。
首条完整路径支持规定入口速度的均匀、对称二维 air/air。
准备 v2 为规定速度、均匀对称二维几何增加 air/water/sCO2/CO2 的全部 16 个有序配对。
准备 v3 为均匀二维总质量流量增加独立容量查询、入口流量解析和完整准备，复用物理入口网格，
并将前段记录与最终准备证据分开。
准备 v4 增加规范连续 XY 场与完整局部阻力。
Python 准备入口对对称均匀和连续二维输入使用 v3/v4；非零 delta 均匀、离散分区、sigmoid 与三维保留明确原路径。
CaseData 与保存文件契约不变，原生失败直接传播，不选择其他准备路线。
run v2 通过现有 model-h 或 true-h 驱动消费准备 v2。
Quick Design 准备 v2 接受带类型的原始输入，并提供不创建热网格或设计场数组的独立压降查询。
Python 通过 `_native_quick_prepare.py` 执行固定宿主协议，将原生输出复制到 CaseData。
被替代的 `shared/models/quick_design.py` 已删除；默认值统一来自 `shared/configs/model_parameters_v1.json` 及生成的 C++ 常量。
native-double v1 契约与既有 LTNE 模型继续可用。
Python 执行通过保存的准备态调用原生 run 阶段；原生结果阶段负责 Quick Design 指标。
准备与结果的宿主操作保留既有 Python 类型、缓存、警告和事件协议。
阶段迁移期间，上述 Python 入口继续保留全部现有模式。

## 修改数值函数

修改数值规则时，从下表找到 C++ 所有者。
公开输入／输出契约位于 `shared/domain/`；Python 绑定负责类型与数组传递。

| 修改内容 | C++ 文件与代表函数 |
| --- | --- |
| 单元几何、chi 与固体导热率 | [geometry.cpp](solvers/native/src/geometry.cpp): `standard_geometry`, `solid_conductivity`; [asym_geometry.cpp](solvers/native/src/asym_geometry.cpp) |
| 网格与物理端口 | [grid.cpp](solvers/native/src/grid.cpp): `uniform`, `wall`; [ports.cpp](solvers/native/src/ports.cpp): `port_overlap_1d`, `port_fractions_1d` |
| 连续场、sigmoid、LUT 与分区 | [field_continuous.cpp](solvers/native/src/field_continuous.cpp); [field_sigmoid.cpp](solvers/native/src/field_sigmoid.cpp); [field_lut.cpp](solvers/native/src/field_lut.cpp); [zones.cpp](solvers/native/src/zones.cpp) |
| 物性与 Nu 闭合 | [fluid_properties.cpp](solvers/native/src/fluid_properties.cpp): `PropertyEvaluator::evaluate`, `fluid_nusselt`; [preparation_properties.cpp](solvers/native/src/preparation_properties.cpp) |
| 固定 DF、修正、投影与规定流量 | [preparation_df.cpp](solvers/native/src/preparation_df.cpp): `fixed_df`; [preparation_df_corrections.cpp](solvers/native/src/preparation_df_corrections.cpp); [preparation_df_projection.cpp](solvers/native/src/preparation_df_projection.cpp); [preparation_flow.cpp](solvers/native/src/preparation_flow.cpp): `inlet_capacity_2d`, `inlet_speed` |
| 完整二维／三维与 Quick Design | [full_2d.cpp](solvers/native/src/full_2d.cpp): `solve_full_2d`; [full_3d.cpp](solvers/native/src/full_3d.cpp): `solve_full_3d`; [quick_design_driver.cpp](solvers/native/src/quick_design_driver.cpp): `solve_quick_design` |
| 指标、物理平衡、分区统计与检查 | [result_metrics.cpp](solvers/native/src/result_metrics.cpp): `pressure_face`, `boundary_enthalpy_duty`; [result_balance.cpp](solvers/native/src/result_balance.cpp): `mass`, `energy`, `zone_std`; [result_checks.cpp](solvers/native/src/result_checks.cpp): `collect_range`, `strict_certificate` |
| 完整阶段准备与执行 | [preparation_case.cpp](solvers/native/src/preparation_case.cpp): `prepare_case_2d`; [stage_run.cpp](solvers/native/src/stage_run.cpp): `tpmshx_run_case_2d_v1`, `tpmshx_run_case_2d_v2`; [stage_capture_2d.cpp](solvers/native/src/stage_capture_2d.cpp) |
| Quick Design 阶段准备与执行 | [quick_design_prepare_v2.cpp](solvers/native/src/quick_design_prepare_v2.cpp): `tpmshx_prepare_quick_design_v2`, `tpmshx_quick_pressure_fractions_v2`; [quick_design_prepare.cpp](solvers/native/src/quick_design_prepare.cpp)：保留 v1; [quick_design_run.cpp](solvers/native/src/quick_design_run.cpp): `tpmshx_run_quick_design_v1` |
| 阶段评估与资格判断 | [result_stage.cpp](solvers/native/src/result_stage.cpp): `evaluate`, `evaluate_applicability`, `evaluate_physical_balance`, `evaluate_qualification` |

几何库使用 geometry ABI 1／field ABI 2；准备库保留 ABI 1 加载入口，并增加带版本的 Quick 准备 v2 契约；结果库使用 result ABI 2。
求解器的算法细节从上表 driver 进入对应 SIMPLE、压力和能量实现；[C++ 说明](../docs/cpp-migration.zh-CN.md)给出接口边界。
Python 保留配置、DTO、I/O、缓存、NumPy 事件处理、GUI／搜索和离线研究。
原生结果阶段负责完整结果的证据选择与资格；Python 将其输出适配到应用接口。
具体保留边界见[架构](../docs/architecture.zh-CN.md#retained-python-responsibilities)。

### 修改后重新构建

修改 C++ 函数或编入库的模型数据后，先通过[当前环境检查](../README.md#first-run)。
从仓库根目录重新构建并发布四库，最后重启进程。
下列命令使用基础锁；若 `.venv-path` 指向 BO 环境，换成 `engineering/requirements/` 中对应的 `bo-macos.txt` 或 `bo-windows.txt`。
首次使用构建缓存时，先执行[首次运行](../README.md#first-run)中的 `fetch` 命令，再用同一缓存执行下列命令。

macOS:

```sh
PYTHON="$(head -n 1 .venv-path)"
"$PYTHON" engineering/scripts/build_native_dependencies.py publish --python-lock engineering/requirements/base.txt
```

Windows (PowerShell):

```powershell
$tm1Python = Get-Content .venv-path -TotalCount 1
& $tm1Python engineering/scripts/build_native_dependencies.py publish --python-lock engineering/requirements/base.txt
```

组件单独发布和旧检查点运行库保留规则见[C++ 构建说明](../docs/cpp-migration.zh-CN.md#native-geometry-core)。

<a id="三模块主线"></a>
<a id="支撑模块与应用入口"></a>

## 六类目录

| 目录 | 职责与边界 |
| --- | --- |
| [preprocess/](preprocess/) | 前处理与显式离线模型准备 |
| [solvers/](solvers/) | 求解 API、准备态适配和 Python C++ 绑定；[native/](solvers/native/) 保存 C++ 源码、独立 C ABI、构建文件及原生调用测试 |
| [postprocess/](postprocess/) | 已记录结果的指标、物理审计、资格结论和导出 |
| [shared/](shared/) | `domain/` 数据契约、`models/` 与 `df_surrogate/` 模型、`io/` 文件交接、`configs/` 资源及共享辅助函数 |
| [applications/](applications/) | `gui/` 界面和控制器、`cli/` 命令行、`design/` 快速设计、`optimization/` 优化、`execution/` 运行恢复；`result_adapter.py` 统一映射应用结果 |
| [development/](development/) | 严格保留三类：`tests/` 自动测试，`validation/` 数值与实验验证，`runs/` 演示、诊断和测量工具 |

GUI 实现在 [applications/gui/main.py](applications/gui/main.py)，CLI 实现在 [applications/cli/main.py](applications/cli/main.py)。
包顶 [main.py](main.py)、[cli.py](cli.py) 和 [desktop.py](desktop.py) 保留短启动入口。
使用 `python -m sjtu_tpmshx.main` 或 `python -m sjtu_tpmshx.cli`；计算代码直接调用上面的四个入口。

根 [engineering/](../engineering/) 保存 `scripts/` 构建与检查脚本、`packaging/` 打包配置和 `requirements/` 依赖锁。
[docs/contracts/](../docs/contracts/) 保存公共文件契约，`.github/workflows/` 保存 CI 配置。
其他根目录职责见[仓库导航](../docs/README.md)。

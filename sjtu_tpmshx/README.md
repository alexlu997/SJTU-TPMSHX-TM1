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

`compute` 同时处理阶段进度、取消、耗时与警告。`postprocess/metrics.py` 选择记录证据并调用结果核心，`postprocess/export.py` 负责导出。
当前正式计算支持矩形二维与长方体三维。公开输入和文件交接见[示例](../examples/three_module/)与[数据契约](../docs/contracts/three_module_v1/README.zh-CN.md)。
近似模式和扩展状态见[能力范围](../docs/capabilities.md)。

标准、CO2、非对称几何与 chi/Kss 的数值所有者位于
[native/src/geometry.cpp](solvers/native/src/geometry.cpp) 和
[native/src/asym_geometry.cpp](solvers/native/src/asym_geometry.cpp)。
[shared/models/_native_geometry.py](shared/models/_native_geometry.py) 通过 ctypes 延迟加载独立几何 ABI 1 库，
保留 Python 公共入口、类型和缓存，不导入求解器后端。
第三批的网格／端口和六方向轴映射由 [grid.cpp](solvers/native/src/grid.cpp) 与 [ports.cpp](solvers/native/src/ports.cpp) 负责。
压力求解器和前处理共用同一端口实现。
[field_continuous.cpp](solvers/native/src/field_continuous.cpp)、sigmoid／LUT 核心及 [zones.cpp](solvers/native/src/zones.cpp)
负责设计场插值、分区和 Gaussian 平滑，仍部署在同一几何库中。
Python 保留配置、类型／数组适配、数据对象、I/O、缓存、GUI 和 BO 编排。
已替换的 Python 数值体已退役；独立参考只供 development 回归使用。
第四批由 [fluid_properties.cpp](solvers/native/src/fluid_properties.cpp)、`preparation_properties.cpp`、`preparation_df*.cpp` 和 `preparation_flow.cpp`
负责物性／闭合、固定 DF／实验修正、投影、固定流量与设计准备数值。
[shared/models/_native_preparation.py](shared/models/_native_preparation.py) 延迟加载独立 preparation ABI 1 库；几何 ABI 1／field ABI 2 不变。
Python 保留配置、DTO、I/O、缓存、GUI／BO 策略和离线拟合；正式数值与开发独立参考分开。
第五批的 [result/](solvers/native/result/) 是独立 C++ 结果核心，负责指标、物理平衡、分区统计和数值资格检查。
[shared/_native_result.py](shared/_native_result.py) 按需加载结果 ABI 2；读取文件不加载求解器、准备库或结果库。
Python 保留证据选择、状态解释和文件接口。四个日常入口不变；修改数值函数时进入对应 C++ 源文件，重新构建并重启进程。
第五批仍在数值与平台验收中，六批目标尚未完成。
独立构建和四库交付见[原生结果核心](../docs/cpp-migration.zh-CN.md#native-result-core)。

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

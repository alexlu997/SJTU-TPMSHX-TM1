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

`compute` 同时处理阶段进度、取消、耗时与警告。`postprocess/metrics.py` 保留指标公式与归约辅助函数，`postprocess/export.py` 负责导出。
当前正式计算支持矩形二维与长方体三维。公开输入和文件交接见[示例](../examples/three_module/)与[数据契约](../docs/contracts/three_module_v1/README.zh-CN.md)。
近似模式和扩展状态见[能力范围](../docs/capabilities.md)。

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

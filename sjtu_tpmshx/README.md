# 主体源码：sjtu_tpmshx

[中文](README.md) | [English](README.en.md)

这是 TM1 的核心源码包，包含 Python 应用和 `solvers/native/` 下的 C++ 数值后端。
首次配置、命令行算例和 GUI 启动见
[项目 README](../README.md#first-run)；命令从仓库根目录执行。
完整的模块边界和物理约束见[架构说明](../docs/architecture.zh-CN.md)。

## 三模块主线

[compute.py](compute.py) 中的 `compute` 是主计算入口，执行配置校验并统一调用以下三个公开 API。
它返回 `CaseData`、`FieldResult` 和 `PerformanceResult`，同时处理阶段进度、取消、耗时与警告。

```text
compute → preprocess.api.prepare_case → CaseData → solvers.api.run_case → FieldResult
                                                                      → postprocess.api.evaluate → PerformanceResult
```

| 模块 | 公开入口 | 职责 |
| --- | --- | --- |
| [preprocess/](preprocess/) | [api.py](preprocess/api.py)：`prepare_case` | 准备实际网格、边界、设计场、模型资源和运行输入 |
| [solvers/](solvers/) | [api.py](solvers/api.py)：`run_case` | 消费 CaseData，通过 `solvers/backends/cpp/` 绑定调用 `solvers/native/` 下的 C++ 数值后端，返回原生场和运行状态 |
| [postprocess/](postprocess/) | [api.py](postprocess/api.py)：`evaluate` | 组织 FieldResult 指标评估；`metrics.py` 保留指标公式与归约辅助函数，`export.py` 负责导出，不重跑求解 |

真实算例和文件交接入口见[三模块示例](../examples/three_module/)。
当前正式计算域为矩形 2D/3D；应用近似模式和扩展能力状态见
[项目 README](../README.md)与[能力范围](../docs/capabilities.md)。

## 支撑模块与应用入口

| 目录或文件 | 职责 |
| --- | --- |
| [domain/](domain/) | CaseData、FieldResult、PerformanceResult、运行控制及输入校验 |
| [io/](io/) | YAML/HDF5/JSON 文件交接与读取校验 |
| [models/](models/)、[df_surrogate/](df_surrogate/) | 共享几何、物性、关联式及模型资源 |
| [configs/](configs/) | 随包提供的配置资源 |
| [compute.py](compute.py) | 主计算入口，组织三模块调用、阶段进度与取消 |
| [workflows/](workflows/) | 文件交接、运行状态、检查点与续算编排，复用主计算阶段 |
| [solvers/native/](solvers/native/) | C++ 数值源码、独立 C ABI、构建文件、原生调用测试与许可声明 |
| [main.py](main.py)、[ui/](ui/)、[controllers/](controllers/) | GUI 入口、显示和界面控制；通过公开模块组织计算 |
| [cli.py](cli.py) | 命令行的准备、求解、后处理及完整运行入口 |
| [design/](design/)、[optimization/](optimization/) | 快速设计和参数优化应用 |
| [runs/](runs/) | 演示、诊断和研究工具 |
| [tests/](tests/)、[validation/](validation/) | 自动测试、数值与实验验证及相关证据 |

根目录的工程项目、辅助工具和历史资料见[仓库目录导航](../docs/README.md)。

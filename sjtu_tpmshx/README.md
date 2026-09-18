# 主体源码：sjtu_tpmshx

这是 TM1 的 Python 源码包。首次配置、命令行算例和 GUI 启动见
[项目 README](../README.md#first-run)；命令从仓库根目录执行。
完整的模块边界和物理约束见[架构说明](../docs/architecture.md)。

## 三模块主线

```text
应用输入 → preprocess → CaseData → solvers → FieldResult → postprocess → PerformanceResult
```

| 模块 | 公开入口 | 职责 |
| --- | --- | --- |
| [preprocess/](preprocess/) | [api.py](preprocess/api.py)：`prepare_case` | 准备实际网格、边界、设计场、模型资源和运行输入 |
| [solvers/](solvers/) | [api.py](solvers/api.py)：`run_case` | 消费 CaseData，执行数值求解，返回原生场和运行状态 |
| [postprocess/](postprocess/) | [api.py](postprocess/api.py)：`evaluate` | 从 FieldResult 计算指标和导出结果，不重跑求解 |

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
| [pipelines/](pipelines/)、[workflows/](workflows/) | 脚本入口与计算流程编排 |
| [main.py](main.py)、[ui/](ui/)、[controllers/](controllers/) | GUI 入口、显示和界面控制；通过公开模块组织计算 |
| [cli.py](cli.py) | 命令行的准备、求解、后处理及完整运行入口 |
| [design/](design/)、[optimization/](optimization/) | 快速设计和参数优化应用 |
| [core/](core/) | 优化与验证共用的评估入口；它只是主体包的一部分 |
| [runs/](runs/) | 演示、诊断和研究工具 |
| [tests/](tests/)、[validation/](validation/) | 自动测试、数值与实验验证及相关证据 |

根目录的工程项目、辅助工具和历史资料见[仓库目录导航](../docs/README.md)。

# SJTU-TPMSHX-TM1

TM1 将 TPMS 换热器的前处理、求解和后处理拆为独立维护的模块，供计算界面、
参数优化和快速设计通过公开接口调用。目标仓库为
[alexlu997/SJTU-TPMSHX-TM1](https://github.com/alexlu997/SJTU-TPMSHX-TM1)。
原 SJTU-TPMSHX/V2 是来源参考，本分支不合回原仓库。

当前为接管修复阶段，M-A 尚未完成。独立审查、精确提交的远端 CI、最终合并验证
和历史 B40 基线处理仍未关闭。当前状态见
[Graph 状态](docs/plans/three-module-graph/state/)、
[接管记录](docs/plans/three-module-graph/TAKEOVER.md) 与
[验收协议](docs/plans/three-module-graph/OPERATIONS.md)。

## 三个模块

```text
应用输入 → preprocess → CaseData → solvers → FieldResult → postprocess → PerformanceResult
                         YAML/HDF5             HDF5/VTK                   JSON
```

前处理确定实际网格、边界、设计场、固定几何、模型资源和运行设置。求解消费准备好的
CaseData，温度相关物性和数值迭代在求解侧执行。后处理从 FieldResult 的原生场、通量、
压力和状态计算指标，缺数据时报告原因；不启动求解或读取 GUI、活动求解器对象。

```python
from sjtu_tpmshx.preprocess.api import prepare_case
from sjtu_tpmshx.solvers.api import run_case
from sjtu_tpmshx.postprocess.api import evaluate

case = prepare_case(config, case_id="example")
result = run_case(case)
metrics = evaluate(result)
```

同进程不强制落盘。独立进程使用正式文件交接：

```bash
PYTHON="$(head -n 1 .venv-path)"
"$PYTHON" -m sjtu_tpmshx.cli prepare config.json case.yaml --case-id example
"$PYTHON" -m sjtu_tpmshx.cli solve case.yaml results.h5
"$PYTHON" -m sjtu_tpmshx.cli postprocess results.h5 metrics.json
```

Case YAML 引用伴随 HDF5；result/VTK 导出和严格指标 JSON 的限制见
[schema](schemas/three_module_v1/)。取消与失败不伪装成完成结果；已完成但未收敛的
结果保留原状态。指标有限不等于数值、能量或实验精度验收通过。

## 已接线能力与边界

| 用途 | 公开入口 | 数量口径 |
| --- | --- | --- |
| 全模型 2D/3D | `prepare_case`，随后 `run_case` / `evaluate` | 2D Q 为 W/m；3D Q 为 W |
| 优化筛选 2D/3D | `prepare_screening_2d/3d`，随后相同求解和后处理 API | 核心 3D 为总量；优化目标在应用层按真实 Lz 归一 |
| 快速设计 | `prepare_quick_design`，随后相同 API | 规定速度 LTNE 与解析入口压损，非完整 SIMPLE；Q 为 W |
| 参数扫描与有效场输入 | [公开示例](examples/) | 不改求解器私有成员 |
| 离线清洗与拟合 | `preprocess.offline` | 显式数据版本和本地输出目录，不自动替换生产模型 |

`models/`、`df_surrogate/` 等是共享技术支撑，不是第四个业务模块。旧 Pipeline/应用
入口单向调用公开模块。具体边界见[架构说明](docs/architecture.md)。

实际后端为 Python/Numba。C++、OpenFOAM、REFPROP 等提供器、扩展 h/f/PEC 定义与
伴随能力继续按 M-B/原文限定追踪，不能据目录或接口声明为已实现。

## 环境与检查

本地 Python 必须使用 `.venv-path` 第一行的绝对解释器。缺失时先配置合规环境；
代理不自动创建、升级或重装共享环境。依赖声明与精确锁同时维护，共享 venv
只安装锁定依赖，不把当前项目 editable 安装进去。命令从当前仓库根运行。

```bash
PYTHON="$(head -n 1 .venv-path)"
"$PYTHON" -m sjtu_tpmshx.runs.tools.check_locked_environment
"$PYTHON" -m pip check
export MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg"
"$PYTHON" -m pytest sjtu_tpmshx/tests -q -m "not slow and not heavy" --timeout=600 --timeout-method=thread
"$PYTHON" -m pytest sjtu_tpmshx/tests/integration_tm1 -q --timeout=600 --timeout-method=thread
```

第一条 pytest 排除了 slow/heavy，不能代替真实集成。最小后处理 CI 使用独立的
`requirements-lock-postprocess.txt` 环境，并消费另一完整环境生成的真实 2D/3D
结果文件；文件留在 CI 作业本地，不上传结果 artifact。配置不等于实际 CI 通过。

## 数据与历史证据

原始实验/CFD 数据位于本地 `data/raw_data/`，不提交。匹配版本见
[data-revision.txt](data-revision.txt)。清洗、拟合和本地输出规则见
[离线模型说明](docs/plans/three-module-graph/decisions/offline_models.md)。
当前水 CFD 工作簿缺失时不以旧版文件替代。

原 README 的历史精度与物理说明原样保存在
[V2 README 存档](docs/history/v2-readme.md)，相对路径沿用来源仓库根目录。
这些数字不是 TM1 或当前默认 CFD 模式的新验收。B40 原锁定测试 4/4 失败、
3D 筛选未收敛及其他原生失败证据继续保留；不改阈值或物理范围迎合结果。

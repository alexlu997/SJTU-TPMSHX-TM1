# 仓库目录与文档导航

**主体程序位于 [sjtu_tpmshx/](../sjtu_tpmshx/)**。
读代码从[模块地图](../sjtu_tpmshx/README.md)开始，运行程序从
[首次运行说明](../README.md#first-run)开始。

## 当前文档

| 内容 | 入口 |
| --- | --- |
| 模块职责、调用关系和物理约束 | [architecture.md](architecture.md) |
| CaseData、FieldResult、指标与文件交接 | [三模块数据契约](../schemas/three_module_v1/) |
| 已交付能力、M-B 未完成事项与阻塞条件 | [能力范围](capabilities.md) |
| 离线清洗、sCO2 有效 Nu 与上海空气阻力标定来源 | [模型资源](model-resources.md) |
| 数据文件名、已结案缺项与水 Nu 选择 | [数据目录](data-catalog.md) |
| 工程、验证、研究与性能工具的输入输出 | [工具入口](tools.md) |
| 数值/实验验证工具与方向系数研究边界 | [验证导航](../sjtu_tpmshx/validation/README.md) |
| GUI、孔隙率与 CI 的现行行为要求 | [OpenSpec 规范](../openspec/specs/) |
| 历史报告、任务图、旧基准与退役工具 | [固定历史索引](history/README.md) |

## 根目录各自放什么

| 目录 | 用途 |
| --- | --- |
| [sjtu_tpmshx/](../sjtu_tpmshx/) | 主体源码、应用层、共享模型、有效测试和验证工具 |
| [docs/](./) | 当前说明与历史资料入口 |
| [examples/](../examples/) | 公开调用示例和首次运行配置 |
| [scripts/](../scripts/) | 通用测试与服务器测试辅助脚本 |
| [benchmarks/](../benchmarks/) | 现行性能剖析工具 |
| [schemas/](../schemas/) | 三模块数据契约；实现位于主体包的 domain/、io/ 等模块 |
| [openspec/](../openspec/) | 按功能分开的现行行为规范 |
| [.github/](../.github/) | macOS / Windows CI 和最小后处理环境检查 |

`pyproject.toml`、`requirements*.txt`、`pytest.ini` 负责构建、依赖和测试；
`mypy-core-files.txt` 声明公共接口与数据契约的显式类型检查范围，执行方式见
[环境与检查](../README.md#环境与检查)。
`AGENTS.md` 记录项目协作规则，`LICENSE` 记录许可，`data-revision.txt` 声明配套数据版本。
原始实验/CFD 数据位于本地 `data/raw_data/`，研究脚本与结果放在忽略的 `.cache/`，
均不随公共代码仓库提交。旧 `reports/` 输出目录也被忽略，避免旧命令重新提交结果表。

一维焓方程参考模型由有效测试直接使用，现放在
[tests/enthalpy_1d_reference.py](../sjtu_tpmshx/tests/enthalpy_1d_reference.py)。
生产 CFD 系数 CSV 和测试读取的 MMS 数据继续保留；历史 `golden_3d.json`、旧 γ 快照、
阶段报告与任务过程文件从固定 Git 历史查阅，不再作为当前测试资源或当前精度说明。

M-A 三模块主线完成不代表 M-B 扩展功能完成，也不代表实验精度已通过。
原 B40 失败、冻结参考和历史结论按原状态保留。

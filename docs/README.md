# 仓库目录与文档导航

**主体程序位于 [sjtu_tpmshx/](../sjtu_tpmshx/)**。
读代码从[模块地图](../sjtu_tpmshx/README.md)开始，运行程序从
[首次运行说明](../README.md#first-run)开始。

## 当前文档

| 内容 | 入口 |
| --- | --- |
| 模块职责、调用关系和物理约束 | [architecture.md](architecture.md) |
| CaseData、FieldResult、指标与文件交接 | [三模块数据契约](../schemas/three_module_v1/) |
| 任务依赖、实施状态与验收证据 | [三模块计划](plans/three-module-graph/README.md)、[Graph 状态](plans/three-module-graph/state/) |
| 当前 M-A / M-B 验收说明 | [架构验收](plans/three-module-graph/acceptance_architecture.md)、[需求验收](plans/three-module-graph/acceptance_document.md) |
| 原始数据、离线清洗与模型发布边界 | [离线模型说明](plans/three-module-graph/decisions/offline_models.md) |
| 工程、研究、性能工具的输入输出与运行边界 | [工具入口](tools.md) |

当前运行和安装说明集中在项目 README，架构与物理约束集中在 architecture.md。
历史手册中的旧命令、目录地图和精度数字保留其当时语境。

## 根目录各自放什么

| 目录 | 用途 |
| --- | --- |
| [sjtu_tpmshx/](../sjtu_tpmshx/) | 主体源码，包含三模块、应用层、共享模型、测试和验证工具 |
| [docs/](./) | 当前文档、实施计划和历史文档 |
| [examples/](../examples/) | 公开调用示例和首次运行配置 |
| [projects/](../projects/) | 各合作或工程评估项目的入口脚本、说明和交付记录；调用主体包 |
| [scripts/](../scripts/) | 测试、服务器运行和结果拉取等辅助脚本 |
| [benchmarks/](../benchmarks/) | 性能剖析工具与历史性能记录 |
| [poc/](../poc/) | 概念验证代码，其中部分由自动测试直接导入 |
| [schemas/](../schemas/) | 三模块数据契约文档；实现位于主体包的 domain/ 和 io/ 等模块 |
| [openspec/](../openspec/) | 设计规范与变更提案；提案本身不代表功能已实现 |
| [reports/](../reports/) | 研究报告、验证记录和结果；部分 CSV 仍被复现脚本读取 |
| [.github/](../.github/) | macOS / Windows CI 和最小后处理环境检查 |

根目录的 `pyproject.toml`、`requirements*.txt`、`pytest.ini` 等负责构建、依赖和测试；
`AGENTS.md` 记录项目协作规则，`LICENSE` 记录许可。
`data-revision.txt` 声明配套数据版本，`golden_3d.json` 与其元数据保留历史基准。
原始实验/CFD 数据位于本地 `data/raw_data/`，不随代码仓库提交。

## 历史参考

- [历史资料总索引](history/README.md)：旧 README、图片、探索记录与架构快照。
- [旧项目手册](history/PROJECT_MANUAL.md)：保留旧目录、逐文件说明和当时的使用流程。
- [旧开发日志](history/devlog.md)：保留原始工作记录及其已注明的同步缺口。
- [2026-07-11 环境快照](../constraints-devbox-2026-07-11.txt)：历史复现记录，当前安装使用项目 README 指定的锁文件。

M-A 三模块主线与 M-B 扩展能力分别追踪；目录或接口存在不等于通过验收。
历史 B40 失败、冻结参考和原始报告结论保留原状。

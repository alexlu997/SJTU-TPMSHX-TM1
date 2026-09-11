# TM1 三模块计划、状态与验收索引

本目录同时保留初始方案和实施记录。当前目标仓库为
[SJTU-TPMSHX-TM1](https://github.com/alexlu997/SJTU-TPMSHX-TM1)，目标分支为 `main`。
M-A 架构合并验收已完成，M-B 扩展能力未完成；当前状态以
[state/](state/) 及对应证据为准，见[架构验收](acceptance_architecture.md)、
[能力追踪](acceptance_document.md)和[接管记录](TAKEOVER.md)。

初始方案中的 `planned`、原仓库 `master` 和“本轮授权”描述保留当时语境，
不能用于重置现有状态或替代当前用户指令。恢复任务时继承现有 Goal/Graph，
仅刷新受实际变更影响的验收记录。

| 文件 | 用途 |
|---|---|
| START_HERE.md | 初始启动提示词存档，保留原仓库和初始调度语境 |
| GOAL.md | 初始总目标、两里程碑、并行策略与节点总览 |
| graph.json / graph.mmd | 机器可读依赖图 / Mermaid 图源，不是原生 Codex 格式声明 |
| nodes/ | 45 个节点任务卡：职责、依赖、独占写路径、验收和证据 |
| state/ | 各节点当前状态及证据引用；结论需结合实际证据读取 |
| OPERATIONS.md | 工作树、阻塞、审查、CI、自主合并与回退协议 |
| CONTRACT_BLUEPRINT.md | CaseData/FieldResult、物理语义、状态与字段设计输入 |
| REQUIREMENTS.md / V01_SOURCE.md | 原文需求追踪 / V0.1 转录 |
| SOURCES.md | 固定仓库版本、官方参考与核查范围 |
| tools/check_graph.py | 只读的静态图校验、依赖影响和拓扑就绪查询 |
| VALIDATION.md | 本执行包的实际静态检查记录，不是仓库数值验证 |

37 个架构节点、8 个能力分支节点不等于同时启动 45 个代理。默认建议 3 个实现工作者，共享重数值作业 1 个、合并协调者 1 个；根据实际工具、内存、CPU 和权限调度。

执行前核对当前 TM1 `main`、远端地址和活动工作。初始方案参考提交 `5f1cafb`
不构成回滚依据；普通执行遵守当前用户授权和 OPERATIONS.md 的验收门槛，
不得绕过测试、保护、数据和环境限制。

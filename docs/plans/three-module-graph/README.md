# SJTU-TPMSHX：TM1 并行 Graph 执行包 V2

这是目标执行规格，不是已经完成的重构代码，也不是后台执行器。当前所有节点为 planned。

建议使用：将整个目录与原始 V0.1 Word 提供给 Codex，以 START_HERE.md 作为启动提示词。已有本地 Goal/Graph 机制时映射到原机制，不创建第二套状态真源。

| 文件 | 用途 |
|---|---|
| START_HERE.md | 可直接使用的 Codex 启动提示词与本轮授权 |
| GOAL.md | 总目标、两里程碑、并行策略与节点总览 |
| graph.json / graph.mmd | 机器可读依赖图 / Mermaid 图源，不是原生 Codex 格式声明 |
| nodes/ | 45 个节点任务卡：职责、依赖、独占写路径、验收和证据 |
| state/ | 各节点独立初始状态；不是完成证据 |
| OPERATIONS.md | 工作树、阻塞、审查、CI、自主合并与回退协议 |
| CONTRACT_BLUEPRINT.md | CaseData/FieldResult、物理语义、状态与字段设计输入 |
| REQUIREMENTS.md / V01_SOURCE.md | 原文需求追踪 / V0.1 转录 |
| SOURCES.md | 固定仓库版本、官方参考与核查范围 |
| tools/check_graph.py | 只读的静态图校验、依赖影响和拓扑就绪查询 |
| VALIDATION.md | 本执行包的实际静态检查记录，不是仓库数值验证 |

37 个架构节点、8 个能力分支节点不等于同时启动 45 个代理。默认建议 3 个实现工作者，共享重数值作业 1 个、合并协调者 1 个；根据实际工具、内存、CPU 和权限调度。

执行前重新核对 origin/master 和活动工作。本包参考提交 5f1cafb，不允许以此为由回滚较新的用户提交。本轮授权允许 Goal 范围内自主 commit/push/PR/CI/达标合并，不允许绕过测试、保护、数据和环境限制。

# 依据与核查范围

## 原始需求与后续指令

S1：用户提供的 V0.1 Word（WK，2026.09.08），文本转录见 V01_SOURCE.md。文件中的章节、限定词和接口对象为需求依据。原始 Word 若与转录有差别，以原文件及用户明确后续要求为准。

S2：用户后续明确：三个一级模块独立维护，外部应用只调用、不修改内部；求解模块保留 Python/Numba、C++、OpenFOAM 三路线。本轮新增：Graph 尽量并行、无关节点不因局部阻塞停工，并授权目标范围内自主提交、PR、CI和达标合并。

S3：上一版 Goal 文件已在本轮读取。本版细化其大串行节点，新增明确所有权、独立叶节点、阻塞类型、自动合并门槛；本轮授权替代旧计划中的普通提交无授权和设计后再批准停点。

## GitHub 固定快照

执行前必须再次确认目标分支，以下只说明本次规划所依据的提交，不自动切换或重置用户分支。

- 仓库：https://github.com/alexlu997/SJTU-TPMSHX
- 提交：https://github.com/alexlu997/SJTU-TPMSHX/commit/5f1cafb0c7e461a8c30a8ea96920ce03a828e412
- AGENTS：https://github.com/alexlu997/SJTU-TPMSHX/blob/5f1cafb0c7e461a8c30a8ea96920ce03a828e412/AGENTS.md
- 架构：https://github.com/alexlu997/SJTU-TPMSHX/blob/5f1cafb0c7e461a8c30a8ea96920ce03a828e412/docs/architecture.md
- 流水线：https://github.com/alexlu997/SJTU-TPMSHX/blob/5f1cafb0c7e461a8c30a8ea96920ce03a828e412/sjtu_tpmshx/controllers/compute_pipeline.py
- PR #93：https://github.com/alexlu997/SJTU-TPMSHX/pull/93
- 二维出口温度：https://github.com/alexlu997/SJTU-TPMSHX/blob/5f1cafb0c7e461a8c30a8ea96920ce03a828e412/sjtu_tpmshx/pipelines/solve_2d.py
- CI 定义：https://github.com/alexlu997/SJTU-TPMSHX/blob/5f1cafb0c7e461a8c30a8ea96920ce03a828e412/.github/workflows/ci.yml
- 当前提交 CI：https://github.com/alexlu997/SJTU-TPMSHX/actions/runs/34370615214
- 项目依赖：https://github.com/alexlu997/SJTU-TPMSHX/blob/5f1cafb0c7e461a8c30a8ea96920ce03a828e412/pyproject.toml

本次读取了远端分支、递归目录树、AGENTS、关键入口、PR #93 diff、二维出口温度实现、CI 定义和当前提交的 CI 状态等；当前运行显示 success，CI 定义的测试选择仍排除 slow/heavy。pyproject 已列依赖中未显式声明 HDF5/YAML 对应依赖，E00 须核查并按项目规则处理，不能推断本地环境已有或没有这些包。

未执行本地项目数值测试，未完成全库逐行审计，未复跑实验对照。节点中的其他候选路径来自前文核查与当前树，执行时仍须在实际提交上确认。包内计划检查结果只证明本任务图的静态结构，不证明求解器实现或数值精度。

## 外部工具使用依据

以下官方文档用于核对工作树、多代理和平台合并机制，不是 V0.1 的原文内容；项目具体并发数与门槛为本计划建议。

- OpenAI，Codex worktrees：https://developers.openai.com/codex/app/worktrees
- OpenAI，Codex multi-agent：https://developers.openai.com/codex/multi-agent
- GitHub，自动合并：https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-auto-merge-for-pull-requests-in-your-repository
- GitHub，管理合并队列：https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue

本包不声明 Codex 支持原生导入 graph.json，也不声明仓库已启用 auto-merge 或 merge queue。存在原生队列时依其规则验证；用 Actions 做必需队列检查时要覆盖 merge_group。没有这些功能则由单个协调者正常串行合并，不能虚构队列已运行。

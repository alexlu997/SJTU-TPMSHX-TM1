# repo-ci Specification

[中文](spec.md) | [English](spec.en.md)

## Purpose
仓库 CI 门（GitHub Actions，headless pytest 子集）及其安装/排除约定。来自 openspec archive `2026-07-02-cleanup-ci`（架构扫描批次 D+F）。
## Requirements
### Requirement: Headless CI gate on push/PR
仓库 SHALL 提供 `.github/workflows/ci.yml`，在 main push 与 PR 时运行。
平台为 macOS/Python 3.13 和 Windows/Python 3.12、3.13，从 `requirements.txt` 引用的共同精确锁安装。
`scripts/ci_scope.py` 按完整变更选择必需层级：

| 层级 | 允许的变更 | 必需工作 |
| --- | --- | --- |
| docs | 仅限声明的文档路径 | 文档链接、项目命令及四项汇总门；明确核对允许跳过的作业 |
| application | 仅限声明的显示文件、图标和文档 | 平台应用测试、真实模块集成、BO、最小后处理及匹配的原生构建 |
| full | 其他或混合变更；所有 main push 和手动运行 | 全部应用检查，加支持的平台/Python 矩阵中的完整原生依赖资格检查 |

在 `PYTHONHASHSEED=0` 下，快测使用 `-m "not slow and not heavy"`，排除 `integration_tm1`，并采用 `-n 2`。
`fast-0` 使用 `--dist load --maxschedchunk=1`；`fast-1` 使用 `--dist worksteal`。
现有 `ci_shard` 插件将快测分为两个独立作业。
`fast-1` 作业随后在独立 pytest 进程中完整运行 `tests/integration_tm1/`，不加 marker 过滤。
快测和集成 SHALL 保留各自报告；除非作业已取消，快测失败不得阻止集成执行。
常规 Qt 测试使用 offscreen 并禁用 3D 面板；实际渲染使用独立的原生 Qt 进程，其平台要求和证据边界见根 README。
CI SHALL NOT 依赖忽略的本地数据资产。

快测 SHALL 固定两个 worker，BLAS/OMP/MKL/NumExpr 单线程。各作业 SHALL 输出最慢 30 项与 skip 原因，并保存
逐项状态及耗时的 JUnit XML，测试报告 artifact 保留 7 天。上传范围为
`.cache/ci/` 的测试报告、收集/分片清单及资源记录，不包含原生求解结果或本地数据。
原生资格模块 SHALL 由 `sjtu_tpmshx/tests/native/_ci_suite.txt` 共同清单选择，应用快测 SHALL 移交相同模块并保留原完整收集集合。清单外的新模块 SHALL 自动进入应用快测。
平台汇总门 SHALL 验证原生分片完整且互斥，再验证应用与原生两组覆盖原完整集合且没有重复，并要求测试分片、集成、BO 及原生依赖资格作业成功。
平台快测、真实集成和最小后处理门均保留；macOS 3.13、Windows 3.12、Windows 3.13 和 minimal-postprocess 四项检查均为必需门，数值断言/容差不因提速改变。基础与 BO 作业 SHALL 使用相同的平台/Python 版本矩阵；两个 Windows 版本共用 requirements/bo-windows.txt。

#### Scenario: Integration is executed once per platform
- **WHEN** 合并两个快测分片和独立集成进程的测试集合
- **THEN** 既有用例仍被覆盖，集成目录不在快测中重复执行；新增测试单独记录

#### Scenario: Native tests run once per platform
- **WHEN** 应用快测将共同清单中的模块移交原生分片
- **THEN** 原生分片必须成功且完整，合并后没有重复或漏测；缺失或失败的 manifest 阻止通过
- **AND** 线程并发、进程恢复和结果所有权测试保留在原生组，断言不变

#### Scenario: Native dependencies are independently qualified
- **WHEN** macOS/Python 3.13 或 Windows/Python 3.12、3.13 的原生依赖作业运行
- **THEN** 每个平台由一个构建作业按 `native/dependencies-lock.toml` 获取固定源码与 CMake，并离线构建。资格作业消费其匹配原生产物，真实执行独立 EOS/压力、Quick Design、true-h、model-h 与 SIMPLE caller；Windows Python 3.12 和 3.13 分别验证同一平台构建。随后用独立公式、离散账本、制造解、组件重放和固定历史参考验证完整驱动和公开 C 接口；`TPMSHX_REQUIRE_NATIVE_DEPS_TESTS=1` 与 `TPMSHX_REQUIRE_CPP_TESTS=1` 将缺少编译器、可执行程序或动态库视为失败，不允许以 skip 充当验收
- **AND** 构建只在独立原生作业发生，普通快测分片不重复构建依赖；上传构建日志和资格测试 XML，不上传源码、物性表或本地实验数据

#### Scenario: CI green on a clean main
- **WHEN** workflow 在当前 main 运行
- **THEN** pytest 子集 0 failed（skipped 允许），职位状态绿

#### Scenario: Environment-gated tests skip, not fail
- **WHEN** CI 环境缺本地数据资产或禁用 3D 面板
- **THEN** 相关测试被 skip 而非 fail

### Requirement: Dead-reference cleanup with history preserved
不可运行的历史基准脚本与退役 polygon 求解链 SHALL 从当前树移除，通过 `docs/history/retired-tools.md` 的固定 Git 索引追溯；现行保留的工具 SHALL 有实际调用或验证用途。3D 演示 SHALL 通过公开 `load_result` 读取已有 `FieldResult` 的真实场与 L 设计场，不再保留私有求解流程或旧 `sigmoid_field_3d` 生成器。

#### Scenario: No dangling runnable references
- **WHEN** 搜索仓库内对 `validation/legacy/validate_shanghai.py` 的非注释引用
- **THEN** 仅存在于 archive 与文档中，无声称可运行的脚本引用它

### Requirement: openspec history hygiene
已完成的 changes SHALL 由 Git 历史保留；`openspec/changes/` SHALL 只包含真实活跃的 change，不在工作树内重复保存已归档副本。

#### Scenario: Active list reflects reality
- **WHEN** 检查 `openspec/changes/`（无活动提案时目录可以不存在）
- **THEN** 仅保留真实活跃的 change；不要求默认 Python 环境安装 OpenSpec CLI

### Requirement: Pytest config single source
仓库根 `pyproject.toml` SHALL 在 `[tool.pytest.ini_options]` 中定义：`testpaths = sjtu_tpmshx/tests`、`--strict-markers`，并注册 `slow`、`fast` 与 `heavy` 标记。未注册标记 SHALL 导致收集期报错而非静默通过。

#### Scenario: Bare pytest collects only the real suite
- **WHEN** 在仓库根运行 `pytest --collect-only -q`
- **THEN** 收集项全部位于 `sjtu_tpmshx/tests/`，无 worktree 副本

#### Scenario: Typo'd marker fails loudly
- **WHEN** 某测试使用未注册标记（如 `@pytest.mark.slwo`）
- **THEN** pytest 收集期报错

### Requirement: Public interface type gate
`pyproject.toml` 的 `[tool.mypy].files` SHALL 显式列出公共接口与数据契约检查范围，包含当前 envelope
实现、三模块 API 和数据对象，同时保留仍有消费者的兼容入口。`pyproject.toml`
SHALL 对 envelope、前处理 API、求解 API 和后处理 metrics 启用无注解函数体检查。
这不声明全求解器严格类型覆盖。`test_type_gate.py` SHALL 在快测中执行清单检查，
并验证错误类型不能传入 `prepare_case`、`run_case`、`evaluate`；CI 不另加重复 mypy 步骤。

#### Scenario: Wrong public input types are rejected
- **WHEN** mypy 检查向三个公共 API 传入字符串代替各自数据对象的调用
- **THEN** 三处调用均报告参数类型错误；清单中的实际代码仍须零错误

### Requirement: Parallel local gate
本地全量门 SHALL 支持 pytest-xdist 并行：`pytest sjtu_tpmshx/tests/ -q -n auto --dist loadscope`，且在启动 Python 前设置 `PYTHONHASHSEED=0` 和 BLAS/OMP 单线程。`--dist loadscope` 为本机文档默认，worker 数可按资源改为固定值；128 核服务器保留脚本中的 worksteal 策略。解释器、环境检查和完整命令集中在[根 README](../../../README.md#环境与检查)。pytest-xdist 位于共同依赖锁中。

#### Scenario: Parallel full suite green
- **WHEN** 在 `PYTHONHASHSEED=0` 下运行 `pytest sjtu_tpmshx/tests/ -q -n auto --dist loadscope`
- **THEN** 所有实有测试进入验收（0 failed），skip 保留原因；历史耗时不作为跨机器速度承诺

### Requirement: Slow-marking policy — studies out, invariant gates in
`slow` 按角色区分研究型/冗余等价检查，且同路径须保留廉价覆盖；
物理不变量不得仅因耗时而标为 `slow`。`heavy` 是另一个耗时分层。
标记逐测试维护，不为获得绿色而删除物理不变量或扩大排除集。
严格能量守恒、asym δ=0、sizing 等既有检查保留在完整本地门中。
CI 快测排除 slow/heavy，随后独立运行 `integration_tm1`；它们共同提供持续反馈，
仍不覆盖全部本地重数值检查。全量本地门（无 `-m` 过滤）仍是完成判据。

#### Scenario: Fast subset materially faster
- **WHEN** 调整 CI 并行或测试分组
- **THEN** 0 failed，并记录同平台基准及候选的快测、集成、整 job 墙钟耗时；不得为提速扩大排除集

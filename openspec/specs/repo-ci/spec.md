# repo-ci Specification

## Purpose
仓库 CI 门（GitHub Actions，headless pytest 子集）及其安装/排除约定。来自 openspec archive `2026-07-02-cleanup-ci`（架构扫描批次 D+F）。
## Requirements
### Requirement: Headless CI gate on push/PR
仓库 SHALL 提供 GitHub Actions workflow（`.github/workflows/ci.yml`），在 push 到 main 与 PR 时分别使用 macOS/Python 3.13 和 Windows/Python 3.12，从 `requirements.txt` 引用的共同精确锁安装，并在 `PYTHONHASHSEED=0` 下运行 `pytest sjtu_tpmshx/tests/ -m "not slow and not heavy"`。随后运行 `tests/integration_tm1/` 的真实模块交接与数值检查。Qt SHALL 使用 offscreen 模式，3D 面板 SHALL 在该快速门中禁用。CI SHALL NOT 依赖 gitignored 的本地数据资产。

#### Scenario: CI green on a clean main
- **WHEN** workflow 在当前 main 运行
- **THEN** pytest 子集 0 failed（skipped 允许），职位状态绿

#### Scenario: Environment-gated tests skip, not fail
- **WHEN** CI 环境缺本地数据资产或禁用 3D 面板
- **THEN** 相关测试被 skip 而非 fail

### Requirement: Dead-reference cleanup with history preserved
不可运行的历史基准脚本与退役 polygon 求解链 SHALL 从当前树移除，通过 `docs/history/retired-tools.md` 的固定 Git 索引追溯；现行保留的工具 SHALL 有实际调用或验证用途。`sigmoid_field_3d` 仍供 3D 演示及测试使用。

#### Scenario: No dangling runnable references
- **WHEN** 搜索仓库内对 `validation/legacy/validate_shanghai.py` 的非注释引用
- **THEN** 仅存在于 archive 与文档中，无声称可运行的脚本引用它

### Requirement: openspec history hygiene
已完成的 changes SHALL 由 Git 历史保留；`openspec/changes/` SHALL 只包含真实活跃的 change，不在工作树内重复保存已归档副本。

#### Scenario: Active list reflects reality
- **WHEN** 检查 `openspec/changes/`（无活动提案时目录可以不存在）
- **THEN** 仅保留真实活跃的 change；不要求默认 Python 环境安装 OpenSpec CLI

### Requirement: Pytest config single source
仓库根 SHALL 提供 `pytest.ini`：`testpaths = sjtu_tpmshx/tests`、`--strict-markers`，并注册 `slow`、`fast` 与 `heavy` 标记。未注册标记 SHALL 导致收集期报错而非静默通过。

#### Scenario: Bare pytest collects only the real suite
- **WHEN** 在仓库根运行 `pytest --collect-only -q`
- **THEN** 收集项全部位于 `sjtu_tpmshx/tests/`，无 worktree 副本

#### Scenario: Typo'd marker fails loudly
- **WHEN** 某测试使用未注册标记（如 `@pytest.mark.slwo`）
- **THEN** pytest 收集期报错

### Requirement: Public interface type gate
`mypy-core-files.txt` SHALL 显式列出公共接口与数据契约检查范围，包含当前 envelope
实现、三模块 API 和数据对象，同时保留仍有消费者的兼容入口。`pyproject.toml`
SHALL 对 envelope、前处理 API、求解 API 和后处理 metrics 启用无注解函数体检查。
这不声明全求解器严格类型覆盖。`test_type_gate.py` SHALL 在快测中执行清单检查，
并验证错误类型不能传入 `prepare_case`、`run_case`、`evaluate`；CI 不另加重复 mypy 步骤。

#### Scenario: Wrong public input types are rejected
- **WHEN** mypy 检查向三个公共 API 传入字符串代替各自数据对象的调用
- **THEN** 三处调用均报告参数类型错误；清单中的实际代码仍须零错误

### Requirement: Parallel local gate
本地全量门 SHALL 支持 pytest-xdist 并行：`pytest sjtu_tpmshx/tests/ -q -n auto --dist loadscope`，且在启动 Python 前设置 `PYTHONHASHSEED=0`、`NUMBA_NUM_THREADS=2` 和 BLAS/OMP 单线程。`--dist loadscope` 为本机文档默认，worker 数可按资源改为固定值；128 核服务器保留脚本中的 worksteal 策略。解释器、环境检查和完整命令集中在[根 README](../../../README.md#环境与检查)。pytest-xdist 位于共同依赖锁中。

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
- **WHEN** 运行 `pytest sjtu_tpmshx/tests/ -q -m "not slow and not heavy" -n auto --dist loadscope`
- **THEN** 0 failed，且墙钟时间低于全量并行运行

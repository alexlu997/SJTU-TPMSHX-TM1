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
- **WHEN** 运行 `openspec list`
- **THEN** 仅剩真实活跃的 change

### Requirement: Pytest config single source
仓库根 SHALL 提供 `pytest.ini`：`testpaths = sjtu_tpmshx/tests`、`--strict-markers`，并注册 `slow`、`fast` 与 `heavy` 标记。未注册标记 SHALL 导致收集期报错而非静默通过。

#### Scenario: Bare pytest collects only the real suite
- **WHEN** 在仓库根运行 `pytest --collect-only -q`
- **THEN** 收集项全部位于 `sjtu_tpmshx/tests/`，无 worktree 副本

#### Scenario: Typo'd marker fails loudly
- **WHEN** 某测试使用未注册标记（如 `@pytest.mark.slwo`）
- **THEN** pytest 收集期报错

### Requirement: Parallel local gate
本地全量门 SHALL 支持 pytest-xdist 并行：`pytest sjtu_tpmshx/tests/ -q -n auto --dist loadscope`，且在启动 Python 前设置 `PYTHONHASHSEED=0`。`--dist loadscope` SHALL 为文档化默认，pytest-xdist SHALL 位于共同依赖锁中。

#### Scenario: Parallel full suite green
- **WHEN** 在 `PYTHONHASHSEED=0` 下运行 `pytest sjtu_tpmshx/tests/ -q -n auto --dist loadscope`
- **THEN** 结果与单进程一致（0 failed），墙钟时间显著低于单进程基线（~16 min）

### Requirement: Slow-marking policy — studies out, invariant gates in
`slow` 标记 SHALL 按角色而非单纯耗时：实测 > ~45 s 且属**研究型/冗余等价型**（网格收敛研究、优化器质量对比、并行==串行等价）且同路径有廉价覆盖存留的测试标 `slow`；**不变量门**（严格能量守恒 `test_conservation_3d_energy`、asym δ=0 位相同 `test_asym_porosity_3d`、sizing golden）无论耗时 SHALL NOT 标 `slow`（CI 必须保留）。标记 SHALL 逐测试而非整模块。全量本地门（无 `-m` 过滤）仍 SHALL 是 "done" 判据。

#### Scenario: Fast subset materially faster
- **WHEN** 运行 `pytest sjtu_tpmshx/tests/ -q -m "not slow" -n auto --dist loadscope`
- **THEN** 0 failed，且墙钟时间低于全量并行运行

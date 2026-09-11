# 执行包静态校验记录

日期：2026-09-10。对象：本包 Graph、任务卡、初始状态与只读检查脚本。

> 本文件是初始执行包的静态检查记录；下文的 planned 仅描述当时状态。
> 当前实施与验收见[本目录索引](README.md)和[state/](state/)。

**不是 GitHub 仓库的数值测试、不是三模块改造验收，也不是 C++/OpenFOAM 接入完成证据。所有节点仍为 planned。**

已执行：45 个节点、110 条依赖的 DAG 检查；节点/分支唯一性；依赖存在性；任务卡、状态文件及验收文字对应；无依赖关系节点之间的声明写路径冲突检查；里程碑可达性；工具脚本语法；图校验器 8 个单元测试。声明所有权检查不能保证未来 Git diff 没有越界，实际执行仍须按 OPERATIONS 检查。

检查器只支持精确路径或末尾 /** 子树，这是本图采用的模式范围。祖先与后继可以按显式交接复用路径；无依赖节点的重叠写范围拒绝。工具只显示拓扑就绪，资源和权限仍需执行协调者核查。

## validate

```text
PASS: JSON/schema essentials, unique ids/branches, dependency references, DAG,
      task card/state parity, declared acceptance parity, independent write ranges, state names.
Goal TM1 | plan 2.0 | reference 5f1cafb0c7e461a8c30a8ea96920ce03a828e412
Nodes: 45; dependency edges: 110
Scopes: architecture=37, backend_extension=5, document_capability=3
States: planned=45
Topological layers (illustrative, not synchronized execution waves):
  0: G00
  1: B20, B30, B40, E00, G10
  2: A10, A20, A30, A40, D10, D20, H10, H20, H30, M00, P20, P30, Q10, R20, R30, S20, S30, S40, X10, X20
  3: I20, I30, I40, P40, X21, X30
  4: I51, I55, V20, V30
  5: I52, I53, I54, I56, V40, X11, X22
  6: Z00
  7: Z10
This is plan metadata only: no numerical or integration test is performed.
```

## ready

```text
Topologically ready (resources, permissions and ownership leases still need checking):
  G00: 执行基线、授权与所有权登记 | needs: repository_read, workspace_write
```

## impact X21

```text
X21: hard-dependency descendants (2): X22, Z10
Unrelated nodes remain schedulable; a shared resource or contract incident may have additional scope.
```

## impact D20

```text
D20: hard-dependency descendants (8): V20, V30, X11, X22, I56, V40, Z00, Z10
Unrelated nodes remain schedulable; a shared resource or contract incident may have additional scope.
```

## 工具单元测试

```text
test_cycle_rejected (__main__.GraphCheckerTests.test_cycle_rejected) ... ok
test_diamond_is_acyclic (__main__.GraphCheckerTests.test_diamond_is_acyclic) ... ok
test_duplicate_id_rejected (__main__.GraphCheckerTests.test_duplicate_id_rejected) ... ok
test_missing_dependency_rejected (__main__.GraphCheckerTests.test_missing_dependency_rejected) ... ok
test_ordered_handover_allowed (__main__.GraphCheckerTests.test_ordered_handover_allowed) ... ok
test_parallel_writer_conflict (__main__.GraphCheckerTests.test_parallel_writer_conflict) ... ok
test_path_prefix_is_not_directory (__main__.GraphCheckerTests.test_path_prefix_is_not_directory) ... ok
test_unsafe_pattern_rejected (__main__.GraphCheckerTests.test_unsafe_pattern_rejected) ... ok

----------------------------------------------------------------------
Ran 8 tests in 0.002s

OK
```

本次没有运行 SJTU-TPMSHX 数值环境或测试，也没有修改 GitHub 源码、提交、创建 PR 或合并。当前远端 CI 的状态仅作为计划参考，详见 SOURCES.md。

# 历史资料索引

当前架构与运行方式见[架构说明](../architecture.md)和[项目 README](../../README.md)。

## 保留在当前仓库的历史文档

| 内容 | 入口 | 阅读范围 |
| --- | --- | --- |
| 旧项目手册 | [PROJECT_MANUAL.md](PROJECT_MANUAL.md) | 原根目录手册，旧目录地图、命令和模型说明仅作历史参考 |
| 旧开发日志 | [devlog.md](devlog.md) | 原始工作记录，保留已注明的同步缺口 |
| V2 README | [v2-readme.md](v2-readme.md) | 来源版本的精度与物理说明 |
| 2026-07 升级收尾记录 | [upgrade-2026-07.md](upgrade-2026-07.md) | 当时的分支和验收记录 |

旧手册和开发日志归档自 `8041602`，正文保留原样；当前目录地图见
[主体源码导航](../../sjtu_tpmshx/README.md)和[仓库导航](../README.md)。

本次旧阻力模型及专属资产退役见 [2026-09-12 历史模型索引](legacy-models.md)。

## 通过固定提交查阅的历史产物

下列历史产物已从当前文件树移除，原文与原始数字固定保存在已合并的
[d3ba040](https://github.com/alexlu997/SJTU-TPMSHX-TM1/commit/d3ba040de0d43fce8e9b485396a5b660c2d87c5f)。

| 内容 | 历史入口 | 文件数 |
| --- | --- | ---: |
| 旧 README／报告图片 | [assets](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/d3ba040de0d43fce8e9b485396a5b660c2d87c5f/assets) | 8 |
| 2026-05-13 优化输出 | [qnehvi_3d_20260513_175108](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/d3ba040de0d43fce8e9b485396a5b660c2d87c5f/opt_runs/qnehvi_3d_20260513_175108) | 7 |
| 2026-04 未采纳的模型探索 | [scratch 结论及失败原因](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/d3ba040de0d43fce8e9b485396a5b660c2d87c5f/reports/scratch/README.md) | 6 |
| 2026-07 架构与交接快照 | [Atlas 索引](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/d3ba040de0d43fce8e9b485396a5b660c2d87c5f/docs/atlas/README.md) | 19 |

探索记录中的失败与未采纳结论保留原状，不作为当前模型的新验收。
历史网格收敛图仍可用 `sjtu_tpmshx/runs/tools/plot_grid_convergence.py` 和对应原始 CSV
重新生成，输出位于已忽略的 `reports/figs/grid-convergence.png`。

当前模型资源、冻结基线、正式失败证据、Graph 验收记录，以及仍被复现脚本读取的
`reports/m1_uniform_vs_graded/` 留在原位置。

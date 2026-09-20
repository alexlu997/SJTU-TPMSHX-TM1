# 历史资料索引

当前架构与运行方式见[架构说明](../architecture.md)和[项目 README](../../README.md)。

旧手册、开发日志、V2 README、已结束工程和固定试验已移出当前树，
从[退役工具索引](retired-tools.md)查阅固定提交中的原文件。
旧 γ/RBF、SmoothDF 等阻力模型及原报告见[模型退役索引](legacy-models.md)。
2026-09-20 退役的 sCO2 Nu 旧锚定 γ、拟合与逐温度报告工具见
[固定源码入口](legacy-models.md#sco2-nu-旧锚定路线2026-09-20)；现行总有效系数
与使用范围见[模型资源](../model-resources.md#sco2-有效-nu-系数)。
旧 OpenSpec 拆分方案与 CSV 状态原稿也由
[文档归档索引](retired-tools.md#旧规范与状态原稿归档2026-09-13)追溯；
当前补充规范保留在 `openspec/specs/`，不把历史稿中的“当前”当作本版状态。

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
当前运行资源与有效测试留在代码树；旧冻结快照、正式失败证据和 Graph 验收记录按下节固定入口保留。

## 2026-09-18 历史材料整理

下列原文件从当前树移出，内容与原数值固定保存在已合并提交
[5534369](https://github.com/alexlu997/SJTU-TPMSHX-TM1/commit/5534369de8f1f9e535076b36b55d2bce2c1d1e38)。
本地也保留原文件副本；新研究过程和输出只保存在本地 `.cache/`。
这里的历史入口不要求当前代码重新执行已退役的命令，也不代表重写 Git 历史。

| 历史材料 | 固定入口 | 当前用途或替代位置 |
| --- | --- | --- |
| 三模块原始需求、任务图、45 项状态与证据 | [three-module-graph](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/5534369de8f1f9e535076b36b55d2bce2c1d1e38/docs/plans/three-module-graph)（176 文件） | [能力范围](../capabilities.md)保留 7 项 planned、Z10 blocked 及解除条件；完整原要求从历史读取 |
| 8 份日期报告与 3 份阶段计划 | [报告](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/5534369de8f1f9e535076b36b55d2bce2c1d1e38/docs)、[计划](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/5534369de8f1f9e535076b36b55d2bce2c1d1e38/docs/plans) | 维护、精度/性能、架构、Nu 速度、压力边界、空气—水收敛和阻力标定的当时记录；现行规则集中到架构和模型资源说明 |
| 拟合结果表与原导航 | [reports](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/5534369de8f1f9e535076b36b55d2bce2c1d1e38/reports)（7 CSV + README） | Nu/DF 的当时研究输出；复核工具现在写入 `.cache/reports/`，生产系数资源仍保留 |
| 3D golden 与元数据 | [golden_3d.json](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/5534369de8f1f9e535076b36b55d2bce2c1d1e38/golden_3d.json)、[meta](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/5534369de8f1f9e535076b36b55d2bce2c1d1e38/golden_3d.meta.json) | 2026-07 的环境相关快照，不是当前 CI 或实验精度基准 |
| 手工 2D/3D golden 捕获脚本 | [原 _out](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/5534369de8f1f9e535076b36b55d2bce2c1d1e38/sjtu_tpmshx/runs/_out)（2 脚本） | 有效二维测试配置已就地移入测试，三维配置原本就在 tests/cases_3d.py |
| 旧 γ 投影快照 | [原 JSON](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/5534369de8f1f9e535076b36b55d2bce2c1d1e38/sjtu_tpmshx/tests/_data_df_projection_baseline.json) | 当前投影测试使用可解析的合成系数，不读取旧模型数据 |
| 2026-05-04 partial-B 事后审计 | [原脚本](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/5534369de8f1f9e535076b36b55d2bce2c1d1e38/sjtu_tpmshx/validation/cases/audit_partial_b_ltne.py) | 已结案的单次诊断；现行守恒检查和求解器证据字段继续保留 |
| 外部 AI 流程模板 | [agents](https://github.com/alexlu997/SJTU-TPMSHX-TM1/tree/5534369de8f1f9e535076b36b55d2bce2c1d1e38/docs/agents)（3 文件） | 不属于程序运行、CI 或现行项目规则 |

原始 B40 失败、未采纳候选、冻结数值和状态不变。M-A 完成及后续修复不将
原失败记录改成通过；M-B 仍需分别实现并验收。当前标定公式、数据列和范围见
[模型资源](../model-resources.md)，不再从日期报告推定现行参数。

# 主体源码：sjtu_tpmshx

[中文](README.md) | [English](README.en.md)

全部核心源码位于这个包内。首次配置、公开算例和启动步骤见[项目 README](../README.md#first-run)。
命令均从仓库根目录执行。完整模块边界和物理约束见[架构说明](../docs/architecture.zh-CN.md)。

## 四个计算入口

| 文件 | 公开入口 | 职责 |
| --- | --- | --- |
| [compute.py](compute.py) | `compute` | 主计算入口，校验配置并统一组织三个阶段；返回 CaseData、FieldResult 和 PerformanceResult |
| [preprocess/api.py](preprocess/api.py) | `prepare_case` | 准备实际网格、边界、设计场、模型资源和可移植运行输入 |
| [solvers/api.py](solvers/api.py) | `run_case` | 消费 CaseData，经 Python 绑定执行 C++ 数值求解，返回原生场和运行状态 |
| [postprocess/api.py](postprocess/api.py) | `evaluate` | 从 FieldResult 组织指标评估与资格结论，不重跑求解 |

```text
compute -> preprocess.api.prepare_case -> CaseData -> solvers.api.run_case -> FieldResult
                                                                       -> postprocess.api.evaluate -> PerformanceResult
```

`compute` 同时处理阶段进度、取消、耗时与警告。`postprocess/api.py` 将完整 2D/3D、Quick Design 评估及独立查询交给原生结果阶段。
`shared/_native_result_stage.py` 适配证据、NumPy 事件与返回对象；`postprocess/export.py` 负责导出。
当前正式计算支持矩形二维与长方体三维。公开输入和文件交接见[示例](../examples/three_module/)与[数据契约](../docs/contracts/three_module_v1/README.zh-CN.md)。
近似模式和扩展状态见[能力范围](../docs/capabilities.md)。

[原生阶段 SDK](../docs/native-stages.zh-CN.md)提供独立的 C++ 调用流程。
首条完整路径支持规定入口速度的均匀、对称二维 air/air。
准备 v2 为规定速度、均匀对称二维几何增加 air/water/sCO2/CO2 的全部 16 个有序配对。
准备 v3 为均匀二维总质量流量增加独立容量查询、入口流量解析和完整准备，复用物理入口网格，
并将前段记录与最终准备证据分开。
准备 v4 增加规范连续 XY 场与完整局部阻力。
准备 v5 增加规定速度、CFD 阻力和零 delta 下的原始 air/air 条带与矩形。
它的独立热几何与行阻力保留原离散规则。
准备 v6 增加原始 air/air sigmoid 控制，以及支持生产分辨率冷构建、可复用的原生 LUT。
它保留独立热几何和行阻力，不使用离散平滑。

准备 v8 为这些 air/air 空间输入增加容量查询、流量解析和完整固定流量准备。
它保留物理网格和几何，在换热计算前解析速度，并拥有复制后的区域、控制点与 LUT。
域长／端口类型输入与独立的前段证据仍明确保留。
准备 v9 通过带类型的宿主缓存钩子连接对称空间几何的 Python 准备、容量查询与解析。
`preprocess/native_preparation.py` 共享缓存与证据传输，未命中时由原生阶段计算。
Python 保留 LUT 存储，缺表时原生代码在原几何检查点构建。

Python 准备入口对对称均匀和连续二维输入使用 v7 及 v3/v4 载荷，对 air/air 空间输入使用 v9。
非零 delta 与三维准备保留明确原路径。
公共 ZoneConfig 与 sigmoid 组合查询在单独迁移通过前仍保留独立调用和偏移几何消费者。
CaseData 与保存文件契约不变，原生失败直接传播，不选择其他准备路线。
run v2 通过现有 model-h 或 true-h 驱动消费准备 v2；run v1 保留原 air/air CFD 范围。
独立 Quick Design 路径支持 native double 工况，并保留既有 LTNE 模型。
阶段迁移期间，上述 Python 入口继续保留全部现有模式。

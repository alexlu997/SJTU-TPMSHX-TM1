<a id="file-transport-v1"></a>

# 文件传输 v1

[中文](files.zh-CN.md) | [English](files.md)

`case.yaml` 是安全 YAML 清单，包含模式版本、记录类型、Case ID 和同目录 `case.h5` 文件名。HDF5 是准备态数据的权威来源；两个文件必须一起复制。也支持直接以 `.h5` 为入口。YAML/JSON 源配置是公共前处理阶段的另一种输入。文件加载器不得重新运行前处理，也不得从快照重建 Case。

HDF5 保存根级模式和类型属性、UTF-8 JSON 描述符，以及 `/arrays` 下的数值数组数据集。描述符为映射、序列、ModelRef 记录、字节和非有限诊断标量添加类型标签。数组具有精确的 dtype/shape 描述符，并保存为真实 HDF5 数据集，不使用 pickle/NPZ 载荷。未知版本、缺失字段、变化的 dtype/shape、对象数组、外部链接及虚拟或外部数据集都必须拒绝。恢复数组的底层缓冲区不可变。文件边界校验物理网格轴、SI 宽度与边缘，以及场元数据。

显式原生压力单位必须为 `Pa`。原生质量通量单位在二维中必须为 `kg/(s m)` 或 `kg/(m s)`，在三维中必须为 `kg/s`。内存后处理前也检查这些声明；矛盾单位不得自动转换。

`results.h5` 保存已完成的执行结果，包括 `converged=False`。失败或取消产生的部分数据不能保存为正常完成结果。`metrics.json` 使用标准 JSON：不可用值为 null，并带有明确原因和状态；有限的可用值保留 MetricSpec 单位和版本。非有限诊断保留在 HDF5 中，不能转换成有效指标。

公共阶段命令为：

```
python -m sjtu_tpmshx.cli prepare config.json case.yaml --case-id example
python -m sjtu_tpmshx.cli solve case.yaml results.h5
python -m sjtu_tpmshx.cli postprocess results.h5 metrics.json
python -m sjtu_tpmshx.cli run config.json output-directory --case-id example
```

以上命令使用当前工作树 `.venv-path` 中的解释器。退出码 0 表示该阶段完成其声明的检查。solve/run 未收敛时返回 2；postprocess 请求的核心指标不可用时返回 2；取消返回 130。postprocess 返回 0 不改变存档运行的数值或物理状态。阶段异常作为失败向上传播。

`results.vtk` 是传统 ASCII 直角坐标网格。物理坐标单位为 m，单元数据保留原生顺序；嵌入的 UTF-8 JSON field-data 数组记录单位、轴、状态和运行状态。二维使用单一 z 坐标，不虚构拉伸深度。ASCII VTK 要求场值有限；NaN/Inf 诊断场保留在 HDF5 中。场与指标通过 HDF5、VTK 和 JSON 交换；可视化读取已记录的场及其物理轴。

准备态 `_environment` 记录活动的 SIMPLE 收敛模式、压力射击、可变 rho-cp、sCO2 可压缩性、加速标志和固体曲折度覆盖来源。运行时读取冻结的覆盖值，不使用接收方环境替换。准备好的固体导热率拥有其实际数值。性能分析和 CPU 调度设置属于执行层。

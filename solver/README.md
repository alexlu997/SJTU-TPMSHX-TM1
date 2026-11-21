# 从一个二维换热工况读求解器

[English](README.en.md)

打开[二维空气算例](../examples/cpp/air_2d.cpp#L15-L17)。它把两侧的入口速度、温度、压力和芯体几何交给前处理，接着求解，最后输出工程指标。

| 顺序 | 去哪里读 | 在这里看什么 |
| --- | --- | --- |
| 1. 准备工况 | [二维 prepare_case](../preprocess/preparation_case.cpp#L1083) | 从几何得到孔隙率和水力直径，在实际网格上准备两侧端口和阻力。连续二维场在这里分出供流体使用的孔隙率。 |
| 2. 推进一轮求解 | [Full2DRun::advance_impl](full_2d.cpp#L1095) | 顺着 outer_boundary、flow_boundary、thermal_boundary 读。先更新流场，再推进温度，最后检查外迭代收敛或次数上限。速度和压力的具体迭代见 [SIMPLE 二维实现](simple_2d.cpp)。 |
| 3. 计算工程指标 | [evaluate](../postprocess/result_stage.cpp#L1254) | 从求解场和随场保存的数据选取适用指标。[指标公式](../postprocess/result_metrics.cpp)计算换热量等结果，[守恒检查](../postprocess/result_balance.cpp)核对质量与能量收支。 |

**从哪里转入其他流程**

- **三维**沿用三阶段调用。对照[三维算例](../examples/cpp/run_3d.cpp)与 [Full3DRun::advance](full_3d.cpp#L1500) 阅读三维推进过程。
- **快速设计**从[单候选算例](../examples/cpp/quick_design.cpp)进入独立的[快速设计求解](quick_design_run.cpp)，随后评估该候选的结果。
- **暂停和续算**从 [Full2DRun::snapshot](full_2d.cpp#L1320) 读取迭代状态。[恢复算例](../examples/cpp/resume_2d.cpp)演示原生状态恢复。桌面应用从磁盘继续计算的入口是 [resume_run](../python/applications/execution/recovery.py#L67)。

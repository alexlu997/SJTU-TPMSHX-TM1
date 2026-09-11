# B40 冻结案例完整输入与比较依据

2026-09-11。输入来自冻结测试、其 evaluator 默认配置和实际调用；不是新物理范围。
四项旧观测/锁定输出原值见 `application-path-map.md`，差异见 `failure-triage.md`。

## 共同输入

| 参数 | 值 |
| --- | --- |
| 工质 A / B | air / air |
| 入口温度 A / B | 350 / 300 K |
| 入口绝对压力 A / B | 101325 / 101325 Pa |
| 入口速度 A / B | 10 / 10 m/s；未指定独立质量流量，实际面质量另采集 |
| 流向 / 开口 | A +x，B -y；全端面入口/出口 |
| 宏观 x / y | 0.10 / 0.05 m |
| 拓扑 / 固体 | Diamond；k_s=17 W/(m K)，rho_s=2700 kg/m³ |
| 控制场 | 4×4，y 对称，三次插值；L_bounds=[4,8] mm，t_bounds=[.3,.5] mm；材料属性按 .05/.01 mm 量化 |
| D-F 默认 | cfd_full_core_3cell_fixed_v2；须同时记录进程环境覆盖 |
| 制造性惩罚 | 开启，权重 1；目标 dP 不应未经核查直接当作原始两侧压降 |
| 拒绝设置 | dp_cap_pa=1e6；reject_unconverged=False |

非均匀输入（mm，顺序不可改变）：
L=`[5,6,7,8,5.5,6.5,7.5,6]`，t=`[.40,.45,.50,.55,.42,.48,.52,.46]`。

| 案例 | 局部 L/t | 网格 / 深度 | 原预算 |
| --- | --- | --- | --- |
| 2D uniform | 6 / .4 mm | 52×26；单位深度 | SIMPLE 800、tol=1e-3；LTNE 1500、tol=.5 K；密度循环 1 |
| 2D nonuniform | 上述向量，经插值/边界限制 | 50×25；单位深度 | 同上 |
| 3D uniform | 原始八个 L=4、八个 t=.6 mm；实际 t=.5 mm | 10×6×3；z=.042 m | SIMPLE 300、tol=1e-2；LTNE 800、tol=.5 K；outer 2 |
| 3D nonuniform | 上述向量，沿 z 挤出 | 10×6×3；z=.042 m | 同上 |

2D 网格按控制场平均 L/t 的 D_h 计算：Nx=max(20,round(.10/(.8 D_h)))，
Ny=max(10,round(.05/(.8 D_h)))。实际 Nx/Ny 应从准备数据或历史执行采集，
本次在 cef75a5 调用原 `_resolve_grid` 得到表中 52×26/50×25，原生退出 0，未启动 2D 求解。非均匀控制场不等于非均匀网格间距。

原生 3D 场进一步确认：uniform 的 t_field 全为 .5 mm，L_field 为 4 mm（末位浮点尾数）；nonuniform 的采样 L_field 范围为 [5.641479492187501,8] mm，t_field 为 [.43044433593750003,.5] mm。因此不能把原始控制值 .6 mm 当作实际参与闭合的厚度。这是既有场边界行为，未在本次改变。

3D 其他控制：outer 温差阈值 .5 K、松弛 .6；LTNE alpha_T=.7、
conservative_ltne=True；legacy SIMPLE 判据，A 温度/密度外更新、B 冻结流场；
未传 model-h 的 model_mass/model_fluids 输入。roughness=norris_1a，100 µm，
其摩擦修正是历史 baseline no-op。两次外迭代的预算耗尽不表示收敛。

四项断言只检查 `(Q_neg,dP,mass)`，使用 pytest.approx(rel=1e-12)，
且未显式设置 abs，因此还保留 pytest 默认绝对容差 1e-6。
此断言不是边界能量或工程收敛判据。2D 目标单位 W/m、Pa、kg/m；
3D 原生 Q/mass 为 W/kg，经实际 .042 m 除法后才形成同单位的优化目标。

## 版本与环境

2D 最后锁定值更新是 `dafdc92`；3D 是 `fd2e001`。
`fd2e001` 的原 3D 测试于本次匹配 71 包环境复现：2 passed、2 deselected，
72.15 s，原生退出 0。命令为 `python -m pytest
sjtu_tpmshx/tests/test_evaluator_frozen_values.py -q -k 3d
--timeout=600 --timeout-method=thread`，解释器为
`/Users/luwenhuan/.venvs/sjtu-tpmshx-py313/bin/python`。
该工作树 `.venv-path`、精确锁检查和 pip check 均通过；锁文件在
fd2e001 至 5f1cafb 间未变。Matplotlib/XDG 使用工作树 .cache。
本次允许列出的 TPMSHX_DF_METHOD、TPMSHX_DF_OVERRIDES、
TPMSHX_DF_RESIDUAL_CORR、TPMSHX_CONV_MODE、TPMSHX_CHI_S、
NUMBA_NUM_THREADS、OMP_NUM_THREADS 环境变量均未设置，采用源码默认。
原历史 pin 捕获进程没有完整环境记录，不能事后补称它完全相同。

旧 4/4 失败观察在 `5f1cafb`；迁移前 `961fbb6` 与其四行数值相同。
当前迁移候选 `60417cf` 的环境为新增文件交接依赖后的 73 包锁，
不能用它的完整环境冒充历史 71 包运行。原始失败和新复现分列保存。

## 下一对照

先比较 `5adb61d` 的直接父提交 `cef75a5` 与 `5adb61d`，保持原两项
3D 输入和 outer=2。采集各次 LTNE 返回原生数组、实际面速度/热容通量、
SIMPLE 压力/密度/开口和状态，再核对 Q 的体积分报告路径。
需检查更早可达改动时沿历史继续向前，不能把这一对照自动叫作首次根因。
增加预算的工程资格实验单独标识；不覆盖原预算、不改变原判据。

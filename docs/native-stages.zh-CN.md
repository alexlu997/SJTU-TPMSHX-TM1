# 原生阶段接口

[中文](native-stages.zh-CN.md) | [English](native-stages.md)

## 范围

原生阶段工作增加可独立调用的准备、执行和评估接口。对应阶段通过验收前，现有 Python
入口继续作为正式运行路径。准备 v1 支持规定入口速度、CFD 阻力的均匀对称二维 air/air。
准备 v2 在相同几何和入口模式下支持 air、water、sCO2、CO2 的全部 16 个有序配对，
保留现有实验 DF 和 sCO2 Nu 选择、状态检查及适用限制，并分别保存两侧模型证据。
run v2 通过现有 model-h 或 true-h 驱动消费准备 v2。
run v1 保留 air/air CFD 范围及已公开布局。
非零 delta、分区、连续场和规定质量流量仍不在这一准备 v2 范围内。
这些限制不删除现有 Python 工作流支持的任何模式。
独立 Quick Design 入口接受 air、water、sCO2 的 native double 工况，复用既有给定流量 LTNE 驱动。

准备 v3 在同一均匀对称二维流体矩阵内增加总质量流量输入，提供独立的入口容量查询、
入口流量解析和完整准备。物理深度、标定限制与标量算术规则保持不变。
连续场、分区和非零 delta 仍不在准备 v3 范围内；已解析的均匀准备视图使用 run v2，包括总流量案例。

完整 2D/3D 的 Python 评估现已调用原生结果阶段；独立适用性、物理平衡和资格查询也使用该阶段。
原生结果阶段负责 Quick Design 指标并保留类型化中间值。V3 通过固定具名宿主操作保留既有 Python 对象、任意精度整数和最终转换协议。公开 Python 入口和保存格式继续可用。
宿主查询借用类型化证据，保留延迟输入错误，并在每个原语返回前送达 NumPy 事件。
回调错误在原指标或资格边界处理；未捕获的宿主错误保留原 Python 对象。
回调不拥有查询状态。延迟错误保留异常对象、cause/context 链接和异常组成员，但不保留这些对象原有的 traceback。查询退出时清空延迟错误引用，覆盖输入打包失败；借用的场不等待循环垃圾回收。
已发布的 v1 C 布局和查询继续保留；每个输出须通过创建它的库释放。
结果调用会拒绝错误的输出尺寸或尚未释放的 owner；这类拒绝保留借用输入、旧输出和诊断存储。

C++ 调用顺序是 `prepare_case`、`run_case`、`evaluate`。调用者提供尺寸、设计值、
边界条件和控制参数。准备库生成物理场，求解库使用该准备态，结果库评估记录的证据。

## 所有权和单位

- 使用输入字段名标明的单位。设计输入使用 mm，保存的物理设计场使用 m。执行适配生成
  输运和闭合输入时，保留原有 mm→m→mm 运算顺序。
- 请求网格数和实际网格数是不同字段。物理二维场形状是 `(nx, ny)`、C 顺序。
  每侧流动场使用现有 `(cross, stream)` 顺序。
- C 调用成功后返回一个 owner。全部数组和文本视图都属于这个 owner。最后一次使用后，
  通过创建它的同一库释放。不得复制 owner 或通过调用者分配器释放它的缓冲区。
- 回调在调用线程接收借用的事件视图，不承担数值准备。保留事件顺序、logger 名和消息。
- 结果 v3 传输原始标签和带类型的 Quick 操作数；C++ 拥有标签比较和指标规则。
  固定具名宿主回调只在选定运算处保留 Python 值协议。
  对象相等与不等比较使用独立回调；字符串子类保留原运算符。
- 宿主负责 case ID、时间戳、文件路径和 Python 对象转换。原生阶段负责物理规则、数值默认值和证据。
- 准备库、求解库使用各自锁定的 CoolProp 构建。结果库不链接准备库、求解库、CoolProp 或 Qt。
- 准备 v2 增加显式标量精度、强弱类型和布局标记。缓冲区采用 double 传输，结果标记保留原字段精度。
  失败结果为宿主保留状态细节和异常 cause；Python 特有的类型及对象检查仍由宿主负责。
- 任一 CO2 侧会为两侧选择共同的 CO2 几何。固定阻力和 Nu 因子只应用于 CO2 侧，sCO2 仍是独立模型。
  实验 DF 修正流动种子和行数组；入口静态 DF 保留原 CFD 值，并在适用时包含 CO2 固定因子。
- 现有低层 ABI 版本继续保留。归档运行库恢复保存的运行态时，不得依赖新增准备符号。
- run v2 记录实际热质量流、边界功率、能量设置和证书，供结果评估使用。
  它复制准备阶段 notice，保留当前 sCO2 适用范围限制，不为未经验证的模型授予合格结论。
- run v2 使用 v1 结果 owner 和释放函数。取消状态为 6，状态 4 保留完整驱动的包络失败含义。
  run v1 保留原取消状态 4。

## 均匀几何的总质量流量

`FlowInput2D` 选择配置中逐侧保存的目标，或显式给出的两个总流量目标。
保存的目标只替换对应侧速度，并保留在解析后的输入中；显式目标替换两侧保存目标，
并在解析后的输入中清空它们。总目标使用 kg/s，必须给出正的物理深度（m）。
准备的二维场和求解器量继续采用原有单位深度基准。

`prepare_inlet_mass_capacities` 使用物理入口的孔隙开口面积、轮廓和入口密度，
不使用过时速度、不评估 Nu，并计算两侧容量。
`resolve_inlet_flow` 用各目标除以容量，再校验解析后的速度。
没有目标时，它复制返回输入，不做物理校验或容量计算；Python 适配保留原有的无目标对象身份规则。

`prepare_case(FlowInput2D)` 在最终准备中复用物理入口网格和几何。
前段流量记录保存在 `flow.evidence`，最终记录保存在 `prepared`；回调按实际顺序报告两个阶段。
完整 flow-case 结果拥有两组视图；内部 owner 字段为 null，只释放完整结果。
深度和目标标记保留原浮点与整数标量算术，Python 对象校验和配置快照仍由宿主负责。

## 连续 XY 场

准备 v4 通过 `ContinuousInput2D` 接收规范的连续 XY 控制点，支持规定速度以及 v3 的总流量查询和准备。
v1/v2/v3 C 布局与现有 Python 正式路径保持不变。控制输入给出整数控制点数、1..3 阶、y 镜像标记、边界和决策值。
决策先放 L、再放 t，采用 mm 和 C 顺序；y 镜像时每个场只保存下半区，奇数行包含中心行。
控制值与裁剪边界均受现有几何范围约束。

现有样条核心在实际物理单元中心采样；固定流量准备在解析入口速度后复用这些场。
完整结果包含现有准备态和前段流量视图，增加四个物理单元数组：面积密度、原始水力直径及两侧流体有效导热率。
局部渗透率和 Forchheimer 数组使用各侧现有的 `(cross, stream)` 视图。
行数组保留压力种子的用途，完整局部场供运行适配使用。

CFD 模式支持两种拓扑和全部 16 个有序流体配对。
实验转移保留名义 7/0.6 mm 的上海 Gyroid air-A/water-B 契约，其域、速度规则与探索性证据不变。
CO2/CO2 固定因子路径也继续支持实验模式。
前段范围标签保留转移上下文，最终元数据保留连续场适用范围和参考几何。
run v3 通过现有 model-h 或 true-h 驱动消费准备 v4，按原顺序使用物理单元场和局部阻力。
保存的 SI 单元长度先还原为 mm，再生成输运 SI 值和闭合比值；名义参考几何与实际物理场保持独立。
请求、取消状态、结果所有权和评估沿用 run v2 契约。该接口不认证梯度几何的准确度。

## 构建和安装

先按 [README](../README.md) 配置环境和锁定依赖。新 CMake 入口只使用已经准备的本地依赖，
不获取源码、安装 Python 包或替换已发布的运行库。

使用 `.venv-path` 指定的解释器生成两个模型头文件：

```sh
"$PYTHON" -m engineering.scripts.generate_native_model_coefficients \
  --output .cache/stages/generated/tpmshx/model_coefficients.hpp \
  --df-output .cache/stages/generated/tpmshx/preparation_df_data.hpp
```

使用锁定的 CMake 可执行文件。macOS 分别提供已验收依赖缓存中的准备和求解 archive：

```sh
"$CMAKE" -S sjtu_tpmshx/solvers/native -B .cache/stages/build \
  -DTPMSHX_NATIVE_DEPS_ROOT="$PWD/.cache/native-deps" \
  -DTPMSHX_MODEL_INCLUDE_DIR="$PWD/.cache/stages/generated" \
  -DTPMSHX_PREPARATION_COOLPROP_LIBRARY="$PWD/.cache/native-deps/build/coolprop-preparation-macos-arm64/libCoolProp.a" \
  -DTPMSHX_SOLVER_COOLPROP_LIBRARY="$PWD/.cache/native-deps/build/coolprop-macos-arm64/libCoolProp.a" \
  -DCMAKE_INSTALL_PREFIX="$PWD/.cache/stages/install"
"$CMAKE" --build .cache/stages/build --config Release --parallel 1
"$CMAKE" --install .cache/stages/build --config Release
```

Windows 使用 `-A x64`，两种角色都使用锁定的 `Release/CoolProp.lib` archive；具体路径
取自已验收的依赖缓存。独立组件工程保留原有编译选项和导出符号。

设置 `-DTPMSHX_COMPONENTS=result` 可独立构建结果库，无需模型头文件或 EOS 依赖。
Linux 只支持这一组件。安装内容包括选定的共享库、C ABI 头文件、CMake 包配置及相应源码声明。

外部 C++ 工程可使用安装后的包：

```cmake
find_package(tpmshx CONFIG REQUIRED COMPONENTS result)
target_link_libraries(my_program PRIVATE tpmshx::result)
```

[外部结果客户端](../examples/cpp/result_client.cpp)通过公开头文件检查数组并评估历史证据。
[完整二维示例](../examples/cpp/air_2d.cpp)从原始尺寸、工况和边界输入开始，依次准备、求解并评估。
它不读取 Python 预生成的数值场，也不启动或链接 Python。
[多流体准备示例](../examples/cpp/prepare_fluids_2d.cpp)通过 v2 准备 CO2/water，
只链接准备库，不执行求解。
[质量流量准备示例](../examples/cpp/prepare_mass_2d.cpp)查询容量、解析显式双侧目标，再准备工况；
它同样只链接准备库，不执行求解。
[连续场准备示例](../examples/cpp/prepare_continuous_2d.cpp)从 XY 决策和总流量开始，通过 v4 提供物理场与局部阻力，且只链接准备库。
[连续场运行示例](../examples/cpp/continuous_2d.cpp)从 XY 决策和固定质量流量开始，完成准备与运行，释放准备态后再评估结果。

[均匀流体示例](../examples/cpp/uniform_2d.cpp)对 CO2/water 执行完整三个阶段。
释放准备态后，结果评估仍有效。
[Quick Design 示例](../examples/cpp/quick_design.cpp)从原始工况和尺寸开始，调用
`prepare_quick_design`、`run_case`、`evaluate`。这些示例只使用安装的公开头文件与共享库。
Windows 构建会将所需 DLL 复制到可执行文件旁。

```sh
"$CMAKE" -S examples/cpp -B .cache/stages/examples \
  -DCMAKE_PREFIX_PATH="$PWD/.cache/stages/install"
"$CMAKE" --build .cache/stages/examples --config Release
"$CTEST" --test-dir .cache/stages/examples -C Release --output-on-failure
```

准备态、运行结果和评估结果是可移动、不可复制的 C++ 对象。运行结果拥有评估所需的证据，
因此调用 `run_case` 后可以释放准备态。直接 C 调用的 owner 与借用视图规则见对应头文件。
空的评估请求返回该模式全部指标；指定指标时保留其单位、定义版本、可用状态和原因。
独立适用性、物理平衡和资格查询使用同一个结果库。

现有依赖构建完成后，以下检查会复用组件构建目录，临时安装 SDK，并在源码树外构建和运行调用程序：

```sh
"$PYTHON" engineering/scripts/build_native_dependencies.py check-stages
```

该命令使用当前环境的适用锁；BO 环境须传对应的 `--python-lock`。
Linux 另传 `--component result --python-lock engineering/requirements/postprocess.txt`。
检查命令保留日志、二维对照字段和 Quick Design 对照字段，删除临时安装和外部构建目录。
这些原生路径不代表离散分区或三维已完成阶段迁移。
Python 接入及检查点恢复仍有各自的验收关口。

## Quick Design 阶段

`quick_design_stage_c_api.h` 定义独立的版本 1 合同，不修改既有 ABI。
准备库负责几何、均匀网格、入口态物性和解析 D-F 压降分数。
求解库调用既有 Quick Design 驱动，不运行 SIMPLE。
结果库评价记录的字段和最终物性过程标量。

原始胞元长度和壁厚使用 mm；外形尺寸使用 m，温度使用 K，绝对压力使用 Pa，
质量流量使用 kg/s。叉流保持 `(60, 40, 1)` 网格；逆流保持 `(60, 1, 2)`。
可选标志区分缺省值和显式无效值。高度默认取宽度，固体导热率默认为
16 W/(m K)，容差默认为 `1e-5`。各流向的预算、松弛、分块和热量容差保持不变。
D-F 继续使用固定 CFD 表。宿主在调用前解析环境中的方法选择；原生入口不读环境变量。

准备态复制外部热启动场；运行复制准备场且不修改原准备态。const 物性执行一次
热过程，mean 执行两次，第二次使用第一次返回的温度。入口解析压降分数在两次
过程中保持不变。结果拥有全部 15 个场、物理网格宽度、压力证据、最终物性标量，
并保留驱动返回的完整过程记录。取消返回状态 6 且不发布结果。
现有驱动没有每次调用的 CPU 参数；进程线程控制保持原行为。

原生 double 路径与 Python 标量和对象协议分别验收。Python 准备、保存态验证、
警告路由和 Quick Design 指标适配仍有生产消费者。数值数组、NumPy 错误策略、
任意精度整数和对象需要独立的边界检查，之后才能切换生产入口。
C++ 示例不代表这些检查已通过，也不代表 N12 退役已完成。
Quick Design 保持定尺近似；数值收敛不建立物理验证、适用性或设计资格。

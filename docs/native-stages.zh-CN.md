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

准备 v3 在同一均匀对称二维流体矩阵内增加总质量流量输入，提供独立的入口容量查询、
入口流量解析和完整准备。物理深度、标定限制与标量算术规则保持不变。
连续场、分区和非零 delta 仍不在准备 v3 范围内；已解析的均匀准备视图使用 run v2，包括总流量案例。

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

## 运行续算

`Run2D` 接收均匀 v2 或连续 v4 准备视图，支持创建、步进、阶段查询、快照、恢复及结果转移。
它复用现有完整二维状态机和带类型的状态，不重置已消耗的计算工作。
恢复必须使用相同构建、准备输入和数值控制；正的 CPU 线程数可以改变。

结果转移或运行释放前，准备 owner 必须保持存活且不可修改。
运行复制数值输入和控制，借用准备证据用于结果捕获。
回调上下文必须保持存活直到运行释放；同一运行的调用不得重叠。
快照拥有独立存储；完成结果在准备和运行释放后仍拥有其证据。
全部查询与释放必须使用创建对象的库；取消不能发布成功的阶段结果。

`RunRequest2Dv3` 增加六项独立可选能量控制和可选焓更新门槛。
缺省值由所选运行库提供。这些控制仅适用于现有 true-h 路径，
不得与完整显式能量控制指针或启用的 model-h 控制并用。
现有一次性接口保留其布局和行为。
此接口尚未替换 Python 正式检查点路径，也尚未提供替换所需的完整 `FieldResult` 捕获。

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
[均匀流体示例](../examples/cpp/uniform_2d.cpp)对 CO2/water 执行完整三个阶段。
释放准备态后，结果评估仍有效。
[质量流量准备示例](../examples/cpp/prepare_mass_2d.cpp)查询容量、解析显式双侧目标，再准备工况；
它同样只链接准备库，不执行求解。
[连续场准备示例](../examples/cpp/prepare_continuous_2d.cpp)从 XY 决策和总流量开始，通过 v4 提供物理场与局部阻力，且只链接准备库。
[连续场运行示例](../examples/cpp/continuous_2d.cpp)从 XY 决策和固定质量流量开始，完成准备、运行和评估；评估前已释放准备态。
[续算示例](../examples/cpp/resume_2d.cpp)从原始输入创建运行，保留流动快照、释放运行，并更换 CPU 线程数后恢复。
这些示例只使用安装的公开头文件与共享库。
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
检查命令保留日志与二维对照字段，删除临时安装和外部构建目录。
这些二维运行路径不代表离散分区、三维或 Quick Design 已完成阶段迁移。
Python 接入及检查点恢复仍有各自的验收关口。

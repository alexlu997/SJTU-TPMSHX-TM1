# 原生阶段接口

[中文](native-stages.zh-CN.md) | [English](native-stages.md)

## 范围

原生阶段工作增加可独立调用的准备、执行和评估接口。Python 保留公共入口与原有数据契约。
对称均匀和规范连续 XY 二维准备使用原生阶段；非零 delta 均匀、离散分区、sigmoid 与三维
使用各自明确保留的原路径。原生加载或执行错误不会选择其他路径。准备 v1 支持规定入口速度、CFD 阻力的均匀对称二维 air/air。
准备 v2 在相同几何和入口模式下支持 air、water、sCO2、CO2 的全部 16 个有序配对，
保留现有实验 DF 和 sCO2 Nu 选择、状态检查及适用限制，并分别保存两侧模型证据。
run v2 通过现有 model-h 或 true-h 驱动消费准备 v2。
run v1 保留 air/air CFD 范围及已公开布局。
非零 delta、分区、连续场和规定质量流量仍不在这一准备 v2 范围内。
这些限制不删除现有 Python 工作流支持的任何模式。
Quick Design 保留面向 air、water、sCO2 的 native-double v1 准备及运行接口。
准备 v2 增加带类型的原始输入及独立压降分数查询。
Python 使用 v2 准备，通过固定具名宿主操作保留既有值协议。
准备／查询的流体注册表包括 CO2；这不扩大既有 air/water/sCO2 LTNE 运行范围。

准备 v3 在同一均匀对称二维流体矩阵内增加总质量流量输入，提供独立的入口容量查询、
入口流量解析和完整准备。物理深度、标定限制与标量算术规则保持不变。
连续场、分区和非零 delta 仍不在准备 v3 范围内；已解析的均匀准备视图使用 run v2，包括总流量案例。

独立的三维准备 v1 接收规定入口速度的原始对称均匀算例，支持两种拓扑、全部 16 个有序流体配对，
以及现有 CFD 和实验 DF 选择。其物理网格、带类型的端口与字段证据不改变 Python 三维生产路径。
独立的三维流量 v2 增加容量查询、流量解析及使用解析速度的完整准备。
[均匀三维准备契约](#均匀三维准备)说明输入要求与剩余关口。

完整 2D/3D 的 Python 评估现已调用原生结果阶段；独立适用性、物理平衡和资格查询也使用该阶段。
原生结果阶段负责 Quick Design 指标并保留类型化中间值。V3 通过固定具名宿主操作保留既有 Python 对象、任意精度整数和最终转换协议。公开 Python 入口和保存格式继续可用。
宿主查询借用类型化证据，保留延迟输入错误，并在每个原语返回前送达 NumPy 事件。
回调错误在原指标或资格边界处理；未捕获的宿主错误保留原 Python 对象。
回调不拥有查询状态。延迟错误保留异常对象、cause/context 链接和异常组成员，但不保留这些对象原有的 traceback。查询退出时清空延迟错误引用，覆盖输入打包失败；借用的场不等待循环垃圾回收。
已发布的 v1 C 布局和查询继续保留；每个输出须通过创建它的库释放。
结果调用会拒绝错误的输出尺寸或尚未释放的 owner；这类拒绝保留借用输入、旧输出和诊断存储。

已支持的二维 C++ 调用顺序是 `prepare_case`、`run_case`、`evaluate`。调用者提供尺寸、设计值、
边界条件和控制参数。准备库生成物理场，求解库使用该准备态，结果库评估记录的证据。

## 所有权和单位

- 使用输入字段名标明的单位。设计输入使用 mm，保存的物理设计场使用 m。执行适配生成
  输运和闭合输入时，保留原有 mm→m→mm 运算顺序。
- 请求网格数和实际网格数是不同字段。物理二维场形状是 `(nx, ny)`、C 顺序。
  每侧流动场使用现有 `(cross, stream)` 顺序。
- 返回具有所有权数组的成功 C 调用包含一个 owner，数组和文本视图均属于该 owner。
  最后一次使用后通过同一个库释放，不复制 owner，也不使用调用方分配器释放内部缓冲区。
  仅返回标量的查询（包括 Quick 压降分数 v2）直接返回值，无需释放。
- 回调在调用线程接收借用的事件视图，不承担数值准备。保留事件顺序、logger 名和消息。
- 结果 v3 传输原始标签和带类型的 Quick 操作数；C++ 拥有标签比较和指标规则。
  固定具名宿主回调只在选定运算处保留 Python 值协议。
  对象相等与不等比较使用独立回调；字符串子类保留原运算符。
- 宿主负责 case ID、时间戳、文件路径和 Python 对象转换。原生阶段负责物理规则、数值默认值和证据。
- 准备库、求解库使用各自锁定的 CoolProp 构建。结果库不链接准备库、求解库、CoolProp 或 Qt。
- 准备 v2 增加显式标量精度、强弱类型和布局标记。缓冲区采用 double 传输，结果标记保留原字段精度。
  失败结果为宿主保留状态细节和异常 cause；Python 特有的类型及对象检查仍由宿主负责。
- 任一 CO2 侧会为两侧选择共同的 CO2 几何。固定阻力和 Nu 因子只应用于 CO2 侧，sCO2 仍是独立模型。
  二维实验 DF 修正流动种子和行数组；入口静态 DF 保留原 CFD 值，并在适用时包含 CO2 固定因子。
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
Python 对称均匀和连续二维的正式运行及检查点路径使用保存输入接口。
`SavedCase2D` 借用已验证的 v2 视图及保存的热几何，不重新准备算例。
均匀保存态可含逐单元热几何与局部阻力，同时保持均匀闭合模式。
范围记录缺失与空记录分别传递；未捕获行不生成数值样本。
保存的标量及场类型保留原单位换算和闭合比运算精度。
启用 model-h 控制时，保存接口在执行前检查请求的能量算法。
它不会向数值驱动同时传递两套迭代控制。
输入及范围标记必须保持有效，直到结果转移或运行释放。

Python 在执行前检查所选库的新协议能力。归档库、非零 delta 和未迁移分区模式使用原协议。
新协议不完整或运行失败时直接报错。所有查询、状态释放和结果释放使用所选的同一库。
现有保存格式、同构建恢复要求、CPU 变更规则与公共 Python 接口保持不变。

## 捕获标量

`capture_summary(result, application)` 从完成的阶段结果返回复制的标量。
它保留主网格和细网格的 model-h 面积与单元数、Nu 下限观测、
主热态压力范围、有符号热量之和、热量绝对值及压力裁剪次数。
面积与归约复用现有结果算术，并静态链接；求解器不新增结果动态库依赖。

调用方提供保存的两侧应用层面积密度和表面换热系数。
这些输入与求解器热几何、最终 h_v 场分开。查询在原有非负检查后逐侧相乘。
NaN、无穷大和有符号零保留现有算术行为。
复制的摘要不持有指针，结果释放后仍然有效。
场、历史和数值账本继续通过现有原始证据查询取得。
Python 正式结果映射及其历史运行库路径保持不变。

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
v1/v2/v3 C 布局保持不变；Python 将其 owner 持有的结果适配为原有 CaseData schema。控制输入给出整数控制点数、1..3 阶、y 镜像标记、边界和决策值。
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

## 均匀三维准备

`prepare_case(CaseInput3D)` 调用 `preparation_case_3d_c_api.h` 中的
`tpmshx_prepare_case_3d_v1`，返回拥有独立存储的 `PreparedCase3D`。
输入必须给出三个正的物理长度、三个网格数和显式单元数上限。
深度不可省略，`Nz` 至少为 2；C++ 输入的默认上限为 2,000,000 个单元。
宿主在调用前解析配置及环境中的上限，库本身不读取这些设置。

两侧端口都必须启用。接口支持六个流向、整面和局部开口，以及可选的第二横向窗口。
端口值保留标量类型标记；均匀及 `port_wall_refine` 网格使用现有物理网格规则。
字段采用物理 `(x,y,z)` 形状和 C 顺序；开口掩码采用物理 `(cross1,cross2)` 顺序。
每侧记录轴置换和反向标记，不反转物理单元宽度。

owner 保留名义几何、物理宽度与边界、设计场、入口物性、模型选择、范围、通知和 DF 应用证据。
两侧孔隙率已包含对称拆分，不得再次除以二。返回的 K/cF 场保留未缩放的 CFD 基础值；
逐侧证据单独记录 CO2 或实验因子，供后续执行使用。
原有状态检查、标定限制和 sCO2 Nu 选择保持不变。

接口借用输入和 v1 事件回调直到返回；成功时提交一个 owner，失败不发布准备结果。
全部视图完成最后一次使用后，须通过创建 owner 的准备库释放该 owner。
v1 接口不接收总质量流量目标。独立的 `FlowInput3D` v2 为同一均匀几何提供
`prepare_inlet_mass_capacities`、`resolve_inlet_flow` 和 `prepare_case`。
容量使用实际物理入口切片、该侧孔隙率、开口面积和密度；不使用过时速度，不检查 Nu 或实验速度窗口。
显式目标替换两侧配置中的质量输入；混合输入保留另一侧速度，无目标解析只复制输入，不执行物理准备。
完整准备只构建一次几何，解析两侧速度后执行原有速度和模型检查。
最终证据保留静态物性观测在前、解析速度预检和最终 air/DF 观测在后的原顺序。
组合 owner 提供借用的准备态和流量视图，嵌套 owner 均为空。
`ContinuousInput3D` v3 为三个流量操作增加规范的 XY 挤出和真实 XYZ 控制点。
即使 z 控制点数为一，`have_ctrl_z` 仍选择 XYZ；决策值先保存全部 L，再保存全部 t，z 变化最快。
采样使用最终物理单元中心；XY 与 XYZ 保留各自的样条规则及可选 y 对称性。
owner 分别保留原始设计几何与热几何的 mm→m→mm 路径，返回完整局部 K/cF、面积密度、水力直径和热孔隙率。
原有连续上海转移限制及 CO2 因子保持不变；离散分区和非零 delta 仍不属于这些原始接口。
Python 三维准备、宿主缓存钩子、原生三维运行／捕获接入、接近单元上限的内存检查，
以及真实三维 BO 仍是独立的迁移和验收关口。
保存的 CaseData 继续使用现有校验器，不得重新准备。

## 保留类型的域长和端口

准备 v7 增加 `GridKinds2D`，描述既有域长及每侧四个端口值的标量类型。
网格、开口、入口容量和空间采样保留 NumPy 整数及 float16/32/64 的运算规则。
C++ 调用将描述符作为第二个参数，将准备选项作为第三个参数。
[类型网格示例](../examples/cpp/prepare_typed_grid_2d.cpp)检查固定质量流量下的整数与 float16 混合端口。
C 入口将相同描述符与既有 v3/v4 输入及输出布局配对使用。
若再次准备已解析输入，须同时保留描述符；结果仍用原对应函数释放。
此前的 C 和 C++ 入口继续将域长及端口值作为弱类型 double。
该接口不改变物理范围或保存文件格式。

## Python 准备适配

公共准备、容量查询和流量解析入口对受支持的二维输入使用 v7 入口及 v3/v4 载荷。
适配器先复制数组、标量类型与证据，再释放原生 owner；保存的工况保留原 schema、SI 场、控制量和模型引用。
前段质量流量记录仍位于最终准备的警告作用域之外。

v3/v4 调用可以通过 `values` 成员传入 `tpmshx_preparation_case_callbacks_v2`；该成员声明版本 2 和完整描述符大小。
可选宿主钩子在最终准备入口、名义几何和每侧入口物性边界执行，按原时序检查 Python 对象规则，不提供数值。
钩子异常请求取消，Python 在 C 调用返回后抛出原异常。v1 回调描述符和全部输入／结果布局保持不变。

v3 回调描述符在 v2 上增加具名的几何与入口物性缓存交换，通过 `values.values` 声明版本 3 和完整大小。
回调版本 4 保留该布局，增加物理网格构建前的宿主检查点，stage 为 3、side 为 2。
Python 适配器通过该检查点，在此前几何和物性检查之后保留不支持对象的原错误顺序。
该检查点不返回数值；此前回调版本不会收到 stage 3。
范围与通知钩子在原计算点同步报告每项观测；宿主保留警告过滤器、来源位置，以及后续步骤失败前已完成的观测。
缓存记录不会重复独立警告，警告异常会停止原生操作。
未命中时由 C++ 计算；宿主可以返回已完成的缓存值及其原始范围记录。
查询视图保持有效直到阶段返回；发布视图只在回调期间有效，宿主必须在回调返回前复制。
嵌套视图不得与 result、failure 或 error 存储重叠；非法存储保持这些输出不变。
共享 Python 所有者保留 32768 项几何缓存和 4096 项入口物性缓存，保持不区分类型的键、LRU 顺序、统计、清空、并发发布和 `__wrapped__` 访问。
相等键保留第一个成功值的标量类型，材料导热系数和 chi 仍在这两个缓存之外。

生产准备中专用于连续场、局部阻力和样条复用的 Python 分支已退役。
`development/tests/preparation_*_reference.py` 下的 2026-11-11 冻结参考用于原生阶段和适配器资格比较，
不作为生产路线；独立准备比较仍需要该参考时继续保留。

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
[三维准备示例](../examples/cpp/prepare_3d.cpp)从原始 CO2/water 输入生成各轴长度及网格数不同的物理网格，
检查反向 z 端口和字段证据，只链接准备库。
[三维质量流量示例](../examples/cpp/prepare_mass_3d.cpp)在反向入口面解析总流量后完成准备。
[连续三维示例](../examples/cpp/prepare_continuous_3d.cpp)在解析总流量后，分别准备 XY 挤出和 XYZ 控制点。
[质量流量准备示例](../examples/cpp/prepare_mass_2d.cpp)查询容量、解析显式双侧目标，再准备工况；
它同样只链接准备库，不执行求解。
[连续场准备示例](../examples/cpp/prepare_continuous_2d.cpp)从 XY 决策和总流量开始，通过 v4 提供物理场与局部阻力，且只链接准备库。
[连续场运行示例](../examples/cpp/continuous_2d.cpp)从 XY 决策和固定质量流量开始，完成准备与运行，释放准备态后再评估结果。
[续算示例](../examples/cpp/resume_2d.cpp)从原始输入创建运行，保留流动快照、释放运行，并更换 CPU 线程数后恢复。

[均匀流体示例](../examples/cpp/uniform_2d.cpp)对 CO2/water 执行完整三个阶段。
释放准备态后，结果评估仍有效。
[Quick Design 示例](../examples/cpp/quick_design.cpp)从原始工况和尺寸开始，调用
`prepare_quick_design`、`run_case`、`evaluate`，使用保留的 v1 契约。
[类型化 Quick 准备示例](../examples/cpp/prepare_quick_design.cpp)使用 `QuickDesignInputV2`，
只链接准备库，调用 `pressure_fractions` 和 `prepare_quick_design`。
它检查具有所有权的场及逆流缺省 qtol/chunk 控制量，不执行求解。
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
检查命令保留日志、二维对照字段和 Quick Design 对照字段，删除临时安装和外部构建目录。
这些原生路径不代表离散分区或三维已完成阶段迁移。
Python 接入及检查点恢复仍有各自的验收关口。

## Quick Design 阶段

`quick_design_stage_c_api.h` 保留 native-double v1 准备与运行契约。
独立的准备 v2 契约增加 `tpmshx_prepare_quick_design_v2` 和 `tpmshx_quick_pressure_fractions_v2`。
已公开的 v1 布局不变；`quick_design_prepare_v2.cpp` 负责两条新增数值顺序。
准备库复用几何、网格、物性和解析 D-F 实现。
求解库使用既有 Quick Design 驱动；结果库评价记录的场与最终阶段标量。

### 类型化原始准备与压降查询

v2 输入包含 13 个带类型标量：胞元长度、壁厚、宽度、长度、高度、导热率、容差、双侧质量流量、双侧温度和双侧压力。
胞元长度与壁厚使用 mm，外形尺寸使用 m，温度使用 K，压力使用 Pa(abs)，质量流量使用 kg/s。
文本字段具有显式字节长度。原生调用方填写全部标量槽；`have_height=0` 将高度槽替换为宽度。
无宿主钩子时，阶段不读取环境变量，使用固定 CFD D-F 表。
Python 宿主在原边界保留方法、chi、原始对象和快照协议。

叉流保留 `(60, 40, 1)`，逆流保留 `(60, 1, 2)`。
共享 `model_parameters_v1.json` 资源统一提供网格数、几何分辨率、导热率、容差及流向控制量。
Python 读取该资源，原生准备使用生成的常量。
Python 默认值仍为 16 W/(m K)、`1e-5` 和几何分辨率 128。
v2 通过 `have_q_relative_tolerance=0` 和 `have_chunk_iterations=0` 保留逆流 qtol/chunk 的缺省状态。
CaseData 将两者存为 `None`；执行时使用既有核默认值解析。
v1 继续返回已解析的驱动配置，逆流包含 `max(tol*10, 1e-4)` 和 chunk 250。

完整准备保留以下顺序：热启动检查、标签、正值输入、shape、几何／材料、网格和工况快照。
随后计算 A/B 入口物性、截面、A/B 压力状态和压降分数。
配置快照在压降之后；设计场、mm 到 m 换算及最终环境／模型快照随后执行。
此顺序保留每项警告、错误、转换与缓存观测的原执行点。

仅压降查询只使用几何／材料及入口压降顺序。
它跳过完整准备校验、热网格、设计场数组、配置快照和最终单位转换。
仅在该查询中，所有非 `cross` 流向均使用逆流截面。
完整准备入口仍检查其支持的流向及物性模式标签。
查询保留入口物性、液态水与解析压降检查，不执行热求解。

v2 描述符须初始化 ABI 2 及准确的 `struct_size`；完整结果须初始化 `owner=NULL`。
失败不修改结果存储。输入、输出与错误存储须互不重叠；错误缓冲区须可写且非空。
完整输出拥有网格宽度、边缘、复制的初始场和设计场，并包含带类型的压降分数与保存控制量。
数组使用 double 传输，精度标签供宿主复制时恢复原字段 dtype。
通过创建该输出的准备库调用 `tpmshx_quick_prepared_release_v2` 释放。
压降输出只按值保存分数及压力证据，没有 owner。
`stages.hpp` 提供 `QuickDesignInputV2`、`PreparedQuickDesignV2`、`prepare_quick_design` 和 `pressure_fractions`。
v2 输出没有新增 run 重载；Python 将它映射到 CaseData，交给现有运行适配器。

### 固定宿主操作

原生类型化输入可不提供 `tpmshx_quick_callbacks_v2`。
原生输入及观测使用 `raw_objects=0`；Python 原始对象协议使用 1，并且必须提供 host 回调。
C++ 选择每项操作及数值分支；宿主操作可打包原始操作数或执行指定对象操作。
它不得调用几何、物性、压降或求解器的数值实现。
已完成的几何缓存项通过独立回调交换。
请求与观测视图均为借用；打包输入缓冲区须保持有效直到下一次回调或原生调用结束，观测须在回调返回前复制。
回调返回非零值时，阶段以状态 20 停止；C 调用返回后，Python 抛出保存的原异常。
后续步骤失败时，已完成的警告与缓存观测仍保留。

下表省略 `TPMSHX_QUICK_` 前缀；`side` 为 0 时表示 A，为 1 时表示 B。
物性索引依次为 rho、mu、k、cp、Pr；标量槽顺序由各行说明。
标为观测的字段只读，其余所列字段传递宿主原始打包值或固定操作结果。

| 操作 | 宿主边界与请求字段 |
| --- | --- |
| `WARM_CHECK`、`LABEL_CHECK` | 检查原热启动对象与标签，不输出数值。 |
| `POSITIVE_SNAPSHOT`、`POSITIVE_CHECK` | 按原顺序读取一次输入；`index` 选择 13 项中的一项，`flags[0]` 返回有限正值检查结果。 |
| `SHAPE_CHECK` | 检查热启动场 shape；`flags[0]` 返回叉流选择，网格数由原生常量提供。 |
| `GEOMETRY_PACK` | `scalars[0:2]` 打包胞元长度／壁厚；`flags[0:3]` 传递拓扑、胞元精度和比例精度。 |
| `MATERIAL_PACK` | 观测 `geometry`；`scalars[0:2]` 打包导热率和 chi，`flags[0:3]` 传递拓扑／chi 存在标志／精度。`index=1` 选择 chi=1 的最终导热率。 |
| `WIDTH_PACK` | `index` 选择 x/y/z；`scalars[0]` 打包原始长度，`flags[0]` 传递数组精度。 |
| `OPERATING_SNAPSHOT` | 捕获原工况值及已解析 DF 选项，不输出数值。 |
| `PROPERTY_ENTRY` | 打开该侧范围作用域，在 `text` 返回已验证流体标签。 |
| `STATE_PACK`、`PROPERTY_PACK` | 在 `property_inputs` 打包广播后的操作数。`flags[0]` 标识流体，状态 `flags[1]` 选择标量 EOS 返回 shape；物性 `index` 选择 getter。 |
| `EOS_CACHE_LOOKUP` | `flags[0]` 标识 sCO2 或 CO2；`flags[1]` 返回命中状态，`property_values` 提供已完成的标量值或五值组合。阶段检查并复制该视图。 |
| `EOS_CACHE_STORE` | 在 `property_values` 观测已完成的标量结果，通过既有缓存 owner 发布；不得执行计算。 |
| `PROPERTY_RESULT` | 观测物性数组、kind、category 和浮点事件，恢复宿主标量／数组并送达 NumPy 事件。 |
| `PRANDTL_PACK` | 在 `property_inputs` 打包 mu、cp、k；`imaginary_inputs` 和 `categories` 保留原值协议。 |
| `SECTIONS_PACK` | `scalars[0:4]` 打包孔隙率、宽度、长度和高度；`flags[0]` 返回原叉流比较。 |
| `SECTIONS_RESULT` | 在 `scalars[0:4]` 观测 A 面积／长度和 B 面积／长度，保留原宿主长度对象。 |
| `PRESSURE_ENTRY` | 在原压降边界读取该侧原始入口值并复制 DF 选项。 |
| `FLOW_PACK`、`FLOW_RESULT` | `scalars[0:3]` 打包质量流量、面积、密度；`flags[0]` 返回原 air 比较。结果 `scalars[0:2]` 观测质量通量及速度。 |
| `PRESSURE_COMPARE` | `flags[0]` 返回独立的原 air 比较，用于选择压降分支。 |
| `PRESSURE_PACK` | `flags[0:3]` 传递 air、拓扑、strict。空气在 `scalars[0:5]` 打包质量通量／T／P／mu／长度，其余流体在 `scalars[0:4]` 打包速度／rho／mu／长度。胞元长度位于 `scalars[5]`，壁厚位于 `property_kind`。 |
| `PRESSURE_RESULT` | 观测 `pressure`，送达浮点事件和既有压降限制警告或错误。 |
| `FRACTION_PACK` | `scalars[0:2]` 打包已保留压降值与原入口压力，由 C++ 执行除法。 |
| `CONFIG_SNAPSHOT` | 在压降计算后执行原 `asdict` 转换。 |
| `UNIT_PACK`、`UNIT_RESULT` | `index` 选择胞元／壁厚；打包原始标量供原生除法使用。`flags[0]=1` 时在宿主保留自定义对象除法协议；标志为零时观测原生转换。 |
| `FINAL_SNAPSHOT` | 在原最终边界捕获环境和 ModelRef。 |
| `FAILURE` | 观测状态、文本、物性失败信息及 `flags[1]` 中的阶段；送达事件并映射原异常及原因链。 |

几何缓存回调以 action 0 查询、action 1 发布。
命中时提供已完成的几何值并设置 `hit=1`；未命中时设置 `hit=0`，由 C++ 计算。
Python 保留共享缓存键、命中／未命中行为及原存储值类型，不增加 Quick 专用缓存。
EOS 操作共享 `sco2_props._prop` 与 `co2_props._scalar`，保留原 4096 项上限及键。
sCO2 在状态校验前查找标量缓存，CO2 先校验；数组均绕过标量缓存。
只有成功的原生计算发布结果；外部物性调用和缓存清空使用同一 owner。
被替代的 `shared/models/quick_design.py` 已删除；冻结参考 `development/tests/quick_prepare_reference.py` 保留用于独立回归检查。
`preprocess/app_modes/quick_design.py` 只用复制的原生场和宿主快照组装 CaseData。

### 准备态执行与证据

保留的 v1 run 阶段复制传入准备场，不重复准备或修改原准备态。
const 物性执行一次热过程，mean 执行两次，第二次使用第一次返回的温度。
入口解析压降分数在两次过程中保持不变。
结果拥有全部 15 个场、物理网格宽度、压力证据、最终阶段标量和完整驱动过程记录。
取消返回状态 6 且不发布结果。驱动没有每次调用的 CPU 参数，继续应用既有进程线程控制。

Python 传递保存 CaseData 的借用视图，在释放原生结果前复制返回场和声明。
公开结果保留原网格、固定场 dtype、质量流量和入口温度。
Python 保留保存态校验、警告路由和异常映射；原生结果阶段负责 Quick Design 评估。
准备示例不能证明 N12 已完整交付；数值、打包、CI 和独立审查仍有各自关口。
Quick Design 保持定尺近似；数值收敛不建立物理验证、适用性或设计资格。

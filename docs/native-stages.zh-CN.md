# 原生阶段接口

[中文](native-stages.zh-CN.md) | [English](native-stages.md)

## 范围

原生阶段工作增加可独立调用的准备、执行和评估接口。Python 保留公共入口与原有数据契约。
对称均匀、规范连续 XY 和 air/air 空间几何二维准备使用原生阶段；非零 delta 与三维准备
使用各自明确保留的原路径。原生加载或执行错误不会选择其他路径。准备 v1 支持规定入口速度、CFD 阻力的均匀对称二维 air/air。
准备 v2 在相同几何和入口模式下支持 air、water、sCO2、CO2 的全部 16 个有序配对，
保留现有实验 DF 和 sCO2 Nu 选择、状态检查及适用限制，并分别保存两侧模型证据。
run 接口仍只接受 v1 的 air/air CFD 路径。
非零 delta、分区、连续场和规定质量流量仍不在这一准备 v2 范围内。
这些限制不删除现有 Python 工作流支持的任何模式。

准备 v3 在同一均匀对称二维流体矩阵内增加总质量流量输入，提供独立的入口容量查询、
入口流量解析和完整准备。物理深度、标定限制与标量算术规则保持不变。
连续场、分区和非零 delta 仍不在 v3 范围内，run 接口不变。

准备 v8 为原始 air/air 条带、矩形和 sigmoid 场增加容量查询、流量解析与完整准备。
它保留 CFD 阻力、零 delta，以及独立的域长和端口类型输入。
准备 v9 通过带类型的缓存钩子，将这些对称空间几何 Python 路由连接到原生阶段。

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
这些准备接口不改变 run 接口，也不认证梯度几何的准确度。

## 离散分区

准备 v5 通过 `ZonedInput2D` 接收原始条带和矩形。
它接受 air/air、规定入口速度、CFD 阻力与零 delta。
配置或显式总质量流量、实验阻力和 sigmoid 控制不属于该接口。
Python 生产路径与运行接口不变。非零 delta 均匀准备也仍未迁入原生阶段接口。

每个区域提供边界、名称、L/t 和标量类型。
条带沿 x 或 y 使用前两个边界，保留稳定排序。
矩形使用 x0/x1/y0/y1，保留输入顺序、重叠与局部覆盖。
赋值保留首次命中和各布局原有的空隙规则。
阶段先采样请求网格，再采样最终物理网格。
行 D-F 先按横向真实物理宽度投影原始 L/t，再预测阻力。
这一顺序与连续场的局部系数路径不同。

设计孔隙率、固体导热率、两侧流体导热率和两侧体积换热系数保留原有高斯平滑。
L/t、面积密度、水力半径与区域 ID 不平滑。
单独的热几何孔隙率、面积密度和直径由原始 float64 L/t 场得到。
结果拥有复制的区域描述、逐区物性、物理场、行阻力、端口和有序证据。
仅外层结果拥有 owner，必须用匹配的 v5 函数释放。

每次原始调用从空的有界几何和入口物性缓存开始。
相等键保留第一次成功值的标量类型和已完成范围记录。
材料导热率每次使用当前 chi 和固体导热率。
此接口只接受 v1 事件回调，不使用 Python 共享缓存及其 host hooks。
原 Python 路径与全部 v1-v4 范围保持可用。

## Sigmoid 场

准备 v6 接收既有 air/air 网格 sigmoid 控制、规定速度、CFD 阻力和零 delta。
输入包含至少 36 个交错排列的 L/t 值（mm），以及保留标量类型的入口和出口过渡量。
阶段使用前 36 个值，先采样请求网格，再采样最终物理网格。
它保留原有有序混合、裁剪、外推提示和行 D-F 投影。
Sigmoid 场不使用离散分区的高斯平滑。
设计几何来自 LUT；独立热几何来自原始 L/t 场。
总质量流量、实验阻力和非零 delta 仍不属于 v6 范围。
下述 v9 适配器提供 Python 路由与缓存策略。

`build_sigmoid_lut` 在现有训练范围内创建具有独立所有权的原生查找表。
默认使用 41 个胞元长度节点、31 个壁厚节点和 256 体素分辨率。
它调用 raw 几何，保留原始退化节点，不使用 Python 或磁盘读写。
调用方可复用该资源，也可提供规范化轴和已捕获的表值。
两个表各自保留插值标志；原位引入的 NaN 保留原查询行为。
完整准备结果拥有复制的控制量、场和证据，嵌套视图的 owner 为空。
LUT 和准备结果须分别用对应的 v6 函数释放。
释放 LUT 不影响已经生成的准备结果。
只接收事件的 v1 回调与此前 ABI 布局保持不变。

## 保留类型的域长和端口

准备 v7 增加 `GridKinds2D`，描述既有域长及每侧四个端口值的标量类型。
网格、开口、入口容量和空间采样保留 NumPy 整数及 float16/32/64 的运算规则。
C++ 调用将描述符作为第二个参数，将准备选项作为第三个参数。
[类型网格示例](../examples/cpp/prepare_typed_grid_2d.cpp)检查固定质量流量下的整数与 float16 混合端口。
C 入口将相同描述符与既有 v3-v6 输入及输出布局配对使用。
若再次准备已解析输入，须同时保留描述符；结果仍用原对应函数释放。
此前的 C 和 C++ 入口继续将域长及端口值作为弱类型 double。
该接口不改变物理范围或保存文件格式。

## 空间几何总质量流量

准备 v8 将 `ZonedFlowInput2D` 或 `SigmoidFlowInput2D` 与 `GridKinds2D`、准备选项一起使用。
每种输入包含既有原始空间描述符、深度和目标类型，以及可选的显式双侧目标。
六个 C 入口分别为两种空间输入提供容量查询、流量解析和完整准备。
它们接受 air/air、CFD 阻力和零 delta；既有 v1-v7 布局与范围保持不变。

容量使用实际物理入口处的设计孔隙率切片、开口剖面、宽度、密度和物理深度。
离散设计孔隙率保留高斯平滑；sigmoid 几何不使用高斯滤波。
查询不会用过时入口速度计算 Nu 或换热系数。
流量解析按既有标量算术处理配置中的单侧或双侧目标，或显式双侧目标。
显式目标清除已存目标；无目标时，解析仅复制原始输入，不执行物理准备。

完整固定流量准备只构建一次物理网格，并保留其几何直至速度解析完成。
最终物性使用解析后的速度；请求网格观测、每次调用的缓存顺序及行 D-F 投影保留原顺序。
前段记录位于 `flow.flow.evidence`，最终记录仍位于准备结果视图。
这些原始操作只接受事件回调，不使用 Python 缓存钩子。

容量和解析结果的 `input` 视图拥有复制后的区域名称、控制点与 LUT 数组。
再次使用解析输入时，须保留匹配的网格描述符与标量类型。
嵌套 owner 为空，只用对应的 v8 释放函数释放外层结果。
[空间流量示例](../examples/cpp/prepare_spatial_flow_2d.cpp)使用全部六个操作，并在完整准备前释放原始输入。
它用小型 LUT 检查所有权与保留类型的端口，不构成 LUT 物理精度验收。

## 空间几何宿主缓存接口

准备 v9 在 v8 输入外增加 `ZonedFlowInput2Dv9` 和 `SigmoidFlowInput2Dv9`。
`model` 成员携带空间导热系数类型、几何外推标志和默认 LUT 标志。
公共配置要求名义与空间拓扑、导热系数数值一致。
相等的导热系数数值可以具有不同标量类型，v9 保留空间类型。
可选的默认 LUT 查询在各路径原有几何检查点执行。
规定速度准备先执行预检查，再查询 LUT；容量在速度解析前只使用几何。
Python 负责内存、磁盘查询与发布；未命中时按既有 41x31 节点和 256 体素分辨率构建原生表。

`tpmshx_preparation_case_callbacks_v9` 通过 `values.values.values` 声明版本 9 和完整描述符大小。
此前的几何与入口缓存槽置空，使用 `geometry_cache_at` 与 `inlet_cache_at` 交换带类型的缓存项。
几何探针携带实际拓扑、L/t 与标量类型；入口探针另含流体、u/T/P、对应类型和模型选择。
未提供 Nu 选择与名义默认选择保持区别。
宿主负责键、查询、LRU 顺序和发布；未命中时全部物理数值由原生实现计算。
键仅在回调期间有效；查询返回的缓存数组必须保持有效直到阶段返回。
发布数组为只读，必须在回调返回前复制。
原观测与校验钩子保留执行时序和失败行为。
空间操作在区域准备前增加 stage 为 4、side 为 2 的宿主检查点，保留缺失宿主配置在先前检查之后报错的顺序。
通知 kind 为 2 时逐条传递几何外推原因，与 Nu 警告记录分开，并保留各侧的原始顺序。

全部六个 v9 操作只返回一个外层 owner，嵌套 owner 为空。
完整结果还通过 `design_pore_porosity` 提供 Python CaseData 对应字段。
使用匹配的 v9 释放函数；此前 C 布局与 v8 操作不变。
[空间缓存示例](../examples/cpp/prepare_spatial_cache_2d.cpp)在 Python 外调用全部六个入口和带类型的回调。
它通过缓存钩子提供小型 LUT，并在原 owner 释放后复用复制后的 LUT。
这属于接口证据，不构成小型表的物理资格验证。

## Python 准备适配

公共均匀和规范连续二维入口使用 v7 及 v3/v4 载荷。
对称 air/air 条带、矩形和 sigmoid 场的准备、容量查询与流量解析使用 v9。
仅容量查询保留配置校验，不计算阻力；完整空间准备仍要求 CFD 阻力。
`preprocess/native_preparation.py` 传输共享缓存值与证据，不调用缓存函数的数值主体。
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
公共 ZoneConfig 与 sigmoid 场查询仍服务于独立调用和非零 delta 准备。
其剩余组合计算须单独迁移并验收后才能退役。

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
[分区准备示例](../examples/cpp/prepare_zoned_2d.cpp)从原始条带边界和逐区 L/t 开始，通过 v5 提供准备场和行阻力，且只链接准备库。
[Sigmoid 准备示例](../examples/cpp/prepare_sigmoid_2d.cpp)创建生产分辨率 LUT，并从原始控制量准备两个工况。
它复用 LUT，且只链接准备库。
[空间流量示例](../examples/cpp/prepare_spatial_flow_2d.cpp)通过 v8 查询、解析并准备分区和 sigmoid 场。
[空间缓存示例](../examples/cpp/prepare_spatial_cache_2d.cpp)增加 v9 带类型的缓存及 LUT 回调。
它同样只链接准备库，并保留行阻力与独立热几何。
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
这条基础运行路径不代表固定质量流量、其他流体、分区、三维或 Quick Design 已完成阶段迁移。
Python 接入及检查点恢复仍有各自的验收关口。

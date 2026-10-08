# 仓库目录与文档导航

[中文](README.md) | [English](README.en.md)

**主体程序位于 [sjtu_tpmshx/](../sjtu_tpmshx/)**。
读代码从[模块地图](../sjtu_tpmshx/README.md)开始，运行程序从
[首次运行说明](../README.md#first-run)开始。

## 当前文档

| 内容 | 入口 |
| --- | --- |
| 模块职责、调用关系和物理约束 | [architecture.zh-CN.md](architecture.zh-CN.md) |
| 完整 Python/C++ 后端、原生 ABI 与构建 | [C++ 接入说明](cpp-migration.zh-CN.md) |
| macOS/Windows 项目文件夹运行与可选打包 | [桌面运行说明](desktop.md) |
| CaseData、FieldResult、指标与文件交接 | [三模块数据契约](../schemas/three_module_v1/README.zh-CN.md) |
| 已交付能力、M-B 未完成事项与阻塞条件 | [能力范围](capabilities.md) |
| 离线清洗、sCO2 有效 Nu 与上海空气阻力标定来源 | [模型资源](model-resources.md) |
| 数据文件名、已结案缺项与水 Nu 选择 | [数据目录](data-catalog.md) |
| 工程、验证、研究与性能工具的输入输出 | [工具入口](tools.md) |
| 数值/实验验证工具与方向系数研究边界 | [验证导航](../sjtu_tpmshx/validation/README.md) |
| GUI、孔隙率与 CI 的现行行为要求 | [OpenSpec 规范](../openspec/specs/) |
| 历史报告、任务图、旧基准与退役工具 | [固定历史索引](history/README.md) |

## 根目录各自放什么

| 目录 | 用途 |
| --- | --- |
| [sjtu_tpmshx/](../sjtu_tpmshx/) | 主体源码、应用层、共享模型、有效测试和验证工具 |
| [docs/](./) | 当前说明与历史资料入口 |
| [examples/](../examples/) | 公开调用示例和首次运行配置 |
| [scripts/](../scripts/) | 测试、原生依赖构建和模型系数生成脚本 |
| [sjtu_tpmshx/runs/](../sjtu_tpmshx/runs/) | 现行性能剖析、诊断和演示工具 |
| [schemas/](../schemas/) | 三模块数据契约；实现位于主体包的 domain/、io/ 等模块 |
| [openspec/](../openspec/) | 按功能分开的现行行为规范 |
| [.github/](../.github/) | macOS / Windows CI 和最小后处理环境检查 |

`pyproject.toml`、`requirements*.txt`、`pytest.ini` 负责构建、依赖和测试；
`mypy-core-files.txt` 声明公共接口与数据契约的显式类型检查范围，执行方式见
[环境与检查](../README.md#环境与检查)。
`AGENTS.md` 记录项目协作规则，`LICENSE` 记录许可，`data-revision.txt` 声明配套数据版本。
原始实验/CFD 数据位于本地 `data/raw_data/`，研究脚本与结果放在忽略的 `.cache/`，
均不随公共代码仓库提交。旧 `reports/` 输出目录也被忽略，避免旧命令重新提交结果表。

一维焓方程参考模型由有效测试直接使用，现放在
[tests/enthalpy_1d_reference.py](../sjtu_tpmshx/tests/enthalpy_1d_reference.py)。
生产 CFD 系数 CSV 和测试读取的 MMS 数据继续保留；历史 `golden_3d.json`、旧 γ 快照、
阶段报告与任务过程文件从固定 Git 历史查阅，不再作为当前测试资源或当前精度说明。

M-A 三模块主线完成不代表 M-B 扩展功能完成，也不代表实验精度已通过。
原 B40 失败、冻结参考和历史结论按原状态保留。

## 双语文档与术语

当前使用说明、架构、接口和现行规范提供中英文版本。原路径保留其主语言，
另一版本使用 `.en.md` 或 `.zh-CN.md`，页首提供语言切换。
历史正文、代理指令和许可证原文保留；历史索引及当前用途说明提供双语。

英文按 [ASD-STE100 Issue 9](https://www.asd-ste100.org/about_STE.html)的受控英语规则编写。
操作步骤每句表达一个动作，操作句不超过 20 词，描述句不超过 25 词。
代码、字段、模型名称和下列技术名词保持固定写法。中文使用相同结构和技术含义。
句长检查辅助人工词义与技术审读，不代表独立的 STE 合规认证。

| 英文技术名词 | 中文 | 本项目含义 |
| --- | --- | --- |
| solver backend | 求解后端 | 通过 RunControl 选择的 Python 或 C++ 数值实现 |
| prepared case | 准备态工况 | 前处理生成的 CaseData，包含实际网格及固定物理输入 |
| native evidence | 原生证据 | 求解时记录的场、通量、压力与状态 |
| ABI | 二进制接口 | C 结构布局、符号、版本及内存所有权约定 |
| metric | 指标 | 带单位、定义版本和可用状态的派生量 |
| completed | 执行完成 | 执行返回完成状态，不自动表示收敛 |
| converged | 已收敛 | 对应路线的数值与物理门槛通过 |
| available | 可用 | 已记录证据足以计算所请求指标，不代表求解已收敛 |
| engineering parity | 工程一致性 | 相同输入和预算下满足既定工程误差与独立物理门槛 |
| numerical verification | 数值验证 | 数值公式、离散、求解与守恒检查 |
| experimental validation | 实验验证 | 在声明适用范围内与实验观测比较 |
| qualification | 资格检查 | 对明确能力、平台和版本完成规定验收 |
| replay | 重放 | 从保存的准备态执行，或从保存的结果独立后处理 |

词汇审读依据[官方 Issue 9 词典](https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf)的词义和词性。
例如，`check` 用作名词，动作用 `do a check` 表达；一般意义的 `retain` 和 `preserve` 使用 `keep`。
强制要求使用 `must`。引用的界面标签和代码标识保持原文。

以下技术词保留其数学、物理或软件含义，不能用作已批准一般词汇的任意替代。

| 领域与词性 | 技术词 | 含义边界 |
| --- | --- | --- |
| 数值与物理名词 | residual, accuracy, convergence, conservation, enthalpy, porosity, interpolation, boundary flux, pressure reference, finite-volume row | 架构和模型文档定义的量与方法；accuracy 不表示重复性 |
| 软件名词 | case, field, state, backend, ABI, callback, archive, metadata, cache, build, worker, trace, result owner | 公共契约及当前实现定义的对象和过程 |
| 证据名词 | original budget, native evidence, engineering parity, acceptance gate, qualification, experimental validation | 明确版本和范围下记录的参考、限制与证据 |
| 数值动词 | solve, converge, discretize, interpolate, integrate, normalize, extrapolate, refine, fit, calibrate, clip, relax | 对应的数值操作，不表示物理结果已通过验收 |
| 软件动词 | build, compile, run, load, parse, serialize, deserialize, validate, allocate, release, cache, replay, export, import | 对应计算机过程；例如 build 生成二进制，不表示数值资格已通过 |

字段名和代码字面值不翻译。一次修改同步核对两种语言的默认值、单位、限制、
命令和当前证据；旧链接入口及被引用锚点继续保留。

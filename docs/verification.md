# 本地检查、CI 与验收记录

[中文](verification.md) · [English](verification.en.md) · [返回首页](../README.md)

## 本地环境和检查命令

本地项目执行使用 `.venv-path` 第一行的绝对解释器。任务环境缺失或检查失败时，
先停止依赖该环境的工作，再按[环境恢复流程](collaboration.zh-CN.md#环境恢复)
自主恢复。修改前说明影响并保留恢复方式，通过检查后再切换指针和继续工作。
恢复使用当前适用锁；依赖版本变更须同时更新依赖声明和精确锁。
共享 venv 只安装锁定依赖，不把当前项目 editable 安装进去，不修改使用中的环境。
命令从当前仓库根运行。

```bash
PYTHON="$(head -n 1 .venv-path)"
"$PYTHON" -m sjtu_tpmshx.development.runs.tools.check_locked_environment
"$PYTHON" -m pip check
export MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg"
export QT_QPA_PLATFORM=offscreen PYTHONHASHSEED=0
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
"$PYTHON" -m engineering.scripts.check_types
"$PYTHON" -m pytest tests/python -q -ra -m "not slow and not heavy" --ignore=tests/python/integration_tm1 -n 2 --dist worksteal --timeout=600 --timeout-method=thread --durations=30 --junitxml=.cache/ci/fast.xml
"$PYTHON" -m pytest tests/python/integration_tm1 -q -ra --timeout=600 --timeout-method=thread --durations=30 --junitxml=.cache/ci/integration.xml
# 完整本地验收：没有 -m 过滤；按本机 CPU/内存可将 auto 换为固定 worker 数。
"$PYTHON" -m pytest tests/python -q -n auto --dist loadscope --timeout=600 --timeout-method=thread
```

PowerShell 使用同样的 pytest 参数，以 `$env:变量名=值` 设置上述环境变量，
并以 `& $tm1Python` 调用解释器。测试前必须提供匹配的原生库。
macOS 和 Windows 的 Python 3.13 快测按完整模块分到两个独立 runner，每片固定两个 worker。
`fast-0` 使用 `load --maxschedchunk=1`，减少长耗时尺寸设计测试后方排队的工作；`fast-1` 使用 `worksteal`。
每个 worker 的 BLAS/OMP 单线程。Windows 集成测试在本平台构建后与快测并行。
macOS 在 `fast-0` 中单独运行集成进程，共用 runner。两平台的集成报告独立保存。
Windows/Python 3.12 跑完整集成和 [兼容性用例](../tests/python/_ci_windows_312.txt)，包括实际渲染和二维、三维续算。
<a id="qt-rendering"></a>

CI 在独立 Qt 进程中渲染真实 3D 体场，检查字段切换、PNG 解码、缩放图像、应用导出及关闭。
macOS 使用 Cocoa；Windows 使用固定版本的 Mesa OpenGL 软件渲染。
macOS arm64 托管机若检测到 `Apple Software Renderer`，该像素检查明确跳过。
[PyVistaQt 记录了此环境的渲染限制](https://github.com/pyvista/pyvistaqt/blob/v0.13.1/pyvistaqt/rwi.py)。
实体 Mac 的完整像素检查仍是图形依赖变更的本地验收项。
包含此测试的 artifact 保留 OpenGL 信息、进程日志，以及成功生成的 PNG 和渲染报告。
实体 Windows 显示器的桌面验收仍单独记录。

现有测试辅助脚本继续保留；`run_tests_fast.ps1` 只提供开发反馈，
其 `not heavy` 子集与 CI 快测不同。两份 PowerShell 脚本默认严格检查基础锁。
已有 Windows BO 环境时，显式使用
`./engineering/scripts/run_tests_server.ps1 -LockFile engineering/requirements/bo-windows.txt`，或向
`run_tests_fast.ps1` 传同一参数；所选锁与 `pip check` 都通过后才启动测试。
脚本不安装依赖，也不因为选择了服务器锁而放行锁外包。

当前 macOS CI 使用 `macos-15` arm64 镜像。GitHub 已于 2026-11-02 [退役 macOS 14 镜像](https://github.com/actions/runner-images/issues/13518)。受保护的汇总检查保留名称 `tests (macos-14, 3.13)`；它仍要求当前 macOS 作业及原有全部检查通过。分支保护规则和必需检查集合保持不变。

GitHub workflow 使用 checkout v7、setup-python v7、upload-artifact v7，
分片门使用 download-artifact v8。这些 Action 的运行时不改变求解器的 Python 环境；
`ci` 内的 `minimal-postprocess` 验证完整环境到最小后处理环境的真实文件交接。
`ci` 的基础和独立 BO 运行均覆盖 macOS / Python 3.13，以及 Windows / Python
3.12、3.13。`bo-tests` 作业在 Windows 的全部运行层级和 macOS 的 `application` 层级运行。
macOS `full` 层级由 `fast-0` 测试片先在独立环境中运行 BO；该步骤在恢复求解库之前执行，BO 环境变量只在该步骤内设置。
因此 macOS `full` 层级在构建后启动五个作业：三个原生分片和两个测试片。BO 运行分别安装对应平台的 BO 锁，严格检查环境后
显式导入 Torch / BoTorch / GPyTorch，并运行多工况优化器测试（含两种真实 Log
采集函数）。基础作业仍使用不含 BO 的锁，覆盖可选依赖缺失时的行为。
BO 作业上传 JUnit 与完整收集 manifest，保留 7 天，不上传求解数据或虚拟环境。

## CI 检查范围与分片

PR 和 main 推送按 [明确的路径清单](../engineering/scripts/ci_scope.py) 选择检查层级：

- `docs`：仅根目录 README、AGENTS 和 `docs/` 下的非契约 Markdown。检查本地链接、锚点和具体项目模块命令。
- `application`：仅用于 PR，覆盖指定界面显示、布局模块、图标及对应测试，可包含文档。保留两平台构建、应用、集成、BO 与真实文件后处理检查。
- `full`：求解器、模型、公共接口、依赖、工作流和所有未列出的路径。运行完整矩阵。

main 推送中仅纯文档变更使用 `docs`，手动触发始终使用 `full`。重命名同时检查旧、新路径，未知或空的变更集合使用完整矩阵。
完整矩阵有 27 个作业，包含独立 Linux 结果库构建。较轻层级不能作为完整 CI 耗时或数值研究验收。
物理变更仍须完成其要求的扩展数值研究；常规 CI 不替代该证据。

`pyproject.toml` 的 `[tool.mypy].files` 显式列出 19 个类型检查文件：覆盖配置、控制器、CLI、统一工作流、当前
envelope 实现、三模块数据契约与公共 API、后处理指标入口；已删除的转发模块不再列入。
`pyproject.toml` 还对四个边界实现模块启用无注解函数体检查；这不等于全求解器严格类型覆盖。
`test_type_gate.py` 在 pytest 快测中执行同一清单。上面的 mypy 命令用于本地单独检查。

第一条 pytest 排除了 slow/heavy 和 `integration_tm1`，第二条单独完整执行该集成目录，
避免重复执行其中的快测成员；两者不能代替第三条完整本地验收。
本地上述命令仍执行未分片的完整子集。CI 中的原生资格测试只在原生组执行，
共同模块清单为 `tests/python/native/_ci_suite.txt`。完整 CI 中，Python 3.13
再加入 `tests/python/native/_ci_stage_suite.txt` 的阶段用例，包括其中的长测。
原生 pytest 使用 `@<清单路径>` 读取这些清单。
应用快测仍记录原完整收集集合，再通过 `--ci-covered-modules=<清单路径>` 移交这些模块。
清单外的新模块自动保留在应用快测中，不会按目录整体排除。
复现应用分片时，在第一条 pytest 命令追加
`-p tests.python.ci_shard --ci-shard=0 --ci-manifest=.cache/ci/fast-0
--ci-covered-modules=tests/python/native/_ci_suite.txt`。
复现完整 CI 的 Python 3.13 分片时，再传入
`--ci-covered-modules=tests/python/native/_ci_stage_suite.txt`。
另一片改为 `--ci-shard=1` 并使用独立 manifest 目录。
分片 0 的模块列在 `tests/python/_ci_shard0.txt`，其余应用模块自动进入分片 1。
移交和分片在原 heavy 标记及 pytest 过滤之后执行。

汇总门先验证原生分片完整、互斥且成功，再与应用分片合并核对原完整快测集合。
跨组重复、漏测、缺失 worker 或失败记录均阻止通过。下载相同平台/Python 的全部 manifest 后运行：

```bash
"$PYTHON" engineering/scripts/check_ci_shards.py .cache/ci/fast-0 .cache/ci/fast-1 --covered-by .cache/ci/native-*/native-manifest
```

原生分片必须按编号顺序传入。若本地不使用 `--ci-covered-modules`，仍可单独核对两个完整快测分片。

Python 3.13 原生资格检查在 macOS 分为三片，在 Windows 分为六片。
每片使用两个 worker 和 `loadscope`，将同一模块或类保留在同一 worker。
分组依据完整矩阵的实测用例耗时。保守能量测试按共享 fixture 参数分组，
同组的收敛、物性、能量账本和真实回放检查保持在同片。其他模块保留共享 fixture；
独立工程用例与二维检查点用例可按完整 node ID 分组。
分组清单位于 `tests/python/native/`：macOS 使用 `_ci_macos_shard0.txt` 至 `_ci_macos_shard1.txt`，
Windows 使用 `_ci_windows_shard0.txt` 至 `_ci_windows_shard4.txt`。
按编号顺序将每份清单通过 `--ci-shard-modules=<清单路径>` 重复传入。
未列出的用例自动进入最后一片，即 macOS 分片 2 或 Windows 分片 5。
按编号向同一集合校验器传入全部 manifest，核对其完整且互斥；每片必须有 `gw0`、`gw1` 两份记录。
`--serial` 仅用于本地串行测试的 `controller` 记录。
原生工程用例保留逐侧物理模型、收敛及能量门槛。二维适配对照用有限迭代比较字段、指标和回调。
原生组设置 `TPMSHX_REQUIRE_NATIVE_DEPS_TESTS=1`，缺少所需原生库或调用程序时失败。
测试桥接库复用同一次 CMake 构建的数值目标。线程并发、进程恢复和结果所有权测试仍由原生组执行。
Python 数值对照迁移为独立公式／离散账本、制造解、组件重放及固定历史参考；
不保留已退役迭代器作为第二套求解实现。

每个平台调用 [原生工作流](../.github/workflows/native.yml)，用 Python 3.13 构建一次原生库并运行独立 C/C++ 调用程序。
application 和 full tier 均构建完整 pilot。归档包含求解库、几何库、准备库、结果库和 SDK 对照样本。
结果库通过独立 `build --component result` 构建，再与其余库一起执行完整验证。
完整 SDK 检查编译全部 C++ 示例，执行有代表性的前处理、求解、续算和后处理路径。
Linux 最小后处理在 macOS 的结果和 wheel 及 Linux 结果库就绪后启动，与 Windows 资格检查并行。
BO 恢复本轮同平台归档中的几何库、准备库和结果库，不恢复求解库，与该平台的其他回归并行。
原生库不链接 Python 运行时。Windows 两个 Python 版本测试同一构建。
分片在本平台构建完成后启动，不等待其他平台。原生、快测和集成测试共同使用本轮工作流及源码产生的
`native-build-<平台>` artifact。归档保留可执行权限，包含运行库、调用程序和许可声明。
CoolProp 精确缓存键绑定平台、架构、Python 3.13、托管工具链镜像版本、原生依赖锁中的 CoolProp 输入和 `engineering/scripts/build_coolprop.py`。
`build_coolprop.py cache-key --host <主机>` 输出 CMake 版本与生成器、CoolProp 锁定版本与主机选项、CPM 依赖锁定版本及其补丁文件的 SHA-256；SuperLU 和 AMGCL 变更不使缓存失效。
项目 C++ 和模型系数每轮重新构建；缓存命中仍须完成独立调用验证。
构建日志单独保存在 `native-build-logs-<平台>`。
每片上传 `native-dependencies-<平台>-py<版本>-shard-<编号>`，macOS 编号为 0–2，Windows 为 0–5，
包含 JUnit 和 `native-manifest`。以上 artifact 均保留 7 天。
原生日志保留最慢 20 项和 skip 原因。

快测和集成日志保留最慢 30 项和 skip 原因。各测试组将 JUnit 与 collection manifest 分别保存为
`test-reports-<平台>-py<版本>-<fast-0|fast-1|integration>` artifact，保留 7 天。
manifest 附带各 pytest 进程的独立 RSS 峰值；
进程峰值不能相加当作同期总峰值，统计不覆盖普通子进程。
三个原名 `tests (<平台>, <版本>)` 必需检查核对所选层级的预期作业名称及结果。
`docs` 只允许明确跳过运行时作业；文档检查必须成功。其他层级要求构建、应用、集成、BO 和后处理成功。
`full` 必须通过完整原生覆盖；`application` 只允许省略原生模块清单中的精确路径，其他遗漏均失败。
各平台/Python 汇总还要求对应 BO 和集成报告、成功收集记录及完整测试计数。
Windows/Python 3.12 汇总以这两份报告检查兼容性。
BO 不允许跳过测试；集成允许已记录的单项跳过，但全跳过必须失败。
未预期的失败、取消、跳过、缺失报告或覆盖缺口均不能放行。
`minimal-postprocess` 继续作为独立必需检查；在 `docs` 层级只核对预期作业结果。
比较速度时区分快测、集成和整个 job，并使用相同平台的基准，不据本地耗时承诺 CI 提速。
完整验收的 skip 须保留具体原因，不能当作被跳过能力已经通过。最小后处理 CI 使用独立的
`engineering/requirements/postprocess.txt` 环境，并消费另一完整环境生成的真实 2D/3D
结果文件。独立 `result-build` 矩阵在 Ubuntu 24.04 和 26.04 上运行。
每个作业只获取锁定 CMake，随后构建结果库、验证 SDK 并运行独立数值参考。
两项构建均须通过，Ubuntu 24.04 的 `minimal-postprocess` 才能执行文件检查。
该作业使用 `result-build-linux-x86_64-ubuntu-24.04`；Ubuntu 26.04 产物单独保留。
macOS 集成步骤同时将公开算例的两个结果及指标通过 `real-file-handoff`
传给该 Linux 最小环境。两类交接保留 7 天，不包含私有数据。
最小作业使用预构建结果库读取并评估真实文件，覆盖源码和已安装的 wheel。
配置不等于实际 CI 通过。

## 协作与合并

Codex 与 Claude 共用 [AGENTS.md](../AGENTS.md) 中的项目规则。任务归属、独立工作树、
环境选择、同步与交接使用[协作流程](collaboration.zh-CN.md)。

公开契约的修改需要检查下游消费者：前处理的配置/单位/网格由求解侧复核；求解的
原生场/边界证据/状态由后处理侧复核；指标定义及文件关联由应用/文件消费者复核。
GUI 和调度留在 `applications/gui/ui/`、`applications/gui/controllers/`，模型资源保持共享。每个 PR 写明受影响的
接口、验证证据和参与复核者。当前仓库维护者为 `alexlu997`；师兄加入后再分配具名
模块责任人，当前不建立虚构的 CODEOWNERS 或把模型自查写成人工独立批准。

2026-09-13 已回读核验 main 保护：通过 PR 更新，要求分支与 main 同步，并通过
`tests (macos-14, 3.13)`、`tests (windows-2022, 3.12)`、`minimal-postprocess`
三项 GitHub Actions 检查；管理员同样受约束，禁止强推和删除。多人正式参与后
再启用至少一位非作者批准；目前平台所需批准人数为 0。实际状态以 GitHub 为准。

Windows 同时支持 Python 3.12 和 3.13：main 保护保留上述三项，并新增
`tests (windows-2022, 3.13)`，共四项必需检查；其他保护保持不变。
工作流更新不会自动修改 GitHub 保护设置，合并前须核实必需检查已同步。

现行能力与待完成事项见[能力范围](capabilities.md)，
测量工具和复现边界见[工具说明](tools.md)。

## 数据与历史证据

原始实验/CFD 数据位于本地 `data/raw_data/`，不提交。匹配版本见
[data-revision.txt](../data-revision.txt)。清洗、拟合和本地输出规则见
[离线模型说明](model-resources.md)。
目录按实验、CFD 结果和工况计划分类；Excel 的新旧名称、用途及读取约束见
[数据目录与文件名对照](data-catalog.md)。移动数据时须同步加载器和压力口径识别。

优化研究脚本、逐工况结果和探索报告保留在忽略的 `.cache/` 中，不提交或上传到
代码仓库；长期需要的研究证据应另外做私有归档，不能把 Git 忽略规则当作备份。
本地虚拟环境和 `.venv-path` 同样不提交，由版本化的依赖声明与锁文件重建。
生产优化模块、回归测试、CI 工作流、锁文件及使用/架构文档随代码提交。

旧 γ/RBF、SmoothDF、水发展段及旧 sCO2 阻力模型已退役，代码和结果见
[固定历史索引](history/legacy-models.md)。当前联合 K/cF、原水 Nu 和 D-F
实验修正继续使用；sCO₂ Nu 的旧锚定 γ 及专属报告工具已由
[现行有效系数](model-resources.md#sco2-有效-nu-系数)替代。历史实验误差不改写。
当前水 CFD 工作簿缺失时不以旧版文件替代。

原 README 的历史精度与物理说明原样保存在
[V2 README 存档](https://github.com/alexlu997/SJTU-TPMSHX-TM1/blob/b1af7edcea5796aa955aa8fae1785be3c1b57e1d/docs/history/v2-readme.md)，旧图片链接固定到历史提交。
已移出当前文件树的图片、优化输出、探索记录与 Atlas 快照见
[历史资料索引](history/README.md)。
这些数字不是 TM1 或当前默认 CFD 模式的新验收。B40 原锁定测试 4/4 失败、
3D 筛选未收敛及其他原生失败证据继续保留；不改阈值或物理范围迎合结果。

### 版本与验证范围

TM1 在 [alexlu997/SJTU-TPMSHX-TM1](https://github.com/alexlu997/SJTU-TPMSHX-TM1) 独立维护，原 SJTU-TPMSHX/V2 仓库用于来源追溯。

[v0.1.0](https://github.com/alexlu997/SJTU-TPMSHX-TM1/releases/tag/v0.1.0) 是首个 GitHub 源码发布版本，保留 Python 与 C++ 双后端。
0.1 发布包保留两套求解器源码。0.2 删除 Python 数值迭代器及其专用研究入口，
并删除外层物性 Anderson；固定物性松弛、热方程与流动加速保持原有规则。
既有守恒 EOS 能量路线默认使用 T-SOU（`temperature_sou`）。H-FOU 和 T-FOU 执行已退役；model-h 及其他温度路线保留原物理约定。历史结果仍可读取，历史检查点须使用匹配的归档运行库。运行前须构建与源码匹配的本机原生库。

矩形 2D/3D 三模块主线的 M-A 合并验收已记录；M-B 扩展能力继续单独追踪。
历史 B40 失败与物理适用范围仍须保留。当前结论见
[能力范围与未完成事项](capabilities.md)；
原计划、接管过程与各节点证据从[固定历史索引](history/README.md)查阅。

2026-10-05 的候选验收保留以下边界：Ceff43 为 19/43 通过、24/43 超时，
固定总体未通过；fixed230 执行和索引为 230/230，用时 93 分 18.5 秒，
保存态独立检查为 229/230 通过，首行因审计工具错误未评估且未重试。
这些局部检查不构成完整原生配置、迭代历史、F2 或实验准确度资格。
当时源码 GUI 已有两维显示和导出证据，取消、重算、菜单配置保存重载、重启恢复及
外循环次数显示仍待解锁 Mac 后进行可见复核。这段记录描述 2026-10-05 的状态，
不代表后续版本的桌面验收结论。
合入 PR #136 的 `298761d2` 基线已通过 macOS/Windows 原生 CI，见
[CI 记录](https://github.com/alexlu997/SJTU-TPMSHX-TM1/actions/runs/37713153292)。
早期数值比较失败仍属于其原版本记录。工程对照、严格局部回归、实验精度、
完整性能和可见桌面验收分别保留各自门槛。
文件夹可启动与限定回归通过不代表完整原生资格通过。

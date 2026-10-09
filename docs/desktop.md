<a id="桌面软件构建与验证"></a>

# 桌面运行与可选打包

[中文](desktop.md) | [English](desktop.en.md)

日常交付使用普通项目文件夹，保留 Python/Qt、源码、模型资源和匹配的原生库。
Python 与 C++ 都是受维护后端。macOS arm64 与 Windows x64 使用同一界面；
不需要制作 `.app` 才能运行。下文保留既有冻结打包方式，供明确需要时使用。

<a id="source-folder"></a>

## 从项目文件夹运行

从仓库根目录操作。先确认 `.venv-path` 第一行指向本机已有的绝对解释器，
再按 [README 环境检查](../README.md#环境与检查)核对锁和依赖。
原生库必须与当前适配器和头文件匹配；源码仓库不附带本机编译产物。
原生依赖构建方法见 [C++ 说明](cpp-migration.zh-CN.md)。

项目文件夹保留以下内容：

- 完整 `sjtu_tpmshx/` 源码，包括 `configs/*.json`、`df_surrogate/_prebuilt/*.csv` 和界面资源。
- 本机 `.venv-path`、对应 `requirements-lock*.txt`、使用示例和运行说明。
- 与源码版本、平台和 ABI 匹配的动态库，以及 `native/include/`、`native/dependencies-lock.toml`、`native/THIRD_PARTY_NOTICES.md` 和 `native/licenses/`。
- 可写的模型表与运行缓存目录；表文件不写入动态库或只读资源目录。

下列 C++ 命令直接使用既有构建流程的输出路径。

macOS arm64：

```sh
tm1_python="$(sed -n '1p' .venv-path)"
export MPLCONFIGDIR="$PWD/.cache/matplotlib" XDG_CACHE_HOME="$PWD/.cache/xdg"
export NUMBA_CACHE_DIR="$PWD/.cache/numba"
"$tm1_python" -m sjtu_tpmshx.main --backend python
```

需要使用 C++ 时，关闭该窗口，再以匹配的原生库启动：

```sh
"$tm1_python" -m sjtu_tpmshx.main --backend cpp \
  --native-library "$PWD/.cache/native-deps/build/pilot-macos-arm64/libtpmshx_solver_shared.dylib" \
  --native-table-directory "$PWD/.cache/native-deps/tables"
```

Windows x64（PowerShell）：

```powershell
$tm1Python = Get-Content .venv-path -TotalCount 1
$env:MPLCONFIGDIR = Join-Path $PWD '.cache/matplotlib'
$env:XDG_CACHE_HOME = Join-Path $PWD '.cache/xdg'
$env:NUMBA_CACHE_DIR = Join-Path $PWD '.cache/numba'
& $tm1Python -m sjtu_tpmshx.main --backend python
```

需要使用 C++ 时，关闭该窗口，再以既有构建产物启动：

```powershell
$tm1Library = Join-Path $PWD '.cache/native-deps/build/pilot-windows-x64/tpmshx_solver_shared.dll'
$tm1Tables = Join-Path $PWD '.cache/native-deps/tables'
& $tm1Python -m sjtu_tpmshx.main --backend cpp --native-library $tm1Library --native-table-directory $tm1Tables
```

如库存放在其他文件夹，替换该路径。程序不搜索磁盘、编译库、下载或安装依赖。
表目录必须可写；同一原生进程固定使用一个表目录。目录内的 `CoolProp-8.0.0`
子目录只保存当前 EOS 版本生成的表，旧版本表保留供原版本使用。
CLI 的 `run` 和 `solve` 子命令接受同样的三个后端参数。
源码运行不以 `TPMSHX_NATIVE_SOLVER_LIBRARY` 代替显式启动参数。

窗口中的“计算后端”作用于下一次普通计算、快速设计和优化。
运行及取消收尾时禁止切换；切换不修改已发布结果的后端来源或保存的工况。
源码 GUI 和 CLI 共用本机默认库：macOS 为
`native/lib/macos-arm64/libtpmshx_solver_shared.dylib`，Windows 为
`native/lib/windows-x64/tpmshx_solver_shared.dll`。使用默认库时，表目录默认为
`.cache/native-deps/tables`；显式参数优先。匹配库就位后只需选择后端。
CLI、独立 C 调用和 CI 通过不代替两平台可见桌面验收。

## 可选冻结打包

桌面入口是 `sjtu_tpmshx.desktop`，调用现有 GUI 和公共三模块计算链。
`packaging/desktop.spec` 使用 PyInstaller 将解释器、锁定运行依赖、模型配置、
DF 表和 SVG 图标打包；不包含原始实验数据、研究输出、测试代码或 Office 字体。
默认构建与 `requirements-lock.txt` 的功能范围一致，不含可选 Torch/BoTorch
优化依赖。完整 BO 发行包需要单独锁定和真实优化验证，不能仅解除排除列表。
冻结桌面包的快速设计采用单进程串行候选搜索，避免子进程重复启动 GUI；
源码运行保留现有并行路径。界面会显示实际执行方式。

同一个 spec 可显式加入预构建的统一原生库：macOS 使用
`libtpmshx_solver_shared.dylib`，Windows 使用 `tpmshx_solver_shared.dll`。
库放在包内 `native/`，相应第三方说明、原生依赖锁和完整许可证放在
`licenses/native/`。打包阶段不下载依赖、不调用 C/C++ 编译器，也不改变
Python 默认后端；原生库必须先用既有原生构建流程生成并完成对应数值资格检查。

三维代码按 `vtkmodules` 定向导入；打包排除会加载全部 VTK 可选模块的旧
`vtk` 聚合入口，保留 PyVista、体渲染、拾取、透明度和导出所需的实际依赖。
更换 VTK/PyVista 版本后需重新核查导入闭包，并验证三维显示和图像/VTK 导出；
不能只因某个二进制体积较大就手动删除它。
Matplotlib 显式收集 Agg、QtAgg、SVG 和 PDF 后端，以覆盖界面和三种图像导出
格式；只依靠静态导入分析会漏掉 `savefig` 动态选择的矢量后端。

macOS 输出 `.app`，Windows 输出包含可执行文件及依赖的目录。构建必须在
目标系统上进行，不能将本机 macOS 验证当作 Windows 安装验证。参见
[PyInstaller 使用说明](https://pyinstaller.org/en/stable/usage.html)。

## 环境与构建

共享求解环境和仓库根 `.venv-path` 不变。经明确授权后，在独立构建环境安装
`requirements-lock-desktop.txt`，它包含原锁及固定版本的打包工具。
将该环境的绝对解释器路径保存在 `.cache/desktop-build/.venv-path`；后续构建
使用该解释器，从仓库根执行以下模块。不能将新构建依赖装入共享求解环境。

构建前将 PyInstaller、Matplotlib 和通用缓存设在当前工作树的忽略目录，避免
构建过程向系统用户目录写缓存。macOS shell 使用：

```sh
export PYINSTALLER_CONFIG_DIR="$PWD/.cache/desktop-build/pyinstaller-cache"
export MPLCONFIGDIR="$PWD/.cache/desktop-build/matplotlib"
export XDG_CACHE_HOME="$PWD/.cache/desktop-build/xdg-cache"
```

Windows PowerShell 使用：

```powershell
$env:PYINSTALLER_CONFIG_DIR = Join-Path $PWD '.cache/desktop-build/pyinstaller-cache'
$env:MPLCONFIGDIR = Join-Path $PWD '.cache/desktop-build/matplotlib'
$env:XDG_CACHE_HOME = Join-Path $PWD '.cache/desktop-build/xdg-cache'
```

`PYINSTALLER_CONFIG_DIR` 是 PyInstaller 的官方构建缓存控制变量，参见
[PyInstaller 环境变量说明](https://pyinstaller.org/en/stable/man/pyinstaller.html#environment-variables)。
这些设置用于开发机上的构建过程；下文的安装程序启动缓存仍由桌面启动器管理。

```text
python -m sjtu_tpmshx.runs.tools.check_locked_environment requirements-lock-desktop.txt
python -m pip check
python -m PyInstaller --noconfirm --clean --distpath .cache/desktop-build/dist --workpath .cache/desktop-build/work packaging/desktop.spec
```

上述命令在未设置 `TPMSHX_NATIVE_SOLVER_LIBRARY` 时保持既有 Python 包。
构建原生候选包时，先把该变量设为本目标平台已构建库的绝对路径，例如：

```sh
export TPMSHX_NATIVE_SOLVER_LIBRARY="/absolute/path/libtpmshx_solver_shared.dylib"
```

Windows PowerShell 使用：

```powershell
$env:TPMSHX_NATIVE_SOLVER_LIBRARY = 'C:\absolute\path\tpmshx_solver_shared.dll'
```

再执行同一 PyInstaller 命令。显式指定的文件缺失、为空或库名与目标平台不符
会使构建失败；不会悄悄省略原生库。只收集该预构建动态库及其实际运行依赖，
不把 `.cache/native-deps` 的编译器、源码树、构建目录或物性表缓存装入程序包。

示例中的 `python` 均替换为构建指针记录的绝对解释器。Numba 需要真实的源文件
定位 JIT 缓存，spec 为应用模块采用纯 Python 源文件收集和加载，避免归档内的
相对代码路径使独立目录启动时找不到缓存定位文件。启动器在导入计算模块前
将 JIT 和 Matplotlib 缓存指向系统用户缓存目录，并执行
`multiprocessing.freeze_support()`；参见
[PyInstaller 多进程说明](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#multi-processing)。
几何查表缓存也遵从 `XDG_CACHE_HOME`，首次生成和再次使用均不写入程序目录；
构建只收集白名单中的模型资源和图标，不携带开发机的会话或缓存。

## 选择原生候选后端

启动原生候选包时必须显式传入 `--backend cpp`。未传 `--native-library`
时，冻结程序从自己的包内 `native/` 定位上述平台库名；显式路径始终优先。
源码运行仍要求主机提供库路径，不会自动搜寻开发缓存、编译库或改用其他后端。
这些选项仅构造本次调用的 `RunControl`，不进入保存的 `CaseData` 或物理配置。

例如，在 macOS 上直接运行包内可执行文件：

```sh
"/path/SJTU-TPMSHX.app/Contents/MacOS/SJTU-TPMSHX" --backend cpp \
  --native-table-directory "/absolute/writable/path/native-eos-tables"
```

同一可执行文件的 `--cli run ...` / `--cli solve ...` 接受相同三个主机选项。
`--native-table-directory` 指定程序包外可写的绝对路径；sCO2 的 BICUBIC
物性表使用它，不能指向只读安装目录。原生库在一个进程内固定这一个表目录。
双击启动而不传后端参数时仍使用 Python 后端。

## 文件与状态

- 外观偏好：系统用户配置目录下 `SJTU-TPMSHX-TM1`。
- 会话、用户预设、工作区与历史：系统用户数据目录下 `SJTU-TPMSHX-TM1`。
- GUI 优化结果：用户 Documents 下 `SJTU-TPMSHX-TM1/opt_runs`，运行状态显示实际路径。
- 旧源码目录中的已知用户文件只在新位置缺少对应文件时复制，旧文件保留。
- 程序包内模型与界面资源只读；用户显式导出的 CSV/NPZ/图像遵从保存对话框路径。

普通计算、优化和快速设计均需先结束工作线程，再关闭所属窗口或重启软件。
取消是合作式请求，数值步骤完成前不会强制停止线程。优化结果区分正常完成、
用户取消和执行失败，保留已经获得的有效候选及运行记录。
关闭前会先保存当前输入；保存失败时默认取消关闭，仍可编辑或另存配置，也可明确
选择放弃后退出。取消关闭不会中断正在运行的任务。会话、预设或工作区标记编码损坏
时，原文件会尽可能保留为同目录的 `.corrupt-<唯一标识>` 文件，再使用默认值启动。
会话 JSON 对象的字段被恢复校验拒绝时，也保留同样的原文件副本，并在提示中显示
恢复失败的原因和副本位置；JSON 顶层不是对象的文件也隔离保存。每次拒绝保留独立
副本。会话读取或隔离失败后，保存前会
重试保护原文件；备份仍失败则不覆盖原件，关闭、工作区切换和重启沿用保存失败提示。
恢复目录权限后可重试保存当前会话；原件已被用户移走时也可正常保存新会话。

## 交付验证

构建成功只是第一项检查。将整个产物复制到源码树之外的临时安装目录，再从
另一个工作目录启动，验证以下行为：

1. 启动 GUI，检查字体、图标、深浅主题、参数栏和三维渲染组件能加载。
2. 修改偏好、退出、重启并核对恢复；确认程序目录没有新增用户状态文件。
3. 用包内可执行文件执行 `--cli run INPUT OUTPUT --case-id CASE_ID`，分别运行公开的
   `air_2d.json` 与 `air_3d.json`。必须保留原返回码、收敛和指标支持状态。
4. 使用 `--cli postprocess RESULTS METRICS` 独立回读结果；检查 Q 单位为
   二维 W/m、三维 W，Q/压降/出口温度与同版本源码基线一致。
5. GUI 完成真实计算并导出 CSV/NPZ；检查后台任务运行时的关闭、取消和重启保护。

包含原生库的候选包还需以显式 `--backend cpp` 重复相关计算、取消与错误路径，
检查实际加载的是复制后包内库，并在不提供 C/C++ 编译器的运行环境中完成。
macOS 用 `otool -L` 核对动态依赖，用 `otool -l` 记录库与可执行文件真实的
`LC_BUILD_VERSION minos`；使用了 macOS 13.3 起提供的 Accelerate 接口，不代表
某个以更新 SDK 构建的二进制就能运行在 13.3。最低系统版本必须按最终产物和
目标系统实测声明。Windows 仍须在真实 Windows 环境验证 DLL 依赖、GUI 与导出。

macOS 的本地临时签名构建不是经过 Apple 公证的外部分发版本。正式对外发布
仍需要项目自己的签名身份、公证和目标系统验证；此文不声明已有相关凭证。
构建日志、截图、安装运行及数值对照保存在忽略的 `.cache/`，不上传实验数据。

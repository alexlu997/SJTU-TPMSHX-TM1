# 桌面软件构建与验证

桌面入口是 `sjtu_tpmshx.desktop`，调用现有 GUI 和公共三模块计算链。
`packaging/desktop.spec` 使用 PyInstaller 将解释器、锁定运行依赖、模型配置、
DF 表和 SVG 图标打包；不包含原始实验数据、研究输出、测试代码或 Office 字体。
默认构建与 `requirements-lock.txt` 的功能范围一致，不含可选 Torch/BoTorch
优化依赖。完整 BO 发行包需要单独锁定和真实优化验证，不能仅解除排除列表。
冻结桌面包的快速设计采用单进程串行候选搜索，避免子进程重复启动 GUI；
源码运行保留现有并行路径。界面会显示实际执行方式。

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

```text
python -m sjtu_tpmshx.runs.tools.check_locked_environment requirements-lock-desktop.txt
python -m pip check
python -m PyInstaller --noconfirm --clean --distpath .cache/desktop-build/dist --workpath .cache/desktop-build/work packaging/desktop.spec
```

示例中的 `python` 均替换为构建指针记录的绝对解释器。Numba 需要真实的源文件
定位 JIT 缓存，spec 为应用模块采用纯 Python 源文件收集和加载，避免归档内的
相对代码路径使独立目录启动时找不到缓存定位文件。启动器在导入计算模块前
将 JIT 和 Matplotlib 缓存指向系统用户缓存目录，并执行
`multiprocessing.freeze_support()`；参见
[PyInstaller 多进程说明](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#multi-processing)。
几何查表缓存也遵从 `XDG_CACHE_HOME`，首次生成和再次使用均不写入程序目录；
构建只收集白名单中的模型资源和图标，不携带开发机的会话或缓存。

## 文件与状态

- 外观偏好：系统用户配置目录下 `SJTU-TPMSHX-TM1`。
- 会话、用户预设、工作区与历史：系统用户数据目录下 `SJTU-TPMSHX-TM1`。
- GUI 优化结果：用户 Documents 下 `SJTU-TPMSHX-TM1/opt_runs`，运行状态显示实际路径。
- 旧源码目录中的已知用户文件只在新位置缺少对应文件时复制，旧文件保留。
- 程序包内模型与界面资源只读；用户显式导出的 CSV/NPZ/图像遵从保存对话框路径。

普通计算、优化和快速设计均需先结束工作线程，再关闭所属窗口或重启软件。
取消是合作式请求，数值步骤完成前不会强制停止线程。优化结果区分正常完成、
用户取消和平台期提前结束，保留已经获得的有效候选。
关闭前会先保存当前输入；保存失败时默认取消关闭，仍可编辑或另存配置，也可明确
选择放弃后退出。取消关闭不会中断正在运行的任务。会话、预设或工作区标记编码损坏
时，原文件会尽可能保留为同目录的 `.corrupt-<时间戳>` 文件，再使用默认值启动。

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

macOS 的本地临时签名构建不是经过 Apple 公证的外部分发版本。正式对外发布
仍需要项目自己的签名身份、公证和目标系统验证；此文不声明已有相关凭证。
构建日志、截图、安装运行及数值对照保存在忽略的 `.cache/`，不上传实验数据。

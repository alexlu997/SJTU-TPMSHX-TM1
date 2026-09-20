# Spec: ui-design-tokens

## Purpose
设计令牌纪律：圆角/色值单一来源于 theme.py，锁测试禁散落 hex 与私设半径。（结构修复 2026-07-03：补 Purpose 头，内容不变。）

## Requirements

### Requirement: Shared control radii
共享输入、按钮和卡片 SHALL 使用 `theme.py` 的令牌
`RADIUS_INPUT=8` / `RADIUS_BTN=8` / `RADIUS_CARD=12`（px）。滑块、复选框、滚动条、
进度条及语义胶囊按控件尺寸设置圆角；现有例外由布局卫生测试界定。
已删除的 `RADIUS_TAB` 不再作为实现要求。

#### Scenario: No stray radii
- **WHEN** 运行 `test_ui_layout_hygiene.py` 的圆角检查
- **THEN** 新增卡片和控件圆角通过令牌获取，没有散落的 8/10/12px 字面量；保留现有微型控件及胶囊例外

### Requirement: No hex outside theme
普通 UI 色值 SHALL 经 theme token 获取；红色错误边框与搜索高亮也使用 token。
token 查找的 fallback、色图和特殊渲染例外由现有布局卫生测试明确限定。

#### Scenario: Light theme inherits fixes
- **WHEN** 切亮色主题
- **THEN** 使用 token 的控件取亮色值，无固定暗色残留

### Requirement: Type scale closed
共享字号 SHALL 使用 `theme.py` 的 FONT_* 层级（状态 9pt、标签/次要按钮 10pt、
输入/区块 11pt、主计算按钮 12pt），保留已有密度调整和展示位字号。
正文和输入使用常规字重，标题、结果及主操作使用较高字重以区分层次。

#### Scenario: 13pt eliminated
- **WHEN** grep `font-size:13pt`
- **THEN** 零命中

### Requirement: Numeric inputs right-aligned
`FieldFactory.line_edit` 产出的数值输入 SHALL 右对齐，便于比较数量级。
界面 SHALL 使用系统无衬线字体：macOS 系统西文与苹方，Windows Segoe UI 与微软雅黑，
Linux 可用的 Noto Sans / 系统回退。图表与导出图片独立保留现有论文字体，
界面不得依赖 Office 字体，也不将比例数字描述为等宽字体。

#### Scenario: Alignment set
- **WHEN** 检查任一参数输入框
- **THEN** alignment 含 AlignRight

### Requirement: Glass chrome and stable interaction
玻璃质感 SHALL 使用共享渐变与细边框绘制于导航和少量浮层；参数和结果区域保持实底，
图表内容保持清晰，不在 Matplotlib/PyVista 表面增加模糊或持续重绘效果。
悬停与键盘聚焦 SHALL 保留内容位置和清晰的焦点提示。

#### Scenario: Transient feedback
- **WHEN** 显示计算完成提示或重复触发结果高光
- **THEN** 位移与透明度同步变化，停留阶段保持静止；结束后释放临时效果，旧动画不会清除新效果

#### Scenario: Form transitions
- **WHEN** 切换参数页、展开参数栏或展开计算详情
- **THEN** 新内容以 200 ms OutCubic 从 0.72 不透明度淡入，文字全程保持清晰，结束后释放效果；输入与页码立即生效，连续操作替换旧动画。同页点击、隐藏窗口初始化及 `QT_REDUCED_MOTION=1` 不启动该动效
- **AND** 图表不附加模糊效果，参数栏宽度一次调整到位；画布切换在一次重绘批次中提交，不在隐藏与显示之间分发下一次输入
- **AND** 窗口首次出现时在当前可见参数区播放一次相同淡入，提前初始化效果；再次显示窗口不重复，也不改变当前分组或输入值

#### Scenario: High refresh displays
- **WHEN** 可见窗口播放参数、提示、高光或三维预设视角动画
- **THEN** 以独立的 8 ms 精确定时器和实际经过时间推进；晚帧不补队列，取消/销毁时停止驱动，提示静止停留时暂停高频唤醒。定时器间隔不视为实际显示帧率
- **AND** 高刷新验收记录窗口缩放、显示器刷新率、绘制间隔与首次响应延迟；计时器回调和离屏测试不能代替屏幕呈现帧率证据
- **AND** 三维鼠标旋转和预设过渡使用 VTK 原生交互预算，自适应降低运动中的体渲染采样精细度；停止后恢复原静态预算并重绘，不改变计算场或完整结果导出。鼠标拖拽接管时取消旧预设过渡，隐藏和关闭时不追加渲染

### Requirement: Workbench parameter rail and canvas focus
工作台 SHALL 将参数编辑放在左侧、画布放在右侧、计算状态与结果摘要放在画布下方。
参数栏可调整宽度，并通过标题按钮或 `Ctrl+\` 收成包含几何、边界、求解入口的图标栏。
展开时 SHALL 复用原输入控件，保留输入值、当前分组、滚动位置及上次展开宽度。
“专注”按钮与 `F` SHALL 作用于当前画布，暂时收起参数和结果摘要；退出时恢复原来的
展开状态。参数收纳及专注模式 SHALL 保留计算状态卡的取消入口。

#### Scenario: Inspect results while editing the next case
- **WHEN** 运行计算后收起参数、切换专注模式，再展开参数并修改下一轮配置
- **THEN** 本次计算仍使用启动时的输入快照，结果来源和导出内容不随草稿编辑改变

### Requirement: Truthful expandable compute status
计算状态卡 SHALL 复用已有耗时、迭代及残差回调；展开后显示实际收到的 A/B 残差，
不制造进度、残差或预计剩余时间。三维路径未发布实时残差时 SHALL 明确显示暂无数据。
取消后显示等待当前计算步结束，终态区分正常完成、有提示、未收敛、失败和取消；
求解器完成但三维视图不可用时显示提示，保留已有结果的导出能力。
本次完整日志仅在计算结束并已捕获内容时开放，重新计算时清除上一轮状态卡内容。

#### Scenario: A terminal callback is not a validation verdict
- **WHEN** 收到 finished 回调，但 `ComputeResult.converged` 为 false 或结果带有提示
- **THEN** 卡片保留未收敛或有提示的终态，不以正常完成样式掩盖该信息

### Requirement: Scalable consistent icons
工作台导航及常用操作 SHALL 使用共享 SVG 图标入口，统一视觉尺寸和主题色，并按目标
设备像素比绘制。仅图标按钮 SHALL 提供可访问名称或清楚的提示，关键操作保留文字。

#### Scenario: Device scale changes
- **WHEN** 同一图标在不同设备像素比下绘制
- **THEN** 使用目标尺度渲染矢量资源，不放大固定低分辨率位图

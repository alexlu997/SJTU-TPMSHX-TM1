# 贡献者扩展指南

[中文](extending.zh-CN.md) | [English](extending.md)

本指南用于快速定位扩展改动的起点、公开接口、下游使用方及对应测试。
路线对应 `main` 当前代码，涵盖 C++ 数值所有者、Python 绑定、保存数据与 GUI。
三阶段流程和物理不变量见[架构说明](architecture.zh-CN.md)，本地与 CI 检查命令见[验证指南](verification.md)。

## 快速路线索引

| 扩展问题 | 首选所有者与接口 | 下游使用方 | 现有测试 | 完整路线 |
| --- | --- | --- | --- | --- |
| 新增流体或 Nu 闭合 | [compute_config.py](../python/data_types/compute_config.py)（`FluidType`、`Sco2NuConfig`）、[fluid_props.py](../python/physical_models/fluid_props.py)（`FLUIDS`、`get`）、[nu_correlations.py](../python/physical_models/nu_correlations.py)、[fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp)（`Fluid`）、[fluid_properties.cpp](../numerics/fluid_properties.cpp)（`fluid_nusselt_ratio`、`nu_point`） | [model_configs/](../python/model_configs/)、[generate_native_model_coefficients.py](../engineering/scripts/generate_native_model_coefficients.py)、[inlet_properties.py](../python/cpp_interface/inlet_properties.py)、[preparation_host.py](../python/cpp_interface/preparation_host.py)、[full_2d_stage.py](../python/cpp_interface/full_2d_stage.py)、[full_3d_stage.py](../python/cpp_interface/full_3d_stage.py)、[builders_fluids.py](../python/applications/gui/ui/builders_fluids.py)、[stage_saved_models.hpp](../solver/stage_saved_models.hpp) | [test_fluid_properties.py](../tests/python/native/test_fluid_properties.py)、[test_fluid_props.py](../tests/python/test_fluid_props.py)、[test_nu_correlations.py](../tests/python/test_nu_correlations.py)、[test_sco2_nu_modes.py](../tests/python/test_sco2_nu_modes.py)、[test_catalog.py](../tests/python/models_tm1/test_catalog.py) | [新增流体或 Nu 闭合](#new-fluid-or-nu-closure) |
| 新增 GUI 面板或对话框 | [ui_builders.py](../python/applications/gui/ui/ui_builders.py)（`build_ui`）、[builders_canvas.py](../python/applications/gui/ui/builders_canvas.py)（`build_canvas_area`）、[optimize_ui.py](../python/applications/gui/ui/mixins/optimize_ui.py)（`_open_quick_design`）、[quick_design_panel.py](../python/applications/gui/ui/quick_design_panel.py)（`build_quick_design_dialog`）、[result_cache.py](../python/applications/gui/controllers/result_cache.py)（`ResultCache`） | [main.py](../python/applications/gui/main.py)、[tab_view.py](../python/applications/gui/ui/mixins/tab_view.py)、[run_results.py](../python/applications/gui/ui/mixins/run_results.py)、[plot_2d_results.py](../python/applications/gui/ui/plot_2d_results.py)、[window_config.py](../python/applications/gui/ui/window_config.py)、[OpenSpec `ui-*`](../openspec/specs/) | [conftest.py](../tests/python/conftest.py)、[test_quick_design_panel_wiring.py](../tests/python/test_quick_design_panel_wiring.py)、[test_optimize_panel_wiring.py](../tests/python/test_optimize_panel_wiring.py)、[test_result_snapshot_lifecycle.py](../tests/python/test_result_snapshot_lifecycle.py)、[test_ui_layout_hygiene.py](../tests/python/test_ui_layout_hygiene.py) | [新增 GUI 面板或对话框](#new-gui-panel-or-dialog) |
| 新增第三种 TPMS 拓扑 | [compute_config.py](../python/data_types/compute_config.py)（`TPMSType`）、[fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp)（`Topology`）、[geometry.cpp](../geometry/geometry.cpp)（`phi_grid`、`topology_row`） | [_native_values.py](../python/cpp_interface/_native_values.py)（`TOPOLOGIES`）、[generate_native_model_coefficients.py](../engineering/scripts/generate_native_model_coefficients.py)（`table`）、[stage_saved_models.hpp](../solver/stage_saved_models.hpp)、[preparation_df.cpp](../preprocess/preparation_df.cpp)、[window_config.py](../python/applications/gui/ui/window_config.py)（`_selected_topology`）、[sensitivity.py](../python/applications/gui/ui/sensitivity.py) | [geometry_kernel_smoke.cpp](../tests/cpp/geometry_kernel_smoke.cpp)、[test_native_geometry.py](../tests/python/test_native_geometry.py)、[test_main_smoke.py](../tests/python/test_main_smoke.py)、[test_catalog.py](../tests/python/models_tm1/test_catalog.py) | [第三种 TPMS 拓扑](#third-tpms-topology) |

<a id="new-fluid-or-nu-closure"></a>

## 新增流体或 Nu 闭合

先区分“为现有流体新增 Nu 关联式”和“新增工质流体”两种范围。

- **为现有流体新增 Nu 关联式（范围较小）**：保持 `FluidType` 与 `enum class Fluid` 不变，复用现有输运物性、相态检查与能量方程。主要更新带版本模型资源、配置项、Nu 封装、原生 `nu_point`、阶段传输与 GUI 选项。
- **新增工质流体（完整范围）**：须同步扩展 Python 类型、原生枚举、输运或 EOS 求值器、相态检查、能量关系、D-F 适用范围、保存工况解析及 GUI 流体选项。

### 1. 首先打开的文件（规则所有者）

按以下顺序查看配置类型、Python 分发、模型资源与原生计算核：

1. 打开 [python/data_types/compute_config.py](../python/data_types/compute_config.py)。
   新增流体时扩展 `FluidType`，并核对 `FluidConfig` 与 `ComputeConfig.validate`。
   新增 Nu 关联式时，参照 `Sco2NuConfig` 新增或扩展带类型校验的配置数据类。
2. 打开 [python/physical_models/fluid_props.py](../python/physical_models/fluid_props.py) 与 [python/physical_models/nu_correlations.py](../python/physical_models/nu_correlations.py)。
   `fluid_props.py` 负责 `FLUIDS`、`FluidModel`、`get`、`flow_model` 与 `check_water_state`。
   `nu_correlations.py` 负责公开 Nu 封装（`nu_from_Re`、`nu_vec`、`nu_water_topo`、`nu_sco2_topo`、`nu_sco2_selected`、`sco2_effective_nu_config`）与范围警告辅助（`record_raw_nu_range`、`warn_sco2_nu_evidence`）。
3. 打开 [python/model_configs/](../python/model_configs/) 与 [engineering/scripts/generate_native_model_coefficients.py](../engineering/scripts/generate_native_model_coefficients.py)。
   系数、范围与版本标识统一写入带版本 JSON 资源（`model_parameters_v1.json`、`sco2_effective_nu.json`、`co2_segment2_v1.json`、`preparation_df_v1.json`）。
   在 [python/model_configs/model_parameters.py](../python/model_configs/model_parameters.py) 中校验格式（`MODEL_VERSIONS`、`load_model_parameters`、`load_co2_coefficients`、`load_preparation_df_parameters`）。
   在 `generate_native_model_coefficients.py` 中生成 C++ 编译期常量（`header`、`df_header`、`table`）。
4. 打开 [include/tpmshx/fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp) 与 [numerics/fluid_properties.cpp](../numerics/fluid_properties.cpp)。
   `fluid_properties.hpp` 定义 `enum class Fluid`、`uses_co2_eos`、`model_h_coefficients`、`nusselt_floor`、`fluid_nusselt`、`fluid_nusselt_ratio` 与 `PropertyEvaluator`。
   `fluid_properties.cpp` 实现 `PropertyEvaluator::evaluate`、`PropertyEvaluator::transport`、`fluid_nusselt_ratio`、`preparation::empirical_point` 与 `preparation::nu_point`。
   同时核对 [preprocess/preparation_properties.hpp](../preprocess/preparation_properties.hpp)（`enum class Empirical`、`enum class NuRoute`）。

### 2. 公开接口

- **Python 配置与模型查询**：[python/data_types/compute_config.py](../python/data_types/compute_config.py) 中的 `ComputeConfig`、`FluidConfig`、`Sco2NuConfig`；[python/physical_models/fluid_props.py](../python/physical_models/fluid_props.py) 中的 `fluid_props.get` 与 `fluid_props.flow_model`；[python/physical_models/nu_correlations.py](../python/physical_models/nu_correlations.py) 中的 Nu 函数。
- **三阶段 Python API**：`prepare_case`（[python/preprocess/api.py](../python/preprocess/api.py)）、`run_case`（[python/solvers/api.py](../python/solvers/api.py)）、`evaluate`（[python/postprocess/api.py](../python/postprocess/api.py)）与 `compute`（[python/compute.py](../python/compute.py)）。
- **原生 C 与 C++ 接口**：[include/tpmshx/fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp) 中的 `enum class Fluid`、`PropertyEvaluator`、`fluid_nusselt`、`fluid_nusselt_ratio`；[include/tpmshx/preparation_case_c_api.h](../include/tpmshx/preparation_case_c_api.h) 中的 `tpmshx_query_inlet_properties_v2`；[include/tpmshx/solver_c_api.h](../include/tpmshx/solver_c_api.h) 中的 `enum tpmshx_fluid`。

### 3. 下游使用方

#### 原生准备与求解传输

- **C ABI 布局与物性适配**：更新 [python/cpp_interface/_native_preparation_case.py](../python/cpp_interface/_native_preparation_case.py) 中的 `_FLUIDS`、`_Inlet`、`_Nu`，以及 [python/cpp_interface/_native_properties.py](../python/cpp_interface/_native_properties.py) 中的物性／Nu 调用（`empirical`、`nu_inputs`、`nusselt`）。
- **独立入口查询**：在 [python/cpp_interface/inlet_properties.py](../python/cpp_interface/inlet_properties.py) 的 `inlet_query` 中同步更新流体编号、压力规则或 Nu 选项打包（对应 `tpmshx_query_inlet_properties_v2`）。
- **共享前处理宿主**：更新 [python/cpp_interface/preparation_host.py](../python/cpp_interface/preparation_host.py) 中的 `validate_fluid_type`、`observe_range`、`pack_nu`、`pack_saved_resources`、`model_metadata` 与 `PreparationCacheBridge`。
- **完整二维与三维阶段绑定**：在 [python/cpp_interface/full_2d_stage.py](../python/cpp_interface/full_2d_stage.py)（`prepare_stage`、`pack_saved`、`run_case`）和 [python/cpp_interface/full_3d_stage.py](../python/cpp_interface/full_3d_stage.py)（`validate_saved_case`、`pack_input`、`pack_saved_case`、`run_case`）中同步更新流体编号、Nu 参数打包与保存工况校验。
- **原生 C++ 驱动**：新增流体时还须核对 [preprocess/preparation_case.cpp](../preprocess/preparation_case.cpp)（`query_inlet_properties`、`prepare_case_2d`、`prepare_case_3d`）、[preprocess/preparation_df.cpp](../preprocess/preparation_df.cpp)、[solver/full_2d.cpp](../solver/full_2d.cpp)、[solver/full_3d.cpp](../solver/full_3d.cpp) 及 [solver/quick_design_driver.cpp](../solver/quick_design_driver.cpp)。
- **重编原生库**：修改 C++ 或编译期模型资源后，使用 [engineering/scripts/build_native_dependencies.py](../engineering/scripts/build_native_dependencies.py) 重新构建并发布受影响的原生库，然后重启 Python 进程。详见[C++ 接入说明](cpp-migration.zh-CN.md#native-preparation-core)。

#### 应用与 GUI

- 打开 [python/applications/gui/ui/builders_fluids.py](../python/applications/gui/ui/builders_fluids.py)（`build_fluid_sections`、`refresh_fluid_model_visibility`），更新 `combo_fluidA`、`combo_fluidB` 或 Nu 模型控件（可参照 `combo_sco2_nu_mode`）。
- 打开 [python/applications/gui/ui/window_config.py](../python/applications/gui/ui/window_config.py)，同步更新 `_parse_fluid_label`、`sco2_nu_from_window` 与 `config_from_window`。
- 核对 [python/applications/gui/ui/mixins/fluid_input.py](../python/applications/gui/ui/mixins/fluid_input.py) 中的入口自动填充预览，以及 [python/applications/gui/ui/sensitivity.py](../python/applications/gui/ui/sensitivity.py)（当前灵敏度扫描将流体 A 限制为空气）。

#### 保存数据与模型解析

- 在 [python/physical_models/catalog.py](../python/physical_models/catalog.py)（`resolve_model`、`MODEL_VERSIONS`）与 [solver/stage_saved_models.hpp](../solver/stage_saved_models.hpp)（`validate_saved_models`）中注册或更新带版本模型标识。
- 保持 [python/file_io/case_io.py](../python/file_io/case_io.py) 与 [python/file_io/result_io.py](../python/file_io/result_io.py) 的 YAML／HDF5 持久化符合[三模块数据契约](contracts/three_module_v1/README.zh-CN.md)。
- 已有保存工况与结果文件必须保留各自记录的模型版本与参数，不得静默替换。

### 4. 需要扩展的现有测试

- **原生物性与 Nu 检查**：[tests/python/native/test_fluid_properties.py](../tests/python/native/test_fluid_properties.py) 与 [tests/cpp/fluid_properties_smoke.cpp](../tests/cpp/fluid_properties_smoke.cpp)。
- **Python 模型与 Nu 契约**：[tests/python/test_fluid_props.py](../tests/python/test_fluid_props.py)、[tests/python/test_nu_correlations.py](../tests/python/test_nu_correlations.py)、[tests/python/test_fluid_type_validation.py](../tests/python/test_fluid_type_validation.py) 与 [tests/python/test_sco2_nu_modes.py](../tests/python/test_sco2_nu_modes.py)。
- **目录、配置与阶段准备**：[tests/python/models_tm1/test_catalog.py](../tests/python/models_tm1/test_catalog.py)、[tests/python/test_compute_config_roundtrip.py](../tests/python/test_compute_config_roundtrip.py)、[tests/python/preprocess/test_2d_tm1.py](../tests/python/preprocess/test_2d_tm1.py)、[tests/python/preprocess/test_3d_tm1.py](../tests/python/preprocess/test_3d_tm1.py) 与 [tests/python/io_tm1/test_case_io.py](../tests/python/io_tm1/test_case_io.py)。
- **GUI 流体输入接线**：[tests/python/test_fluid_input.py](../tests/python/test_fluid_input.py)。

### 5. 验证与数据要求

- 新增流体或 Nu 闭合进入生产使用前，必须提供 CFD 或实验物理证据。
- 原始数据保留在本地 `data/raw_data/` 且不提交到 Git；在[模型资源](model-resources.md)和[数据目录](data-catalog.md)记录来源与适用范围。
- 明确声明温度、压力、`Re` 与 `Pr` 范围，确保 `evaluate_applicability` 与 `evaluate_qualification` 准确报告参数范围和模型适用状态。
- 在[能力范围](capabilities.md)中说明已支持能力与当前限制。
- **物理验收由用户决定。** 单元测试、原生冒烟测试或 CI 通过不代表物理模型已获准用于工程设计。

<a id="new-gui-panel-or-dialog"></a>

## 新增 GUI 面板或对话框

先判断界面功能应作为工作台卡片嵌入主画布，还是作为独立对话框打开。
工作台卡片共享主画布生命周期，独立对话框则自行管理窗口与后台工作线程状态。

### 1. 首先打开的文件（规则所有者）

- **工作台外壳与参数检查栏**：打开 [python/applications/gui/ui/ui_builders.py](../python/applications/gui/ui/ui_builders.py)（`build_ui`、`build_param_tabs`、`build_page_zones`、`refresh_group_badges`）。
- **工作台画布卡片**：打开 [python/applications/gui/ui/builders_canvas.py](../python/applications/gui/ui/builders_canvas.py)（`build_canvas_area`、`_build_canvas_content`、`_build_optimize_panel`、`refresh_field_controls`）。
  `build_canvas_area` 将卡片注册到 `window._canvas_cards`，并挂载优化向导等内嵌面板。
- **独立对话框归属示例（快速设计）**：
  - 打开 [python/applications/gui/ui/mixins/optimize_ui.py](../python/applications/gui/ui/mixins/optimize_ui.py)（`OptimizeUIMixin._open_quick_design`），查看主窗口如何按需创建、复用并置顶 `self._qd_dialog`。
  - 打开 [python/applications/gui/ui/quick_design_panel.py](../python/applications/gui/ui/quick_design_panel.py)（`build_quick_design_dialog`、`run_quick_design`、`cancel_quick_design`、`_gather_inputs`），查看控件构建、后台工作线程接线与关闭保护。
  - 其他窗口级对话框见 [python/applications/gui/ui/mixins/dialogs.py](../python/applications/gui/ui/mixins/dialogs.py)（`DialogsMixin`）。
- **已发布结果归属**：打开 [python/applications/gui/controllers/result_cache.py](../python/applications/gui/controllers/result_cache.py)（`ResultCache`）。
  `ResultCache` 是已发布二维与三维 `ComputeResult` 的唯一所有者。

### 2. 公开接口与边界规则

- **Qt 边界规则**：仅允许在 `python/applications/gui/ui/` 与 `python/applications/gui/controllers/` 中导入 `PySide6`。
  下层模块（`data_types/`、`physical_models/`、`preprocess/`、`solvers/`、`postprocess/`、`file_io/`、`run_control/`、`cpp_interface/`）必须保持无 Qt 依赖。
- **控件到配置边界**：在 [python/applications/gui/ui/window_config.py](../python/applications/gui/ui/window_config.py)（`config_from_window`、`CONFIG_FIELDS`、`FieldSpec`）中一次性将控件读取为无 Qt 依赖的 `ComputeConfig`。
  `window_config.py` 不导入 Qt，无头测试可直接传入轻量桩对象。
- **单一结果所有者**：[python/applications/gui/ui/mixins/run_results.py](../python/applications/gui/ui/mixins/run_results.py)（`RunResultsMixin.write_result`）将隔离后的 `ComputeResult` 发布到 `ResultCache`（`set_result`、`get_result`、`has_results`、`mark_drawn`）。
  不得在 `Main_Menu` 上另存结果字段镜像。
  例如 [python/applications/gui/ui/plot_2d_results.py](../python/applications/gui/ui/plot_2d_results.py)（`finalize_plots`、`plot_temperature_3panel`、`_draw_zone_overlays`）中的二维分区叠加线已直接从 `ResultCache` 读取 `result.zones`。
- **样式与后台线程**：统一使用 [field_factory.py](../python/applications/gui/ui/field_factory.py)（`FieldFactory`）、[theme_manager.py](../python/applications/gui/ui/theme_manager.py)（`ThemeManager`）与 [responsive.py](../python/applications/gui/ui/responsive.py)（`ResponsiveRow`）。
  繁重数值计算放在后台工作线程，控件更新、Matplotlib 与 OpenGL 保持在 GUI 线程执行。

### 3. 下游使用方

- **主窗口与导航**：在 [python/applications/gui/main.py](../python/applications/gui/main.py)（`Main_Menu`）、[python/applications/gui/ui/mixins/tab_view.py](../python/applications/gui/ui/mixins/tab_view.py)（`TabViewMixin._canvas_tab_availability`、`_update_tab_visibility`）、[python/applications/gui/ui/mixins/shortcuts.py](../python/applications/gui/ui/mixins/shortcuts.py)、[python/applications/gui/ui/builders_sidebar.py](../python/applications/gui/ui/builders_sidebar.py)（`refresh_result_sidebar`）及 [python/applications/gui/ui/command_palette.py](../python/applications/gui/ui/command_palette.py) 中衔接入口按钮、快捷键与卡片可见性。
- **会话、预设与导出**：若新面板增加持久化输入或导出项，须同步更新 [python/applications/gui/ui/mixins/session_presets.py](../python/applications/gui/ui/mixins/session_presets.py)、[python/applications/gui/ui/mixins/io_actions.py](../python/applications/gui/ui/mixins/io_actions.py) 与 [python/applications/gui/controllers/user_storage.py](../python/applications/gui/controllers/user_storage.py)。
  旧版会话与预设文件必须保持可读。
- **应用层调用**：调用公开应用或后处理接口（[python/compute.py](../python/compute.py)、[python/applications/design/](../python/applications/design/)、[python/applications/optimization/](../python/applications/optimization/)、[python/postprocess/result_display.py](../python/postprocess/result_display.py)），不要直接调用 `python/cpp_interface/`。
- **OpenSpec UI 规范**：核对 [openspec/specs/](../openspec/specs/) 下的九项现行 `ui-*` 规范：
  - [ui-result-workbench](../openspec/specs/ui-result-workbench/spec.md) 与 [ui-layout-hygiene](../openspec/specs/ui-layout-hygiene/spec.md)（工作台卡片、禁止横向滚动、`ResultCache` 归属）。
  - [ui-cta-and-shortcuts](../openspec/specs/ui-cta-and-shortcuts/spec.md)、[ui-workflow-ia](../openspec/specs/ui-workflow-ia/spec.md) 与 [ui-optimize-wizard](../openspec/specs/ui-optimize-wizard/spec.md)（主操作按钮、信息架构与优化向导状态）。
  - [ui-chinese-chrome](../openspec/specs/ui-chinese-chrome/spec.md)、[ui-design-tokens](../openspec/specs/ui-design-tokens/spec.md)、[ui-group-badges](../openspec/specs/ui-group-badges/spec.md) 与 [ui-results-quickswitch](../openspec/specs/ui-results-quickswitch/spec.md)（界面文案、主题令牌、分组徽章与结果快速切换）。

### 4. 需要扩展的现有测试

- **无头 Qt 测试基础**：[tests/python/conftest.py](../tests/python/conftest.py) 在导入 `PySide6` 前设置 `QT_QPA_PLATFORM=offscreen`，并初始化共享离屏 `QApplication`。
- **对话框与面板接线**：[tests/python/test_quick_design_panel_wiring.py](../tests/python/test_quick_design_panel_wiring.py)、[tests/python/test_quick_design_dialog.py](../tests/python/test_quick_design_dialog.py)、[tests/python/test_optimize_panel_wiring.py](../tests/python/test_optimize_panel_wiring.py) 与 [tests/python/test_main_smoke.py](../tests/python/test_main_smoke.py)。
- **结果缓存、叠加线与工作台状态**：[tests/python/test_result_cache.py](../tests/python/test_result_cache.py)、[tests/python/test_result_snapshot_lifecycle.py](../tests/python/test_result_snapshot_lifecycle.py)、[tests/python/test_workbench_field_selection.py](../tests/python/test_workbench_field_selection.py) 与 [tests/python/test_workbench_navigation.py](../tests/python/test_workbench_navigation.py)。
- **布局与导入分层检查**：[tests/python/test_ui_layout_hygiene.py](../tests/python/test_ui_layout_hygiene.py)、[tests/python/architecture/test_three_module_imports.py](../tests/python/architecture/test_three_module_imports.py) 与 [tests/python/models_tm1/test_model_boundary.py](../tests/python/models_tm1/test_model_boundary.py)。
  同时运行 `python -m sjtu_tpmshx.development.runs.tools.audit_import_graph --fail-on-violations`。
- 遵守[测试范围规则](collaboration.zh-CN.md#测试范围)：测试状态变化、公开契约与资源清理，不测试离屏像素坐标或固定边距数值。

### 5. 验证与数据要求

- 按[验证指南](verification.md)运行无头 GUI 测试、布局健康检查与导入分层检查。
- 界面行为变更时同步更新受影响 `openspec/specs/ui-*/` 目录下的 `spec.md` 与 `spec.en.md`。
- 无头 CI 不替代 macOS 与 Windows 实机界面和 OpenGL 三维渲染验收，见[Qt 渲染说明](verification.md#qt-rendering)。
- 尚未定案的交互流程或界面契约变更，在交付前须先由用户确认。

<a id="third-tpms-topology"></a>

## 第三种 TPMS 拓扑（简明路线）

当前新增第三种 TPMS 拓扑，在计入系数、资格数据、测试、UI 与文档之前，约需改动 22 个代码文件。
请在获得经批准的标定数据后再实施，并确保未支持的拓扑在所有入口显式报错。

### 1. 首先打开的文件（规则所有者）

- 打开 [python/data_types/compute_config.py](../python/data_types/compute_config.py)（`TPMSType`），它是 `GeometryConfig` 与 GUI 校验共同使用的无 Qt 依赖支持拓扑列表。
- 打开 [include/tpmshx/fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp)（`enum class Topology`）与 [geometry/geometry.cpp](../geometry/geometry.cpp)（`topology_row`、`phi_grid`、`calibration`）。

### 2. 公开接口

- **Python ABI 映射**：在 [python/cpp_interface/_native_values.py](../python/cpp_interface/_native_values.py) 中同步更新 `TOPOLOGIES`、`TOPOLOGY_CODES` 与 `geometry_topology`，使其与 C++ 枚举顺序一致。
- **原生 C 与 C++ 枚举**：更新 `enum class Topology`（[include/tpmshx/fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp)）、`enum tpmshx_geometry_topology_v1`（[include/tpmshx/geometry_c_api.h](../include/tpmshx/geometry_c_api.h)）、`enum tpmshx_topology`（[include/tpmshx/solver_c_api.h](../include/tpmshx/solver_c_api.h)）及 [include/tpmshx/stages.hpp](../include/tpmshx/stages.hpp) 中的 SDK 映射。

### 3. 下游使用方

- **几何内核与物性分发**：更新 [geometry/geometry.cpp](../geometry/geometry.cpp)（`phi_grid`、`topology_row`）、[geometry/geometry_c_api.cpp](../geometry/geometry_c_api.cpp) 与 [numerics/fluid_properties.cpp](../numerics/fluid_properties.cpp)（`topology_row`、`preparation::nu_point`）。
- **生成器行顺序与模型资源**：更新 [engineering/scripts/generate_native_model_coefficients.py](../engineering/scripts/generate_native_model_coefficients.py)（`table`、`header`、`df_header`）中的拓扑行顺序，以及 [python/model_configs/model_parameters.py](../python/model_configs/model_parameters.py)（`load_model_parameters`、`load_co2_coefficients`、`load_preparation_df_parameters`）中的资源校验。
  同步更新 `model_parameters_v1.json`、`preparation_df_v1.json` 与 `cfd_full_core_3cell_fixed_v2.csv`（或在 [preprocess/preparation_df.cpp](../preprocess/preparation_df.cpp) 的 `topology_check` 中对未支持模式显式报错）。
- **前处理、求解与保存模型解码**：更新 [preprocess/preparation_case.cpp](../preprocess/preparation_case.cpp)、[preprocess/property_c_api.cpp](../preprocess/property_c_api.cpp)、[preprocess/quick_design_prepare_v2.cpp](../preprocess/quick_design_prepare_v2.cpp)、[solver/solver_c_api.cpp](../solver/solver_c_api.cpp)、[solver/full_2d.cpp](../solver/full_2d.cpp)、[solver/full_3d_c_api.cpp](../solver/full_3d_c_api.cpp)、[solver/stage_run.cpp](../solver/stage_run.cpp)、[solver/closure_ranges.hpp](../solver/closure_ranges.hpp)、[solver/stage_capture_2d.cpp](../solver/stage_capture_2d.cpp) 与 [solver/stage_capture_3d.cpp](../solver/stage_capture_3d.cpp) 中的拓扑分支与输出标签。
  更新保存模型解码：[solver/stage_saved_models.hpp](../solver/stage_saved_models.hpp)（`validate_saved_models`）、[python/cpp_interface/preparation_host.py](../python/cpp_interface/preparation_host.py)（`pack_saved_resources`）与 [python/physical_models/catalog.py](../python/physical_models/catalog.py)（`resolve_model`）。
  已有 Diamond 与 Gyroid 归档必须保持原有拓扑标识不变。
- **GUI 拓扑选择**：更新 [python/applications/gui/ui/builders_domain.py](../python/applications/gui/ui/builders_domain.py) 中的 `combo_tpms` 与 [python/applications/gui/ui/quick_design_panel.py](../python/applications/gui/ui/quick_design_panel.py) 中的 `combo_cell_topo`。
  [python/applications/gui/ui/window_config.py](../python/applications/gui/ui/window_config.py)（`_selected_topology`）与 [python/applications/gui/ui/sensitivity.py](../python/applications/gui/ui/sensitivity.py)（`SensitivityDialog._collect_fixed_params`）已直接读取 `TPMSType` 并拒绝未支持名称。
- **重编原生库**：使用 [engineering/scripts/build_native_dependencies.py](../engineering/scripts/build_native_dependencies.py) 重新构建并发布全部四个原生库。

### 4. 需要扩展的现有测试

- **原生几何与物性**：[tests/cpp/geometry_kernel_smoke.cpp](../tests/cpp/geometry_kernel_smoke.cpp)、[tests/cpp/geometry_c_smoke.c](../tests/cpp/geometry_c_smoke.c)、[tests/python/test_native_geometry.py](../tests/python/test_native_geometry.py) 与 [tests/python/native/test_fluid_properties.py](../tests/python/native/test_fluid_properties.py)。
- **配置、目录与 GUI 选择**：[tests/python/test_main_smoke.py](../tests/python/test_main_smoke.py)、[tests/python/test_compute_config_roundtrip.py](../tests/python/test_compute_config_roundtrip.py) 与 [tests/python/models_tm1/test_catalog.py](../tests/python/models_tm1/test_catalog.py)。
  须包含未知拓扑名称的失败测试，以及对缺少拟合数据的流体或 D-F 模式的显式拒绝测试。

### 5. 验证与数据要求

- 第三种 TPMS 拓扑需要完整的物理标定数据：水平集壁厚拟合、固体弯曲度（`chi`）、各流体 Nu 拟合与固定 D-F 的 CFD 系数表。
- 在[模型资源](model-resources.md)、[数据目录](data-catalog.md)与[能力范围](capabilities.md)中记录数据来源、适用范围及未支持组合。
- **物理验收由用户决定。**

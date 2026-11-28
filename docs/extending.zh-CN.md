# 贡献者扩展指南

[中文](extending.zh-CN.md) | [English](extending.md)

本指南用于快速定位扩展改动的起点、公开接口、下游使用方及对应测试。
路线对应 `main` 当前代码，涵盖 C++ 数值所有者、Python 绑定、保存数据与 GUI。
三阶段流程和物理不变量见[架构说明](architecture.zh-CN.md)，本地与 CI 检查命令见[验证指南](verification.md)。

## 快速路线索引

| 扩展问题 | 首先打开的文件 | 关键下游层级 | 现有测试 | 完整路线 |
| --- | --- | --- | --- | --- |
| 新增流体或 Nu 闭合 | [compute_config.py](../python/data_types/compute_config.py)（`FluidType`、`Sco2NuConfig`）——拥有公开流体名与带校验 Nu 配置 | [model_configs/](../python/model_configs/)、[generate_native_model_coefficients.py](../engineering/scripts/generate_native_model_coefficients.py)、[fluid_props.py](../python/physical_models/fluid_props.py)、[fluid_properties.cpp](../numerics/fluid_properties.cpp)、阶段 1／2 适配器、[builders_fluids.py](../python/applications/gui/ui/builders_fluids.py)、[stage_saved_models.hpp](../solver/stage_saved_models.hpp) | [test_fluid_properties.py](../tests/python/native/test_fluid_properties.py)、[test_fluid_props.py](../tests/python/models_tm1/test_fluid_props.py)、[test_nu_correlations.py](../tests/python/models_tm1/test_nu_correlations.py)、[test_sco2_nu_modes.py](../tests/python/test_sco2_nu_modes.py)、[test_catalog.py](../tests/python/models_tm1/test_catalog.py) | [新增流体或 Nu 闭合](#new-fluid-or-nu-closure) |
| 新增 GUI 面板或对话框 | 卡片：[builders_canvas.py](../python/applications/gui/ui/builders_canvas.py)（`build_canvas_area`）；页面：[quick_design_panel.py](../python/applications/gui/ui/quick_design_panel.py)（`QuickDesignPage`）；结果：[result_cache.py](../python/applications/gui/controllers/result_cache.py)（`ResultCache`） | [ui_builders.py](../python/applications/gui/ui/ui_builders.py)、[quick_design_panel.py](../python/applications/gui/ui/quick_design_panel.py)、[background_tasks.py](../python/applications/gui/ui/background_tasks.py)、[main_window.py](../python/applications/gui/ui/main_window.py)、[session_manager.py](../python/applications/gui/controllers/session_manager.py)、[OpenSpec `ui-*`](../openspec/specs/) | [conftest.py](../tests/python/conftest.py)、[test_quick_design_panel_wiring.py](../tests/python/test_quick_design_panel_wiring.py)、[test_optimize_panel_wiring.py](../tests/python/test_optimize_panel_wiring.py)、[test_result_snapshot_lifecycle.py](../tests/python/test_result_snapshot_lifecycle.py)、[test_ui_layout_hygiene.py](../tests/python/test_ui_layout_hygiene.py) | [新增 GUI 面板或对话框](#new-gui-panel-or-dialog) |
| 新增第三种 TPMS 拓扑 | [compute_config.py](../python/data_types/compute_config.py)（`TPMSType`）——配置与 GUI 校验共用的无 Qt 依赖支持拓扑列表 | [_native_values.py](../python/cpp_interface/_native_values.py)、[geometry.cpp](../geometry/geometry.cpp)、[generate_native_model_coefficients.py](../engineering/scripts/generate_native_model_coefficients.py)、[preparation_df.cpp](../preprocess/preparation_df.cpp)、[stage_saved_models.hpp](../solver/stage_saved_models.hpp)、[builders_domain.py](../python/applications/gui/ui/builders_domain.py) | [geometry_kernel_smoke.cpp](../tests/cpp/geometry_kernel_smoke.cpp)、[test_native_geometry.py](../tests/python/test_native_geometry.py)、[test_main_smoke.py](../tests/python/test_main_smoke.py)、[test_catalog.py](../tests/python/models_tm1/test_catalog.py) | [第三种 TPMS 拓扑](#third-tpms-topology) |

<a id="new-fluid-or-nu-closure"></a>

## 新增流体或 Nu 闭合

修改代码前先明确改动范围。
文中 `sCO2` 指超临界二氧化碳，`Sco2NuConfig` 是现行的超临界 CO2 Nu 模式与标定元数据配置数据类。

- **为现有流体新增 Nu 关联式**：此路线仍需改动带版本资源、原生 Nu 分发、阶段传输与 GUI 控件，但保持现有流体编号、输运／EOS 求值器、相态检查、能量方程及 D-F 流体表不变。
- **新增工质流体**：须在配置、Python 查询、原生枚举、输运／EOS 求值器及相态检查中同步加入新流体，并更新能量关系、D-F 范围、阶段适配器、保存模型解码与 GUI 控件。

### 1. 首先打开的文件（规则所有者）

首先打开 [python/data_types/compute_config.py](../python/data_types/compute_config.py)。
它拥有 `FluidType`、`FluidConfig`、`Sco2NuConfig` 与 `ComputeConfig.validate`，所有下游层级均以此为准。
随后依次查看 Python 分发（[fluid_props.py](../python/physical_models/fluid_props.py) 与 [nu_correlations.py](../python/physical_models/nu_correlations.py)）、带版本资源（[python/model_configs/](../python/model_configs/)）及原生计算核（[fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp) 与 [fluid_properties.cpp](../numerics/fluid_properties.cpp)）。

### 2. 公开接口

- **Python 配置与模型查询**：[python/data_types/compute_config.py](../python/data_types/compute_config.py) 中的 `ComputeConfig`、`FluidConfig`、`Sco2NuConfig`；[python/physical_models/fluid_props.py](../python/physical_models/fluid_props.py) 中的 `fluid_props.get` 与 `fluid_props.flow_model`；[python/physical_models/nu_correlations.py](../python/physical_models/nu_correlations.py) 中的 Nu 函数。
- **三阶段 Python API**：`prepare_case`（[python/preprocess/api.py](../python/preprocess/api.py)）、`run_case`（[python/solvers/api.py](../python/solvers/api.py)）、`evaluate`（[python/postprocess/api.py](../python/postprocess/api.py)）与 `compute`（[python/compute.py](../python/compute.py)）。
- **原生 C 与 C++ 接口**：[include/tpmshx/fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp) 中的 `enum class Fluid`、`PropertyEvaluator`、`fluid_nusselt` 与 `fluid_nusselt_ratio`。
- **C API 流体编码**：完整二维与三维 C API（[preparation_case_c_api.h](../include/tpmshx/preparation_case_c_api.h)、[full_2d_c_api.h](../include/tpmshx/full_2d_c_api.h)、[full_3d_c_api.h](../include/tpmshx/full_3d_c_api.h)）将 `uint32_t fluid` 编码为 `0..3`（`air`、`water`、`sco2`、`co2`）。
  [include/tpmshx/solver_c_api.h](../include/tpmshx/solver_c_api.h) 中的 `enum tpmshx_fluid` 仅用于 Quick Design（`0..2`，不含 `co2`）。

### 3. 下游使用方

下表按层级列出须同步修改的文件；标注 **（新增流体）** 的项仅在新增工质流体时需要改动。

| 层级 | 路径 | 关键符号 | 职责 |
| --- | --- | --- | --- |
| 配置与资源 | [python/data_types/compute_config.py](../python/data_types/compute_config.py) | `FluidType`、`FluidConfig`、`Sco2NuConfig`、`ComputeConfig.validate` | 公开流体名称、Nu 选项数据类与静态校验 |
| 配置与资源 | [python/model_configs/model_parameters.py](../python/model_configs/model_parameters.py) | `MODEL_VERSIONS`、`load_model_parameters`、`load_co2_coefficients`、`load_preparation_df_parameters` | `MODEL_VERSIONS` 的规范所有者与 JSON 格式校验 |
| 配置与资源 | [python/model_configs/](../python/model_configs/) | `model_parameters_v1.json`、`sco2_effective_nu.json`、`co2_segment2_v1.json`、`preparation_df_v1.json` | 带版本系数、运行范围与模型版本标识 |
| 配置与资源 | [engineering/scripts/generate_native_model_coefficients.py](../engineering/scripts/generate_native_model_coefficients.py) | `header`、`df_header`、`table` | 生成编译期 C++ 系数头文件 |
| Python 模型查询 | [python/physical_models/fluid_props.py](../python/physical_models/fluid_props.py) | `FLUIDS`、`FluidModel`、`get`、`flow_model`、`check_water_state` | 运行期按流体分发与相态检查 |
| Python 模型查询 | [python/physical_models/nu_correlations.py](../python/physical_models/nu_correlations.py) | `nu_from_Re`、`nu_vec`、`nu_water_topo`、`nu_sco2_topo`、`nu_sco2_selected`、`sco2_effective_nu_config`、`record_raw_nu_range`、`warn_sco2_nu_evidence` | 公开 Nu 封装与范围／证据通知 |
| Python 模型查询 | [python/physical_models/design_fluids.py](../python/physical_models/design_fluids.py) | `nu_re_window`、`fluid_nu`、`record_native_design_ranges` | Quick Design 与 GUI 预览的流体 Nu 与 `Re` 窗口 **（新增流体）** |
| Python 模型查询 | [python/physical_models/tpms_calc.py](../python/physical_models/tpms_calc.py)、[tpms_props.py](../python/physical_models/tpms_props.py) | `nu_re_window`、`model_h_coefficients`、`record_temperature_ranges` | 独立入口警告、Quick Design 与 GUI 预览共用的 `Re` 范围，以及 model-h 多项式与温度范围 **（新增流体）** |
| Python 原生适配器 | [python/cpp_interface/_native_preparation_case.py](../python/cpp_interface/_native_preparation_case.py)、[_native_preparation_3d.py](../python/cpp_interface/_native_preparation_3d.py)、[_native_properties.py](../python/cpp_interface/_native_properties.py) | `_FLUIDS`、`_Inlet`、`_Nu`、`pack_input`、`empirical`、`nu_inputs`、`nusselt` | C ABI 流体编号、二维／三维输入结构与直接物性／Nu 调用 |
| Python 原生绑定 | [native_preparation.py](../python/cpp_interface/native_preparation.py)、[inlet_properties.py](../python/cpp_interface/inlet_properties.py)、[preparation_host.py](../python/cpp_interface/preparation_host.py) | `pack_input`、`pack_volume_input`、`query_values`、`PreparationCacheBridge`、`pack_nu`、`pack_saved_resources` | 完整准备与独立入口查询的 ABI 输入、独立输出、缓存缓冲区及释放 |
| Python 准备阶段 | [二维宿主](../python/preprocess/two_d/preparation.py)、[三维宿主](../python/preprocess/three_d/preparation.py)、[共享回调](../python/preprocess/preparation.py) | `prepare_case`、`PreparationCache`、`model_metadata` | 构造 `CaseData`，选择缓存条目并记录警告 |
| Quick Design 准备 | [准备宿主](../python/preprocess/quick_design.py)、[原生绑定](../python/cpp_interface/quick_preparation.py) | `prepare_quick_design`、`pressure_fractions`、`run_preparation` | 宿主选择流体模型并组装 `CaseData`。绑定打包输入，在释放原生结果前复制准备场。 |
| Python 求解宿主与原生适配器 | [python/solvers/full_2d.py](../python/solvers/full_2d.py)、[full_3d.py](../python/solvers/full_3d.py)、[python/cpp_interface/full_2d_stage.py](../python/cpp_interface/full_2d_stage.py)、[full_3d_stage.py](../python/cpp_interface/full_3d_stage.py) | `saved_inputs`、`prepare_stage`、`pack_saved`、`validate_saved_case`、`select_sco2_nu`、`pack_input`、`pack_saved_case`、`run_case` | 阶段 2 流体编号打包、Nu 选项与保存工况执行 |
| C++ 原生层 | [include/tpmshx/fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp)、[property_kernels.hpp](../numerics/property_kernels.hpp)、[numerics/fluid_properties.cpp](../numerics/fluid_properties.cpp) | `enum class Fluid`、`uses_co2_eos`、`model_h_coefficients`、`nusselt_floor`、`PropertyEvaluator`、`fluid_nusselt_ratio`、`tpmshx::empirical_point`、`tpmshx::nu_point` | 核心 C++ 物性、EOS 与 Nu 计算 |
| C++ 原生层 | [preprocess/preparation_properties.hpp](../preprocess/preparation_properties.hpp)、[preparation_properties.cpp](../preprocess/preparation_properties.cpp)、[preparation_property_points.cpp](../preprocess/preparation_property_points.cpp)、[property_c_api.cpp](../preprocess/property_c_api.cpp) | `Empirical`、`NuRoute`、`empirical_range`、`empirical`、`nu_inputs`、`nusselt`、`tpmshx_preparation_empirical_v1`、`tpmshx_preparation_nu_inputs_v1`、`tpmshx_preparation_nu_v1` | 前处理物性／Nu 校验与 C 边界范围门禁 |
| C++ 原生层 | [preprocess/preparation_case.cpp](../preprocess/preparation_case.cpp)、[preparation_df.cpp](../preprocess/preparation_df.cpp)、[preparation_df_corrections.cpp](../preprocess/preparation_df_corrections.cpp) | `query_inlet_properties`、`prepare_case_2d`、`prepare_case_3d`、`df_experiment_scope`、`df_select` | 原生二维／三维准备与 D-F 实验适用范围 **（新增流体）** |
| C++ 原生层 | [solver/enthalpy_eos.cpp](../solver/enthalpy_eos.cpp)、[closure_ranges.hpp](../solver/closure_ranges.hpp)、[full_2d.cpp](../solver/full_2d.cpp)、[full_3d.cpp](../solver/full_3d.cpp) | `EnthalpyEOS`、`fluid_name`、`property`、`nu` | 求解器 EOS 状态、范围记录与二维／三维流动热学循环 **（新增流体）** |
| C++ 原生层 | [include/tpmshx/stages.hpp](../include/tpmshx/stages.hpp)、[solver/stage_run.cpp](../solver/stage_run.cpp)、[stage_run_3d.cpp](../solver/stage_run_3d.cpp)、[full_3d_c_api.cpp](../solver/full_3d_c_api.cpp)、[stage_capture_2d.cpp](../solver/stage_capture_2d.cpp)、[stage_capture_3d.cpp](../solver/stage_capture_3d.cpp) | `fluid_text`、保存态流体编号检查与捕获元数据 | 原生 SDK 与保存态二维／三维边界校验 **（新增流体）** |
| C++ 原生层 | [solver/quick_design_driver.cpp](../solver/quick_design_driver.cpp)、[quick_design_run.cpp](../solver/quick_design_run.cpp)、[solver_c_api.cpp](../solver/solver_c_api.cpp) | `enum tpmshx_fluid` 检查与 Quick Design 流体分发 | Quick Design 求解支持或显式拒绝 **（新增流体）** |
| GUI 与保存数据 | [python/applications/gui/ui/builders_fluids.py](../python/applications/gui/ui/builders_fluids.py)、[window_config.py](../python/applications/gui/ui/window_config.py)、[main_window.py](../python/applications/gui/ui/main_window.py) | `build_fluid_sections`、`refresh_fluid_model_visibility`、`combo_fluidA`、`combo_fluidB`、`combo_sco2_nu_mode`、`_parse_fluid_label`、`sco2_nu_from_window`、`_FLUID_DEFAULTS` | GUI 流体／Nu 控件、默认入口参数与配置解析 |
| GUI 与保存数据 | [python/applications/gui/ui/mixins/fluid_input.py](../python/applications/gui/ui/mixins/fluid_input.py)、[case_files.py](../python/applications/gui/ui/case_files.py)、[command_palette.py](../python/applications/gui/ui/command_palette.py)、[sensitivity.py](../python/applications/gui/ui/sensitivity.py) | `CaseFiles.PRESET_COMBOS`、`validate_preset`、`set_sco2_nu_parameters`、`load_sco2_nu_parameters` | 自动填充预览、预设读写、命令面板与仅支持空气的灵敏度检查 |
| GUI 与保存数据 | [python/physical_models/catalog.py](../python/physical_models/catalog.py)、[solver/stage_saved_models.hpp](../solver/stage_saved_models.hpp)、[python/file_io/case_io.py](../python/file_io/case_io.py)、[result_io.py](../python/file_io/result_io.py) | `resolve_model`、`validate_saved_models`、`save_case`、`load_case`、`save_result`、`load_result` | 保存工况模型解析（`catalog.py` 从 `model_parameters.py` 导入 `MODEL_VERSIONS`）与 YAML／HDF5 持久化 |

- **重编原生库**：修改 C++ 代码或编译期模型资源后，使用 [engineering/scripts/build_native_dependencies.py](../engineering/scripts/build_native_dependencies.py) 重新构建并发布受影响的原生库。然后重启 Python 进程。详见[C++ 接入说明](cpp-migration.zh-CN.md#native-preparation-core)。
- **保存数据规则**：遵守[三模块数据契约](contracts/three_module_v1/README.zh-CN.md)。已有保存工况与结果文件必须保留各自记录的模型版本与参数，不得静默替换。
- 独立入口计算使用流体注册表中的规范名称选择雷诺数范围，并据此给出警告。
- 可选的 GUI 流体选择框缺失或为空时，默认使用空气。非空标签必须对应受支持的流体。几何和流体预览会检查两侧的选择。仅支持空气的灵敏度扫描会检查 A 侧流体，若标签无效，则清除先前的热图。

### 4. 需要扩展的现有测试

- **原生物性与 Nu 检查**：[tests/python/native/test_fluid_properties.py](../tests/python/native/test_fluid_properties.py) 与 [tests/cpp/fluid_properties_smoke.cpp](../tests/cpp/fluid_properties_smoke.cpp)。
- **Python 模型与 Nu 契约**：[tests/python/models_tm1/test_fluid_props.py](../tests/python/models_tm1/test_fluid_props.py)、[tests/python/models_tm1/test_nu_correlations.py](../tests/python/models_tm1/test_nu_correlations.py)、[tests/python/native_adapters/test_fluid_type_validation.py](../tests/python/native_adapters/test_fluid_type_validation.py) 与 [tests/python/test_sco2_nu_modes.py](../tests/python/test_sco2_nu_modes.py)。
- **目录、配置与阶段准备**：[tests/python/models_tm1/test_catalog.py](../tests/python/models_tm1/test_catalog.py)、[tests/python/test_compute_config_roundtrip.py](../tests/python/test_compute_config_roundtrip.py)、[tests/python/preprocess/test_2d_tm1.py](../tests/python/preprocess/test_2d_tm1.py)、[tests/python/preprocess/test_3d_tm1.py](../tests/python/preprocess/test_3d_tm1.py) 与 [tests/python/io_tm1/test_case_io.py](../tests/python/io_tm1/test_case_io.py)。
- **GUI 流体输入接线**：[tests/python/test_fluid_input.py](../tests/python/test_fluid_input.py)。

### 5. 验证与数据要求

- 新增流体或 Nu 闭合进入生产使用前，必须提供 CFD 或实验物理证据。
- 原始数据保留在本地 `data/raw_data/` 且不提交到 Git。
  在[模型资源](model-resources.md)和[数据目录](data-catalog.md)记录来源与适用范围。
- 明确声明温度、压力、`Re` 与 `Pr` 范围，供 [python/postprocess/api.py](../python/postprocess/api.py)（由 [postprocess/result_stage.cpp](../postprocess/result_stage.cpp) 实现）中的 `evaluate_applicability` 与 `evaluate_qualification` 检查。
- 在[能力范围](capabilities.md)中说明已支持能力与当前限制。
- **物理验收由用户决定。** 单元测试、原生冒烟测试或 CI 通过不代表物理模型已获准用于工程设计。

<a id="new-gui-panel-or-dialog"></a>

## 新增 GUI 面板或对话框

修改代码前先选择将功能作为工作台卡片还是独立对话框。
工作台卡片共享主画布生命周期。
独立对话框自行管理窗口与后台工作线程状态。

### 1. 首先打开的文件（规则所有者）

- **工作台卡片**：首先打开 [python/applications/gui/ui/builders_canvas.py](../python/applications/gui/ui/builders_canvas.py)（`build_canvas_area`），因为它构建并将全部卡片注册到 `window._canvas_cards`。
  随后打开 [python/applications/gui/ui/ui_builders.py](../python/applications/gui/ui/ui_builders.py)（`build_ui`、`build_param_tabs`），查看左侧导航栏、顶栏与右侧检查器抽屉。
- 在[quick_design_panel.py](../python/applications/gui/ui/quick_design_panel.py) 中使用 `QuickDesignPage` 管理快速设计的输入、工作线程和结果。切换页面后可以返回查看同一任务。
  其他窗口级对话框见 [python/applications/gui/ui/shell_dialogs.py](../python/applications/gui/ui/shell_dialogs.py)（`ShellDialogs`）。
- **已发布结果**：打开 [python/applications/gui/controllers/result_cache.py](../python/applications/gui/controllers/result_cache.py)（`ResultCache`），它是已发布二维与三维 `ComputeResult` 的唯一所有者。

### 2. 公开接口与边界规则

- **Qt 边界规则**：仅允许在 `python/applications/gui/ui/`、`python/applications/gui/controllers/` 和 GUI 入口 [python/applications/gui/main.py](../python/applications/gui/main.py) 中导入 `PySide6`。根目录 [main.py](../main.py) 选择模式，GUI 路由导入 Qt。
  唯一的例外是离屏 GUI 冒烟工具 `python/development/runs/_smoke_boot.py` 和 `python/development/runs/smokes/`。
  下层模块（`data_types/`、`physical_models/`、`preprocess/`、`solvers/`、`postprocess/`、`file_io/`、`run_control/`、`cpp_interface/`）必须保持无 Qt 依赖。
- 在[配置字段](../python/data_types/compute_config.py)上记录物理量的符号、存储单位、适用维度及范围来源。
  默认值由字段定义，实际限值由相应模型或校验器执行。
- 在 [`CONFIG_FIELDS`](../python/applications/gui/ui/window_config.py) 中为每个新增配置叶字段指定一种用途。
  可选值为 `edited`（界面编辑）、`derived`（派生或固定）、`api-only`（仅 API）和 `archive`（存档）。将可编辑字段绑定到相应控件。
  算例表单从绑定表取得单位、默认值和校验顺序。修改后运行[参数映射检查](../tests/python/test_compute_config_roundtrip.py)。
- **单一结果所有者**：[python/applications/gui/ui/field_results.py](../python/applications/gui/ui/field_results.py)（`FieldResults.publish`）将隔离后的 `ComputeResult` 发布到 `ResultCache`（`set_result`、`get_result`、`has_results`、`mark_drawn`）。
  不得在 `Main_Menu` 上另存结果字段副本。
  例如 [python/applications/gui/ui/plot_2d_results.py](../python/applications/gui/ui/plot_2d_results.py)（`finalize_plots`、`plot_temperature_3panel`、`_draw_zone_overlays`）中的二维分区叠加线已直接从 `ResultCache` 读取 `result.zones`。
- **后台工作线程与关闭保护**：繁重计算在后台工作线程执行。
  控件更新、Matplotlib 与 OpenGL 保持在 GUI 线程执行。
  页面通过 `is_idle()` 报告任务状态。只有终态已送达且线程已退出，窗口才允许关闭、重启或更改 CPU 设置。
  在 `Main_Menu.closeEvent`（[python/applications/gui/ui/main_window.py](../python/applications/gui/ui/main_window.py)）中安全取消活动工作线程。

### 3. 下游使用方

下表按层级列出可能受影响的 GUI 与控制器文件。

| 层级 | 路径 | 关键符号 | 职责 |
| --- | --- | --- | --- |
| 界面构建 | [python/applications/gui/ui/ui_builders.py](../python/applications/gui/ui/ui_builders.py)、[builders_canvas.py](../python/applications/gui/ui/builders_canvas.py) | `build_ui`、`build_param_tabs`、`build_page_zones`、`refresh_group_badges`、`build_canvas_area`、`_build_canvas_content`、`refresh_field_controls` | 顶栏、左侧参数分组、工作台卡片与内嵌优化面板 |
| 界面构建 | [python/applications/gui/ui/field_factory.py](../python/applications/gui/ui/field_factory.py)、[theme_manager.py](../python/applications/gui/ui/theme_manager.py)、[responsive.py](../python/applications/gui/ui/responsive.py) | `FieldFactory`、`ThemeManager`、`ResponsiveRow` | 设计令牌、主题控件与响应式卡片堆叠 |
| 页面与任务 | [single_run.py](../python/applications/gui/ui/single_run.py), [optimize_panel.py](../python/applications/gui/ui/optimize_panel.py), [quick_design_panel.py](../python/applications/gui/ui/quick_design_panel.py) | `SingleRun`、`OptimizationPage`、`QuickDesignPage` | 启动、取消、终态送达与任务退出 |
| 对话框与工作线程 | [python/applications/gui/ui/background_tasks.py](../python/applications/gui/ui/background_tasks.py)、[python/applications/gui/ui/main_window.py](../python/applications/gui/ui/main_window.py) | `has_active_tasks`、`Main_Menu`、`Main_Menu.closeEvent` | 活动任务互斥锁、CPU 控件门控与安全退出 |
| 控制器 | [python/applications/gui/controllers/result_cache.py](../python/applications/gui/controllers/result_cache.py)、[session_manager.py](../python/applications/gui/controllers/session_manager.py) | `ResultCache`、`SessionManager`、`SCHEMA_VERSION`、`load_session`、`save_session`、`load_user_presets`、`save_user_presets` | 已发布结果缓存与会话／预设 JSON 模式兼容 |
| 控制器 | [python/applications/gui/controllers/signal_router.py](../python/applications/gui/controllers/signal_router.py)、[compute_orchestrator.py](../python/applications/gui/controllers/compute_orchestrator.py)、[user_storage.py](../python/applications/gui/controllers/user_storage.py) | `SignalRouter`、`ComputeOrchestrator` | 退出时统一断开信号、主计算线程池及平台数据路径／外观文件 |
| 导航与结果 | [python/applications/gui/ui/workbench.py](../python/applications/gui/ui/workbench.py)、[field_results.py](../python/applications/gui/ui/field_results.py)、[plot_2d_results.py](../python/applications/gui/ui/plot_2d_results.py) | `Workbench.canvas_tab_availability`、`update_tab_visibility`、`FieldResults.publish`、`finalize_plots`、`plot_temperature_3panel`、`_draw_zone_overlays` | 卡片可见性路由、结果发布与基于缓存的二维绘图 |
| 导航与结果 | [python/applications/gui/ui/shell_shortcuts.py](../python/applications/gui/ui/shell_shortcuts.py)、[builders_sidebar.py](../python/applications/gui/ui/builders_sidebar.py)、[command_palette.py](../python/applications/gui/ui/command_palette.py) | `refresh_result_sidebar` | 按需更新快捷键、底部读数条与命令面板入口 |
| 文件 | [case_files.py](../python/applications/gui/ui/case_files.py), [result_export.py](../python/applications/gui/ui/result_export.py) | `CaseFiles`、`ResultExport` | 算例、预设、工作区会话、结果和图表导出 |

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
  同时运行 `python -m tm1.development.runs.tools.audit_import_graph --fail-on-violations`。
- 遵守[测试范围规则](collaboration.zh-CN.md#测试范围)：测试状态变化、公开契约与资源清理，不测试离屏像素坐标或固定边距数值。

### 5. 验证与数据要求

- 按[验证指南](verification.md)运行无头 GUI 测试、布局健康检查与导入分层检查。
- 界面行为变更时同步更新受影响 `openspec/specs/ui-*/` 目录下的 `spec.md` 与 `spec.en.md`。
- 无头 CI 不替代 macOS 与 Windows 实机界面和 OpenGL 三维渲染验收，见[Qt 渲染说明](verification.md#qt-rendering)。
- 尚未定案的交互流程或界面契约变更，合并前须先由用户批准。

<a id="third-tpms-topology"></a>

## 第三种 TPMS 拓扑（简明路线）

新增第三种 TPMS 拓扑，在计入系数、标定数据、GUI 控件、测试与文档之前，至少需改动 22 个核心 C++ 与 Python 分发文件。
请在获得经批准的标定数据后再开始实施。
务必确保未支持的拓扑在每个入口显式报错。

### 1. 首先打开的文件（规则所有者）

首先打开 [python/data_types/compute_config.py](../python/data_types/compute_config.py)。
它定义 `TPMSType`，是 `GeometryConfig` 与 GUI 校验（`_selected_topology`）共同读取的无 Qt 依赖支持拓扑列表。
随后打开 [include/tpmshx/fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp)（`enum class Topology`）与 [geometry/geometry.cpp](../geometry/geometry.cpp)（`phi_grid`、`topology_row`、`calibration`），查看原生几何内核。

### 2. 公开接口

- **Python ABI 映射**：在 [python/cpp_interface/_native_values.py](../python/cpp_interface/_native_values.py) 中同步更新 `TOPOLOGIES`、`TOPOLOGY_CODES` 与 `geometry_topology`，使其与 C++ 枚举顺序一致。
- **原生 C 与 C++ 枚举**：更新 `enum class Topology`（[include/tpmshx/fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp)）、`enum tpmshx_geometry_topology_v1`（[include/tpmshx/geometry_c_api.h](../include/tpmshx/geometry_c_api.h)）、`enum tpmshx_topology`（[include/tpmshx/solver_c_api.h](../include/tpmshx/solver_c_api.h)）及 [include/tpmshx/stages.hpp](../include/tpmshx/stages.hpp) 中的 `topology_text`。

### 3. 下游使用方

下表列出须修改的核心分发、模型资源、GUI 与快速设计文件。

| 层级 | 路径 | 关键符号 | 职责 |
| --- | --- | --- | --- |
| 配置与资源 | [python/data_types/compute_config.py](../python/data_types/compute_config.py)、[python/model_configs/model_parameters.py](../python/model_configs/model_parameters.py) | `TPMSType`、`load_model_parameters`、`load_co2_coefficients`、`load_preparation_df_parameters` | 支持拓扑列表与 JSON 资源格式校验 |
| 配置与资源 | [python/model_configs/model_parameters_v1.json](../python/model_configs/model_parameters_v1.json)、[preparation_df_v1.json](../python/model_configs/preparation_df_v1.json)、[co2_segment2_v1.json](../python/model_configs/co2_segment2_v1.json)、[python/physical_models/df_surrogate/_prebuilt/cfd_full_core_3cell_fixed_v2.csv](../python/physical_models/df_surrogate/_prebuilt/cfd_full_core_3cell_fixed_v2.csv) | 拓扑系数行与固定 D-F 网格节点 | 几何、Nu、CO2 与固定 D-F 数据表 |
| 配置与资源 | [engineering/scripts/generate_native_model_coefficients.py](../engineering/scripts/generate_native_model_coefficients.py) | `table`、`header`、`df_header` | 固定生成的 C++ 拓扑行顺序 |
| Python 模型查询 | [python/physical_models/tpms_geometry.py](../python/physical_models/tpms_geometry.py)、[nu_correlations.py](../python/physical_models/nu_correlations.py)、[co2_correlations.py](../python/physical_models/co2_correlations.py)、[df_surrogate/full_core_3cell_fixed_v2.py](../python/physical_models/df_surrogate/full_core_3cell_fixed_v2.py) | `_compute_geometry_cached`、`compute_geometry_fields`、`sco2_nu_parameters`、`_sco2_nu`、`_topology`、`FullCore3CellFixedDFV2` | Python 几何错误文案（`tpms_geometry.py` 已按 `TOPOLOGIES` 校验），以及 Nu、CO2 与固定 D-F 分发 |
| Python 求解宿主与原生适配器 | [python/solvers/full_2d.py](../python/solvers/full_2d.py)、[full_3d.py](../python/solvers/full_3d.py)、[python/cpp_interface/_native_values.py](../python/cpp_interface/_native_values.py)、[_native_df.py](../python/cpp_interface/_native_df.py)、[preparation_host.py](../python/cpp_interface/preparation_host.py)、[full_2d_stage.py](../python/cpp_interface/full_2d_stage.py)、[full_3d_stage.py](../python/cpp_interface/full_3d_stage.py) | `TOPOLOGIES`、`TOPOLOGY_CODES`、`geometry_topology`、`experiment_scope`、`selection`、`pack_saved_resources`、`prepare_stage`、`select_sco2_nu`、`pack_input` | ABI 编码映射、D-F 适用域打包与 sCO2 `alpha` 选择 |
| C++ 原生层 | [geometry/geometry.cpp](../geometry/geometry.cpp)、[geometry_c_api.cpp](../geometry/geometry_c_api.cpp)、[numerics/fluid_properties.cpp](../numerics/fluid_properties.cpp) | `topology_row`、`phi_grid`、`calibration`、`tpmshx::nu_point` | 水平集场构造、几何 C API 与 Nu 行索引 |
| C++ 原生层 | [preprocess/preparation_df.cpp](../preprocess/preparation_df.cpp)、[preparation_df_corrections.cpp](../preprocess/preparation_df_corrections.cpp)、[preparation_case.cpp](../preprocess/preparation_case.cpp)、[property_c_api.cpp](../preprocess/property_c_api.cpp)、[quick_design_prepare_v2.cpp](../preprocess/quick_design_prepare_v2.cpp) | `topology_check`、`df_experiment_scope`、`df_select`、`geometry_index` | 固定 D-F 限制、实验适用域、前处理缓存与快速设计准备 |
| C++ 原生层 | [solver/solver_c_api.cpp](../solver/solver_c_api.cpp)、[full_2d.cpp](../solver/full_2d.cpp)、[full_3d_c_api.cpp](../solver/full_3d_c_api.cpp)、[stage_run.cpp](../solver/stage_run.cpp)、[quick_design_run.cpp](../solver/quick_design_run.cpp)、[closure_ranges.hpp](../solver/closure_ranges.hpp)、[stage_capture_2d.cpp](../solver/stage_capture_2d.cpp)、[stage_capture_3d.cpp](../solver/stage_capture_3d.cpp) | 拓扑范围检查、Quick Design 选择器与捕获拓扑名 | 求解执行、范围记录与结果捕获 |
| 保存数据 | [solver/stage_saved_models.hpp](../solver/stage_saved_models.hpp)、[python/physical_models/catalog.py](../python/physical_models/catalog.py) | `validate_saved_models`、`resolve_model` | 保存模型解码；已有 Diamond 与 Gyroid 归档保持原有标识 |
| GUI | [python/applications/gui/ui/builders_domain.py](../python/applications/gui/ui/builders_domain.py)、[quick_design_panel.py](../python/applications/gui/ui/quick_design_panel.py)、[window_config.py](../python/applications/gui/ui/window_config.py)、[sensitivity.py](../python/applications/gui/ui/sensitivity.py) | `combo_tpms`、`combo_qd_cell_topo`（局部 `combo_cell_topo`）、`le_qd_topo`、`_selected_topology`、`SensitivityDialog._collect_fixed_params` | GUI 拓扑控件（`window_config.py` 与 `sensitivity.py` 已按 `TPMSType` 校验） |
| 应用层 | [python/applications/design/select.py](../python/applications/design/select.py)、[python/applications/optimization/multi_condition.py](../python/applications/optimization/multi_condition.py) | `NODES` | Quick Design 枚举网格与多工况 Nu 来源筛选 |

- **重编原生库**：修改 C++ 代码或编译期模型资源后，使用 [engineering/scripts/build_native_dependencies.py](../engineering/scripts/build_native_dependencies.py) 重新构建并发布全部四个原生库。然后重启 Python 进程。
- 保存工况的二维 ABI 按 Diamond、Gyroid 的顺序存储两个 sCO₂ Nu 乘数。添加第三个乘数前，须先扩展这个定长数组。

### 4. 需要扩展的现有测试

- **原生几何与物性**：[tests/cpp/geometry_kernel_smoke.cpp](../tests/cpp/geometry_kernel_smoke.cpp)、[tests/cpp/geometry_c_smoke.c](../tests/cpp/geometry_c_smoke.c)、[tests/python/test_native_geometry.py](../tests/python/test_native_geometry.py) 与 [tests/python/native/test_fluid_properties.py](../tests/python/native/test_fluid_properties.py)。
- **配置、目录与 GUI 选择**：[tests/python/test_main_smoke.py](../tests/python/test_main_smoke.py)、[tests/python/test_compute_config_roundtrip.py](../tests/python/test_compute_config_roundtrip.py) 与 [tests/python/models_tm1/test_catalog.py](../tests/python/models_tm1/test_catalog.py)。
  须新增未知拓扑名称的失败测试。
  同时测试缺少拟合数据的流体或 D-F 模式会显式报错。

### 5. 验证与数据要求

- 第三种 TPMS 拓扑需要完整的物理标定数据：水平集壁厚拟合、固体弯曲度（`chi`）、各流体 Nu 拟合与固定 D-F 的 CFD 系数表。
- 在[模型资源](model-resources.md)、[数据目录](data-catalog.md)与[能力范围](capabilities.md)中记录数据来源、适用范围及未支持组合。
- **物理验收由用户决定。**

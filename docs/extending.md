# Contributor extension guide

[中文](extending.zh-CN.md) | [English](extending.md)

Use this guide to find where an extension starts, which interfaces it changes, and which checks apply.
It maps the code on `main` across C++ numerical owners, Python bindings, saved data, and the GUI.
See [architecture](architecture.md) for the three-stage flow and physical invariants, and [verification](verification.en.md) for local and CI commands.

## Quick route index

| Question | First owner and interface | Downstream consumers | Existing tests | Route |
| --- | --- | --- | --- | --- |
| Add a fluid or Nu closure | [compute_config.py](../python/data_types/compute_config.py) (`FluidType`, `Sco2NuConfig`), [fluid_props.py](../python/physical_models/fluid_props.py) (`FLUIDS`, `get`), [nu_correlations.py](../python/physical_models/nu_correlations.py), [fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp) (`Fluid`), [fluid_properties.cpp](../numerics/fluid_properties.cpp) (`fluid_nusselt_ratio`, `nu_point`) | [model_configs/](../python/model_configs/), [generate_native_model_coefficients.py](../engineering/scripts/generate_native_model_coefficients.py), [inlet_properties.py](../python/cpp_interface/inlet_properties.py), [preparation_host.py](../python/cpp_interface/preparation_host.py), [full_2d_stage.py](../python/cpp_interface/full_2d_stage.py), [full_3d_stage.py](../python/cpp_interface/full_3d_stage.py), [builders_fluids.py](../python/applications/gui/ui/builders_fluids.py), [stage_saved_models.hpp](../solver/stage_saved_models.hpp) | [test_fluid_properties.py](../tests/python/native/test_fluid_properties.py), [test_fluid_props.py](../tests/python/test_fluid_props.py), [test_nu_correlations.py](../tests/python/test_nu_correlations.py), [test_sco2_nu_modes.py](../tests/python/test_sco2_nu_modes.py), [test_catalog.py](../tests/python/models_tm1/test_catalog.py) | [New fluid or Nu closure](#new-fluid-or-nu-closure) |
| Add a GUI panel or dialog | [ui_builders.py](../python/applications/gui/ui/ui_builders.py) (`build_ui`), [builders_canvas.py](../python/applications/gui/ui/builders_canvas.py) (`build_canvas_area`), [optimize_ui.py](../python/applications/gui/ui/mixins/optimize_ui.py) (`_open_quick_design`), [quick_design_panel.py](../python/applications/gui/ui/quick_design_panel.py) (`build_quick_design_dialog`), [result_cache.py](../python/applications/gui/controllers/result_cache.py) (`ResultCache`) | [main.py](../python/applications/gui/main.py), [tab_view.py](../python/applications/gui/ui/mixins/tab_view.py), [run_results.py](../python/applications/gui/ui/mixins/run_results.py), [plot_2d_results.py](../python/applications/gui/ui/plot_2d_results.py), [window_config.py](../python/applications/gui/ui/window_config.py), [OpenSpec `ui-*`](../openspec/specs/) | [conftest.py](../tests/python/conftest.py), [test_quick_design_panel_wiring.py](../tests/python/test_quick_design_panel_wiring.py), [test_optimize_panel_wiring.py](../tests/python/test_optimize_panel_wiring.py), [test_result_snapshot_lifecycle.py](../tests/python/test_result_snapshot_lifecycle.py), [test_ui_layout_hygiene.py](../tests/python/test_ui_layout_hygiene.py) | [New GUI panel or dialog](#new-gui-panel-or-dialog) |
| Add a third TPMS topology | [compute_config.py](../python/data_types/compute_config.py) (`TPMSType`), [fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp) (`Topology`), [geometry.cpp](../geometry/geometry.cpp) (`phi_grid`, `topology_row`) | [_native_values.py](../python/cpp_interface/_native_values.py) (`TOPOLOGIES`), [generate_native_model_coefficients.py](../engineering/scripts/generate_native_model_coefficients.py) (`table`), [stage_saved_models.hpp](../solver/stage_saved_models.hpp), [preparation_df.cpp](../preprocess/preparation_df.cpp), [window_config.py](../python/applications/gui/ui/window_config.py) (`_selected_topology`), [sensitivity.py](../python/applications/gui/ui/sensitivity.py) | [geometry_kernel_smoke.cpp](../tests/cpp/geometry_kernel_smoke.cpp), [test_native_geometry.py](../tests/python/test_native_geometry.py), [test_main_smoke.py](../tests/python/test_main_smoke.py), [test_catalog.py](../tests/python/models_tm1/test_catalog.py) | [Third TPMS topology](#third-tpms-topology) |

<a id="new-fluid-or-nu-closure"></a>

## New fluid or Nu closure

First decide if you add a new Nu law for an existing fluid or add a new working fluid.

- **New Nu law for an existing fluid (smaller scope)**: Keep `FluidType` and `enum class Fluid` unchanged. Keep existing transport properties, phase checks, and energy equations. Update the versioned model resource, config option, Nu wrappers, native `nu_point`, stage transport, and GUI selector.
- **New working fluid (full scope)**: Add the fluid across Python types, native enums, transport or EOS evaluators, and phase checks. Also update energy relations, D-F scope, saved-case resolution, and GUI choices.

### 1. First file to open (rule owner)

Start with the configuration type, Python dispatch, model resource, and native property kernel in this order:

1. Open [python/data_types/compute_config.py](../python/data_types/compute_config.py).
   For a new fluid, extend `FluidType` and do a check of `FluidConfig` and `ComputeConfig.validate`.
   For a new Nu law, add or extend a typed settings dataclass such as `Sco2NuConfig`.
2. Open [python/physical_models/fluid_props.py](../python/physical_models/fluid_props.py) and [python/physical_models/nu_correlations.py](../python/physical_models/nu_correlations.py).
   `fluid_props.py` owns `FLUIDS`, `FluidModel`, `get`, `flow_model`, and `check_water_state`.
   `nu_correlations.py` owns the public Nu wrappers (`nu_from_Re`, `nu_vec`, `nu_water_topo`, `nu_sco2_topo`, `nu_sco2_selected`, `sco2_effective_nu_config`) and warning helpers (`record_raw_nu_range`, `warn_sco2_nu_evidence`).
3. Open [python/model_configs/](../python/model_configs/) and [engineering/scripts/generate_native_model_coefficients.py](../engineering/scripts/generate_native_model_coefficients.py).
   Store coefficients, ranges, and version IDs in versioned JSON files (`model_parameters_v1.json`, `sco2_effective_nu.json`, `co2_segment2_v1.json`, `preparation_df_v1.json`).
   Validate the schema in [python/model_configs/model_parameters.py](../python/model_configs/model_parameters.py) (`MODEL_VERSIONS`, `load_model_parameters`, `load_co2_coefficients`, `load_preparation_df_parameters`).
   Generate native C++ constants in `generate_native_model_coefficients.py` (`header`, `df_header`, `table`).
4. Open [include/tpmshx/fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp) and [numerics/fluid_properties.cpp](../numerics/fluid_properties.cpp).
   `fluid_properties.hpp` defines `enum class Fluid`, `uses_co2_eos`, `model_h_coefficients`, `nusselt_floor`, `fluid_nusselt`, `fluid_nusselt_ratio`, and `PropertyEvaluator`.
   `fluid_properties.cpp` contains `PropertyEvaluator::evaluate`, `PropertyEvaluator::transport`, `fluid_nusselt_ratio`, `preparation::empirical_point`, and `preparation::nu_point`.
   Also inspect [preprocess/preparation_properties.hpp](../preprocess/preparation_properties.hpp) (`enum class Empirical`, `enum class NuRoute`).

### 2. Public interface

- **Python configuration and model queries**: `ComputeConfig`, `FluidConfig`, `Sco2NuConfig` in [python/data_types/compute_config.py](../python/data_types/compute_config.py); `fluid_props.get` and `fluid_props.flow_model` in [python/physical_models/fluid_props.py](../python/physical_models/fluid_props.py); Nu functions in [python/physical_models/nu_correlations.py](../python/physical_models/nu_correlations.py).
- **Three-stage Python APIs**: `prepare_case` ([python/preprocess/api.py](../python/preprocess/api.py)), `run_case` ([python/solvers/api.py](../python/solvers/api.py)), `evaluate` ([python/postprocess/api.py](../python/postprocess/api.py)), and `compute` ([python/compute.py](../python/compute.py)).
- **Native C and C++ interfaces**: `enum class Fluid`, `PropertyEvaluator`, `fluid_nusselt`, and `fluid_nusselt_ratio` in [include/tpmshx/fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp); `tpmshx_query_inlet_properties_v2` in [include/tpmshx/preparation_case_c_api.h](../include/tpmshx/preparation_case_c_api.h); `enum tpmshx_fluid` in [include/tpmshx/solver_c_api.h](../include/tpmshx/solver_c_api.h).

### 3. Downstream consumers

#### Native preparation and solver transport

- **C ABI layouts and property adapters**: Update `_FLUIDS`, `_Inlet`, and `_Nu` in [python/cpp_interface/_native_preparation_case.py](../python/cpp_interface/_native_preparation_case.py).
  Update `empirical`, `nu_inputs`, and `nusselt` in [python/cpp_interface/_native_properties.py](../python/cpp_interface/_native_properties.py).
- **Standalone inlet query**: Update `inlet_query` in [python/cpp_interface/inlet_properties.py](../python/cpp_interface/inlet_properties.py) when packing fluid IDs, pressure rules, or Nu selections for `tpmshx_query_inlet_properties_v2`.
- **Shared preparation host**: Update `validate_fluid_type`, `observe_range`, `pack_nu`, `pack_saved_resources`, `model_metadata`, and `PreparationCacheBridge` in [python/cpp_interface/preparation_host.py](../python/cpp_interface/preparation_host.py).
- **Full 2D and 3D stage adapters**: Update fluid ID packing, Nu options, and saved-case checks in [python/cpp_interface/full_2d_stage.py](../python/cpp_interface/full_2d_stage.py) (`prepare_stage`, `pack_saved`, `run_case`).
  Apply matching updates in [python/cpp_interface/full_3d_stage.py](../python/cpp_interface/full_3d_stage.py) (`validate_saved_case`, `pack_input`, `pack_saved_case`, `run_case`).
- **Native C++ drivers**: For a new fluid, inspect [preprocess/preparation_case.cpp](../preprocess/preparation_case.cpp) (`query_inlet_properties`, `prepare_case_2d`, `prepare_case_3d`), [preprocess/preparation_df.cpp](../preprocess/preparation_df.cpp), [solver/full_2d.cpp](../solver/full_2d.cpp), [solver/full_3d.cpp](../solver/full_3d.cpp), and [solver/quick_design_driver.cpp](../solver/quick_design_driver.cpp).
- **Native library rebuild**: Rebuild and publish changed native libraries with [engineering/scripts/build_native_dependencies.py](../engineering/scripts/build_native_dependencies.py), then restart Python. See [C++ integration](cpp-migration.md#native-preparation-core).

#### Application and GUI

- Open [python/applications/gui/ui/builders_fluids.py](../python/applications/gui/ui/builders_fluids.py) (`build_fluid_sections`, `refresh_fluid_model_visibility`) to update `combo_fluidA`, `combo_fluidB`, or Nu model controls (`combo_sco2_nu_mode` is the existing example).
- Open [python/applications/gui/ui/window_config.py](../python/applications/gui/ui/window_config.py) to update `_parse_fluid_label`, `sco2_nu_from_window`, and `config_from_window`.
- Inspect [python/applications/gui/ui/mixins/fluid_input.py](../python/applications/gui/ui/mixins/fluid_input.py) for inlet auto-fill preview, and [python/applications/gui/ui/sensitivity.py](../python/applications/gui/ui/sensitivity.py) (which accepts air only for Fluid A).

#### Saved data and model resolution

- Register or update versioned model IDs in [python/physical_models/catalog.py](../python/physical_models/catalog.py) (`resolve_model`, `MODEL_VERSIONS`) and native saved-model decoding in [solver/stage_saved_models.hpp](../solver/stage_saved_models.hpp) (`validate_saved_models`).
- Keep YAML and HDF5 persistence in [python/file_io/case_io.py](../python/file_io/case_io.py) and [python/file_io/result_io.py](../python/file_io/result_io.py) consistent with the [public data contract](contracts/three_module_v1/README.md).
- Existing saved cases and results must keep their original model versions and parameters without silent replacement.

### 4. Existing tests to extend

- **Native property and Nu checks**: [tests/python/native/test_fluid_properties.py](../tests/python/native/test_fluid_properties.py) and [tests/cpp/fluid_properties_smoke.cpp](../tests/cpp/fluid_properties_smoke.cpp).
- **Python model and Nu contracts**: [tests/python/test_fluid_props.py](../tests/python/test_fluid_props.py), [tests/python/test_nu_correlations.py](../tests/python/test_nu_correlations.py), [tests/python/test_fluid_type_validation.py](../tests/python/test_fluid_type_validation.py), and [tests/python/test_sco2_nu_modes.py](../tests/python/test_sco2_nu_modes.py).
- **Catalog, config, and stage preparation**: [tests/python/models_tm1/test_catalog.py](../tests/python/models_tm1/test_catalog.py), [tests/python/test_compute_config_roundtrip.py](../tests/python/test_compute_config_roundtrip.py), [tests/python/preprocess/test_2d_tm1.py](../tests/python/preprocess/test_2d_tm1.py), [tests/python/preprocess/test_3d_tm1.py](../tests/python/preprocess/test_3d_tm1.py), and [tests/python/io_tm1/test_case_io.py](../tests/python/io_tm1/test_case_io.py).
- **GUI fluid input wiring**: [tests/python/test_fluid_input.py](../tests/python/test_fluid_input.py).

### 5. Validation and data

- A new fluid or Nu closure needs physical evidence from CFD or experiments before production use.
- Keep raw datasets in local `data/raw_data/` without committing them.
  Record provenance and bounds in [model resources](model-resources.en.md) and the [data catalog](data-catalog.en.md).
- Define operating limits (temperature, pressure, `Re`, and `Pr` windows) so `evaluate_applicability` and `evaluate_qualification` report range and scope states accurately.
- Update [capabilities](capabilities.en.md) to state what the new fluid or law supports and what stays out of scope.
- **Physical acceptance is the user's decision.** Passing unit tests, native smoke tests, or CI does not approve a physical model for design use.

<a id="new-gui-panel-or-dialog"></a>

## New GUI panel or dialog

First decide if the UI feature belongs inside a workbench card or in a separate dialog.
Workbench cards share the main canvas lifecycle, while dialogs own their own window and worker state.

### 1. First file to open (rule owner)

- **Workbench shell and parameter inspector**: Open [python/applications/gui/ui/ui_builders.py](../python/applications/gui/ui/ui_builders.py) (`build_ui`, `build_param_tabs`, `build_page_zones`, `refresh_group_badges`).
- **Workbench canvas cards**: Open [python/applications/gui/ui/builders_canvas.py](../python/applications/gui/ui/builders_canvas.py) (`build_canvas_area`, `_build_canvas_content`, `_build_optimize_panel`, `refresh_field_controls`).
  `build_canvas_area` registers cards in `window._canvas_cards` and adds embedded panels such as the optimization wizard.
- **Separate dialog ownership (Quick Design example)**:
  - Open [python/applications/gui/ui/mixins/optimize_ui.py](../python/applications/gui/ui/mixins/optimize_ui.py) (`OptimizeUIMixin._open_quick_design`) to see how the main window creates on demand, keeps, and raises `self._qd_dialog`.
  - Open [python/applications/gui/ui/quick_design_panel.py](../python/applications/gui/ui/quick_design_panel.py) (`build_quick_design_dialog`, `run_quick_design`, `cancel_quick_design`, `_gather_inputs`) to see dialog construction, worker connections, and close guards.
  - Other window-owned dialogs live in [python/applications/gui/ui/mixins/dialogs.py](../python/applications/gui/ui/mixins/dialogs.py) (`DialogsMixin`).
- **Published result ownership**: Open [python/applications/gui/controllers/result_cache.py](../python/applications/gui/controllers/result_cache.py) (`ResultCache`).
  `ResultCache` is the only owner of published 2D and 3D `ComputeResult` data.

### 2. Public interface and boundary rules

- **Qt boundary rule**: Import `PySide6` only inside `python/applications/gui/ui/` and `python/applications/gui/controllers/`.
  Lower layers (`data_types/`, `physical_models/`, `preprocess/`, `solvers/`, `postprocess/`, `file_io/`, `run_control/`, `cpp_interface/`) must stay free of Qt.
- **Widget-to-config boundary**: Read input widgets once at the UI boundary in [python/applications/gui/ui/window_config.py](../python/applications/gui/ui/window_config.py) (`config_from_window`, `CONFIG_FIELDS`, `FieldSpec`).
  `window_config.py` imports no Qt, so headless tests can pass plain stub objects.
- **Single result owner**: [python/applications/gui/ui/mixins/run_results.py](../python/applications/gui/ui/mixins/run_results.py) (`RunResultsMixin.write_result`) publishes an isolated `ComputeResult` to `ResultCache` (`set_result`, `get_result`, `has_results`, `mark_drawn`).
  Do not copy result fields onto `Main_Menu` attributes.
  For example, 2D zone overlays in [python/applications/gui/ui/plot_2d_results.py](../python/applications/gui/ui/plot_2d_results.py) (`finalize_plots`, `plot_temperature_3panel`, `_draw_zone_overlays`) read `result.zones` directly from `ResultCache`.
- **Styling and background execution**: Use [field_factory.py](../python/applications/gui/ui/field_factory.py) (`FieldFactory`), [theme_manager.py](../python/applications/gui/ui/theme_manager.py) (`ThemeManager`), and [responsive.py](../python/applications/gui/ui/responsive.py) (`ResponsiveRow`).
  Run heavy computation in background workers, and keep widget updates, Matplotlib, and OpenGL on the GUI thread.

### 3. Downstream consumers

- **Main window and navigation**: Connect buttons, shortcuts, and card visibility in [python/applications/gui/main.py](../python/applications/gui/main.py) (`Main_Menu`) and [python/applications/gui/ui/mixins/tab_view.py](../python/applications/gui/ui/mixins/tab_view.py) (`TabViewMixin._canvas_tab_availability`, `_update_tab_visibility`).
  Update [python/applications/gui/ui/mixins/shortcuts.py](../python/applications/gui/ui/mixins/shortcuts.py), [python/applications/gui/ui/builders_sidebar.py](../python/applications/gui/ui/builders_sidebar.py) (`refresh_result_sidebar`), and [python/applications/gui/ui/command_palette.py](../python/applications/gui/ui/command_palette.py) when needed.
- **Session, presets, and exports**: If the panel adds persistent user inputs or exports, update [python/applications/gui/ui/mixins/session_presets.py](../python/applications/gui/ui/mixins/session_presets.py), [python/applications/gui/ui/mixins/io_actions.py](../python/applications/gui/ui/mixins/io_actions.py), and [python/applications/gui/controllers/user_storage.py](../python/applications/gui/controllers/user_storage.py).
  Older saved sessions and presets must stay readable.
- **Application layer calls**: Call public application or postprocessing entries ([python/compute.py](../python/compute.py), [python/applications/design/](../python/applications/design/), [python/applications/optimization/](../python/applications/optimization/), [python/postprocess/result_display.py](../python/postprocess/result_display.py)), not `python/cpp_interface/` directly.
- **OpenSpec UI requirements**: Do a check against the active `ui-*` specifications under [openspec/specs/](../openspec/specs/):
  - [ui-result-workbench](../openspec/specs/ui-result-workbench/spec.en.md) and [ui-layout-hygiene](../openspec/specs/ui-layout-hygiene/spec.en.md) (workbench cards, no horizontal scroll, `ResultCache` ownership).
  - [ui-cta-and-shortcuts](../openspec/specs/ui-cta-and-shortcuts/spec.en.md), [ui-workflow-ia](../openspec/specs/ui-workflow-ia/spec.en.md), and [ui-optimize-wizard](../openspec/specs/ui-optimize-wizard/spec.en.md) (primary actions, navigation, wizard states).
  - [ui-chinese-chrome](../openspec/specs/ui-chinese-chrome/spec.en.md), [ui-design-tokens](../openspec/specs/ui-design-tokens/spec.en.md), [ui-group-badges](../openspec/specs/ui-group-badges/spec.en.md), and [ui-results-quickswitch](../openspec/specs/ui-results-quickswitch/spec.en.md) (labels, theme tokens, badges, result switching).

### 4. Existing tests to extend

- **Headless Qt fixture setup**: [tests/python/conftest.py](../tests/python/conftest.py) sets `QT_QPA_PLATFORM=offscreen` before importing `PySide6` and creates one shared offscreen `QApplication`.
- **Dialog and panel wiring**: [tests/python/test_quick_design_panel_wiring.py](../tests/python/test_quick_design_panel_wiring.py), [tests/python/test_quick_design_dialog.py](../tests/python/test_quick_design_dialog.py), [tests/python/test_optimize_panel_wiring.py](../tests/python/test_optimize_panel_wiring.py), and [tests/python/test_main_smoke.py](../tests/python/test_main_smoke.py).
- **Result cache, overlays, and workbench state**: [tests/python/test_result_cache.py](../tests/python/test_result_cache.py), [tests/python/test_result_snapshot_lifecycle.py](../tests/python/test_result_snapshot_lifecycle.py), [tests/python/test_workbench_field_selection.py](../tests/python/test_workbench_field_selection.py), and [tests/python/test_workbench_navigation.py](../tests/python/test_workbench_navigation.py).
- **Layout and import-layer rules**: [tests/python/test_ui_layout_hygiene.py](../tests/python/test_ui_layout_hygiene.py), [tests/python/architecture/test_three_module_imports.py](../tests/python/architecture/test_three_module_imports.py), and [tests/python/models_tm1/test_model_boundary.py](../tests/python/models_tm1/test_model_boundary.py).
  Also run `python -m sjtu_tpmshx.development.runs.tools.audit_import_graph --fail-on-violations`.
- Follow [test scope](collaboration.md#test-scope): test state changes, contracts, and cleanup, not offscreen pixel coordinates or fixed margins.

### 5. Validation and data

- Run offscreen GUI tests, layout hygiene checks, and import-graph checks from the [verification guide](verification.en.md).
- Update both `spec.md` and `spec.en.md` in any affected `openspec/specs/ui-*/` folder when UI behavior changes.
- Headless CI does not replace real desktop visual or OpenGL 3D checks on macOS and Windows. See [Qt rendering](verification.en.md#qt-rendering).
- Get user approval for undecided user-facing workflows or layout contracts before you merge them.

<a id="third-tpms-topology"></a>

## Third TPMS topology (short route)

Now, adding a third TPMS topology changes about 22 code files before coefficients, qualification data, tests, UI, or documents.
Wait for approved calibration data before starting implementation, and keep unsupported topologies failing explicitly at every entry point.

### 1. First file to open (rule owner)

- Open [python/data_types/compute_config.py](../python/data_types/compute_config.py) (`TPMSType`), which is the Qt-free supported topology list used by `GeometryConfig` and GUI validators.
- Open [include/tpmshx/fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp) (`enum class Topology`) and [geometry/geometry.cpp](../geometry/geometry.cpp) (`topology_row`, `phi_grid`, `calibration`).

### 2. Public interface

- **Python ABI mapping**: Update `TOPOLOGIES`, `TOPOLOGY_CODES`, and `geometry_topology` in [python/cpp_interface/_native_values.py](../python/cpp_interface/_native_values.py) to match the C++ enum order.
- **Native C and C++ enums**: Update `enum class Topology` ([include/tpmshx/fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp)), `enum tpmshx_geometry_topology_v1` ([include/tpmshx/geometry_c_api.h](../include/tpmshx/geometry_c_api.h)), `enum tpmshx_topology` ([include/tpmshx/solver_c_api.h](../include/tpmshx/solver_c_api.h)), and SDK mappings in [include/tpmshx/stages.hpp](../include/tpmshx/stages.hpp).

### 3. Downstream consumers

- **Geometry kernel and property dispatch**: Update [geometry/geometry.cpp](../geometry/geometry.cpp) (`phi_grid`, `topology_row`), [geometry/geometry_c_api.cpp](../geometry/geometry_c_api.cpp), and [numerics/fluid_properties.cpp](../numerics/fluid_properties.cpp) (`topology_row`, `preparation::nu_point`).
- **Generator row order and model resources**: Update row order in [engineering/scripts/generate_native_model_coefficients.py](../engineering/scripts/generate_native_model_coefficients.py) (`table`, `header`, `df_header`).
  Update resource checks in [python/model_configs/model_parameters.py](../python/model_configs/model_parameters.py) (`load_model_parameters`, `load_co2_coefficients`, `load_preparation_df_parameters`).
  Update `model_parameters_v1.json`, `preparation_df_v1.json`, and `cfd_full_core_3cell_fixed_v2.csv` (or reject unsupported modes explicitly in [preprocess/preparation_df.cpp](../preprocess/preparation_df.cpp), `topology_check`).
- **Preparation, solver, and saved-model decoding**: Update topology selectors and labels in [preprocess/preparation_case.cpp](../preprocess/preparation_case.cpp), [preprocess/property_c_api.cpp](../preprocess/property_c_api.cpp), and [preprocess/quick_design_prepare_v2.cpp](../preprocess/quick_design_prepare_v2.cpp).
  Update matching branches in [solver/solver_c_api.cpp](../solver/solver_c_api.cpp), [solver/full_2d.cpp](../solver/full_2d.cpp), [solver/full_3d_c_api.cpp](../solver/full_3d_c_api.cpp), [solver/stage_run.cpp](../solver/stage_run.cpp), [solver/closure_ranges.hpp](../solver/closure_ranges.hpp), [solver/stage_capture_2d.cpp](../solver/stage_capture_2d.cpp), and [solver/stage_capture_3d.cpp](../solver/stage_capture_3d.cpp).
  Update saved-model decoding in [solver/stage_saved_models.hpp](../solver/stage_saved_models.hpp) (`validate_saved_models`), [python/cpp_interface/preparation_host.py](../python/cpp_interface/preparation_host.py) (`pack_saved_resources`), and [python/physical_models/catalog.py](../python/physical_models/catalog.py) (`resolve_model`).
  Existing Diamond and Gyroid archives must keep their original topology identity.
- **GUI selectors**: Update `combo_tpms` in [python/applications/gui/ui/builders_domain.py](../python/applications/gui/ui/builders_domain.py) and `combo_cell_topo` in [python/applications/gui/ui/quick_design_panel.py](../python/applications/gui/ui/quick_design_panel.py).
  [python/applications/gui/ui/window_config.py](../python/applications/gui/ui/window_config.py) (`_selected_topology`) and [python/applications/gui/ui/sensitivity.py](../python/applications/gui/ui/sensitivity.py) (`SensitivityDialog._collect_fixed_params`) already read `TPMSType` and reject unsupported names.
- **Native library rebuild**: Rebuild and publish all four native libraries with [engineering/scripts/build_native_dependencies.py](../engineering/scripts/build_native_dependencies.py).

### 4. Existing tests to extend

- **Native geometry and properties**: [tests/cpp/geometry_kernel_smoke.cpp](../tests/cpp/geometry_kernel_smoke.cpp), [tests/cpp/geometry_c_smoke.c](../tests/cpp/geometry_c_smoke.c), [tests/python/test_native_geometry.py](../tests/python/test_native_geometry.py), and [tests/python/native/test_fluid_properties.py](../tests/python/native/test_fluid_properties.py).
- **Config, catalog, and GUI selection**: [tests/python/test_main_smoke.py](../tests/python/test_main_smoke.py), [tests/python/test_compute_config_roundtrip.py](../tests/python/test_compute_config_roundtrip.py), and [tests/python/models_tm1/test_catalog.py](../tests/python/models_tm1/test_catalog.py).
  Add a negative test for an unknown topology name.
  Also test that unsupported fluids or D-F modes fail explicitly.

### 5. Validation and data

- A third TPMS topology needs physical calibration data: level-set wall fit, solid tortuosity (`chi`), per-fluid Nu fits, and fixed D-F CFD tables.
- Record data sources, bounds, and unsupported combinations in [model resources](model-resources.en.md), the [data catalog](data-catalog.en.md), and [capabilities](capabilities.en.md).
- **Physical acceptance is the user's decision.**

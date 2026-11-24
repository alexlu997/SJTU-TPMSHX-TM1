# Contributor extension guide

[中文](extending.zh-CN.md) | [English](extending.md)

Use this guide to find where an extension starts, which interfaces it changes, and which checks apply.
It maps the code on `main` across C++ numerical owners, Python bindings, saved data, and the GUI.
See [architecture](architecture.md) for the three-stage flow and physical invariants, and [verification](verification.en.md) for local and CI commands.

## Quick route index

| Question | First file to open | Key downstream layers | Existing tests | Route |
| --- | --- | --- | --- | --- |
| Add a fluid or Nu closure | [compute_config.py](../python/data_types/compute_config.py) (`FluidType`, `Sco2NuConfig`) — owns public fluid names and validated Nu config | [model_configs/](../python/model_configs/), [generate_native_model_coefficients.py](../engineering/scripts/generate_native_model_coefficients.py), [fluid_props.py](../python/physical_models/fluid_props.py), [fluid_properties.cpp](../numerics/fluid_properties.cpp), Stage-1/2 adapters, [builders_fluids.py](../python/applications/gui/ui/builders_fluids.py), [stage_saved_models.hpp](../solver/stage_saved_models.hpp) | [test_fluid_properties.py](../tests/python/native/test_fluid_properties.py), [test_fluid_props.py](../tests/python/test_fluid_props.py), [test_nu_correlations.py](../tests/python/test_nu_correlations.py), [test_sco2_nu_modes.py](../tests/python/test_sco2_nu_modes.py), [test_catalog.py](../tests/python/models_tm1/test_catalog.py) | [New fluid or Nu closure](#new-fluid-or-nu-closure) |
| Add a GUI panel or dialog | Card: [builders_canvas.py](../python/applications/gui/ui/builders_canvas.py) (`build_canvas_area`); Dialog: [optimize_ui.py](../python/applications/gui/ui/mixins/optimize_ui.py) (`_open_quick_design`); Results: [result_cache.py](../python/applications/gui/controllers/result_cache.py) (`ResultCache`) | [ui_builders.py](../python/applications/gui/ui/ui_builders.py), [quick_design_panel.py](../python/applications/gui/ui/quick_design_panel.py), [background_tasks.py](../python/applications/gui/ui/background_tasks.py), [main.py](../python/applications/gui/main.py), [session_manager.py](../python/applications/gui/controllers/session_manager.py), [OpenSpec `ui-*`](../openspec/specs/) | [conftest.py](../tests/python/conftest.py), [test_quick_design_panel_wiring.py](../tests/python/test_quick_design_panel_wiring.py), [test_optimize_panel_wiring.py](../tests/python/test_optimize_panel_wiring.py), [test_result_snapshot_lifecycle.py](../tests/python/test_result_snapshot_lifecycle.py), [test_ui_layout_hygiene.py](../tests/python/test_ui_layout_hygiene.py) | [New GUI panel or dialog](#new-gui-panel-or-dialog) |
| Add a third TPMS topology | [compute_config.py](../python/data_types/compute_config.py) (`TPMSType`) — Qt-free supported topology list read by config and GUI validators | [_native_values.py](../python/cpp_interface/_native_values.py), [geometry.cpp](../geometry/geometry.cpp), [generate_native_model_coefficients.py](../engineering/scripts/generate_native_model_coefficients.py), [preparation_df.cpp](../preprocess/preparation_df.cpp), [stage_saved_models.hpp](../solver/stage_saved_models.hpp), [builders_domain.py](../python/applications/gui/ui/builders_domain.py) | [geometry_kernel_smoke.cpp](../tests/cpp/geometry_kernel_smoke.cpp), [test_native_geometry.py](../tests/python/test_native_geometry.py), [test_main_smoke.py](../tests/python/test_main_smoke.py), [test_catalog.py](../tests/python/models_tm1/test_catalog.py) | [Third TPMS topology](#third-tpms-topology) |

<a id="new-fluid-or-nu-closure"></a>

## New fluid or Nu closure

Select your scope before you edit code.
Here `sCO2` means supercritical CO2, and `Sco2NuConfig` is the existing typed dataclass for supercritical CO2 Nu modes and calibration metadata.

- **New Nu law for an existing fluid**: This route still changes resources, native Nu dispatch, stage transport, and GUI controls. It keeps existing fluid IDs, transport or EOS evaluators, phase checks, energy equations, and D-F fluid tables unchanged.
- **New working fluid**: Add the fluid across configuration, Python queries, native enums, transport or EOS evaluators, and phase checks. Also update energy relations, D-F scope, stage adapters, saved-model decoding, and GUI controls.

### 1. First file to open (rule owner)

Open [python/data_types/compute_config.py](../python/data_types/compute_config.py) first.
It owns `FluidType`, `FluidConfig`, `Sco2NuConfig`, and `ComputeConfig.validate`, which every downstream layer reads.
Then inspect [fluid_props.py](../python/physical_models/fluid_props.py), [nu_correlations.py](../python/physical_models/nu_correlations.py), [python/model_configs/](../python/model_configs/), [fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp), and [fluid_properties.cpp](../numerics/fluid_properties.cpp).

### 2. Public interface

- **Python configuration and queries**: `ComputeConfig`, `FluidConfig`, and `Sco2NuConfig` in [python/data_types/compute_config.py](../python/data_types/compute_config.py); `fluid_props.get` and `fluid_props.flow_model` in [python/physical_models/fluid_props.py](../python/physical_models/fluid_props.py); Nu functions in [python/physical_models/nu_correlations.py](../python/physical_models/nu_correlations.py).
- **Three-stage Python APIs**: `prepare_case` ([python/preprocess/api.py](../python/preprocess/api.py)), `run_case` ([python/solvers/api.py](../python/solvers/api.py)), `evaluate` ([python/postprocess/api.py](../python/postprocess/api.py)), and `compute` ([python/compute.py](../python/compute.py)).
- **Native C and C++ interfaces**: `enum class Fluid`, `PropertyEvaluator`, `fluid_nusselt`, and `fluid_nusselt_ratio` in [include/tpmshx/fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp).
- **C API fluid encodings**: Full 2D and 3D C APIs ([preparation_case_c_api.h](../include/tpmshx/preparation_case_c_api.h), [full_2d_c_api.h](../include/tpmshx/full_2d_c_api.h), [full_3d_c_api.h](../include/tpmshx/full_3d_c_api.h)) encode `uint32_t fluid` as `0..3` (`air`, `water`, `sco2`, `co2`).
  `enum tpmshx_fluid` in [include/tpmshx/solver_c_api.h](../include/tpmshx/solver_c_api.h) covers Quick Design only (`0..2`, without `co2`).

### 3. Downstream consumers

Use the table below to find each file that must change.
Items marked **(new fluid)** apply only when you add a new working fluid.

| Layer | Path | Symbols | Role |
| --- | --- | --- | --- |
| Config and resources | [python/data_types/compute_config.py](../python/data_types/compute_config.py) | `FluidType`, `FluidConfig`, `Sco2NuConfig`, `ComputeConfig.validate` | Public fluid names, Nu selection dataclass, and static validation |
| Config and resources | [python/model_configs/model_parameters.py](../python/model_configs/model_parameters.py) | `MODEL_VERSIONS`, `load_model_parameters`, `load_co2_coefficients`, `load_preparation_df_parameters` | Canonical owner of `MODEL_VERSIONS` and JSON schema checks |
| Config and resources | [python/model_configs/](../python/model_configs/) | `model_parameters_v1.json`, `sco2_effective_nu.json`, `co2_segment2_v1.json`, `preparation_df_v1.json` | Versioned coefficients, operating bounds, and model versions |
| Config and resources | [engineering/scripts/generate_native_model_coefficients.py](../engineering/scripts/generate_native_model_coefficients.py) | `header`, `df_header`, `table` | Compile-time C++ coefficient header generation |
| Python model queries | [python/physical_models/fluid_props.py](../python/physical_models/fluid_props.py) | `FLUIDS`, `FluidModel`, `get`, `flow_model`, `check_water_state` | Runtime per-fluid dispatch and phase guards |
| Python model queries | [python/physical_models/nu_correlations.py](../python/physical_models/nu_correlations.py) | `nu_from_Re`, `nu_vec`, `nu_water_topo`, `nu_sco2_topo`, `nu_sco2_selected`, `sco2_effective_nu_config`, `record_raw_nu_range`, `warn_sco2_nu_evidence` | Public Nu wrappers and range/evidence notices |
| Python model queries | [python/physical_models/design_fluids.py](../python/physical_models/design_fluids.py) | `nu_re_window`, `fluid_nu`, `record_native_design_ranges` | Quick Design and GUI preview fluid Nu and `Re` bounds **(new fluid)** |
| Python model queries | [python/physical_models/tpms_calc.py](../python/physical_models/tpms_calc.py), [tpms_props.py](../python/physical_models/tpms_props.py) | `_RE_FIT_RANGE_BY_FLUID`, `model_h_coefficients`, `record_temperature_ranges` | Standalone `Re` windows, model-h polynomials, and temperature ranges **(new fluid)** |
| Python native adapters | [python/cpp_interface/_native_preparation_case.py](../python/cpp_interface/_native_preparation_case.py), [_native_properties.py](../python/cpp_interface/_native_properties.py) | `_FLUIDS`, `_Inlet`, `_Nu`, `empirical`, `nu_inputs`, `nusselt` | C ABI fluid codes, Nu structs, and direct property/Nu calls |
| Python native adapters | [python/cpp_interface/inlet_properties.py](../python/cpp_interface/inlet_properties.py), [preparation_host.py](../python/cpp_interface/preparation_host.py) | `inlet_query`, `validate_fluid_type`, `observe_range`, `pack_nu`, `pack_saved_resources`, `model_metadata`, `PreparationCacheBridge` | Standalone inlet query (`tpmshx_query_inlet_properties_v2`), host callbacks, and saved resource packing |
| Python native adapters | [python/cpp_interface/native_preparation.py](../python/cpp_interface/native_preparation.py), [python/preprocess/three_d/preparation.py](../python/preprocess/three_d/preparation.py), [_native_quick_prepare.py](../python/cpp_interface/_native_quick_prepare.py) | `_input`, `_case`, `_execute`, `_FLUIDS` | Stage-1 2D, 3D, and Quick Design input packing and `CaseData` assembly |
| Python native adapters | [python/cpp_interface/full_2d_stage.py](../python/cpp_interface/full_2d_stage.py), [full_3d_stage.py](../python/cpp_interface/full_3d_stage.py) | `prepare_stage`, `pack_saved`, `validate_saved_case`, `pack_input`, `pack_saved_case`, `run_case` | Stage-2 fluid ID packing, Nu options, and saved-case execution |
| C++ native | [include/tpmshx/fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp), [numerics/fluid_properties.cpp](../numerics/fluid_properties.cpp) | `enum class Fluid`, `uses_co2_eos`, `model_h_coefficients`, `nusselt_floor`, `PropertyEvaluator`, `fluid_nusselt_ratio`, `preparation::empirical_point`, `preparation::nu_point` | Core C++ property, EOS, and Nu calculations |
| C++ native | [preprocess/preparation_properties.hpp](../preprocess/preparation_properties.hpp), [preparation_properties.cpp](../preprocess/preparation_properties.cpp), [property_c_api.cpp](../preprocess/property_c_api.cpp) | `Empirical`, `NuRoute`, `empirical_range`, `empirical`, `nu_inputs`, `nusselt`, `tpmshx_preparation_empirical_v1`, `tpmshx_preparation_nu_inputs_v1`, `tpmshx_preparation_nu_v1` | Preparation property/Nu validation and C-boundary range guards |
| C++ native | [preprocess/preparation_case.cpp](../preprocess/preparation_case.cpp), [preparation_df.cpp](../preprocess/preparation_df.cpp), [preparation_df_corrections.cpp](../preprocess/preparation_df_corrections.cpp) | `query_inlet_properties`, `prepare_case_2d`, `prepare_case_3d`, `df_experiment_scope`, `df_select` | Native 2D/3D preparation and D-F experiment scope **(new fluid)** |
| C++ native | [solver/enthalpy_eos.cpp](../solver/enthalpy_eos.cpp), [closure_ranges.hpp](../solver/closure_ranges.hpp), [full_2d.cpp](../solver/full_2d.cpp), [full_3d.cpp](../solver/full_3d.cpp) | `EnthalpyEOS`, `fluid_name`, `property`, `nu` | Solver EOS states, range recording, and 2D/3D thermal/flow loops **(new fluid)** |
| C++ native | [include/tpmshx/stages.hpp](../include/tpmshx/stages.hpp), [solver/stage_run.cpp](../solver/stage_run.cpp), [stage_run_3d.cpp](../solver/stage_run_3d.cpp), [full_3d_c_api.cpp](../solver/full_3d_c_api.cpp), [stage_capture_2d.cpp](../solver/stage_capture_2d.cpp), [stage_capture_3d.cpp](../solver/stage_capture_3d.cpp) | `fluid_text`, saved-stage fluid ID checks and capture metadata | Native SDK and saved-stage 2D/3D bounds checks **(new fluid)** |
| C++ native | [solver/quick_design_driver.cpp](../solver/quick_design_driver.cpp), [quick_design_run.cpp](../solver/quick_design_run.cpp), [solver_c_api.cpp](../solver/solver_c_api.cpp) | `enum tpmshx_fluid` checks and Quick Design fluid dispatch | Quick Design solver support or explicit rejection **(new fluid)** |
| GUI and saved data | [python/applications/gui/ui/builders_fluids.py](../python/applications/gui/ui/builders_fluids.py), [window_config.py](../python/applications/gui/ui/window_config.py), [main.py](../python/applications/gui/main.py) | `build_fluid_sections`, `refresh_fluid_model_visibility`, `combo_fluidA`, `combo_fluidB`, `combo_sco2_nu_mode`, `_parse_fluid_label`, `sco2_nu_from_window`, `_FLUID_DEFAULTS` | GUI fluid/Nu controls, default inlet values, and config parsing |
| GUI and saved data | [python/applications/gui/ui/mixins/fluid_input.py](../python/applications/gui/ui/mixins/fluid_input.py), [session_presets.py](../python/applications/gui/ui/mixins/session_presets.py), [io_actions.py](../python/applications/gui/ui/mixins/io_actions.py), [command_palette.py](../python/applications/gui/ui/command_palette.py), [sensitivity.py](../python/applications/gui/ui/sensitivity.py) | `_PRESET_COMBOS`, `_validate_preset`, `_set_sco2_nu_parameters`, `_load_sco2_nu_parameters` | Auto-fill preview, preset save/load, command palette, and air-only sensitivity check |
| GUI and saved data | [python/physical_models/catalog.py](../python/physical_models/catalog.py), [solver/stage_saved_models.hpp](../solver/stage_saved_models.hpp), [python/file_io/case_io.py](../python/file_io/case_io.py), [result_io.py](../python/file_io/result_io.py) | `resolve_model`, `validate_saved_models`, `save_case`, `load_case`, `save_result`, `load_result` | Saved-case model resolution (`catalog.py` imports `MODEL_VERSIONS` from `model_parameters.py`) and YAML/HDF5 persistence |

- **Native library rebuild**: After you change C++ code or compiled model resources, rebuild and publish affected native libraries with [engineering/scripts/build_native_dependencies.py](../engineering/scripts/build_native_dependencies.py). Then restart Python. See [C++ integration](cpp-migration.md#native-preparation-core).
- **Saved data rule**: Follow the [public data contract](contracts/three_module_v1/README.md). Existing saved cases and results must keep their original model versions and parameters without silent replacement.
- **Known silent fallbacks**: Update these sites so unknown fluid names or enum values fail explicitly during your extension:
  - [solver/closure_ranges.hpp](../solver/closure_ranges.hpp) (`fluid_name`, `property`, `nu`): unknown enum values fall through to `"sco2"` or air/sCO2 bounds.
  - [python/physical_models/design_fluids.py](../python/physical_models/design_fluids.py) (`nu_re_window`) and [python/physical_models/tpms_calc.py](../python/physical_models/tpms_calc.py) (`_RE_FIT_RANGE_BY_FLUID`): unknown fluid names fall back to air `NU_RE_FIT_RANGE`.
  - [python/applications/gui/ui/window_config.py](../python/applications/gui/ui/window_config.py) (`_parse_fluid_label`): unrecognized combo text falls back to `'air'`.

### 4. Existing tests to extend

- **Native property and Nu checks**: [tests/python/native/test_fluid_properties.py](../tests/python/native/test_fluid_properties.py) and [tests/cpp/fluid_properties_smoke.cpp](../tests/cpp/fluid_properties_smoke.cpp).
- **Python model and Nu contracts**: [tests/python/test_fluid_props.py](../tests/python/test_fluid_props.py), [tests/python/test_nu_correlations.py](../tests/python/test_nu_correlations.py), [tests/python/test_fluid_type_validation.py](../tests/python/test_fluid_type_validation.py), and [tests/python/test_sco2_nu_modes.py](../tests/python/test_sco2_nu_modes.py).
- **Catalog, config, and stage preparation**: [tests/python/models_tm1/test_catalog.py](../tests/python/models_tm1/test_catalog.py), [tests/python/test_compute_config_roundtrip.py](../tests/python/test_compute_config_roundtrip.py), [tests/python/preprocess/test_2d_tm1.py](../tests/python/preprocess/test_2d_tm1.py), [tests/python/preprocess/test_3d_tm1.py](../tests/python/preprocess/test_3d_tm1.py), and [tests/python/io_tm1/test_case_io.py](../tests/python/io_tm1/test_case_io.py).
- **GUI fluid input wiring**: [tests/python/test_fluid_input.py](../tests/python/test_fluid_input.py).

### 5. Validation and data

- A new fluid or Nu closure needs physical evidence from CFD or experiments before production use.
- Keep raw datasets in local `data/raw_data/` without committing them.
  Record provenance and bounds in [model resources](model-resources.en.md) and the [data catalog](data-catalog.en.md).
- Define temperature, pressure, `Re`, and `Pr` limits for `evaluate_applicability` and `evaluate_qualification` in [python/postprocess/api.py](../python/postprocess/api.py) (backed by [postprocess/result_stage.cpp](../postprocess/result_stage.cpp)).
- Update [capabilities](capabilities.en.md) to state what the new fluid or law supports and what stays out of scope.
- **Physical acceptance is the user's decision.** Passing unit tests, native smoke tests, or CI does not approve a physical model for design use.

<a id="new-gui-panel-or-dialog"></a>

## New GUI panel or dialog

Choose between a workbench card and a separate dialog before you edit code.
Workbench cards share the main canvas lifecycle.
Separate dialogs own their own window and background worker state.

### 1. First file to open (rule owner)

- **Workbench card**: Open [python/applications/gui/ui/builders_canvas.py](../python/applications/gui/ui/builders_canvas.py) (`build_canvas_area`) first, because it builds and registers every card in `window._canvas_cards`.
  Then open [python/applications/gui/ui/ui_builders.py](../python/applications/gui/ui/ui_builders.py) (`build_ui`, `build_param_tabs`) for top-bar entries and left-rail parameter sections.
- **Separate dialog (Quick Design example)**: Open [python/applications/gui/ui/mixins/optimize_ui.py](../python/applications/gui/ui/mixins/optimize_ui.py) (`OptimizeUIMixin._open_quick_design`) first, because it shows how the main window owns dialog lifetime (`self._qd_dialog`).
  Then open [python/applications/gui/ui/quick_design_panel.py](../python/applications/gui/ui/quick_design_panel.py) (`build_quick_design_dialog`, `run_quick_design`, `cancel_quick_design`) for dialog widgets, worker connections, and close guards.
  Other window dialogs live in [python/applications/gui/ui/mixins/dialogs.py](../python/applications/gui/ui/mixins/dialogs.py) (`DialogsMixin`).
- **Published results**: Open [python/applications/gui/controllers/result_cache.py](../python/applications/gui/controllers/result_cache.py) (`ResultCache`), which is the only owner of published 2D and 3D `ComputeResult` data.

### 2. Public interface and boundary rules

- **Qt boundary rule**: Keep `PySide6` imports inside `python/applications/gui/ui/`, `python/applications/gui/controllers/`, the GUI entry point [python/applications/gui/main.py](../python/applications/gui/main.py), and the desktop launcher [python/desktop.py](../python/desktop.py).
  Lower layers (`data_types/`, `physical_models/`, `preprocess/`, `solvers/`, `postprocess/`, `file_io/`, `run_control/`, `cpp_interface/`) must stay free of Qt.
- **Widget-to-config boundary**: Read input widgets once at the UI boundary in [python/applications/gui/ui/window_config.py](../python/applications/gui/ui/window_config.py) (`config_from_window`, `CONFIG_FIELDS`, `FieldSpec`).
  `window_config.py` imports no Qt, so headless tests can pass plain stub objects.
- **Single result owner**: [python/applications/gui/ui/mixins/run_results.py](../python/applications/gui/ui/mixins/run_results.py) (`RunResultsMixin.write_result`) publishes one isolated `ComputeResult` to `ResultCache` (`set_result`, `get_result`, `has_results`, `mark_drawn`).
  Do not copy result fields onto `Main_Menu` attributes.
  For example, 2D zone overlays in [python/applications/gui/ui/plot_2d_results.py](../python/applications/gui/ui/plot_2d_results.py) (`finalize_plots`, `plot_temperature_3panel`, `_draw_zone_overlays`) read `result.zones` directly from `ResultCache`.
- **Background workers and teardown**: Run heavy computation in background workers.
  Keep widget updates, Matplotlib, and OpenGL on the GUI thread.
  Register every new worker in [python/applications/gui/ui/background_tasks.py](../python/applications/gui/ui/background_tasks.py) (`has_active_tasks`, `refresh_resource_availability`).
  Cancel active workers cleanly in `Main_Menu.closeEvent` ([python/applications/gui/main.py](../python/applications/gui/main.py)).

### 3. Downstream consumers

Use the table below to find each GUI and controller file that can change.

| Layer | Path | Symbols | Role |
| --- | --- | --- | --- |
| UI construction | [python/applications/gui/ui/ui_builders.py](../python/applications/gui/ui/ui_builders.py), [builders_canvas.py](../python/applications/gui/ui/builders_canvas.py) | `build_ui`, `build_param_tabs`, `build_page_zones`, `refresh_group_badges`, `build_canvas_area`, `_build_canvas_content`, `_build_optimize_panel`, `refresh_field_controls` | Top bar, left-rail groups, workbench cards, and embedded optimization panel |
| UI construction | [python/applications/gui/ui/field_factory.py](../python/applications/gui/ui/field_factory.py), [theme_manager.py](../python/applications/gui/ui/theme_manager.py), [responsive.py](../python/applications/gui/ui/responsive.py) | `FieldFactory`, `ThemeManager`, `ResponsiveRow` | Design tokens, themed inputs, and responsive card stacking |
| Dialogs and workers | [python/applications/gui/ui/mixins/optimize_ui.py](../python/applications/gui/ui/mixins/optimize_ui.py), [quick_design_panel.py](../python/applications/gui/ui/quick_design_panel.py), [mixins/dialogs.py](../python/applications/gui/ui/mixins/dialogs.py) | `_open_quick_design`, `build_quick_design_dialog`, `run_quick_design`, `cancel_quick_design`, `_gather_inputs`, `DialogsMixin` | Dialog creation, lazy lifetime, worker run/cancel, and close guards |
| Dialogs and workers | [python/applications/gui/ui/background_tasks.py](../python/applications/gui/ui/background_tasks.py), [python/applications/gui/main.py](../python/applications/gui/main.py) | `has_active_tasks`, `refresh_resource_availability`, `Main_Menu`, `Main_Menu.closeEvent` | Shared active-task lockouts, CPU control gating, and safe shutdown |
| Controllers | [python/applications/gui/controllers/result_cache.py](../python/applications/gui/controllers/result_cache.py), [session_manager.py](../python/applications/gui/controllers/session_manager.py) | `ResultCache`, `SessionManager`, `SCHEMA_VERSION`, `load_session`, `save_session`, `load_user_presets`, `save_user_presets` | Published result store and session/preset JSON schema compatibility |
| Controllers | [python/applications/gui/controllers/signal_router.py](../python/applications/gui/controllers/signal_router.py), [compute_orchestrator.py](../python/applications/gui/controllers/compute_orchestrator.py), [user_storage.py](../python/applications/gui/controllers/user_storage.py) | `SignalRouter`, `ComputeOrchestrator` | Bulk signal disconnect on close, main compute worker pool, and platform data paths/appearance files |
| Navigation and results | [python/applications/gui/ui/mixins/tab_view.py](../python/applications/gui/ui/mixins/tab_view.py), [run_results.py](../python/applications/gui/ui/mixins/run_results.py), [plot_2d_results.py](../python/applications/gui/ui/plot_2d_results.py) | `TabViewMixin._canvas_tab_availability`, `_update_tab_visibility`, `RunResultsMixin.write_result`, `finalize_plots`, `plot_temperature_3panel`, `_draw_zone_overlays` | Card visibility routing, result publication, and cache-backed 2D plots |
| Navigation and results | [python/applications/gui/ui/mixins/shortcuts.py](../python/applications/gui/ui/mixins/shortcuts.py), [builders_sidebar.py](../python/applications/gui/ui/builders_sidebar.py), [command_palette.py](../python/applications/gui/ui/command_palette.py) | `refresh_result_sidebar` | Shortcuts, bottom result summary, and command palette entries when needed |
| Session and presets | [python/applications/gui/ui/mixins/session_presets.py](../python/applications/gui/ui/mixins/session_presets.py), [mixins/io_actions.py](../python/applications/gui/ui/mixins/io_actions.py) | `_PRESET_COMBOS`, `_validate_preset` | Widget snapshot capture, preset import/export, and backward-compatible load |

- **Application layer calls**: Call public application or postprocessing entries ([python/compute.py](../python/compute.py), [python/applications/design/](../python/applications/design/), [python/applications/optimization/](../python/applications/optimization/), [python/postprocess/result_display.py](../python/postprocess/result_display.py)), not `python/cpp_interface/` directly.
- **OpenSpec UI requirements**: Do a check against the nine active `ui-*` specifications under [openspec/specs/](../openspec/specs/):
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

Adding a third TPMS topology changes at least 22 core C++ and Python dispatch files before coefficients, calibration data, GUI selectors, tests, or documents.
Wait for approved calibration data before you start implementation.
Make sure unsupported topologies fail explicitly at each entry point.

### 1. First file to open (rule owner)

Open [python/data_types/compute_config.py](../python/data_types/compute_config.py) first.
It defines `TPMSType`, the Qt-free supported topology list read by `GeometryConfig` and GUI validators (`_selected_topology`).
Then open [include/tpmshx/fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp) (`enum class Topology`) and [geometry/geometry.cpp](../geometry/geometry.cpp) (`phi_grid`, `topology_row`, `calibration`) for the native geometry kernel.

### 2. Public interface

- **Python ABI mapping**: Update `TOPOLOGIES`, `TOPOLOGY_CODES`, and `geometry_topology` in [python/cpp_interface/_native_values.py](../python/cpp_interface/_native_values.py) to match the C++ enum order.
- **Native C and C++ enums**: Update `enum class Topology` ([include/tpmshx/fluid_properties.hpp](../include/tpmshx/fluid_properties.hpp)), `enum tpmshx_geometry_topology_v1` ([include/tpmshx/geometry_c_api.h](../include/tpmshx/geometry_c_api.h)), `enum tpmshx_topology` ([include/tpmshx/solver_c_api.h](../include/tpmshx/solver_c_api.h)), and `topology_text` in [include/tpmshx/stages.hpp](../include/tpmshx/stages.hpp).

### 3. Downstream consumers

Use the table below to find each core dispatch, model resource, GUI, and Quick Design file.

| Layer | Path | Symbols | Role |
| --- | --- | --- | --- |
| Config and resources | [python/data_types/compute_config.py](../python/data_types/compute_config.py), [python/model_configs/model_parameters.py](../python/model_configs/model_parameters.py) | `TPMSType`, `load_model_parameters`, `load_co2_coefficients`, `load_preparation_df_parameters` | Supported topology list and JSON resource schema checks |
| Config and resources | [python/model_configs/model_parameters_v1.json](../python/model_configs/model_parameters_v1.json), [preparation_df_v1.json](../python/model_configs/preparation_df_v1.json), [co2_segment2_v1.json](../python/model_configs/co2_segment2_v1.json), [python/physical_models/df_surrogate/_prebuilt/cfd_full_core_3cell_fixed_v2.csv](../python/physical_models/df_surrogate/_prebuilt/cfd_full_core_3cell_fixed_v2.csv) | Topology coefficient rows and fixed D-F grid nodes | Geometry, Nu, CO2, and fixed D-F data tables |
| Config and resources | [engineering/scripts/generate_native_model_coefficients.py](../engineering/scripts/generate_native_model_coefficients.py) | `table`, `header`, `df_header` | Fixes generated C++ topology row order |
| Python model queries | [python/physical_models/tpms_geometry.py](../python/physical_models/tpms_geometry.py), [nu_correlations.py](../python/physical_models/nu_correlations.py), [co2_correlations.py](../python/physical_models/co2_correlations.py), [df_surrogate/full_core_3cell_fixed_v2.py](../python/physical_models/df_surrogate/full_core_3cell_fixed_v2.py) | `_compute_geometry_cached`, `compute_geometry_fields`, `_sco2_nu`, `_topology`, `FullCore3CellFixedDFV2` | Python geometry, Nu, CO2, and fixed D-F dispatch |
| Python native adapters | [python/cpp_interface/_native_values.py](../python/cpp_interface/_native_values.py), [_native_df.py](../python/cpp_interface/_native_df.py), [preparation_host.py](../python/cpp_interface/preparation_host.py), [full_2d_stage.py](../python/cpp_interface/full_2d_stage.py), [full_3d_stage.py](../python/cpp_interface/full_3d_stage.py) | `TOPOLOGIES`, `TOPOLOGY_CODES`, `geometry_topology`, `experiment_scope`, `selection`, `pack_saved_resources`, `prepare_stage`, `pack_input` | ABI code mapping, D-F scope packing, and sCO2 `alpha` selection |
| C++ native | [geometry/geometry.cpp](../geometry/geometry.cpp), [geometry_c_api.cpp](../geometry/geometry_c_api.cpp), [numerics/fluid_properties.cpp](../numerics/fluid_properties.cpp) | `topology_row`, `phi_grid`, `calibration`, `preparation::nu_point` | Level-set field construction, geometry C API, and Nu row lookup |
| C++ native | [preprocess/preparation_df.cpp](../preprocess/preparation_df.cpp), [preparation_df_corrections.cpp](../preprocess/preparation_df_corrections.cpp), [preparation_case.cpp](../preprocess/preparation_case.cpp), [property_c_api.cpp](../preprocess/property_c_api.cpp), [quick_design_prepare_v2.cpp](../preprocess/quick_design_prepare_v2.cpp) | `topology_check`, `df_experiment_scope`, `df_select`, `geometry_index` | Fixed D-F limits, experiment scope, preparation cache, and Quick preparation |
| C++ native | [solver/solver_c_api.cpp](../solver/solver_c_api.cpp), [full_2d.cpp](../solver/full_2d.cpp), [full_3d_c_api.cpp](../solver/full_3d_c_api.cpp), [stage_run.cpp](../solver/stage_run.cpp), [quick_design_run.cpp](../solver/quick_design_run.cpp), [closure_ranges.hpp](../solver/closure_ranges.hpp), [stage_capture_2d.cpp](../solver/stage_capture_2d.cpp), [stage_capture_3d.cpp](../solver/stage_capture_3d.cpp) | Topology bounds checks, Quick Design selector, and captured topology names | Solver execution, range recording, and result capture |
| GUI and saved data | [solver/stage_saved_models.hpp](../solver/stage_saved_models.hpp), [python/physical_models/catalog.py](../python/physical_models/catalog.py) | `validate_saved_models`, `resolve_model` | Saved-model decoding; existing Diamond and Gyroid archives keep their identity |
| GUI and saved data | [python/applications/gui/ui/builders_domain.py](../python/applications/gui/ui/builders_domain.py), [quick_design_panel.py](../python/applications/gui/ui/quick_design_panel.py), [window_config.py](../python/applications/gui/ui/window_config.py), [sensitivity.py](../python/applications/gui/ui/sensitivity.py) | `combo_tpms`, `combo_qd_cell_topo` (local `combo_cell_topo`), `le_qd_topo`, `_selected_topology`, `SensitivityDialog._collect_fixed_params` | GUI topology widgets (`window_config.py` and `sensitivity.py` already validate against `TPMSType`) |
| GUI and saved data | [python/applications/design/select.py](../python/applications/design/select.py), [python/applications/optimization/multi_condition.py](../python/applications/optimization/multi_condition.py) | `NODES` | Quick Design enumeration grid and multi-condition Nu source filter |

- **Native library rebuild**: After you change C++ code or compiled model resources, rebuild and publish all four native libraries with [engineering/scripts/build_native_dependencies.py](../engineering/scripts/build_native_dependencies.py). Then restart Python.
- **Known silent fallbacks**: Update these sites so a third or unsupported topology never selects Diamond or Gyroid silently:
  - [python/cpp_interface/_native_df.py](../python/cpp_interface/_native_df.py) (`experiment_scope`): `int(topology == 'Gyroid')` maps any non-Gyroid name to `0` (`Diamond`).
  - [python/physical_models/nu_correlations.py](../python/physical_models/nu_correlations.py) (`_sco2_nu`): binary `Diamond` checks select `alpha_G` and code `1` for any non-Diamond name.
  - [python/cpp_interface/full_3d_stage.py](../python/cpp_interface/full_3d_stage.py) (`pack_input`) and [full_2d_stage.py](../python/cpp_interface/full_2d_stage.py) (`prepare_stage`): `pack_input` selects `'alpha_G'` for any nonzero topology code, and `prepare_stage` packs only `(nu.alpha_D, nu.alpha_G)`.
  - [preprocess/preparation_case.cpp](../preprocess/preparation_case.cpp) (`geometry_index`) and [solver/closure_ranges.hpp](../solver/closure_ranges.hpp) (`nu`): both fall through to Gyroid for any non-Diamond enum value.

### 4. Existing tests to extend

- **Native geometry and properties**: [tests/cpp/geometry_kernel_smoke.cpp](../tests/cpp/geometry_kernel_smoke.cpp), [tests/cpp/geometry_c_smoke.c](../tests/cpp/geometry_c_smoke.c), [tests/python/test_native_geometry.py](../tests/python/test_native_geometry.py), and [tests/python/native/test_fluid_properties.py](../tests/python/native/test_fluid_properties.py).
- **Config, catalog, and GUI selection**: [tests/python/test_main_smoke.py](../tests/python/test_main_smoke.py), [tests/python/test_compute_config_roundtrip.py](../tests/python/test_compute_config_roundtrip.py), and [tests/python/models_tm1/test_catalog.py](../tests/python/models_tm1/test_catalog.py).
  Add a negative test for an unknown topology name.
  Also test that unsupported fluids or D-F modes fail explicitly.

### 5. Validation and data

- A third TPMS topology needs physical calibration data: level-set wall fit, solid tortuosity (`chi`), per-fluid Nu fits, and fixed D-F CFD tables.
- Record data sources, bounds, and unsupported combinations in [model resources](model-resources.en.md), the [data catalog](data-catalog.en.md), and [capabilities](capabilities.en.md).
- **Physical acceptance is the user's decision.**

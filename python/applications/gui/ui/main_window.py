"""Main desktop window implementation (Main_Menu)."""
from pathlib import Path

import matplotlib
matplotlib.use("QtAgg")

from PySide6.QtWidgets import (
    QMainWindow, QMessageBox, QWidget,
)

from sjtu_tpmshx.data_types.compute_config import SCO2_P_RANGE_PA
from sjtu_tpmshx.data_types.validator import format_unit_value
from sjtu_tpmshx.model_configs.df_domain import TRAIN_L, TRAIN_T
from sjtu_tpmshx.model_configs.units import CELSIUS_ZERO_K
from sjtu_tpmshx.physical_models.tpms_calc import geometry as tpms_geometry, adaptive_grid
from sjtu_tpmshx.applications.gui.ui.fmt import duration as _fmt_dur
from sjtu_tpmshx.applications.gui.ui.window_config import LINE_EDITS, parse_field_value
from sjtu_tpmshx.applications.gui.ui.case_files import CaseFiles
from sjtu_tpmshx.applications.gui.ui.field_results import FieldResults
from sjtu_tpmshx.applications.gui.ui.result_export import ResultExport
from sjtu_tpmshx.applications.gui.ui.run_history import RunHistory
from sjtu_tpmshx.applications.gui.ui.shell_appearance import ShellAppearance
from sjtu_tpmshx.applications.gui.ui.shell_dialogs import ShellDialogs
from sjtu_tpmshx.applications.gui.ui.shell_shortcuts import ShellShortcuts
from sjtu_tpmshx.applications.gui.ui.single_run import SingleRun
from sjtu_tpmshx.applications.gui.ui.workbench import Workbench
from sjtu_tpmshx.applications.gui.ui.mixins import (
    FluidInputMixin, UIBuilderMixin, ZonePanelMixin,
)
from sjtu_tpmshx.applications.gui.ui.ui_constants import (
    TOAST_MS_MED,
)

from sjtu_tpmshx.run_control.module_ports import RunControl


class Main_Menu(ZonePanelMixin, UIBuilderMixin, FluidInputMixin, QMainWindow):
    def __init__(self, *, control=RunControl()):
        super().__init__()
        self.run_control = control
        # Central widget created directly — the old `Ui_MainWindow` /
        # `mainui.py` scaffolding (auto-generated from Designer and then
        # fully hidden at startup) has been dropped. QMainWindow auto-
        # creates menuBar() + statusBar() on first access, so no extra
        # wiring is needed here.
        self.setCentralWidget(QWidget())
        self.setWindowTitle("SJTU-TPMSHX")
        self.resize(1440, 900)
        self.setMinimumSize(900, 720)
        # Showing the window is the entry-point's responsibility —
        # `window.showMaximized()` in `applications/gui/main.py`. Keeping
        # that concern out of __init__ avoids a double show + the
        # timing race with `_maybe_show_onboarding`.

        # App icon
        import os
        from PySide6.QtGui import QIcon
        _icon_path = str(Path(__file__).resolve().parents[3] / 'assets' / 'logos' / 'sjtulogosilver.png')
        if os.path.exists(_icon_path):
            self.setWindowIcon(QIcon(_icon_path))

        # Temperature unit state — toggled through the More menu. All
        # compute paths read temperatures via `_temp_to_K(le)` which honours
        # this flag, so internal physics always runs in Kelvin regardless of
        # what the user is typing.
        self._temp_unit = 'K'

        self._close_pending = False
        self._continuous_field_spec = None
        from sjtu_tpmshx.applications.gui.controllers import ResultCache, SignalRouter
        from sjtu_tpmshx.applications.gui.ui.theme import apply_mpl_theme
        from sjtu_tpmshx.applications.gui.ui.theme_manager import ThemeManager

        # ThemeManager owns the styles consumed by FieldFactory and builders.
        # SignalRouter records connections for bulk disconnect on closeEvent.
        self.theme = ThemeManager(self)
        apply_mpl_theme()
        self.signals = SignalRouter(self)

        # Phase 5: install a process-wide FieldFactory backed by the live
        # ThemeManager so ui_builders helpers (section/row/res_row/add_row)
        # build widgets through DI rather than module globals.
        from sjtu_tpmshx.applications.gui.ui.field_factory import FieldFactory, set_default_factory
        set_default_factory(FieldFactory(self.theme))

        self.cache = ResultCache(self)
        self.case_files = CaseFiles(self)
        self.results = FieldResults(self)
        self.result_export = ResultExport(self)
        self.workbench = Workbench(self)
        self.single_run = SingleRun(self)
        self.appearance = ShellAppearance(self)
        self.dialogs = ShellDialogs(self)
        self.shortcuts = ShellShortcuts(self)
        self.history = RunHistory(self)

        from sjtu_tpmshx.applications.gui.ui.ui_builders import build_ui
        build_ui(self)
        from sjtu_tpmshx.applications.gui.ui.compute_resources import bind_resource_controls
        bind_resource_controls(self)
        self.optimization.figures_changed.connect(self.result_export.refresh_export_button)
        self._apply_accessibility()
        self._install_field_help()
        self._attach_field_validation()
        self._install_status_log()
        self.history.rebuild_recent_menu()
        self._install_undo_stack()
        from PySide6.QtCore import QTimer as _QT
        _QT.singleShot(1200, self, self.dialogs.maybe_show_onboarding)
        self._apply_shanghai_defaults()
        self.case_files.restore_session()
        self.optimization.depth.setText(self.le_Lz.text())
        for le in (self.le_Nx, self.le_Ny, self.le_Nz):
            le.textEdited.connect(self._mark_grid_edited)
            self.signals.adopt(le.textEdited, self._mark_grid_edited,
                                sender=le)
        self.shortcuts.setup()
        import os as _os_perf
        if _os_perf.environ.get('TPMSHX_PREINIT_3D', '0') == '1':
            self.workbench.schedule_3d_preinit()
        self._schedule_tpms_geometry_prewarm()
        self._wire_fluid_defaults()
        self._install_status_bar_widgets()
        self.dialogs.install_dialog_theme()
        from sjtu_tpmshx.applications.gui.ui.command_palette import install_command_palette
        install_command_palette(self)
        from sjtu_tpmshx.applications.gui.ui.coord_inspector import install_coord_inspector
        install_coord_inspector(self)
        from sjtu_tpmshx.applications.gui.ui.zone_editor import ZoneHandleManager
        self._zone_handle_mgr = ZoneHandleManager(self)
        self._zone_handle_mgr.wire()
        from sjtu_tpmshx.applications.gui.ui.field_menu import install_field_menus
        install_field_menus(self)
        self.setAcceptDrops(True)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self, self._preview_initial_geometry)

    def showEvent(self, event):
        super().showEvent(event)
        self.appearance.schedule_initial_reveal()
        self.appearance.sync_viewport_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.appearance.sync_viewport_layout()

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() and any(
                u.toLocalFile().lower().endswith('.json')
                for u in mime.urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        if not mime.hasUrls():
            event.ignore()
            return
        paths = [u.toLocalFile() for u in mime.urls()
                 if u.toLocalFile().lower().endswith('.json')]
        if not paths:
            event.ignore()
            return
        if self.case_files.load_config_path(paths[0]):
            event.acceptProposedAction()
        else:
            event.ignore()

    def _mark_grid_edited(self, _txt=None):
        self._user_edited_grid = True

    def _reset_defaults(self):
        """Reset all parameters to Shanghai Electric preset."""
        self._user_edited_grid = False
        # Tier 25: a reset changes every input, so the prior compute
        # result is stale — invalidate it (disables result tabs + export,
        # clears cached fields) before re-seeding defaults. Without this
        # the old Temperature/Pressure/Velocity/3D plots stayed visible
        # next to freshly-reset inputs.
        self.case_files.invalidate_results_for_preset_load()
        self._apply_shanghai_defaults()
        self.statusBar().showMessage("Parameters reset to Shanghai Electric preset.", TOAST_MS_MED)

    # ─────────────────────────────────────────────────────────
    #  Shanghai presets + deferred 3D init
    # ─────────────────────────────────────────────────────────
    def _apply_shanghai_defaults(self):
        """Restore Shanghai case 8 with its recorded inlet flows and states."""
        self.case_files.active_preset_name = "Shanghai (3D Gyroid)"
        self.case_files.set_shanghai_grid(is_3d=True)
        self.combo_df_mode.setCurrentIndex(self.combo_df_mode.findData('experimental'))
        from sjtu_tpmshx.applications.gui.ui.case_files import shanghai_field_defaults
        presets = shanghai_field_defaults(is_3d=True)
        # Temperature fields are authored in Kelvin. If the UI is currently
        # showing °C, convert on write so the displayed digits match the
        # user's current unit (avoids the silent 273.15 bug where a preset
        # dumps "422" into a °C field and compute then reads 695 K).
        temp_fields = {'le_TinA', 'le_TinB'}
        for attr, val in presets.items():
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                if attr in temp_fields and val != '':
                    # Unified temp setter — handles K/°C dispatch in one
                    # place so preset load can never disagree with session
                    # restore on the 273.15 sign (latent bug fixed
                    # 2026-05-05 audit).
                    self._set_temp_K(w, val)
                else:
                    w.setText(val)
            except Exception:
                pass
        # TPMS type → Gyroid (index 1)
        try:
            if hasattr(self, 'combo_tpms'):
                self.combo_tpms.setCurrentIndex(1)
        except Exception:
            pass
        # Dimensionality → 3D (index 1)
        try:
            if hasattr(self, 'combo_dim'):
                self.combo_dim.setCurrentIndex(1)
        except Exception:
            pass
        # Restore both fluids and directions without overwriting the explicit
        # Shanghai inlet values with generic fluid defaults.
        for combo_attr, idx in (('combo_dirA', 0),
                                ('combo_dirB', 3),
                                ('combo_fluidA', 0),
                                ('combo_fluidB', 1),
                                ('combo_inlet_modeA', 1), ('combo_inlet_modeB', 1)):
            try:
                c = getattr(self, combo_attr, None)
                if c is None or not (0 <= idx < c.count()):
                    continue
                if combo_attr in ('combo_fluidA', 'combo_fluidB'):
                    blocked = c.blockSignals(True)
                    c.setCurrentIndex(idx)
                    c.blockSignals(blocked)
                else:
                    c.setCurrentIndex(idx)
            except Exception:
                pass
        self.combo_sco2_nu_mode.setCurrentIndex(
            self.combo_sco2_nu_mode.findData('cfd_smooth'))
        self.case_files.set_sco2_nu_parameters({})
        self.chk_allow_extrap.setChecked(True)
        self.chk_zones.setChecked(False)
        self.combo_zone_axis.setCurrentIndex(0)
        self._grid_nx = 2
        self._zone_init_1d(3)
        self._pareto_x_decision = None
        self._pareto_y_trans_inlet = self._pareto_y_trans_outlet = 0.2
        self.optimization.use_current_condition()
        # Treat preset Nx/Ny/Nz as authoritative — without this flag the next
        # `compute_tpms` call would auto-overwrite the preset values with
        # D_h-derived suggestions (e.g. 20/20/20 → 14/25/25).
        self._user_edited_grid = True
        # Tier 25: snap the undo baseline to the just-written preset values
        # so a later manual edit's Ctrl+Z stops at the preset state, not
        # the values that preceded the preset load. Safe at init (the
        # helper no-ops when `_undo_last` is not yet built).
        self._refresh_field_validation()
        self.case_files.resync_undo_baseline()
        from sjtu_tpmshx.applications.gui.ui.builders_fluids import refresh_fluid_model_visibility
        refresh_fluid_model_visibility(self)
        self.statusBar().showMessage(
            "Loaded Shanghai Electric preset (3D, Gyroid L=7 t=0.6, 182×42×42 mm).",
            5000)

    def _schedule_tpms_geometry_prewarm(self):
        """Warm the current TPMS geometry cache off the UI thread.

        Auto-fill calls compute_tpms(). Its first geometry query builds an
        N=128 native count index. Run it in the background to reduce the
        delay on the first Auto-fill click.

        Also load the current fixed K/cF table and make one geometry-based
        prediction in the same background thread.
        """
        from PySide6.QtCore import QTimer

        def _start():
            try:
                args = (
                    self.combo_tpms.currentText(),
                    float(self.le_Lcell.text()),
                    float(self.le_t.text()),
                    float(self.le_ks.text()),
                )
            except Exception:
                return

            tpms_type, Lcell, t_mm, _ = args

            def _worker():
                try:
                    tpms_geometry(*args)
                except Exception:
                    pass
                # Warm the current fixed K/cF table with one prediction.
                try:
                    from sjtu_tpmshx.physical_models.df_surrogate.predict import predict_K_cF
                    predict_K_cF(tpms_type, float(Lcell), float(t_mm), 0.4)
                except Exception:
                    pass

            import threading
            threading.Thread(
                target=_worker, name="tpms-geometry-prewarm",
                daemon=True).start()

        QTimer.singleShot(900, self, _start)


    # ─────────────────────────────────────────────────────────
    #  TPMS geometry + time-constant helpers
    # ─────────────────────────────────────────────────────────
    def compute_tpms(self) -> bool:
        """Compute pure geometry (ε, A₀, D_h, K_ss) from TPMS inputs. Returns True on success."""
        self.statusBar().showMessage("Computing TPMS geometry...")
        try:
            from sjtu_tpmshx.applications.gui.ui.window_config import fluid_types_from_window
            geometry_model = tpms_geometry
            if 'co2' in fluid_types_from_window(self).values():
                from sjtu_tpmshx.physical_models.co2_correlations import geometry as geometry_model
            r = geometry_model(
                self.combo_tpms.currentText(),
                float(self.le_Lcell.text()),
                float(self.le_t.text()),
                float(self.le_ks.text()))
        except Exception as e:
            QMessageBox.critical(self, "TPMS Geometry Error", str(e))
            return False

        self._v_eps.setText(f"{r['epsilon']:.5f}")
        self._v_A0.setText(f"{r['A_0']:.2f}")
        self._v_Dh.setText(f"{r['D_h'] * 1000:.4f}")
        self._v_Kss.setText(f"{r['K_ss']:.5f}")
        # Suggested counts include every port/wall layer in that mesh scheme.
        # They are a starting mesh, not a grid-convergence or accuracy claim.
        is_3d = (hasattr(self, 'combo_dim')
                 and self.combo_dim.currentIndex() == 1)
        try:
            L_dom = float(self.le_L.text())
            H_dom = float(self.le_H.text())
            if is_3d:
                from sjtu_tpmshx.physical_models.grid import suggest_grid_3d
                try:
                    Lz_dom = float(self.le_Lz.text())
                except ValueError:
                    Lz_dom = 0.02
                Nx_sug, Ny_sug, Nz_sug = suggest_grid_3d(
                    L_dom, H_dom, Lz_dom, r['D_h'],
                    port_wall_refine=bool(self.combo_grid.currentData()),
                    ports=(self._fluid_config('A'), self._fluid_config('B')))
                # Only overwrite if user hasn't manually edited grid fields —
                # otherwise Auto-fill (which calls compute_tpms) would stomp
                # on user's custom Nx/Ny/Nz between TPMS Compute and Run.
                if not getattr(self, '_user_edited_grid', False):
                    self.le_Nx.setText(str(Nx_sug))
                    self.le_Ny.setText(str(Ny_sug))
                    self.le_Nz.setText(str(Nz_sug))
            else:
                Nx_sug, Ny_sug = adaptive_grid(L_dom, H_dom, r['D_h'], alpha=0.4)
                if not getattr(self, '_user_edited_grid', False):
                    self.le_Nx.setText(str(Nx_sug))
                    self.le_Ny.setText(str(Ny_sug))
        except ValueError:
            pass  # L or H not yet filled

        self.statusBar().showMessage(
            f"TPMS geometry: eps={r['epsilon']:.4f}  A_0={r['A_0']:.1f}  D_h={r['D_h']*1000:.3f}mm", 5000)
        return True


    # ─────────────────────────────────────────────────────────
    #  Inlet / Outlet helpers (unified)
    # ─────────────────────────────────────────────────────────
    _DIR_MAP = {0: '+x', 1: '-x', 2: '+y', 3: '-y', 4: '+z', 5: '-z'}


    # Auto-defaults applied when the user swaps the fluid type for a given
    # side. Values are editable starting points, not guarantees of local-state
    # validity or convergence. Temperature stored in K; the parser
    # converts to °C if the header toggle is currently °C.
    _FLUID_DEFAULTS = {
        'Air':   {'u': 20.0,  'T': 422.0, 'P': 101325.0},
        'Water': {'u': 0.15,  'T': 300.0, 'P': 101325.0},
        'sCO₂':  {'u': 2.0,   'T': 350.0, 'P': 12000000.0},
        'CO₂':   {'u': .3,    'T': 340.0, 'P': 8000000.0},
    }


    #  Status bar — persistent context strip (IDE-style)
    # ─────────────────────────────────────────────────────────

    def _refresh_status_bar(self):
        """Re-read Re / clock values and repaint the persistent status-bar
        widgets. Safe to call before the widgets exist (early startup) —
        silently no-ops."""
        if not hasattr(self, '_sb_re'):
            return
        # Re values come from the `_v_ReA`/`_v_ReB` result labels when a
        # compute has populated them. Fall back to "—" before first run.
        try:
            ra = self._v_ReA.text().strip() if hasattr(self, '_v_ReA') else '—'
            rb = self._v_ReB.text().strip() if hasattr(self, '_v_ReB') else '—'
            self._sb_re.setText(f"Re: A={ra or '—'} · B={rb or '—'}")
        except Exception:
            pass
        try:
            last = getattr(self, '_last_elapsed_s', None)
            if last is None or not self.cache.has_any_results():
                self._sb_clock.setText("⏱ —")
            else:
                mode = self.cache.get_result().diagnostics.get('mode', '2d')
                self._sb_clock.setText(
                    f"⏱ {_fmt_dur(last)} · {mode.upper()}")
        except Exception:
            pass

    def _redraw_temp_if_ready(self):
        """Re-render the temperature tab using stored compute results.
        Invoked by the Sync-colorbar toggle on canvas_temp's mini toolbar.
        """
        try:
            from sjtu_tpmshx.applications.gui.ui.plot_2d_results import redraw_result_fields
            redraw_result_fields(self)
        except Exception:
            pass

    def closeEvent(self, event):
        """Save inputs, wait for worker exit, then release views and connections."""
        if not self._close_pending:
            try:
                saved = bool(self.case_files.save_session())
            except Exception:
                saved = False
            if not saved:
                choice = QMessageBox.warning(
                    self, "会话未保存",
                    "当前输入保存失败。取消关闭可继续编辑或另存配置；"
                    "放弃将关闭软件，未保存的输入会丢失。",
                    QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Discard,
                    QMessageBox.StandardButton.Cancel)
                if choice != QMessageBox.StandardButton.Discard:
                    event.ignore()
                    return
        # Keep every task owner alive until terminal delivery and worker exit.
        # Native computation or view imports can exceed a fixed timeout.
        from sjtu_tpmshx.applications.gui.ui.background_tasks import has_active_tasks
        if has_active_tasks(self):
            event.ignore()
            if not self._close_pending:
                self._close_pending = True
                for page in (self.single_run, self.optimization, self.quick_design):
                    page.cancel()
            self.setEnabled(False)
            self.statusBar().showMessage("正在关闭 — 等待当前任务安全结束…")
            if not hasattr(self, '_close_retry_timer'):
                from PySide6.QtCore import QTimer
                self._close_retry_timer = QTimer(self)
                self._close_retry_timer.timeout.connect(self.close)
                self._close_retry_timer.start(100)
            return
        self._close_pending = True
        if hasattr(self, '_close_retry_timer'):
            self._close_retry_timer.stop()
        self.workbench.close_views()
        self.signals.disconnect_all()
        super().closeEvent(event)

    def _apply_accessibility(self):
        """Set AccessibleName/AccessibleDescription on main controls for
        screen readers. Tooltips are already AT-accessible but explicit
        accessible text lets NVDA/JAWS announce *purpose* (e.g., "Run
        heat-transfer solve") distinct from the visible label.
        """
        _A = [
            ('btn_compute', "Compute",
             "Run heat-transfer and pressure-drop solve for current parameters"),
            ('btn_more', "更多",
             "切换主题、温度单位和工作区，查看诊断、帮助与快捷键"),
            ('btn_collapse_parameters', "Parameter panel",
             "Collapse or expand the left parameter panel"),
            ('combo_tpms', "TPMS type",
             "Triply-Periodic Minimal Surface lattice type"),
            ('combo_dim', "Dimensionality",
             "Switch between 2D planar and 3D volumetric solve"),
            ('combo_fluidA', "Fluid A type",
             "Working fluid for channel A"),
            ('combo_fluidB', "Fluid B type",
             "Working fluid for channel B"),
            ('combo_dirA', "Flow direction A",
             "Principal flow axis for channel A"),
            ('combo_dirB', "Flow direction B",
             "Principal flow axis for channel B"),
            ('btn_tab_result', "Result tab",
             "Show available 2D or 3D results"),
            ('btn_tab_layout', "Layout tab",
             "Show zone layout preview"),
            ('btn_tab_pareto', "Pareto tab",
             "Show Pareto-front optimisation results"),
            ('progress', "Computation progress",
             "Current solve progress as a percentage"),
            ('zone_table', "Zone table",
             "Per-zone start, end, L, t parameters. Tab to navigate cells."),
        ]
        self.optimization.start_button.setAccessibleName("Optimize")
        self.optimization.start_button.setAccessibleDescription(
            "Start multi-condition continuous-field search with the selected optimization method")
        for attr, name, desc in _A:
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                w.setAccessibleName(name)
                w.setAccessibleDescription(desc)
            except Exception:
                continue
        # LineEdits: rough accessible name from their row label. Reads the
        # label text stripped of HTML and unit brackets so a screen reader
        # hears "domain length" rather than "L [m]". Attach only to the
        # ones we know have a corresponding stored `_lbl_<name>` or which
        # map clearly to a physical quantity.
        _INP_A11Y = {
            'le_L': ("Domain length", "Overall domain length in metres"),
            'le_H': ("Domain height", "Overall domain height in metres"),
            'le_Lz': ("Domain depth",  "Domain extent in the z direction in metres"),
            'le_Lcell': ("TPMS cell size", "Unit-cell edge length in millimetres"),
            'le_t': ("Wall thickness",  "TPMS solid wall thickness in millimetres"),
            'le_ks': ("Solid conductivity",
                      "Thermal conductivity of the solid phase, W/m-K"),
            'le_uA': ("Fluid A velocity", "Interstitial velocity, m/s"),
            'le_uB': ("Fluid B velocity", "Interstitial velocity, m/s"),
            'le_TinA': ("Fluid A inlet temperature", "Inlet temperature of fluid A"),
            'le_TinB': ("Fluid B inlet temperature", "Inlet temperature of fluid B"),
            'le_PinA': ("Fluid A inlet pressure", "Absolute inlet pressure, Pa"),
            'le_PinB': ("Fluid B inlet pressure", "Absolute inlet pressure, Pa"),
            'le_Nx': ("Grid Nx", "Number of mesh cells in x direction"),
            'le_Ny': ("Grid Ny", "Number of mesh cells in y direction"),
            'le_Nz': ("Grid Nz", "Number of mesh cells in z direction"),
        }
        for attr, (name, desc) in _INP_A11Y.items():
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                w.setAccessibleName(name)
                w.setAccessibleDescription(desc)
            except Exception:
                continue

    _CO2_PRESSURE_HELP = (
        "<br/>For sCO₂, the entire actual local pressure field must remain within "
        f"{SCO2_P_RANGE_PA[0]/1e6:g}–{SCO2_P_RANGE_PA[1]/1e6:g} MPa. Check the whole field. "
        "Allow for the computed pressure variation.")
    _FIELD_HELP = {
        'le_L': (
            "<b>Domain length <i>L</i><sub>x</sub></b> [m]<br/>"
            "Flow-direction extent of the TPMS heat-exchanger block. "
            "Excludes any external piping."),
        'le_H': (
            "<b>Domain width <i>H</i></b> [m]<br/>"
            "Cross-flow extent."),
        'le_Lz': (
            "<b>Domain depth <i>L<sub>z</sub></i></b> [m] (3D only)<br/>"
            "Out-of-plane extent. 2D runs treat Lz as unit depth."),
        'le_Lcell': (
            "<b>TPMS unit-cell edge <i>L</i></b> [mm]<br/>"
            f"Fixed CFD grid from {TRAIN_L[0]:g} to {TRAIN_L[1]:g} mm. Intermediate values use interpolation. "
            "Drives D<sub>h</sub>, porosity and permeability."),
        'le_t': (
            "<b>TPMS wall thickness <i>t</i></b> [mm]<br/>"
            f"Fixed CFD grid from {TRAIN_T[0]:g} to {TRAIN_T[1]:g} mm. Intermediate values use interpolation."),
        'le_ks': (
            "<b>Solid thermal conductivity <i>k<sub>s</sub></i></b> "
            "[W/(m·K)]<br/>"
            "SS316L ≈ 16, Inconel 625 ≈ 12, copper ≈ 390."),
        'le_uA': (
            "<b>Fluid A interstitial velocity <i>u<sub>A</sub></i></b> [m/s]"
            "<br/>孔隙内速度 = 表观速度 / ε<sub>f</sub>。"
            "Nu 的 Re 适用范围随流体类型变化，自动填充会显示对应范围提示。"),
        'le_uB': (
            "<b>Fluid B interstitial velocity <i>u<sub>B</sub></i></b> [m/s]"
            "<br/>孔隙内速度 = 表观速度 / ε<sub>f</sub>。"
            "Nu 的 Re 适用范围随流体类型变化，自动填充会显示对应范围提示。"),
        'le_TinA': (
            "<b>Fluid A inlet temperature <i>T<sub>in,A</sub></i></b><br/>"
            "内部计算使用 K；可在“更多”菜单中切换 K/°C 显示。"),
        'le_TinB': (
            "<b>Fluid B inlet temperature <i>T<sub>in,B</sub></i></b><br/>"
            "内部计算使用 K；可在“更多”菜单中切换 K/°C 显示。"),
        'le_PinA': (
            "<b>Fluid A inlet absolute pressure <i>P<sub>in,A</sub></i></b> "
            "[Pa]<br/>101 325 = 1 atm. Gauge + atm." + _CO2_PRESSURE_HELP),
        'le_PinB': (
            "<b>Fluid B inlet absolute pressure <i>P<sub>in,B</sub></i></b> "
            "[Pa]" + _CO2_PRESSURE_HELP),
        'le_Nx': (
            "<b>Grid count along <i>x</i></b><br/>"
            "端口与壁面加密方案中，输入格数包含全部加密单元；"
            "实际网格及端口覆盖情况见计算前的网格检查。"),
        'le_Ny': (
            "<b>Grid count along <i>y</i></b><br/>"
            "端口与壁面加密方案中，输入格数包含全部加密单元；"
            "实际网格及端口覆盖情况见计算前的网格检查。"),
        'le_Nz': (
            "<b>Grid count along <i>z</i></b> (3D only)<br/>"
            "端口与壁面加密方案中，输入格数包含全部加密单元；"
            "内部开口边缘会分段，每段均需足够单元，具体要求见网格检查。"),
    }


    def _attach_field_validation(self):
        """Unified blur-time unit parser + numeric validator.

        Audit C5 H4 fix (2026-05-28): replaces the pre-Phase-5 split where
        ``_attach_input_validators`` and ``_install_inline_unit_parser``
        each connected their own callback to ``editingFinished``. Qt
        fired them in connection order, so the validator saw the raw
        "5 mm" text *before* the unit parser converted it, leaving the
        ``inpError`` red border stuck on freshly-valid fields.

        The unified handler does parse → validate → apply in one slot.
        """
        self._field_validators = {}
        for attr, spec in LINE_EDITS.items():
            le = getattr(self, attr)
            cb = self._make_field_handler(le, spec)
            self._field_validators[attr] = cb
            le.editingFinished.connect(cb)
            self.signals.adopt(le.editingFinished, cb,
                                sender=le)

    def _refresh_field_validation(self):
        """Commit/validate current text without recording an undo or recent edit."""
        for callback in self._field_validators.values():
            callback()

    def _make_field_handler(self, le, spec):
        """Convert the active editor to its display unit before checking its value."""
        import math
        import re as _re_up
        base_tip = le.toolTip() or ""
        attr = spec.widget
        is_temperature = spec.family == 'temp'
        num_unit = _re_up.compile(
            r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*"
            r"([A-Za-zμΜ°][A-Za-z0-9μΜ°/·()\s]*)\s*$")

        def _cb():
            from sjtu_tpmshx.applications.gui.ui.window_config import inlet_input_active
            if not inlet_input_active(self, attr):
                le.setProperty('inpError', 'false')
                return
            # Badge repaint FIRST — the empty-text case returns early below
            # (empty is preflight's job, not a blur-time error), but the
            # group ⚠N badge must still update for exactly that case.
            # getattr-guarded: test mocks borrow this handler without the
            # badge machinery.
            getattr(self, '_kick_badge_timer', lambda: None)()
            txt = le.text().strip()
            if not txt:
                return

            from sjtu_tpmshx.applications.gui.ui.expr_eval import is_expression, eval_expr
            unit_match = num_unit.match(txt)
            value = None
            if unit_match:
                raw = float(unit_match[1])
                # Read explicit temperature units in kelvin before display rounding.
                value = parse_field_value(attr, raw, unit_match[2])
            if value is None:
                unit_match = None
                if is_expression(txt):
                    value = eval_expr(txt)

            temp_unit = getattr(self, '_temp_unit', 'K')
            family = spec.family if unit_match else 'number'
            # Other fields validate the committed text, including rounded cell counts.
            formatted = txt
            if value is not None and not is_temperature:
                formatted = format_unit_value(value, family)
            reason = ""
            if spec.positive:
                try:
                    v = value if is_temperature and value is not None else float(formatted)
                    if is_temperature and not unit_match and temp_unit == 'C':
                        v += CELSIUS_ZERO_K
                    if not math.isfinite(v):
                        reason = "Must be finite"
                    elif v <= 0:
                        if is_temperature:
                            reason = "Must be above 0 K"
                            value = None  # Keep the rejected input for the next validation.
                        else:
                            reason = "Must be > 0"
                except ValueError:
                    reason = "Must be a number"

            if value is not None:
                if is_temperature:
                    if unit_match and temp_unit == 'C':
                        value = parse_field_value(attr, raw, unit_match[2], temp_unit='C')
                    formatted = format_unit_value(value, family)
                was = le.blockSignals(True)
                le.setText(formatted)
                le.blockSignals(was)
                if unit_match:
                    unit = '°C' if is_temperature and temp_unit == 'C' else spec.unit
                    self.statusBar().showMessage(
                        f"Converted {unit_match[1]} {unit_match[2]} → {formatted} "
                        f"({unit})", 4000)
                else:
                    self.statusBar().showMessage(f"{attr}: {txt} → {formatted}", 3500)

            current = le.property('inpError')
            new = 'true' if reason else 'false'
            if current != new:
                le.setProperty('inpError', new)
                le.style().unpolish(le)
                le.style().polish(le)
            if reason:
                le.setToolTip(f"⚠ {reason}"
                              + (f"\n{base_tip}" if base_tip else ""))
                self.statusBar().showMessage(
                    f"⚠  Invalid input: {le.objectName() or 'field'}"
                    f" — {reason}", 4000)
            else:
                le.setToolTip(base_tip)

        return _cb

    def _kick_badge_timer(self):
        """Debounced accordion ⚠N badge repaint (ui-batch3 IA-4). Called on
        every field blur; 150 ms coalesces preset loads that rewrite every
        field in one burst."""
        timer = getattr(self, '_badge_timer', None)
        if timer is None:
            from PySide6.QtCore import QTimer
            from sjtu_tpmshx.applications.gui.ui.ui_builders import refresh_group_badges
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(150)
            timer.timeout.connect(lambda: refresh_group_badges(self))
            self._badge_timer = timer
        timer.start()


    _MAX_RECENT_RUNS = 5

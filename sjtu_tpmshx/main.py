import sys
from pathlib import Path as _PathBoot

# Launcher self-location (P1.8b F2): `python main.py` / `python
# sjtu_tpmshx/main.py` must work on a raw clone with no editable install,
# so the REPO ROOT goes on sys.path to make `sjtu_tpmshx.*` resolvable.
# This is launcher plumbing, not an import-style shim — the package-dir
# insert that used to support top-level style (`from solvers...`) is gone
# with the convention (openspec p18b-import-style-migration).
_PROJECT_PARENT = str(_PathBoot(__file__).resolve().parent.parent)
if _PROJECT_PARENT not in sys.path:
    sys.path.insert(0, _PROJECT_PARENT)

import matplotlib
matplotlib.use("QtAgg")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QWidget,
)

from sjtu_tpmshx.models.tpms_calc import geometry as tpms_geometry, adaptive_grid
from sjtu_tpmshx.ui.fmt import duration as _fmt_dur
from sjtu_tpmshx.ui.mixins import (RunHistoryMixin, DialogsMixin, ZonePanelMixin,
                       OptimizeUIMixin, TabViewMixin, UIBuilderMixin,
                       FluidInputMixin, RunControllerMixin, RunResultsMixin,
                       AppearanceMixin, SessionPresetsMixin,
                       ShortcutsMixin, IOActionsMixin)
from sjtu_tpmshx.ui.ui_constants import (
    TOAST_MS_BRIEF, TOAST_MS_MED,
)
from sjtu_tpmshx.ui.theme import (
    set_theme,
    apply_mpl_theme, set_density,
)

from sjtu_tpmshx._version import __version__  # noqa: E402
from sjtu_tpmshx.domain.provenance import SOURCE_ROOT, repository_revision

def _rebuild_styles(theme_name=None):
    """Refresh styles after a theme switch.

    Batch-3 (2026-06-10): the module-level style globals (``_BG``,
    ``_LBL``, ``_COMBO``, …) are retired — every consumer reads styles
    through :class:`ui.theme_manager.ThemeManager` (via
    ``ui.field_factory.default_factory().theme``). This hook persists
    the theme choice, refreshes the live window's manager when one
    exists, and re-applies the matplotlib theme.
    """
    if theme_name is not None:
        try:
            from sjtu_tpmshx.ui.theme import set_theme as _st
            _st(theme_name)
        except Exception:
            pass
    # Refresh the live window's ThemeManager if one exists.
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            for w in app.topLevelWidgets():
                if (w.__class__.__name__ == 'Main_Menu'
                        and getattr(w, 'theme', None) is not None):
                    w.theme.rebuild()
                    break
    except Exception:
        pass
    apply_mpl_theme()


# ── Auto-select delegate for zone table editing ─────────────
class Main_Menu(RunHistoryMixin, DialogsMixin, ZonePanelMixin, OptimizeUIMixin,
                TabViewMixin, UIBuilderMixin, FluidInputMixin,
                RunControllerMixin, RunResultsMixin,
                AppearanceMixin, SessionPresetsMixin,
                ShortcutsMixin, IOActionsMixin,
                QMainWindow):
    def __init__(self):
        super().__init__()
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
        # `window.showMaximized()` at the bottom of this file. Keeping
        # that concern out of __init__ avoids a double show + the
        # timing race with `_maybe_show_onboarding`.

        # App icon
        import os
        from PySide6.QtGui import QIcon
        _icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'logos', 'sjtulogosilver.png')
        if os.path.exists(_icon_path):
            self.setWindowIcon(QIcon(_icon_path))

        # Temperature unit state — toggled through the More menu. All
        # compute paths read temperatures via `_temp_to_K(le)` which honours
        # this flag, so internal physics always runs in Kelvin regardless of
        # what the user is typing.
        self._temp_unit = 'K'

        # Compute lifecycle state (P0 re-entrancy guard, 2026-05-05 audit).
        # Explicit init at construction time so `getattr(self, ..., False)`
        # fallbacks elsewhere can't accidentally surface a stale value if a
        # future refactor removes the getattr safety nets.
        self._compute_running = False
        self._compute_btn_handler = None

        # Controllers — Phase 1+2+3 of 2026-05-06 main.py refactor (#4).
        # See vault/reports/refactor/2026-05-06-main-py-refactor-plan-CN.md.
        from sjtu_tpmshx.controllers import (ComputeOrchestrator, ResultCache,
                                  SessionManager, SignalRouter)
        from sjtu_tpmshx.ui.theme_manager import ThemeManager

        # ThemeManager owns the styles consumed by FieldFactory and builders.
        # SignalRouter records connections for bulk disconnect on closeEvent.
        self.theme = ThemeManager(self)
        self.signals = SignalRouter(self)

        # Phase 5: install a process-wide FieldFactory backed by the live
        # ThemeManager so ui_builders helpers (section/row/res_row/add_row)
        # build widgets through DI rather than module globals.
        from sjtu_tpmshx.ui.field_factory import FieldFactory, set_default_factory
        set_default_factory(FieldFactory(self.theme))

        # Phase 1: solver lifecycle (refactor-p1-done).
        self.compute = ComputeOrchestrator(self)
        self.signals.connect(self.compute.started, self._on_orch_started,
                             sender=self.compute)
        self.signals.connect(self.compute.progress, self._on_orch_progress,
                             sender=self.compute)
        self.signals.connect(self.compute.iteration, self._on_orch_iteration,
                             sender=self.compute)
        self.signals.connect(self.compute.finished, self._on_orch_finished,
                             sender=self.compute)
        self.signals.connect(self.compute.error, self._on_orch_error,
                             sender=self.compute)
        self.signals.connect(self.compute.cancelled, self._on_orch_cancelled,
                             sender=self.compute)

        # Persist user sessions separately from current renderable results.
        self.sm = SessionManager(parent=self)
        self.cache = ResultCache(self)

        # Active workspace loaded from disk via SessionManager (replaces
        # the legacy inline .workspace marker read). Defaults to 'A' if
        # the marker file is missing or contains garbage.
        self._active_workspace = self.sm.get_active_workspace()

        self._build_ui()
        self._apply_accessibility()
        # Tooltips must be attached BEFORE the validators so the validator
        # captures the help HTML as its baseline tooltip (saved and later
        # restored when the field returns to a valid value).
        self._install_field_help()
        # Audit C5 H4 fix: unified parse → validate handler replaces
        # the pre-Phase-5 split (``_attach_input_validators`` +
        # ``_install_inline_unit_parser``). The single connection
        # eliminates the order-sensitive dual-editingFinished race
        # that left ``inpError`` red borders stuck on freshly-valid
        # converted fields.
        self._attach_field_validation()
        self._install_status_log()
        self._rebuild_recent_menu()
        self._install_undo_stack()
        # First-run guidance. Deferred 1.2 s after showMaximized so the window
        # is already on screen when the overlay appears.
        from PySide6.QtCore import QTimer as _QT
        _QT.singleShot(1200, self._maybe_show_onboarding)
        self._apply_shanghai_defaults()
        # Restore the last-used field state on top of the Shanghai baseline
        # so returning users see exactly what they had, while the Reset
        # button still snaps back to the canonical preset.
        self._restore_session()
        # Track manual grid edits so `compute_tpms` (invoked by Auto-fill)
        # does NOT overwrite user-customised Nx/Ny/Nz. textEdited fires on
        # keyboard input only, not on programmatic `setText`. NB: do NOT
        # reset _user_edited_grid here — `_apply_shanghai_defaults` and
        # `_restore_session` both raise it to True so preset/saved Nx/Ny/Nz
        # survive the next compute_tpms call. Resetting it here would let
        # auto-suggest stomp the user-visible defaults.
        for le in (self.le_Nx, self.le_Ny, self.le_Nz):
            le.textEdited.connect(self._mark_grid_edited)
            self.signals.adopt(le.textEdited, self._mark_grid_edited,
                                sender=le)
        self._setup_shortcuts()
        # PyVista/VTK context creation costs 1-2 s and was running 500 ms
        # after startup. Keep it lazy unless explicitly opted in for demos.
        import os as _os_perf
        if _os_perf.environ.get('TPMSHX_PREINIT_3D', '0') == '1':
            self._schedule_3d_preinit()
        self._schedule_tpms_geometry_prewarm()
        # Note: ``_install_inline_unit_parser`` was merged into
        # ``_attach_field_validation`` at line 257 (audit C5 H4 fix).
        self._wire_fluid_defaults()
        self._install_status_bar_widgets()
        self._install_dialog_theme()
        from sjtu_tpmshx.ui.command_palette import install_command_palette
        install_command_palette(self)
        from sjtu_tpmshx.ui.coord_inspector import install_coord_inspector
        install_coord_inspector(self)
        from sjtu_tpmshx.ui.zone_editor import ZoneHandleManager
        self._zone_handle_mgr = ZoneHandleManager(self)
        self._zone_handle_mgr.wire()
        from sjtu_tpmshx.ui.field_menu import install_field_menus
        install_field_menus(self)
        # Accept file drops on the whole window — users can drag a saved
        # `.json` preset onto the app to load it without going through the
        # preset combo. Only .json with the expected preset/session shape
        # is honoured; anything else is rejected with a status message.
        self.setAcceptDrops(True)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self, self._preview_initial_geometry)

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
        import json as _j_dnd
        loaded = 0
        for p in paths[:1]:  # only the first dropped file is applied
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    data = _j_dnd.load(f)
                if isinstance(data, dict) and 'line_edits' in data:
                    self._apply_user_preset(data)
                    loaded += 1
                elif isinstance(data, dict) and 'presets' in data:
                    # Full user-preset file — pick the first entry.
                    presets = list(data.get('presets') or [])
                    if presets:
                        self._apply_user_preset(presets[0])
                        loaded += 1
            except Exception as e:
                QMessageBox.warning(
                    self, "Preset Load Failed",
                    f"Could not load {p}:\n{e}")
                event.ignore()
                return
        if loaded:
            self.statusBar().showMessage(
                f"Loaded preset from {paths[0]}.", 5000)
            event.acceptProposedAction()
        else:
            self.statusBar().showMessage(
                "Dropped file did not contain a recognizable preset.", 5000)
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
        self._invalidate_results_for_preset_load()
        self._apply_shanghai_defaults()
        self.statusBar().showMessage("Parameters reset to Shanghai Electric preset.", TOAST_MS_MED)

    # ─────────────────────────────────────────────────────────
    #  Shanghai presets + deferred 3D init
    # ─────────────────────────────────────────────────────────
    def _apply_shanghai_defaults(self):
        """Restore the complete Shanghai Electric case-8 input baseline."""
        self._active_preset_name = "Shanghai (3D Gyroid)"
        self._set_shanghai_grid(is_3d=True)
        self.combo_df_mode.setCurrentIndex(self.combo_df_mode.findData('experimental'))
        from sjtu_tpmshx.ui.mixins.session_presets import shanghai_field_defaults
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
                                ('combo_fluidB', 1)):
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
        self._set_sco2_nu_parameters({})
        self.chk_allow_extrap.setChecked(True)
        self.chk_zones.setChecked(False)
        self.combo_zone_axis.setCurrentIndex(0)
        self._grid_nx = 2
        self._zone_init_1d(3)
        self._zone_grid = None
        self._pareto_x_decision = None
        self._pareto_y_trans_inlet = self._pareto_y_trans_outlet = 0.2
        # Treat preset Nx/Ny/Nz as authoritative — without this flag the next
        # `compute_tpms` call would auto-overwrite the preset values with
        # D_h-derived suggestions (e.g. 20/20/20 → 14/25/25).
        self._user_edited_grid = True
        # Tier 25: snap the undo baseline to the just-written preset values
        # so a later manual edit's Ctrl+Z stops at the preset state, not
        # the values that preceded the preset load. Safe at init (the
        # helper no-ops when `_undo_last` is not yet built).
        self._resync_undo_baseline()
        from sjtu_tpmshx.ui.builders_fluids import refresh_fluid_model_visibility
        refresh_fluid_model_visibility(self)
        self.statusBar().showMessage(
            "Loaded Shanghai Electric preset (3D, Gyroid L=7 t=0.6, 182×42×42 mm).",
            5000)

    def _schedule_3d_preinit(self):
        """Pre-initialise PyVistaQt panel 500 ms after window.show() so the
        first click on '3D View' tab is responsive. Runs on main thread but
        deferred → UI is already visible, user sees brief status blip."""
        from PySide6.QtCore import QTimer
        def _preinit():
            if getattr(self, 'canvas_3d', None) is not None:
                return
            self.statusBar().showMessage("Preparing 3D viewer…")
            QApplication.processEvents()
            try:
                self._lazy_init_3d_panel()
            except Exception as e:
                self.statusBar().showMessage(
                    f"3D viewer init deferred (will retry on first click): {e}",
                    5000)
                return
            self.statusBar().showMessage("3D viewer ready.", TOAST_MS_BRIEF)
        QTimer.singleShot(500, _preinit)

    def _schedule_tpms_geometry_prewarm(self):
        """Warm the current TPMS geometry cache off the UI thread.

        Auto-fill calls compute_tpms(), whose first exact geometry evaluation
        builds a 256^3 voxel grid. Doing that in the background keeps the
        first Auto-fill click from paying the full cold-cache cost.

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
                    from sjtu_tpmshx.df_surrogate.predict import predict_K_cF
                    predict_K_cF(tpms_type, float(Lcell), float(t_mm), 0.4)
                except Exception:
                    pass

            import threading
            threading.Thread(
                target=_worker, name="tpms-geometry-prewarm",
                daemon=True).start()

        QTimer.singleShot(900, _start)


    # ─────────────────────────────────────────────────────────
    #  TPMS geometry + time-constant helpers
    # ─────────────────────────────────────────────────────────
    def compute_tpms(self) -> bool:
        """Compute pure geometry (ε, A₀, D_h, K_ss) from TPMS inputs. Returns True on success."""
        self.statusBar().showMessage("Computing TPMS geometry...")
        try:
            r = tpms_geometry(
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
                from sjtu_tpmshx.models.grid import suggest_grid_3d
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
    }


    # Detached 3D panel — right-click the "3D View" tab offers "Open in
    # new window". The panel widget is reparented to a borderless QDialog
    # so users on multi-monitor setups can drag it to a second screen.
    # Closing the detached window reattaches to the card.
    _3d_detached_window = None


    # ─── D17 — generic any-canvas detach ─────────────────────────────
    _detached_canvases = {}


    # ─────────────────────────────────────────────────────────
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
            mode = self._active_compute_mode()
            if last is None:
                self._sb_clock.setText("⏱ —")
            else:
                self._sb_clock.setText(
                    f"⏱ {_fmt_dur(last)} · {mode.upper()}")
        except Exception:
            pass

    def _redraw_temp_if_ready(self):
        """Re-render the temperature tab using stored compute results.
        Invoked by the Sync-colorbar toggle on canvas_temp's mini toolbar.
        """
        try:
            from sjtu_tpmshx.ui.plot_2d_results import redraw_result_fields
            redraw_result_fields(self)
        except Exception:
            pass

    def _validate_inputs_preflight(self):
        """Return True if all session inputs pass the validator; False +
        show a modal listing every bad field otherwise. Reuses the
        `inpError` dynamic property set by `_attach_input_validators`."""
        bad = []
        for name in self._SESSION_LINE_EDITS:
            le = getattr(self, name, None)
            if le is None:
                continue
            if le.property('inpError') == 'true':
                label = (le.accessibleName() or name)
                val = le.text() or '(empty)'
                bad.append((label, name, val))
            elif not le.text().strip():
                # Empty strict-positive fields are bad too.
                label = (le.accessibleName() or name)
                bad.append((label, name, '(empty)'))
        if not bad:
            return True
        # Escape user-typed text before interpolating into RichText HTML.
        # Without escape, a user typing `<img>` / `&` / quote characters
        # into a LineEdit would either break the table layout or render
        # arbitrary HTML in the modal. (Qt RichText doesn't run JS but
        # still parses tags; we escape every cell to be safe.) — 2026-04-29
        import html as _html_esc
        rows = "".join(
            f"<tr><td style='padding:4px 14px 4px 0;'>{_html_esc.escape(str(lbl))}</td>"
            f"<td style='padding:4px 14px 4px 0; color:#6b7280;'>"
            f"<code>{_html_esc.escape(str(name))}</code></td>"
            f"<td style='padding:4px 0; color:#DC2626;'>"
            f"{_html_esc.escape(str(val))}</td></tr>"
            for lbl, name, val in bad[:30])
        html = (
            f"<h3 style='margin:0 0 8px 0;'>"
            f"{len(bad)} 个无效输入</h3>"
            "<p style='margin:0 0 10px 0; color:#6b7280;'>"
            "运行计算前请先修正下列字段；悬停字段可查看原因。</p>"
            "<table style='border-collapse:collapse;'>"
            f"{rows}</table>")
        msg = QMessageBox(self)
        msg.setWindowTitle("检查输入")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(html)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
        # Focus the first invalid field so Tab navigation works from there.
        first_attr = bad[0][1]
        le = getattr(self, first_attr, None)
        if le is not None:
            from sjtu_tpmshx.ui.ui_builders import reveal_parameter
            reveal_parameter(self, le)
            try:
                le.setFocus(); le.selectAll()
            except Exception:
                pass
        return False

    def _preflight_grid(self):
        """Grid-legality preflight (runs after field-level validator).

        Previews the refined grid, checks inlet/outlet cell coverage, and
        warns when Richardson doubling would blow up runtime. Returns True
        if OK to continue (no errors AND user acknowledged any warnings).
        """
        from sjtu_tpmshx.ui.preflight import FluidCfg, compute_preflight

        # robustness-hardening (2026-07-03): the old _f/_i fell back to
        # 0.0/0 on unparseable text, so preflight ran its geometry checks
        # against a phantom L=0 domain (wrong errors / silence). Core
        # fields now abort preflight with the invalid-input modal instead.
        _parse_fails: list = []

        def _f(attr, default=0.0, core=False):
            le = getattr(self, attr, None)
            if le is None:
                return default
            try:
                return float(le.text())
            except (TypeError, ValueError):
                if core:
                    _parse_fails.append(attr)
                return default

        def _i(attr, default=0, core=False):
            le = getattr(self, attr, None)
            if le is None:
                return default
            try:
                return int(le.text())
            except (TypeError, ValueError):
                if core:
                    _parse_fails.append(attr)
                return default

        L = _f('le_L', core=True); H = _f('le_H', core=True)
        Lz = _f('le_Lz')
        Nx = _i('le_Nx', core=True); Ny = _i('le_Ny', core=True)
        Nz = _i('le_Nz', 1)
        if _parse_fails:
            QMessageBox.warning(
                self, "检查输入",
                "以下字段无法解析为数字，预检无法进行：\n  "
                + "\n  ".join(_parse_fails)
                + "\n\n请先修正后再计算。")
            return False
        is_3d = (hasattr(self, 'combo_dim')
                 and self.combo_dim.currentIndex() == 1)

        def _cfg(which):
            try:
                raw = self._fluid_config(which)
            except Exception:
                return None
            return FluidCfg(
                dir=raw['dir'],
                in_ctr=raw['in_ctr'], in_w=raw['in_w'],
                out_ctr=raw.get('out_ctr', raw['in_ctr']),
                out_w=raw.get('out_w', raw['in_w']),
                z_in_ctr=raw.get('in_z_ctr'),
                z_in_w=raw.get('in_z_w'),
                z_out_ctr=raw.get('out_z_ctr'),
                z_out_w=raw.get('out_z_w'))

        def _t_k(attr):
            le = getattr(self, attr, None)
            if le is None or not le.text().strip():
                return None
            try:
                return self._temp_to_K(le)
            except (TypeError, ValueError):
                return None

        # Geometry/D-F coverage is separate from Nu and calibration limits.
        # Hard invalid geometry blocks; soft findings join the grid report.
        _geom_warnings = []
        try:
            from sjtu_tpmshx.domain.validator import validate_geometry as _vg
            _geom_warnings = _vg(
                L, H, (Lz if is_3d else None),
                _f('le_Lcell', 7.0), _f('le_t', 0.6),
                ks=_f('le_ks', 16.0), is_3d=is_3d)
        except ValueError as _ge:
            QMessageBox.critical(
                self, "几何输入不合法", str(_ge))
            return False
        except Exception:
            pass  # validator itself failing must not block a run

        report = compute_preflight(
            L=L, H=H, Lz=Lz, Nx=Nx, Ny=Ny, Nz=Nz,
            is_3d=is_3d, wall_refine_3d=False,
            port_wall_refine=bool(self.combo_grid.currentData()),
            fluid_A=_cfg('A'), fluid_B=_cfg('B'),
            T_inA=_t_k('le_TinA'), T_inB=_t_k('le_TinB'))
        for _w in _geom_warnings:
            _msg = getattr(_w, 'message', None) or str(_w)
            if getattr(_w, 'severity', 'warning') == 'error':
                report.errors.append(_msg)
            else:
                report.warnings.append(_msg)

        if not report.errors and not report.warnings:
            # Still surface info in the status bar so the user knows the
            # effective grid size even when everything passes.
            if report.info:
                self.statusBar().showMessage(
                    " · ".join(report.info[:2]), 6000)
            return True

        import html as _h

        def _rows(items, color):
            return "".join(
                f"<li style='margin:4px 0; color:{color};'>{_h.escape(s)}</li>"
                for s in items)

        sev_html = []
        if report.errors:
            sev_html.append(
                f"<h4 style='margin:8px 0 4px 0; color:#DC2626;'>"
                f"{len(report.errors)} error"
                f"{'s' if len(report.errors) != 1 else ''}</h4>"
                f"<ul style='margin:0;'>{_rows(report.errors, '#DC2626')}</ul>")
        if report.warnings:
            sev_html.append(
                f"<h4 style='margin:8px 0 4px 0; color:#B45309;'>"
                f"{len(report.warnings)} warning"
                f"{'s' if len(report.warnings) != 1 else ''}</h4>"
                f"<ul style='margin:0;'>{_rows(report.warnings, '#B45309')}</ul>")
        if report.info:
            sev_html.append(
                f"<h4 style='margin:8px 0 4px 0; color:#6b7280;'>Info</h4>"
                f"<ul style='margin:0;'>{_rows(report.info, '#6b7280')}</ul>")

        html = (
            "<h3 style='margin:0 0 8px 0;'>Grid preflight</h3>"
            "<p style='margin:0 0 8px 0; color:#6b7280;'>"
            "Reviewed wall-refine fit, inlet/outlet coverage, "
            "and Richardson budget.</p>" + "".join(sev_html))

        msg = QMessageBox(self)
        msg.setWindowTitle("Grid preflight")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(html)
        if report.errors:
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
            return False
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        return msg.exec() == QMessageBox.StandardButton.Yes

    def closeEvent(self, event):
        """Single close-event handler — covers all three concerns:

        1. Persist session (legacy contract — was lost when a duplicate
           closeEvent at L4399 silently shadowed this one prior to the
           2026-05-20 UI sweep merge).
        2. Tear down PyVistaQt GL context before Qt destroys the widgets
           (moved here from the deleted L4399 dup).
        3. Bulk-disconnect router-tracked signal connections (Phase 3
           2026-05-06 #4 — belt-and-braces against bound-method slots
           that close over ``self`` and outlive C++ widget destruction).
        """
        # Keep every task owner alive until terminal delivery and worker exit.
        # A JIT sweep/candidate batch may exceed any fixed timeout.
        opt_worker = getattr(self, '_opt_worker', None)
        qd_dialog = getattr(self, '_qd_dialog', None)
        qd_worker = getattr(qd_dialog, '_qd_worker', None)
        from sjtu_tpmshx.ui.background_tasks import has_active_tasks
        if has_active_tasks(self):
            event.ignore()
            self._close_pending = True
            self.compute.cancel()
            if opt_worker is not None:
                opt_worker.requestInterruption()
            if qd_worker is not None:
                qd_dialog.close()
            self.setEnabled(False)
            self.statusBar().showMessage("正在关闭 — 等待计算、优化和快速设计安全结束…")
            if not hasattr(self, '_close_retry_timer'):
                from PySide6.QtCore import QTimer
                self._close_retry_timer = QTimer(self)
                self._close_retry_timer.timeout.connect(self.close)
                self._close_retry_timer.start(100)
            return
        if hasattr(self, '_close_retry_timer'):
            self._close_retry_timer.stop()
        # 1. Persist session first — `_save_session` failure used to be a
        #    silent pass; now surface to statusBar so users know.
        try:
            self._save_session()
        except Exception as _e_save:
            try:
                self.statusBar().showMessage(
                    f"Warning: session save failed — {_e_save}", 6000)
            except Exception:
                pass
        # 2b. Neutralise any floating/detached canvas windows BEFORE Qt
        #     tears them down. Each was given a closeEvent override that
        #     calls _reattach_* → self.statusBar(); firing that during
        #     main-window destruction dereferences a half-dead C++
        #     object. Replace the override with a plain accept and close
        #     them now. Added 2026-05-20 UI sweep (Tier 21).
        _dw3d = getattr(self, '_3d_detached_window', None)
        if _dw3d is not None:
            try:
                _dw3d.closeEvent = lambda ev: ev.accept()
                _dw3d.close()
            except Exception:
                pass
            self._3d_detached_window = None
        for _k, _dw in list(getattr(self, '_detached_canvases', {}).items()):
            if _dw is not None:
                try:
                    _dw.closeEvent = lambda ev: ev.accept()
                    _dw.close()
                except Exception:
                    pass
        try:
            self._detached_canvases = {}
        except Exception:
            pass
        # 3. PyVistaQt GL context teardown — must happen before Qt
        #    destroys child widgets, otherwise vtkRenderWindow leaks.
        panel = getattr(self, 'canvas_3d', None)
        if panel is not None:
            try:
                panel.cleanup()
            except Exception:
                pass
        # 5. Bulk-disconnect router-tracked signal connections.
        try:
            if getattr(self, 'signals', None) is not None:
                self.signals.disconnect_all()
        except Exception:
            pass
        super().closeEvent(event)

    def _maybe_show_onboarding(self):
        """First-run only: surface a 3-step guidance dialog pointing at the
        parameter panel, Compute button, and result tabs. Dismissal writes
        `.first_run_done` in the user data directory; future launches skip.
        """
        import os as _os_ob
        flag = self.sm.base_dir / '.first_run_done'
        if _os_ob.path.exists(flag):
            return
        # Headless guard: a fresh checkout has no flag file, and a modal
        # exec() on the offscreen platform blocks forever (no one to click
        # OK — this hung CI at the 45-min job kill). Skip the dialog but
        # still write the flag.
        if QApplication.instance().platformName() == 'offscreen':
            pass
        else:
            msg = QMessageBox(self)
            msg.setWindowTitle("欢迎使用 SJTU-TPMSHX")
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText(
                "快速上手\n\n"
                "1.  左侧工况参数 — 在几何、边界、求解三个页签填写参数。\n"
                "2.  开始计算 — 使用面板底部蓝色按钮；"
                "优化设计页面可运行 qNEHVI 多目标优化。\n"
                "3.  场图结果 — 选择温度、压力或速度，"
                "三维计算还可切换到三维视图；提示可在诊断详情中查看。\n\n"
                "顶栏“载入”可打开工况和预设；"
                "“更多”中可切换主题与 K/°C 单位。"
                "本提示只显示一次。")
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
        try:
            with open(flag, 'w', encoding='utf-8') as _f:
                _f.write("1")
        except Exception:
            pass  # best-effort; next launch may show again

    # ─────────────────────────────────────────────────────────
    #  Help surface — About dialog + keyboard shortcut cheat sheet
    # ─────────────────────────────────────────────────────────
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
            ('_opt_btn', "Optimize",
             "Start qNEHVI Bayesian multi-objective search — runs for minutes to hours"),
            ('progress', "Computation progress",
             "Current solve progress as a percentage"),
            ('zone_table', "Zone table",
             "Per-zone start, end, L, t parameters. Tab to navigate cells."),
        ]
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

    def _show_about(self):
        """Report version, commit, Python/Qt/NumPy/SciPy versions, author."""
        lines = [f"<b>SJTU-TPMSHX</b> v{__version__}"]
        commit = (repository_revision(SOURCE_ROOT)['revision'] or '')[:7]
        if commit:
            lines.append(f"Commit: <code>{commit}</code>")
        lines.append("")
        lines.append("TPMS heat-exchanger homogenised solver for SJTU.")
        lines.append(
            "2D/3D compressible D-F + SIMPLE with qNEHVI Bayesian zoning search.")
        lines.append("")
        import sys as _sys_ab, platform as _plat
        try:
            from PySide6 import __version__ as _qt_ver
        except Exception:
            _qt_ver = "?"
        try:
            import numpy as _np_ab
            _np_v = _np_ab.__version__
        except Exception:
            _np_v = "?"
        try:
            import scipy as _sp_ab
            _sp_v = _sp_ab.__version__
        except Exception:
            _sp_v = "?"
        try:
            import matplotlib as _mpl_ab
            _mpl_v = _mpl_ab.__version__
        except Exception:
            _mpl_v = "?"
        lines.append(f"Python {_sys_ab.version.split()[0]} · {_plat.system()} {_plat.release()}")
        lines.append(
            f"PySide6 {_qt_ver} · NumPy {_np_v} · SciPy {_sp_v} · Matplotlib {_mpl_v}")
        lines.append("")
        lines.append("Author: alexlu997 &lt;alexlu997@hotmail.com&gt;")
        lines.append("Repo: github.com/alexlu997/SJTU-TPMSHX-TM1")
        msg = QMessageBox(self)
        msg.setWindowTitle("About SJTU-TPMSHX")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText("<br>".join(lines))
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()


    def _show_quick_tour(self):
        """Re-show the first-run onboarding dialog (clears the flag)."""
        import os as _os_qt
        flag = self.sm.base_dir / '.first_run_done'
        try:
            if _os_qt.path.exists(flag):
                _os_qt.remove(flag)
        except Exception:
            pass
        self._maybe_show_onboarding()


    _CO2_PRESSURE_HELP = (
        "<br/>For sCO₂, the entire actual local pressure field must remain within "
        "7.9–16 MPa; an inlet value in range alone is insufficient. "
        "Allow for the computed pressure variation.")
    _FIELD_HELP = {
        'le_L': (
            "<b>Domain length <i>L</i></b> [m]<br/>"
            "Flow-direction extent of the TPMS heat-exchanger block. "
            "Excludes any external piping."),
        'le_H': (
            "<b>Domain width <i>H</i></b> [m]<br/>"
            "Cross-flow extent."),
        'le_Lz': (
            "<b>Domain depth <i>L<sub>z</sub></i></b> [m] (3D only)<br/>"
            "Out-of-plane extent. 2D runs treat Lz as unit depth."),
        'le_Lcell': (
            "<b>TPMS unit-cell edge <i>L<sub>cell</sub></i></b> [mm]<br/>"
            "Fixed-CFD grid: 4–8 mm; values between nodes are interpolated. "
            "Drives D<sub>h</sub>, porosity and permeability."),
        'le_t': (
            "<b>TPMS wall thickness <i>t</i></b> [mm]<br/>"
            "Fixed-CFD grid: 0.3–0.6 mm; values between nodes are interpolated."),
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


    # Audit C5 Phase 4 (L-b, 2026-05-28): unit-parsing config + the
    # canonical positive-numeric set live in ``domain/validator.py``
    # so future scripts / widgets can read the same canonical map.
    # The class still surfaces the two names as attributes for the
    # ``_attach_field_validation`` / ``_make_field_handler`` callers.
    from sjtu_tpmshx.domain.validator import (
        FIELD_UNITS as _FIELD_UNITS,
        POSITIVE_FIELDS as _POSITIVE_FIELDS,
    )

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
        all_fields = self._POSITIVE_FIELDS | self._FIELD_UNITS.keys() | set(self._SESSION_LINE_EDITS)
        for attr in all_fields:
            le = getattr(self, attr, None)
            if le is None:
                continue
            fam_target = self._FIELD_UNITS.get(attr)
            is_positive = attr in self._POSITIVE_FIELDS
            cb = self._make_field_handler(le, attr, fam_target, is_positive)
            le.editingFinished.connect(cb)
            self.signals.adopt(le.editingFinished, cb,
                                sender=le)

    def _make_field_handler(self, le, attr, fam_target, is_positive):
        """Build the per-field blur callback: parse → validate → apply.

        ``fam_target`` is ``self._FIELD_UNITS.get(attr)`` (an
        ``(family, target_unit)`` tuple, or ``None`` if the field has
        no unit-parsing rule).  ``is_positive`` flips on the
        strictly-positive numeric validation.

        Unit parsing + formatting delegate to
        :func:`domain.validator.parse_field_value` /
        :func:`domain.validator.format_unit_value`.
        """
        import re as _re_up
        base_tip = le.toolTip() or ""
        num_unit = _re_up.compile(
            r"\s*([+-]?\d+\.?\d*(?:[eE][+-]?\d+)?)\s*"
            r"([A-Za-zμΜ°/··]+[A-Za-z0-9/··]*)\s*$")

        from sjtu_tpmshx.domain.validator import (
            parse_field_value as _domain_parse_field,
            format_unit_value as _domain_format,
        )

        def _cb():
            # Badge repaint FIRST — the empty-text case returns early below
            # (empty is preflight's job, not a blur-time error), but the
            # group ⚠N badge must still update for exactly that case.
            # getattr-guarded: test mocks borrow this handler without the
            # badge machinery.
            getattr(self, '_kick_badge_timer', lambda: None)()
            txt = le.text().strip()
            if not txt:
                return

            # ── 1. PARSE — convert "5 mm" → "5e-3" etc. when the field
            #    has a unit family. Validator then sees the canonical
            #    value, never the raw "5 mm" string.
            if fam_target is not None:
                fam, target = fam_target
                m = num_unit.match(txt)
                if m:
                    try:
                        raw_val = float(m.group(1))
                    except ValueError:
                        raw_val = None
                    if raw_val is not None:
                        unit_txt = m.group(2)
                        new_val = _domain_parse_field(
                            attr, raw_val, unit_txt,
                            temp_unit=getattr(self, '_temp_unit', 'K'))
                        if new_val is not None:
                            fmt = _domain_format(new_val, fam)
                            # Suppress our own re-fire of editingFinished.
                            was = le.blockSignals(True)
                            le.setText(fmt)
                            le.blockSignals(was)
                            self.statusBar().showMessage(
                                f"Converted {m.group(1)} {unit_txt} → {fmt} "
                                f"({target or fam})", 4000)
                            txt = fmt

            # Expressions share this commit with unit parsing and validation.
            # The undo/history slots run afterwards and record the final text.
            from sjtu_tpmshx.ui.expr_eval import is_expression, eval_expr
            if is_expression(txt):
                value = eval_expr(txt)
                if value is not None:
                    converted = _domain_format(value, 'number')
                    was = le.blockSignals(True)
                    le.setText(converted)
                    le.blockSignals(was)
                    self.statusBar().showMessage(f"{attr}: {txt} → {converted}", 3500)
                    txt = converted

            # ── 2. VALIDATE — strictly-positive numeric check for the
            #    positive-set fields. Non-positive fields skip this.
            bad = False
            reason = ""
            if is_positive:
                try:
                    v = float(txt)
                    if fam_target is not None and fam_target[0] == 'temp':
                        if getattr(self, '_temp_unit', 'K') == 'C':
                            v += 273.15
                    import math as _math
                    # robustness-hardening: float("nan") parses fine and
                    # `nan <= 0` is False — nan/inf sailed through here.
                    if not _math.isfinite(v):
                        bad = True
                        reason = "Must be finite"
                    elif v <= 0:
                        bad = True
                        reason = "Must be above 0 K" if fam_target and fam_target[0] == 'temp' else "Must be > 0"
                except Exception:
                    bad = True
                    reason = "Must be a number"

            # ── 3. APPLY — flip inpError + tooltip + status-bar warn.
            current = le.property('inpError')
            new = 'true' if bad else 'false'
            if current != new:
                le.setProperty('inpError', new)
                le.style().unpolish(le)
                le.style().polish(le)
            if bad:
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
            from sjtu_tpmshx.ui.ui_builders import refresh_group_badges
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(150)
            timer.timeout.connect(lambda: refresh_group_badges(self))
            self._badge_timer = timer
        timer.start()


    _MAX_RECENT_RUNS = 5

    def _lazy_init_3d_panel(self):
        """Create PyVistaQt panel on first 3D tab click. ~1-2 s hit amortised.

        2026-05-20 UI sweep: added reentrance + already-init guards.
        Previously a rapid double-click on the 3D tab (or a tab switch
        while ``ThreeDVisPanel()`` was mid-construction) could spawn a
        second ``ThreeDVisPanel`` whose ``replaceWidget`` call no-op'd
        (placeholder already cleared by the first call), leaving the
        first real panel orphaned in the layout while ``self.canvas_3d``
        pointed at the second instance — a leaked VTK GL context plus a
        layout-stale widget.
        """
        if getattr(self, '_vis3d_import_error', None):
            return      # Offscreen / disabled — leave placeholder
        if getattr(self, 'canvas_3d', None) is not None:
            return      # Already initialised by a prior call.
        if getattr(self, '_lazy_init_3d_running', False):
            return      # In flight on another (nested) event loop call.
        self._lazy_init_3d_running = True
        try:
            try:
                from sjtu_tpmshx.ui.panel_vis_3d import ThreeDVisPanel
                panel = ThreeDVisPanel()
            except Exception as e:
                self._vis3d_import_error = str(e)
                return
            # Swap placeholder → real panel in the card layout
            card = self._canvas_cards.get('3d')
            if card is None:
                return
            placeholder = getattr(self, '_canvas_3d_placeholder', None)
            lay = card.layout()
            if placeholder is not None and lay is not None:
                lay.replaceWidget(placeholder, panel)
                placeholder.deleteLater()
            self._canvas_3d_placeholder = None
            self.canvas_3d = panel
            # Fit the 3D card to the scroll viewport now that the real panel is
            # in (avoids the fixed 1144 px card overflowing → scrollbar).
            _fit = getattr(self, '_fit_3d_card_to_viewport', None)
            if _fit is not None:
                try:
                    _fit()
                except Exception:
                    pass
            self.statusBar().showMessage("3D view initialised.", TOAST_MS_BRIEF)
        finally:
            self._lazy_init_3d_running = False


# ── Entry point ───────────────────────────────────────────────
def _apply_app_font(app):
    """Use the platform's native sans-serif interface fonts."""
    from sjtu_tpmshx.ui.typography import apply_app_font
    return apply_app_font(app)


def main():
    """Start the desktop interface from source or an installed launcher."""
    # High-DPI + font smoothing before QApplication instantiation
    from PySide6.QtCore import Qt as _Qt
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        _Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    import os as _os_main
    _os_main.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '1')
    app = QApplication.instance() or QApplication(sys.argv)

    from sjtu_tpmshx.controllers.user_storage import load_appearance_settings
    from sjtu_tpmshx.ui.theme import set_accent_override
    saved = load_appearance_settings()
    for name, setter in (('theme', set_theme), ('density', set_density),
                         ('accent', set_accent_override)):
        if name in saved:
            setter(saved[name])
    # Force grayscale anti-aliasing to eliminate sub-pixel color fringing
    from PySide6.QtGui import QFont
    font = app.font()
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)
    _apply_app_font(app)
    apply_mpl_theme()
    _rebuild_styles()
    window = Main_Menu()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

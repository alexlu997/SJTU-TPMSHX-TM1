"""Select, prepare and detach workbench views."""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from sjtu_tpmshx.applications.gui.ui.ui_constants import TOAST_MS_BRIEF, TOAST_MS_SHORT
from sjtu_tpmshx.applications.gui.ui.theme import get_theme


class Workbench:
    def __init__(self, window):
        self.window = window
        self.active_tab = "layout"
        self.result_view = "2d"
        self.split_tabs = None
        self.detached_canvases = {}
        self.detached_volume = None
        self.volume_parent_layout = None
        self.volume_ready = False
        self.volume_error = False
        self.rendered_slices = False
        self.requested_3d_action = None
        self.requested_3d_result = None
        self.requested_3d_background = False
        self.import_error = None
        self.creating_volume = False
        self.imports_ready = False
        self.import_worker = None
        self.last_hover_time = 0.0

    def is_idle(self):
        return self.import_worker is None and not self.creating_volume

    def prepare_3d(self, callback):
        """Import the 3D module once. Deliver callbacks on the GUI thread."""
        from .background_tasks import ViewImports
        from .compute_resources import refresh_resource_availability

        if self.import_error or self.imports_ready:
            callback()
            return
        if self.import_worker is None:
            self.import_worker = ViewImports(self)
            self.import_worker.prepared.connect(callback)
            refresh_resource_availability(self.window)
            self.import_worker.start()
        else:
            self.import_worker.prepared.connect(callback)

    def schedule_3d_preinit(self):
        """Prepare the optional 3D view before its first use."""
        from PySide6.QtCore import QTimer

        window = self.window

        def ready():
            self.create_volume_panel()
            if not window._close_pending and self.import_error:
                window.statusBar().showMessage(f"3D viewer unavailable: {self.import_error}", 5000)

        def start():
            if window.canvas_3d is None and not window._close_pending:
                window.statusBar().showMessage("Preparing 3D viewer…")
                self.prepare_3d(ready)

        QTimer.singleShot(500, window, start)

    def create_volume_panel(self):
        """Replace the placeholder with the prepared panel on the GUI thread."""
        from .compute_resources import refresh_resource_availability

        window = self.window
        if window._close_pending or self.import_error or window.canvas_3d is not None or self.creating_volume:
            return
        self.creating_volume = True
        refresh_resource_availability(window)
        try:
            from .panel_vis_3d import ThreeDVisPanel
            panel = ThreeDVisPanel()
            panel.restore_color_ranges(getattr(window, '_volume_color_ranges', {}).get('results', {}))
        except Exception as exc:
            self.import_error = str(exc)
        else:
            placeholder = window._canvas_3d_placeholder
            window._canvas_cards['3d'].layout().replaceWidget(placeholder, panel)
            placeholder.deleteLater()
            window._canvas_3d_placeholder = None
            window.canvas_3d = panel
            window._fit_3d_card_to_viewport()
            window.statusBar().showMessage("3D view initialised.", TOAST_MS_BRIEF)
        finally:
            self.creating_volume = False
            refresh_resource_availability(window)

    def close_views(self):
        """Release detached windows and OpenGL panels before the main window closes."""
        for dialog in (self.detached_volume, *self.detached_canvases.values()):
            if dialog is not None:
                dialog.closeEvent = lambda event: event.accept()
                dialog.close()
        self.detached_volume = None
        self.detached_canvases.clear()
        for panel in (self.window.canvas_3d, self.window.optimization.volume_panel):
            if panel is not None:
                panel.cleanup()

    def show_quick_design(self):
        window = self.window
        if not self.requested_3d_background:
            self.requested_3d_result = None
            self.requested_3d_action = None
        window.page_stack.setCurrentWidget(window.quick_design)
        window.btn_quick_design.setStyleSheet(window._PTAB_ON)
        for button in (window.btn_tab_layout, window.btn_tab_result, window.btn_tab_pareto):
            button.setStyleSheet(window._PTAB_OFF if button.isEnabled() else window._PTAB_DISABLED)

    def canvas_tab_availability(self):
        """Return availability from result state, independent of UI widgets."""
        window = self.window
        mode = window.results.summary().get('mode')
        is_3d = (mode == '3d' if mode is not None else
                 hasattr(window, 'combo_dim') and window.combo_dim.currentIndex() == 1)
        has_2d = (self.rendered_slices if is_3d else
                  window.cache.has_results('2d'))
        has_3d = (is_3d and window.cache.has_results('3d')
                  and not self.volume_error)
        return {
            'layout': True,
            'temp': has_2d,
            'pres': has_2d,
            'vel': has_2d,
            '3d': has_3d,
            'pareto': True,
            '2d_view': has_2d,
            'result': has_2d or has_3d,
        }

    def update_tab_visibility(self):
        """Show/hide tab buttons based on available results and current mode.

        Fields require a cached 2D result or rendered 3D slices; the volume
        view requires a cached 3D result and loads its panel on demand.

        If the currently active tab disappears, fall back to Layout.
        Safe to call before ui_builders finishes — returns if buttons absent.
        """
        window = self.window
        if not hasattr(window, 'btn_tab_layout'):
            return  # Tab buttons not yet constructed (early _on_dim_changed)
        rules = self.canvas_tab_availability()
        btn_map = {
            'layout':  window.btn_tab_layout,
            'pareto':  window.btn_tab_pareto,
            'result':  getattr(window, 'btn_tab_result', None),
        }
        for key, btn in btn_map.items():
            enabled = rules[key]
            if btn is None:
                continue
            btn.setEnabled(enabled)
            if not enabled and key != 'layout':
                btn.setStyleSheet(window._PTAB_DISABLED)
            elif enabled and btn.styleSheet() == window._PTAB_DISABLED:
                btn.setStyleSheet(window._PTAB_OFF)
        for key in ('temp', 'pres', 'vel', '3d'):
            card = window._canvas_cards.get(key)
            if card is not None and not rules[key]:
                card.hide()
        # Keep the 2D field state and visible selector gated together.
        _combo = getattr(window, 'combo_2d_field', None)
        if _combo is not None:
            _combo.setEnabled(rules.get('2d_view', False))
        # ui-batch4: the segmented 温度/速度/压力 buttons gate with the tab
        # just like the (now hidden) combo did.
        # ui-plan3-workbench: the field seg is only meaningful while the 2D
        # rendering is showable; the 2D|3D toggle gates each side on its
        # own rule.
        _seg = getattr(window, '_2d_field_seg', None)
        if _seg is not None:
            _seg.setEnabled(rules.get('2d_view', False))
        _rv = getattr(window, '_result_view_btns', None)
        if _rv:
            _rv['2d'].setEnabled(rules.get('2d_view', False))
            _rv['3d'].setEnabled(rules.get('3d', False))
            # Snap the toggle to the only available side.
            if rules.get('3d') and not rules.get('2d_view'):
                self.result_view = '3d'
            elif rules.get('2d_view') and not rules.get('3d'):
                self.result_view = '2d'
            paint = getattr(window, '_paint_result_seg', None)
            if paint is not None:
                paint()
        if not rules.get(self.active_tab, True):
            if window.page_stack.currentWidget() is window.quick_design:
                self.active_tab = 'layout'
            else:
                self.switch_tab('layout')
        refresh_navigation = getattr(window, '_refresh_workbench_navigation', None)
        if refresh_navigation is not None:
            refresh_navigation()

    def split_with_current(self, tab):
        """Enter split-view pairing the currently active tab with `tab`.
        No-op if the shifted tab is the one already active (user would
        end up pairing X with X, which is just a single view). The split
        view persists until any normal (non-shifted) tab click."""
        window = self.window
        if window.page_stack.currentWidget() is window.quick_design:
            self.switch_tab(tab)
            return
        # Resolve aggregate result keys to their underlying canvas card.
        if tab == 'result':
            tab = ('3d' if self.result_view == '3d'
                   else self.resolve_2d_view_card())
        if tab == '2d_view':
            tab = self.resolve_2d_view_card()
        cur = self.active_tab
        if cur == '2d_view':
            cur = self.resolve_2d_view_card()
        if cur is None or cur == tab:
            return
        # Both tabs must be enabled (e.g., can't split into temp before
        # Compute has populated it).
        available = self.canvas_tab_availability()
        if not (available.get(cur, False) and available.get(tab, False)):
            window.statusBar().showMessage(
                "Split view requires both tabs to have data.", 4000)
            return
        if tab == '3d' and not self.volume_ready:
            self.request_3d_view(lambda: self.split_with_current(tab))
            return
        from sjtu_tpmshx.applications.gui.ui.plot_2d_results import ensure_result_plot
        for key in (cur, tab):
            if key in ('temp', 'pres', 'vel') and not ensure_result_plot(window, key):
                return
        from sjtu_tpmshx.applications.gui.ui.builders_canvas import _layout_split_cards
        _layout_split_cards(window, [cur, tab])
        # Paint the visible workbench tabs for the two selected cards.
        for k, btn in (('layout', window.btn_tab_layout),
                       ('pareto', window.btn_tab_pareto)):
            if k in (cur, tab):
                btn.setStyleSheet(window._PTAB_ON)
            else:
                btn.setStyleSheet(window._PTAB_OFF)
        if any(k in ('temp', 'pres', 'vel', '3d') for k in (cur, tab)):
            window.btn_tab_result.setStyleSheet(window._PTAB_ON)
        else:
            window.btn_tab_result.setStyleSheet(window._PTAB_OFF)
        self.active_tab = cur  # keep primary tab as "active"
        window.statusBar().showMessage(
            f"Split view: {cur} ↔ {tab}. Click any tab to return "
            "to single view.", 5000)

    def resolve_2d_view_card(self) -> str:
        """Return the card for the selected 2D field."""
        window = self.window
        _combo = getattr(window, 'combo_2d_field', None)
        sel = _combo.currentText() if _combo is not None else "Temperature"
        return {
            "Temperature":   'temp',
            "Velocity |U|":  'vel',
            "Pressure":      'pres',
        }.get(sel, 'temp')

    def toggle_result_view(self):
        """Open the selected result view or switch between its available 2D and 3D views."""
        window = self.window
        if (window.page_stack.currentWidget() is window.quick_design
                or self.active_tab not in ('temp', 'pres', 'vel', '3d')):
            if window.btn_tab_result.isEnabled():
                self.switch_tab('result')
            return
        other = '3d' if self.result_view == '2d' else '2d'
        if window._result_view_btns[other].isEnabled():
            self.result_view = other
            self.switch_tab('result')

    def request_3d_view(self, on_ready=None, *, background=False):
        """Load the current volume on demand; discard obsolete requests."""
        window = self.window
        from time import perf_counter
        result = window.cache.get_result('3d')
        if result is None:
            return
        self.requested_3d_action = on_ready or (lambda: self.switch_tab('3d'))
        self.requested_3d_background = background
        if self.requested_3d_result is result:
            return
        self.requested_3d_result = result
        started = perf_counter()
        window.statusBar().showMessage("正在准备三维视图…")

        def ready():
            if self.requested_3d_result is not result:
                return
            self.requested_3d_result = None
            action = self.requested_3d_action
            self.requested_3d_action = None
            if (window._close_pending
                    or window.cache.get_result('3d') is not result):
                return
            from sjtu_tpmshx.applications.gui.ui.plot_3d_results import finalize_plots_3d
            try:
                self.volume_ready = bool(finalize_plots_3d(window))
            except Exception as exc:
                self.volume_ready = False
                window.statusBar().showMessage(f"三维视图加载失败：{exc}", 10000)
            self.volume_error = not self.volume_ready
            result.metadata.setdefault('timings_s', {})['volume_display'] = perf_counter() - started
            if self.volume_ready:
                window.canvas_3d.show()
                window.cache.mark_drawn('3d')
                action()
            else:
                window.statusBar().showMessage(
                    "三维视图不可用；场图、计算结果和数据导出仍可使用。", 10000)
            self.update_tab_visibility()

        self.prepare_3d(ready)

    def switch_tab(self, tab: str, *, foreground=True):
        window = self.window
        from_quick_design = window.page_stack.currentWidget() is window.quick_design
        if from_quick_design and not foreground:
            return
        # 2026-05-09 Phase 4 — '2d_view' is the merged Temperature/Velocity/
        # Pressure tab. Resolve to the underlying card key based on the
        # combo_2d_field selection. The legacy 'temp'/'pres'/'vel' keys
        # still work directly (hotkeys, code-side routing) and reverse-sync
        # the combo so the dropdown reflects the active field.
        _combo = getattr(window, 'combo_2d_field', None)
        _combo_label_map = {
            'temp': "Temperature",
            'vel':  "Velocity |U|",
            'pres': "Pressure",
        }
        # ui-plan3-workbench: 'result' aggregates 2D fields + the 3D volume;
        # self.result_view picks the rendering, then the resolved key
        # flows through the legacy machinery untouched.
        if tab == 'result':
            tab = ('3d' if self.result_view == '3d'
                   else '2d_view')
        if tab == '2d_view':
            sel = _combo.currentText() if _combo is not None else "Temperature"
            tab = {
                "Temperature":   'temp',
                "Velocity |U|":  'vel',
                "Pressure":      'pres',
            }.get(sel, 'temp')
        elif tab in _combo_label_map and _combo is not None:
            target = _combo_label_map[tab]
            if _combo.currentText() != target:
                # Update the selector without requesting the same switch again.
                _combo.blockSignals(True)
                _combo.setCurrentText(target)
                _combo.blockSignals(False)
                window._paint_2d_seg()
        if tab == '3d' and not self.volume_ready:
            if self.canvas_tab_availability().get('3d'):
                self.request_3d_view()
            return
        if not self.requested_3d_background:
            self.requested_3d_result = None
            self.requested_3d_action = None
        # Exiting split view — a plain tab click means "back to single".
        if self.split_tabs:
            self.split_tabs = None
            from sjtu_tpmshx.applications.gui.ui.builders_canvas import _relayout_canvas_cards
            _relayout_canvas_cards(window, 1)
        if not self.canvas_tab_availability().get(tab, False):
            tab = 'layout'

        if from_quick_design:
            window.page_stack.setCurrentWidget(window._splitter)
            window.btn_quick_design.setStyleSheet(window._PTAB_OFF)
        same_tab = tab == self.active_tab and not from_quick_design
        self.active_tab = tab
        from sjtu_tpmshx.applications.gui.ui.builders_canvas import refresh_field_controls
        if hasattr(window, '_field_phase_seg'):
            refresh_field_controls(window)

        # Refresh result controls even when the same canvas stays visible.
        # Tab-switch fast path: no-op only when the active card is visible.
        # Preview can draw layout while the startup-hidden layout card is
        # still marked active, so visibility must be part of the guard.
        if same_tab and not self.split_tabs:
            card = getattr(window, '_canvas_cards', {}).get(tab)
            if card is not None and card.isVisible() and (
                    tab not in ('temp', 'pres', 'vel') or tab in window.cache.get_drawn_tabs()):
                return

        if tab in ('temp', 'pres', 'vel'):
            from sjtu_tpmshx.applications.gui.ui.plot_2d_results import ensure_result_plot
            if not ensure_result_plot(window, tab):
                window._canvas_cards[tab].hide()
                self.switch_tab('layout')
                return
        tabs = ('temp', 'pres', 'vel', 'layout', 'pareto', '3d')
        drawn = window.cache.get_drawn_tabs()
        # Publish the complete tab state in one repaint batch. Dispatching
        # processEvents between hide/show let a newer click run inside this
        # call, then the older call showed its stale target over the new one.
        _scroll = getattr(window, '_canvas_scroll', None)
        _viewport = _scroll.viewport() if _scroll is not None else None
        _updates_enabled = _viewport.updatesEnabled() if _viewport is not None else False
        if _viewport is not None:
            _viewport.setUpdatesEnabled(False)
        try:
            for key in tabs:
                card = window._canvas_cards.get(key)
                if key != tab and card:
                    card.hide()
                    if self.active_tab != tab:
                        return
            for key, btn in (('layout', window.btn_tab_layout),
                             ('pareto', window.btn_tab_pareto)):
                btn.setStyleSheet(window._PTAB_ON if key == tab else window._PTAB_OFF)
            # Field controls only accompany a 2D result card.
            _fs = getattr(window, '_2d_field_seg', None)
            if _fs is not None:
                _fs.setVisible(tab in ('temp', 'pres', 'vel'))
            scale = getattr(window, 'chk_shared_pressure_scale', None)
            if scale is not None:
                scale.setVisible(tab == 'pres')
            # Reverse-sync aggregate result navigation to the actual card.
            _btn_res = getattr(window, 'btn_tab_result', None)
            if _btn_res is not None:
                if tab in ('temp', 'pres', 'vel', '3d'):
                    self.result_view = '3d' if tab == '3d' else '2d'
                    paint = getattr(window, '_paint_result_seg', None)
                    if paint is not None:
                        paint()
                    _btn_res.setStyleSheet(window._PTAB_ON)
                elif _btn_res.isEnabled():
                    _btn_res.setStyleSheet(window._PTAB_OFF)
                else:
                    _btn_res.setStyleSheet(window._PTAB_DISABLED)

            target_card = window._canvas_cards.get(tab)
            showed_any = False
            if target_card and (tab == 'pareto'
                                or window.cache.has_any_results()
                                or tab in drawn):
                target_card.show()
                # A widget showEvent can synchronously choose another tab.
                if self.active_tab != tab:
                    return
                fit = getattr(window, '_fit_3d_card_to_viewport', None)
                if fit is not None:
                    fit()
                showed_any = True
            elif tab == '3d' and target_card:
                target_card.hide()

            if hasattr(window, '_empty_state_label'):
                window._empty_state_label.setVisible(not showed_any)
            if window.cache.has_any_results():
                try:
                    window.results.refresh_summary()
                except Exception:
                    pass
            # Footer follows the result family.
            try:
                from sjtu_tpmshx.applications.gui.ui.builders_sidebar import update_result_sidebar_visibility
                update_result_sidebar_visibility(window)
            except Exception:
                pass
            window._hover_label.setText("")
            refresh_navigation = getattr(window, '_refresh_workbench_navigation', None)
            if refresh_navigation is not None:
                refresh_navigation()
        finally:
            if _viewport is not None:
                _viewport.setUpdatesEnabled(_updates_enabled)

    def on_hover(self, event):
        """Show data value at mouse position on contour plots."""
        window = self.window
        # Throttle to ~30 Hz: this label-updating handler fires on every
        # motion_notify_event and runs an axes scan + grid-index lookup +
        # QLabel.setText + a coord_inspector update. At 144 Hz mouse polling
        # that churned >100 KB/s of hover work; the eye can't read faster
        # than ~30 Hz anyway.
        from time import monotonic as _now_hover
        _t_hover = _now_hover()
        if _t_hover - self.last_hover_time < 0.033:
            return
        self.last_hover_time = _t_hover
        # Feed the dockable coord inspector first — it reads the full
        # compute-results stack, not just the single canvas field.
        inspector = getattr(window, '_coord_inspector', None)
        if inspector is not None and inspector.isVisible():
            try:
                inspector.update_from_event(event)
            except Exception:
                pass

        if event.inaxes is None or event.xdata is None or event.ydata is None:
            window._hover_label.setText("")
            return

        # Find which canvas this event belongs to
        canvas = event.canvas
        hd = getattr(canvas, '_hover_data', None)
        if not hd:
            return

        # Convert mm coordinates to grid indices
        x_mm, y_mm = event.xdata, event.ydata
        L, H = hd['L'], hd['H']
        Nx, Ny = hd['Nx'], hd['Ny']
        from sjtu_tpmshx.applications.gui.ui.matplotlib_canvas import cell_index_mm
        import numpy as np
        i = cell_index_mm(x_mm, hd.get('dx_arr', np.full(Nx, L / Nx)))
        j = cell_index_mm(y_mm, hd.get('dy_arr', np.full(Ny, H / Ny)))

        # Find which subplot the mouse is in. Cache the flattened axes
        # list on the canvas so we do not rebuild it on every motion —
        # the axes objects survive `fig.clear()` (clear destroys the
        # axes children but a *new* clear/replot would update
        # `canvas.axes` and invalidate the cache; we invalidate by
        # comparing the id of `canvas.axes`).
        _cache_key = id(canvas.axes)
        _cached = getattr(canvas, '_axes_flat_cache', None)
        if _cached is None or _cached[0] != _cache_key:
            axes = [ax for row in canvas.axes for ax in row]
            canvas._axes_flat_cache = (_cache_key, axes)
        else:
            axes = _cached[1]
        ax_idx = -1
        for k, ax in enumerate(axes):
            if event.inaxes is ax:
                ax_idx = k
                break

        if ax_idx < 0 or ax_idx >= len(hd['fields']):
            window._hover_label.setText(f"x={x_mm:.1f}mm, y={y_mm:.1f}mm")
            return

        val = hd['fields'][ax_idx][i, j]
        name = hd['names'][ax_idx]
        unit = hd['unit']
        # Render "P_A" → "P<sub>A</sub>" (real subscript, no literal underscore).
        # _hover_label is RichText (set at creation), so the tag is honoured.
        if '_' in name:
            _h, _sub = name.split('_', 1)
            name = f"{_h}<sub>{_sub}</sub>"
        fmt = hd['fmt']
        window._hover_label.setText(
            f"x={x_mm:.1f}mm, y={y_mm:.1f}mm  |  Cell ({i},{j}): {name} = {val:{fmt}} {unit}")

    def detach_3d_window(self):
        """Reparent canvas_3d into a standalone QDialog and show it."""
        window = self.window
        panel = getattr(window, 'canvas_3d', None)
        if panel is None:
            QMessageBox.information(
                window, "3D panel", "3D panel is not initialised yet. "
                "Click the 3D tab first.")
            return
        if self.detached_volume is not None:
            self.detached_volume.raise_()
            self.detached_volume.activateWindow()
            return
        from PySide6.QtWidgets import QDialog, QVBoxLayout
        dlg = QDialog(window)
        dlg.setWindowTitle("SJTU-TPMSHX — 3D View (detached)")
        dlg.resize(1200, 800)
        dlg.setModal(False)
        dlg.setStyleSheet(f"QDialog{{background:{get_theme()['bg']};}}")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(4, 4, 4, 4); lay.setSpacing(0)
        # Remember previous parent & layout position so re-docking restores
        # the widget to exactly where it came from.
        self.volume_parent_layout = None
        card = window._canvas_cards.get('3d') if hasattr(window, '_canvas_cards') else None
        if card is not None:
            self.volume_parent_layout = card.layout()
        panel.setParent(None)
        lay.addWidget(panel)
        self.detached_volume = dlg

        # Wire reattach on close instead of destroying the window, so the
        # OpenGL context lives inside a Qt object continuously.
        # 2026-05-20 UI sweep (Tier 21): guard the reattach against the
        # main-window-teardown path. The dialog is parented to `window`,
        # so when the main window closes Qt also destroys this dialog
        # and fires this override — at which point `window` is mid-destroy
        # and `window.statusBar()` inside `_reattach_3d_window` would
        # dereference a deleted C++ object. closeEvent (step 2) now
        # neutralises the override before app teardown, but keep a
        # try/except here as belt-and-braces.
        def _on_close(ev):
            try:
                self.reattach_3d_window()
            except (RuntimeError, AttributeError):
                pass
            ev.accept()
        dlg.closeEvent = _on_close
        dlg.show()
        window.statusBar().showMessage(
            "3D view detached — close the window to re-dock.", 5000)

    def reattach_3d_window(self):
        """Put canvas_3d back into its original card and close the dialog."""
        window = self.window
        dlg = self.detached_volume
        panel = getattr(window, 'canvas_3d', None)
        if dlg is None or panel is None:
            return
        # Move the widget back into its old layout before destroying dialog.
        prev_layout = self.volume_parent_layout
        if prev_layout is not None:
            panel.setParent(None)
            prev_layout.addWidget(panel)
        self.detached_volume = None
        # Avoid recursion: clear the overridden closeEvent before invoking it.
        try:
            dlg.close()
        except Exception:
            pass
        window.statusBar().showMessage("3D view re-docked.", TOAST_MS_SHORT)

    def canvas_for_key(self, key):
        window = self.window
        mapping = {
            'temp':   getattr(window, 'canvas_temp', None),
            'pres':   getattr(window, 'canvas_pres', None),
            'vel':    getattr(window, 'canvas_vel', None),
            'layout': getattr(window, 'canvas_layout', None),
            'pareto': window.optimization.pareto_canvas,
        }
        return mapping.get(key)

    def detach_canvas(self, key):
        """Reparent any 2D matplotlib canvas into a floating QDialog.
        3D uses the dedicated path (`_detach_3d_window`) because
        PyVistaQt's OpenGL context needs more careful handling."""
        window = self.window
        if key == '3d':
            self.detach_3d_window()
            return
        canvas = self.canvas_for_key(key)
        if canvas is None:
            return
        if key in ('temp', 'pres', 'vel'):
            from sjtu_tpmshx.applications.gui.ui.plot_2d_results import ensure_result_plot
            if not ensure_result_plot(window, key):
                return
        if self.detached_canvases.get(key) is not None:
            self.detached_canvases[key].raise_()
            return
        from PySide6.QtWidgets import QDialog, QVBoxLayout
        dlg = QDialog(window)
        dlg.setWindowTitle(f"SJTU-TPMSHX — {key} (detached)")
        dlg.resize(1200, 800)
        dlg.setModal(False)
        dlg.setStyleSheet(f"QDialog{{background:{get_theme()['bg']};}}")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(4, 4, 4, 4); lay.setSpacing(0)
        card = window._canvas_cards.get(key)
        prev_layout = card.layout() if card is not None else None
        canvas._prev_layout = prev_layout
        canvas.setParent(None)
        lay.addWidget(canvas)
        self.detached_canvases[key] = dlg

        def _on_close(ev, _k=key):
            # Tier 21: same dead-window guard as the 3D detach path.
            try:
                self.reattach_canvas(_k)
            except (RuntimeError, AttributeError):
                pass
            ev.accept()
        dlg.closeEvent = _on_close
        dlg.show()
        window.statusBar().showMessage(
            f"{key} canvas detached — close the window to re-dock.", 5000)

    def reattach_canvas(self, key):
        window = self.window
        if key == '3d':
            self.reattach_3d_window()
            return
        dlg = self.detached_canvases.pop(key, None)
        canvas = self.canvas_for_key(key)
        if dlg is None or canvas is None:
            return
        prev_layout = getattr(canvas, '_prev_layout', None)
        if prev_layout is not None:
            canvas.setParent(None)
            prev_layout.addWidget(canvas)
        try:
            dlg.close()
        except Exception:
            pass
        window.statusBar().showMessage(f"{key} canvas re-docked.", TOAST_MS_SHORT)

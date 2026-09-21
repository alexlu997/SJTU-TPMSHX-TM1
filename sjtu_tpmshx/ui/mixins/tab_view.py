"""Tab-switching and detach/reattach handlers for ``Main_Menu``.

Extracted verbatim from the ``main`` god object: 2D/3D tab visibility &
switching, coordinate hover read-out, and the
detach/reattach of the 3D window and 2D canvases. UI-only -- no solver
or numeric path. Adopted via
``class Main_Menu(..., TabViewMixin, ..., QMainWindow)``; methods resolve
on the live window through the MRO so external wiring keeps working.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from sjtu_tpmshx.ui.ui_constants import TOAST_MS_SHORT
from sjtu_tpmshx.ui.theme import get_theme


class TabViewMixin:
    """Tab / canvas / detach-reattach UI handlers."""

    def _canvas_tab_availability(self):
        """Return availability from result state, independent of UI widgets."""
        mode = getattr(self, '_diag_summary', {}).get('mode')
        is_3d = (mode == '3d' if mode is not None else
                 hasattr(self, 'combo_dim') and self.combo_dim.currentIndex() == 1)
        has_2d = (getattr(self, '_rendered_3d_slices', False) if is_3d else
                  getattr(self, '_has_results_2d', False))
        has_3d = is_3d and getattr(self, '_3d_view_ready', False)
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

    def _update_tab_visibility(self):
        """Show/hide tab buttons based on available results and current mode.

        Rules (finalized 2026-04-21):
          - Layout : always
          - Temp/Pres/Vel : 2D mode AND _has_results_2d
          - 3D View : 3D mode AND _3d_view_ready (panel populated; U1 2026-06-28
            — was _has_results_3d, but that is now result-presence and stays
            True after a soft viz-fail to keep the result exportable)
          - Pareto  : _has_pareto (independent of mode)

        If the currently active tab disappears, fall back to Layout.
        Safe to call before ui_builders finishes — returns if buttons absent.
        """
        if not hasattr(self, 'btn_tab_layout'):
            return  # Tab buttons not yet constructed (early _on_dim_changed)
        rules = self._canvas_tab_availability()
        btn_map = {
            'layout':  self.btn_tab_layout,
            'pareto':  self.btn_tab_pareto,
            'result':  getattr(self, 'btn_tab_result', None),
        }
        for key, btn in btn_map.items():
            enabled = rules[key]
            if btn is None:
                continue
            btn.setEnabled(enabled)
            if not enabled and key != 'layout':
                btn.setStyleSheet(self._PTAB_DISABLED)
        for key in ('temp', 'pres', 'vel', '3d'):
            card = self._canvas_cards.get(key)
            if card is not None and not rules[key]:
                card.hide()
        # Keep the 2D field state and visible selector gated together.
        _combo = getattr(self, 'combo_2d_field', None)
        if _combo is not None:
            _combo.setEnabled(rules.get('2d_view', False))
        # ui-batch4: the segmented 温度/速度/压力 buttons gate with the tab
        # just like the (now hidden) combo did.
        # ui-plan3-workbench: the field seg is only meaningful while the 2D
        # rendering is showable; the 2D|3D toggle gates each side on its
        # own rule.
        _seg = getattr(self, '_2d_field_seg', None)
        if _seg is not None:
            _seg.setEnabled(rules.get('2d_view', False))
        _rv = getattr(self, '_result_view_btns', None)
        if _rv:
            _rv['2d'].setEnabled(rules.get('2d_view', False))
            _rv['3d'].setEnabled(rules.get('3d', False))
            # Snap the toggle to the only available side.
            if rules.get('3d') and not rules.get('2d_view'):
                self._result_view = '3d'
            elif rules.get('2d_view') and not rules.get('3d'):
                self._result_view = '2d'
            paint = getattr(self, '_paint_result_seg', None)
            if paint is not None:
                paint()
        # Fall back to Layout if active tab just became disabled
        if not rules.get(getattr(self, '_active_tab', 'layout'), True):
            self._switch_tab('layout')
        refresh_navigation = getattr(self, '_refresh_workbench_navigation', None)
        if refresh_navigation is not None:
            refresh_navigation()

    def _split_with_current(self, tab):
        """Enter split-view pairing the currently active tab with `tab`.
        No-op if the shifted tab is the one already active (user would
        end up pairing X with X, which is just a single view). The split
        view persists until any normal (non-shifted) tab click."""
        # Resolve aggregate result keys to their underlying canvas card.
        if tab == 'result':
            tab = ('3d' if getattr(self, '_result_view', '2d') == '3d'
                   else self._resolve_2d_view_card())
        if tab == '2d_view':
            tab = self._resolve_2d_view_card()
        cur = getattr(self, '_active_tab', None)
        if cur == '2d_view':
            cur = self._resolve_2d_view_card()
        if cur is None or cur == tab:
            return
        # Both tabs must be enabled (e.g., can't split into temp before
        # Compute has populated it).
        available = self._canvas_tab_availability()
        if not (available.get(cur, False) and available.get(tab, False)):
            self.statusBar().showMessage(
                "Split view requires both tabs to have data.", 4000)
            return
        from sjtu_tpmshx.ui.builders_canvas import _layout_split_cards
        _layout_split_cards(self, [cur, tab])
        # Paint the visible workbench tabs for the two selected cards.
        for k, btn in (('layout', self.btn_tab_layout),
                       ('pareto', self.btn_tab_pareto)):
            if k in (cur, tab):
                btn.setStyleSheet(self._PTAB_ON)
            else:
                btn.setStyleSheet(self._PTAB_OFF)
        if any(k in ('temp', 'pres', 'vel', '3d') for k in (cur, tab)):
            self.btn_tab_result.setStyleSheet(self._PTAB_ON)
        else:
            self.btn_tab_result.setStyleSheet(self._PTAB_OFF)
        self._active_tab = cur  # keep primary tab as "active"
        self.statusBar().showMessage(
            f"Split view: {cur} ↔ {tab}. Click any tab to return "
            "to single view.", 5000)

    def _resolve_2d_view_card(self) -> str:
        """Map the '2d_view' tab key onto the currently-selected underlying
        field card ('temp'/'vel'/'pres'). Added 2026-05-20 UI sweep so
        ``_split_with_current`` and other code paths share one resolver.
        """
        _combo = getattr(self, 'combo_2d_field', None)
        sel = _combo.currentText() if _combo is not None else "Temperature"
        return {
            "Temperature":   'temp',
            "Velocity |U|":  'vel',
            "Pressure":      'pres',
        }.get(sel, 'temp')

    def _toggle_result_view(self):
        """Ctrl+4 (ui-shortcuts-persist) — flip 结果 between 2D and 3D.

        From outside the result family it just enters 结果 on the current
        `_result_view`; inside, it flips to the other side unless that side
        is gated off (no results / wrong dimensionality) — then no-op.
        """
        if getattr(self, '_active_tab', None) not in ('temp', 'pres',
                                                      'vel', '3d'):
            btn = getattr(self, 'btn_tab_result', None)
            if btn is None or not btn.isEnabled():
                return
            self._switch_tab('result')
            return
        cur = getattr(self, '_result_view', '2d')
        other = '3d' if cur == '2d' else '2d'
        rv = getattr(self, '_result_view_btns', None)
        if rv and not rv[other].isEnabled():
            return
        self._result_view = other
        self._switch_tab('result')

    def _switch_tab(self, tab: str):
        # 2026-05-09 Phase 4 — '2d_view' is the merged Temperature/Velocity/
        # Pressure tab. Resolve to the underlying card key based on the
        # combo_2d_field selection. The legacy 'temp'/'pres'/'vel' keys
        # still work directly (hotkeys, code-side routing) and reverse-sync
        # the combo so the dropdown reflects the active field.
        _combo = getattr(self, 'combo_2d_field', None)
        _combo_label_map = {
            'temp': "Temperature",
            'vel':  "Velocity |U|",
            'pres': "Pressure",
        }
        # ui-plan3-workbench: 'result' aggregates 2D fields + the 3D volume;
        # window._result_view picks the rendering, then the resolved key
        # flows through the legacy machinery untouched.
        if tab == 'result':
            tab = ('3d' if getattr(self, '_result_view', '2d') == '3d'
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
                # Block the change-signal so we don't recurse via _switch_tab
                _combo.blockSignals(True)
                _combo.setCurrentText(target)
                _combo.blockSignals(False)
        # Exiting split view — a plain tab click means "back to single".
        if getattr(self, '_split_tabs', None):
            self._split_tabs = None
            from sjtu_tpmshx.ui.builders_canvas import _relayout_canvas_cards
            _relayout_canvas_cards(self, 1)
        if not self._canvas_tab_availability().get(tab, False):
            tab = 'layout'

        # Tab-switch fast path: no-op only when the active card is visible.
        # Preview can draw layout while the startup-hidden layout card is
        # still marked active, so visibility must be part of the guard.
        if tab == getattr(self, '_active_tab', None) \
                and not getattr(self, '_split_tabs', None):
            card = getattr(self, '_canvas_cards', {}).get(tab)
            if card is not None and card.isVisible():
                return

        self._active_tab = tab
        from sjtu_tpmshx.ui.builders_canvas import refresh_field_controls
        if hasattr(self, '_field_phase_seg'):
            refresh_field_controls(self)
        tabs = ('temp', 'pres', 'vel', 'layout', 'pareto', '3d')
        drawn = getattr(self, '_drawn_tabs', set())
        # Publish the complete tab state in one repaint batch. Dispatching
        # processEvents between hide/show let a newer click run inside this
        # call, then the older call showed its stale target over the new one.
        _scroll = getattr(self, '_canvas_scroll', None)
        _viewport = _scroll.viewport() if _scroll is not None else None
        _updates_enabled = _viewport.updatesEnabled() if _viewport is not None else False
        if _viewport is not None:
            _viewport.setUpdatesEnabled(False)
        try:
            for key in tabs:
                card = self._canvas_cards.get(key)
                if key != tab and card:
                    card.hide()
                    if self._active_tab != tab:
                        return
            for key, btn in (('layout', self.btn_tab_layout),
                             ('pareto', self.btn_tab_pareto)):
                btn.setStyleSheet(self._PTAB_ON if key == tab else self._PTAB_OFF)
            # Field controls only accompany a 2D result card.
            _fs = getattr(self, '_2d_field_seg', None)
            if _fs is not None:
                _fs.setVisible(tab in ('temp', 'pres', 'vel'))
            # Reverse-sync aggregate result navigation to the actual card.
            _btn_res = getattr(self, 'btn_tab_result', None)
            if _btn_res is not None:
                if tab in ('temp', 'pres', 'vel', '3d'):
                    self._result_view = '3d' if tab == '3d' else '2d'
                    paint = getattr(self, '_paint_result_seg', None)
                    if paint is not None:
                        paint()
                    _btn_res.setStyleSheet(self._PTAB_ON)
                elif _btn_res.isEnabled():
                    _btn_res.setStyleSheet(self._PTAB_OFF)
                else:
                    _btn_res.setStyleSheet(self._PTAB_DISABLED)

            target_card = self._canvas_cards.get(tab)
            showed_any = False
            if target_card and (tab == 'pareto'
                                or getattr(self, '_has_results', False)
                                or tab in drawn):
                target_card.show()
                # A widget showEvent can synchronously choose another tab.
                if self._active_tab != tab:
                    return
                fit = getattr(self, '_fit_3d_card_to_viewport', None)
                if fit is not None:
                    fit()
                showed_any = True
            elif tab == '3d' and target_card:
                target_card.hide()

            if hasattr(self, '_empty_state_label'):
                self._empty_state_label.setVisible(not showed_any)
            if hasattr(self, '_result_summary_bar') \
                    and getattr(self, '_has_results', False):
                try:
                    self._update_result_summary()
                except Exception:
                    pass
            # Sidebar follows the result family.
            try:
                from sjtu_tpmshx.ui.builders_canvas import update_result_sidebar_visibility
                update_result_sidebar_visibility(self)
            except Exception:
                pass
            self._hover_label.setText("")
            refresh_navigation = getattr(self, '_refresh_workbench_navigation', None)
            if refresh_navigation is not None:
                refresh_navigation()
        finally:
            if _viewport is not None:
                _viewport.setUpdatesEnabled(_updates_enabled)

    def _on_hover(self, event):
        """Show data value at mouse position on contour plots."""
        # Throttle to ~30 Hz: this label-updating handler fires on every
        # motion_notify_event and runs an axes scan + grid-index lookup +
        # QLabel.setText + a coord_inspector update. At 144 Hz mouse polling
        # that churned >100 KB/s of hover work; the eye can't read faster
        # than ~30 Hz anyway.
        from time import monotonic as _now_hover
        _t_hover = _now_hover()
        if _t_hover - getattr(self, '_last_hover_t', 0.0) < 0.033:
            return
        self._last_hover_t = _t_hover
        # Feed the dockable coord inspector first — it reads the full
        # compute-results stack, not just the single canvas field.
        inspector = getattr(self, '_coord_inspector', None)
        if inspector is not None and inspector.isVisible():
            try:
                inspector.update_from_event(event)
            except Exception:
                pass

        if event.inaxes is None or event.xdata is None or event.ydata is None:
            self._hover_label.setText("")
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
        from sjtu_tpmshx.ui.matplotlib_canvas import cell_index_mm
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
            self._hover_label.setText(f"x={x_mm:.1f}mm, y={y_mm:.1f}mm")
            return

        val = hd['fields'][ax_idx][i, j]
        name = hd['names'][ax_idx]
        unit = hd['unit']
        # Render "P_A" → "P<sub>A</sub>" (real subscript, no literal underscore).
        # _hover_label is RichText (set at creation), so the tag is honoured.
        if '_' in name:
            _h, _sub = name.split('_', 1)
            name = f"{_h}<sub>{_sub}</sub>"
        self._hover_label.setText(
            f"x={x_mm:.1f}mm, y={y_mm:.1f}mm  |  {name} = {val:.2f} {unit}")

    def _detach_3d_window(self):
        """Reparent canvas_3d into a standalone QDialog and show it."""
        panel = getattr(self, 'canvas_3d', None)
        if panel is None:
            QMessageBox.information(
                self, "3D panel", "3D panel is not initialised yet. "
                "Click the 3D tab first.")
            return
        if getattr(self, '_3d_detached_window', None) is not None:
            self._3d_detached_window.raise_()
            self._3d_detached_window.activateWindow()
            return
        from PySide6.QtWidgets import QDialog, QVBoxLayout
        dlg = QDialog(self)
        dlg.setWindowTitle("SJTU-TPMSHX — 3D View (detached)")
        dlg.resize(1200, 800)
        dlg.setModal(False)
        dlg.setStyleSheet(f"QDialog{{background:{get_theme()['bg']};}}")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(4, 4, 4, 4); lay.setSpacing(0)
        # Remember previous parent & layout position so re-docking restores
        # the widget to exactly where it came from.
        self._3d_prev_parent = panel.parentWidget()
        self._3d_prev_parent_layout = None
        card = self._canvas_cards.get('3d') if hasattr(self, '_canvas_cards') else None
        if card is not None:
            self._3d_prev_parent_layout = card.layout()
        panel.setParent(None)
        lay.addWidget(panel)
        self._3d_detached_window = dlg

        # Wire reattach on close instead of destroying the window, so the
        # OpenGL context lives inside a Qt object continuously.
        # 2026-05-20 UI sweep (Tier 21): guard the reattach against the
        # main-window-teardown path. The dialog is parented to `self`,
        # so when the main window closes Qt also destroys this dialog
        # and fires this override — at which point `self` is mid-destroy
        # and `self.statusBar()` inside `_reattach_3d_window` would
        # dereference a deleted C++ object. closeEvent (step 2) now
        # neutralises the override before app teardown, but keep a
        # try/except here as belt-and-braces.
        def _on_close(ev):
            try:
                self._reattach_3d_window()
            except (RuntimeError, AttributeError):
                pass
            ev.accept()
        dlg.closeEvent = _on_close
        dlg.show()
        self.statusBar().showMessage(
            "3D view detached — close the window to re-dock.", 5000)

    def _reattach_3d_window(self):
        """Put canvas_3d back into its original card and close the dialog."""
        dlg = getattr(self, '_3d_detached_window', None)
        panel = getattr(self, 'canvas_3d', None)
        if dlg is None or panel is None:
            return
        # Move the widget back into its old layout before destroying dialog.
        prev_layout = getattr(self, '_3d_prev_parent_layout', None)
        if prev_layout is not None:
            panel.setParent(None)
            prev_layout.addWidget(panel)
        self._3d_detached_window = None
        # Avoid recursion: clear the overridden closeEvent before invoking it.
        try:
            dlg.close()
        except Exception:
            pass
        self.statusBar().showMessage("3D view re-docked.", TOAST_MS_SHORT)

    def _canvas_for_key(self, key):
        mapping = {
            'temp':   getattr(self, 'canvas_temp', None),
            'pres':   getattr(self, 'canvas_pres', None),
            'vel':    getattr(self, 'canvas_vel', None),
            'layout': getattr(self, 'canvas_layout', None),
            'pareto': getattr(self, 'canvas_pareto', None),
        }
        return mapping.get(key)

    def _detach_canvas(self, key):
        """Reparent any 2D matplotlib canvas into a floating QDialog.
        3D uses the dedicated path (`_detach_3d_window`) because
        PyVistaQt's OpenGL context needs more careful handling."""
        if key == '3d':
            self._detach_3d_window()
            return
        canvas = self._canvas_for_key(key)
        if canvas is None:
            return
        if self._detached_canvases.get(key) is not None:
            self._detached_canvases[key].raise_()
            return
        from PySide6.QtWidgets import QDialog, QVBoxLayout
        dlg = QDialog(self)
        dlg.setWindowTitle(f"SJTU-TPMSHX — {key} (detached)")
        dlg.resize(1200, 800)
        dlg.setModal(False)
        dlg.setStyleSheet(f"QDialog{{background:{get_theme()['bg']};}}")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(4, 4, 4, 4); lay.setSpacing(0)
        card = self._canvas_cards.get(key)
        prev_layout = card.layout() if card is not None else None
        canvas._prev_layout = prev_layout
        canvas.setParent(None)
        lay.addWidget(canvas)
        self._detached_canvases[key] = dlg

        def _on_close(ev, _k=key):
            # Tier 21: same dead-self guard as the 3D detach path.
            try:
                self._reattach_canvas(_k)
            except (RuntimeError, AttributeError):
                pass
            ev.accept()
        dlg.closeEvent = _on_close
        dlg.show()
        self.statusBar().showMessage(
            f"{key} canvas detached — close the window to re-dock.", 5000)

    def _reattach_canvas(self, key):
        if key == '3d':
            self._reattach_3d_window()
            return
        dlg = self._detached_canvases.pop(key, None)
        canvas = self._canvas_for_key(key)
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
        self.statusBar().showMessage(f"{key} canvas re-docked.", TOAST_MS_SHORT)

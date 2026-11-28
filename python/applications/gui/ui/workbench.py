"""Select, prepare and detach workbench views."""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from tm1.applications.gui.ui.theme import get_theme
from tm1.applications.gui.ui.ui_constants import TOAST_MS_SHORT


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
            self.import_worker.settled.connect(lambda: refresh_resource_availability(self.window))
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
                window.dialogs.notify(
                    f"三维视图暂不可用：{self.import_error}", kind="warn", duration_ms=5000
                )

        def start():
            if window.canvas_3d is None and not window._close_pending:
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
            panel.restore_color_ranges(getattr(window, "_volume_color_ranges", {}).get("results", {}))
        except Exception as exc:
            self.import_error = str(exc)
        else:
            placeholder = window._canvas_3d_placeholder
            window._canvas_cards["3d"].layout().replaceWidget(placeholder, panel)
            placeholder.deleteLater()
            window._canvas_3d_placeholder = None
            window.canvas_3d = panel
            from .builders_canvas import refresh_field_controls

            panel.field_changed.connect(lambda _k: refresh_field_controls(window))
            window._fit_3d_card_to_viewport()
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

    def _sync_shell_header(self, page_key: str) -> None:
        window = self.window
        titles = {
            "run": "算例计算",
            "result": "计算结果",
            "opt": "优化设计",
            "qd": "快速设计",
        }
        title = getattr(window, "_page_title", None)
        if title is not None:
            title.setText(titles.get(page_key, "算例计算"))
        if hasattr(window, "btn_update_geometry"):
            window.btn_update_geometry.setVisible(page_key == "run")
        if hasattr(window, "btn_compute"):
            window.btn_compute.setVisible(
                page_key == "run" or not window.single_run.is_idle()
            )
        if hasattr(window, "btn_export"):
            window.btn_export.setVisible(page_key in ("result", "opt"))
        if hasattr(window, "btn_run_info"):
            window.btn_run_info.setVisible(page_key in ("run", "result"))
        window.appearance.sync_drawer_visibility()
        from tm1.applications.gui.ui.builders_sidebar import (
            refresh_header_status,
            update_result_sidebar_visibility,
        )

        refresh_header_status(window)
        update_result_sidebar_visibility(window)

    def show_quick_design(self):
        window = self.window
        if not self.requested_3d_background:
            self.requested_3d_result = None
            self.requested_3d_action = None
        window.page_stack.setCurrentWidget(window.quick_design)
        self._sync_shell_header("qd")
        refresh_nav = getattr(window, "_refresh_workbench_navigation", None)
        if refresh_nav is not None:
            refresh_nav()

    def canvas_tab_availability(self):
        """Return availability from result state, independent of UI widgets."""
        window = self.window
        mode = window.results.summary().get("mode")
        is_3d = (
            mode == "3d"
            if mode is not None
            else hasattr(window, "combo_dim") and window.combo_dim.currentIndex() == 1
        )
        has_2d = self.rendered_slices if is_3d else window.cache.has_results("2d")
        has_3d = is_3d and window.cache.has_results("3d") and not self.volume_error
        return {
            "layout": True,
            "temp": has_2d,
            "pres": has_2d,
            "vel": has_2d,
            "3d": has_3d,
            "pareto": True,
            "2d_view": has_2d,
            "result": has_2d or has_3d,
        }

    def update_tab_visibility(self):
        """Enable/disable navigation pages and result controls from available results."""
        window = self.window
        if not hasattr(window, "_canvas_cards"):
            return
        rules = self.canvas_tab_availability()
        for nav_key, rule_key in (("run", "layout"), ("result", "result"), ("opt", "pareto")):
            enabled = bool(rules[rule_key])
            window.nav_rail.set_page_enabled(nav_key, enabled)
            if hasattr(window, "expanded_nav_rail"):
                window.expanded_nav_rail.set_page_enabled(nav_key, enabled)

        if hasattr(window, "btn_view_result"):
            window.btn_view_result.setEnabled(bool(rules["result"]))

        for key in ("temp", "pres", "vel", "3d"):
            card = window._canvas_cards.get(key)
            if card is not None and not rules[key]:
                card.hide()

        combo = getattr(window, "combo_2d_field", None)
        if combo is not None:
            combo.setEnabled(rules.get("2d_view", False))
        seg = getattr(window, "_2d_field_seg", None)
        if seg is not None:
            seg.setEnabled(bool(rules.get("2d_view", False) or rules.get("3d", False)))
        rv = getattr(window, "_result_view_btns", None)
        if rv:
            rv["2d"].setEnabled(rules.get("2d_view", False))
            rv["3d"].setEnabled(rules.get("3d", False))
            if rules.get("3d") and not rules.get("2d_view"):
                self.result_view = "3d"
            elif rules.get("2d_view") and not rules.get("3d"):
                self.result_view = "2d"
            paint = getattr(window, "_paint_result_seg", None)
            if paint is not None:
                paint()

        if not rules.get(self.active_tab, True):
            if window.page_stack.currentWidget() is window.quick_design:
                self.active_tab = "layout"
            else:
                self.switch_tab("layout")

        refresh_nav = getattr(window, "_refresh_workbench_navigation", None)
        if refresh_nav is not None:
            refresh_nav()
        if hasattr(window, "result_export"):
            window.result_export.refresh_export_button()

    def split_with_current(self, tab):
        """Enter split-view pairing the currently active tab with `tab`."""
        window = self.window
        if window.page_stack.currentWidget() is window.quick_design:
            self.switch_tab(tab)
            return
        if tab == "result":
            tab = "3d" if self.result_view == "3d" else self.resolve_2d_view_card()
        if tab == "2d_view":
            tab = self.resolve_2d_view_card()
        cur = self.active_tab
        if cur == "2d_view":
            cur = self.resolve_2d_view_card()
        if cur is None or cur == tab:
            return
        available = self.canvas_tab_availability()
        if not (available.get(cur, False) and available.get(tab, False)):
            window.dialogs.notify("并排对比需要两个视图均已就绪。", kind="warn", duration_ms=4000)
            return
        if tab == "3d" and not self.volume_ready:
            self.request_3d_view(lambda: self.split_with_current(tab))
            return
        from tm1.applications.gui.ui.plot_2d_results import ensure_result_plot

        for key in (cur, tab):
            if key in ("temp", "pres", "vel") and not ensure_result_plot(window, key):
                return
        from tm1.applications.gui.ui.builders_canvas import _layout_split_cards

        _layout_split_cards(window, [cur, tab])
        self.active_tab = cur
        window.dialogs.notify(
            f"并排视图：{cur} ↔ {tab}。单击任意页面恢复单视图。", kind="info", duration_ms=5000
        )

    def resolve_2d_view_card(self) -> str:
        """Return the card for the selected 2D field."""
        window = self.window
        combo = getattr(window, "combo_2d_field", None)
        sel = combo.currentText() if combo is not None else "Temperature"
        return {
            "Temperature": "temp",
            "Velocity |U|": "vel",
            "Pressure": "pres",
        }.get(sel, "temp")

    def toggle_result_view(self):
        """Open the selected result view or toggle between available 2D and 3D views."""
        window = self.window
        if (
            window.page_stack.currentWidget() is window.quick_design
            or self.active_tab not in ("temp", "pres", "vel", "3d")
        ):
            if window.btn_tab_result.isEnabled():
                self.switch_tab("result")
            return
        other = "3d" if self.result_view == "2d" else "2d"
        if window._result_view_btns[other].isEnabled():
            self.result_view = other
            self.switch_tab("result")

    def request_3d_view(self, on_ready=None, *, background=False):
        """Load the current volume on demand; discard obsolete requests."""
        from time import perf_counter

        window = self.window
        result = window.cache.get_result("3d")
        if result is None:
            return
        self.requested_3d_action = on_ready or (lambda: self.switch_tab("3d"))
        self.requested_3d_background = background
        if self.requested_3d_result is result:
            return
        self.requested_3d_result = result
        started = perf_counter()

        def ready():
            if self.requested_3d_result is not result:
                return
            self.requested_3d_result = None
            action = self.requested_3d_action
            self.requested_3d_action = None
            if window._close_pending or window.cache.get_result("3d") is not result:
                return
            from tm1.applications.gui.ui.plot_3d_results import finalize_plots_3d

            load_err = None
            try:
                self.volume_ready = bool(finalize_plots_3d(window))
            except Exception as exc:
                self.volume_ready = False
                load_err = exc
            self.volume_error = not self.volume_ready
            result.metadata.setdefault("timings_s", {})["volume_display"] = perf_counter() - started
            if self.volume_ready:
                window.canvas_3d.show()
                window.cache.mark_drawn("3d")
                action()
            elif load_err is not None:
                window.dialogs.notify(f"三维视图加载失败：{load_err}", kind="error", duration_ms=10000)
            else:
                window.dialogs.notify(
                    "三维视图不可用；场图、计算结果和数据导出仍可使用。",
                    kind="warn",
                    duration_ms=10000,
                )
            self.update_tab_visibility()

        self.prepare_3d(ready)

    def switch_tab(self, tab: str, *, foreground=True):
        window = self.window
        from_quick_design = window.page_stack.currentWidget() is window.quick_design
        if from_quick_design and not foreground:
            return

        combo = getattr(window, "combo_2d_field", None)
        combo_label_map = {
            "temp": "Temperature",
            "vel": "Velocity |U|",
            "pres": "Pressure",
        }
        if tab == "result":
            tab = "3d" if self.result_view == "3d" else "2d_view"
        if tab == "2d_view":
            sel = combo.currentText() if combo is not None else "Temperature"
            tab = {
                "Temperature": "temp",
                "Velocity |U|": "vel",
                "Pressure": "pres",
            }.get(sel, "temp")
        elif tab in combo_label_map and combo is not None:
            target = combo_label_map[tab]
            if combo.currentText() != target:
                combo.blockSignals(True)
                combo.setCurrentText(target)
                combo.blockSignals(False)
                window._paint_2d_seg()

        if tab == "3d" and not self.volume_ready:
            if self.canvas_tab_availability().get("3d"):
                self.request_3d_view()
            return
        if not self.requested_3d_background:
            self.requested_3d_result = None
            self.requested_3d_action = None

        if self.split_tabs:
            self.split_tabs = None
            from tm1.applications.gui.ui.builders_canvas import _relayout_canvas_cards

            _relayout_canvas_cards(window, 1)
        if not self.canvas_tab_availability().get(tab, False):
            tab = "layout"

        if from_quick_design:
            window.page_stack.setCurrentWidget(window._workbench_canvas)

        prev_tab = self.active_tab
        same_tab = tab == prev_tab and not from_quick_design
        self.active_tab = tab

        page_key = (
            "opt"
            if tab == "pareto"
            else ("result" if tab in ("temp", "pres", "vel", "3d") else "run")
        )
        self._sync_shell_header(page_key)

        from tm1.applications.gui.ui.builders_canvas import refresh_field_controls

        if hasattr(window, "_field_phase_seg"):
            refresh_field_controls(window)
        if hasattr(window, "result_export"):
            window.result_export.refresh_export_button()

        if same_tab and not self.split_tabs:
            card = getattr(window, "_canvas_cards", {}).get(tab)
            if card is not None and card.isVisible() and (
                tab not in ("temp", "pres", "vel") or tab in window.cache.get_drawn_tabs()
            ):
                return

        if tab in ("temp", "pres", "vel"):
            from tm1.applications.gui.ui.plot_2d_results import ensure_result_plot

            if not ensure_result_plot(window, tab):
                window._canvas_cards[tab].hide()
                self.switch_tab("layout")
                return

        tabs = ("temp", "pres", "vel", "layout", "pareto", "3d")
        drawn = window.cache.get_drawn_tabs()
        scroll = getattr(window, "_canvas_scroll", None)
        viewport = scroll.viewport() if scroll is not None else None
        updates_enabled = viewport.updatesEnabled() if viewport is not None else False
        if viewport is not None:
            viewport.setUpdatesEnabled(False)
        try:
            for key in tabs:
                card = window._canvas_cards.get(key)
                if key != tab and card:
                    card.hide()
                    if self.active_tab != tab:
                        return

            fs = getattr(window, "_2d_field_seg", None)
            if fs is not None:
                fs.setVisible(tab in ("temp", "pres", "vel", "3d"))
            if tab in ("temp", "pres", "vel", "3d"):
                self.result_view = "3d" if tab == "3d" else "2d"
                paint = getattr(window, "_paint_result_seg", None)
                if paint is not None:
                    paint()

            target_card = window._canvas_cards.get(tab)
            showed_any = False
            if target_card and (
                tab == "pareto" or window.cache.has_any_results() or tab in drawn
            ):
                target_card.show()
                if self.active_tab != tab:
                    return
                fit = getattr(window, "_fit_3d_card_to_viewport", None)
                if fit is not None:
                    fit()
                showed_any = True
            elif tab == "3d" and target_card:
                target_card.hide()

            if hasattr(window, "_empty_state_label"):
                window._empty_state_label.setVisible(not showed_any)
            if window.cache.has_any_results():
                try:
                    window.results.refresh_summary()
                except Exception:
                    pass
            try:
                from tm1.applications.gui.ui.builders_sidebar import (
                    update_result_sidebar_visibility,
                )

                update_result_sidebar_visibility(window)
            except Exception:
                pass
            window._hover_label.setText("")
            refresh_nav = getattr(window, "_refresh_workbench_navigation", None)
            if refresh_nav is not None:
                refresh_nav()
        finally:
            if viewport is not None:
                viewport.setUpdatesEnabled(updates_enabled)

    def on_hover(self, event):
        """Show data value at mouse position on contour plots."""
        from time import monotonic

        window = self.window
        now = monotonic()
        if now - self.last_hover_time < 0.033:
            return
        self.last_hover_time = now

        inspector = getattr(window, "_coord_inspector", None)
        if inspector is not None and inspector.isVisible():
            try:
                inspector.update_from_event(event)
            except Exception:
                pass

        if event.inaxes is None or event.xdata is None or event.ydata is None:
            window._hover_label.setText("")
            return

        canvas = event.canvas
        hd = getattr(canvas, "_hover_data", None)
        if not hd:
            return

        x_mm, y_mm = event.xdata, event.ydata
        L, H = hd["L"], hd["H"]
        Nx, Ny = hd["Nx"], hd["Ny"]
        import numpy as np
        from tm1.applications.gui.ui.matplotlib_canvas import cell_index_mm

        i = cell_index_mm(x_mm, hd.get("dx_arr", np.full(Nx, L / Nx)))
        j = cell_index_mm(y_mm, hd.get("dy_arr", np.full(Ny, H / Ny)))

        cache_key = id(canvas.axes)
        cached = getattr(canvas, "_axes_flat_cache", None)
        if cached is None or cached[0] != cache_key:
            axes = [ax for row in canvas.axes for ax in row]
            canvas._axes_flat_cache = (cache_key, axes)
        else:
            axes = cached[1]
        ax_idx = -1
        for k, ax in enumerate(axes):
            if event.inaxes is ax:
                ax_idx = k
                break

        if ax_idx < 0 or ax_idx >= len(hd["fields"]):
            window._hover_label.setText(f"<i>x</i>={x_mm:.1f}\u202fmm, <i>y</i>={y_mm:.1f}\u202fmm")
            return

        val = hd["fields"][ax_idx][i, j]
        name = hd["names"][ax_idx]
        unit = hd["unit"]
        if "_" in name:
            head, sub = name.split("_", 1)
            name = f"<i>{head}</i><sub>{sub}</sub>"
        fmt = hd["fmt"]
        window._hover_label.setText(
            f"<i>x</i>={x_mm:.1f}\u202fmm, <i>y</i>={y_mm:.1f}\u202fmm  |  "
            f"Cell ({i},{j}): {name} = {val:{fmt}}\u202f{unit}"
        )

    def on_canvas_click(self, event):
        """Record a clicked physical coordinate inside the active field data axes."""
        if getattr(event, "button", None) != 1:
            return
        if event.inaxes is None or event.xdata is None or event.ydata is None:
            return
        tab = self.active_tab
        canvas = self.canvas_for_key(tab)
        if canvas is None or not getattr(canvas, "axes", None):
            return
        data_axes = [ax for row in canvas.axes for ax in row]
        if event.inaxes not in data_axes:
            return
        hd = getattr(canvas, "_hover_data", None)
        if not isinstance(hd, dict):
            return
        x_mm = float(event.xdata)
        y_mm = float(event.ydata)
        L_mm = float(hd.get("L", 0.0)) * 1000.0
        H_mm = float(hd.get("H", 0.0)) * 1000.0
        if not (0.0 <= x_mm <= L_mm and 0.0 <= y_mm <= H_mm):
            return
        from tm1.applications.gui.ui.builders_sidebar import add_sample_point

        add_sample_point(self.window, x_mm, y_mm)

    def detach_3d_window(self):
        """Reparent canvas_3d into a standalone QDialog and show it."""
        window = self.window
        panel = getattr(window, "canvas_3d", None)
        if panel is None:
            QMessageBox.information(
                window, "三维视图", "三维视图尚未初始化，请先切换到“三维”视图。"
            )
            return
        if self.detached_volume is not None:
            self.detached_volume.raise_()
            self.detached_volume.activateWindow()
            return
        from PySide6.QtWidgets import QDialog, QVBoxLayout

        dlg = QDialog(window)
        dlg.setWindowTitle("SJTU-TPMSHX — 三维视图（独立窗口）")
        dlg.resize(1200, 800)
        dlg.setModal(False)
        dlg.setStyleSheet(f"QDialog {{ background: {get_theme()['window']}; }}")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(0)
        self.volume_parent_layout = None
        card = window._canvas_cards.get("3d") if hasattr(window, "_canvas_cards") else None
        if card is not None:
            self.volume_parent_layout = card.layout()
        panel.setParent(None)
        lay.addWidget(panel)
        self.detached_volume = dlg

        def _on_close(ev):
            try:
                self.reattach_3d_window()
            except (RuntimeError, AttributeError):
                pass
            ev.accept()

        dlg.closeEvent = _on_close
        dlg.show()
        window.dialogs.notify("三维视图已分离 — 关闭窗口自动放回。", kind="info", duration_ms=5000)

    def reattach_3d_window(self):
        """Put canvas_3d back into its original card and close the dialog."""
        window = self.window
        dlg = self.detached_volume
        panel = getattr(window, "canvas_3d", None)
        if dlg is None or panel is None:
            return
        prev_layout = self.volume_parent_layout
        if prev_layout is not None:
            panel.setParent(None)
            prev_layout.addWidget(panel)
        self.detached_volume = None
        try:
            dlg.close()
        except Exception:
            pass
        window.dialogs.notify("三维视图已放回主窗口。", kind="info", duration_ms=TOAST_MS_SHORT)

    def canvas_for_key(self, key):
        window = self.window
        mapping = {
            "temp": getattr(window, "canvas_temp", None),
            "pres": getattr(window, "canvas_pres", None),
            "vel": getattr(window, "canvas_vel", None),
            "layout": getattr(window, "canvas_layout", None),
            "pareto": window.optimization.pareto_canvas,
        }
        return mapping.get(key)

    def _replace_pareto_tab(self, page, replacement):
        tabs = self.window.optimization.result_tabs
        index = tabs.indexOf(page)
        tabs.insertTab(index, replacement, tabs.tabText(index))
        if tabs.currentWidget() is page:
            tabs.setCurrentWidget(replacement)
        tabs.removeTab(index + 1)

    def detach_canvas(self, key):
        """Reparent any 2D matplotlib canvas into a floating QDialog."""
        window = self.window
        if key == "3d":
            self.detach_3d_window()
            return
        canvas = self.canvas_for_key(key)
        if canvas is None:
            return
        if key in ("temp", "pres", "vel"):
            from tm1.applications.gui.ui.plot_2d_results import ensure_result_plot

            if not ensure_result_plot(window, key):
                return
        if self.detached_canvases.get(key) is not None:
            self.detached_canvases[key].raise_()
            return
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

        dlg = QDialog(window)
        dlg.setWindowTitle(f"SJTU-TPMSHX — {key}（独立窗口）")
        dlg.resize(1200, 800)
        dlg.setModal(False)
        dlg.setStyleSheet(f"QDialog {{ background: {get_theme()['window']}; }}")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(0)
        if key == "pareto":
            # Keep the field and volume tabs at their indices while the plot is detached.
            dlg.pareto_placeholder = QWidget()
            self._replace_pareto_tab(canvas, dlg.pareto_placeholder)
        canvas.setParent(None)
        lay.addWidget(canvas)
        canvas.show()
        self.detached_canvases[key] = dlg

        def _on_close(ev, _k=key):
            try:
                self.reattach_canvas(_k)
            except (RuntimeError, AttributeError):
                pass
            ev.accept()

        dlg.closeEvent = _on_close
        dlg.show()
        window.dialogs.notify(f"{key} 画布已分离 — 关闭窗口自动放回。", kind="info", duration_ms=5000)

    def reattach_canvas(self, key):
        window = self.window
        if key == "3d":
            self.reattach_3d_window()
            return
        dlg = self.detached_canvases.pop(key, None)
        canvas = self.canvas_for_key(key)
        if dlg is None or canvas is None:
            return
        if key == "pareto":
            self._replace_pareto_tab(dlg.pareto_placeholder, canvas)
            dlg.pareto_placeholder.deleteLater()
        else:
            window._canvas_cards[key].layout().addWidget(canvas)
        try:
            dlg.close()
        except Exception:
            pass
        window.dialogs.notify(f"{key} 画布已放回主窗口。", kind="info", duration_ms=TOAST_MS_SHORT)

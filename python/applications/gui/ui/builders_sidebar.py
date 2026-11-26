"""Result drawer bands, two-tier readout strip, and stale-input detection."""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sjtu_tpmshx.model_configs.units import CELSIUS_ZERO_K

from .fmt import duration as fmt_duration
from .fmt import qualification_reasons
from .inspector_drawer import CollapsibleBand
from .readout_strip import ReadoutItem, ReadoutNotice
from .symbols import SYM
from .theme import RADIUS_BTN, get_theme


def _build_kv_row(parent_layout: QVBoxLayout, label_text: str, *, theme: dict) -> tuple[QLabel, QLabel]:
    row = QWidget()
    row.setStyleSheet("background: transparent;")
    hl = QHBoxLayout(row)
    hl.setContentsMargins(16, 6, 16, 6)
    hl.setSpacing(8)
    lbl = QLabel(label_text)
    if "<" in label_text:
        lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setStyleSheet(
        f"color: {theme['sub']}; font-size: 9.5pt; font-weight: 400; "
        "background: transparent; border: none;"
    )
    val = QLabel("—")
    val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    val.setStyleSheet(
        f"color: {theme['fg']}; font-family: {theme['mono_family']}; "
        "font-size: 9.5pt; font-weight: 600; background: transparent; border: none;"
    )
    hl.addWidget(lbl)
    hl.addStretch(1)
    hl.addWidget(val)
    parent_layout.addWidget(row)
    return lbl, val


def _build_action_row(
    parent_layout: QVBoxLayout,
    label_text: str,
    callback,
    *,
    theme: dict,
) -> QPushButton:
    btn = QPushButton(label_text)
    btn.setFixedHeight(32)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        f"QPushButton {{ background: transparent; color: {theme['fg']}; "
        f"border: none; border-radius: {RADIUS_BTN}px; text-align: left; "
        "padding: 0 16px; font-size: 9.5pt; font-weight: 400; }"
        f"QPushButton:hover {{ background: {theme['row_hover']}; }}"
    )
    btn.clicked.connect(callback)
    parent_layout.addWidget(btn)
    return btn


def build_result_drawer_content(window) -> QWidget:
    """Build the Style P2 collapsible result drawer bands (no left strips/underlines)."""
    theme = get_theme()
    body = QWidget()
    body.setStyleSheet("background: transparent;")
    vlay = QVBoxLayout(body)
    vlay.setContentsMargins(0, 0, 0, 0)
    vlay.setSpacing(0)

    window._sb_labels = {}

    # Band 1: 计算状态
    status_band = CollapsibleBand(
        "计算状态",
        first=True,
        collapsible=True,
        expanded=True,
        actions=[
            ("日志", window.dialogs.show_solve_log),
            ("诊断", window.dialogs.show_diagnostics),
        ],
    )
    st_body = status_band.body_layout()
    _, window._sb_labels["status"] = _build_kv_row(st_body, "状态", theme=theme)
    _, window._sb_labels["iters"] = _build_kv_row(st_body, "迭代 / 耗时", theme=theme)
    vlay.addWidget(status_band)

    # Band 2: 核查
    check_summary = QLabel("—")
    check_summary.setStyleSheet(
        f"color: {theme['tert']}; font-size: 11px; font-weight: 500; background: transparent;"
    )
    window._lbl_check_summary = check_summary
    check_band = CollapsibleBand(
        "核查",
        collapsible=True,
        expanded=True,
        right_widget=check_summary,
    )
    ck_body = check_band.body_layout()
    _, window._sb_labels["closure"] = _build_kv_row(ck_body, "能量闭合", theme=theme)
    _, window._sb_labels["envelope"] = _build_kv_row(ck_body, "压缩性包络", theme=theme)
    _, window._sb_labels["extrap"] = _build_kv_row(ck_body, "适用范围", theme=theme)
    _, window._sb_labels["design"] = _build_kv_row(ck_body, "设计资格", theme=theme)
    window._sb_labels["design"].setWordWrap(True)
    vlay.addWidget(check_band)

    # Band 3: 读数
    readout_band = CollapsibleBand("读数", collapsible=True, expanded=True)
    rd_body = readout_band.body_layout()
    _, window._sb_labels["q"] = _build_kv_row(rd_body, f"换热量 {SYM['Q']}", theme=theme)
    _, window._sb_labels["dpa"] = _build_kv_row(rd_body, f"压降 {SYM['dP_A']} [Pa]", theme=theme)
    _, window._sb_labels["dpb"] = _build_kv_row(rd_body, f"压降 {SYM['dP_B']} [Pa]", theme=theme)
    unit = "°C" if getattr(window, "_temp_unit", "K") == "C" else "K"
    window._lbl_sidebar_tout_unit, window._sb_labels["tout"] = _build_kv_row(
        rd_body, f"出口温度 A / B [{unit}]", theme=theme
    )
    window._sb_labels["tout"].setWordWrap(True)
    vlay.addWidget(readout_band)

    # Band 4: 画布
    canvas_band = CollapsibleBand("画布", collapsible=True, expanded=True)
    cv_body = canvas_band.body_layout()
    cv_body.setContentsMargins(0, 4, 0, 6)

    def _toggle_probe() -> None:
        toggle = getattr(window, "_toggle_coord_inspector", None)
        if toggle is not None:
            toggle()

    _build_action_row(cv_body, "坐标探针  (Ctrl+I)", _toggle_probe, theme=theme)
    _build_action_row(
        cv_body,
        "导出图像 — PNG / SVG / PDF",
        window.result_export.export_figure,
        theme=theme,
    )
    _build_action_row(
        cv_body,
        "导出完整结果 — CSV + NPZ",
        window.result_export.export_results,
        theme=theme,
    )
    _build_action_row(
        cv_body,
        "打开运行目录",
        lambda: window.dialogs.open_output_folder(),
        theme=theme,
    )
    vlay.addWidget(canvas_band)

    vlay.addStretch(1)
    window._result_drawer_content = body
    return body


def result_metric_texts(window) -> dict[str, str]:
    """Format the published result for the readout strip, drawer, and run history."""
    d = window.results.summary()
    is_3d = d.get("mode") == "3d"

    def value(number, digits):
        return f"{number:.{digits}f}" if number is not None and math.isfinite(number) else "—"

    offset = CELSIUS_ZERO_K if getattr(window, "_temp_unit", "K") == "C" else 0.0
    temperatures = (d.get("T_out_A_K"), d.get("T_out_B_K"))
    return {
        "Q": value(d.get("Q_W"), 2 if is_3d else 1),
        "Q_unit": d.get("Q_unit", ""),
        "dP_A": value(d.get("dP_A"), 0 if is_3d else 1),
        "dP_B": value(d.get("dP_B"), 0 if is_3d else 1),
        "ToutA": value(None if temperatures[0] is None else temperatures[0] - offset, 2),
        "ToutB": value(None if temperatures[1] is None else temperatures[1] - offset, 2),
    }


def is_result_stale(window) -> bool:
    """Return True when active case inputs differ from the published result."""
    result = window.cache.get_result()
    if result is None:
        return False
    provenance = result.metadata.get("run_provenance")
    saved_preset = provenance.get("preset") if isinstance(provenance, dict) else None
    if not isinstance(saved_preset, dict):
        return False

    from .window_config import LINE_EDITS, field_active

    is_3d = window.combo_dim.currentIndex() == 1
    for name, spec in LINE_EDITS.items():
        if not field_active(window, spec, is_3d=is_3d):
            continue
        le = getattr(window, name, None)
        if le is not None and le.property("inpError") == "true":
            return True

    current = window.case_files.capture_current_preset("")
    cur_unit = current.get("temp_unit", "K")
    sav_unit = saved_preset.get("temp_unit", "K")

    for key in window.case_files.PRESET_COMBOS:
        if current.get("combos", {}).get(key) != saved_preset.get("combos", {}).get(key):
            return True
    for key in window.case_files.PRESET_CHECKS:
        if current.get("checks", {}).get(key) != saved_preset.get("checks", {}).get(key):
            return True

    cur_edits = current.get("line_edits", {})
    sav_edits = saved_preset.get("line_edits", {})
    for name, spec in LINE_EDITS.items():
        if not field_active(window, spec, is_3d=is_3d):
            continue
        raw_c = str(cur_edits.get(name, "")).strip()
        raw_s = str(sav_edits.get(name, "")).strip()
        if raw_c == raw_s and (name not in ("le_TinA", "le_TinB") or cur_unit == sav_unit):
            continue
        try:
            vc = float(raw_c)
            vs = float(raw_s)
            if name in ("le_TinA", "le_TinB"):
                if cur_unit == "C":
                    vc += CELSIUS_ZERO_K
                if sav_unit == "C":
                    vs += CELSIUS_ZERO_K
            if not math.isclose(vc, vs, rel_tol=1e-7, abs_tol=1e-9):
                return True
        except ValueError:
            return True
    return False


def refresh_stale_indicator(window) -> None:
    """Update the readout strip stale-input badge without redrawing plots."""
    strip = getattr(window, "readout_strip", None)
    if strip is None:
        return
    strip.set_stale(is_result_stale(window))


def refresh_result_sidebar(window) -> None:
    """Refresh result drawer labels, bottom readout strip, and header run-info badge."""
    labels = getattr(window, "_sb_labels", None)
    theme = get_theme()
    values = result_metric_texts(window)
    d = window.results.summary()
    has_result = window.cache.has_any_results()

    if labels:
        labels["q"].setText(f"{values['Q']} {values['Q_unit']}".strip())
        labels["dpa"].setText(values["dP_A"])
        labels["dpb"].setText(values["dP_B"])
        labels["tout"].setText(f"{values['ToutA']} / {values['ToutB']}")

        good = theme["ok"]
        warn = theme["warn"]
        err = theme["err"]

        def _mark(key: str, text: str, ok):
            lbl = labels[key]
            lbl.setText(text)
            color = {True: good, False: warn, "err": err, None: theme["fg"]}[ok]
            lbl.setStyleSheet(
                f"color: {color}; background: transparent; border: none; "
                f"font-family: {theme['mono_family']}; font-size: 9.5pt; font-weight: 600;"
            )

        if not has_result:
            _mark("status", "尚未计算", None)
        elif d.get("converged") is False:
            _mark("status", "未收敛", "err")
        elif d.get("warnings") or d.get("extrap"):
            _mark("status", "完成 · 有提示", False)
        else:
            _mark("status", "已收敛", True)

        rel = d.get("closure_rel")
        labels["closure"].setToolTip(d.get("closure_basis", "两侧焓流"))
        if rel is not None and rel == rel:
            _mark(
                "closure",
                f"{abs(rel) * 100:.1f}\u202f%",
                d.get("qualification", {}).get("physical", {}).get("passed"),
            )
        else:
            _mark("closure", "—", None)

        env = d.get("envelope_valid")
        _mark(
            "envelope",
            "有效 ✓" if env else ("失效 ⚠" if env is not None else "—"),
            env if env is not None else None,
        )

        qualification = d.get("qualification", {})
        fails = 0
        for key, passed in (
            ("extrap", qualification.get("applicability", {}).get("passed")),
            ("design", qualification.get("design", {}).get("eligible")),
        ):
            _mark(
                key,
                "通过 ✓" if passed is True else "未通过 ⚠" if passed is False else "未核实",
                passed,
            )
            if passed is False:
                fails += 1
        if d.get("qualification", {}).get("physical", {}).get("passed") is False:
            fails += 1
        if env is False:
            fails += 1

        check_lbl = getattr(window, "_lbl_check_summary", None)
        if check_lbl is not None:
            if not has_result:
                check_lbl.setText("—")
                check_lbl.setStyleSheet(
                    f"color: {theme['tert']}; font-size: 11px; font-weight: 500; "
                    "background: transparent;"
                )
            elif fails > 0:
                check_lbl.setText(f"{fails} 项未通过")
                check_lbl.setStyleSheet(
                    f"color: {theme['warn']}; font-size: 11px; font-weight: 600; "
                    "background: transparent;"
                )
            else:
                check_lbl.setText("全部通过")
                check_lbl.setStyleSheet(
                    f"color: {theme['ok']}; font-size: 11px; font-weight: 600; "
                    "background: transparent;"
                )

        reasons = qualification_reasons(qualification, d.get("applicability_evidence"))
        labels["design"].setToolTip("\n".join(reasons))
        if reasons:
            labels["design"].setText(
                labels["design"].text() + "：" + reasons[0].split("（实际 ")[0]
            )

        it = (d.get("iters") or {}).get("iter_outer")
        ws = d.get("wall_s")
        labels["iters"].setText(
            f"{it if it is not None else '—'} · "
            f"{f'{ws:.1f} s' if isinstance(ws, (int, float)) else '—'}"
        )

    # Update bottom two-tier ReadoutStrip
    strip = getattr(window, "readout_strip", None)
    if strip is not None:
        unit_t = "°C" if getattr(window, "_temp_unit", "K") == "C" else "K"
        items = [
            ReadoutItem(f"换热量 {SYM['Q']}", values["Q"], values["Q_unit"] or "W"),
            ReadoutItem(f"压降 {SYM['dP_A']}", values["dP_A"], "Pa"),
            ReadoutItem(f"压降 {SYM['dP_B']}", values["dP_B"], "Pa"),
            ReadoutItem(f"出口温度 {SYM['T_out_A']}", values["ToutA"], unit_t),
            ReadoutItem(f"出口温度 {SYM['T_out_B']}", values["ToutB"], unit_t),
        ]
        notice = None
        if has_result:
            extrap_list = d.get("extrap") or []
            if d.get("converged") is False:
                notice = ReadoutNotice("未收敛", "结果仅供参考，请核查诊断", kind="err")
            elif extrap_list:
                notice = ReadoutNotice("外推提示", f"{len(extrap_list)} 项超拟合范围", kind="warn")
            elif d.get("warnings"):
                notice = ReadoutNotice("运行提示", f"{len(d['warnings'])} 条提示，见诊断", kind="warn")
        strip.set_items(items)
        strip.set_notice(notice)
        strip.set_stale(is_result_stale(window))

    # Update header status pill (btn_run_info)
    refresh_header_status(window)


def refresh_header_status(window) -> None:
    """Update the header run-info trigger text and status dot."""
    btn = getattr(window, "btn_run_info", None)
    if btn is None:
        return
    theme = get_theme()
    has_result = window.cache.has_any_results()
    d = window.results.summary() if has_result else {}
    elapsed = getattr(window, "_last_elapsed_s", None)
    dur = fmt_duration(elapsed) if isinstance(elapsed, (int, float)) else ""

    if not window.single_run.is_idle():
        dot_color = theme["accent_fg"]
        text = "正在求解…"
    elif not has_result:
        dot_color = theme["tert"]
        text = "尚未计算"
    elif d.get("converged") is False:
        dot_color = theme["err"]
        text = f"未收敛 · {dur}" if dur else "未收敛"
    elif d.get("warnings") or d.get("extrap"):
        dot_color = theme["warn"]
        prefix = "上次结果" if window.workbench.active_tab == "layout" else "完成"
        text = f"{prefix} · 有提示 · {dur}" if dur else f"{prefix} · 有提示"
    else:
        dot_color = theme["ok"]
        prefix = "上次结果" if window.workbench.active_tab == "layout" else "完成"
        text = f"{prefix} · {dur}" if dur else prefix

    btn.setText(f"●  {text}  ▾")
    btn.setStyleSheet(
        f"QPushButton {{ background: {theme['panel']}; color: {theme['fg']}; "
        f"border: 1px solid {theme['border']}; border-radius: {RADIUS_BTN}px; "
        "padding: 0 10px; font-size: 9.5pt; font-weight: 500; }"
        f"QPushButton:hover {{ background: {theme['hover']}; border-color: {theme['border_strong']}; }}"
    )
    btn.setProperty("statusColor", dot_color)


def update_result_sidebar_visibility(window) -> None:
    """Show the bottom readout strip on case and result sheets when results exist."""
    strip = getattr(window, "readout_strip", None)
    if strip is None:
        return
    in_qd = (
        getattr(window, "page_stack", None) is not None
        and window.page_stack.currentWidget() is window.quick_design
    )
    tab = window.workbench.active_tab
    on_case_or_result = (not in_qd) and tab in ("layout", "temp", "pres", "vel", "3d")
    has_result = window.cache.has_any_results()
    toggle = getattr(window, "btn_result_summary", None)
    if toggle is not None:
        toggle.setVisible(bool(tab in ("temp", "pres", "vel", "3d") and has_result and not in_qd))
    summary_on = True if toggle is None else toggle.isChecked()
    strip.setVisible(
        bool(on_case_or_result and has_result and summary_on and not window.appearance.is_focused())
    )

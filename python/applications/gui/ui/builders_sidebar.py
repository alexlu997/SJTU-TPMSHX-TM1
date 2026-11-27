"""Result drawer bands, per-point probe readouts, readout strip, and stale detection."""
from __future__ import annotations

import math
from dataclasses import asdict

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sjtu_tpmshx.model_configs.units import CELSIUS_ZERO_K

from .fmt import duration as fmt_duration
from .fmt import qualification_reasons, warning_strip_summary
from .inspector_drawer import CollapsibleBand
from .readout_strip import ReadoutItem, ReadoutNotice
from .symbols import SYM
from .theme import RADIUS_BTN, get_theme


def evaluate_result_status(result, summary: dict) -> tuple[str, str]:
    """Return a single ``(kind, label)`` status shared across header, drawer, and popover."""
    if result is None:
        return ("idle", "尚未计算")
    converged = summary.get("converged")
    if converged is False:
        return ("err", "未收敛")
    qualification = summary.get("qualification") or {}
    design_ok = qualification.get("design", {}).get("eligible")
    extrap_ok = qualification.get("applicability", {}).get("passed")
    phys_ok = qualification.get("physical", {}).get("passed")
    env_ok = summary.get("envelope_valid")
    has_notice = (
        design_ok is False
        or extrap_ok is False
        or phys_ok is False
        or env_ok is False
        or bool(summary.get("warnings"))
        or bool(summary.get("extrap"))
    )
    if has_notice:
        return ("warn", "完成 · 有提示")
    if converged is True:
        return ("ok", "已收敛")
    return ("idle", "状态未知")


def _status_dot_icon(color_hex: str, size: int = 8) -> QIcon:
    """Render a crisp anti-aliased colored status dot for header controls."""
    dpr = 2
    px = size * dpr
    pm = QPixmap(px, px)
    pm.setDevicePixelRatio(float(dpr))
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color_hex))
    painter.drawEllipse(QPointF(size / 2.0, size / 2.0), size * 0.42, size * 0.42)
    painter.end()
    return QIcon(pm)


def _build_kv_row(
    parent_layout: QVBoxLayout, label_text: str, *, theme: dict
) -> tuple[QLabel, QLabel]:
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
        f"QPushButton:disabled {{ color: {theme['tert']}; }}"
    )
    btn.clicked.connect(callback)
    parent_layout.addWidget(btn)
    return btn


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()


def add_sample_point(window, x_mm: float, y_mm: float) -> bool:
    """Record a physical probe coordinate on the accepted result and refresh drawer cards."""
    if not window.cache.has_any_results():
        return False
    from .coord_inspector import _resolve_fields

    rows = _resolve_fields(window, float(x_mm), float(y_mm))
    if not rows:
        return False
    points = getattr(window, "_probe_sample_points", None)
    if points is None:
        points = []
        window._probe_sample_points = points
    points.append((float(x_mm), float(y_mm)))
    refresh_sample_points(window)
    return True


def clear_sample_points(window) -> None:
    """Clear all per-point 3-phase readouts in the result drawer."""
    window._probe_sample_points = []
    refresh_sample_points(window)


def refresh_sample_points(window) -> None:
    """Render per-point 3-phase readout cards from the accepted result."""
    container = getattr(window, "_probe_points_layout", None)
    if container is None:
        return
    _clear_layout(container)
    theme = get_theme()
    points: list[tuple[float, float]] = list(getattr(window, "_probe_sample_points", ()))
    band = getattr(window, "_result_readout_band", None)
    if band is not None:
        band.header.set_title(f"读数 {len(points)}" if points else "读数")

    if not window.cache.has_any_results() or not points:
        hint = QLabel("点击二维结果场图添加定点三相读数")
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {theme['tert']}; font-size: 9pt; padding: 8px 16px; "
            "background: transparent; border: none;"
        )
        container.addWidget(hint)
        return

    from .coord_inspector import _resolve_fields

    for idx, (x_mm, y_mm) in enumerate(points, start=1):
        rows = _resolve_fields(window, x_mm, y_mm)
        by_key = {k: (v, u) for k, v, u in rows}

        card_wrap = QWidget()
        card_wrap.setStyleSheet("background: transparent;")
        cw = QVBoxLayout(card_wrap)
        cw.setContentsMargins(16, 6, 16, 6)
        cw.setSpacing(4)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        tag = QLabel(f"#{idx}")
        tag.setStyleSheet(
            f"color: {theme['fg']}; font-size: 9.5pt; font-weight: 600; "
            "background: transparent; border: none;"
        )
        coord = QLabel(f"<i>x</i> {x_mm:.1f} · <i>y</i> {y_mm:.1f}\u202fmm")
        coord.setTextFormat(Qt.TextFormat.RichText)
        coord.setStyleSheet(
            f"color: {theme['tert']}; font-family: {theme['mono_family']}; "
            "font-size: 8.5pt; background: transparent; border: none;"
        )
        head.addWidget(tag)
        head.addStretch(1)
        head.addWidget(coord)
        cw.addLayout(head)

        box = QFrame()
        box.setStyleSheet(
            f"QFrame {{ background: {theme['sunken']}; "
            f"border: 1px solid {theme['border']}; border-radius: {RADIUS_BTN}px; }}"
        )
        bl = QHBoxLayout(box)
        bl.setContentsMargins(8, 6, 8, 6)
        bl.setSpacing(6)
        for key, sym_html in (
            ("T_fA", SYM["T_fA"]),
            ("T_fB", SYM["T_fB"]),
            ("T_s", SYM["T_s"]),
        ):
            val, unit = by_key.get(key, ("—", ""))
            cell = QWidget()
            cell.setStyleSheet("background: transparent; border: none;")
            cl = QVBoxLayout(cell)
            cl.setContentsMargins(2, 0, 2, 0)
            cl.setSpacing(1)
            k_lbl = QLabel(sym_html)
            k_lbl.setTextFormat(Qt.TextFormat.RichText)
            k_lbl.setStyleSheet(
                f"color: {theme['sub']}; font-size: 8.5pt; background: transparent; border: none;"
            )
            v_lbl = QLabel(f"{val}\u202f{unit}".strip() if val != "—" else "—")
            v_lbl.setStyleSheet(
                f"color: {theme['fg']}; font-family: {theme['mono_family']}; "
                "font-size: 9pt; font-weight: 600; background: transparent; border: none;"
            )
            cl.addWidget(k_lbl)
            cl.addWidget(v_lbl)
            bl.addWidget(cell, 1)
        cw.addWidget(box)
        container.addWidget(card_wrap)


def build_result_drawer_content(window) -> QWidget:
    """Build the Style P2 collapsible result drawer bands (no left strips/underlines)."""
    theme = get_theme()
    body = QWidget()
    body.setStyleSheet("background: transparent;")
    vlay = QVBoxLayout(body)
    vlay.setContentsMargins(0, 0, 0, 0)
    vlay.setSpacing(0)

    window._sb_labels = {}
    window._probe_sample_points = []

    # Band 1: 计算状态
    status_band = CollapsibleBand(
        "计算状态",
        first=True,
        collapsible=True,
        expanded=True,
        actions=[
            ("日志", window.dialogs.show_solve_log),
            ("诊断", window.results.show_diag_dialog),
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
    design_row = QWidget()
    design_row.setStyleSheet("background: transparent;")
    design_col = QVBoxLayout(design_row)
    design_col.setContentsMargins(16, 6, 16, 6)
    design_col.setSpacing(2)
    design_head = QHBoxLayout()
    design_head.setContentsMargins(0, 0, 0, 0)
    design_head.setSpacing(8)
    design_key = QLabel("设计资格")
    design_key.setStyleSheet(
        f"color: {theme['sub']}; font-size: 9.5pt; font-weight: 400; "
        "background: transparent; border: none;"
    )
    design_val = QLabel("—")
    design_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    design_val.setStyleSheet(
        f"color: {theme['fg']}; font-family: {theme['mono_family']}; "
        "font-size: 9.5pt; font-weight: 600; background: transparent; border: none;"
    )
    design_head.addWidget(design_key)
    design_head.addStretch(1)
    design_head.addWidget(design_val)
    design_col.addLayout(design_head)
    design_reason = QLabel()
    design_reason.setWordWrap(True)
    design_reason.setStyleSheet(
        f"color: {theme['warn']}; font-size: 11px; font-weight: 400; "
        "background: transparent; padding: 0px;"
    )
    design_reason.hide()
    design_col.addWidget(design_reason)
    ck_body.addWidget(design_row)
    window._sb_labels["design"] = design_val
    window._sb_labels["design_reason"] = design_reason
    vlay.addWidget(check_band)

    # Band 3: 读数 (per-point 3-phase readouts; whole-device KPIs live in bottom ReadoutStrip)
    readout_band = CollapsibleBand(
        "读数",
        collapsible=True,
        expanded=True,
        actions=[("清除", lambda: clear_sample_points(window))],
    )
    window._result_readout_band = readout_band
    rd_host = QWidget()
    rd_host.setStyleSheet("background: transparent;")
    window._probe_points_layout = QVBoxLayout(rd_host)
    window._probe_points_layout.setContentsMargins(0, 2, 0, 6)
    window._probe_points_layout.setSpacing(2)
    readout_band.body_layout().addWidget(rd_host)
    vlay.addWidget(readout_band)
    refresh_sample_points(window)

    # Band 4: 画布
    canvas_band = CollapsibleBand("画布", collapsible=True, expanded=True)
    cv_body = canvas_band.body_layout()
    cv_body.setContentsMargins(0, 4, 0, 6)

    def _toggle_probe() -> None:
        toggle = getattr(window, "_toggle_coord_inspector", None)
        if toggle is not None:
            toggle()

    _build_action_row(cv_body, "坐标探针  (Ctrl+I)", _toggle_probe, theme=theme)
    window._btn_drawer_export_figure = _build_action_row(
        cv_body,
        "导出图像 — PNG / SVG / PDF",
        window.result_export.export_figure,
        theme=theme,
    )
    window._btn_drawer_export_figure.setEnabled(False)
    window._btn_drawer_export_results = _build_action_row(
        cv_body,
        "导出完整结果 — CSV",
        window.result_export.export_results,
        theme=theme,
    )
    window._btn_drawer_open_folder = _build_action_row(
        cv_body,
        "打开运行目录",
        lambda: window.dialogs.open_output_folder(scope="accepted_result"),
        theme=theme,
    )
    window._btn_drawer_open_folder.setEnabled(False)
    vlay.addWidget(canvas_band)

    vlay.addStretch(1)
    window._result_drawer_content = body
    return body


def result_metric_texts(window) -> dict[str, str]:
    """Format the published result for the readout strip and run history."""
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


def _values_equal(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isnan(a) and math.isnan(b):
            return True
        return math.isclose(float(a), float(b), rel_tol=1e-7, abs_tol=1e-9)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_values_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_values_equal(x, y) for x, y in zip(a, b))
    return a == b


def _compare_config_snapshots(window, saved_cfg: dict) -> bool:
    """Compare current window inputs against a saved ComputeConfig snapshot dict."""
    from .window_config import config_from_window

    try:
        is_3d = window.combo_dim.currentIndex() == 1
        cur_cfg = asdict(config_from_window(window, strict=True, force_3d=is_3d))
    except (ValueError, TypeError):
        return True

    if bool(cur_cfg.get("is_3d")) != bool(saved_cfg.get("is_3d")):
        return True
    if cur_cfg.get("df_mode") != saved_cfg.get("df_mode"):
        return True
    if (cur_cfg.get("extrap") or {}).get("allow") != (saved_cfg.get("extrap") or {}).get("allow"):
        return True
    if not _values_equal(cur_cfg.get("sco2_nu"), saved_cfg.get("sco2_nu")):
        return True

    for section in ("geometry", "solver", "bc_A", "bc_B", "zones"):
        if not _values_equal(cur_cfg.get(section), saved_cfg.get(section)):
            return True

    cur_flags = dict(cur_cfg.get("flags") or {})
    sav_flags = dict(saved_cfg.get("flags") or {})
    # Display temperature unit does not affect physical computation (inputs are stored in K).
    cur_flags.pop("temp_unit", None)
    sav_flags.pop("temp_unit", None)
    if not _values_equal(cur_flags, sav_flags):
        return True

    for side in ("fluid_A", "fluid_B"):
        cf = dict(cur_cfg.get(side) or {})
        sf = dict(saved_cfg.get(side) or {})
        # In 3D mass-flow mode, u_mps is derived by the solver and read-only in the UI.
        if cf.get("mass_flow_kg_s") is not None and sf.get("mass_flow_kg_s") is not None:
            cf.pop("u_mps", None)
            sf.pop("u_mps", None)
        if not _values_equal(cf, sf):
            return True
    return False


def is_result_stale(window) -> bool:
    """Return True when active case inputs differ from the accepted result."""
    result = window.cache.get_result()
    if result is None:
        return False
    provenance = result.metadata.get("run_provenance")
    saved_preset = provenance.get("preset") if isinstance(provenance, dict) else None
    if not isinstance(saved_preset, dict):
        saved_cfg = (
            provenance.get("config_snapshot") if isinstance(provenance, dict) else None
        ) or result.metadata.get("config_snapshot")
        if isinstance(saved_cfg, dict):
            return _compare_config_snapshots(window, saved_cfg)
        return False

    from .window_config import LINE_EDITS, field_active, mass_flow_active

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

    cur_combos = current.get("combos", {})
    sav_combos = saved_preset.get("combos", {})
    for key in window.case_files.PRESET_COMBOS:
        if not is_3d and key in ("combo_inlet_modeA", "combo_inlet_modeB"):
            continue
        if cur_combos.get(key) != sav_combos.get(key):
            return True

    cur_checks = current.get("checks", {})
    sav_checks = saved_preset.get("checks", {})
    for key in window.case_files.PRESET_CHECKS:
        if cur_checks.get(key) != sav_checks.get(key):
            return True

    cur_edits = current.get("line_edits", {})
    sav_edits = saved_preset.get("line_edits", {})
    for name, spec in LINE_EDITS.items():
        if not field_active(window, spec, is_3d=is_3d):
            continue
        # In 3D mass-flow mode, le_uA / le_uB displays the solver-resolved speed.
        if name == "le_uA" and mass_flow_active(window, "A"):
            continue
        if name == "le_uB" and mass_flow_active(window, "B"):
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

    if cur_checks.get("chk_zones"):
        if not _values_equal(current.get("zone_inputs"), saved_preset.get("zone_inputs")):
            return True
    if not _values_equal(current.get("continuous_field"), saved_preset.get("continuous_field")):
        return True
    if not _values_equal(
        current.get("sco2_nu_parameters") or {},
        saved_preset.get("sco2_nu_parameters") or {},
    ):
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
    result = window.cache.get_result()
    d = window.results.summary()
    has_result = result is not None
    status_kind, status_text = evaluate_result_status(result, d)

    if labels:
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

        status_ok = {"ok": True, "warn": False, "err": "err", "idle": None}[status_kind]
        _mark("status", status_text, status_ok)

        qualification = d.get("qualification", {})
        phys_passed = qualification.get("physical", {}).get("passed")
        rel = d.get("closure_rel")
        labels["closure"].setToolTip(d.get("closure_basis", "两侧焓流"))
        if rel is not None and rel == rel:
            _mark("closure", f"{abs(rel) * 100:.1f}\u202f%", phys_passed)
        else:
            _mark("closure", "—", None)

        env = d.get("envelope_valid")
        _mark(
            "envelope",
            "有效 ✓" if env is True else ("失效 ⚠" if env is False else "—"),
            env if env is not None else None,
        )

        extrap_passed = qualification.get("applicability", {}).get("passed")
        design_passed = qualification.get("design", {}).get("eligible")
        for key, passed in (("extrap", extrap_passed), ("design", design_passed)):
            _mark(
                key,
                "通过 ✓" if passed is True else "未通过 ⚠" if passed is False else "未核实",
                passed,
            )

        checks_verdicts = [phys_passed, extrap_passed, design_passed]
        if d.get("mode") == "3d" or env is not None:
            checks_verdicts.append(env)
        fails = sum(1 for v in checks_verdicts if v is False)
        unknowns = sum(1 for v in checks_verdicts if v is None)

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
            elif unknowns > 0:
                check_lbl.setText("部分未核实")
                check_lbl.setStyleSheet(
                    f"color: {theme['tert']}; font-size: 11px; font-weight: 500; "
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
        reason_lbl = labels.get("design_reason")
        if reason_lbl is not None:
            specific = [
                r.split("（实际 ")[0].strip()
                for r in reasons
                if r.strip() and r.strip() != "关联式适用范围未通过"
            ]
            if not specific and design_passed is False and d.get("extrap"):
                specific = [str(d["extrap"][0]).split("（")[0].strip()]
            if specific:
                reason_lbl.setText(specific[0])
                reason_lbl.setStyleSheet(
                    f"color: {theme['warn']}; font-size: 11px; font-weight: 400; "
                    "background: transparent; padding: 0px;"
                )
                reason_lbl.show()
            else:
                reason_lbl.clear()
                reason_lbl.hide()

        from sjtu_tpmshx.applications.gui.ui.field_results import recorded_elapsed_s

        it = (d.get("iters") or {}).get("iter_outer")
        ws = recorded_elapsed_s(result)
        labels["iters"].setText(
            f"{it if it is not None else '—'} · "
            f"{fmt_duration(ws) if isinstance(ws, (int, float)) else '—'}"
        )

    export_label = "导出完整结果 — CSV + NPZ" if d.get("mode") == "3d" else "导出完整结果 — CSV"
    btn_export = getattr(window, "_btn_drawer_export_results", None)
    if btn_export is not None:
        btn_export.setText(export_label)
        btn_export.setEnabled(has_result)
    act_export = getattr(window, "_act_export_results", None)
    if act_export is not None:
        act_export.setText(export_label)
        act_export.setEnabled(has_result)

    btn_folder = getattr(window, "_btn_drawer_open_folder", None)
    if btn_folder is not None:
        btn_folder.setEnabled(
            window.dialogs.resolve_output_directory(scope="accepted_result") is not None
        )

    refresh_sample_points(window)

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
            if status_kind == "err":
                notice = ReadoutNotice("未收敛", "结果仅供参考，请核查诊断", kind="err")
            elif extrap_list:
                first_reason = str(extrap_list[0]).split("（")[0].strip()
                if not any("\u4e00" <= ch <= "\u9fff" for ch in first_reason):
                    first_reason = warning_strip_summary(d)
                else:
                    if len(first_reason) > 36:
                        first_reason = first_reason[:35] + "…"
                    if len(extrap_list) > 1:
                        first_reason = f"{first_reason}（共 {len(extrap_list)} 项）"
                notice = ReadoutNotice("外推提示", first_reason, kind="warn")
            elif status_kind == "warn":
                notice = ReadoutNotice("运行提示", warning_strip_summary(d), kind="warn")
        strip.set_items(items)
        strip.set_notice(notice)
        strip.set_stale(is_result_stale(window))

    refresh_header_status(window)


def refresh_header_status(window) -> None:
    """Update the header run-info trigger text and painted status dot."""
    btn = getattr(window, "btn_run_info", None)
    if btn is None:
        return
    from sjtu_tpmshx.applications.gui.ui.field_results import recorded_elapsed_s

    theme = get_theme()
    result = window.cache.get_result()
    d = window.results.summary() if result is not None else {}
    elapsed = recorded_elapsed_s(result)
    dur = fmt_duration(elapsed) if isinstance(elapsed, (int, float)) else ""

    if not window.single_run.is_idle():
        dot_color = theme["accent_fg"]
        text = "正在求解…"
    else:
        status_kind, _ = evaluate_result_status(result, d)
        if status_kind == "idle" and result is None:
            dot_color = theme["tert"]
            text = "尚未计算"
        elif status_kind == "err":
            dot_color = theme["err"]
            text = f"未收敛 · {dur}" if dur else "未收敛"
        elif status_kind == "warn":
            dot_color = theme["warn"]
            prefix = "上次结果" if window.workbench.active_tab == "layout" else "完成"
            text = f"{prefix} · 有提示 · {dur}" if dur else f"{prefix} · 有提示"
        elif status_kind == "ok":
            dot_color = theme["ok"]
            prefix = "上次结果" if window.workbench.active_tab == "layout" else "完成"
            text = f"{prefix} · {dur}" if dur else prefix
        else:
            dot_color = theme["tert"]
            text = "状态未知"

    btn.setIcon(_status_dot_icon(dot_color))
    btn.setText(f"{text}  ▾")
    btn.setStyleSheet(
        f"QPushButton {{ background: {theme['panel']}; color: {theme['fg']}; "
        f"border: 1px solid {theme['border']}; border-radius: {RADIUS_BTN}px; "
        "padding: 0 10px; font-size: 9.5pt; font-weight: 500; }"
        f"QPushButton:hover {{ background: {theme['hover']}; border-color: {theme['border_strong']}; }}"
    )


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

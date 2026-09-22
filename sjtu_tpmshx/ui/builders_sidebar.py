"""Result metrics and diagnostics below the field workbench."""
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QWidget,
    QScrollArea, QSizePolicy,
)
from PySide6.QtCore import Qt

from .theme import get_theme, glass_surface
from .responsive import ResponsiveRow


def _build_result_sidebar(window, _t, t):
    """Keep the existing result-label interface in a horizontal footer."""
    side = QFrame()
    side.setStyleSheet("QFrame{background:transparent; border:none;}")
    slay = QVBoxLayout(side)
    slay.setContentsMargins(20, 0, 20, 6)
    slay.setSpacing(6)

    _card_qss = f"QWidget#resultDiagnostics{{{glass_surface(_t)}}}"
    _h_qss = (f"color:{_t.get('sub_fg', _t['fg'])}; background:transparent;"
              " border:none; font-size:9pt; font-weight:600;")
    _lbl_qss = (f"color:{_t.get('sub_fg', _t['fg'])}; background:transparent;"
                " border:none; font-size:9pt;")
    _val_qss = (f"color:{_t['fg']}; background:transparent; border:none;"
                f" font-family:{_t['mono_family']}; font-size:18pt;"
                " font-weight:600;")
    _val2_qss = (f"color:{_t['fg']}; background:transparent; border:none;"
                 f" font-family:{_t['mono_family']}; font-size:9pt;"
                 " font-weight:600;")

    window._sb_labels = {}

    def _kv(row, label, key, primary=False):
        group = QVBoxLayout() if primary else QHBoxLayout()
        group.setSpacing(4 if primary else 8)
        l = QLabel(label); l.setStyleSheet(_lbl_qss)
        v = QLabel("—"); v.setStyleSheet(_val_qss if primary else _val2_qss)
        group.addWidget(l); group.addWidget(v)
        row.addLayout(group, 1 if primary else 0)
        window._sb_labels[key] = v
        return l

    window._sb_result_heading = QLabel("本次结果")
    window._sb_result_heading.setStyleSheet(_h_qss)
    slay.addWidget(window._sb_result_heading)
    window._sb_result_heading.hide()  # The workbench header shows the run mode.
    headline = ResponsiveRow(threshold=640, spacing=8)
    window._result_kpi_row = headline
    heat_pressure = QWidget()
    heat_row = QHBoxLayout(heat_pressure)
    heat_row.setContentsMargins(0, 0, 0, 0)
    heat_row.setSpacing(24)
    outlet_pressure = QWidget()
    outlet_row = QHBoxLayout(outlet_pressure)
    outlet_row.setContentsMargins(0, 0, 0, 0)
    outlet_row.setSpacing(24)
    headline.addWidget(heat_pressure)
    headline.addWidget(outlet_pressure)
    _kv(heat_row, "换热量 Q", 'q', primary=True)
    _kv(heat_row, "ΔP_A [Pa]", 'dpa', primary=True)
    _kv(outlet_row, "ΔP_B [Pa]", 'dpb', primary=True)
    unit = "°C" if getattr(window, '_temp_unit', 'K') == 'C' else "K"
    window._lbl_sidebar_tout_unit = _kv(
        outlet_row, f"出口温度 A / B [{unit}]", 'tout', primary=True)
    window._sb_labels['tout'].setWordWrap(True)
    slay.addWidget(headline)

    diagnostic = ResponsiveRow(threshold=680, spacing=6)
    window._result_diagnostic_row = diagnostic
    diagnostic.setObjectName('resultDiagnostics')
    diagnostic.setStyleSheet(_card_qss)
    diagnostic.layout().setContentsMargins(12, 5, 12, 5)
    confidence = QWidget()
    row = QHBoxLayout(confidence)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(16)
    _kv(row, "能量闭合", 'closure')
    _kv(row, "压缩性包络", 'envelope')
    _kv(row, "外推", 'extrap')
    row.addStretch(1)
    convergence = QWidget()
    detail_row = QHBoxLayout(convergence)
    detail_row.setContentsMargins(0, 0, 0, 0)
    detail_row.setSpacing(16)
    detail_row.addStretch(1)
    diagnostic.addWidget(confidence)
    diagnostic.addWidget(convergence)

    _kv(detail_row, "迭代 / 耗时", 'iters')
    btn_diag = QPushButton("诊断详情…")
    btn_diag.setFixedHeight(26)
    btn_diag.setStyleSheet(t.style('BTN_TERTIARY'))
    btn_diag.clicked.connect(
        lambda: getattr(window, '_show_diag_dialog', lambda: None)())
    detail_row.addWidget(btn_diag)
    slay.addWidget(diagnostic)

    # Wrapped metrics must not consume the field viewport on short windows.
    # Keep the user's summary choice; only its overflow needs scrolling.
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}"
                        + t.style('SCROLLBAR'))
    scroll.viewport().setAutoFillBackground(False)
    scroll.setWidget(side)
    scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
    scroll.setMaximumHeight(max(
        120, window._sb_labels['q'].sizeHint().height()
        + window._lbl_sidebar_tout_unit.sizeHint().height() + btn_diag.height() + 36))
    scroll.hide()
    window._result_sidebar = scroll
    return scroll


def refresh_result_sidebar(window):
    """Refresh result metrics and diagnostics after publication or tab changes."""
    labels = getattr(window, '_sb_labels', None)
    if not labels:
        return
    _t = get_theme()
    def _value(attr):
        w = getattr(window, attr, None)
        s = w.text().strip() if w is not None else ''
        return s if s and s != '—' else '—'
    labels['q'].setText(f"{_value('_r_Q')} {getattr(window, '_result_Q_unit', '')}".strip())
    labels['dpa'].setText(_value('_r_dP_A'))
    labels['dpb'].setText(_value('_r_dP_B'))
    labels['tout'].setText(f"{_value('_r_ToutA')} / {_value('_r_ToutB')}")

    d = getattr(window, '_diag_summary', None) or {}
    mode = d.get('mode')
    window._sb_result_heading.setText(
        f"本次结果 · {mode.upper()}" if mode in ('2d', '3d') else "本次结果")
    _good = _t.get('accent_green', '#22C55E')
    _warn = _t.get('warn', '#FBBF24')

    def _mark(key, text, ok):
        lbl = labels[key]
        lbl.setText(text)
        color = {True: _good, False: _warn, None: _t['fg']}[ok]
        lbl.setStyleSheet(
            f"color:{color}; background:transparent; border:none;"
            f" font-family:{_t['mono_family']}; font-size:9pt;"
            " font-weight:600;")
    rel = d.get('closure_rel')
    labels['closure'].setToolTip(d.get('closure_basis', '两侧焓流'))
    if rel is not None and rel == rel:          # not NaN
        _mark('closure', f"{abs(rel) * 100:.1f} % {'✓' if abs(rel) < 0.05 else '⚠'}",
              abs(rel) < 0.05)
    else:
        _mark('closure', "—", None)
    env = d.get('envelope_valid')
    _mark('envelope', "有效 ✓" if env else ("失效 ⚠" if env is not None else "—"),
          env if env is not None else None)
    n_ex = len(d.get('extrap') or [])
    _mark('extrap', f"{n_ex} 项 ⚠" if n_ex else "无 ✓", not n_ex)
    it = (d.get('iters') or {}).get('iter_outer')
    ws = d.get('wall_s')
    labels['iters'].setText(
        f"{it if it is not None else '—'} · "
        f"{f'{ws:.1f} s' if isinstance(ws, (int, float)) else '—'}")


def update_result_sidebar_visibility(window):
    """Keep the user's summary choice while navigating result tabs."""
    side = getattr(window, '_result_sidebar', None)
    if side is None:
        return
    show = (getattr(window, '_active_tab', None) in ('temp', 'pres', 'vel', '3d')
            and getattr(window, '_has_results', False))
    toggle = window.btn_result_summary
    toggle.setVisible(bool(show))
    side.setVisible(bool(show) and toggle.isChecked()
                    and not getattr(window, '_3d_immersive', False))

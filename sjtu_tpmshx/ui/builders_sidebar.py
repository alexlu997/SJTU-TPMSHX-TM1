"""结果工作台诊断侧栏 — moved verbatim from builders_canvas.py (openspec split-ui-main, 2026-07-03)."""
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)

from .theme import get_theme


def _build_result_sidebar(window, _t, t):
    """Diagnostics sidebar for the 结果 tab (ui-plan3-workbench T2)."""
    from .sparkline import Sparkline
    side = QFrame()
    side.setFixedWidth(298)
    side.setStyleSheet("QFrame{background:transparent; border:none;}")
    slay = QVBoxLayout(side)
    slay.setContentsMargins(0, 0, 4, 0)
    slay.setSpacing(8)

    _card_qss = (f"QFrame{{background:{_t['card_bg']};"
                 f" border:1px solid {_t['card_border']}; border-radius:6px;}}")
    _h_qss = (f"color:{_t.get('sub_fg', _t['fg'])}; background:transparent;"
              " border:none; font-size:8pt; font-weight:600;"
              " letter-spacing:1.2px;")
    _lbl_qss = (f"color:{_t.get('sub_fg', _t['fg'])}; background:transparent;"
                " border:none; font-size:9pt;")
    _val_qss = (f"color:{_t['val']}; background:transparent; border:none;"
                f" font-family:{_t['mono_family']}; font-size:10pt;"
                " font-weight:700;")
    _val2_qss = (f"color:{_t['fg']}; background:transparent; border:none;"
                 f" font-family:{_t['mono_family']}; font-size:9pt;"
                 " font-weight:600;")

    window._sb_labels = {}

    def _card(title):
        c = QFrame(); c.setStyleSheet(_card_qss)
        cl = QVBoxLayout(c)
        cl.setContentsMargins(12, 8, 12, 10); cl.setSpacing(4)
        h = QLabel(title); h.setStyleSheet(_h_qss)
        cl.addWidget(h)
        return c, cl

    def _kv(cl, label, key, primary=False):
        row = QHBoxLayout(); row.setSpacing(8)
        l = QLabel(label); l.setStyleSheet(_lbl_qss)
        v = QLabel("—"); v.setStyleSheet(_val_qss if primary else _val2_qss)
        row.addWidget(l); row.addStretch(1); row.addWidget(v)
        cl.addLayout(row)
        window._sb_labels[key] = v
        return v

    c1, cl1 = _card("本次结果")
    _kv(cl1, "Q", 'q', primary=True)
    _kv(cl1, "ΔP_A [Pa]", 'dpa', primary=True)
    _kv(cl1, "ΔP_B [Pa]", 'dpb', primary=True)
    _kv(cl1, "T_out A / B", 'tout')
    slay.addWidget(c1)

    c2, cl2 = _card("可信度")
    _kv(cl2, "能量闭合", 'closure')
    _kv(cl2, "压缩性包络", 'envelope')
    _kv(cl2, "代理外推", 'extrap')
    slay.addWidget(c2)

    c3, cl3 = _card("收敛 · SIMPLE-A 残差 (log₁₀)")
    spark = Sparkline(height=52)
    cl3.addWidget(spark)
    window._resid_spark = spark
    _kv(cl3, "外循环 / 耗时", 'iters')
    btn_diag = QPushButton("诊断详情…")
    btn_diag.setFixedHeight(26)
    btn_diag.setStyleSheet(t.style('BTN_TERTIARY'))
    btn_diag.clicked.connect(
        lambda: getattr(window, '_show_diag_dialog', lambda: None)())
    cl3.addWidget(btn_diag)
    slay.addWidget(c3)

    slay.addStretch(1)
    side.hide()
    window._result_sidebar = side
    return side


def refresh_result_sidebar(window):
    """Repaint the sidebar from _res_chips (KPI) + _diag_summary +
    _live_residuals. Cheap; called after each result lands and on tab
    switches into the result family."""
    labels = getattr(window, '_sb_labels', None)
    if not labels:
        return
    _t = get_theme()
    chips = getattr(window, '_res_chips', {})

    def _chip(key):
        w = chips.get(key)
        s = w.text().strip() if w is not None else ''
        return s if s and s != '—' else '—'
    labels['q'].setText(f"{_chip('Q')} {getattr(window, '_result_Q_unit', '')}".strip())
    labels['dpa'].setText(_chip('dPA'))
    labels['dpb'].setText(_chip('dPB'))
    labels['tout'].setText(f"{_chip('ToutA')} / {_chip('ToutB')}")

    d = getattr(window, '_diag_summary', None) or {}
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

    spark = getattr(window, '_resid_spark', None)
    hist = (getattr(window, '_live_residuals', None) or {}).get('A') or []
    if d.get('mode') == '3d':
        hist = []
    if spark is not None:
        import math as _m
        spark._data = [
            _m.log10(max(r, 1e-20)) for _i, r in hist[-500:]
            if isinstance(r, (int, float)) and r == r]
        spark.update()


def update_result_sidebar_visibility(window):
    """Sidebar shows only on the result family with results present."""
    side = getattr(window, '_result_sidebar', None)
    if side is None:
        return
    show = (getattr(window, '_active_tab', None) in ('temp', 'pres', 'vel', '3d')
            and getattr(window, '_has_results', False))
    side.setVisible(bool(show))

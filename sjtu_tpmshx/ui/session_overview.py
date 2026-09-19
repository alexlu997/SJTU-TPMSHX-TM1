"""Overview dialog — dashboard-style digest of the current session.

Bigger KPI cards than the header strip, Q-history sparkline across
recent runs, preset quick-launch buttons, and recent-run chips with
click-to-restore. Opens from the command palette or `Ctrl+D`.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)

from .theme import get_theme
from .sparkline import Sparkline


def _float(s):
    try: return float(str(s).strip())
    except Exception: return None


class OverviewDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self._w = window
        self.setWindowTitle("Overview — session snapshot")
        self.resize(980, 620)

        t = get_theme()
        _surface = t.get('surface_raised', t['card_bg'])
        _elev = t.get('surface_elevated', t['card_bg'])
        _border = t.get('border_subtle', t['card_border'])
        _sub = t.get('sub_fg', t['fg'])
        _hero = t['sans_family']
        _mono = t['mono_family']
        self.setStyleSheet(f"QDialog{{background:{_surface};}}")

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18); root.setSpacing(16)

        # Header title + subtitle
        hdr = QHBoxLayout()
        title = QLabel("Session overview")
        title.setStyleSheet(
            f"color:{t['fg']}; font-size:20pt; font-weight:700;"
            f"font-family:{_hero}; background:transparent; border:none;"
            "letter-spacing:-0.3px;")
        hdr.addWidget(title)
        hdr.addStretch(1)
        # P1.9: version from the _version leaf — importing main here was the
        # ui->main cycle edge (composition root pulled in for one constant).
        from sjtu_tpmshx._version import __version__ as _app_version
        from .field_factory import default_factory
        _tm = default_factory().theme
        from .fmt import preset_display as _pd
        sub = QLabel(
            f"Preset: {_pd(getattr(window, '_active_preset_name', '—'))}  "
            f"·  Workspace: {getattr(window, '_active_workspace', 'A')}  "
            f"·  v{_app_version}")
        sub.setStyleSheet(
            f"color:{_sub}; font-size:10pt; font-family:{_mono};"
            "background:transparent; border:none;")
        hdr.addWidget(sub, 0, Qt.AlignmentFlag.AlignBottom)
        root.addLayout(hdr)

        # ── KPI hero row ───────────────────────────────────────────
        kpi_row = QHBoxLayout(); kpi_row.setSpacing(12)
        def _kpi(label, value, unit, accent):
            card = QFrame()
            card.setStyleSheet(
                f"QFrame{{background:{_elev}; border:1px solid {_border};"
                "border-radius:6px;}")
            card.setFixedHeight(130)
            v = QVBoxLayout(card)
            v.setContentsMargins(18, 12, 18, 12); v.setSpacing(2)
            cap = QLabel(label)
            cap.setStyleSheet(
                f"color:{accent}; font-size:9pt; font-weight:700;"
                "letter-spacing:1.6px; background:transparent; border:none;"
                f"font-family:{t['sans_family']};")
            val = QLabel(value)
            val.setStyleSheet(
                f"color:{t['fg']}; font-family:{_hero};"
                "font-size:34pt; font-weight:600;"
                "background:transparent; border:none;"
                "font-feature-settings: 'tnum' on, 'lnum' on;")
            un = QLabel(unit)
            un.setStyleSheet(
                f"color:{_sub}; font-size:10pt;"
                "background:transparent; border:none;"
                f"font-family:{_mono};")
            v.addWidget(cap); v.addWidget(val, 1); v.addWidget(un)
            return card

        def _g(attr):
            w = getattr(window, attr, None)
            if w is None: return '—'
            txt = w.text().strip()
            return txt or '—'

        kpi_row.addWidget(_kpi("HEAT TRANSFER  Q",
                                 _g('_r_Q'), getattr(window, '_result_Q_unit', 'W/m'),
                                 t.get('accent_primary', '#3B82F6')))
        kpi_row.addWidget(_kpi("PRESSURE DROP  ΔP_A",
                                 _g('_r_dP_A'), "Pa",
                                 t.get('accent_orange', '#F97316')))
        kpi_row.addWidget(_kpi("PRESSURE DROP  ΔP_B",
                                 _g('_r_dP_B'), "Pa",
                                 t.get('accent_orange', '#F97316')))
        root.addLayout(kpi_row)

        # ── Trend sparkline of recent Q values ────────────────────
        trend_card = QFrame()
        trend_card.setStyleSheet(
            f"QFrame{{background:{_elev}; border:1px solid {_border};"
            "border-radius:6px;}")
        trend_card.setFixedHeight(110)
        tv = QVBoxLayout(trend_card)
        tv.setContentsMargins(18, 10, 18, 10); tv.setSpacing(4)
        trend_cap = QLabel("RECENT Q TREND")
        trend_cap.setStyleSheet(
            f"color:{_sub}; font-size:8pt; font-weight:700;"
            "letter-spacing:1.4px; background:transparent; border:none;"
            f"font-family:{t['sans_family']};")
        tv.addWidget(trend_cap)
        spark = Sparkline(height=60)
        for e in reversed(list(getattr(window, '_recent_runs', []) or [])):
            if e.get('Q_unit') != getattr(window, '_result_Q_unit', 'W/m'):
                continue
            v = _float(e.get('Q'))
            if v is not None:
                spark.push(v)
        tv.addWidget(spark, 1)
        root.addWidget(trend_card)

        # ── Preset quick-launch row ───────────────────────────────
        preset_label = QLabel("QUICK PRESETS")
        preset_label.setStyleSheet(
            f"color:{_sub}; font-size:8pt; font-weight:700;"
            "letter-spacing:1.4px; background:transparent; border:none;"
            f"padding-top:4px; font-family:{t['sans_family']};")
        root.addWidget(preset_label)

        pr_row = QHBoxLayout(); pr_row.setSpacing(8)
        for name in getattr(window, '_BUILTIN_PRESETS', ()):
            btn = QPushButton(name)
            btn.setFixedHeight(34)
            btn.setStyleSheet(_tm.style('BTN_SECONDARY'))
            btn.clicked.connect(
                lambda _c=False, n=name: self._load_preset(n))
            pr_row.addWidget(btn)
        pr_row.addStretch(1)
        root.addLayout(pr_row)

        # ── Recent runs chips ─────────────────────────────────────
        recents = list(getattr(window, '_recent_runs', []) or [])[:5]
        if recents:
            rc_label = QLabel("RECENT RUNS  (click to restore)")
            rc_label.setStyleSheet(
                f"color:{_sub}; font-size:8pt; font-weight:700;"
                "letter-spacing:1.4px; background:transparent; border:none;"
                f"padding-top:4px; font-family:{t['sans_family']};")
            root.addWidget(rc_label)
            rc_row = QHBoxLayout(); rc_row.setSpacing(8)
            for e in recents:
                btn = QPushButton(
                    f"  {e.get('label', '?')}   Q={e.get('Q','?')} {e.get('Q_unit', '?')}  ")
                btn.setFixedHeight(32)
                btn.setStyleSheet(_tm.style('BTN_TERTIARY'))
                btn.clicked.connect(
                    lambda _c=False, entry=e: self._load_recent(entry))
                rc_row.addWidget(btn)
            rc_row.addStretch(1)
            root.addLayout(rc_row)

        root.addStretch(1)

        # Close button
        close_row = QHBoxLayout(); close_row.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.setFixedHeight(32); btn_close.setMinimumWidth(110)
        btn_close.setStyleSheet(_tm.style('BTN_TERTIARY'))
        btn_close.clicked.connect(self.accept)
        close_row.addWidget(btn_close)
        root.addLayout(close_row)

    def _load_preset(self, name):
        if hasattr(self._w, '_load_named_preset'):
            self._w._load_named_preset(name)
        self.accept()

    def _load_recent(self, entry):
        self._w._load_recent_run(entry)
        self.accept()


def open_overview(window):
    OverviewDialog(window).exec()

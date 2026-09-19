"""UI construction helpers for SJTU-TPMSHX Main_Menu.

Extracted from main.py (Task B.6). All functions take `window` (Main_Menu
instance) as first argument. Widget attributes are stored directly on
`window` (`window.combo_tpms = ...`), preserving the original access pattern.

Batch-2 split (2026-06-10): the page builders now live in sibling modules —
``builders_base`` (section/row/res_row/add_row + _ResultLabel),
``builders_domain`` (Geometry page + _on_dim_changed),
``builders_fluids`` (Boundary Conditions page),
``builders_canvas`` (canvas cards, tab toolbar, zoom helpers).
This module keeps the top-level assembly (build_ui / build_param_tabs)
and the zone page; page builders and row helpers live in the sibling
``builders_*`` modules and must be imported from there.

Intra-module calls use top-level function names (e.g., `build_param_tabs(window)`
instead of `window._build_param_tabs()`) so the wiring within this module is
direct. Calls to methods that remain in main.py use `window.xxx()` so Python's
dynamic dispatch resolves them on the Main_Menu instance.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QToolButton, QComboBox, QScrollArea, QSplitter,
    QFrame, QSizePolicy,
    QCheckBox, QTableWidget, QTableWidgetItem,
    QHeaderView,
    QAbstractItemView,
)
from .theme import get_theme, get_theme_name

# Internal imports only — the Batch-2 re-export shim was removed in
# refactor B1 (2026-06-12); import page builders from their source
# modules (builders_base / builders_domain / builders_fluids /
# builders_canvas) directly.
from .builders_domain import build_page_domain
from .builders_fluids import build_page_fluids
from .builders_canvas import build_canvas_area


def build_ui(window):
    """Ex-Main_Menu._build_ui(self).
    Constructs the entire main window. Widgets are stored as attributes on
    `window` (e.g., `window.combo_tpms = QComboBox()`).
    """
    # Phase 5 follow-up: styles via FieldFactory + ThemeManager DI.
    from .field_factory import default_factory
    f = default_factory()
    t = f.theme
    _BG = t.style('BG')

    cw = window.centralWidget()
    cw.setStyleSheet(f"background:{_BG}; color:{get_theme()['fg']};")

    root = QVBoxLayout(cw)
    root.setContentsMargins(8, 6, 8, 6)
    root.setSpacing(6)

    _t = get_theme()
    _hdr_btn_qss = (
        f"QPushButton{{background:{_t['hdr_btn_bg']}; border:1px solid {_t['hdr_btn_border']};"
        f"border-radius:6px; color:{_t['hdr_btn_fg']}; font-weight:bold; font-size:10pt;}}"
        f"QPushButton:hover{{background:{_t['hdr_btn_hover']}; color:{_t['hdr_fg']};}}"
        f"QPushButton:focus{{border:2px solid {_t['inp_focus']};}}"
        f"QPushButton:disabled{{color:rgba(255,255,255,0.35);}}")

    # Header bar: navy blue background strip
    header_widget = QWidget()
    header_widget.setStyleSheet(
        f"background:{_t['hdr_bg']}; border-radius:6px;")
    header_widget.setFixedHeight(44)
    header_row = QHBoxLayout(header_widget)
    header_row.setContentsMargins(8, 4, 8, 4)
    header_row.setSpacing(8)
    # SJTU banner (横版校徽+校名) — left side of header
    import os as _os_hdr
    from PySide6.QtGui import QPixmap
    _banner_path = _os_hdr.path.join(
        _os_hdr.path.dirname(_os_hdr.path.dirname(_os_hdr.path.abspath(__file__))),
        'assets', 'logos',
        'sjtubannersilver.png' if get_theme_name() == 'dark' else 'sjtubannerred.png')
    banner_present = False
    if _os_hdr.path.exists(_banner_path):
        banner_lbl = QLabel()
        banner_lbl.setStyleSheet("background:transparent; border:none; padding:0;")
        banner_lbl.setToolTip("SJTU-TPMSHX · 上海交通大学")
        # HiDPI-aware scaling: request a pixmap at (logical height × dpr) and
        # tell the label the logical dpr so Qt draws crisply on 4K screens
        # instead of blurring a pre-scaled bitmap.
        _dpr = float(window.devicePixelRatioF() or 1.0)
        _logical_h = 30
        _px = QPixmap(_banner_path).scaledToHeight(
            int(_logical_h * _dpr),
            Qt.TransformationMode.SmoothTransformation)
        _px.setDevicePixelRatio(_dpr)
        banner_lbl.setPixmap(_px)
        banner_lbl.setFixedSize(
            int(_px.width() / _dpr), int(_px.height() / _dpr))
        header_row.addWidget(banner_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
        header_row.addSpacing(12)
        banner_present = True
    # Show the project-code title only when the banner image is missing — the
    # banner already renders "SJTU-TPMSHX · 上海交通大学" itself, so repeating
    # the name here wastes header space.
    if not banner_present:
        hdr = QLabel("SJTU-TPMSHX")
        hdr.setStyleSheet(
            f"background:transparent; color:{_t['hdr_fg']}; font-size:11pt;"
            "font-weight:bold; border:none; padding:0;")
        hdr.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        header_row.addWidget(hdr, 0)
    header_row.addStretch(1)

    # Theme toggle — icon reflects the theme you will switch TO, not the
    # current one (consistent with most desktop apps).
    btn_theme = QPushButton("☀" if get_theme_name() == 'dark' else "☾")
    btn_theme.setFixedSize(32, 32)
    btn_theme.setStyleSheet(_hdr_btn_qss)
    btn_theme.setToolTip(
        "Switch to light theme" if get_theme_name() == 'dark'
        else "Switch to dark theme")
    btn_theme.clicked.connect(window._toggle_theme)
    window.btn_theme = btn_theme
    header_row.addWidget(btn_theme, 0)
    header_row.addSpacing(6)

    # Help menu — About / Shortcuts / Quick tour. Pops a QMenu beneath the
    # button so users can discover shortcuts without hunting a menubar
    # (this app uses a custom header instead of QMainWindow.menuBar).
    btn_help = QPushButton("?")
    btn_help.setFixedSize(32, 32)
    btn_help.setStyleSheet(_hdr_btn_qss)
    btn_help.setToolTip(
        "Help — About, keyboard shortcuts, quick tour (Ctrl+?)")
    btn_help.clicked.connect(lambda: window._show_help_menu(btn_help))
    window.btn_help = btn_help
    header_row.addWidget(btn_help, 0)
    header_row.addSpacing(6)

    # 载入 ▾ menu — consolidates the canonical presets, user-saved presets,
    # and the last 5 run snapshots into one header entry (the separate preset
    # dropdown was removed in the 2026-06 declutter). QToolButton + InstantPopup
    # so the ▾ opens the menu on first click.
    btn_recent = QToolButton()
    btn_recent.setText("载入 ▾")
    btn_recent.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    btn_recent.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    btn_recent.setFixedHeight(32)
    btn_recent.setFixedWidth(84)
    # The "▾" is part of the text; kill the NATIVE menu-indicator too, or Qt
    # paints a second arrow bottom-right that overflows onto the next button.
    btn_recent.setStyleSheet(
        _hdr_btn_qss.replace("QPushButton", "QToolButton")
        + "QToolButton::menu-indicator{image:none;width:0;}")
    btn_recent.setToolTip(
        "载入标准工况 / 我的预设 / 最近运行,或保存当前为预设")
    window.btn_recent = btn_recent
    header_row.addWidget(btn_recent, 0)
    header_row.addSpacing(6)
    # Seed an empty menu so the first click behaves as "no recent runs"
    # rather than silently doing nothing because menu is None.
    window._rebuild_recent_menu()

    # Workspace selector — three independent session slots (A/B/C). Lets
    # users keep a comparative parameter set parked (e.g., "Shanghai air"
    # vs "Water-loop sweep") and flip between them without losing either.
    btn_ws = QToolButton()
    btn_ws.setText("WS: A ▾")
    btn_ws.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
    btn_ws.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    btn_ws.setFixedHeight(32)
    btn_ws.setFixedWidth(76)
    btn_ws.setStyleSheet(
        _hdr_btn_qss.replace("QPushButton", "QToolButton")
        + "QToolButton::menu-indicator{image:none;width:0;}")
    btn_ws.setToolTip("Switch between workspace A / B / C — each has its "
                      "own persisted parameter state")
    window.btn_workspace = btn_ws
    header_row.addWidget(btn_ws, 0)
    header_row.addSpacing(6)
    window._rebuild_workspace_menu()

    # Temperature unit toggle (K ↔ °C). Label shows the CURRENT unit so the
    # user knows what they're looking at; click flips display values.
    btn_temp_unit = QPushButton(
        "°C" if getattr(window, '_temp_unit', 'K') == 'C' else "K")
    btn_temp_unit.setFixedSize(36, 32)
    btn_temp_unit.setStyleSheet(_hdr_btn_qss)
    btn_temp_unit.setToolTip(
        "Temperatures currently in K. Click to switch K ↔ °C.")
    btn_temp_unit.clicked.connect(window._toggle_temp_unit)
    window.btn_temp_unit = btn_temp_unit
    header_row.addWidget(btn_temp_unit, 0)
    header_row.addSpacing(6)

    btn_reset = QPushButton("↺  重置参数")
    btn_reset.setFixedHeight(32)
    btn_reset.setFixedWidth(108)
    btn_reset.setStyleSheet(
        _hdr_btn_qss)
    btn_reset.setToolTip("重置全部参数为基准算例 (Ctrl+Shift+R)")
    btn_reset.clicked.connect(window._reset_defaults)
    header_row.addWidget(btn_reset, 0)
    header_row.addSpacing(6)
    # Quick-design tool — opens a standalone sizing dialog (Phase 2 Task 4).
    btn_qd = QPushButton("📐  快速设计")
    btn_qd.setFixedHeight(32)
    btn_qd.setMinimumWidth(110)
    btn_qd.setStyleSheet(_hdr_btn_qss)
    btn_qd.setToolTip("打开快速设计工具 — 自动选型并输出可行件清单")
    btn_qd.clicked.connect(window._open_quick_design)
    window.btn_quick_design = btn_qd
    header_row.addWidget(btn_qd, 0)
    header_row.addSpacing(6)
    # Compute moved to the left panel's sticky bottom bar (ui-batch2 IA-3):
    # the primary CTA now lives next to the parameters it acts on and never
    # scrolls away. See build_param_tabs.
    root.addWidget(header_widget, 0)

    # Keep a quiet divider with a usable mouse target.
    splitter = QSplitter(Qt.Orientation.Horizontal)
    _sep_col = _t.get('card_border', _t['splitter'])
    splitter.setHandleWidth(6)
    splitter.setStyleSheet(
        f"QSplitter::handle{{background:{_BG}; border-left:1px solid {_sep_col};}}"
        f"QSplitter::handle:hover{{background:{_t['splitter_hover']};}}")
    # Non-opaque resize: only recompute layout on mouse release. The rubber
    # band indicator drags at screen refresh rate, avoiding per-pixel child
    # re-layout which was causing noticeable drag lag on the 3D panel side.
    splitter.setOpaqueResize(False)
    splitter.setChildrenCollapsible(False)
    splitter.addWidget(build_param_tabs(window))
    splitter.addWidget(build_canvas_area(window))
    splitter.setStretchFactor(0, 35)
    splitter.setStretchFactor(1, 65)
    splitter.setSizes([400, 800])
    window._splitter = splitter
    root.addWidget(splitter, 1)


def _group_title_text(window, title):
    """Accordion group title: chevron + name + `⚠N` invalid-field badge.

    Single renderer for both the toggle handler and refresh_group_badges —
    a separate chevron-only path would wipe the badge on expand/collapse.
    """
    grp = window._accordion_groups.get(title)
    chev = "▾" if (grp is not None and grp.isChecked()) else "▸"
    n = getattr(window, '_group_badge_counts', {}).get(title, 0)
    return f"{chev}  {title}" + (f"     ⚠ {n}" if n else "")


def refresh_group_badges(window):
    """Recount invalid/empty session fields per accordion group and repaint
    group titles (ui-batch3 IA-4).

    Bad = same criterion as `_validate_inputs_preflight`: `inpError` set by
    the field validator, or empty text. Fields hidden by a 2D/3D or
    rect/poly mode gate are skipped via `isVisibleTo(content)` — that check
    ignores the ancestors' own visibility, so fields inside a COLLAPSED
    group still count (the badge's whole point) while gate-hidden ones
    don't.
    """
    contents = getattr(window, '_accordion_contents', None)
    if not contents:
        return
    counts = {}
    for title, content in contents.items():
        n = 0
        for name in getattr(window, '_SESSION_LINE_EDITS', ()):
            le = getattr(window, name, None)
            if le is None or not content.isAncestorOf(le):
                continue
            if not le.isVisibleTo(content):
                continue
            if le.property('inpError') == 'true' or not le.text().strip():
                n += 1
        counts[title] = n
    window._group_badge_counts = counts
    for title, grp in window._accordion_groups.items():
        txt = _group_title_text(window, title)
        if grp.title() != txt:
            grp.setTitle(txt)


def build_param_tabs(window):
    """Left-panel parameter groups — collapsible accordion layout."""
    # Phase 5 follow-up: styles via FieldFactory + ThemeManager DI.
    from .field_factory import default_factory
    f = default_factory()
    t = f.theme
    _BG = t.style('BG')

    # Canvas-tab styles: flat underline indicator instead of the older filled
    # pill. Active tab shows a 2px accent bar along the bottom edge; hover on
    # inactive tabs lightens the label without adding a second bar.
    _ts = get_theme()
    _accent = _ts['tab_on_bg']
    window._PTAB_ON  = (
        f"QPushButton{{color:{_accent};"
        "background:transparent; border:none;"
        f"border-bottom:2px solid {_accent};"
        "font-weight:bold; font-size:9pt; padding:6px 14px 4px 14px;}")
    window._PTAB_OFF = (
        f"QPushButton{{color:{_ts['tab_off_fg']};"
        "background:transparent; border:none;"
        "border-bottom:2px solid transparent;"
        "font-size:9pt; font-weight:500; padding:6px 14px 4px 14px;}"
        f"QPushButton:hover{{color:{_ts['fg']};"
        f"border-bottom:2px solid {_ts['tab_off_border']};}}"
        f"QPushButton:focus{{color:{_ts['fg']};"
        f"border-bottom:2px solid {_ts['inp_focus']};}}")
    # ★ fix #3 (2026-05-09) — disabled tabs explicitly drop bold + use a dimmer
    # foreground so the global QApplication Bold (Phase 3) doesn't make
    # disabled and enabled tabs visually identical.
    # 2026-06-03 — was hardcoded rgba(255,255,255,40): a faint *white* that
    # vanished on the light theme's near-white tab strip (disabled 2D/3D View
    # rendered invisible). Use the per-theme disabled token so it stays dim
    # yet legible on both palettes.
    window._PTAB_DISABLED = (
        f"QPushButton{{color:{_ts['tab_disabled_fg']};"
        "background:transparent; border:none;"
        "border-bottom:2px solid transparent;"
        "font-size:9pt; font-weight:normal; padding:6px 14px 4px 14px;}")

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    # ui-layout-fixes: the left panel must never scroll horizontally —
    # row labels word-wrap (FieldFactory.label) instead of widening cards.
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    # 8px track, semi-transparent handle — quieter than the old 10px slab but
    # still grabbable. Codex review 2026-04-22: "rgba(0.1)/0.2 on hover".
    scroll.setStyleSheet(
        f"QScrollArea{{background:{_BG}; border:none;}}"
        f"QScrollBar:vertical{{background:transparent; width:8px; border:none; margin:2px;}}"
        f"QScrollBar::handle:vertical{{background:{_ts['scroll_handle']};"
        f"border-radius:4px; min-height:30px;}}"
        f"QScrollBar::handle:vertical:hover{{background:{_ts['scroll_handle_hover']};}}"
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{{height:0;}}")
    scroll.setMinimumWidth(240)

    # Top-level accordion group: 12pt + 3px left accent bar, gray title strip
    _GRP_QSS = (
        "QGroupBox {"
        f"  font-size:12pt; font-weight:600; color:{_ts['fg']};"
        f"  background:transparent; border:none;"
        "  margin-top:12px; padding-top:38px;"
        "}"
        "QGroupBox::title {"
        f"  subcontrol-origin:margin; subcontrol-position:top left;"
        f"  left:0px; right:0px;"
        f"  background:{_ts['card_bg']}; color:{_ts['fg']};"
        f"  border-left:3px solid {_ts['group_accent']};"
        f"  border-bottom:1px solid {_ts['card_border']};"
        f"  border-top-left-radius:4px; border-top-right-radius:4px;"
        "  padding:10px 12px 10px 16px; min-height:20px; letter-spacing:0.3px;"
        "}"
        "QGroupBox::indicator {"
        "  width:0px; height:0px; margin:0px; padding:0px;"
        "  border:none; image:none;"
        "}"
        "QGroupBox::indicator:checked { image:none; }"
        "QGroupBox::indicator:unchecked { image:none; }"
    )

    # Build the pages for their WIDGET SIDE EFFECTS (every input widget +
    # the window._ia_sections registry); the page scroll shells themselves
    # are discarded — sections re-home into the four workflow groups below
    # (ui-ia-batch1), killing the old nested-scroll-area layout.
    # KEEP the shell references alive until after the re-homing addWidget
    # calls: dropping them immediately lets shiboken delete the C++ scroll
    # (no Qt parent) and its whole child tree — including the sections we
    # are about to re-parent.
    _shell_domain = build_page_domain(window)
    _shell_fluids = build_page_fluids(window)
    # Zone configuration now lives inside the Optimize tab (QSplitter on
    # the left side). The builder still runs here so the attached widgets
    # (zone_table, chk_zones, +Row/-Row, combo_zone_axis, etc.) exist on
    # the window before other builders reference them; `build_canvas_area`
    # then lifts the returned panel into the Optimize card.
    page_zone_layout = build_page_zones(window)
    window._zone_panel = page_zone_layout
    # Optimization UI now lives in its own top canvas tab (Plan D).

    from PySide6.QtWidgets import QGroupBox

    container = QWidget()
    container.setStyleSheet(f"background:{_BG};")
    vlay = QVBoxLayout(container)
    # Accordion: 8px outer padding + 12px gap between top-level groups.
    # Group's own margin-top:12px pushes total inter-group spacing to ~24px.
    vlay.setContentsMargins(6, 4, 6, 4)
    vlay.setSpacing(12)

    # Workflow-ordered groups (ui-ia-batch1): the two everyday groups open,
    # grid/solver + boundary-details collapsed (sane defaults cover the
    # standard full-face cross-flow case; flow-direction combos live in ④).
    sec = window._ia_sections
    _GROUPS = [
        ("几何与结构", True,
         ['domain_geometry', 'tpms_structure', 'tpms_computed']),
        ("流体", True,
         ['fluids_row', 'df_method', 'sco2_nu', 'preview_btn']),
        ("网格与求解器", False,
         ['grid_rect', 'mesh_poly', 'material']),
        ("边界细节与高级", False,
         ['pipe_a', 'pipe_b', 'poly_pipe_label', 'poly_pipe_frame',
          'advanced_flags']),
    ]

    window._accordion_groups = {}
    window._accordion_contents = {}
    for title, default_open, keys in _GROUPS:
        grp = QGroupBox()
        grp.setCheckable(True)
        grp.setChecked(default_open)
        grp.setStyleSheet(_GRP_QSS)
        grp_lay = QVBoxLayout(grp)
        grp_lay.setContentsMargins(6, 4, 8, 6)
        grp_lay.setSpacing(12)
        content = QWidget()
        content.setStyleSheet("background:transparent;")
        c_lay = QVBoxLayout(content)
        c_lay.setContentsMargins(0, 0, 0, 0)
        c_lay.setSpacing(12)
        for k in keys:
            w = sec.get(k)
            if w is not None:
                c_lay.addWidget(w)
        grp_lay.addWidget(content)
        content.setVisible(default_open)

        def _on_toggled(checked, p=content, t=title, g=grp):
            p.setVisible(checked)
            g.setTitle(_group_title_text(window, t))
            # Re-assert per-widget mode gates: QWidget.setVisible(True)
            # blanket-shows children, which would resurrect widgets a 2D/3D
            # or rect/poly gate had hidden (same rationale as the Advanced
            # collapsible's on_toggle in builders_domain).
            if checked:
                try:
                    from .builders_domain import _on_dim_changed as _dim_gate
                    _dim_gate(window)
                    window._on_shape_changed(
                        window.combo_shape.currentIndex())
                except Exception:
                    pass
            # Gate re-assertion may flip field visibility → recount badges.
            refresh_group_badges(window)
        grp.toggled.connect(_on_toggled)
        vlay.addWidget(grp)
        window._accordion_groups[title] = grp
        window._accordion_contents[title] = content
    # Initial titles + badge counts (empty-field only at this point —
    # validators attach later in Main_Menu.__init__ and re-trigger).
    refresh_group_badges(window)

    # Last-run results summary stays OUTSIDE the accordion — always visible
    # at the bottom regardless of which groups are collapsed.
    if sec.get('results') is not None:
        vlay.addWidget(sec['results'])

    # Every registered section is re-parented now — the empty page shells
    # can go (deleteLater: safe teardown after the event loop resumes).
    _shell_domain.deleteLater()
    _shell_fluids.deleteLater()

    vlay.addStretch(1)
    scroll.setWidget(container)

    window._param_stack = None
    window._param_btns = []

    # ── Sticky Compute CTA (ui-batch2 IA-3) ──────────────────────────
    # The ONE primary action, permanently visible at the bottom of the
    # parameter panel (moved from the header's far corner). Same widget
    # object the run_controller ticker owns — text/handler state machine
    # untouched.
    panel = QWidget()
    panel.setStyleSheet(f"background:{_BG};")
    p_lay = QVBoxLayout(panel)
    p_lay.setContentsMargins(0, 0, 0, 0)
    p_lay.setSpacing(0)
    p_lay.addWidget(scroll, 1)

    cta_bar = QWidget()
    cta_bar.setStyleSheet(
        f"background:{_ts.get('surface_raised', _ts['card_bg'])};"
        f"border-top:1px solid {_ts['card_border']};")
    cta_lay = QVBoxLayout(cta_bar)
    cta_lay.setContentsMargins(10, 8, 10, 8)
    # CJK mnemonics are useless — no '&'; Ctrl+R stays the shortcut.
    btn_run = QPushButton("▶  计算")
    btn_run.setMinimumHeight(40)
    btn_run.setStyleSheet(t.style('BTN_PRIMARY'))
    btn_run.setToolTip("运行单点计算 (Ctrl+R)")
    btn_run.clicked.connect(window.run_calculation)
    window.btn_compute = btn_run
    cta_lay.addWidget(btn_run)
    p_lay.addWidget(cta_bar, 0)
    window._cta_bar = cta_bar

    return panel


def build_page_zones(window):
    """Ex-Main_Menu._build_page_zones(self) -> QScrollArea.

    Note: post 2026-04-22 restructure this page hosts "Zone Layout" only
    (config + table + Preview) — it feeds the COMPUTE path's zone feature.
    The optimizer trigger + status live in the Optimize-tab wizard built in
    builders_canvas (M0 2026-07-09: this panel mounts there under its own
    "分区定义 (Compute 路径)" card, separate from the optimizer 搜索空间).
    """
    # Phase 5 follow-up: styles via FieldFactory + ThemeManager DI.
    from .field_factory import default_factory
    f = default_factory()
    t = f.theme
    _t = get_theme()

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    # ui-layout-fixes: no horizontal scroll on param pages (labels wrap).
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setStyleSheet("border:none; background:transparent;")

    w = QWidget(); w.setStyleSheet(f"background:{t.style('BG')};")
    lay = QVBoxLayout(w)
    lay.setSpacing(12); lay.setContentsMargins(6, 4, 8, 6)

    # ── Zone Configuration ── (title-less frame: panel lives inside the
    # Optimize tab card which is already labelled "Optimize", so repeating
    # "Zone Configuration" above the grid would be noise).
    sec_zone = QWidget()
    sec_zone.setStyleSheet("background:transparent;")
    _cz_lay = QVBoxLayout(sec_zone)
    _cz_lay.setContentsMargins(0, 4, 0, 0); _cz_lay.setSpacing(0)
    _cz_frame = QFrame()
    _cz_frame.setStyleSheet(t.style('F_NEUTRAL'))
    g_zone = QGridLayout(_cz_frame)
    g_zone.setContentsMargins(12, 10, 12, 10)
    g_zone.setVerticalSpacing(8); g_zone.setHorizontalSpacing(10)
    g_zone.setColumnStretch(0, 3); g_zone.setColumnStretch(1, 2)
    _cz_lay.addWidget(_cz_frame)
    lay.addWidget(sec_zone)
    window._rect_only_widgets.append(sec_zone)

    window.chk_zones = QCheckBox("Enable zone partitioning")
    _tcz = get_theme()
    # Explicit checkbox-indicator styling — without this, Qt falls back to
    # the native square which on Windows light is a white box with a thin
    # gray border that's nearly invisible on a white card_bg.
    window.chk_zones.setStyleSheet(
        f"QCheckBox{{color:{_tcz['fg']}; font-size:10pt; font-weight:bold;"
        f"background:transparent; spacing:8px;}}"
        f"QCheckBox::indicator{{width:16px; height:16px;"
        f"border:1.5px solid {_tcz['chk_indicator_border']};"
        f"border-radius:3px; background:{_tcz['chk_bg']};}}"
        f"QCheckBox::indicator:hover{{border-color:{_tcz['chk_hover_border']};}}"
        f"QCheckBox::indicator:checked{{background:{_tcz['chk_checked_bg']};"
        f"border-color:{_tcz['chk_checked_border']};}}"
        f"QCheckBox:focus{{outline:0;}}")
    window.chk_zones.setChecked(False)
    # Hide zone table + controls when unchecked (saves vertical space on small screens)
    def _toggle_zone_table(checked):
        for w_z in (window.zone_table, nz_row, window.combo_zone_axis):
            try:
                w_z.setVisible(checked)
            except Exception:
                pass
    window.chk_zones.toggled.connect(_toggle_zone_table)
    window.combo_zone_axis = QComboBox()
    window.combo_zone_axis.addItems(["Along Y", "Along X", "Grid Y×X"])
    window.combo_zone_axis.setFixedHeight(32)
    window.combo_zone_axis.setStyleSheet(t.style('INP'))
    window.combo_zone_axis.currentIndexChanged.connect(window._zone_mode_changed)
    g_zone.addWidget(window.chk_zones, 0, 0)
    g_zone.addWidget(window.combo_zone_axis, 0, 1)

    # Zone +/- buttons row
    nz_row = QWidget()
    nz_lay = QHBoxLayout(nz_row)
    nz_lay.setContentsMargins(0, 0, 0, 0); nz_lay.setSpacing(4)
    btn_add = QPushButton("+Row"); btn_rm = QPushButton("-Row")
    _btn_tert = t.style('BTN_TERTIARY')
    for b in (btn_add, btn_rm):
        b.setFixedHeight(32); b.setMinimumWidth(48)
        b.setStyleSheet(_btn_tert)
    btn_add.setToolTip("Add a row (split the last zone in half)")
    btn_rm.setToolTip("Remove the last row")
    btn_add.clicked.connect(window._zone_add_row)
    btn_rm.clicked.connect(window._zone_remove_row)
    window.lbl_nx = QLabel("Col:"); window.lbl_nx.setStyleSheet(t.style('LBL'))
    window.btn_add_x = QPushButton("+Col"); window.btn_rm_x = QPushButton("-Col")
    for b in (window.btn_add_x, window.btn_rm_x):
        b.setFixedHeight(32); b.setMinimumWidth(48)
        b.setStyleSheet(_btn_tert)
    window.btn_add_x.setToolTip("Add a column (split the last column in half)")
    window.btn_rm_x.setToolTip("Remove the last column")
    window.btn_add_x.clicked.connect(window._zone_add_col)
    window.btn_rm_x.clicked.connect(window._zone_remove_col)
    window.lbl_nx.hide(); window.btn_add_x.hide(); window.btn_rm_x.hide()
    nz_lay.addWidget(btn_add)
    nz_lay.addWidget(btn_rm)
    nz_lay.addStretch()
    nz_lay.addWidget(window.lbl_nx)
    nz_lay.addWidget(window.btn_add_x)
    nz_lay.addWidget(window.btn_rm_x)
    g_zone.addWidget(nz_row, 1, 0, 1, 2)
    window._grid_nx = 2  # track x-column count for grid mode

    window.zone_table = QTableWidget(3, 4)
    window.zone_table.setHorizontalHeaderLabels(
        ["START %", "END %", "L [mm]", "t [mm]"])
    window.zone_table.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.Stretch)
    window.zone_table.verticalHeader().setVisible(True)
    window.zone_table.verticalHeader().setDefaultSectionSize(34)
    window.zone_table.verticalHeader().setStyleSheet(
        f"QHeaderView::section{{background:{_t.get('surface_raised', _t['card_bg'])};"
        f"color:{_t.get('sub_fg', _t['fg'])};"
        f"font-family:'Fira Code','Consolas',monospace;"
        f"font-size:9pt; font-weight:700;"
        f"border:none; border-right:1px solid {_t.get('border_subtle', _t['card_border'])};"
        f"padding:0 6px;}}")
    window.zone_table.setSizePolicy(QSizePolicy.Policy.Expanding,
                                     QSizePolicy.Policy.Expanding)
    window.zone_table.setMinimumHeight(220)
    window.zone_table.setAlternatingRowColors(True)
    window.zone_table.setShowGrid(False)
    window.zone_table.horizontalHeader().setHighlightSections(False)
    window.zone_table.verticalHeader().setHighlightSections(False)
    # Per-zone colour palette for the row indicator swatch — rotated by
    # row index. Uses the shared `canvas_accents` list so the swatch
    # colour matches anything else keyed off zone index.
    _zone_swatches = _t.get('canvas_accents', [_t['accent_primary']] * 6)
    window._zone_swatches = list(_zone_swatches)
    window.zone_table.setStyleSheet(
        f"QTableWidget{{background:{_t['card_bg']}; color:{_t['fg']};"
        f"font-size:10pt; gridline-color:transparent;"
        f"alternate-background-color:{_t.get('surface_raised', _t['card_bg'])};"
        f"border:1px solid {_t.get('border_subtle', _t['card_border'])};"
        f"border-radius:6px;}}"
        f"QHeaderView::section{{background:transparent;"
        f"color:{_t.get('sub_fg', _t['fg'])}; font-size:9pt;"
        f"font-weight:700; letter-spacing:1.2px; padding:8px 6px;"
        f"border:none;"
        f"border-bottom:2px solid {_t.get('accent_primary', '#3B82F6')};}}"
        f"QTableWidget::item{{padding:6px 10px;"
        f"font-family:'Fira Code','Consolas',monospace;"
        f"border-right:1px solid {_t.get('border_subtle', _t['card_border'])};}}"
        f"QTableWidget::item:hover{{background:"
        f"{_t.get('btn_sec_hover_bg', 'rgba(59,130,246,0.12)')};}}"
        f"QTableWidget::item:selected{{background:"
        f"{_t.get('accent_primary', '#3B82F6')}; color:white;}}"
        f"QTableCornerButton::section{{background:{_t.get('surface_raised', _t['card_bg'])};"
        f"border:none;}}"
    )
    # Auto-select-on-edit delegate (Phase 5: moved out of main.py).
    from .delegates import SelectAllDelegate
    window.zone_table.setItemDelegate(SelectAllDelegate(window.zone_table))

    def _repaint_zone_swatches():
        """Prefix each row header with a coloured ● from the canvas_accents
        palette so zone rows have a stable visual identity that matches any
        per-zone markers in the layout preview."""
        from PySide6.QtGui import QBrush, QColor
        pal = window._zone_swatches
        n = window.zone_table.rowCount()
        for r in range(n):
            col = QColor(pal[r % len(pal)])
            item = QTableWidgetItem(f" ● #{r + 1} ")
            item.setForeground(QBrush(col))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            window.zone_table.setVerticalHeaderItem(r, item)
    window._repaint_zone_swatches = _repaint_zone_swatches

    # Keep swatches in sync whenever rows are added/removed. Qt emits
    # rowsInserted / rowsRemoved through the model; connect there.
    model = window.zone_table.model()
    model.rowsInserted.connect(lambda *a: _repaint_zone_swatches())
    model.rowsRemoved.connect(lambda *a: _repaint_zone_swatches())

    window._zone_init_1d(3)
    _repaint_zone_swatches()
    g_zone.addWidget(window.zone_table, 2, 0, 1, 2)

    # Initially hide zone table (checkbox unchecked)
    window.zone_table.setVisible(False)
    nz_row.setVisible(False)
    window.combo_zone_axis.setVisible(False)

    # Edit triggers: always allow editing (checkbox only controls whether zones are used in solver)
    window.zone_table.setEditTriggers(
        QAbstractItemView.EditTrigger.DoubleClicked |
        QAbstractItemView.EditTrigger.SelectedClicked |
        QAbstractItemView.EditTrigger.EditKeyPressed |
        QAbstractItemView.EditTrigger.AnyKeyPressed)

    # Cell-level validation: start/end percent in [0, 100]; L/t > 0. Writes
    # the `cellError` dynamic property which is styled red in the sheet
    # above. Lets the user spot a bad cell even when the solver hasn't run.
    def _zone_cell_validate(row, col):
        item = window.zone_table.item(row, col)
        if item is None:
            return
        txt = item.text().strip()
        # E16 — `=expr` cells evaluate via the safe expression parser
        # so users can type e.g. `=100/3` or `=0.4+0.1`.
        if txt.startswith('='):
            from .expr_eval import eval_expr as _ev
            val = _ev(txt[1:])
            if val is not None:
                window.zone_table.blockSignals(True)
                item.setText(f"{val:.6g}")
                window.zone_table.blockSignals(False)
                txt = item.text().strip()
        bad = False
        try:
            v = float(txt)
            if col in (0, 1):  # start%, end%
                if v < 0 or v > 100:
                    bad = True
            elif col in (2, 3):  # L [mm], t [mm]
                if v <= 0:
                    bad = True
        except Exception:
            bad = True
        new = 'true' if bad else 'false'
        if item.data(Qt.ItemDataRole.UserRole + 1) != new:
            item.setData(Qt.ItemDataRole.UserRole + 1, new)
        # setProperty isn't enough on QTableWidgetItem — use a visual marker
        # via background brush so the selector fires. Qt has no per-item
        # dynamic property driving QSS; approximate via background colour.
        if bad:
            from PySide6.QtGui import QBrush, QColor
            item.setBackground(QBrush(QColor(220, 38, 38, 70)))
            item.setToolTip(
                "Value out of range" if col in (0, 1)
                else "Value must be > 0")
        else:
            from PySide6.QtGui import QBrush
            item.setBackground(QBrush())
            item.setToolTip("")
    window.zone_table.cellChanged.connect(_zone_cell_validate)

    # Preview Layout trigger — auto-switches to the Layout tab after
    # drawing so the user actually sees the result (the canvas lives in
    # a different tab from this Zone panel, which is now embedded in
    # Optimize; clicking with no tab-switch felt like a broken button).
    btn_preview_z = QPushButton("预览布局  ↗")
    btn_preview_z.setFixedHeight(28)
    btn_preview_z.setStyleSheet(t.style('BTN_SECONDARY'))
    btn_preview_z.setToolTip(
        "Render the zone configuration on the Layout tab and jump to it")
    def _preview_and_switch():
        window._draw_layout()
        try:
            window._switch_tab('layout')
        except Exception:
            pass
    btn_preview_z.clicked.connect(_preview_and_switch)
    lay.addWidget(btn_preview_z)

    lay.addStretch()
    scroll.setWidget(w)
    return scroll

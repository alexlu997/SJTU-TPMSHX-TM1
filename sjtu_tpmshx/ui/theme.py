"""Theme system for SJTU-TPMSHX GUI — light and charcoal workbenches.

Design tokens follow an 8dp spacing rhythm.
Typography: modular scale 9 / 10 / 11 / 12 / 14 pt.
"""
from pathlib import Path

from sjtu_tpmshx.ui.typography import FONT_STACK

# ── Typography — modular scale (pt), smallest → largest ──────
# One coherent hierarchy. Section titles (FONT_SECTION) now sit one step
# above field labels (was equal at 10pt) so panel groups read as headings
# rather than just bold rows.
FONT_STATUS = 9      # status bar text
FONT_BTN = 10        # secondary / tertiary button text
FONT_LABEL = 10      # field labels
FONT_INPUT = 11      # input + value text
FONT_SECTION = 11    # second-level section titles (panel groups)
FONT_BTN_RUN = 12    # primary CTA (Compute)

# ── Spacing — 4dp rhythm, single source ─────────────────────
SPACE_XS = 4
SPACE_SM = 6
SPACE_MD = 10
SPACE_LG = 16

# ── Sizing ──────────────────────────────────────────────────

# Nested controls have tighter corners than their enclosing cards.
# Pills and micro-controls retain radii proportional to their dimensions.
RADIUS_INPUT = 8
RADIUS_BTN = 8
RADIUS_CARD = 12

# ── Theme colour definitions ────────────────────────────────
_THEMES = {
    'light': dict(
        # Light theme 4-tier elevation — subtler than dark since contrast
        # is driven by shadows rather than tonal lightening.
        surface_base="#eef1f5", surface_raised="#ffffff",
        surface_elevated="#f8fafc", surface_overlay="#ffffff",
        border_subtle="#dce2e9", border_strong="#bac5d2",
        bg="#eef1f5", fg="#243140", val="#1e609b", warn="#a35d11",
        card_bg="#ffffff", card_border="#dce2e9", card_shadow="rgba(0,0,0,18)",
        scroll_bg="#f8fafc",
        inp_bg="#ffffff", inp_fg="#111827", inp_border="#d1d5db",
        inp_focus="#2c5282",
        frame_border="rgba(0,0,0,0.05)", frame_neutral="255,255,255,60",
        frame_a="79,70,229,12", frame_b="13,148,136,12",
        t_neutral=("37,99,235","99,144,235"),
        t_a=("79,70,229","120,110,245"),
        t_b=("13,148,136","40,180,170"),
        btn_tpms=("68,114,196","100,150,220"),
        btn_run=("34,197,94","74,222,128"),
        combo_list_bg="#ffffff", combo_list_fg="#333333",
        combo_sel="rgba(68,114,196,100)", combo_border="rgba(0,0,0,20)",
        combo_arrow="80,80,80",
        combo_hover_border="rgba(68,114,196,180)",
        fig_bg="#ffffff", ax_bg="#ffffff",
        ax_text="#333333", ax_spine="#cccccc", zone_line="#666666",
        zone_fill="#4472c4", poly_fill="#e8e8e8",
        splitter="rgba(0,0,0,25)", splitter_hover="#2c5282",
        hdr_bg="#ffffff", hdr_fg="#243140",
        hdr_btn_bg="#f8fafc", hdr_btn_border="#dce2e9",
        hdr_btn_fg="#526174", hdr_btn_hover="#e8eef5",
        tab_on_bg="#2c5282", tab_on_fg="white", tab_on_border="#2c5282",
        tab_off_bg="transparent", tab_off_fg="#6b7280", tab_off_border="#d1d5db",
        tab_off_hover="#eef0f3",
        tab_disabled_fg="#c0c4cc", tab_disabled_border="#e5e7eb",
        prog_chunk="#4472c4",
        slider_groove="rgba(0,0,0,30)", slider_handle="rgba(0,0,0,120)",
        slider_sub="rgba(68,114,196,120)",
        scroll_handle="#9ca3af", scroll_handle_hover="#6b7280",
        accent_primary="#2c5282", accent_green="#548235", accent_orange="#c55a11",
        # Semantic state colors (ui-plan3a) — darker pair for the white ground.
        err="#B91C1C", err_soft="#B91C1C", search_hl="#B45309",
        # Section-title fg: forced near-black so titles stay legible on white
        # card_bg regardless of parent QGroupBox color cascades.
        title_fg="#020617",
        mpl_subtitle="#6b7280",
        sub_fg="#6b7280",              # secondary/caption gray (WCAG AA on white)
        val_empty_fg="#6b7280",
        dp_card_bg="#F0F2F5", dp_card_border="#D8DBE0",
        dp_color_a="#2e75b6", dp_color_b="#548235",
        inlet_color="#e8751a", outlet_color="#1e5a9e",
        pareto_accent="#cc4444",
        triad_x="#d13b3b", triad_y="#3bbd3b", triad_z="#3b68d1",
        wireframe="#3c4758", pane_edge="#e0e0e0", pane_grid="#cfd4d9",
        # 3D viewport background — pure white on light theme reads fine.
        vp_bg_3d="#ffffff",
        mono_family=FONT_STACK,
        sans_family=FONT_STACK,
        glass_top="#ffffff", glass_bottom="#f0f4f9",
        glass_edge_light="rgba(255,255,255,245)",
        glass_edge_shade="rgba(133,157,183,125)",
        chk_bg="#ffffff", chk_border="#aeb4ba", chk_hover_border="#2c5282",
        chk_hover_bg="#eef2f6", chk_checked_bg="#2c5282", chk_checked_border="#1e3a5f",
        chk_indicator_border="#606870",
        shadow_alpha=15, shadow_blur=8,
        # Chart series begin with the workbench's blue accent.
        canvas_accents=["#2c5282", "#0EA5E9", "#0D9488", "#7C3AED", "#D97706", "#64748B"],
        # 4-tier button semantics
        btn_primary_rgb="44,82,130",       # blue filled (Compute)
        btn_long_rgb="197,90,17",          # orange filled (NSGA-II)
        btn_sec_fg="#2C5282", btn_sec_border="#2C5282",
        btn_sec_hover_bg="rgba(44,82,130,25)",
        btn_tert_fg="#4B5563", btn_tert_border="#d1d5db",
        btn_tert_hover_bg="rgba(107,114,128,20)",
        # top-level accordion group left accent bar
        group_accent="#2C5282",
    ),
    'dark': dict(
        # 4-tier surface elevation (Linear pattern). Use these for new
        # components; the legacy `bg`/`card_bg`/`scroll_bg` tokens remain
        # as aliases so existing call sites keep working.
        #   surface_base:     app window background (deepest)
        #   surface_raised:   param panels, result cards
        #   surface_elevated: menus, popups, tooltips, command palette
        #   surface_overlay:  modal dialogs, highest layer
        surface_base="#181d25", surface_raised="#262e3a",
        surface_elevated="#303a48", surface_overlay="#3b4757",
        border_subtle="#465366", border_strong="#65788f",
        bg="#181d25", fg="#e8edf3", val="#85b9e9", warn="#f2bd64",
        card_bg="#262e3a", card_border="#465366",
        card_shadow="rgba(0,0,0,30)",
        scroll_bg="#1d242e",
        inp_bg="#1d2530", inp_fg="#e8edf3",
        inp_border="#526176",
        inp_focus="#3B82F6",
        frame_border="#465366", frame_neutral="38,46,58,180",
        frame_a="79,70,229,20", frame_b="13,148,136,20",
        t_neutral=("148,163,184","100,116,139"),
        t_a=("79,70,229","120,110,245"),
        t_b=("13,148,136","40,180,170"),
        btn_tpms=("59,130,246","96,165,250"),
        btn_run=("34,197,94","74,222,128"),
        combo_list_bg="#303a48", combo_list_fg="#e8edf3",
        combo_sel="rgba(59,130,246,120)", combo_border="#526176",
        combo_arrow="148,163,184",
        combo_hover_border="#3B82F6",
        fig_bg="#181d25", ax_bg="#181d25",
        ax_text="#d4dce6", ax_spine="#48515e", zone_line="#a5b1c1",
        zone_fill="#3B82F6", poly_fill="#323740",
        splitter="#465366", splitter_hover="#3B82F6",
        hdr_bg="#262e3a", hdr_fg="#e8edf3",
        hdr_btn_bg="#303a48", hdr_btn_border="#526176",
        hdr_btn_fg="#d4dce6", hdr_btn_hover="#424b58",
        tab_on_bg="#3B82F6", tab_on_fg="#FFFFFF", tab_on_border="#3B82F6",
        tab_off_bg="transparent", tab_off_fg="#94A3B8",
        tab_off_border="#475569",
        tab_off_hover="#323740",
        tab_disabled_fg="#7b8797", tab_disabled_border="#3b424d",
        prog_chunk="#3B82F6",
        slider_groove="#3b424d",
        slider_handle="#3B82F6",
        slider_sub="#1D4ED8",
        scroll_handle="#64748B", scroll_handle_hover="#94A3B8",
        accent_primary="#3B82F6", accent_green="#22C55E", accent_orange="#F97316",
        # Semantic state colors (ui-plan3a): error border + Ctrl+F highlight.
        # err_soft = readable light red for error TEXT on the dark ground
        # (residual diagnostics); err stays the border/badge red.
        err="#DC2626", err_soft="#F87171", search_hl="#F59E0B",
        # Section-title fg: near-white counterpart of the light theme's
        # forced near-black (see that token's comment).
        title_fg="#F8FAFC",
        mpl_subtitle="#94A3B8",
        sub_fg="#a5b1c1",
        val_empty_fg="#94a0b1",
        dp_card_bg="#323740", dp_card_border="#48515e",
        dp_color_a="#60A5FA", dp_color_b="#4ADE80",
        inlet_color="#F97316", outlet_color="#38BDF8",
        pareto_accent="#F87171",
        triad_x="#F87171", triad_y="#4ADE80", triad_z="#60A5FA",
        wireframe="#7b8797", pane_edge="#48515e", pane_grid="#3b424d",
        vp_bg_3d="#181d25",
        mono_family=FONT_STACK,
        sans_family=FONT_STACK,
        glass_top="#343c48", glass_bottom="#272d36",
        glass_edge_light="rgba(217,235,255,100)",
        glass_edge_shade="rgba(126,155,187,35)",
        chk_bg="#24282f", chk_border="#566171",
        chk_hover_border="#3B82F6", chk_hover_bg="#323740",
        chk_checked_bg="#3B82F6", chk_checked_border="#2563EB",
        chk_indicator_border="#64748B",
        shadow_alpha=80, shadow_blur=16,
        # Perceptually ordered series palette (blue→sky→emerald→violet→amber→
        # slate). Primary stays #3B82F6 so single-series plots are unchanged;
        # harsh orange softened to amber, neutral slate moved last.
        canvas_accents=["#3B82F6", "#38BDF8", "#34D399", "#A78BFA", "#FBBF24", "#94A3B8"],
        # 4-tier button semantics
        btn_primary_rgb="59,130,246",      # blue filled (Compute)
        btn_long_rgb="249,115,22",         # orange filled (NSGA-II)
        btn_sec_fg="#60A5FA", btn_sec_border="#3B82F6",
        btn_sec_hover_bg="rgba(59,130,246,30)",
        btn_tert_fg="#a5b1c1", btn_tert_border="#48515e",
        btn_tert_hover_bg="rgba(148,163,184,25)",
        # top-level accordion group left accent bar
        group_accent="#3B82F6",
    ),
}

# ── Active theme state ───────────────────────────────────────
_active_theme = 'dark'

# Display density — multiplier applied to input padding, label/value font
# size, and layout spacing inside `_build_styles`. Compact packs more
# fields on screen for parameter sweeps; Comfortable widens touch targets
# for presentation / demo machines.
_DENSITY_PROFILES = {
    'compact':     {'pad_scale': 0.55, 'font_bump': -1, 'row_scale': 0.80},
    'cozy':        {'pad_scale': 1.00, 'font_bump':  0, 'row_scale': 1.00},
    'comfortable': {'pad_scale': 1.40, 'font_bump':  1, 'row_scale': 1.20},
}
_active_density = 'cozy'


def get_theme():
    return _THEMES[_active_theme]


def get_theme_name():
    return _active_theme


def set_theme(name):
    global _active_theme
    if name not in _THEMES:
        raise ValueError(f"Unknown theme {name!r}, expected {list(_THEMES)}")
    _active_theme = name


def set_accent_override(hex_color):
    """Override `accent_primary` for both themes so user's preferred
    brand colour ripples through all components that read from the
    token. Pass None to reset to the built-in accents."""
    for t in _THEMES.values():
        if hex_color:
            t['accent_primary'] = hex_color
        # Reset is handled by re-importing module; don't bother tracking
        # original values here.


def get_density():
    return _active_density


def set_density(name):
    global _active_density
    if name not in _DENSITY_PROFILES:
        raise ValueError(
            f"Unknown density {name!r}, expected {list(_DENSITY_PROFILES)}")
    _active_density = name


def _density_profile():
    return _DENSITY_PROFILES[_active_density]


def glass_surface(t):
    """Static glass highlight for card chrome; no blur of scientific plots."""
    return (
        "background:qlineargradient(x1:0,y1:0,x2:0.4,y2:1,"
        f"stop:0 {t['glass_top']}, stop:1 {t['glass_bottom']});"
        "border:1px solid qlineargradient(x1:0,y1:0,x2:1,y2:1,"
        f"stop:0 {t['glass_edge_light']}, stop:0.5 {t['glass_edge_shade']},"
        f"stop:1 {t['glass_edge_light']});"
        f"border-radius:{RADIUS_CARD}px;"
    )


# ── Style builder ────────────────────────────────────────────

def _build_styles(theme_name=None):
    """Build all Qt stylesheet tokens for the given theme."""
    if theme_name is None:
        theme_name = _active_theme
    t = _THEMES[theme_name]
    dp = _density_profile()
    pad_scale = dp['pad_scale']
    font_bump = dp['font_bump']
    # Clamp font scaling so Compact doesn't render unreadable 8pt text.
    _fi = max(8, FONT_INPUT + font_bump)
    _fl = max(8, FONT_LABEL + font_bump)
    _fsec = max(9, FONT_SECTION + font_bump)   # section titles, one step up
    _fs = max(7, FONT_STATUS + font_bump)

    def _px(base):
        """Scale a base pixel value by the active density's pad_scale.
        Rounds up so tiny values don't collapse to zero under Compact."""
        return max(1, int(round(base * pad_scale)))

    s = {}
    s['BG'] = t['bg']
    s['LBL'] = (f"color:{t['fg']}; font-size:{_fl}pt; font-weight:400;"
                "border:none; background:transparent;")
    s['SUB'] = (f"color:{t['sub_fg']}; font-size:{_fs}pt; font-weight:400;"
                "border:none; background:transparent;")
    # res_row value label: two dynamic states via Qt property `valState`.
    # empty  → muted italic  |  filled → bold accent
    # Keep numeric controls in the same native sans-serif face as their labels.
    _MONO_STACK = t['mono_family']
    _pad_v = _px(5); _pad_h = _px(10)
    _focus_v = max(1, _pad_v - 1); _focus_h = max(1, _pad_h - 1)
    s['VAL'] = (
        f"QLabel{{color:{t['val']}; font-family:{_MONO_STACK};"
        f"font-size:{_fi}pt; font-weight:600;"
        "border:none; background:transparent;}"
        f"QLabel[valState=\"empty\"]{{color:{t['val_empty_fg']}; font-style:italic;"
        "font-weight:normal;}"
        f"QLabel[valState=\"filled\"]{{color:{t['val']}; font-weight:600;"
        " font-style:normal;}"
    )
    s['VAL_WARN'] = (f"color:{t['warn']}; font-family:{_MONO_STACK};"
                     f"font-size:{_fi}pt; font-weight:600;"
                     "border:none; background:transparent;")
    s['INP'] = (
        f"QLineEdit{{background:{t['inp_bg']}; color:{t['inp_fg']};"
        f"font-family:{_MONO_STACK};"
        f"border:1px solid {t['inp_border']}; border-radius:{RADIUS_INPUT}px;"
        f"font-size:{_fi}pt; font-weight:400;"
        f"padding:{_pad_v}px {_pad_h}px; min-width:60px;"
        f"selection-background-color:rgba(44,82,130,0.15);}}"
        f"QLineEdit:hover{{border:1px solid {t['combo_hover_border']};}}"
        f"QLineEdit:focus{{border:2px solid {t['inp_focus']}; padding:{_focus_v}px {_focus_h}px;}}"
        f"QLineEdit[inpError=\"true\"]{{border:2px solid {t['err']}; padding:{_focus_v}px {_focus_h}px;}}"
        f"QLineEdit[inpError=\"true\"]:focus{{border:2px solid {t['err']};}}"
        # Ctrl+F param-search highlight: amber outline for fields matching
        # the current query. Does not steal focus; outline reads over the
        # field's own border so searchable fields stay legible.
        f"QLineEdit[searchMatch=\"true\"]{{border:2px solid {t['search_hl']};"
        f"padding:{_focus_v}px {_focus_h}px;}}"
        f"QLineEdit:disabled{{color:{t['val_empty_fg']};"
        f"background:{t['scroll_bg']}; border-color:{t['card_border']};}}"
    )
    s['INP_FOCUS'] = f"border:2px solid {t['inp_focus']};"

    # Section-title text color — per-theme `title_fg` token (near-black on
    # light / near-white on dark) to guarantee legibility on card_bg
    # regardless of any parent QGroupBox stylesheet color inheritance.
    _title_fg = t['title_fg']

    def _title(rgb, _border=None):
        # One flat label above each input group; avoid nested title boxes.
        return (f"QLabel, QLabel#secTitle{{background:transparent; color:{_title_fg};"
                "border:none; border-radius:0;"
                f"border-bottom:1px solid rgba({rgb},100);"
                f"font-weight:600; font-size:{_fsec}pt; padding:6px 2px;"
                "qproperty-alignment: AlignLeft | AlignVCenter;}")

    def _frame(rgba):
        return (f"QFrame{{background:{t['card_bg']};"
                f"border:1px solid {t['card_border']};"
                f"border-radius:{RADIUS_CARD}px; padding:3px;}}")

    s['T_NEUTRAL'] = _title(*t['t_neutral'])
    s['T_A'] = _title(*t['t_a'])
    s['T_B'] = _title(*t['t_b'])
    s['F_NEUTRAL'] = _frame(t['frame_neutral'])
    s['F_A'] = _frame(t['frame_a'])
    s['F_B'] = _frame(t['frame_b'])

    _btn = (f"border-radius:{RADIUS_BTN}px; color:white; font-weight:600;"
            f"font-size:{FONT_BTN}pt; padding:{SPACE_XS}px {SPACE_MD}px;")

    # ── 4-tier button semantics (Primary/Secondary/Tertiary/Long-running) ──
    # `:focus` selector on every tier draws a thick accent ring when the user
    # lands on a button via Tab — a hard requirement for WCAG 2.4.7
    # Focus Visible. Qt's default focus rect is OS-dependent and often
    # invisible against our themed backgrounds.
    _focus_ring = t.get('inp_focus', '#3B82F6')

    # Primary: blue filled, big padding — main CTA (Compute)
    _rp = t['btn_primary_rgb']
    s['BTN_PRIMARY'] = (f"QPushButton{{border-radius:{RADIUS_CARD}px; color:white;"
                        f"font-weight:600; font-size:{FONT_BTN_RUN}pt; padding:{SPACE_SM}px {SPACE_LG}px;"
                        f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                        f"stop:0 rgba({_rp},230), stop:1 rgba({_rp},190));"
                        f"border:1px solid rgba({_rp},210);}}"
                        f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                        f"stop:0 rgba({_rp},250), stop:1 rgba({_rp},215));}}"
                        f"QPushButton:pressed{{background:rgba({_rp},255);}}"
                        f"QPushButton:focus{{border:2px solid #FFFFFF; padding:5px 15px;}}"
                        f"QPushButton:disabled{{background:rgba({_rp},80);"
                        f"color:rgba(255,255,255,0.4); border-color:rgba({_rp},110);}}")

    # Long-running: orange filled — NSGA-II / multi-minute tasks
    _rl = t['btn_long_rgb']
    s['BTN_LONG'] = (f"QPushButton{{{_btn}"
                     f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                     f"stop:0 rgba({_rl},220), stop:1 rgba({_rl},180));"
                     f"border:1px solid rgba({_rl},200);}}"
                     f"QPushButton:hover{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                     f"stop:0 rgba({_rl},245), stop:1 rgba({_rl},205));}}"
                     f"QPushButton:pressed{{background:rgba({_rl},255);}}"
                     f"QPushButton:focus{{border:2px solid #FFFFFF; padding:3px 9px;}}"
                     f"QPushButton:disabled{{background:rgba({_rl},80);"
                     f"color:rgba(255,255,255,0.4);}}")

    # Secondary: blue outlined — Preview, Export, Auto-fill, Compute-TPMS
    s['BTN_SECONDARY'] = (f"QPushButton{{border-radius:{RADIUS_BTN}px;"
                          f"color:{t['btn_sec_fg']}; font-weight:500;"
                          f"font-size:{FONT_BTN}pt; padding:{SPACE_XS}px {SPACE_MD}px;"
                          f"background:transparent; border:1px solid {t['btn_sec_border']};}}"
                          f"QPushButton:hover{{background:{t['btn_sec_hover_bg']};"
                          f"color:{t['btn_sec_fg']};}}"
                          f"QPushButton:pressed{{background:rgba(59,130,246,70);"
                          f"color:#FFFFFF;}}"
                          f"QPushButton:focus{{border:2px solid {_focus_ring}; padding:3px 9px;}}"
                          f"QPushButton:disabled{{color:rgba(148,163,184,0.45);"
                          f"border-color:rgba(148,163,184,0.25);}}")

    # Tertiary: gray outlined — Reset, +/-, zone row ops
    s['BTN_TERTIARY'] = (f"QPushButton{{border-radius:{RADIUS_BTN}px;"
                         f"color:{t['btn_tert_fg']}; font-weight:400;"
                         f"font-size:{FONT_BTN}pt; padding:{SPACE_XS}px {SPACE_MD}px;"
                         f"background:transparent; border:1px solid {t['btn_tert_border']};}}"
                         f"QPushButton:hover{{background:{t['btn_tert_hover_bg']};"
                         f"color:{t['fg']};}}"
                         f"QPushButton:pressed{{background:rgba(148,163,184,60);}}"
                         f"QPushButton:focus{{border:2px solid {_focus_ring}; color:{t['fg']}; padding:3px 9px;}}"
                         f"QPushButton:disabled{{color:rgba(148,163,184,0.35);"
                         f"border-color:rgba(148,163,184,0.15);}}")

    # Legacy aliases (preserve name-compat for any lingering callers)
    s['BTN_A']    = s['BTN_SECONDARY']
    s['BTN_B']    = s['BTN_SECONDARY']
    s['BTN_TPMS'] = s['BTN_SECONDARY']
    s['BTN_RUN']  = s['BTN_PRIMARY']

    # QToolButton split-button dressing — paints the dropdown arrow zone so
    # it reads as part of the Primary CTA rather than a raw Qt affordance.
    s['TOOLBTN_SPLIT'] = (
        "QToolButton::menu-button{"
        "  border-left:1px solid rgba(255,255,255,0.28);"
        "  width:18px; background:transparent;"
        f"  border-top-right-radius:{RADIUS_CARD}px; border-bottom-right-radius:{RADIUS_CARD}px;}}"
        "QToolButton::menu-arrow{"
        "  image:none;"
        "  border-left:4px solid transparent;"
        "  border-right:4px solid transparent;"
        "  border-top:5px solid white;"
        "  width:0; height:0;}"
        "QToolButton::menu-indicator{image:none;}"
        # Keyboard focus ring on the split button: 2px white border matches
        # the Primary-tier convention (BTN_PRIMARY does the same on :focus).
        "QToolButton:focus{border:2px solid #FFFFFF; padding:5px 15px;}"
    )

    # Explicit SVGs remain visible when macOS delegates the control to QSS.
    arrow = (Path(__file__).with_name('assets') / 'icons'
             / f'chevron-down-{theme_name}.svg').as_posix()
    s['SCROLLBAR'] = (
        f"QScrollBar:vertical{{background:{t['scroll_bg']}; width:10px; margin:2px; border:none;}}"
        f"QScrollBar::handle:vertical{{background:{t['scroll_handle']}; border:none;"
        "border-radius:3px; min-height:28px;}"
        f"QScrollBar::handle:vertical:hover{{background:{t['scroll_handle_hover']};}}"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{"
        "height:0; width:0; border:none; background:transparent;}"
        "QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical{"
        "image:none; width:0; height:0; border:none;}"
        "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical{"
        "background:transparent; border:none;}"
        f"QAbstractScrollArea::corner{{background:{t['scroll_bg']}; border:none;}}")
    s['COMBO'] = (
        f"QComboBox{{color:{t['inp_fg']}; background:{t['inp_bg']};"
        f"border:1px solid {t['inp_border']}; border-radius:{RADIUS_INPUT}px;"
        f"font-size:{_fi}pt; font-weight:400; padding:4px 28px 4px 8px;"
        "combobox-popup:0;}"
        f"QComboBox:hover{{border:1px solid {t['combo_hover_border']};}}"
        f"QComboBox:focus{{border:2px solid {t['inp_focus']}; padding:3px 27px 3px 7px;}}"
        # Editable value fields already exclude the arrow subcontrol. Extra
        # right padding would leave right-aligned text in the control's middle.
        "QComboBox:editable{padding:4px 1px 4px 8px;}"
        "QComboBox:editable:focus{padding:3px 0px 3px 7px;}"
        f"QComboBox::drop-down{{subcontrol-origin:border; subcontrol-position:top right;"
        "width:24px; margin:1px; border:none;"
        f"border-top-right-radius:{RADIUS_INPUT - 1}px; border-bottom-right-radius:{RADIUS_INPUT - 1}px;"
        "background:transparent;}"
        f'QComboBox::down-arrow{{image:url("{arrow}"); width:12px; height:12px;}}'
        # Disabled combo (e.g. the 2D-field selector before a result exists):
        # flatten to a quiet ghost — transparent fill + muted text + subtle
        # border — so it blends with the flat tab strip instead of reading as
        # a solid white box on the light theme.
        f"QComboBox:disabled{{color:{t['val_empty_fg']}; background:transparent;"
        f"border:1px solid {t['border_subtle']};}}"
        "QComboBox::drop-down:disabled{background:transparent;}"
        f"QComboBox QAbstractItemView{{"
        f"background:{t['combo_list_bg']}; color:{t['combo_list_fg']};"
        f"font-size:{_fi}pt; font-weight:400;"
        f"selection-background-color:{t['combo_sel']};"
        f"selection-color:{t['combo_list_fg']};"
        f"border:1px solid {t['combo_border']};"
        "border-radius:4px; padding:4px; outline:none;}"
        "QComboBox QAbstractItemView::item{min-height:26px; padding:3px 8px;}"
        + s['SCROLLBAR'])

    s['_THEMES'] = _THEMES
    return s


def apply_mpl_theme():
    """Set matplotlib rcParams to match active theme and favour fast
    redraws so hover + contour updates feel 144 Hz-smooth."""
    import matplotlib as mpl
    from sjtu_tpmshx.ui.typography import matplotlib_font_families
    t = get_theme()
    mpl.rcParams['figure.facecolor'] = t['fig_bg']
    mpl.rcParams['axes.facecolor'] = t['ax_bg']
    mpl.rcParams['text.color'] = t['ax_text']
    mpl.rcParams['axes.labelcolor'] = t['ax_text']
    mpl.rcParams['xtick.color'] = t['ax_text']
    mpl.rcParams['ytick.color'] = t['ax_text']
    mpl.rcParams['axes.edgecolor'] = t['ax_spine']
    mpl.rcParams['figure.edgecolor'] = t['fig_bg']
    # Performance — path simplification drops invisibly-close polyline
    # vertices before rasterising. Safe for scientific charts at screen
    # resolution; cuts contour redraw by ~30-50 % at > 1e5 vertices.
    mpl.rcParams['path.simplify'] = True
    mpl.rcParams['path.simplify_threshold'] = 1.0
    mpl.rcParams['agg.path.chunksize'] = 10000
    # Font fallback is per glyph: Latin/digits in Times, Chinese in YaHei.
    # DejaVu remains last for scientific symbols absent from both fonts.
    families = list(matplotlib_font_families())
    mpl.rcParams['font.family'] = families
    mpl.rcParams['font.sans-serif'] = families
    mpl.rcParams['font.serif'] = families
    mpl.rcParams['font.monospace'] = families
    mpl.rcParams['font.weight'] = 'normal'
    mpl.rcParams['axes.titleweight'] = 'normal'
    mpl.rcParams['figure.titleweight'] = 'normal'
    mpl.rcParams['axes.titlelocation'] = 'left'
    mpl.rcParams['axes.titlesize'] = 12
    mpl.rcParams['axes.labelweight'] = 'normal'
    mpl.rcParams['xtick.labelsize'] = 9
    mpl.rcParams['ytick.labelsize'] = 9
    mpl.rcParams['mathtext.fontset'] = 'custom'
    mpl.rcParams['mathtext.rm'] = families[0]
    mpl.rcParams['mathtext.it'] = f'{families[0]}:italic'
    mpl.rcParams['mathtext.bf'] = f'{families[0]}:bold'
    mpl.rcParams['mathtext.bfit'] = f'{families[0]}:italic:bold'
    mpl.rcParams['mathtext.sf'] = families[0]
    mpl.rcParams['mathtext.tt'] = families[0]
    mpl.rcParams['mathtext.cal'] = families[0]
    mpl.rcParams['mathtext.default'] = 'it'
    mpl.rcParams['mathtext.fallback'] = 'stix'
    mpl.rcParams['legend.frameon'] = True
    mpl.rcParams['legend.framealpha'] = 0.9


def _btn_styles() -> dict:
    """Resolve button stylesheets from the *current* theme at call time, so a
    dialog respects a live ``ThemeManager.rebuild()`` instead of the stale
    module-global ``_BTN_*`` snapshot the original main.py read once at import."""
    try:
        s = _build_styles()
        return {"tertiary": s.get("BTN_TERTIARY", ""),
                "secondary": s.get("BTN_SECONDARY", "")}
    except Exception:
        return {"tertiary": "", "secondary": ""}

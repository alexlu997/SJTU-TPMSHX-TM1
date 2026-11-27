"""Style P2 OKLCH theme system and per-quantity colormaps for the TM1 GUI."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from sjtu_tpmshx.applications.gui.ui.typography import FONT_STACK
from sjtu_tpmshx.postprocess.result_display import (
    COLORMAP_CHOICES,
    COLORMAP_QUANTITIES,
    DEFAULT_COLORMAPS,
    field_spec,
)

# Runtime per-quantity colormap overrides; unset quantities use DEFAULT_COLORMAPS.
_cmap_overrides: dict[str, str] = {}


def _colormap_quantity(key_or_quantity: str) -> str:
    if key_or_quantity in COLORMAP_QUANTITIES:
        return key_or_quantity
    return field_spec(key_or_quantity).quantity


def resolve_cmap(key_or_quantity: str) -> str:
    """Resolve the active colormap name for a field key or quantity at draw time."""
    quantity = _colormap_quantity(key_or_quantity)
    return _cmap_overrides.get(quantity, DEFAULT_COLORMAPS[quantity])


def get_colormap_overrides() -> dict[str, str]:
    """Return active per-quantity colormap overrides."""
    return dict(_cmap_overrides)


def set_cmap(quantity: str, cmap: str | None, *, persist: bool = False) -> bool:
    """Set or reset the colormap for one quantity family.

    When ``persist`` is True, write the setting before updating live state and
    return False without changing the active colormap if storage fails.
    """
    if quantity not in COLORMAP_QUANTITIES:
        raise ValueError(
            f"Unknown colormap quantity {quantity!r}, expected {COLORMAP_QUANTITIES}"
        )
    if cmap is None:
        resolved = DEFAULT_COLORMAPS[quantity]
    else:
        if cmap not in COLORMAP_CHOICES:
            raise ValueError(
                f"Unknown colormap {cmap!r}, expected {COLORMAP_CHOICES}"
            )
        resolved = cmap
    if persist:
        from sjtu_tpmshx.applications.gui.controllers.user_storage import (
            save_appearance_setting,
        )
        if not save_appearance_setting(f"cmap_{quantity}", resolved):
            return False
    if resolved == DEFAULT_COLORMAPS[quantity]:
        _cmap_overrides.pop(quantity, None)
    else:
        _cmap_overrides[quantity] = resolved
    return True


def apply_saved_colormaps(saved: dict[str, str]) -> None:
    """Apply validated per-quantity colormap preferences from appearance storage."""
    for quantity in COLORMAP_QUANTITIES:
        value = saved.get(f"cmap_{quantity}")
        if value in COLORMAP_CHOICES:
            set_cmap(quantity, value)


# ── Typography & spacing constants ─────────────────────────────────────────
FONT_STATUS = 9
FONT_BTN = 10
FONT_LABEL = 10
FONT_INPUT = 11
FONT_SECTION = 11
FONT_BTN_RUN = 11

SPACE_XS = 4
SPACE_SM = 6
SPACE_MD = 10
SPACE_LG = 16

RADIUS_INPUT = 6
RADIUS_BTN = 7
RADIUS_CARD = 12


# ── Style P2 OKLCH surface & contrast palette ──────────────────────────────
def oklch_to_hex(L: float, C: float, H_deg: float) -> str:
    """Convert an OKLCH color triple to an uppercase sRGB hex string."""
    h = math.radians(H_deg)
    a = C * math.cos(h)
    b = C * math.sin(h)
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    r = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    b_ = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s

    def _enc(u: float) -> float:
        u = max(0.0, min(1.0, u))
        return 12.92 * u if u <= 0.0031308 else 1.055 * (u ** (1.0 / 2.4)) - 0.055

    return "#{:02x}{:02x}{:02x}".format(
        *(int(round(_enc(x) * 255)) for x in (r, g, b_))
    )


OKLCH_SPEC: dict[str, dict[str, tuple[float, float, float]]] = {
    "light": {
        "window":          (0.924, 0.006, 90),
        "sunken":          (0.948, 0.005, 90),
        "canvas":          (0.975, 0.004, 90),
        "panel":           (0.989, 0.003, 90),
        "popover":         (1.000, 0.000, 0),
        "hover":           (0.912, 0.006, 90),
        "seg_on":          (1.000, 0.000, 0),
        "border":          (0.882, 0.006, 90),
        "border_strong":   (0.806, 0.008, 90),
        "inp_border":      (0.595, 0.008, 90),
        "label_primary":   (0.205, 0.004, 90),
        "label_secondary": (0.395, 0.006, 90),
        "label_tertiary":  (0.512, 0.006, 90),
    },
    "dark": {
        "window":          (0.146, 0.005, 258),
        "sunken":          (0.171, 0.006, 258),
        "canvas":          (0.198, 0.006, 258),
        "panel":           (0.226, 0.007, 258),
        "popover":         (0.258, 0.008, 258),
        "hover":           (0.246, 0.008, 258),
        "seg_on":          (0.292, 0.009, 258),
        "border":          (0.282, 0.008, 258),
        "border_strong":   (0.362, 0.010, 258),
        "inp_border":      (0.562, 0.011, 258),
        "label_primary":   (0.945, 0.004, 90),
        "label_secondary": (0.778, 0.006, 258),
        "label_tertiary":  (0.648, 0.007, 258),
    },
}


def _build_p2_theme(mode: str, extras: dict[str, Any]) -> dict[str, Any]:
    d: dict[str, Any] = {k: oklch_to_hex(*v) for k, v in OKLCH_SPEC[mode].items()}
    d["sheet"] = d["canvas"]
    d["drawer"] = d["panel"]
    d["island"] = d["popover"]
    d["fg"] = d["label_primary"]
    d["sub"] = d["label_secondary"]
    d["tert"] = d["label_tertiary"]
    d["muted"] = d["label_tertiary"]
    d["placeholder"] = d["label_tertiary"]
    d["row_hover"] = d["hover"] if mode == "light" else d["seg_on"]
    d.update(extras)

    # Map existing widget and panel keys onto the Style P2 tokens.
    d.update(
        surface_base=d["window"],
        surface_raised=d["panel"],
        surface_elevated=d["popover"],
        surface_overlay=d["popover"],
        border_subtle=d["border"],
        bg=d["window"],
        val=d["accent_fg"],
        card_bg=d["panel"],
        card_border=d["border"],
        scroll_bg=d["sunken"],
        inp_bg=d["popover"],
        inp_fg=d["fg"],
        inp_focus=d["accent"],
        combo_list_bg=d["popover"],
        combo_list_fg=d["fg"],
        combo_sel=d["accent_soft"],
        combo_border=d["border_strong"],
        combo_hover_border=d["accent"],
        fig_bg=d["canvas"],
        ax_bg=d["canvas"],
        ax_text=d["fg"],
        ax_spine=d["border_strong"],
        zone_line=d["sub"],
        zone_fill=d["accent"],
        splitter=d["border"],
        splitter_hover=d["accent"],
        tab_on_bg=d["accent_fg"],
        tab_on_fg=d["on_accent"],
        tab_off_fg=d["sub"],
        tab_off_border=d["border"],
        tab_off_hover=d["hover"],
        tab_disabled_fg=d["tert"],
        prog_chunk=d["accent"],
        scroll_handle=d["border_strong"],
        scroll_handle_hover=d["inp_border"],
        accent_primary=d["accent"],
        accent_green=d["ok"],
        accent_orange=d["data_b"],
        search_hl=d["warn"],
        title_fg=d["fg"],
        mpl_subtitle=d["sub"],
        sub_fg=d["sub"],
        val_empty_fg=d["tert"],
        inlet_color=d["inlet_a"],
        outlet_color=d["inlet_b"],
        wireframe=d["sub"],
        pane_edge=d["border"],
        pane_grid=d["border"],
        vp_bg_3d=d["canvas"],
        mono_family=FONT_STACK,
        sans_family=FONT_STACK,
        glass_top=d["panel"],
        glass_bottom=d["panel"],
        glass_edge_light=d["border"],
        glass_edge_shade=d["border"],
        chk_bg=d["popover"],
        chk_border=d["inp_border"],
        chk_hover_border=d["accent"],
        chk_hover_bg=d["hover"],
        chk_checked_bg=d["accent"],
        chk_checked_border=d["accent"],
        chk_indicator_border=d["inp_border"],
        btn_sec_fg=d["fg"],
        btn_sec_border=d["border_strong"],
        btn_sec_hover_bg=d["hover"],
        btn_tert_fg=d["sub"],
        btn_tert_border=d["border"],
        btn_tert_hover_bg=d["hover"],
        switch_thumb="#FFFFFF",
    )
    return d


_THEMES: dict[str, dict[str, Any]] = {
    "light": _build_p2_theme(
        "light",
        dict(
            primary_bg="#1B1B19",
            primary_fg="#FAF9F6",
            primary_hover="#2B2B28",
            accent="#0E6275",
            accent_fg="#0B5161",
            accent_soft="#E5F0F2",
            on_accent="#FFFFFF",
            ok="#176B3E",
            warn="#96530C",
            err="#B43025",
            ok_soft="#E7F2EB",
            warn_soft="#F6EEE2",
            err_soft="#F7E9E7",
            data_a="#0E6275",
            data_b="#B65419",
            inlet_a="#C85A17",
            inlet_b="#1B5E9E",
            triad_x="#C23B3B",
            triad_y="#2E8F43",
            triad_z="#2B62B8",
            t_neutral="14,98,117",
            t_a="14,98,117",
            t_b="182,84,25",
            btn_primary_rgb="27,27,25",
            btn_long_rgb="182,84,25",
            canvas_accents=["#0E6275", "#B65419", "#176B3E", "#6E56CF", "#96530C", "#686663"],
            shadow_ambient=(20, 19, 16, 15),
            shadow_key=(20, 19, 16, 24),
            shadow_drawer_ambient=(20, 19, 16, 22),
            shadow_drawer_key=(20, 19, 16, 34),
            scrim=(18, 18, 16, 40),
        ),
    ),
    "dark": _build_p2_theme(
        "dark",
        dict(
            primary_bg="#ECECE7",
            primary_fg="#141618",
            primary_hover="#FFFFFF",
            accent="#3DA8BD",
            accent_fg="#75D2E3",
            accent_soft="#152A30",
            on_accent="#0D1518",
            ok="#4CC385",
            warn="#E2A449",
            err="#EF7A72",
            ok_soft="#13261C",
            warn_soft="#2A2115",
            err_soft="#301B1B",
            data_a="#52C1D6",
            data_b="#E39256",
            inlet_a="#F08C42",
            inlet_b="#4BA8F0",
            triad_x="#F07474",
            triad_y="#56C870",
            triad_z="#6AA6F8",
            t_neutral="61,168,189",
            t_a="82,193,214",
            t_b="227,146,86",
            btn_primary_rgb="236,236,231",
            btn_long_rgb="227,146,86",
            canvas_accents=["#52C1D6", "#E39256", "#4CC385", "#A78BFA", "#E2A449", "#8C8F93"],
            shadow_ambient=(0, 0, 0, 88),
            shadow_key=(0, 0, 0, 130),
            shadow_drawer_ambient=(0, 0, 0, 118),
            shadow_drawer_key=(0, 0, 0, 168),
            scrim=(0, 0, 0, 72),
        ),
    ),
}

# ── Active theme & density state ───────────────────────────────────────────
_active_theme = "light"

_DENSITY_PROFILES = {
    "compact":     {"pad_scale": 0.55, "font_bump": -1},
    "cozy":        {"pad_scale": 1.00, "font_bump":  0},
    "comfortable": {"pad_scale": 1.40, "font_bump":  1},
}
_active_density = "cozy"


def get_theme() -> dict[str, Any]:
    return _THEMES[_active_theme]


def get_theme_name() -> str:
    return _active_theme


def set_theme(name: str) -> None:
    global _active_theme
    if name not in _THEMES:
        raise ValueError(f"Unknown theme {name!r}, expected {list(_THEMES)}")
    _active_theme = name


def set_accent_override(hex_color: str | None) -> None:
    """Set a custom accent color for both themes in this process."""
    if not hex_color:
        return
    for t in _THEMES.values():
        t["accent"] = hex_color
        t["accent_primary"] = hex_color
        t["inp_focus"] = hex_color
        t["chk_checked_bg"] = hex_color
        t["chk_checked_border"] = hex_color
        t["prog_chunk"] = hex_color


def get_density() -> str:
    return _active_density


def set_density(name: str) -> None:
    global _active_density
    if name not in _DENSITY_PROFILES:
        raise ValueError(
            f"Unknown density {name!r}, expected {list(_DENSITY_PROFILES)}"
        )
    _active_density = name


def _density_profile() -> dict[str, float]:
    return _DENSITY_PROFILES[_active_density]


def glass_surface(t: dict[str, Any]) -> str:
    """Neutral Style P2 surface card with crisp border."""
    return (
        f"background:{t['panel']};"
        f"border:1px solid {t['border']};"
        f"border-radius:{RADIUS_CARD}px;"
    )


# ── Style builder ──────────────────────────────────────────────────────────
def _build_styles(theme_name: str | None = None) -> dict[str, str]:
    """Build Qt stylesheet tokens for the active Style P2 theme."""
    if theme_name is None:
        theme_name = _active_theme
    t = _THEMES[theme_name]
    dp = _density_profile()
    pad_scale = dp["pad_scale"]
    font_bump = int(dp["font_bump"])
    _fi = max(9, 13 + font_bump)
    _fl = max(9, 12 + font_bump)
    _fsec = max(9, 12 + font_bump)
    _fs = max(8, 11 + font_bump)

    def _px(base: int) -> int:
        return max(1, int(round(base * pad_scale)))

    s: dict[str, str] = {}
    s["BG"] = t["window"]
    s["LBL"] = (
        f"color:{t['sub']}; font-size:{_fl}px; font-weight:400;"
        "border:none; background:transparent;"
    )
    s["SUB"] = (
        f"color:{t['tert']}; font-size:{_fs}px; font-weight:400;"
        "border:none; background:transparent;"
    )
    _mono = t["mono_family"]
    _pad_v = _px(3)
    _pad_h = _px(8)
    _focus_v = max(1, _pad_v - 1)
    _focus_h = max(1, _pad_h - 1)
    s["VAL"] = (
        f"QLabel{{color:{t['fg']}; font-family:{_mono};"
        f"font-size:{_fi}px; font-weight:500;"
        "border:none; background:transparent;}"
        f"QLabel[valState=\"empty\"]{{color:{t['tert']}; font-weight:400;}}"
        f"QLabel[valState=\"filled\"]{{color:{t['fg']}; font-weight:500;}}"
    )
    s["VAL_WARN"] = (
        f"color:{t['warn']}; font-family:{_mono};"
        f"font-size:{_fi}px; font-weight:600;"
        "border:none; background:transparent;"
    )
    s["INP"] = (
        f"QLineEdit{{background:{t['popover']}; color:{t['fg']};"
        f"font-family:{_mono};"
        f"border:1px solid {t['inp_border']}; border-radius:{RADIUS_INPUT}px;"
        f"font-size:{_fi}px; font-weight:400;"
        f"min-height:24px; padding:{_pad_v}px {_pad_h}px; min-width:56px;"
        f"selection-background-color:{t['accent_soft']}; selection-color:{t['fg']};}}"
        f"QLineEdit:hover{{border:1px solid {t['accent']};}}"
        f"QLineEdit:focus{{border:2px solid {t['accent']}; padding:{_focus_v}px {_focus_h}px;}}"
        f"QLineEdit[inpError=\"true\"]{{border:2px solid {t['err']}; padding:{_focus_v}px {_focus_h}px;}}"
        f"QLineEdit[inpError=\"true\"]:focus{{border:2px solid {t['err']};}}"
        f"QLineEdit[searchMatch=\"true\"]{{border:2px solid {t['warn']};"
        f"padding:{_focus_v}px {_focus_h}px;}}"
        f"QLineEdit:disabled{{color:{t['tert']};"
        f"background:{t['sunken']}; border-color:{t['border']};}}"
    )

    def _title() -> str:
        return (
            f"QLabel, QLabel#secTitle{{background:{t['sunken']}; color:{t['sub']};"
            f"border:none; border-top:1px solid {t['border']}; border-bottom:1px solid {t['border']};"
            f"font-weight:600; font-size:{_fsec}px; padding:6px 14px;"
            "qproperty-alignment: AlignLeft | AlignVCenter;}"
        )

    frame = (
        "QFrame{background:transparent; border:none; border-radius:0px; padding:0px;}"
    )

    s["T_NEUTRAL"] = _title()
    s["T_A"] = _title()
    s["T_B"] = _title()
    s["F_NEUTRAL"] = frame
    s["F_A"] = frame
    s["F_B"] = frame

    _focus_ring = t["accent"]
    s["BTN_PRIMARY"] = (
        f"QPushButton{{border-radius:{RADIUS_BTN}px; color:{t['primary_fg']};"
        f"font-weight:600; font-size:13px; padding:0 14px; min-height:30px;"
        f"background:{t['primary_bg']}; border:none;}}"
        f"QPushButton:hover{{background:{t['primary_hover']};}}"
        f"QPushButton:pressed{{background:{t['primary_bg']};}}"
        f"QPushButton:focus{{border:2px solid {_focus_ring}; padding:0 12px;}}"
        f"QPushButton:disabled{{background:{t['sunken']}; color:{t['tert']};"
        f"border:1px solid {t['border']};}}"
    )

    s["BTN_LONG"] = s["BTN_PRIMARY"]

    s["BTN_SECONDARY"] = (
        f"QPushButton{{border-radius:{RADIUS_BTN}px;"
        f"color:{t['fg']}; font-weight:500; font-size:13px;"
        f"padding:0 12px; min-height:30px;"
        f"background:{t['panel']}; border:1px solid {t['border']};}}"
        f"QPushButton:hover{{background:{t['hover']}; border-color:{t['border_strong']};}}"
        f"QPushButton:pressed{{background:{t['sunken']};}}"
        f"QPushButton:focus{{border:2px solid {_focus_ring}; padding:0 11px;}}"
        f"QPushButton:disabled{{color:{t['tert']}; background:{t['sunken']};"
        f"border-color:{t['border']};}}"
    )

    s["BTN_TERTIARY"] = (
        f"QPushButton{{border-radius:{RADIUS_INPUT}px;"
        f"color:{t['fg']}; font-weight:400; font-size:12px;"
        f"padding:0 10px; min-height:26px;"
        f"background:{t['panel']}; border:1px solid {t['border_strong']};}}"
        f"QPushButton:hover{{background:{t['hover']};}}"
        f"QPushButton:pressed{{background:{t['sunken']};}}"
        f"QPushButton:focus{{border:2px solid {_focus_ring}; padding:0 9px;}}"
        f"QPushButton:disabled{{color:{t['tert']}; border-color:{t['border']};"
        f"background:transparent;}}"
    )

    s["BTN_GHOST"] = (
        f"QPushButton{{border-radius:{RADIUS_INPUT}px;"
        f"color:{t['sub']}; font-weight:400; font-size:12px;"
        f"padding:0 8px; min-height:24px;"
        "background:transparent; border:none;}"
        f"QPushButton:hover{{background:{t['hover']}; color:{t['fg']};}}"
        f"QPushButton:checked{{background:{t['sunken']}; border:1px solid {t['border']};"
        f"color:{t['fg']}; font-weight:600;}}"
        f"QPushButton:disabled{{color:{t['tert']};}}"
    )

    s["BTN_ACTION"] = (
        f"QPushButton{{background:transparent; border:none; color:{t['accent_fg']};"
        "min-height:20px; max-height:20px; padding:0 4px;"
        "font-size:12px; font-weight:500; border-radius:5px;}"
        f"QPushButton:hover{{background:{t['hover']};}}"
        f"QPushButton:disabled{{color:{t['tert']};}}"
    )

    arrow = (
        Path(__file__).with_name("assets") / "icons" / f"chevron-down-{theme_name}.svg"
    ).as_posix()
    s["SCROLLBAR"] = (
        "QScrollBar:vertical{background:transparent; width:5px; margin:4px 1px; border:none;}"
        f"QScrollBar::handle:vertical{{background:{t['border_strong']}; border:none;"
        "border-radius:2px; min-height:36px;}"
        f"QScrollBar::handle:vertical:hover{{background:{t['inp_border']};}}"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{"
        "height:0; width:0; border:none; background:transparent;}"
        "QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical{"
        "image:none; width:0; height:0; border:none;}"
        "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical{"
        "background:transparent; border:none;}"
        "QAbstractScrollArea::corner{background:transparent; border:none;}"
    )
    s["COMBO"] = (
        f"QComboBox{{color:{t['fg']}; background:{t['popover']};"
        f"border:1px solid {t['inp_border']}; border-radius:{RADIUS_INPUT}px;"
        f"font-size:{_fi}px; font-weight:400; min-height:24px; padding:2px 24px 2px 8px;"
        "combobox-popup:0;}"
        f"QComboBox:hover{{border:1px solid {t['accent']};}}"
        f"QComboBox:focus{{border:2px solid {t['accent']}; padding:1px 23px 1px 7px;}}"
        "QComboBox:editable{padding:2px 1px 2px 8px;}"
        "QComboBox:editable:focus{padding:1px 0px 1px 7px;}"
        "QComboBox::drop-down{subcontrol-origin:border; subcontrol-position:top right;"
        "width:22px; margin:1px; border:none; background:transparent;}"
        f'QComboBox::down-arrow{{image:url("{arrow}"); width:11px; height:11px;}}'
        f"QComboBox:disabled{{color:{t['tert']}; background:{t['sunken']};"
        f"border:1px solid {t['border']};}}"
        "QComboBox::drop-down:disabled{background:transparent;}"
        f"QComboBox QAbstractItemView{{"
        f"background:{t['popover']}; color:{t['fg']};"
        f"font-size:{_fi}px; font-weight:400;"
        f"selection-background-color:{t['accent_soft']};"
        f"selection-color:{t['fg']};"
        f"border:1px solid {t['border_strong']};"
        "border-radius:6px; padding:4px; outline:none;}"
        "QComboBox QAbstractItemView::item{min-height:26px; padding:3px 8px;}"
        + s["SCROLLBAR"]
    )
    return s


def apply_mpl_theme() -> None:
    """Set Matplotlib colors and sans UI fonts for the active Style P2 theme."""
    import matplotlib as mpl
    from sjtu_tpmshx.applications.gui.ui.typography import screen_matplotlib_font_families

    t = get_theme()
    mpl.rcParams["figure.facecolor"] = t["fig_bg"]
    mpl.rcParams["axes.facecolor"] = t["ax_bg"]
    mpl.rcParams["text.color"] = t["fg"]
    mpl.rcParams["axes.labelcolor"] = t["sub"]
    mpl.rcParams["xtick.color"] = t["tert"]
    mpl.rcParams["ytick.color"] = t["tert"]
    mpl.rcParams["axes.edgecolor"] = t["border_strong"]
    mpl.rcParams["figure.edgecolor"] = t["fig_bg"]
    mpl.rcParams["axes.unicode_minus"] = True
    mpl.rcParams["path.simplify"] = True
    mpl.rcParams["path.simplify_threshold"] = 1.0
    mpl.rcParams["agg.path.chunksize"] = 10000
    families = list(screen_matplotlib_font_families())
    mpl.rcParams["font.family"] = families
    mpl.rcParams["font.sans-serif"] = families
    mpl.rcParams["font.serif"] = families
    mpl.rcParams["font.monospace"] = families
    mpl.rcParams["font.weight"] = "normal"
    mpl.rcParams["axes.titleweight"] = "normal"
    mpl.rcParams["figure.titleweight"] = "normal"
    mpl.rcParams["axes.titlesize"] = 12
    mpl.rcParams["axes.labelweight"] = "normal"
    mpl.rcParams["xtick.labelsize"] = 9
    mpl.rcParams["ytick.labelsize"] = 9
    mpl.rcParams["mathtext.fontset"] = "custom"
    mpl.rcParams["mathtext.rm"] = families[0]
    mpl.rcParams["mathtext.it"] = f"{families[0]}:italic"
    mpl.rcParams["mathtext.bf"] = f"{families[0]}:bold"
    mpl.rcParams["mathtext.bfit"] = f"{families[0]}:italic:bold"
    mpl.rcParams["mathtext.sf"] = families[0]
    mpl.rcParams["mathtext.tt"] = families[0]
    mpl.rcParams["mathtext.cal"] = families[0]
    mpl.rcParams["mathtext.default"] = "it"
    mpl.rcParams["mathtext.fallback"] = "stix"
    mpl.rcParams["legend.frameon"] = True
    mpl.rcParams["legend.framealpha"] = 0.95


def _btn_styles() -> dict[str, str]:
    """Resolve dialog button styles from the current theme at call time."""
    s = _build_styles()
    return {"tertiary": s["BTN_TERTIARY"], "secondary": s["BTN_SECONDARY"]}

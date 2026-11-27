"""Native sans-serif interface/screen chart fonts and publication export fonts."""
from contextlib import contextmanager
from functools import lru_cache
import logging
from pathlib import Path
import sys


REQUESTED_FAMILIES = ("Times New Roman", "Microsoft YaHei")
CHART_FONT_FAMILIES = (*REQUESTED_FAMILIES, "PingFang SC", "Noto Sans CJK SC", "DejaVu Sans")
SCREEN_CHART_FAMILIES = {
    "darwin": ("Helvetica Neue", "PingFang SC", "Hiragino Sans GB", "Arial", "DejaVu Sans"),
    "win32": ("Segoe UI", "Microsoft YaHei", "DejaVu Sans"),
}.get(sys.platform, ("Noto Sans", "Noto Sans CJK SC", "DejaVu Sans"))
FONT_FAMILIES = {
    "darwin": (".AppleSystemUIFont", "PingFang SC"),
    "win32": ("Segoe UI", "Microsoft YaHei"),
}.get(sys.platform, ("Noto Sans", "Noto Sans CJK SC", "DejaVu Sans"))
FONT_STACK = ",".join(f"'{family}'" for family in FONT_FAMILIES)


@lru_cache(maxsize=1)
def screen_matplotlib_font_families() -> tuple[str, ...]:
    """Return available sans-serif UI font families for on-screen Matplotlib plots."""
    from matplotlib import font_manager

    available = {font.name for font in font_manager.fontManager.ttflist}
    found = tuple(name for name in SCREEN_CHART_FAMILIES if name in available)
    return found or ("DejaVu Sans",)


@contextmanager
def publication_export_fonts(fig):
    """Temporarily apply Times New Roman + CJK fallback to a figure during export."""
    import matplotlib as mpl
    from matplotlib.text import Text

    families = list(matplotlib_font_families())
    if not families:
        yield
        return

    rc_keys = (
        "font.family",
        "font.sans-serif",
        "font.serif",
        "font.monospace",
        "mathtext.rm",
        "mathtext.it",
        "mathtext.bf",
        "mathtext.bfit",
        "mathtext.sf",
        "mathtext.tt",
        "mathtext.cal",
    )
    saved_rc = {k: mpl.rcParams[k] for k in rc_keys}
    saved_texts = []
    for txt in fig.findobj(Text):
        saved_texts.append((txt, txt.get_fontproperties().copy()))

    try:
        mpl.rcParams["font.family"] = families
        mpl.rcParams["font.sans-serif"] = families
        mpl.rcParams["font.serif"] = families
        mpl.rcParams["font.monospace"] = families
        mpl.rcParams["mathtext.rm"] = families[0]
        mpl.rcParams["mathtext.it"] = f"{families[0]}:italic"
        mpl.rcParams["mathtext.bf"] = f"{families[0]}:bold"
        mpl.rcParams["mathtext.bfit"] = f"{families[0]}:italic:bold"
        mpl.rcParams["mathtext.sf"] = families[0]
        mpl.rcParams["mathtext.tt"] = families[0]
        mpl.rcParams["mathtext.cal"] = families[0]
        for txt, _ in saved_texts:
            txt.set_fontfamily(families)
        yield
    finally:
        for txt, props in saved_texts:
            txt.set_fontproperties(props)
        for k, val in saved_rc.items():
            mpl.rcParams[k] = val


@lru_cache(maxsize=1)
def _office_fonts() -> tuple[Path, ...]:
    """Office on macOS has application-local fonts absent from system lists."""
    for app_name in ("Word", "Excel", "PowerPoint"):
        directory = Path(f"/Applications/Microsoft {app_name}.app/Contents/Resources/DFonts")
        if directory.is_dir():
            return tuple(directory / name for name in (
                "msyh.ttc", "msyhbd.ttc", "times.ttf", "timesbd.ttf",
                "timesi.ttf", "timesbi.ttf",
            ) if (directory / name).is_file())
    return ()


def apply_app_font(app) -> str:
    """Use the platform's interface face; Qt supplies per-glyph CJK fallback."""
    from PySide6.QtGui import QFont, QFontDatabase

    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    font.setFamilies(list(dict.fromkeys((font.family(), *FONT_FAMILIES))))
    font.setPointSize(11)
    font.setWeight(QFont.Weight.Normal)
    app.setFont(font)
    return font.family()


@lru_cache(maxsize=1)
def matplotlib_font_families() -> tuple[str, ...]:
    """Keep chart/export typography independent of the native interface face."""
    from matplotlib import font_manager

    available = {font.name for font in font_manager.fontManager.ttflist}
    if not set(REQUESTED_FAMILIES) <= available:
        for path in _office_fonts():
            font_manager.fontManager.addfont(str(path))
        available = {font.name for font in font_manager.fontManager.ttflist}
    missing = tuple(name for name in REQUESTED_FAMILIES if name not in available)
    if missing:
        logging.getLogger(__name__).warning(
            "Requested chart fonts unavailable: %s; using available system fallback",
            ", ".join(missing),
        )
    return tuple(name for name in CHART_FONT_FAMILIES if name in available)


def apply_vtk_font(text_property) -> None:
    """VTK's current Latin chart labels use the actual Times New Roman file."""
    from matplotlib import font_manager

    text_property.SetFontFamilyToTimes()
    if "Times New Roman" in matplotlib_font_families():
        text_property.SetFontFamily(4)  # VTK_FONT_FILE
        text_property.SetFontFile(font_manager.findfont(
            "Times New Roman", fallback_to_default=False))

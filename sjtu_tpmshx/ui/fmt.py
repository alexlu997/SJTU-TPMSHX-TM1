"""Display formatting for durations and saved preset names."""
from __future__ import annotations







def preset_display(name):
    """De-branded DISPLAY name for a preset (2026-07-03 user request):
    the internal key keeps its historical 'Shanghai (…)' spelling (presets
    dict, session files, tests), but every user-visible surface (command
    palette, status bar, session overview) shows 算例工况 instead."""
    if not name:
        return name
    return str(name).replace("Shanghai", "算例工况")


def duration(seconds):
    """'8.4s' / '2m15s' / '1h12m'."""
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return '—'
    if s < 60:
        return f"{s:.1f}s"
    if s < 3600:
        return f"{int(s // 60)}m{int(s % 60):02d}s"
    return f"{int(s // 3600)}h{int((s % 3600) // 60):02d}m"

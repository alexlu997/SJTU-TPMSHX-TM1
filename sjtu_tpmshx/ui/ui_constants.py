"""Centralized UI numeric constants — durations, thresholds.

Keeps the most repeated bare literals in one place so adjustments touch a
single line. One-off literals (window size, individual widget pixel
widths, debounce intervals) stay inline at their callsite — extracting
those adds indirection without saving edits later.
"""

# Status-bar / toast message visibility durations (milliseconds).
# Pick the bucket that matches the user's reading time, not exact ms.
TOAST_MS_BRIEF = 2000  # one-shot acknowledgements ("3D ready")
TOAST_MS_SHORT = 3000  # quick state changes ("Cancelled", "Cleared")
TOAST_MS_MED = 5000    # standard results / config confirmations

# V&V Standard Tier validated velocity limit (m/s). Above this, SIMPLE
# outer iterations slow 5-10× on the Forchheimer branch. Drives the
# off-domain status-bar notice at compute start.
VV_VELOCITY_LIMIT_MS = 10.0

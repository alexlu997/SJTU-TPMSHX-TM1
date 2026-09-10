"""Existing import path for the shared zone_config model implementation."""
import sys
from sjtu_tpmshx.models import zone_config as _implementation

# Publish exports before aliasing: concurrent from-imports may hold this module.
globals().update({key: value for key, value in vars(_implementation).items()
                  if not key.startswith("__")})
sys.modules[__name__] = _implementation

"""Existing import path for the shared sco2_props model implementation."""
import sys
from sjtu_tpmshx.models import sco2_props as _implementation

# Publish exports before aliasing: concurrent from-imports may hold this module.
globals().update({key: value for key, value in vars(_implementation).items()
                  if not key.startswith("__")})
sys.modules[__name__] = _implementation

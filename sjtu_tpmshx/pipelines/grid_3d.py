"""Existing import path for sjtu_tpmshx.models.grid_3d."""
import sys
from sjtu_tpmshx.models import grid_3d as _implementation

globals().update({key: value for key, value in vars(_implementation).items()
                  if not key.startswith("__")})
sys.modules[__name__] = _implementation

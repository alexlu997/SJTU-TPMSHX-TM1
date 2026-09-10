"""Existing import path for sjtu_tpmshx.models.field_coordinates_3d."""
import sys
from sjtu_tpmshx.models import field_coordinates_3d as _implementation

globals().update({key: value for key, value in vars(_implementation).items()
                  if not key.startswith("__")})
sys.modules[__name__] = _implementation

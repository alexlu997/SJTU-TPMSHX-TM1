"""Existing import path for the shared grid_schema model implementation."""
import sys
from sjtu_tpmshx.models import grid_schema as _implementation

sys.modules[__name__] = _implementation

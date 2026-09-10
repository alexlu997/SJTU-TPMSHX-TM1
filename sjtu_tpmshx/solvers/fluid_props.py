"""Existing import path for the shared fluid_props model implementation."""
import sys
from sjtu_tpmshx.models import fluid_props as _implementation

sys.modules[__name__] = _implementation

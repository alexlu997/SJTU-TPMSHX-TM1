"""Existing import path for the shared zone_config model implementation."""
import sys
from sjtu_tpmshx.models import zone_config as _implementation

sys.modules[__name__] = _implementation

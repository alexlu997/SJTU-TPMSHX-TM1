"""Existing import path for the shared tpms_geometry model implementation."""
import sys
from sjtu_tpmshx.models import tpms_geometry as _implementation

sys.modules[__name__] = _implementation

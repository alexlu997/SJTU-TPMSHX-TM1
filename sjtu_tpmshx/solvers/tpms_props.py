"""Existing import path for the shared tpms_props model implementation."""
import sys
from sjtu_tpmshx.models import tpms_props as _implementation

sys.modules[__name__] = _implementation

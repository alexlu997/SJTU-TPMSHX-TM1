"""Existing import path for the shared tpms_calc model implementation."""
import sys
from sjtu_tpmshx.models import tpms_calc as _implementation

sys.modules[__name__] = _implementation

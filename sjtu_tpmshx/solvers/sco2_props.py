"""Existing import path for the shared sco2_props model implementation."""
import sys
from sjtu_tpmshx.models import sco2_props as _implementation

sys.modules[__name__] = _implementation

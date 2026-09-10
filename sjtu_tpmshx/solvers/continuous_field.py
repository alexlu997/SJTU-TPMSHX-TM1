"""Existing import path for the shared continuous_field model implementation."""
import sys
from sjtu_tpmshx.models import continuous_field as _implementation

sys.modules[__name__] = _implementation

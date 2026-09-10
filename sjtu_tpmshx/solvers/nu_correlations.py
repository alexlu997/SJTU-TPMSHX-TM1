"""Existing import path for the shared nu_correlations model implementation."""
import sys
from sjtu_tpmshx.models import nu_correlations as _implementation

sys.modules[__name__] = _implementation

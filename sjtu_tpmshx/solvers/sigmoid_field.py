"""Existing import path for the shared sigmoid model."""
import sys
from sjtu_tpmshx.models import sigmoid_field as _implementation

sys.modules[__name__] = _implementation

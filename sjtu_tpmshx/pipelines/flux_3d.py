"""Existing import path for sjtu_tpmshx.solvers.backends.python.three_d.flux."""
import sys
from sjtu_tpmshx.solvers.backends.python.three_d import flux as _implementation

globals().update({key: value for key, value in vars(_implementation).items()
                  if not key.startswith("__")})
sys.modules[__name__] = _implementation

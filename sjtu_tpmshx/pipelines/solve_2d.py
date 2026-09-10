"""Existing pipeline import path for the 2D numerical coupling implementation."""
import sys
from sjtu_tpmshx.solvers.backends.python.two_d import coupling as _implementation

globals().update({key: value for key, value in vars(_implementation).items()
                  if not key.startswith("__")})
sys.modules[__name__] = _implementation

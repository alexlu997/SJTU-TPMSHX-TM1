"""Historical design fluid API; shared model implementation."""
import sys
from sjtu_tpmshx.models import design_fluids as _implementation

globals().update({key: value for key, value in vars(_implementation).items()
                  if not key.startswith('__')})
sys.modules[__name__] = _implementation

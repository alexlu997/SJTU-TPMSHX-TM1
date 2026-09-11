"""Existing 3D stage names delegating to the prepared numerical backend."""
import sys
from sjtu_tpmshx.preprocess.three_d.preparation import _prepare_problem_data
from sjtu_tpmshx.solvers.backends.python.three_d import runtime as _implementation


def _build_3d_problem(cfg):
    prepared = _prepare_problem_data(cfg)
    return _implementation.build_problem(prepared['cfg'], prepared)


_implementation._build_3d_problem = _build_3d_problem
globals().update({key: value for key, value in vars(_implementation).items()
                  if not key.startswith('__')})
sys.modules[__name__] = _implementation

"""Freeze effective run overrides without changing the process environment."""
import os


RUN_OVERRIDES = (
    'TPMSHX_CONV_MODE', 'TPMSHX_P_IN_SHOOT',
    'TPMSHX_VAR_RHOCP', 'TPMSHX_SCO2_COMPRESSIBLE',
    'TPMSHX_PHASE_A', 'TPMSHX_PHASE_B', 'TPMSHX_PHASE_C', 'TPMSHX_CHI_S',
    # Retain the old selector only to reject saved hybrid-kernel requests.
    'TPMSHX_TRUE_H_KERNEL',
)


def capture_environment():
    return {name: os.environ.get(name) for name in RUN_OVERRIDES}


def run_environment(cfg, name, default=None):
    source = cfg['_environment'] if cfg is not None and '_environment' in cfg else os.environ
    value = source.get(name)
    return default if value is None else value


def require_python_kernel(cfg):
    kernel = run_environment(cfg, 'TPMSHX_TRUE_H_KERNEL', 'numba')
    if kernel != 'numba':
        raise ValueError(
            f'TPMSHX_TRUE_H_KERNEL={kernel!r} is no longer supported; '
            'the mixed Python/C++ sweep route has been retired. '
            'Use backend=python with the default kernel or backend=cpp '
            'with the complete native solver.')


def require_f2_mode(mode):
    """Keep the serialized selector explicit after retiring legacy convergence."""
    if mode not in (None, 'f2'):
        raise ValueError(
            f"convergence_mode must be 'f2', got {mode!r}; "
            "the legacy mass/velocity exit has been retired")
    return 'f2'

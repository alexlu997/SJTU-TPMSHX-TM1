"""Freeze effective run overrides without changing the process environment."""
import os


RUN_OVERRIDES = (
    'TPMSHX_CONV_MODE', 'TPMSHX_P_IN_SHOOT',
    'TPMSHX_VAR_RHOCP', 'TPMSHX_SCO2_COMPRESSIBLE',
    'TPMSHX_PHASE_A', 'TPMSHX_PHASE_B', 'TPMSHX_PHASE_C', 'TPMSHX_CHI_S',
    # Reject explicit requests for the retired Python and hybrid kernels.
    'TPMSHX_TRUE_H_KERNEL',
)


def capture_environment():
    return {name: os.environ.get(name) for name in RUN_OVERRIDES}


def run_environment(cfg, name, default=None):
    source = cfg['_environment'] if cfg is not None and '_environment' in cfg else os.environ
    value = source.get(name)
    return default if value is None else value


def reject_retired_kernel(cfg):
    if run_environment(cfg, 'TPMSHX_TRUE_H_KERNEL') is not None:
        raise ValueError('TPMSHX_TRUE_H_KERNEL has been retired; remove this override for native execution')


def require_f2_mode(mode):
    """Keep the serialized selector explicit after retiring legacy convergence."""
    if mode not in (None, 'f2'):
        raise ValueError(
            f"convergence_mode must be 'f2', got {mode!r}; "
            "the legacy mass/velocity exit has been retired")
    return 'f2'

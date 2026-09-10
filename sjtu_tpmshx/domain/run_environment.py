"""Freeze effective run overrides without changing the process environment."""
import os


RUN_OVERRIDES = (
    'TPMSHX_SIMPLE_TOL', 'TPMSHX_CONV_MODE', 'TPMSHX_P_IN_SHOOT',
    'TPMSHX_VAR_RHOCP', 'TPMSHX_SCO2_COMPRESSIBLE',
    'TPMSHX_PHASE_A', 'TPMSHX_PHASE_B', 'TPMSHX_PHASE_C', 'TPMSHX_CHI_S',
)


def capture_environment():
    return {name: os.environ.get(name) for name in RUN_OVERRIDES}


def run_environment(cfg, name, default=None):
    source = cfg['_environment'] if cfg is not None and '_environment' in cfg else os.environ
    value = source.get(name)
    return default if value is None else value

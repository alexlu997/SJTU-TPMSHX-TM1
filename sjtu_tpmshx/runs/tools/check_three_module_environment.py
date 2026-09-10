"""Check the actual minimal offline runtime, not a full-env import substitute."""
import importlib.util
import sys


def main():
    for package in ('numpy', 'h5py', 'yaml'):
        if importlib.util.find_spec(package) is None:
            raise RuntimeError(f'missing required offline dependency: {package}')
    for package in ('numba', 'PySide6'):
        if importlib.util.find_spec(package) is not None:
            raise RuntimeError(f'minimal offline acceptance must not install {package}')
    from sjtu_tpmshx.io.case_io import load_case  # noqa: F401
    from sjtu_tpmshx.io.result_io import load_result  # noqa: F401
    from sjtu_tpmshx.io.metrics_io import save_metrics  # noqa: F401
    from sjtu_tpmshx.postprocess.metrics import evaluate  # noqa: F401
    for prefix in ('sjtu_tpmshx.solvers', 'sjtu_tpmshx.preprocess', 'sjtu_tpmshx.pipelines', 'numba', 'PySide6'):
        if any(name == prefix or name.startswith(prefix + '.') for name in sys.modules):
            raise RuntimeError(f'offline import crossed module boundary: {prefix}')
    print('minimal offline dependencies and public imports passed; no numerical result is implied')


if __name__ == '__main__':
    main()

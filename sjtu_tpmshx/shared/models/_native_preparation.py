"""Load the prebuilt preparation library through its C data interface."""
import ctypes as ct
from functools import lru_cache
from importlib.resources import files
import os
from pathlib import Path
import platform
import sys


def _library_path():
    selected = os.environ.get('TPMSHX_PREPARATION_LIBRARY')
    if selected is not None:
        if not selected.strip():
            raise ValueError('TPMSHX_PREPARATION_LIBRARY must name a prebuilt preparation library')
        path = Path(selected).expanduser()
    else:
        machine = platform.machine().lower()
        if sys.platform == 'darwin' and machine in ('arm64', 'aarch64'):
            host, name = 'macos-arm64', 'libtpmshx_preparation_shared.dylib'
        elif sys.platform == 'win32' and machine in ('amd64', 'x86_64'):
            host, name = 'windows-x64', 'tpmshx_preparation_shared.dll'
        else:
            raise RuntimeError(
                f'no default native preparation library for {sys.platform}/{machine}; '
                'set TPMSHX_PREPARATION_LIBRARY to a prebuilt library')
        if getattr(sys, 'frozen', False):
            path = Path(sys._MEIPASS) / 'native' / name
        else:
            path = Path(str(files('sjtu_tpmshx').joinpath('solvers', 'native', 'lib', host, name)))
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f'prebuilt native preparation library is missing: {path}')
    return str(path)


class _NativeLibrary:
    def __init__(self, path):
        self.path = path
        try:
            self.library = ct.CDLL(path)
        except OSError as error:
            raise OSError(f'cannot load prebuilt native preparation library {path}: {error}') from error
        version = self.bind('tpmshx_preparation_abi_version_v1', [], ct.c_uint32)
        abi = version()
        if abi != 1:
            raise ValueError(f'unsupported native preparation ABI {abi} in {path}; expected 1')

    def bind(self, symbol, arguments, result=ct.c_int):
        try:
            function = getattr(self.library, symbol)
        except AttributeError as missing:
            raise ValueError(f'prebuilt native preparation library {self.path} lacks {symbol}') from missing
        function.argtypes = arguments
        function.restype = result
        return function


@lru_cache(maxsize=1)
def _load_library(path):
    return _NativeLibrary(path)


def _library():
    return _load_library(_library_path())

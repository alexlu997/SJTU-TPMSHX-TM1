"""Select and bind the independently deployed preparation and result libraries."""
import ctypes as ct
from functools import lru_cache
import os
from pathlib import Path
import platform
import sys

from sjtu_tpmshx.run_control.provenance import PUBLISHED_LIBRARY_DIR


class StageLibrary:
    def __init__(self, name, version, error):
        self.name, self.version, self.error = name, version, error
        self.variable = f'TPMSHX_{name.upper()}_LIBRARY'
        self.load = lru_cache(maxsize=1)(self.open)

    def path(self):
        selected = os.environ.get(self.variable)
        if selected is not None:
            if not selected.strip():
                raise self.error(f'{self.variable} must name a prebuilt {self.name} library')
            path = Path(selected).expanduser()
        else:
            machine = platform.machine().lower()
            if sys.platform == 'darwin' and machine in ('arm64', 'aarch64'):
                host, filename = 'macos-arm64', f'libtpmshx_{self.name}_shared.dylib'
            elif sys.platform == 'win32' and machine in ('amd64', 'x86_64'):
                host, filename = 'windows-x64', f'tpmshx_{self.name}_shared.dll'
            elif self.name == 'result' and sys.platform == 'linux' and machine in ('amd64', 'x86_64'):
                host, filename = 'linux-x86_64', 'libtpmshx_result_shared.so'
            else:
                label = 'native preparation' if self.name == 'preparation' else self.name
                raise RuntimeError(f'no default {label} library for {sys.platform}/{machine}; '
                                   f'set {self.variable} to a prebuilt library')
            path = (Path(sys._MEIPASS) / 'native' / filename if getattr(sys, 'frozen', False)
                    else PUBLISHED_LIBRARY_DIR / host / filename)
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f'prebuilt native {self.name} library is missing: {path}')
        return str(path)

    def open(self, path):
        owner = BoundLibrary(self, path)
        abi = owner.bind(f'tpmshx_{self.name}_abi_version_v1', [], ct.c_uint32)()
        if abi != self.version:
            raise self.error(f'unsupported native {self.name} ABI {abi} in {path}; expected {self.version}')
        return owner

    def get(self):
        return self.load(self.path())


class BoundLibrary:
    def __init__(self, stage, path):
        self.stage, self.path = stage, path
        self.functions = {}
        try:
            self.library = ct.CDLL(path)
        except OSError as error:
            raise OSError(f'cannot load prebuilt native {stage.name} library {path}: {error}') from error

    def bind(self, name, arguments, result=ct.c_int):
        key = name, tuple(arguments), result
        if key not in self.functions:
            try:
                # Indexing gives each signature its own ctypes function.
                function = self.library[name]
            except AttributeError as error:
                raise self.stage.error(f'prebuilt native {self.stage.name} library {self.path} lacks {name}') from error
            function.argtypes, function.restype = arguments, result
            self.functions[key] = function
        return self.functions[key]


preparation_library = StageLibrary('preparation', 2, ValueError)
result_library = StageLibrary('result', 3, RuntimeError)

"""Build the locked base desktop application on the target operating system."""
from pathlib import Path
import os
import sys
from tempfile import TemporaryDirectory

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parents[1]
sys.path.insert(0, str(root))
from engineering.packaging.python_source import build_package
from engineering.scripts.build_native_dependencies import stage_native_notices

with TemporaryDirectory(prefix='tm1-desktop-python-') as package_tree:
    build_package(root, package_tree)
    sys.path.insert(0, package_tree)
    from sjtu_tpmshx._version import __version__

    excluded = ('sjtu_tpmshx.development',)
    hidden = collect_submodules('sjtu_tpmshx', filter=lambda name: not name.startswith(excluded))
    data = collect_data_files('sjtu_tpmshx', includes=[
        'model_configs/*.json',
        'physical_models/df_surrogate/_prebuilt/*.csv',
        'applications/gui/ui/assets/icons/*.svg',
        'applications/gui/ui/assets/icons/LICENSE',
        'applications/gui/ui/assets/icons/README.md',
    ])
    data += [(str(root / 'examples' / 'three_module' / name), 'examples')
             for name in ('air_2d.json', 'air_3d.json')]
    data += [(str(root / 'LICENSE'), 'licenses')]

    # Packaging requires the prebuilt library for the target platform.
    native_input = os.environ.get('TPMSHX_NATIVE_SOLVER_LIBRARY')
    if not native_input or not native_input.strip():
        raise ValueError('TPMSHX_NATIVE_SOLVER_LIBRARY must name a prebuilt solver library')
    library = Path(native_input).expanduser().resolve(strict=True)
    expected_name = {
        'darwin': 'libtpmshx_solver_shared.dylib',
        'win32': 'tpmshx_solver_shared.dll',
    }[sys.platform]
    if not library.is_file() or library.name != expected_name:
        raise ValueError(f'Expected the prebuilt {expected_name} for this desktop target: {library}')
    binaries = [(str(library), 'native')]
    geometry_input = os.environ.get('TPMSHX_NATIVE_GEOMETRY_LIBRARY')
    if not geometry_input or not geometry_input.strip():
        raise ValueError('TPMSHX_NATIVE_GEOMETRY_LIBRARY must name a prebuilt geometry library')
    geometry_library = Path(geometry_input).expanduser().resolve(strict=True)
    geometry_name = {
        'darwin': 'libtpmshx_geometry_shared.dylib',
        'win32': 'tpmshx_geometry_shared.dll',
    }[sys.platform]
    if not geometry_library.is_file() or geometry_library.name != geometry_name:
        raise ValueError(f'Expected the prebuilt {geometry_name} for this desktop target: {geometry_library}')
    binaries.append((str(geometry_library), 'native'))
    preparation_input = os.environ.get('TPMSHX_NATIVE_PREPARATION_LIBRARY')
    if not preparation_input or not preparation_input.strip():
        raise ValueError('TPMSHX_NATIVE_PREPARATION_LIBRARY must name a prebuilt preparation library')
    preparation_library = Path(preparation_input).expanduser().resolve(strict=True)
    preparation_name = {
        'darwin': 'libtpmshx_preparation_shared.dylib',
        'win32': 'tpmshx_preparation_shared.dll',
    }[sys.platform]
    if not preparation_library.is_file() or preparation_library.name != preparation_name:
        raise ValueError(f'Expected the prebuilt {preparation_name} for this desktop target: {preparation_library}')
    binaries.append((str(preparation_library), 'native'))
    result_input = os.environ.get('TPMSHX_NATIVE_RESULT_LIBRARY')
    if not result_input or not result_input.strip():
        raise ValueError('TPMSHX_NATIVE_RESULT_LIBRARY must name a prebuilt result library')
    result_library = Path(result_input).expanduser().resolve(strict=True)
    result_name = {
        'darwin': 'libtpmshx_result_shared.dylib',
        'win32': 'tpmshx_result_shared.dll',
    }[sys.platform]
    if not result_library.is_file() or result_library.name != result_name:
        raise ValueError(f'Expected the prebuilt {result_name} for this desktop target: {result_library}')
    binaries.append((str(result_library), 'native'))
    notices = root / '.cache/desktop/native-notices'
    for notice in stage_native_notices(root, notices):
        destination = Path('licenses/native') / notice.relative_to(notices).parent
        data.append((str(notice), destination.as_posix()))

    a = Analysis(
        [str(root / 'engineering' / 'packaging' / 'desktop_entry.py')],
        pathex=[package_tree], binaries=binaries, datas=data, hiddenimports=hidden,
        # VTK's compatibility aggregator imports every optional VTK module.
        # The app and locked PyVista use vtkmodules directly; PyVista's type hints
        # and old-version fallbacks otherwise pull the aggregator into Analysis.
        excludes=[*excluded, 'vtk', 'torch', 'botorch', 'gpytorch', 'pytest', 'mypy', 'ruff'],
        # savefig selects vector backends dynamically; static discovery misses
        # the SVG/PDF formats exposed by the desktop export dialog.
        hooksconfig={'matplotlib': {'backends': ['Agg', 'QtAgg', 'svg', 'pdf']}},
    )
    pyz = PYZ(a.pure)
    exe = EXE(
        pyz, a.scripts, [], exclude_binaries=True, name='SJTU-TPMSHX',
        debug=False, strip=False, upx=False, console=sys.platform != 'darwin',
    )
    collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='SJTU-TPMSHX')
    if sys.platform == 'darwin':
        app = BUNDLE(
            collection, name='SJTU-TPMSHX.app',
            bundle_identifier='org.sjtu.tpmshx', version=__version__,
            info_plist={'NSHighResolutionCapable': True},
        )

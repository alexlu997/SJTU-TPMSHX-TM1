"""Build the locked base desktop application on the target operating system."""
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parent
sys.path.insert(0, str(root))
from sjtu_tpmshx._version import __version__

excluded = ('sjtu_tpmshx.tests', 'sjtu_tpmshx.runs', 'sjtu_tpmshx.validation')
hidden = collect_submodules('sjtu_tpmshx', filter=lambda name: not name.startswith(excluded))
data = collect_data_files('sjtu_tpmshx', includes=[
    'configs/*.json',
    'df_surrogate/_prebuilt/*.csv',
    'ui/assets/icons/*.svg',
    'ui/assets/icons/LICENSE',
    'ui/assets/icons/README.md',
])
data += [(str(root / 'examples' / 'three_module' / name), 'examples')
         for name in ('air_2d.json', 'air_3d.json')]
data += [(str(root / 'LICENSE'), 'licenses')]

a = Analysis(
    [str(root / 'packaging' / 'desktop_entry.py')],
    pathex=[str(root)], binaries=[], datas=data, hiddenimports=hidden,
    # VTK's compatibility aggregator imports every optional VTK module.
    # The app and locked PyVista use vtkmodules directly; PyVista's type hints
    # and old-version fallbacks otherwise pull the aggregator into Analysis.
    excludes=[*excluded, 'vtk', 'torch', 'botorch', 'gpytorch', 'pytest', 'mypy', 'ruff'],
    # savefig selects vector backends dynamically; static discovery misses
    # the SVG/PDF formats exposed by the desktop export dialog.
    hooksconfig={'matplotlib': {'backends': ['Agg', 'QtAgg', 'svg', 'pdf']}},
    # Load from real files: PYZ code keeps relative co_filename values that
    # Numba's cache locator cannot resolve outside the source directory.
    module_collection_mode={'sjtu_tpmshx': 'py'},
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

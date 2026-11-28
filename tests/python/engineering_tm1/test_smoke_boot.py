"""Keep GUI smoke imports free of application creation in a separate process."""
import subprocess
import sys


def test_smoke_imports_create_no_application():
    subprocess.run([sys.executable, '-c', '''
import importlib
import os
import sys

os.environ.pop('QT_QPA_PLATFORM', None)
from tm1.development.runs import _smoke_boot
assert 'PySide6' not in sys.modules
assert os.environ['QT_QPA_PLATFORM'] == 'offscreen'
from PySide6.QtWidgets import QApplication
for name in ('smoke_ui_offscreen', 'smoke_ui_screenshots'):
    importlib.import_module(f'tm1.development.runs.smokes.{name}')
assert QApplication.instance() is None
app = _smoke_boot.get_app()
assert app.platformName() == 'offscreen'
assert _smoke_boot.get_app() is app
print('import isolation and explicit offscreen app setup PASS')
'''], check=True, timeout=30)

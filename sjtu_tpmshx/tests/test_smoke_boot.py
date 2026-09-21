"""Keep modal patches isolated from the pytest process and other UI tests."""
import os
import subprocess
import sys


def test_pipeline_smoke_modals():
    subprocess.run([sys.executable, '-c', '''
import contextlib
import importlib
import io
import sys

from sjtu_tpmshx.runs import _smoke_boot
assert 'PySide6' not in sys.modules
from PySide6.QtWidgets import QApplication, QMessageBox
names = ('question', 'warning', 'information', 'exec')
original = [getattr(QMessageBox, name) for name in names]
for dimension in ('2d', '3d'):
    importlib.import_module(f'sjtu_tpmshx.runs.smokes.smoke_ui_{dimension}_pipeline')
assert QApplication.instance() is None
assert original == [getattr(QMessageBox, name) for name in names]
app = _smoke_boot.get_app()
assert original == [getattr(QMessageBox, name) for name in names]
output = io.StringIO()
with contextlib.redirect_stdout(output):
    _smoke_boot.patch_modals()
    for name in names[:-1]:
        assert getattr(QMessageBox, name)(None, 'title', 'text') == QMessageBox.StandardButton.Yes
    box = QMessageBox()
    assert box.exec() == QMessageBox.StandardButton.Yes
assert output.getvalue() == '  [dialog auto-Yes]\\n' * 3 + '  [instance modal auto-Yes]\\n'

print('import isolation, explicit app/modal setup and four Yes returns PASS')
'''], check=True, timeout=30, env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen'})

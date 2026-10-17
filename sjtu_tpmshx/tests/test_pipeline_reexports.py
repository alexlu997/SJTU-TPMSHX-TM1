"""Current UI builder exports."""
from __future__ import annotations

import importlib

import pytest


_SURFACE = {
    'sjtu_tpmshx.ui.builders_canvas': [
        '_build_result_sidebar',
        'update_result_sidebar_visibility', 'build_canvas_area',
    ],
}


@pytest.mark.parametrize('module_name', sorted(_SURFACE))
def test_reexport_surface(module_name):
    mod = importlib.import_module(module_name)
    missing = [n for n in _SURFACE[module_name] if not hasattr(mod, n)]
    assert not missing, (
        f"{module_name} lost re-exported names: {missing} — external "
        f"consumers (tests, runs/, validation/) import these from here.")

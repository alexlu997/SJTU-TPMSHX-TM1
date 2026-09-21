"""Capture current geometry and optimization pages offscreen without solving.

Run from the repository root as
``python -m sjtu_tpmshx.runs.smokes.smoke_ui_screenshots --output DIRECTORY``.
Temporary user state and reduced motion keep captures independent of a saved
session. Failed navigation, Qt callbacks or image writes return exit code 1.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import traceback

from sjtu_tpmshx.runs.smokes.smoke_ui_offscreen import _smoke_window


def _save_window(win, path):
    if not win.grab().save(str(path)):
        raise OSError(f'Could not save screenshot: {path}')
    print(f'saved {path}', flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('.cache/ui-smoke-screenshots'))
    args = parser.parse_args(argv)
    try:
        args.output.mkdir(parents=True, exist_ok=True)
        with _smoke_window() as (app, win):
            _save_window(win, args.output / '01_full_window.png')
            combo_dim = getattr(win, 'combo_dim', None)
            if combo_dim is None:
                raise RuntimeError('Required dimension selector is missing')
            for index, target in enumerate(('2D', '3D'), start=2):
                choice = combo_dim.findText(target)
                if choice < 0:
                    raise RuntimeError(f'Dimension selector has no {target} option')
                combo_dim.setCurrentIndex(choice)
                app.processEvents()
                if combo_dim.currentText() != target:
                    raise RuntimeError(f'Dimension did not change to {target}')
                _save_window(win, args.output / f'0{index}_full_window_{target.lower()}_mode.png')

            button = getattr(win, 'btn_tab_pareto', None)
            if button is None or not button.isVisible() or not button.isEnabled():
                raise RuntimeError('Required optimization entry is unavailable')
            button.click()
            app.processEvents()
            if win._active_tab != 'pareto' or not win._canvas_cards['pareto'].isVisibleTo(win):
                raise RuntimeError('Navigation did not show the optimization page')
            _save_window(win, args.output / '04_optimize_panel.png')
    except Exception:
        traceback.print_exc()
        print('UI screenshot smoke FAIL', flush=True)
        return 1
    print(f'UI screenshot smoke PASS: {args.output}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Select CI checks and require their expected job results."""
import argparse
import json
import os
from pathlib import PurePosixPath
import subprocess

TIERS = ('docs', 'application', 'full')
DISPLAY_FILES = {
    'sjtu_tpmshx/ui/' + name for name in (
        'icons.py', 'ui_constants.py', 'vis3d_constants.py', 'responsive.py',
        'matplotlib_canvas.py', 'typography.py', 'theme.py', 'theme_manager.py',
        'microanim.py', 'sparkline.py', 'plot_2d_results.py', 'plot_3d_results.py',
        'panel_vis_3d.py', 'coord_inspector.py', 'field_menu.py', 'layout_drawer.py',
    )
} | {
    'sjtu_tpmshx/tests/' + name for name in (
        'test_theme_manager.py', 'test_ui_typography.py', 'test_responsive.py',
        'test_ui_layout_hygiene.py', 'test_lazy_result_plots.py',
    )
}


def document(path):
    return (path in {'README.md', 'README.en.md', 'AGENTS.md'}
            or path.startswith('docs/') and path.endswith('.md'))


def select_scope(event, paths):
    if event != 'pull_request' or not paths:
        return 'full'
    if all(document(path) for path in paths):
        return 'docs'
    if all(document(path) or path in DISPLAY_FILES
           or path.startswith('sjtu_tpmshx/ui/assets/icons/')
           and PurePosixPath(path).suffix == '.svg' for path in paths):
        return 'application'
    return 'full'


def require_jobs(tier, needs, stage):
    if tier not in TIERS or stage not in {'summary', 'minimal'}:
        raise ValueError('Unknown CI tier or gate')
    result = 'skipped' if tier == 'docs' else 'success'
    expected = {'scope': 'success', 'native': result}
    if stage == 'summary':
        expected.update({'bo-tests': result, 'minimal-postprocess': 'success'})
    actual = {name: job['result'] for name, job in needs.items()}
    if actual != expected:
        raise ValueError(f'Expected CI jobs {expected}; got {actual}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    select = commands.add_parser('select')
    select.add_argument('--event', required=True)
    select.add_argument('--base', default='')
    select.add_argument('--head', default='')
    gate = commands.add_parser('gate')
    gate.add_argument('--tier', required=True, choices=TIERS)
    gate.add_argument('--stage', required=True, choices=('summary', 'minimal'))
    args = parser.parse_args()
    if args.action == 'select':
        paths = []
        if args.event == 'pull_request':
            paths = subprocess.check_output(
                ['git', 'diff', '--name-only', '--no-renames', '-z',
                 args.base, args.head, '--'], text=True).split('\0')
            paths = [path for path in paths if path]
        print(select_scope(args.event, paths))
    else:
        require_jobs(args.tier, json.loads(os.environ['NEEDS_JSON']), args.stage)


if __name__ == '__main__':
    main()

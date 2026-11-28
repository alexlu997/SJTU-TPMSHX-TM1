"""Start TM1: the desktop GUI (default) or one command-line mode (see USAGE).

This file imports no Qt, VTK, Matplotlib or Torch. Each route imports its own
modules after this file selects the mode. The GUI route imports Qt, VTK and
Matplotlib. Torch loads only for a BO method: in the optimize route, or in the
GUI process when the GUI runs a BO study.
Spawned child processes import this file as ``__mp_main__``; the guard at the
end keeps them from routing.
"""
import multiprocessing
import sys

STAGES = ('prepare', 'solve', 'postprocess', 'run', 'resume')
MODES = ('gui', *STAGES, 'summary', 'design', 'optimize')
# A constant, not the docstring: "python -OO" removes docstrings.
USAGE = """Start TM1: the desktop GUI (default) or one command-line mode.

Usage from the repository root:

    python main.py [gui] [GUI options]
    python main.py {prepare,solve,postprocess,run,resume} ...
    python main.py summary CONFIG [--dry-run] [--json]
    python main.py design ...
    python main.py optimize INPUT OUTPUT_DIR ...

Use MODE --help for the arguments of a mode."""


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] in (['-h'], ['--help']):
        print(USAGE)
        return 0
    if not args or args[0].startswith('-'):
        args.insert(0, 'gui')
    mode = args.pop(0)
    if mode in STAGES:
        from tm1.applications.cli.stages import main as run_stage
        return run_stage([mode, *args])
    if mode == 'summary':
        from tm1.applications.cli.main import main as run_summary
        return run_summary(args)
    if mode == 'design':
        from tm1.applications.design.cli import run as run_design
        return run_design(args)
    if mode == 'optimize':
        from tm1.applications.optimization.cli import run as run_optimization
        return run_optimization(args)
    if mode == 'gui':
        from tm1.applications.gui.main import main as run_gui
        return run_gui(args)
    print(f"main.py: unknown mode '{mode}'; use one of: {', '.join(MODES)}", file=sys.stderr)
    return 2


if __name__ == '__main__':
    # A frozen application starts its spawned children through this call.
    multiprocessing.freeze_support()
    raise SystemExit(main())

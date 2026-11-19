"""Start the GUI through the supported module command."""
import sys
from pathlib import Path

# Support the source-file launch without an editable install.
_PROJECT_PARENT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_PARENT not in sys.path:
    sys.path.insert(0, _PROJECT_PARENT)

from sjtu_tpmshx.applications.gui.main import main


if __name__ == '__main__':
    raise SystemExit(main())

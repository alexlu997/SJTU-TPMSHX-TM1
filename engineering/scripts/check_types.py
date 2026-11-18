"""Check public module types in the package layout used by installed clients."""
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from engineering.packaging.python_source import build_package


def main():
    root = Path(__file__).resolve().parents[2]
    with TemporaryDirectory(prefix="tm1-types-") as directory:
        build_package(root, directory)
        return subprocess.call([sys.executable, "-m", "mypy", "--config-file",
                                str(root / "pyproject.toml"), *sys.argv[1:]], cwd=directory)


if __name__ == "__main__":
    raise SystemExit(main())

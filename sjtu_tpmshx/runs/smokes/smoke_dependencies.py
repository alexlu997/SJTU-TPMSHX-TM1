"""Exercise native dependencies used by unattended local worktrees.

Run from the repository root with the dependency-only shared venv::

    python -m sjtu_tpmshx.runs.smokes.smoke_dependencies
"""
from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sjtu_tpmshx


def main() -> None:
    root = Path.cwd().resolve()
    package_file = Path(sjtu_tpmshx.__file__).resolve()
    if not package_file.is_relative_to(root):
        raise RuntimeError(
            f"sjtu_tpmshx resolved outside the current worktree: {package_file}"
        )

    from PIL import Image

    png = BytesIO()
    Image.new("RGB", (2, 2), "white").save(png, format="PNG")
    png.seek(0)
    with Image.open(png) as image:
        image.load()

    import matplotlib

    matplotlib.use("Agg", force=True)
    from matplotlib.figure import Figure

    figure = Figure(figsize=(1, 1))
    axes = figure.subplots()
    axes.plot([0.0, 1.0], [0.0, 1.0])
    figure.savefig(BytesIO(), format="png")

    import numpy as np
    from scipy import linalg

    matrix = np.array([[3.0, 1.0], [1.0, 2.0]])
    rhs = np.array([9.0, 8.0])
    expected = np.array([2.0, 3.0])
    if not np.allclose(np.linalg.solve(matrix, rhs), expected):
        raise RuntimeError("NumPy linear algebra smoke failed")
    if not np.allclose(linalg.solve(matrix, rhs), expected):
        raise RuntimeError("SciPy linear algebra smoke failed")

    from CoolProp.CoolProp import PropsSI

    if PropsSI("D", "T", 300.0, "P", 101325.0, "Air") <= 0.0:
        raise RuntimeError("CoolProp property smoke failed")

    from PySide6.QtWidgets import QApplication, QLabel

    app = QApplication.instance() or QApplication(
        ["smoke_dependencies", "-platform", "offscreen"]
    )
    label = QLabel("SJTU-TPMSHX")
    label.resize(160, 40)
    label.show()
    app.processEvents()
    if label.grab().isNull():
        raise RuntimeError("PySide6 offscreen render smoke failed")
    label.close()
    app.processEvents()

    print("Prewarming PyVista/VTK imports ...", flush=True)
    import pyvista as pv
    from pyvistaqt import QtInteractor  # noqa: F401

    vtk_grid = pv.ImageData(dimensions=(2, 2, 2))
    if vtk_grid.n_points != 8:
        raise RuntimeError("PyVista/VTK grid smoke failed")

    print(f"Dependency smoke pass; source={package_file}")


if __name__ == "__main__":
    main()

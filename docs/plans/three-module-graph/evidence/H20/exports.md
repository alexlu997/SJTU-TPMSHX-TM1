# Independent export evidence

`test_tm1_vtk_readback.py`: **1 passed in 13.05 s, native exit 0**. The real
VTK reader recovered native cell order, unit metadata and converged=False
from an artificial FieldResult. This is a format test, not numerical acceptance.

The real B20/B30 archived HDF5 results were separately read, without a new
solve, to create HTML reports, VTK files and Ta plots. Native exit 0. Outputs
are in `.cache/tm1-io/B20-files/handoff` and `B30-files/handoff`.
The 3D z-cell plot was visually inspected: correct physical x/y axes, K colour
scale, native cell boundaries and no data smoothing. Minimal CI tests the
metric/file boundary; optional plotting and VTK-reader dependencies are distinct.

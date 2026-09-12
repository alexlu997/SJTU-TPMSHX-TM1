# SJTU-TPMSHX-TM1 architecture

This is the current architectural and physical contract for the repository.
Historical audits and reports explain how the project reached this state, but
they do not override the running code or this document.

## Runtime flow

```text
applications -> preprocess.api -> CaseData -> solvers.api -> FieldResult
                                                          -> postprocess.api -> PerformanceResult
                         domain / models / versioned resources / file I/O
```

- `domain/` owns immutable CaseData, FieldResult, metric definitions and
  runtime control ports; it is Qt-free.
- `preprocess/` owns physical grid/boundary preparation, fixed geometry and
  coefficients, model/resource selection and portable execution inputs.
- `solvers/backends/python/` owns prepared numerical execution, current-state
  property evaluation and native result capture; SIMPLE/LTNE kernels remain
  under `solvers/`. It does not import preprocessing or formal postprocessing.
  The 2D loop reads prepared properties directly, reports through `RunControl`,
  and returns application coefficients and zone statistics with its native
  result; it has no window-shaped runtime adapter or attribute-write hooks.
- `postprocess/` reduces recorded fields, fluxes and pressure states. It never
  reruns a solver or reads a private runtime object to recover missing evidence.
- `models/` and `df_surrogate/` own shared pure closures and versioned resources.
  Explicit cleaning/calibration entry points live under `preprocess/offline/`.
- `io/` owns strict YAML/HDF5/JSON interchange. VTK export is a postprocessing
  view of recorded data, not a new numerical state.
- `configs/` owns packaged case configuration.
- `pipelines/` retains explicit scripted stage entry points. Callers import
  shared models and numerical backends directly; there are no `sys.modules`
  aliases or import-time function injection into the numerical backend.
  The retained dictionary-based 3D entry is `run_stack_3d._run_3d_stack`.
  Former `stages_2d`, `stages_3d` and `_stage_common` import facades are retired;
  preparation and shared helpers are imported from their owning modules.
- `controllers/compute_pipeline.py` sequences the public modules; the module
  adapter maps their results to the historical GUI ComputeResult contract.
  It is the sole production result mapper. The old 2D/3D mappings remain only
  as frozen test oracles for the real native-result integration comparison.
- `ui/` owns PySide6 and PyVista presentation only.
- `validation/` and `runs/` are executable research and verification tools,
  not alternative production implementations.

The GUI entry point is `python -m sjtu_tpmshx.main`; source-based headless
work uses `python -m sjtu_tpmshx.cli`. Parameter optimization and design use
the same public contracts with their explicitly named approximation modes.
M-A review, CI and merged-main acceptance are recorded in the Graph state for
the rectangular 2D/3D module flow. M-B extensions and historical baseline
failures retain their separate scope and status.

Production domain shapes are currently limited to **Rectangle**, in 2D and 3D.
Hexagon/Octagon choices are disabled. Saved polygon presets retain their shape
for viewing and saving, but the Compute entry and window-to-config adapter
reject them; they are never silently interpreted as rectangles. The historical
`ui/polygon_calc.py`, polygon kernels and triangular meshing are retired;
only the preset vertex helpers remain for viewing and saving. Original code
is linked in the [history index](history/retired-tools.md).
Reopening polygon compute requires the mainline physical rules and real
CaseData/FieldResult/PerformanceResult handoff, not just relocating the GUI code.

### Persistent interfaces and physical state

CaseData contains the actual prepared grid, design fields, boundary inputs,
fixed thermal/flow geometry, model versions and resolved settings. A config
snapshot is provenance, not instructions for rebuilding the case in a receiver.
Runtime controls (progress/cancellation callbacks) are separate and never
serialized. Unknown modes/resources and incomplete prepared inputs fail.

FieldResult contains native field locations/units, original flux and pressure
evidence, execution/convergence status and diagnostic metadata. Display
pressure/temperature fields do not replace the raw numerical state. NaN in
diagnostic arrays and unconverged completed runs remain visible; strict JSON
metrics report unavailable values with reasons. Cancelled/failed execution
does not return a fabricated completed archive.

Full 2D heat duty is W/m with no fabricated thickness or z-wall loss. Full 3D
is W before any application normalization. The optimizer divides 3D duty/mass
by actual Lz once at its boundary. Quick design is a prescribed-flow LTNE
model with prepared analytical inlet-pressure fractions, not a SIMPLE solve.
Its offline metrics need no EOS or calibration call. Screening retains its
own frozen-B/nonconvergence and unsupported-metric limits.

Separate processes use case.yaml + case.h5, results.h5, VTK views and
metrics.json. Exact contracts and mode-specific restrictions are in
`schemas/three_module_v1/`. Minimal postprocessing has a distinct dependency
lock and actual import/runtime checks; the full environment is not evidence
of minimal installation. Parallel run warnings and control state are local
to each invocation, and arrays crossing contracts are detached and immutable.

### Cooperative cancellation

Pipelines and solvers share `domain.cancellation.CancelledError`, an
`InterruptedError` subclass re-exported by `controllers.compute_pipeline`.
Only explicit cancellation checkpoints raise it; unrelated exceptions remain
errors even when a cancellation request is pending. Both SIMPLE workers are
joined before propagation, with real failures taking precedence over cancellation.
The GUI adapter maps this exception to the orchestrator's cancelled terminal state.

2D polls each SIMPLE iteration and at the existing LTNE chunk boundaries,
including the Richardson refined solve. 3D retains its 25-iteration SIMPLE
polling interval and LTNE chunk boundaries. The shared true-enthalpy driver
polls each property/sweep iteration. A native linear solve, JIT compilation,
LTNE chunk (2D defaults to 500 sweeps), or enthalpy property/sweep iteration
must finish before its next checkpoint; there is no forced thread termination
or fixed wall-time cancellation guarantee. Cancelled runs do not publish results.

### UI structure

- `ui/builders_canvas.py` assembles the visible geometry, result, and
  optimization workbench. `build_canvas_area()` only coordinates its named
  same-file builders.
- `ui/mixins/tab_view.py` owns workbench availability and routing, including
  the 2D/3D result switch. Hidden widgets are not used as navigation state.
- `ui/panel_vis_3d.py` owns the PyVista presentation. Its constructor delegates
  toolbar, controls, viewport, state, and timer setup to focused methods while
  rendering behavior stays in the same widget class.

## Physical invariants

These constraints protect demonstrated solver behavior. Change them only as an
explicit numerical-model change with directly relevant validation.

1. **Compressible air.** Air uses the ideal-gas density path. Do not replace it
   with a constant-density or isothermal shortcut.
2. **Porosity is split once.** Symmetric LTNE callers pass the full porosity;
   the energy solver forms the two half-porosity streams. For an offset
   isosurface, `models/asym_split.py` computes the upstream `eps_A`/`eps_B`
   split, whose sides sum to the full porosity, and the kernel does not halve
   those values again.
3. **Mass-flux inlet.** Compressible air uses the mass-flux inlet in both 2D
   and 3D. Solver velocities are interstitial, not superficial.
4. **Darcy-Forchheimer ownership.** `df_surrogate.predict_K_cF()` remains the
   pure geometry baseline: one water+sCO2 CFD table for both sides and every
   fluid. Base K0 and cF0 depend only on topology, L, and t, are bilinearly
   interpolated inside 4–8 mm by 0.3–0.6 mm, and never depend on Re or fluid.
   The UI exposes exactly two production methods. **CFD smooth-wall** is the
   default and is V2-compatible. **Experiment calibration** applies one fixed,
   reviewed effective correction per side after pipeline assembly and before
   pressure seeding/SIMPLE; K/cF stay fixed for the solve. The selector routes
   to a dataset whose campaign, boundary, pressure-drop definition, and
   geometry match the run. It is not evidence of fluid-intrinsic D-F physics.
   Differences may absorb pressure-tap location, contractions/expansions,
   manifolds/distribution regions, whole-HX losses, flow-area/channel-count
   definitions, instrument zero, and data reduction; these contributions are
   not separately modelled. Without a same-rig comparison they must not be
   attributed to fluid. The superseded `gamma_df` and `rbf` research modes
   are retired; selecting them explicitly now raises an error. Their code,
   tables and results remain available through the [history index](history/legacy-models.md).
5. **Nusselt ownership.** Air, water, and sCO2 coefficient tables live only in
   `models/nu_correlations.py`.
6. **Compressible envelope.** `models/envelope.py` rejects operating points
   without a steady subsonic solution. Do not bypass that result by widening a
   pressure clip or forcing a numerical answer.
7. **Pressure reference.** `P_ref_abs` is the outlet absolute pressure; the
   SIMPLE pressure field is gauge pressure relative to it.
8. **Units.** Prepared contract quantities use K, Pa and m. Legacy closure calls that
   accept cell size/wall thickness in mm receive an explicit boundary conversion;
   those internal units do not change persisted SI fields.
9. **Port boundary.** `ComputeConfig.validate()` normalizes both ports and
   calls the shared validator. 2D supports every ±x/±y direction; 3D also
   supports ±z, with both transverse extents validated against the correct
   domain axes. Non-opening exterior surfaces are stationary no-slip walls:
   tangential momentum has half-cell viscous wall flux, including z± in 3D;
   there is no volume wall penalty or post-solve velocity attenuation. 2D has
   no finite-thickness z term; Nz=1 3D momentum still has two z walls.
   Raw primary and staggered opening fractions come directly from the original
   rectangle on the final actual grid, never from averaged primary fractions.
   Positive raw overlap owns normal outlet flow and PPE support; taper remains
   a separate numerical profile. The inlet mass normalization and local outlet
   mass closure remain in force. Coarse bootstrap rebuilds the original ports,
   transfers inlet mass by physical open-area intersection, and reapplies the
   fine outlet support after prolongation; its budget and initial-guess role
   are unchanged. Richardson does not add a fine SIMPLE solve.
10. **True-enthalpy ownership.** Any ordered fluid pair containing sCO2 uses
    the conservative enthalpy kernel. It consumes SIMPLE's signed staggered
    face mass flows and computes duty from boundary enthalpy fluxes; it must
    not reconstruct a full-face x-flow from a scalar mass rate.
    Every sCO2 side in 2D/3D uses the shared property-wrapper range
    **280–700 K, 7.9–16 MPa absolute**, at inlets and actual local states.
    The 2026-09-09 pressure-floor extension leaves the EOS backend and the
    independent Nu/D-F applicability and acceptance gates unchanged; it does
    not establish experimental accuracy in the added range.
11. **Current V2 limit.** sCO2 zones and offset level sets remain rejected;
    air/water-only runs retain their existing temperature-form kernels.
    For Nz>1, those kernels solve every physical fluid and solid end control
    volume. Tin is imposed at the open inlet face with half-cell conduction;
    outlet zero-gradient applies at the external face. Explicit CC callers
    with SIMPLE supply actual inlet capacity transport while retaining the CC
    interior scheme. Prescribed B remains an external thermal reservoir.
12. **Experiment-correction applicability.** The air core-specimen branch uses
    L=6..8 mm, t=0.3..0.5 mm interpolation; t=0.6 uses the separate HX campaign.
    sCO2 uses only D/G-7-6 hot-side `ok_dp` evidence, keeps K=K0, and is
    HX-effective: uniform symmetric core, no zones, delta, other L/t, or
    independent cold-side fit. Its measured inlet-velocity windows are
    0.5827..2.5396 m/s (Diamond) and 0.6120..2.4705 m/s (Gyroid), corrected
    at absolute pressure for the same hot-side `ok_dp` members, measured mass
    flows and experimental flow areas. sF remains frozen at 6.313005350332494
    (Diamond) and 7.608907691857889 (Gyroid). The fitted
    D-F parameters are a porous-region
    closure and may be used with valid custom port centres, widths, and every
    solver-supported flow direction; only the full-face x-direction calibration
    boundary has direct experimental evidence. The
    water+air D/G-7-6 experiment consists of two complete, disconnected TPMS
    networks with
    full-face inlets and delta=0. Water and air therefore use the same
    topology-derived single-side flow area (D 5.94e-4 / G 6.50e-4 m²), with no
    28/34 channel-count scale or geometric-face shortcut. After excluding
    G/water case 1 (`dp_nonphysical`) and D/water cases 10/11
    (`duplicate_row`), the production water fit uses the declared high-flow
    window `u>=0.10 m/s`; this original calibration membership is unchanged. Fixed-K0 water RMSRE is 6.84% D / 0.93% G with sF 4.8928 / 4.1989.
    The measured upper bounds are 0.2541 / 0.2232 m/s. Matching HX-air uses its
    own sF 1.8024 / 2.0120 and measured velocity windows. `ComputeConfig`
    selects each side independently, allowing all nine ordered air/water/sCO2
    pairs and every valid 2D/3D flow direction. A mixed pair may therefore combine
    corrections from different campaigns; that is a model composition, not joint
    experimental validation of the pair. Each HX-effective side still requires its
    own velocity window, the matching 0.182 x 0.042 x 0.042 m domain, and delta=0.
    Custom inlet/outlet positions and sizes remain supported. Every active side
    must match its own applicability rules; there is no silent fallback.
    `hx_velocity_bounds()` retains original calibration/source-audit windows.
    `hx_application_velocity_bounds()` separately supplies the approved
    production windows (Diamond/Gyroid, m/s): water 0.0139648..0.254055 /
    0.0162341..0.225876; air 3.88324..22.7599 / 3.91282..24.5467; sCO2
    0.434925..2.53961 / 0.381408..2.47046. Full precision is in the selector.
    These windows cover reviewed 7/0.6 mm full-HX measured combinations and
    approved port validation, not arbitrary T/P/mdot combinations. Both ranges,
    actual inlet u and approved purpose are retained in correction metadata;
    leaving the calibration window emits a run-local side-specific warning
    through the existing cache/UI/export path. Water's lower-speed extension
    is substantial approved extrapolation; no coefficients are refitted.
    Each side applies its frozen sF exactly once before pressure seeding and
    SIMPLE, with K unchanged. Explicit CFD mode and independent Nu selection
    retain their defaults. D-F permission does not relax water-state, sCO2
    property-domain, nonfinite, numerical or energy guards.

## Extension points

- Add a fluid through `models/fluid_props.py`; keep its Nu implementation in
  `models/nu_correlations.py` and record its versioned resource and use it through the public module APIs.
- Add a user-facing configuration field to the `domain/compute_config.py`
  dataclasses first, then adapt it once at the UI boundary.
- Add a solver behavior behind an existing configuration boundary only when a
  current use case requires it. Do not introduce a factory or interface for a
  single implementation.
- Keep one production path per dimension. Validation code must call that path
  unless it is explicitly testing a lower-level kernel.

## Local data

Raw data is intentionally outside Git and is resolved relative to the
repository:

```text
data/raw_data/
├── experiments/{air,water_air,sco2}/
├── cfd/
│   ├── water/
│   ├── sco2/{Diamond,Gyroid}/
│   └── co2/{Diamond,Gyroid}/
└── plans/water/
```

Do not rename dataset directories without first updating the loader that names
that exact path. Generated reports must not become a second source of truth for
raw measurements.
The [data catalog](data-catalog.md) maps original filenames to this layout.
Workbook names also select the explicitly confirmed water pressure convention;
renaming them requires updating that registry and its caller tests together.

<a id="能力范围与未完成事项"></a>

# Capabilities and open work

[中文](capabilities.md) | [English](capabilities.en.md)

The GUI, CLI, and multi-condition optimizer share `prepare_case → run_case → evaluate`. The [result qualification table](architecture.md#result-qualification-by-route) defines convergence, metric availability, and optimization eligibility by route. [Model resources](model-resources.en.md) define experimental applicability. The [data catalog](data-catalog.en.md) records reference versions. Native desktop operation, headless CI, numerical conservation, and experimental accuracy require separate acceptance evidence.

The three-module Python mainline, M-A, is complete. The extension scope, M-B, stays incomplete. The original task graph contained 45 nodes: 37 complete, 7 planned, and 1 blocked by dependencies. These counts are a historical snapshot. The table includes later additions.

A local kernel integration does not complete an full extension node or change its acceptance conditions. The [fixed history index](history/README.en.md#2026-09-18-历史材料整理) keeps requirements, node states, reviews, and failure evidence. See [architecture](architecture.md) for current responsibilities and [schemas](../schemas/three_module_v1/README.md) for public file contracts.

| V0.1 requirement | Currently inspectable scope | Undelivered or awaiting acceptance |
| --- | --- | --- |
| Independent preprocessing, solving, and postprocessing | Three public APIs and CaseData/FieldResult. Real process separation and M-A acceptance after merge are complete. | No open M-A item in this row. External backends are listed separately. |
| Shared workflow and external callers | GUI/CLI, design, optimization, parameter/effective-field examples, and handoff acceptance after merge are complete. | External backends and property extensions still require their listed acceptance checks. |
| Python/Numba route | Actual complete 2D/3D models and Quick Design. | Numerical, energy, and experimental conclusions stay specific to each mode. Architecture acceptance does not show them. |
| Native C/C++ backend | Explicit `backend='cpp'` covers rectangular dual-fluid full 2D/3D and Quick Design. Independent C11 callers and native numerical CI comparisons pass on macOS/Python 3.13 and Windows/Python 3.12 and 3.13. Python/Numba stays the default. See [C++ scope](cpp-migration.md). | Visible macOS/Windows desktop acceptance, complete performance evaluation, default selection changes, and previous-path retirement require separate evidence. Local passes do not close X10/X11. |
| OpenFOAM adapter | Public physical data is isolated from backends. | X20/X21/X22 lack real solving, conversion, and cross-validation. |
| Other external backends | Public entry points accept Python and C++ within explicit capabilities. Other backends fail explicitly. | No other concrete external implementation. An interface declaration is not support. |
| Macroscopic and optional microscopic geometry | Fixed/zoned TPMS preparation and shared unit-cell geometry. | The macroscopic solver does not resolve real microscopic surfaces. An optional explicit microscopic mesh workflow is undelivered. |
| Mesh generation/import, boundaries, and materials | Orthogonal grids, Case file loading, actual openings, sides, directions, and design fields. | Arbitrary unstructured meshes and new formats are not directly solvable. |
| Experiment/CFD/DNS cleaning and fitting | Explicit offline entries, existing experiment/CFD reduction, and Nu/DF fitting. | The current water CFD workbook is missing. No independent DNS evidence exists. |
| Homogenized parameter calculation, reading, and interpolation | Case design fields, fixed geometry, versioned CFD tables, and independent model support. | Arbitrary directional homogenization models are not implemented. |
| Backend-independent homogenized intermediate layer | Public SI grid, physical fields, boundaries, and resource descriptions. C++ prepared inputs and FieldResult mappings keep the same contract. | OpenFOAM and general extension mappings require backend-specific acceptance. |
| Tensor representation preferred for directional parameters | Existing scalar/directional fields with explicit axis meaning. | General tensor contracts and anisotropic discretization stay under X30. |
| Properties separated from governing equations | Shared air, water, and sCO2 properties and correlations in models. | New providers need real integration. Persistent Cases cannot contain arbitrary callables. |
| Constant-property provider | Quick Design fixes evaluated properties within each thermal iteration pass. | This is not a general configurable constant-property provider. |
| Tabulated-property provider | Existing closure tables are not fluid-property tables. | No general fluid-property table adapter. |
| Fitted properties | A shared model supplies existing air/water formulas. | No general user-fit resource registration or cross-backend execution. |
| CoolProp / strongly variable sCO2 T-P properties | Actual state evaluation, enthalpy/property paths, and state checks. | Applicability, correlation evidence, and experimental Q acceptance keep separate limits. |
| REFPROP / user models | No runnable matching adapter. | X30 stays incomplete. License and runtime availability are not verified here. |
| Internal FVM responsibilities | Existing SIMPLE/LTNE, boundaries, discretization, and convergence kernels stay. | Python kernels do not show C++ or external backend equivalence. |
| Darcy→DF→anisotropy, LTE→LTNE | Existing DF/LTNE capabilities stay. | Each staged capability needs separate acceptance. Existing physics is not rewritten to fill a checklist. |
| Q/ΔP/Tout | Computed from native evidence, with units and support status defined by mode. | Undefined or unsupported evidence returns a reason, without invented metrics. |
| h/Re/Nu/f/PEC | Quick Design gives Re. Core models contain local closure inputs/outputs. | H30 must define h area/temperature difference, f convention, PEC reference, and required data. |
| Field loading, visualization, and reports | HDF5 loading, real per-field 2D/3D VTK loading, offline metrics, and GUI mapping. M-A handoff acceptance after merge is complete. | Extended engineering metrics still depend on H30 definitions and data. |
| YAML/HDF5/VTK/JSON | Formal implementations, layered IO, independent-process checks, and minimal-environment consumer verification are complete. | Skips and test scopes stay recorded. External format extensions need backend-specific acceptance. |
| Internal SI / schema_version | New persistent contracts use SI and schema versions. Previous leaf kernels have explicit mm adapters. | Full internal SI migration stays incomplete. X30 must migrate and verify each item. |
| pybind11, or C API where needed | Complete drivers use versioned C ABI and thin `ctypes` bindings. Full 2D uses ABI 2. Full 3D/Quick Design use ABI 1. Independent C callers check borrowed inputs, result ownership, cancellation, and errors. | Libraries, headers, and adapters must match. No pybind11 or unlisted capability is claimed. |
| Optimization changes only public design/homogenized fields | Supported Case design fields are inputs. Private matrices are not modified. | Broader tensors or arbitrary 3D fields need actual model support first. |
| First-stage gradient/adjoint reservation only | Unimplemented states are explicit. No invented gradients. | The original stage limit stays. Adjoint support is not claimed. |
| Extensible DOE/GA/PSO/NSGA-II/Bayesian/gradient/surrogate methods | Existing optimization applications use public APIs. | Unimplemented algorithms stay unsupported. Extensibility is a scope statement. |
| Tests, examples, and documentation | Layered tests, public-call examples, and this tracking table. | Directory or test counts cannot replace acceptance evidence. |

Unresolved H30 definitions block only their corresponding extended metrics. Do not invent an average h, friction-factor convention, or reference exchanger to fill values. H30, X10/X11, X20/X21/X22, X30, and Z10 track missing M-B work. Completion of M-A architecture does not show full V0.1 acceptance.

<a id="待完成节点"></a>

## Open nodes

| Node | State | Delivery and acceptance conditions |
| --- | --- | --- |
| H30 | planned | Define h/Re/Nu/f/PEC, area, temperature difference, friction-factor convention, reference basis, available inputs, and metric evidence. |
| X10 | implemented. Platform delivery awaits acceptance | C++ full 2D/3D and Quick Design independently consume public contracts. Visible desktop delivery, default selection changes, and consumer retirement stay required. |
| X11 | macOS/Windows native numerical CI comparison passed. Overall acceptance open | Keep complete field/state/physical comparisons at unchanged thresholds. Add visible desktop and required performance evidence before closure. |
| X20 | planned | Select an OpenFOAM distribution and define model/data mappings. |
| X21 | planned | Implement a real OpenFOAM solver adapter. |
| X22 | planned | Complete OpenFOAM cross-backend acceptance. |
| X30 | planned | Deliver remaining property providers, general tensors/models, and internal SI migration. Keep original optional, staged, and reserved scope. |
| Z10 | blocked | Requires implementation and acceptance for H30, X11, X22, X30, and their prerequisites X10, X20, X21. Z00 is complete. |

The C++ row records migration progress. Other extensions keep their planned states. History keeps the complete V0.1 requirements and detailed node acceptance rules. This summary cannot show delivery of all features. Historical B40 evidence keeps 4/4 failed locked tests, NaN, nonconvergence, and exit states.

Later authorized independent references do not convert those records into passes. Software and architecture tests do not replace experimental accuracy acceptance.
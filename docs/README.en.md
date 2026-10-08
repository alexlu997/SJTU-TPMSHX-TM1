<a id="仓库目录与文档导航"></a>

# Repository and document index

[中文](README.md) | [English](README.en.md)

The main application is in [sjtu_tpmshx](../sjtu_tpmshx/).
Start with the [module map](../sjtu_tpmshx/README.en.md) to read the code.
Use the [first run instructions](../README.en.md#first-run) to run the application.

<a id="当前文档"></a>

## Current documents

| Subject | Entry |
| --- | --- |
| Module responsibilities, data flow and physical constraints | [Architecture](architecture.md) |
| Complete Python/C++ backends, native ABI and builds | [C++ integration](cpp-migration.md) |
| macOS/Windows project folders and optional packaging | [Desktop operation](desktop.en.md) |
| CaseData, FieldResult, metrics and file transport | [Public data contract](../schemas/three_module_v1/README.md) |
| Delivered capabilities, unfinished M-B work and blockers | [Capabilities](capabilities.en.md) |
| Offline processing, effective sCO2 Nu and Shanghai air calibration | [Model resources](model-resources.en.md) |
| Data filenames, closed missing-data items and water Nu selection | [Data catalog](data-catalog.en.md) |
| Engineering, validation, research and performance tools | [Tool index](tools.en.md) |
| Numerical/experimental checks and directional-factor research limits | [Validation index](../sjtu_tpmshx/validation/README.en.md) |
| Current GUI, porosity and CI requirements | [OpenSpec specifications](../openspec/specs/) |
| Historical reports, task graphs, benchmarks and retired tools | [History index](history/README.en.md) |

<a id="根目录各自放什么"></a>

## Root directories

| Directory | Contents |
| --- | --- |
| [sjtu_tpmshx](../sjtu_tpmshx/) | Application source, shared models, active tests and validation tools. |
| [docs](./) | Current explanations and historical references. |
| [examples](../examples/) | Public API examples and first run configurations. |
| [scripts](../scripts/) | Test helpers, native dependency builds and model coefficient generation. |
| [sjtu_tpmshx/runs](../sjtu_tpmshx/runs/) | Current profiling, diagnostic and demonstration tools. |
| [schemas](../schemas/) | Public data contracts. Their implementations are in domain and io. |
| [openspec](../openspec/) | Current requirements grouped by function. |
| [.github](../.github/) | macOS/Windows CI and the minimal postprocessing check. |

`pyproject.toml`, `requirements*.txt` and `pytest.ini` define builds, dependencies and tests. `mypy-core-files.txt` selects public interfaces and data contracts for type checks. See [environment and checks](../README.en.md#环境与检查). `AGENTS.md` defines collaboration rules. `LICENSE` states the license.

`data-revision.txt` declares the associated data version. Raw experiment and CFD data stay in local `data/raw_data/`. Research scripts and results stay in ignored `.cache/`. Neither location is committed. The previous `reports/` output directory is also ignored.

Active tests use the one-dimensional enthalpy reference in [tests/enthalpy_1d_reference.py](../sjtu_tpmshx/tests/enthalpy_1d_reference.py).
Production CFD coefficient CSVs and MMS data used by tests stay.
Historical `golden_3d.json`, previous gamma snapshots, stage reports and task records are available through fixed Git history.
They are not current test resources or evidence of current accuracy.

M-A completion does not show M-B completion or experimental accuracy.
Keep the original B40 failures, frozen references and historical conclusions.

<a id="双语文档与术语"></a>

## Bilingual documents and terminology

Current usage, architecture, contract and specification documents have Chinese and English versions.
The existing path keeps its main language. Its companion uses `.en.md` or `.zh-CN.md`.
Each page gives language links.
Historical bodies, agent instructions and license texts keep their originals.
Historical indexes and current usage explanations have both languages.

English text follows the controlled-language rules of [ASD-STE100 Issue 9](https://www.asd-ste100.org/about_STE.html). Use one action per procedural sentence. Limit procedural sentences to 20 words and descriptive sentences to 25 words. Keep fixed spellings for code, fields, model names and the technical terms below. Chinese text keeps the structure and technical meaning.

Sentence-length checks support human semantic and technical review. They are not independent STE certification.

| English term | Chinese term | Meaning in TM1 |
| --- | --- | --- |
| solver backend | 求解后端 | The Python or C++ numerical implementation selected through RunControl. |
| prepared case | 准备态工况 | CaseData from preprocessing, with the actual grid and fixed physical inputs. |
| native evidence | 原生证据 | Fields, fluxes, pressure and status recorded during execution. |
| ABI | 二进制接口 | C structure layout, symbols, versions and memory ownership. |
| metric | 指标 | A derived quantity with a unit, definition version and availability status. |
| completed | 执行完成 | Execution returned a completed state. This does not show convergence. |
| converged | 已收敛 | The route passed its numerical and physical gates. |
| available | 可用 | The recorded evidence is sufficient to calculate the requested metric. This status does not show solver convergence. |
| engineering parity | 工程一致性 | Results meet specified error limits and independent physical gates with matching inputs and budgets. |
| numerical verification | 数值验证 | Checks of formulas, discretization, execution and conservation. |
| experimental validation | 实验验证 | Comparison with experimental observations within the declared scope. |
| qualification | 资格检查 | Required acceptance checks for a specified capability, platform and version. |
| replay | 重放 | Execution from a saved prepared case, or independent postprocessing from a saved result. |

The vocabulary review uses the word meanings and parts of speech in the
[official Issue 9 dictionary](https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf).
For example, use `check` as a noun and `do a check` for the action.
Use `keep` for the general meanings of `retain` and `preserve`.
Use `must` for mandatory requirements. Keep quoted interface labels and code identifiers unchanged.

These technical terms keep their mathematical, physical, or software meanings.
They are not general alternatives to approved dictionary words.

| Subject and word type | Technical terms | Meaning boundary |
| --- | --- | --- |
| Numerical and physical nouns | residual, accuracy, convergence, conservation, enthalpy, porosity, interpolation, boundary flux, pressure reference, finite-volume row | The quantities and methods defined in the architecture and model documents. Accuracy does not mean repeatability. |
| Software nouns | case, field, state, backend, ABI, callback, archive, metadata, cache, build, worker, trace, result owner | Objects and processes defined by the public contracts and current implementation. |
| Evidence nouns | original budget, native evidence, engineering parity, acceptance gate, qualification, experimental validation | The recorded reference, limits, and evidence for a specified version and scope. |
| Numerical verbs | solve, converge, discretize, interpolate, integrate, normalize, extrapolate, refine, fit, calibrate, clip, relax | The corresponding numerical operation. These terms do not imply that a physical result passed its acceptance gates. |
| Software verbs | build, compile, run, load, parse, serialize, deserialize, validate, allocate, release, cache, replay, export, import | The corresponding computer process. For example, a build creates a binary. It does not show numerical qualification. |

Do not translate field names or code literals.
For each change, compare defaults, units, limits, commands and current evidence in both languages.
Keep existing link entry points and referenced anchors.

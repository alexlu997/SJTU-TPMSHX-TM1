# SJTU-TPMSHX agent instructions

Develop TM1 as a stable engineering design tool. Reduce repeated user intervention
and rework through complete changes, clear decisions, and verified results.

## 1. Task scope and authority

- Complete the requested work and its necessary consequences. Follow the user's
  task limits, including read-only analysis, proposals, or instructions not to merge.
- For a broad goal, investigate first. Propose a direction and clear acceptance
  conditions. Wait for the user's direction before implementation.
  Once the direction is agreed, complete the work without approval at each step.
- For implementation tasks in this repository, the user gives agents standing
  authority to create branches, commit, push, and open PRs. This authority includes
  merge when the required review, tests, CI, and repository protection conditions pass.
  Do not request approval again for these actions or fixes to related CI failures.
  This authority stays valid until the user changes it.
- Record confirmed defects outside the current implementation task.
  After that task is complete, fix them in separate, scoped PRs under the same
  authority and acceptance conditions. Follow explicit analysis-only limits.
  Each follow-up covers a confirmed defect and its necessary consequences.
- Ask the user about unresolved decisions on physical validity, data requirements,
  or TM1 acceptance conditions.
- Changes to global instructions or skills do not reset task scope, valid
  authorization, existing evidence, or unresolved acceptance conditions.
  Keep all physical, data, environment, validation, and CI requirements.
  Repeat only checks that the change affects.

## 2. Project constraints

- Do not add fallbacks, compatibility layers, migrations, abstractions,
  dependencies, or defensive wrappers unless the task requires them.
- Do not add hash-, digest-, or checksum-based tests.
- Keep validation that protects physical correctness, data integrity, or a
  demonstrated failure mode. Keep the C++ numerical backend, Python application interfaces, and support for
  macOS arm64 and Windows x64. Python numerical execution was retired in 0.2.
- Read the existing model documents if physical scope or applicability is unclear.
  If a required physical decision is still missing, give evidence, options, and a recommendation.
  State the decision needed from the user.
  Pause only the work that depends on that decision. Unrelated authority does
  not resolve this pause.
- Keep raw experiment and CFD data in `data/raw_data/`. Do not commit local `data/`.
- Keep exploratory scripts and result reports in ignored `.cache/`.
  Do not commit or upload them. Keep production code, regression tests, and
  necessary usage and architecture documents under version control.
- Before a task writes to or cleans TM1 caches, check the primary checkout for
  `.agents/rules/tm1-local-data.md`. If it exists, protect the files it lists. Its combined cache limit applies across worktrees.
  Keep raw data, paper and GCI evidence, selected designs, and key failure samples.
  Follow the [storage retention rules](docs/collaboration.md#storage-retention)
  before the write or cleanup and at task closeout.

## 3. Work setup and environment

- Read [README.md](README.md) for setup. Before changes to solver, pipeline,
  closure, or data-loading code, read [docs/architecture.md](docs/architecture.md).
- Follow the [collaboration workflow](docs/collaboration.md) for task ownership
  and worktree setup. Use one owner, worktree, branch, and handoff record for each
  independent change task. Reuse them for continued work on that task.
  Read-only work does not need a new worktree. Keep one writer per file and
  one heavy numerical job per machine.
- Before you start a change task or a heavy numerical job, read the task status files.
  They are in `.cache/active-tasks/` of the primary checkout.
  Keep one status file for your task there until task closeout.
  A status file is not a cache write. Follow the [task status rules](docs/collaboration.md#task-status).
  Do not record task status in committed files such as `STATUS.md`.
- For project execution, use the absolute interpreter on the first line of
  `.venv-path` for Python, pip, smoke, and pytest commands.
  If this file, interpreter, or a required dependency is missing, stop dependent work.
  Restore the required task environment through the
  [recovery workflow](docs/collaboration.md#environment-recovery).
  Use that workflow's explicit interpreters for recovery and replacement validation.
  Do not silently use another environment for project execution.
- Run project modules from the current repository root so `sjtu_tpmshx` loads
  from the current checkout. In source worktrees, use `python -m sjtu_tpmshx.cli`.
  Do not use the installed-only `tpmshx-run` command there.
- For Matplotlib, Qt smoke, and pytest commands, set `MPLCONFIGDIR` and
  `XDG_CACHE_HOME` to ignored `.cache/` paths in the current worktree.
- Keep shared environments outside task worktrees. Install only dependencies
  from `engineering/requirements/base.txt`, not `requirements.txt`, in a shared base environment.
  Use the applicable separate lock for other environment purposes.
  Do not install this project into a shared environment in editable mode.
  Keep one accepted environment per active role: base, BO, and minimal postprocessing.
- Before the first environment-dependent work in a task, run
  `python -m sjtu_tpmshx.development.runs.tools.check_locked_environment` with the applicable lock.
  Then run `python -m pip check`. The lock checker ignores the pip version.
  Reuse passing results only while the interpreter, applicable lock, and installed
  dependencies stay unchanged. Repeat both checks after these inputs change or
  an environment-related failure occurs.
- If either environment check fails, stop environment-dependent work.
  Recovery commands and independent static work can continue during this pause.
  Do not bypass either check. Resume dependent work only after both and the
  relevant recovery checks pass.
  Other pause conditions stay in force.
- The user authorizes automatic recovery of environments needed for an agreed task.
  Do not request approval again. Follow the
  [recovery workflow](docs/collaboration.md#environment-recovery) for each recovery.
- Do not rebuild a shared environment while another project Python process uses it.
  A change to a shared environment affects every worktree that uses it.
- Server launch scripts can synchronize code and data.
  They must use their fixed, pre-provisioned interpreter.
  They must not install or upgrade packages.

## 4. Code changes and validation

- Organize modules by responsibility. Give shared rules and mutable state clear owners.
  Use explicit inputs, outputs, and interfaces between modules.
  Do not split or combine code based only on file length or repeated lines.
- Keep GUI code in `python/applications/gui/ui/` and `python/applications/gui/controllers/`.
  Keep lower layers free of Qt.
  Keep application workflows in `python/applications/`. Put C++ preparation, solving, and evaluation in root `preprocess/`, `solver/`, and `postprocess/`.
  Put geometry in `geometry/`, common numerical functions in `numerics/`, and C/C++ headers in `include/tpmshx/`.
  Keep native caller tests in `tests/cpp/`.
  Keep portable types in `python/data_types/`, models in `python/physical_models/`, and resources in `python/model_configs/`.
  Keep file I/O in `python/file_io/`, controls in `python/run_control/`, and native calls in `python/cpp_interface/`.
  Keep Python tests in `tests/python/`. Keep validation and tools in `python/development/`.
  Keep build scripts, packaging and dependency locks in root `engineering/`.
  Do not duplicate correlations or physical constants between these layers.
- Python stage packages produce the public stage data. The types stay in `python/data_types/`.
  Produce new `CaseData` in `python/preprocess/`, new `FieldResult` in `python/solvers/`,
  and new `PerformanceResult` and `MetricValue` in `python/postprocess/`.
  `python/file_io/` can restore saved stage data.
  Other modules can copy stage data with changed metadata.
  Keep the internal steps of each stage in its stage package.
  Each stage gives its native binding the model caches and the warning, progress, and cancellation callbacks that the binding uses.
  Keep standalone model queries and their caches in `python/physical_models/`.
- Keep native image loading, C signatures, input packing, C callbacks, status translation, and resource release
  in `python/cpp_interface/`. Keep each callback and its input storage alive during the native call.
  Before native release, copy or detach each output that stays in use after release.
  A binding can import `run_control`, `model_configs`, and `data_types` modules other than the modules of the stage data types.
  A binding does not import or build the stage data types
  (`CaseData`, `ModelRef`, `FieldResult`, `MetricSpec`, `MetricValue`, `PerformanceResult`).
  A binding can import them under `TYPE_CHECKING`.
  The exception is `python/cpp_interface/preparation_host.py`, which imports `ModelRef` to check a saved model reference.
  Do not import stage, application, physical-model, file I/O, `compute`, or development modules in `python/cpp_interface/`.
  `python -m sjtu_tpmshx.development.runs.tools.audit_import_graph --fail-on-violations` checks these imports.
- Reuse an existing rule when its meaning and required behavior match.
  Keep small duplication when sharing would combine different contracts.
  Preserve independent test references and physical checks.
- Before implementation, trace the consumers that the change can reach along the actual call chain.
  Include callers, tests, fixtures, configuration, saved files, exports, packaging, examples,
  GUI and CLI labels, documentation, comments, and docstrings.
  Complete necessary updates to these items in the same change.
- A change to behavior, interfaces, defaults, units, limits, commands, or file formats is a contract change.
  It requires a check of related current text, including Markdown, TXT, and other relevant text files.
- Record related changes in the PR description. Update the record when you find new effects.
  If the change alters no contract, write one sentence that says so. Do not list unchanged items.
  For a contract change, record the affected contracts, updates, checks, and open items.
  Name the check that covers a consumer. A check covers a consumer only when it compares
  that consumer with the changed contract. Give a reason for an unchanged consumer only when
  the reason is not obvious or no check covers that consumer.
  Use one sentence for consumers that share a reason.
- Resolve conflicts between code and text against confirmed requirements, public contracts, and validation evidence.
  Do not change documentation merely to accept an implementation defect.
  Ask the user when a physical or acceptance decision remains unresolved.
- For a replacement or a removal of code, define its retirement scope before implementation.
  Remove the replaced implementation and its exclusive files in the same PR.
  Follow the [retirement workflow](docs/collaboration.md#complete-code-retirement).
- Run existing tests relevant to the changed files. Add tests for meaningful
  behavior changes or demonstrated failures. Run broader numerical validation only when
  solver, closure, or pipeline behavior changes.
- Record the tested commit, results, and unresolved acceptance conditions.
  Repeat or expand checks only for new changes, failures, or unresolved concerns.
  Complete all necessary validation, including long calculations, under the agreed task authority.

## 5. PR, merge, and handoff

- Before delivery of an implementation task, start one independent review of the
  latest task commit without a user reminder. Use the same model in a new context
  without the author's chat history. Use at most three review rounds for the task.
  After three rounds, report unresolved substantive findings to the user with
  evidence and options.
- A PR that only corrects spelling, links, or formatting in documents needs no
  independent review. It must not change the meaning of a rule, command, or contract.
  `engineering/scripts/check_docs.py` must pass. State this reason in the PR.
- Do not deliver if the required review or required evidence is incomplete, or if a
  blocking finding is unresolved.
- Follow the [review and delivery workflow](docs/collaboration.md#synchronize-and-review)
  for review coverage, synchronization with `origin/main`, CI, merge, and the
  primary checkout update. That workflow names who does each step.
  Wait for required CI on the latest PR commit and on the resulting `main` commit.
- Keep PR CI, merged-main CI, desktop acceptance, and experimental validation
  as separate results.
- Before worktree or runtime removal, keep ignored evidence outside the removal set.
  Follow the [archive and removal checks](docs/collaboration.md#archive-and-remove).
- Report important changes, failures, and decisions that need the user.
  Keep the final report short: result, key checks, and unfinished work.
  Link detailed evidence. Explain it further when the user asks.

## 6. Technical writing

- Use ASD-STE100 Issue 9 for English technical text. This includes documents,
  agent instructions, comments, docstrings, user-facing explanations, commit
  messages, and PR text.
- Follow the [writing rules and terminology](docs/README.en.md#双语文档与术语).
  Write new or changed comments and docstrings in English. Keep comments short.
  Explain reasons that the code does not show.
- Apply these rules to new and changed text. Revise existing text when related
  work touches it. A rewrite of other existing text needs a separate task.
- Keep Chinese documents consistent with their English companions in structure,
  technical meaning, and terminology. STE is an English standard.
- Keep identifiers, commands, formulas, units, external quotations, and license
  text unchanged during language edits.
- Review word meanings, parts of speech, sentences, and technical terms.
  Use sentence-length checks to support that review, not as proof of STE certification.
- Current instructions and explanations must describe supported behavior.
  Mark historical descriptions with their version or date.
  Keep original results, failure records, external quotations, and license text unchanged.
  Link historical material when current text needs it.

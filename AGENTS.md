# SJTU-TPMSHX agent instructions

Develop TM1 as a stable engineering design tool with complete changes, clear decisions, and tested results.
Codex, Claude, and Antigravity use these rules. The [collaboration guide](docs/collaboration.md) has the procedures.

## 1. Task scope and authority

- Follow the user's task limits. A request for analysis or a proposal gives authority for that work only.
- For a broad goal, investigate first. Propose a direction and acceptance conditions. Wait for the user's
  direction. Then complete the agreed work without approval at each step.
- Before a large refactor or a change of the agreed approach, write a plan. Wait for user approval.
- For implementation tasks, the user gives standing authority for branches, commits, pushes, PRs, and related
  CI fixes. It includes merge under [section 5](#5-review-and-delivery). It stays valid until the user changes it.
- Ask the user before you delete or overwrite a file outside the task's own changes. A bulk delete of files,
  branches, or worktrees needs an exact list that the user approved. Do not select by pattern, age, or directory.
- During an implementation task, record each defect that you find outside its scope, with evidence. After
  delivery, fix each one in a separate PR. A read-only task only reports its findings.
- A change of owner, tool, or instructions does not reset task scope, authority, evidence, or open acceptance
  conditions. Repeat only the checks that the change affects.

## 2. Engineering and data requirements

- Keep the C++ numerical backend and the Python application interfaces. Full computation and the GUI run on
  macOS arm64 and Windows x64. Linux x86_64 runs independent result evaluation.
- If physical scope is unclear, read the model documents. For an open physical, data, or acceptance decision,
  give the user evidence, options, and a recommendation. Pause only the dependent work.
- The user is the only developer and the only user of TM1. Old app versions and old saved files need no
  support unless the user asks for it. A file-format change is a contract change.
- Do not add fallbacks, compatibility layers, migrations, defensive wrappers, or speculative abstractions
  unless the user asks for them. Add a dependency only when the task needs it. Keep validation that protects
  physical correctness, data integrity, or a demonstrated failure mode.
- Keep production code, regression tests, and necessary usage and architecture documents in Git. Keep raw
  experiment and CFD data in `data/raw_data/` and exploratory scripts and reports in ignored `.cache/`.
- Do not commit or upload local `data/` or `.cache/` content to the public TM1 repository. Before a data write
  to TM1 caches or a cache cleanup, protect the files in `.agents/rules/tm1-local-data.md` of the primary
  checkout. Follow that file for private backups and the [storage rules](docs/collaboration.md#storage-retention).

## 3. Work setup and environment

- Read [README.md](README.md) for setup. Before a change to solver, pipeline, closure, or data-loading code,
  read [docs/architecture.md](docs/architecture.md).
- Use one owner, worktree, branch, and write scope for each change task. Keep one writer for each file. Follow
  [task setup](docs/collaboration.md#start-a-task) and [multi-agent work](docs/collaboration.md#multi-agent-work).
- Before a change task or a heavy job, read the [task status](docs/collaboration.md#task-status) files in the
  primary checkout. Keep your status file there until closeout. Run one heavy job at a time on each machine.
- Use the absolute interpreter on the first line of `.venv-path` for Python, pip, smoke, and pytest commands.
  Run project modules from the current repository root with `python -m`.
- Before environment-dependent work, run the lock check with the applicable lock, then `python -m pip check`:
  `python -m sjtu_tpmshx.development.runs.tools.check_locked_environment <lock>`.
- If `.venv-path`, the interpreter, or a dependency is missing, or a check fails, stop dependent work. Do not
  bypass the check. The task authority includes [environment recovery](docs/collaboration.md#environment-recovery).

## 4. Code and checks

- Organize modules by responsibility, with clear owners and explicit interfaces, not by file length.
  [Directory owners](docs/architecture.md#directory-owners) gives the location of each layer. Do not duplicate
  correlations or physical constants between layers. Keep independent test references and physical checks.
- Keep Qt in `python/applications/gui/` (`ui/`, `controllers/`, `main.py`) and `python/desktop.py` only.
- Stage packages produce new stage data: `python/preprocess/` `CaseData`, `python/solvers/` `FieldResult`,
  and `python/postprocess/` `PerformanceResult` and `MetricValue`. The types stay in `python/data_types/`.
  `python/file_io/` can restore stage data. Other modules can copy it with changed metadata.
- Each stage keeps its internal steps in its package. It gives its binding the model caches and the warning,
  progress, and cancellation callbacks that the binding uses. Standalone model queries and their caches
  stay in `python/physical_models/`.
- `python/cpp_interface/` owns native image loading, C signatures, input packing, C callbacks, status
  translation, and resource release. Keep each callback and its input storage alive during the native call.
  Before native release, copy or detach each output that stays in use after release.
- Bindings can import `run_control`, `model_configs`, and `data_types` modules. They import stage data type
  modules only under `TYPE_CHECKING` and do not build these types: `CaseData`, `ModelRef`, `FieldResult`,
  `MetricSpec`, `MetricValue`, and `PerformanceResult`. The exception is `preparation_host.py`, which imports
  `ModelRef` for the check of a saved model reference. Bindings do not import stage, application,
  physical-model, file I/O, `compute`, or development modules. After an import change, run
  `python -m sjtu_tpmshx.development.runs.tools.audit_import_graph --fail-on-violations`.
- Before implementation, trace the consumers that the change can reach along the actual call chain. Update
  them in the same change. Write the [related-change record](docs/collaboration.md#related-change-record).
- Resolve conflicts between code and text against approved requirements, public contracts, and validation
  evidence. Do not change documentation to accept an implementation defect.
- For a replacement or a removal, remove the replaced code and its exclusive files in the same PR
  ([retirement workflow](docs/collaboration.md#complete-code-retirement)).
- Run the existing tests for the changed files. If no check covers a found defect or a contract change, add
  a minimal regression test. Prefer a few mapping checks. Do not add hash-, digest-, or checksum-based tests.
- Run broader numerical validation only when solver, closure, or pipeline behavior changes. Complete necessary
  long calculations. Record the tested commit, results, and open acceptance conditions.

## 5. Review and delivery

- Before delivery, get the [independent review](docs/collaboration.md#independent-review) of the latest task
  commit without a user reminder. Each reviewer uses a fresh context without the author's chat.
- Some changes need a reviewer of a different model. These are changes to physical meaning, numerical results,
  units, file formats, public interfaces and the C ABI, platform behavior, or project rules. Other work uses
  the independent reviewer with the shorter queue. Architecture plans and agent-rule changes need two reviewers
  of different models.
- Use at most three review rounds. Then report open findings to the user with evidence and options. A fourth
  round needs user approval for a named finding and commit range.
- A PR that only corrects spelling, links, or formatting in documents and keeps their meaning needs no review.
  `engineering/scripts/check_docs.py` must pass.
- Do not deliver if the review or the necessary evidence is incomplete, or a blocking finding is open. Follow
  the [delivery workflow](docs/collaboration.md#synchronize-and-review). Merge one PR at a time. Do not force-push.
- Wait for the necessary CI on the latest PR commit and on the resulting `main` commit. Report PR CI,
  merged-main CI, desktop acceptance, and experimental validation as separate results.
- Before a worktree or environment removal, do the [archive checks](docs/collaboration.md#archive-and-remove).
- Keep the final report short: result, key checks, unfinished work, and decisions that need the user.

## 6. Language

- Write to the user in Chinese. Write GUI text in Chinese.
- Use ASD-STE100 Issue 9 for English technical text, including comments and docstrings. Follow the
  [writing rules and terms](docs/README.en.md#双语文档与术语). Keep Chinese companions consistent.
- Current text describes supported behavior. Mark historical text with its version or date. Keep original
  results, failure records, external quotations, and license text unchanged.

# SJTU-TPMSHX agent instructions

Develop TM1 as a stable engineering design tool. Reduce repeated user intervention and rework through
complete changes, clear decisions, and confirmed results. Codex, Claude, and Antigravity use these
rules. The [collaboration guide](docs/collaboration.md) gives the procedures.

## 1. Task scope and authority

- Follow the user's task limits. A request for analysis or a proposal gives authority for that work only.
- For a broad goal, investigate first. Propose a direction and acceptance conditions. Wait for the
  user's direction. Then complete the agreed work without approval at each step.
- Before a large refactor or a change of the agreed approach, write a plan. Wait for user approval.
- For implementation tasks, the user gives standing authority to create branches, commit, push, open
  PRs, fix related CI failures, and merge under [section 5](#5-review-and-delivery). This authority
  stays valid until the user changes it.
- Ask the user before you delete or overwrite a file outside the task's own changes. For a bulk delete
  of files, branches, or worktrees, use an exact list that the user approved. Do not select by
  pattern, age, or directory.
- Record confirmed defects outside the current task. After delivery, fix each one in a separate PR.
- A change of owner, tool, or instructions does not reset task scope, authority, evidence, or open
  acceptance conditions. Repeat only the checks that the change affects.

## 2. Engineering and data requirements

- Keep the C++ numerical backend and the Python application interfaces. Full computation and the GUI
  run on macOS arm64 and Windows x64. Linux x86_64 runs independent result evaluation.
- If physical scope is unclear, read the model documents. For an open physical, data, or acceptance
  decision, give the user evidence, options, and a recommendation. Pause only the dependent work.
- The user is the only developer and the only user of TM1. Old app versions and old saved files need
  no support unless the user asks for it. A file-format change is a contract change.
- Do not add fallbacks, compatibility layers, migrations, defensive wrappers, or speculative
  abstractions unless the user asks for them. Add a dependency only when the task needs it. Keep
  validation that protects physical correctness, data integrity, or a demonstrated failure mode.
- Keep raw experiment and CFD data in `data/raw_data/`. Keep exploratory scripts and result reports in
  ignored `.cache/`. Do not commit or upload local `data/` or `.cache/` content.
- Before a data write to TM1 caches or a cache cleanup, protect the files that the primary checkout's
  `.agents/rules/tm1-local-data.md` lists, if it exists. Follow the
  [storage rules](docs/collaboration.md#storage-retention).

## 3. Work setup and environment

- Read [README.md](README.md) for setup. Before a change to solver, pipeline, closure, or data-loading
  code, read [docs/architecture.md](docs/architecture.md).
- Use one owner, worktree, branch, and write scope for each change task. Keep one writer for each file.
  Follow [task setup](docs/collaboration.md#start-a-task) and
  [multi-agent work](docs/collaboration.md#multi-agent-work).
- Before a change task or a heavy job, read the status files in `.cache/active-tasks/` of the primary
  checkout. Keep your [task status](docs/collaboration.md#task-status) file there until task closeout.
- Run one heavy job at a time on each machine. Start a heavy job only after the coordinator grants it.
- Use the absolute interpreter on the first line of `.venv-path` for Python, pip, smoke, and pytest
  commands. Run project modules from the current repository root. In a source worktree, use
  `python -m sjtu_tpmshx.cli`, not `tpmshx-run`. Set `MPLCONFIGDIR` and `XDG_CACHE_HOME` to ignored
  `.cache/` paths in the worktree.
- Before environment-dependent work, run
  `python -m sjtu_tpmshx.development.runs.tools.check_locked_environment` with the applicable lock.
  Then run `python -m pip check`. Repeat both after a change to the interpreter, the lock, or the
  installed dependencies, or after an environment failure.
- If `.venv-path`, the interpreter, or a dependency is missing, or a check fails, stop dependent work.
  Do not bypass the check. The task authority includes the
  [environment recovery](docs/collaboration.md#environment-recovery).

## 4. Code and checks

- Organize modules by responsibility, with clear owners and explicit interfaces, not by file length.
  [Directory owners](docs/architecture.md#directory-owners) gives the location of each layer.
- Do not duplicate correlations or physical constants between layers. Keep small duplication when
  sharing would combine different contracts. Keep independent test references and physical checks.
- Keep Qt in `python/applications/gui/ui/`, `python/applications/gui/controllers/`, and the GUI
  entries `python/applications/gui/main.py` and `python/desktop.py`. Keep lower layers free of Qt.
- The stage data types stay in `python/data_types/`. `python/preprocess/` produces new `CaseData`,
  `python/solvers/` produces new `FieldResult`, and `python/postprocess/` produces new
  `PerformanceResult` and `MetricValue`. `python/file_io/` can restore saved stage data. Other modules
  can copy stage data with changed metadata. Each stage keeps its internal steps in its package.
- Each stage gives its native binding the model caches and the warning, progress, and cancellation
  callbacks that the binding uses. Keep standalone model queries and their caches in `physical_models/`.
- Keep native image loading, C signatures, input packing, C callbacks, status translation, and resource
  release in `python/cpp_interface/`. Keep each callback and its input storage alive during the native
  call. Before native release, copy or detach each output that stays in use after release.
- A binding can import `run_control`, `model_configs`, and `data_types` modules, but not the modules
  of the stage data types (`CaseData`, `ModelRef`, `FieldResult`, `MetricSpec`, `MetricValue`,
  `PerformanceResult`). A binding does not build these types and imports them only under
  `TYPE_CHECKING`. The exception is `python/cpp_interface/preparation_host.py`, which imports
  `ModelRef` for the check of a saved model reference. Bindings do not import stage, application,
  physical-model, file I/O, `compute`, or development modules. After an import change, run
  `python -m sjtu_tpmshx.development.runs.tools.audit_import_graph --fail-on-violations`.
- Before implementation, trace the consumers that the change can reach along the actual call chain.
  Update them in the same change. Write the [related-change record](docs/collaboration.md#related-change-record).
- Resolve conflicts between code and text against confirmed requirements, public contracts, and
  validation evidence. Do not change documentation to accept an implementation defect.
- For a replacement or a removal, remove the replaced code and its exclusive files in the same PR.
  Follow the [retirement workflow](docs/collaboration.md#complete-code-retirement).
- Run the existing tests for the changed files. Add a test only for a fixed defect or a changed
  contract. Use a few mapping checks. Do not add hash-, digest-, or checksum-based tests.
  Follow the [test scope](docs/collaboration.md#test-scope).
- Run broader numerical validation only when solver, closure, or pipeline behavior changes. Complete
  necessary long calculations. Record the tested commit, results, and open acceptance conditions.

## 5. Review and delivery

- Before delivery, get one [independent review](docs/collaboration.md#independent-review) of the
  latest task commit without a user reminder. The reviewer has a fresh context without the author's chat.
- Some changes need a reviewer of a different model. These are changes to physical meaning, numerical
  results, units, file formats, public interfaces and the C ABI, platform behavior, or project rules.
  For other work, use the independent reviewer with the shorter queue. Use two reviewers for architecture plans and
  agent-rule changes.
- Use at most three review rounds for each task. Then report open findings to the user with evidence
  and options. A fourth round needs user approval for a named finding and commit range.
- A PR that only corrects spelling, links, or formatting in documents and keeps their meaning needs no
  review. `engineering/scripts/check_docs.py` must pass. State this reason in the PR.
- Do not deliver if the review or the necessary evidence is incomplete, or a blocking finding is open.
  Follow the [delivery workflow](docs/collaboration.md#synchronize-and-review). Merge one PR at a time
  when the review, tests, CI, and repository protection conditions pass. Do not force-push.
- Wait for the necessary CI on the latest PR commit and on the resulting `main` commit. Report PR CI,
  merged-main CI, desktop acceptance, and experimental validation as separate results.
- Before you remove a worktree or an environment, do the
  [archive and removal checks](docs/collaboration.md#archive-and-remove).
- Keep the final report short: result, key checks, unfinished work, and decisions that need the user.

## 6. Language

- Write to the user in Chinese. Write GUI text in Chinese.
- Use ASD-STE100 Issue 9 for English technical text, including documents, agent instructions,
  comments, docstrings, commit messages, and PR text. Follow the
  [writing rules and terms](docs/README.en.md#双语文档与术语).
- Write new or changed comments and docstrings in English. Keep them short. Explain reasons that the
  code does not show.
- Keep Chinese documents consistent with their English companions in structure, meaning, and terms.
- Current text describes supported behavior. Mark historical text with its version or date. Keep
  original results, failure records, external quotations, and license text unchanged.

# SJTU-TPMSHX agent instructions

## 1. Task scope and authority

- Complete the requested work and its necessary consequences. Follow the user's
  task limits, including read-only analysis, proposals, or instructions not to merge.
- For implementation tasks in this repository, the user gives agents standing
  authority to create branches, commit, push, and open PRs. This authority includes
  merge when the required review, tests, CI, and repository protection conditions pass.
  Do not request approval again for these actions or fixes to related CI failures.
  This authority stays valid until the user changes it.
- Ask the user about gaps in requirements, scope, or authority that existing
  instructions do not resolve. Continue independent work within scope.
- Changes to global instructions or skills do not reset task scope, valid
  authorization, existing evidence, or unresolved acceptance conditions.
  Keep all physical, data, environment, validation, and CI requirements.
  Repeat only checks that the change affects.

## 2. Project constraints

- Do not add fallbacks, compatibility layers, migrations, abstractions,
  dependencies, or defensive wrappers unless the task requires them.
- Do not add hash-, digest-, or checksum-based tests.
- Keep validation that protects physical correctness, data integrity, or a
  demonstrated failure mode. Keep the Python and C++ backends and support for
  macOS arm64 and Windows x64.
- Read the existing model documents if physical scope or applicability is unclear.
  If a required physical decision is still missing, ask the user.
  Pause only the work that depends on that decision. Unrelated authority does
  not resolve this pause.
- Keep raw experiment and CFD data in `data/raw_data/`. Do not commit local `data/`.
- Keep exploratory scripts and result reports in ignored `.cache/`.
  Do not commit or upload them. Keep production code, regression tests, and
  necessary usage and architecture documents under version control.

## 3. Work setup and environment

- Read [README.md](README.md) for setup. Before changes to solver, pipeline,
  closure, or data-loading code, read [docs/architecture.md](docs/architecture.md).
- Follow the [collaboration workflow](docs/collaboration.md) for task ownership
  and worktree setup. Use one owner, worktree, branch, and handoff record for each
  independent change task. Reuse them for continued work on that task.
  Read-only work does not need a new worktree. Keep one writer per file and
  one heavy numerical job per machine.
- Use the absolute interpreter on the first line of `.venv-path` for every
  Python, pip, smoke, and pytest command. If this file, interpreter, or a required
  dependency is missing, stop environment-dependent work. Report the problem.
  Do not use another environment or repair it automatically.
- Run project modules from the current repository root so `sjtu_tpmshx` loads
  from the current checkout. In source worktrees, use `python -m sjtu_tpmshx.cli`.
  Do not use the installed-only `tpmshx-run` command there.
- For Matplotlib, Qt smoke, and pytest commands, set `MPLCONFIGDIR` and
  `XDG_CACHE_HOME` to ignored `.cache/` paths in the current worktree.
- Keep shared environments outside task worktrees. Install only dependencies
  from `requirements-lock.txt`, not `requirements.txt`, in a shared base environment.
  Use the applicable separate lock for other environment purposes.
  Do not install this project into a shared environment in editable mode.
- Before the first environment-dependent work in a task, run
  `python -m sjtu_tpmshx.runs.tools.check_locked_environment` with the applicable lock.
  Then run `python -m pip check`. The lock checker ignores the pip version.
  Reuse passing results only while the interpreter, applicable lock, and installed
  dependencies stay unchanged. Repeat both checks after these inputs change or
  an environment-related failure occurs.
- If either environment check fails, stop environment-dependent work.
  Only independent static work can continue during this pause.
  Do not bypass either check. Resume dependent work only after both pass.
  Other pause conditions stay in force.
- Do not create, upgrade, or reinstall an environment or dependency without
  an explicit user request. For a requested dependency change, update
  `pyproject.toml` and the applicable lock in the same change.
  Do not change the shared environment as part of a code change.
  Report the need for an explicitly requested rebuild and prewarm.
- Do not rebuild a shared environment while another project Python process uses it.
  All worktrees on that machine use the replacement immediately.
- Server launch scripts can synchronize code and data.
  They must use their fixed, pre-provisioned interpreter.
  They must not install or upgrade packages.

## 4. Code changes and validation

- Keep GUI code in `ui/` and `controllers/`. Keep lower layers free of Qt.
- Use `pipelines/` for orchestration and `solvers/` for numerical implementation.
  Do not duplicate correlations or physical constants between these layers.
- Update affected callers, tests, fixtures, configuration, and exports as part
  of the change.
- Run existing tests relevant to the changed files. Add tests for meaningful
  behavior changes or demonstrated failures. Run broader numerical validation only when
  solver, closure, or pipeline behavior changes.
- Record the tested commit, results, and unresolved acceptance conditions.
  Repeat or expand checks only for new changes, failures, or unresolved concerns.

## 5. PR, merge, and handoff

- Follow the [review and delivery workflow](docs/collaboration.md#synchronize-and-review).
  Complete the relevant checks. Commit the task changes.
  Review the latest task commit.
  Keep the review result current after each revision.
- Push the task branch. Open or update the PR with
  its scope, evidence, and unresolved acceptance conditions.
- Wait for required CI on the latest PR commit. Fix related failures within
  the task authority. Keep the branch current with `origin/main` as the workflow
  requires. Do not force-push or bypass repository protection.
- When the required review, checks, and protection conditions pass, merge the PR.
  Confirm the remote merge commit. Wait for required CI on the resulting `main` commit.
- After required CI passes, fast-forward the clean primary checkout to that commit.
  Update the handoff record. Keep PR CI, merged-main CI, desktop acceptance,
  and experimental validation as separate results.
- Before worktree or runtime removal, keep ignored evidence outside the removal set.
  Confirm its recovery. Follow the workflow's archive and removal checks.

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

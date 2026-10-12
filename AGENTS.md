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
  If a required physical decision is still missing, give evidence, options, and a recommendation.
  State the decision needed from the user.
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
  Recovery commands and independent static work can continue during this pause.
  Do not bypass either check. Resume dependent work only after both and the
  relevant recovery checks pass.
  Other pause conditions stay in force.
- The user authorizes automatic recovery of environments needed for an agreed task.
  Explain the impact and recovery method before changes. Do not request approval again.
  Use the existing applicable lock. Keep the original environment and pointer when available.
  Create replacements at their final locations outside task worktrees.
  A dependency version change requires a scoped change to `pyproject.toml` and
  the applicable lock. Validate and prewarm its replacement environment before use.
- Do not rebuild a shared environment while another project Python process uses it.
  A change to a shared environment affects every worktree that uses it.
- Server launch scripts can synchronize code and data.
  They must use their fixed, pre-provisioned interpreter.
  They must not install or upgrade packages.

## 4. Code changes and validation

- Keep GUI code in `ui/` and `controllers/`. Keep lower layers free of Qt.
- Keep workflow orchestration separate from numerical implementation in `solvers/`.
  Do not duplicate correlations or physical constants between these layers.
- Update affected callers, tests, fixtures, configuration, and exports as part
  of the change.
- For a replacement, define its retirement scope before implementation.
  Follow the [retirement workflow](docs/collaboration.md#complete-code-retirement).
  Migrate callers and regression coverage. Remove the replaced implementation
  and its exclusive files in the same PR. Use Git history for previous code.
- Check actual consumers, entry points, packaging, and replacement evidence before removal.
  Names such as `legacy` or `old` do not prove that code is unused.
  For each retained item, record its consumer, reason, and removal condition.
  Keep the retirement state incomplete until its required removals and checks pass.
- Run existing tests relevant to the changed files. Add tests for meaningful
  behavior changes or demonstrated failures. Run broader numerical validation only when
  solver, closure, or pipeline behavior changes.
- Record the tested commit, results, and unresolved acceptance conditions.
  Repeat or expand checks only for new changes, failures, or unresolved concerns.
  Complete all necessary validation, including long calculations, under the agreed task authority.

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

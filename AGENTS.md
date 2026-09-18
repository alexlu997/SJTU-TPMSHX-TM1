# SJTU-TPMSHX agent instructions

Read [README.md](README.md) for setup and [docs/architecture.md](docs/architecture.md)
before changing solver, pipeline, closure, or data-loading code.

## Scope discipline

- Do only the requested work and its necessary consequences.
- Do not add speculative fallbacks, compatibility layers, migrations,
  abstractions, dependencies, or defensive wrappers.
- Do not add hash-, digest-, or checksum-based tests.
- Preserve validation that protects physical correctness, data integrity, or a
  demonstrated failure mode.
- Keep raw experiment and CFD data under `data/raw_data/`; `data/` is local and
  must not be committed.
- Keep exploratory investigation scripts and result reports in ignored `.cache/`;
  do not commit or upload them. Production code, regression tests, and necessary
  usage and architecture documentation remain tracked.
- Commit and push only when authorized by the user. Existing task authorization
  remains valid unless changed by the user; do not request it again.
- Global instruction or skill changes do not reset an active Goal/Graph,
  audit evidence, or task authorization, or relax project physical, data,
  environment, validation, and CI acceptance conditions. Refresh only nodes
  affected by the actual change.
- Pause and ask the user when physical scope or applicability is unclear.
  Authorization for unrelated work does not resolve that pause.

## Python environment

- `.venv-path` is required for local Python work. Use the absolute interpreter
  on its first line for every Python, pip, smoke, and pytest command. If the
  file or interpreter is missing, stop environment-dependent work and report
  it instead of using another environment.
- Run project modules from the current repository root so `sjtu_tpmshx` resolves
  from the current checkout or worktree.
- For Matplotlib, Qt smoke, and pytest commands, use ignored worktree-local
  `.cache/` paths for `MPLCONFIGDIR` and `XDG_CACHE_HOME`.
- A shared worktree venv is dependency-only: install `requirements-lock.txt`,
  not `requirements.txt`, and do not install this project into it editable.
- Do not create, upgrade, or reinstall an environment or dependency unless the
  user explicitly requests it. If the configured interpreter or a dependency is
  missing, stop environment-dependent work and report the problem instead of
  changing the environment.
- Before unattended work that depends on the Python environment, run
  `python -m sjtu_tpmshx.runs.tools.check_locked_environment` against the
  applicable lock, then `python -m pip check`. On failure, stop work that depends
  on that environment and report it; do not repair the environment automatically.
  The checker intentionally ignores the pip version.
- During an environment pause, only static work independent of that environment
  may continue. Do not bypass either environment check; resume dependent work
  only after both pass. Other pause conditions remain in force.
- A requested dependency addition or removal must update `pyproject.toml` and
  the appropriate lock file in the same change. Do not mutate the shared venv
  as part of a code change; report that an explicit rebuild and prewarm are
  required.
- Do not rebuild a shared venv while another project Python process is using it;
  all worktrees on that machine observe the replacement immediately.
- Server launch scripts may synchronize code and data, but they must use their
  pre-provisioned fixed interpreter and must not install or upgrade packages.
- In source worktrees use `python -m sjtu_tpmshx.cli`, not the installed-only
  `tpmshx-run` console script.

## Change discipline

- Keep GUI concerns in `ui/` and `controllers/`; lower layers stay Qt-free.
- Treat `pipelines/` as orchestration and `solvers/` as numerical
  implementation. Do not duplicate correlations or physical constants across
  those layers.
- Run the existing tests relevant to the files changed. Run broader numerical
  validation only when solver, closure, or pipeline behavior changes.

# Collaboration and task handoff

[中文](collaboration.zh-CN.md) | [English](collaboration.md)

Codex, Claude, and Antigravity use the same [project rules](../AGENTS.md),
[setup instructions](../README.en.md), and [architecture](architecture.md).
Keep task decisions in a handoff record. A chat's private context is not a
handoff record. Existing authorization and open acceptance conditions stay
valid when the owner or tool changes.

Use the [standing task authority](../AGENTS.md#1-task-scope-and-authority)
for Git actions. Follow the user's limits for each task.
For a broad goal, investigate and propose a direction with acceptance conditions.
Get the user's direction before implementation. Then complete the agreed work,
including retirement and necessary validation, without approval at each step.

## Start a task

1. For a change task, name one owner, the write scope, a coordinator, and a reviewer if the task needs review.
   If the user names no other coordinator, the owner is the coordinator.
   Use one worktree and branch for each independent change task.
   Use them again for continued work on that task.
   Read-only work does not need a new worktree. Keep one writer for each file.
   For a heavy job, use the [heavy-job slot](#heavy-job-slot).
2. The coordinator does a check of the primary checkout.
   Fast-forward a clean `main` to `origin/main`. Record the base commit.
   Keep local changes or diverged history for inspection before you select an integration action.
3. Start the task branch from that commit. Use a branch name that shows the agent,
   for example `claude/<task>` or `neon/<task>`, unless the user or the coordinator names another.
   Record the worktree and branch in the [task status](#task-status) file.
4. Select the interpreter through the task's ignored `.venv-path`. Shared
   environments contain dependencies only and stay outside task worktrees.
   Share an environment only when its applicable lock files match. Do the
   [environment checks](../AGENTS.md#3-work-setup-and-environment) before environment-dependent work.
5. Import project source from the current worktree. Keep Matplotlib, XDG,
   and native table caches in that worktree's ignored `.cache/`.
   Record the actual native library and its source and build identity separately.
   Do a check for references to a worktree that you will remove.

### Worktree setup

A new worktree has no `.venv-path` and no published native libraries.

1. Set `.venv-path` to the accepted shared interpreter for the task lock.
2. If the task changes native code, build and publish the new libraries before you use them as evidence.
3. If the task does not change native code, set these variables to the matching libraries in the primary checkout:
   `TPMSHX_GEOMETRY_LIBRARY`, `TPMSHX_PREPARATION_LIBRARY`, `TPMSHX_NATIVE_SOLVER_LIBRARY`, and `TPMSHX_RESULT_LIBRARY`.
4. Do not add a symbolic link to the native library directory in the worktree.

## Multi-agent work

Use this section when a coordinator runs several workers, for example in an Orca run.

1. The coordinator divides the work into tasks.
   Give each worker one task, one worktree, one branch, and one write scope.
   Write scopes do not overlap.
2. Give each shared helper, manifest, or test support file one owner.
   Transfer it only after that owner releases it.
3. Run at most five active implementing writers on this machine.
   Use fewer writers when tasks share files, depend on each other, or wait for review.
   Reviewers and the coordinator are not in this count.
4. The coordinator owns these items:
   - The base commit, the write scopes, and the reviewer assignment.
   - The heavy-job slot, the merge queue, and batch PRs.
   - The repair after a `main` CI failure and the primary checkout update.

   The coordinator does not edit files in the write scope of a worker.
5. Give each worker a brief with these items:
   - Goal, base commit, worktree, branch, and write scope.
   - Dependencies, agreed limits, and user decisions.
   - Applicable lock, native library paths, and checks.
   - Delivery target (reviewed branch or own PR), stop conditions, and report format.
6. A worker that needs a file outside its write scope asks the coordinator first.
   A worker sends questions for the user, blockers, review requests, and results to the coordinator.
7. In an authorized run, messages between a worker and its coordinator need no other approval.
   Messages to other chats need user approval.

### Heavy-job slot

A heavy job is a native build, a full test run, or a heavy numerical run.
Native builds include the `build`, `publish`, and `check-stages` commands of `build_native_dependencies.py`.
Heavy numerical runs include solves, benchmarks, and byte comparison runs.
Targeted pytest files, `ruff`, `audit_import_graph`, and `check_docs.py` are light jobs.
Light jobs can run in parallel.

1. One coordinator grants the heavy-job slot for all runs on this machine.
2. Before a heavy job, ask the coordinator for the slot. Start the job only after the grant.
3. Set `Heavy job: yes` in your status file while the job runs.
   When the process stops, set `Heavy job: no` and tell the coordinator.
4. Before the next grant, the coordinator makes sure that the previous process stopped.
5. After a restart, the coordinator confirms the current slot holder and its process state.

## Task status

A task status file shows the current work to other tasks, tools, and later sessions on this machine.
It is a local file. Do not commit it. Do not record task status in committed files.
Do not copy its local paths into a PR.
The task name is the branch name with each `/` replaced by `-`.
A task without its own branch uses a short name that no other status file uses.

1. Before you start a change task or a heavy job, read each file in
   `.cache/active-tasks/` of the primary checkout.
   The first entry in `git worktree list --porcelain` identifies the primary checkout.
   Do not write files in the write scope of another task that has a status file.
2. When a change task starts, create `.cache/active-tasks/<task>.md` in the primary checkout.
   Also create it when a task without a status file starts a heavy job.
   Only the task owner writes this file. Step 6 gives the only exception.
3. Write these lines in the file:

   ```text
   Worktree: <absolute path>
   Branch: <branch, or none>
   Owner: <person or tool>
   Write scope: <files or directories>
   Heavy job: yes | no
   State: active | blocked: <reason>
   Next action: <step and its owner>
   ```

4. Update the file when a heavy job starts or stops.
   Also update it when the task stops or continues, and when the owner or tool changes.
5. At task closeout, make the PR description current. Then remove the file.
6. If a file names a worktree that does not exist, do not assume that the task is closed.
   The coordinator examines the branch, the PR, the owner, and the evidence.
   After the coordinator confirms that the task is closed, it can remove the file. Tell the user.
   If a file seems out of date for another reason, keep it and tell the user.

The status file is the only owner of the current writer, write scope, heavy job, state, and next action.
Keep these lines current until task closeout.
You do not need the storage measurement when you create, update, or remove a status file.
Do not remove the status file of another task during a cache cleanup.

## Environment recovery

Standing task authority includes recovery of the environment that an agreed task needs.
It includes creation when the necessary environment is missing.
Do these steps before dependent project work starts again:

1. Explain the failure, affected tasks, planned changes, and recovery method.
   Record the applicable lock, original interpreter and pointers, and active consumers.
   Keep the old environment and its source revision available.
   If no usable old environment exists, record that limit and keep the original files.
2. Use the applicable exact lock. Build a replacement at its final location outside task worktrees.
   An existing, compatible host Python can create the replacement.
   Record its absolute path and version. Use it only for environment creation.
   Use the replacement's absolute interpreter for installation and recovery checks.
   This is the explicit exception to the active `.venv-path` rule during recovery.
   If a suitable interpreter or necessary access is not available, report the needed action.
3. Run the lock checker and `pip check` with the replacement interpreter.
   Run from the current repository root. Use worktree-local caches.
   Complete the smoke checks and prewarm for the environment's purpose.
   BO and desktop build environments use their own locks and acceptance checks.
4. Switch only the pointer of the affected idle task after these checks pass.
   Keep active consumers on their original environment.
   Do not change or remove an environment in use.
   Do a check of the task through the new pointer.
   If this check fails, restore the original pointer and keep the failure record.
   Start project execution again only with an accepted environment.
5. Record the replacement, results, changed pointers, and recovery paths.
   Keep the previous environment until the switch is confirmed and its consumers are zero.
   Do the archive and removal checks before a later removal.

Recovery uses the current lock. A dependency version change needs a scoped PR
that updates `pyproject.toml` and the applicable lock together.
Validate its replacement environment before the switch.

Install only the dependencies of `engineering/requirements/base.txt`, not `requirements.txt`, in a shared base environment.
Use the applicable separate lock for each other environment purpose.
Do not install this project into a shared environment in editable mode.
The lock checker ignores the pip version.
Do not rebuild a shared environment while another project Python process uses it.
A change to a shared environment affects each worktree that uses it.
Server launch scripts use their fixed, pre-installed interpreter. They do not install or upgrade packages.

## Related-change record

Before implementation, trace the consumers that the change can reach.
Include only relevant configuration, saved files, tests, fixtures, exports, packaging, examples,
GUI and CLI labels, documentation, comments, and docstrings.
Record related changes in the PR description.
A contract is a behavior, interface, default, unit, limit, command, or file format.
A contract change needs a check of related current text, including Markdown, TXT, and other relevant text files.
If the change alters no contract, write one sentence that says so. Do not list unchanged items.
For a contract change, record the affected contracts, updates, checks, and open items.
Name the check that covers a consumer. A check covers a consumer only when it compares
that consumer with the changed contract. A test that only fixes a literal label does not cover a unit change.
Give a reason for an unchanged consumer only when the reason is not obvious or no check covers it.
Use one sentence for consumers that share a reason. Resolve necessary updates before delivery.
The reviewer traces consumers from the requirement and diff, then compares them with this record.

## Complete code retirement

For a replacement or removal task, record the old code to retire before implementation.
For a replacement, also record the new behavior.
Before the PR exists, write this record in the [private local record](#handoff-record).
Then put it in the PR description. Keep detailed local evidence in ignored `.cache/`.

1. Trace public and internal callers, dynamic names, CLI and GUI entries, and external consumers.
   Include configuration, current saved-file readers, exports, packaging, tests, fixtures, and documentation.
   Do a check of actual use. A name such as `legacy` or `old`, a filename, or a search with no hits
   is not enough evidence.
2. Do a check of the replacement against the behavior that current consumers need.
   Keep physical, data, and platform requirements. Test current save and load together.
   C++ numerical execution and Python application interfaces stay current product capabilities.
3. In the same PR, move consumers and regression coverage to the replacement.
   Remove the replaced implementation and files used only by it.
   Update entry points, build lists, configuration, exports, and documentation together.
   Keep useful regression coverage. Use Git history for previous source code.
   Do not keep duplicate backup files in the working tree.
4. Do a check of remaining references. Run the relevant consumer and regression checks.
   For each kept item, record its consumer, reason, and exact removal condition.
   If retirement is incomplete, report implementation and retirement states separately.
   Complete the task only when its necessary retirement and validation pass.

During an implementation task, record confirmed defects outside its scope.
After delivery, fix them in separate PRs under the standing authority.
Each PR covers a confirmed defect and its necessary consequences.
Explicit read-only tasks stay read-only.

For exploratory code, record the question, success criteria, and adoption or retirement conditions in the existing task record.
Keep it on the main branch only for a stated product, research, or independent-reference use.
Record the consumer and the condition for another assessment.
Keep necessary conclusions and uncommitted evidence before retirement.
Keep units, model identity, metric definitions, and validity states readable in current saved files.
Give evidence, options, and a recommendation before the user selects a product or algorithm change.

## Test scope

Apply these rules when you add or change regression tests:

1. Add a test only for a fixed defect or a changed contract.
   Use a few mapping checks, not a matrix of cases.
   Update the existing tests that the change affects.
2. Do not repeat `dtype` or option combinations after a validated conversion boundary.
   Test conversion at that boundary.
   Keep representative end-to-end cases.
3. Write temporary JSON, NPZ, or HDF5 files only if the test reads them.
   Put C ABI layout and pointer tests in `tests/cpp/*_c_smoke.c`.
   Do not copy public adapters into `ctypes` mirrors.
4. Do not test offscreen pixel coordinates, fixed margin values, or internal mock call counts.
   Do not add `ModuleNotFoundError` tests for deleted symbols.
   Test state changes, physical requirements, resource cleanup, and documented contracts.

## Synchronize and review

The owner does steps 1 to 4. The coordinator sets the merge order for steps 5 to 8.
If the user names no other coordinator, the owner is the coordinator.

1. Complete the relevant checks. Commit only changes in the task scope.
   Do not commit local data, environments, or exploratory reports.
2. Start one [independent review](#independent-review) of the head commit without a user reminder.
   A PR that only corrects spelling, links, or formatting in documents needs no review.
   It must not change the meaning of a rule, command, or contract.
   `engineering/scripts/check_docs.py` must pass. State this reason in the PR.
   Make the revisions. Update the review result after each later commit.
   Record who did the review. Do not describe an agent review as independent human approval.
3. Push the task branch. Open or update the PR. Put the [delivery record](#handoff-record) in the PR description.
   Do not put local absolute paths in the PR.
   For [batch delivery](#batch-delivery), give the reviewed branch to the coordinator and open no PR.
4. Wait for the necessary CI on the latest PR commit.
   Fix task-related failures under the standing authority.
   Repeat the affected checks after a fix. Update the review result.
   An open failure outside the write scope needs a recorded next action.
5. Wait for the merge turn from the coordinator.
   The `main` CI cancels a run in progress when a new commit arrives,
   and repository protection needs an up-to-date branch. Thus, merge one PR at a time.
   Start a merge only when no `main` CI run is in progress.
6. Merge the current `origin/main` into the task branch. Resolve conflicts.
   Keep branch history. Do not force-push or overwrite the changes of another owner.
   Compare the task diff with the reviewed diff. If it did not change, no review round is necessary.
   If conflicts or behavior changed, get a review of the affected lines.
   Repeat the affected checks and wait for the necessary PR CI.
7. Merge with a merge commit when the necessary review, tests, CI, and repository protection conditions pass.
   Do not bypass repository protection.
8. Wait for the necessary CI on the resulting `main` commit.
   Add the merge commit and the `main` CI result to the PR in a comment.
   After CI passes, the coordinator fast-forwards the clean primary checkout to the accepted commit.
   Then the next merge can start.

If the necessary `main` CI fails, keep the failure record.
Run a recoverable job again. If a code fix is necessary, its PR gets the next merge slot.
Hold unrelated merges until the fix passes `main` CI.

PR CI, merged-main CI, desktop acceptance, and experimental validation are separate results.

### Batch delivery

The coordinator can deliver several reviewed branches in one PR with one CI run.

1. Start the batch branch from the current `origin/main`.
2. Merge each reviewed branch with its own merge commit.
3. Compare the first-parent diff of each merge commit with its reviewed diff.
4. If a conflict fix changes reviewed lines, get a narrow review of those lines.
5. Run the integration checks that the combined changes affect.
6. Open one PR. Add a table with each branch, base, reviewed head, reviewer model, rounds, checks, and verdict.
   Add the related-change record of each branch.
7. Deliver the batch PR through steps 4 to 8 of the merge procedure.

### Independent review

The owner gives the requirement, the base and head commits, and the evidence.
In an Orca run, the coordinator starts the reviewer as a separate, read-only worker.
The reviewer did not implement the change and has no inherited author chat history.
These rules do not create a file watcher or a technical gate.
The reviewer's read-only role is not operating-system isolation.

Select the reviewer as follows:

- Some changes need a reviewer of a different model. These are changes to physical meaning,
  numerical results, units, file formats, public interfaces and the C ABI, platform behavior, or project rules.
- For other work, use the independent reviewer with the shorter queue.
  This reviewer can use the same model as the author in a fresh context.
- Use two reviewers of different models for architecture plans and agent-rule changes.
- Pair the models as follows: Neon reviews Astra, Astra reviews Neon, and Astra or Neon reviews Opus.
  Astra is Codex gpt-6.2-astra. Neon is Antigravity gemini-4-neon-high. Opus is Claude Opus.
  If the paired model is not available, record the reason.
  Then use another independent model that covers the same scope.

1. Give the reviewer the requirement, accepted constraints, worktree, base and head commits, applicable rules, and test evidence.
   Include the author's related-change record and relevant prior decisions.
   Keep the reviewed worktree unchanged until the reviewer returns.
2. The reviewer first traces connected consumers from the requirement and diff.
   Then the reviewer compares those findings with the author's related-change record.
   Read relevant code and model documents, including dynamic entries and saved-file consumers.
   Do not limit the review to the author's file list.
3. Look for incomplete related changes, unnecessary code, repeated rules, extra abstractions, and incomplete retirement.
   Do a separate check of correctness, including physical requirements, data, current consumers, and evidence coverage.
   Similar code is not enough evidence for sharing.
   Keep necessary copies, physical validation, independent test references, and useful reference implementations.
4. For each blocking finding, give a stable identifier, location, reachable consumer or maintenance case, consequence, and minimum correction.
   State which existing evidence applies or what minimum check is missing.
   No finding count is necessary. Style preferences and unsupported suspicions do not block delivery.
   A historical issue first found here does not automatically affect this change.
   Explain its direct relation to current delivery or existing acceptance conditions before you make it a blocker.
5. The owner fixes findings or gives evidence for the kept code.
   The reviewer examines evidence that disputes a blocking finding.
   Non-blocking advice needs a disposition. It does not cause another review round.
   The reviewer does not edit files or write to Git.
   The owner runs necessary checks under the existing environment and resource rules.
   If evidence is in doubt, the owner runs a focused check again.
6. Count the first substantive review and each substantive later review as one round.
   Use the same reviewer for later rounds when it is available.
   A change of reviewer or a PR split keeps the findings and the round count.
   Use at most three rounds. After round three, give the user the open findings, the commit range,
   the evidence, the options, and the smallest correction.
   A fourth round needs user approval for that finding and commit range.
7. Update coverage for later commits, `main` synchronization, and conflict resolution.
   A clean synchronization that does not change the task diff needs only a diff comparison. It uses no round.
   Review conflict resolutions and changed behavior again.
   Do not repeat the whole review without cause.
   Keep valid test evidence. Do not repeat heavy numerical runs without a specific need.
   Missing review capability or necessary evidence leaves the review incomplete.
   Do not call the author's own check an independent review.

Record the reviewed commit, the reviewer model, the rounds, the open findings, the evidence, and the conclusion.
Report correctness as one of these results: no blocking finding, blocking finding, or incomplete check.
No blocking finding is not proof that the code has no defects.
The delivery conclusion is ready for subsequent checks, needs correction, needs a user decision, or review incomplete.
Specific blockers and necessary evidence set that conclusion.
A round limit does not cancel physical, data, platform, or CI requirements.
An implementation must not lower its own review requirements to pass.

## Handoff record

Each record has one owner:

| Record | Contents |
| --- | --- |
| [Task status](#task-status) file | Current writer, write scope, heavy job, state, and next action |
| PR description | Delivery record |
| `.cache/<task>/HANDOFF.md` | Local evidence, local paths, and blockers |

The PR description contains these items:

- The change and its [related-change record](#related-change-record).
- The checks and the tested commit.
- The review result, reviewer model, reviewed commit, and rounds, or the reason for no review.
- The PR CI result.
- The open acceptance conditions.

After the merge, add the merge commit and the `main` CI result in a PR comment.

Add all of the fields in the table to the PR description when one of these conditions applies:

- The task spans more than one PR or session.
- The task stops on a blocker.
- The owner or tool changes.
- The retirement is incomplete.

| Field | Necessary information |
| --- | --- |
| Task | Goal, write scope, and authorization scope |
| People or tools | Owner, reviewer, and coordinator |
| Code | Base commit, branch, current commit, reviewed commit, and PR |
| Related changes | Affected contracts and consumers; updates and covering checks; reasons for unchanged consumers that are not obvious or not checked; retirement scope and reasons for kept items |
| Review | Reviewer model and context method, commit coverage, findings and dispositions, rounds, and conclusion |
| Runtime | Applicable lock, environment purpose, native build, and data revision |
| Evidence | Check, tested commit, result, and local evidence record name |
| State | Completed work, failures, open gates, and pending approvals |

The private local record contains the worktree, interpreter, native library,
data-link targets, evidence paths, blocked transfers, and unfinished retirement.
Create it only when the task has local evidence or a blocker, or needs a record before its PR exists.
Keep it at `.cache/<task>/HANDOFF.md` in the task worktree.
Use the [task name](#task-status) for `<task>`. Keep the original failure and not-started states.
Refer to private evidence by its record name in shared records.
At handoff, the next owner reads the shared record and the status file.
Then the next owner does a check of the local paths before commands.
If another machine must continue a task before its PR exists, use a designated issue for the shared handoff.

## Archive and remove

Before you remove a worktree, identify its owner, active writers and processes,
uncommitted or unpushed content, runtime consumers, and ignored evidence.
Keep necessary commits and local material outside the removal set. Record
the original paths, commits, locks, file membership, and link targets. Do not
follow raw-data links while you archive a worktree.

Compare the archived files with their originals. Restore a representative report,
input file, and output file. Read each restored file. Record existing missing or
malformed material without a change to its historical verdict. A same-disk archive
is not an independent backup. An app's Git snapshot does not keep ignored evidence.

Remove a worktree or environment only after these checks pass and its active
consumers are zero. Use its managing app or the applicable Git worktree
operation. Close out branches last, after their necessary commits have a recovery
entry. Archive old screening results without a restore of a retired solver or
optimization chain. Current multi-condition BO stays a separate capability.

<a id="storage-retention"></a>

## Storage retention

Use these rules before a task writes data to or cleans TM1 caches, at task closeout,
and during an authorized storage cleanup.
The `.cache/` name does not make research evidence disposable.
The first entry in `git worktree list --porcelain` identifies the primary checkout.
Resolve relative paths in `.agents/rules/tm1-local-data.md` from that checkout.

Routine tool caches need no measurement before a write.
These caches are the `MPLCONFIGDIR` and `XDG_CACHE_HOME` paths, pytest caches, and status files.
If the machine has a cache limit, measure the combined allocation before other data writes to TM1 caches and before a cleanup.
Include `.cache/` in the primary checkout and its linked worktrees. Include other TM1 caches that the limit covers.
Count each hard-linked file once across those locations. Measure symbolic links without following them.
At the closeout of each task that wrote to `.cache/`, measure the combined allocation once.
At the end of a cleanup, list all cache locations that the limit now covers.
Measure their combined allocation even if the cleanup removed no files.

1. Keep raw data, active paper and GCI evidence, selected designs, and key failure samples.
   Keep their inputs, methods, final fields, metrics, and validity limits.
   Keep all study parameters, seeds, scalar observations, constraints, and original verdicts.
   Do not turn stopped, rejected, or unstarted work into successful work during cleanup.
2. Give kept intermediate fields and checkpoints a specific analysis or continuation use.
   Completed software tests and performance studies do not need indefinite continuation storage.
   Record which fields or checkpoints are removed and which recovery operations are no longer available.
   Keep unfinished work until its owner decides its status.
3. Use the task's worktree for temporary output when you can select its location.
   After the checks pass, remove this task's temporary scripts, test outputs, build products, and rebuildable caches before handoff.
   Keep files that another task, the application, or kept research still needs.
   Keep research scripts necessary to interpret or reproduce kept evidence.
   Archive only the necessary files from that task. Never archive the whole `.cache/` or another task's archive recursively.
   Use Git for committed source history. Compress large records without a change to their contents.
4. Keep one accepted environment for each active role: base, BO, and minimal postprocessing.
   Record consumers and removal conditions for packaging or historical environments.
   Retire a predecessor after replacement validation, pointer checks, and zero active consumers.
   First keep exact package versions, the source revision, locks, and unique local files.
5. Share identical fixed snapshots when their filesystem attributes allow it.
   Keep saved relative paths. Use independent copies when hard links are not available.
   Never link a mutable build output directly into saved evidence.
   Replace shared files atomically. Never overwrite their contents in place.
   Do a check of kept results and representative recovery paths before you remove source material.
6. Record kept material, its consumer, and its removal or review condition in the task handoff.
   Report added, removed, and remaining directory allocation and the measured change in volume free space.
   If the total is still more than the machine limit, record the excess and the next action in the same handoff.
   Automatic deletion is limited to named rebuildable caches and task-owned temporary files.
   Research deletion needs an approved, exact selection. Age or directory name alone is not a selection rule.

## Tool instruction entry points

Codex, Claude, and Antigravity use the project rules in `AGENTS.md`.
[Codex](https://learn.chatgpt.com/docs/agent-configuration/agents-md) reads
`AGENTS.md`. [Claude Code](https://code.claude.com/docs/en/memory#agentsmd)
versions with AGENTS support can read it directly when no project or ancestor
`CLAUDE.md` overrides that choice. Antigravity reads a local rule in `.agents/rules/`
that points to `AGENTS.md`. Do a check of the loaded project instructions in the
actual client at onboarding. If an existing Claude setup needs an entry point,
use `@AGENTS.md` in `CLAUDE.md`. Keep the rules in one file. Do not copy them into
a second rule set.

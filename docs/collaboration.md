# Collaboration and task handoff

[中文](collaboration.zh-CN.md) | [English](collaboration.md)

Codex and Claude use the same [project rules](../AGENTS.md),
[setup instructions](../README.en.md), and [architecture](architecture.md).
Keep task decisions in a handoff record. A chat's private context is not a
handoff record. Existing authorization and unresolved acceptance gates remain
in force when the owner or tool changes.

Use the [standing task authority](../AGENTS.md#1-task-scope-and-authority)
for Git actions. Follow the user's limits for each task.
For a broad goal, investigate and propose a direction with acceptance conditions.
Get the user's direction before implementation. Then complete the agreed work,
including retirement and required validation, without approval at each step.

## Start a task

1. For a change task, name one owner, the permitted scope, and a reviewer.
   Use one worktree and branch per independent change task.
   Reuse them for continued work on that task.
   Read-only work does not need a new worktree. Keep one writer per file.
   Run one heavy numerical job at a time on each machine.
   Independent light tasks can run in parallel.
2. The coordinator does a check of the primary checkout.
   Fast-forward a clean `main` to `origin/main`. Record the base commit.
   Keep local changes or diverged history for inspection before you select an integration action.
3. Start the task branch from that commit. Use `codex/` for Codex branches
   unless the user requests another name. Record the worktree and branch.
4. Select the interpreter through the task's ignored `.venv-path`. Shared
   environments contain dependencies only and live outside task worktrees.
   Share an environment only when its applicable lock files match. Run the
   [environment checks](../AGENTS.md#3-work-setup-and-environment) before environment-dependent work.
   Reuse passing results only as those rules permit.
5. Import project source from the current worktree. Keep Matplotlib, XDG,
   and native table caches in that worktree's ignored `.cache/`.
   Record the actual native library and its source/build identity separately.
   Do a check for references to a worktree scheduled for removal.

## Environment recovery

Standing task authority includes recovery of the environment needed for an agreed task.
It includes creation when the required environment is missing.
Follow these steps before dependent project work resumes:

1. Explain the failure, affected tasks, planned changes, and recovery method.
   Record the applicable lock, original interpreter and pointers, and active consumers.
   Keep the old environment and its source revision available.
   If no usable old environment exists, record that limit and preserve the original files.
2. Use the applicable exact lock. Build a replacement at its final location outside task worktrees.
   An existing, compatible host Python can create the replacement.
   Record its absolute path and version. Use it only for environment creation.
   Use the replacement's absolute interpreter for installation and recovery checks.
   This is the explicit exception to the active `.venv-path` rule during recovery.
   If a suitable interpreter or required access is unavailable, report the needed action.
3. Run the lock checker and `pip check` with the replacement interpreter.
   Run from the current repository root. Use worktree-local caches.
   Complete relevant smoke checks and prewarm for the environment's purpose.
   BO and desktop build environments use their own locks and acceptance checks.
4. Switch only the affected idle task's pointer after these checks pass.
   Keep active consumers on their original environment.
   Do not modify or remove an environment in use.
   Check the task through the new pointer. On failure, restore the original pointer
   and retain the failure record. Resume project execution only with a qualified environment.
5. Record the replacement, results, changed pointers, and recovery paths.
   Retain the previous environment until the switch is verified and its consumers are zero.
   Follow the archive and removal checks before later removal.

Recovery uses the current lock. A dependency version change needs a scoped PR
that updates `pyproject.toml` and the applicable lock together.
Validate its replacement environment before switching. Routine launchers still install no packages.

## Complete code retirement

For a replacement task, record the new behavior and the old code to retire before implementation.
Use the task's existing handoff record; keep detailed local evidence in ignored `.cache/`.
For other implementation tasks, record the affected consumers and related changes in the same handoff.
Include only relevant configuration, saved files, tests, fixtures, exports, packaging, and documentation.
Explain why a related consumer needs no change when that is not clear.

1. Trace public and internal callers, dynamic names, CLI/GUI entries, and external consumers.
   Include configuration and saved-file readers, exports, packaging, tests, fixtures, and documentation.
   Check actual use. A filename or a search with no hits is not sufficient evidence.
2. Verify the replacement against the behavior that current consumers need.
   Keep physical, data, platform, and compatibility requirements.
   C++ numerical execution and Python application interfaces remain current product capabilities.
3. In the same PR, move consumers and regression coverage to the replacement.
   Remove the replaced implementation and files used only by it.
   Update entry points, build lists, configuration, exports, and documentation together.
   Preserve useful regression coverage. Use Git history for previous source code;
   do not keep duplicate backup files in the working tree.
4. Check remaining references and run the relevant consumer and regression checks.
   For each retained item, record its consumer, reason, and exact removal condition.
   Report implementation and retirement states separately if retirement is incomplete.
   Complete the task only when its required retirement and validation pass.

During an implementation task, record confirmed defects outside its scope.
After delivery, fix them in separate PRs under the standing authority.
Each PR covers a confirmed defect and its necessary consequences.
Explicit read-only tasks remain read-only.

For exploratory code, record the question, success criteria, and adoption or retirement conditions in the existing task record.
Keep it on the main branch only for a stated product, research, or independent-reference use.
Record the consumer and the condition for another assessment.
Preserve necessary conclusions and uncommitted evidence before retirement.
Historical result reading and current execution are separate contracts.
Keep units, model and algorithm identity, metric definitions, and validity states readable.
A reading requirement does not authorize removal of a supported resume or execution interface.
Present evidence, options, and a recommendation before the user selects a product or algorithm change.

## Synchronize and review

1. The owner completes the relevant checks. Commit only changes within the task scope.
   Exclude local data, environments, and exploratory reports.
2. Start one [independent review](#independent-review) of the specific head commit without a user reminder.
   The owner makes revisions.
   Update the review result after each later commit.
   Record who did the review. Do not describe an agent's own review as independent human approval.
3. Push the task branch. Open or update the PR.
   Put a concise handoff record in the PR description.
   Use a designated issue when the task needs a handoff before a PR exists.
   Keep local absolute paths and detailed evidence in a private ignored record.
4. If `main` advances, merge the current `origin/main` into the task branch.
   Resolve conflicts. Repeat the affected checks and required CI.
   Update the review result for the new head commit.
   Keep branch history. Do not force-push or overwrite another owner's changes.
5. Wait for required CI on the latest PR commit.
   Fix task-related failures under the standing authority.
   Repeat the affected checks after a fix. Update the review result.
   An unresolved failure outside the permitted scope needs a recorded next action.
6. Merge when the required review, tests, CI, and repository protection conditions pass.
   Do not bypass repository protection.
7. Confirm the remote merge commit. Wait for required CI on that `main` commit to finish.
   If this CI fails, record the failure.
   Continue the task-related repair under the same authority.
8. After required CI passes, the coordinator fast-forwards the clean primary checkout to the accepted commit.
   Update the handoff record with the final commit, CI result, and remaining acceptance conditions.

The task's delivery record must show the final status of each required step.
PR CI, merged-main CI, desktop acceptance, and experimental validation are separate results.

### Independent review

Use one reviewer who did not implement the change, with the same model and no inherited author chat history.
In Codex, start the first reviewer with `spawn_agent` and `fork_turns="none"`.
Check that the current host supports this call before relying on it.
These rules require the owner to start the review; they do not create a file watcher or a technical gate.
The reviewer's read-only role is not operating-system isolation.

1. Give the reviewer the requirement, accepted constraints, worktree, base and head commits, applicable rules, and test evidence.
   Include the author's related-change record and relevant prior decisions.
   Keep the reviewed worktree unchanged until the reviewer returns.
2. The reviewer first traces connected consumers from the requirement and diff.
   Then compare those findings with the author's related-change record.
   Read relevant code and model documents, including dynamic entries and saved-file consumers.
   Do not restrict the review to the author's file list.
3. Check incomplete related changes, unnecessary code, repeated rules, extra abstractions, and incomplete retirement.
   Check correctness separately, including physical requirements, data, current consumers, and evidence coverage.
   Similar code is not enough evidence for sharing.
   Keep required copies, physical validation, independent test oracles, and useful reference implementations.
4. For each blocking finding, give a stable identifier, location, reachable consumer or maintenance case, consequence, and minimum correction.
   State which existing evidence applies or what minimum check is missing.
   No finding count is required. Style preferences and unsupported suspicions do not block delivery.
   A historical issue first noticed here does not automatically affect this change.
   Explain its direct relation to current delivery or existing acceptance requirements before treating it as a blocker.
5. The owner fixes findings or supplies evidence for retaining the code.
   The reviewer checks evidence that disputes a blocking finding.
   Non-blocking advice needs a disposition, but does not by itself require another review.
   The reviewer does not edit files or perform Git writes.
   The owner runs necessary checks under the existing environment and resource rules.
6. Reuse the same reviewer's independent context for rounds two and three.
   Check revisions, new effects, and unresolved findings. Expand the scope when behavior or responsibilities change.
   Do not restart the round count by splitting a PR or starting another reviewer.
   After three rounds, report unresolved substantive issues with evidence and options to the user.
   If later changes require substantive review after the limit, report that decision too.
7. Update coverage for later commits, main synchronization, and conflict resolution.
   Recheck affected parts rather than repeating the whole review without cause.
   Preserve valid test evidence. Do not repeat heavy numerical runs without a specific need.
   Missing review capability or required evidence leaves the review incomplete.
   Do not label the author's own check as an independent review.

Rate each maintainability item as met, needs correction, insufficient evidence, or not applicable, with a short reason:

- Complete related changes.
- Necessary code and complete retirement.
- Repeated rules and clear responsibilities.
- Clear control flow and useful choices.

Report correctness separately: no blocking finding, blocking finding, or incomplete check.
No blocking finding is not proof that the code has no defects.
The delivery conclusion is ready for subsequent checks, needs correction, needs a user decision, or review incomplete.
Item ratings do not determine that conclusion automatically; specific blockers and required evidence do.
No score or round limit waives existing physical, data, platform, or CI requirements.
An implementation must not lower its own review requirements to pass.

For the initial trial, aim for a two-to-five-minute first review of an ordinary task.
Record time and uncovered scope when more work is necessary. Required numerical checks have a separate budget.
Time limits never imply approval. Verify invocation without user reminders on three real code tasks.
Use existing task records for useful findings, rejected findings, confirmed omissions, time, and rounds.
Do not create changes to fill the sample. Three tasks show initial use, not a defect detection rate.

## Handoff record

Use the following fields in the shared PR or issue. Update them when ownership,
scope, the reviewed commit, or the next action changes.

| Field | Required information |
| --- | --- |
| Task | Goal, permitted modules/files, and authorization scope |
| People or tools | Owner, reviewer, and integration coordinator |
| Code | Base commit, branch, current commit, reviewed commit, and PR |
| Related changes | Affected consumers, necessary updates, retirement scope, and reasons for retained items |
| Review | Reviewer and context method, commit coverage, findings and dispositions, rounds, time, and conclusion |
| Runtime | Applicable lock, environment purpose, native build, and data revision |
| Evidence | Check, tested commit, result, and local evidence record name |
| State | Completed work, failures, unresolved gates, and pending approvals |
| Next action | Concrete next step and its owner |

The private local record adds the worktree, interpreter, native library,
data-link targets, and evidence paths. Keep original failure and not-started
states. At handoff, the next owner reads the shared record and checks the local
paths before running commands. Send messages to another chat only when the
user authorizes that communication.

## Archive and remove

Before removing a worktree, identify its owner, active writers and processes,
uncommitted or unpushed content, runtime consumers, and ignored evidence.
Preserve necessary commits and local material outside the removal set. Record
the original paths, commits, locks, file membership, and link targets. Do not
follow raw-data links while archiving a worktree.

Compare archived files with their originals and restore/read representative
reports and input/output files. Record existing missing or malformed material
without changing its historical verdict. A same-disk archive is not an
independent backup. An app's Git snapshot does not preserve ignored evidence.

Remove a worktree or environment only after these checks pass and its active
consumers are zero. Use its managing app or the appropriate Git worktree
operation. Close out branches last, after their needed commits have a recovery
entry. Archive old screening results without restoring a retired solver or
optimization chain. Current multi-condition BO remains a separate capability.

## Tool instruction entry points

[Codex](https://learn.chatgpt.com/docs/agent-configuration/agents-md) reads
`AGENTS.md`. [Claude Code](https://code.claude.com/docs/en/memory#agentsmd)
versions with AGENTS support can read it directly when no project or ancestor
`CLAUDE.md` overrides that choice. Check the loaded project instructions in the
actual client at onboarding. If an existing Claude setup needs an entry point,
use `@AGENTS.md` in `CLAUDE.md`; keep the rules in one file. Do not copy them into
a second rule set. Client onboarding and a two-task collaboration trial require
their own execution evidence.

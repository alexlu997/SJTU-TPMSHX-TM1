# Collaboration and task handoff

[中文](collaboration.zh-CN.md) | [English](collaboration.md)

Codex and Claude use the same [project rules](../AGENTS.md),
[setup instructions](../README.en.md), and [architecture](architecture.md).
Keep task decisions in a handoff record. A chat's private context is not a
handoff record. Existing authorization and unresolved acceptance gates remain
in force when the owner or tool changes.

## Start a task

1. Name one owner, the permitted scope, and a reviewer. Use one worktree and
   one branch per task. Keep one writer per file. Run one heavy numerical job
   at a time on each machine; independent light tasks can run in parallel.
2. The coordinator checks the primary checkout and synchronizes a clean
   `main` by fast-forward. Record the base commit. Preserve and inspect local
   changes or diverged history before choosing an integration action.
3. Start the task branch from that commit. Use `codex/` for Codex branches
   unless the user requests another name. Record the worktree and branch.
4. Select the interpreter through the task's ignored `.venv-path`. Shared
   environments contain dependencies only and live outside task worktrees.
   Share an environment only when its applicable lock files match. Run the
   lock checker and `pip check` before environment-dependent work.
5. Import project source from the current worktree. Keep Matplotlib, XDG,
   Numba, and native table caches in that worktree's ignored `.cache/`.
   Record the actual native library and its source/build identity separately.
   Check for references to a worktree scheduled for removal.

Creating or changing an environment requires user authorization. After such an
explicit request, build at its final location from the applicable exact lock.
Validate the new environment before switching active pointers. Keep the old
one until the switch passes. BO and desktop build environments keep their
separate locks and acceptance checks.

## Synchronize and review

The owner completes the relevant checks, then commits, pushes, and opens a PR
within the authorized scope. Exclude local data, environments, and exploratory
reports. Put a concise handoff record in the PR description, or in a designated
issue when a task must be handed off before a PR exists. Keep local absolute
paths and detailed evidence in a private ignored record.

Review a specific head commit. The owner makes revisions. A later commit
requires the review result to be updated. If `main` advances, the owner merges
the current `origin/main` into the task branch, resolves conflicts, and reruns
the affected checks and required CI. Preserve branch history; do not force-push
or overwrite another owner's changes.

Merge only within the user's authorization and repository protection rules.
Verify the remote merge commit and the terminal CI result for the resulting
`main`. The coordinator then fast-forwards the clean primary checkout and
updates the handoff record. PR CI, merged-main CI, desktop acceptance, and
experimental accuracy are separate conclusions.

## Handoff record

Use the following fields in the shared PR or issue. Update them when ownership,
scope, the reviewed commit, or the next action changes.

| Field | Required information |
| --- | --- |
| Task | Goal, permitted modules/files, and authorization scope |
| People or tools | Owner, reviewer, and integration coordinator |
| Code | Base commit, branch, current commit, reviewed commit, and PR |
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

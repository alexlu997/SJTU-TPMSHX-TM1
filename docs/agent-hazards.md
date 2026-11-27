# Agent hazard index

This index lists open hazards that need an action from the next worker.
It is not a history log. It has no Chinese companion.

- `engineering/scripts/pre_push_check.py` prints the rows whose path patterns match the changed files.
  The coordinator copies matching rows into task briefs. Agents do not load this file at each start.
- Remove a row when an automatic check stops the hazard and its failure output gives the fix,
  or when the dependency closes.
- The limit is 15 rows. At the limit, the coordinator reviews, merges, or assigns rows.
- The coordinator edits one row at a time. A row points only to an approved rule or check.
  A row that adds or changes a required action for workers is a rule change.
  It needs two reviewers of different models ([AGENTS.md](../AGENTS.md#5-review-and-delivery)).
- Use only repository-relative paths and public CI links. Do not copy local logs, local paths, or personal data.
  `engineering/scripts/check_docs.py` checks the row count and rejects local absolute paths.

| ID | Paths | Symptom | Cause | Action | Check | Owner | Opened |
| --- | --- | --- | --- | --- | --- | --- | --- |
| H1 | `python/applications/gui/*`, `tests/python/integration_tm1/*` | macOS integration step exits with code 139 (`Fatal Python error: Segmentation fault`) in `test_public_gui.py`, inside `ExpandedNavRail._rebuild` or `ReadoutStrip._rebuild`. | Under investigation. PR #419 tests the hypothesis that cyclic garbage collection on a worker thread releases Qt objects. | Do not add retries, skips, or quarantine. Do not change the CI job order. Send the run link to the coordinator. | None yet (PR #419; crash evidence step planned in `.github/workflows/native.yml`). | Coordinator | 2026-11-24 |
| H2 | `python/applications/gui/ui/*` | Windows CI only: a value is cut in a text widget, for example `AssertionError: 4.00 mm` in `test_optimization_bounds_show_complete_decimal_values`. | A fixed pixel width. The Windows font is wider than the macOS font. | Calculate text widget widths from the font metrics of the longest value and unit, as commit `e70f223e` does. | `tests/python/test_optimize_panel_wiring.py::test_optimization_bounds_show_complete_decimal_values` fails only on Windows CI. | Coordinator | 2026-11-27 |
| H3 | `python/data_types/validator.py`, `python/applications/gui/ui/case_files.py`, `python/applications/gui/ui/mixins/fluid_input.py`, `python/applications/gui/ui/main_window.py`, `python/applications/gui/ui/builders_sidebar.py` | A temperature changes in the last digit after a unit toggle or a session restore, for example `294.2611111111111 K` becomes `294.26111111111106 K`. | Two conversion paths: exact `Decimal` text conversion and `float` addition of 273.15. | Do not add a new K or °C conversion in the GUI. Use the single owner from PR #420 after it merges. | None yet (PR #420). | PR #420 author | 2026-11-27 |
| H4 | `tests/python/*`, `python/applications/gui/controllers/user_storage.py` | Tests write appearance files to the real user preferences directory. Later runs read them and change GUI state. | A GUI fixture does not redirect `user_storage._appearance_dir`. `tests/python/gui_io_support.py` (integration fixture) still does not redirect it. | In each GUI fixture, redirect the appearance directory to a temporary directory for each run, as `tests/python/gui_workbench_support.py` does. Do not use Qt test mode. | None yet (fixture fix planned in PR B). | Coordinator | 2026-11-27 |
| H5 | `tests/python/test_ui_*.py`, `tests/python/test_workbench_*.py`, `tests/python/gui_*_support.py` | A GUI test passes alone and fails after another test in the same worker. Example: `test_numeric_inputs_rule_a_left_aligned_with_unit_suffix` after `test_empty_state_preset_button_applies_shanghai`. | Tests share one main window and a test did not set the window state that it needs. | Set the window state that the test needs (dimension, mode, page) at its start, and restore it at the end. Run the complete changed test file, not only single nodes. | None yet (CI runs whole modules in one worker). | Coordinator | 2026-11-27 |
| H6 | `geometry/*`, `solver/*`, `include/*`, `python/cpp_interface/*` | A pytest run in a worktree hangs or fails to load a native library while the native images of the primary checkout are published again. | Worktrees link the native images of the primary checkout. A publish replaces the files while test processes use them. | Publish native images only with the [heavy-job slot](collaboration.md#heavy-job-slot) and while no test run uses them. Tell the workers that link the images. Run their affected tests again after the publish. | None yet (heavy-job slot rule). | Coordinator | 2026-11-27 |

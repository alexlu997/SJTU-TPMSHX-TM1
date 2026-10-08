# Spec: ui-results-quickswitch

[中文](spec.md) | [English](spec.en.md)

## Purpose
Give quick result selection through combined 2D field buttons and compatible split/detached routes. The structural repair on 2026-07-03 added the Purpose heading without changing the content.

## Requirements

### Requirement: One-click 2D field switch
The 2D toolbar MUST give Temperature, Velocity, and Pressure segmented buttons. One click MUST select the displayed field. `combo_2d_field` MUST stay the hidden state source, with unchanged internal English keys. Button states MUST follow combo changes from keyboard shortcuts or code. Availability MUST match the original combo: controls are disabled without data.

#### Scenario: Single click switches field
- **WHEN** 2D results are ready and the user selects Pressure
- **THEN** the canvas shows pressure, the button state changes, and the combo index follows

#### Scenario: Reverse sync
- **WHEN** code calls `_switch_tab('vel')`
- **THEN** Velocity is active

### Requirement: Copy current figure to clipboard
The export menu MUST contain Copy Current Figure. This action MUST copy the active canvas image to the system clipboard. If no canvas can be copied, the status bar MUST report this state without an exception.

#### Scenario: Copy after compute
- **WHEN** computation has finished, a field plot is active, and the user selects Copy
- **THEN** the clipboard contains that image as a nonempty QImage

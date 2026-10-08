# Spec: ui-group-badges

[中文](spec.md) | [English](spec.en.md)

## Purpose
Parameter group badges count missing required values, use debounced validation, and stay visible when a group collapses. The structural repair on 2026-07-03 added the Purpose heading without changing the content.

## Requirements

### Requirement: Group-title invalid-field badges
Each parameter group title MUST show `⚠N` when its session fields contain invalid or empty values. N is the count. The rule MUST match preflight: `inpError=='true'` or empty text. Fields hidden by the active dimension gate MUST NOT count. Page changes or collapsed groups MUST NOT clear the count. No badge appears when N=0.

#### Scenario: Hidden problem surfaces through collapse
- **WHEN** a field in a collapsed group is cleared
- **THEN** its group title shows `⚠N` without expanding the group

#### Scenario: Badge clears on fix
- **WHEN** the field receives a valid value
- **THEN** the badge disappears after the debounce interval

#### Scenario: Toggle preserves badge
- **WHEN** a group with a badge expands or collapses
- **THEN** the rendered title still contains the badge. The chevron and badge use the same rendering function.

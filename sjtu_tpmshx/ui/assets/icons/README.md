# UI SVG icons

[中文](README.zh-CN.md) | [English](README.md)

This is a small SVG subset from [Lucide](https://lucide.dev/),
retrieved on 2026-09-20 from
https://github.com/lucide-icons/lucide/tree/main/icons.

The adjacent `LICENSE` keeps the complete upstream ISC license and the
Feather-derived icons' MIT notice. Colors are applied at render time by
`ui/icons.py`. The SVG geometry stays unchanged.

`chevron-down-light.svg` and `chevron-down-dark.svg` reuse the same Lucide
geometry with fixed colors selected for the corresponding light/dark theme. These two assets
let Qt stylesheets load a colored arrow without depending on native menu
painting or generating files at runtime. The other SVGs are unmodified.

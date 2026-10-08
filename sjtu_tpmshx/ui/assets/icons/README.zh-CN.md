<a id="ui-svg-icons"></a>

# 界面 SVG 图标

[中文](README.zh-CN.md) | [English](README.md)

本目录是 [Lucide](https://lucide.dev/) 的小型 SVG 子集。
文件于 2026-09-20 从 [上游图标目录](https://github.com/lucide-icons/lucide/tree/main/icons)取得。

相邻的 `LICENSE` 保留完整的上游 ISC 许可，以及源自 Feather 图标的 MIT 声明。
`ui/icons.py` 在渲染时设置颜色；SVG 几何保持不变。

`chevron-down-light.svg` 和 `chevron-down-dark.svg` 使用相同的 Lucide 几何，
分别固定为浅色与深色主题需要的颜色。
Qt 样式表可直接加载这两种箭头，无须依赖系统菜单绘制，也无须运行时生成文件。
其他 SVG 保持原样。

# 704 — 10kW 空冷器定尺

历史工程评估：10 kW 空冷器（air-cooler）定尺与热约束校核。驱动脚本调用 `sjtu_tpmshx` 的设计模块与求解器；报告的静态说明沿用 2026-06 文案，不代表当前 TM1 的设计或实验精度验收。

## 脚本

| 脚本 | 用途 |
|---|---|
| `predict_aircooler_10kw.py` | 10 kW 空冷器定尺，覆盖 3 个工况；提供 `build_cases()`。 |
| `aircooler_conservative_check.py` | 校核定尺结果是否满足热约束（保守 3D 复核）。`from predict_aircooler_10kw import build_cases`——与上一个脚本是同目录兄弟导入，二者必须放在一起。 |

## 运行（从仓库根目录）

`python` 必须替换为 `.venv-path` 第一行的绝对解释器，先通过锁检查和 `pip check`；绘图缓存使用本工作树忽略的 `.cache/`。

```bash
python -u projects/704-Aircooler-10kW/predict_aircooler_10kw.py sanity
python -u projects/704-Aircooler-10kW/aircooler_conservative_check.py
```

输入来自 `build_cases()`，不读取外部工况 Excel。`sanity` 计算单个 Diamond 6.0/0.4 定尺，输出控制台；`square` / `rect` 枚举几何。原研究脚本对包络的设置继续保留。

`report cross` / `report counter` 计算并写报告；`rehtml` 只读取对应缓存；`combined` 读取叉流和逆流两份缓存生成汇报版。XLSX/HTML 默认在 `.cache/aircooler-10kw/`，可用 `TPMSHX_TOOL_OUT_DIR` 指定目录。原 `_aircooler_runs.pkl` / `_aircooler_runs_counter.pkl` 缓存位置仍在本项目目录，读取历史缓存时须核对其代码和模型版本。重复运行会覆盖同名产物，先保全需要的旧结果。

两个脚本把仓库根加入模块路径，使用 `sjtu_tpmshx.*`；同目录 `build_cases()` 兄弟导入保留。当前正式能力和物理边界见[架构说明](../../docs/architecture.md)。

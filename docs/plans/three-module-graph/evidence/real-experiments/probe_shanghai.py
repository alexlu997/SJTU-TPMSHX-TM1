import json
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sjtu_tpmshx.validation.water_exp import with_water_absolute_pressures
from sjtu_tpmshx.validation.cases import validate_shanghai_aligned as runner


def encode(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


root = Path(sys.argv[1] if len(sys.argv) > 1 else ".cache/shanghai-migration")
root.mkdir(exist_ok=False)
(root / "provenance.json").write_text(
    json.dumps(
        dict(
            source_sha=subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True
            ).strip(),
            interpreter=sys.executable,
            case_numbers=list(range(1, 17)),
            runner="pipeline",
            workbook=str(runner.SHANGHAI_XLSX.resolve()),
        ),
        indent=2,
    )
)
df = pd.read_excel(
    runner.SHANGHAI_XLSX,
    engine="openpyxl",
    sheet_name="Sheet1",
    header=None,
    skiprows=2,
    nrows=16,
)
assert len(df) == 16
# Fixed declared row set, never a validity filter: every selected row is validated.
df = with_water_absolute_pressures(
    df, source=runner.SHANGHAI_XLSX, sheet="Sheet1", tin=24, tout=25, pin=26, pout=27
)
captured = {}


def observe(frame, event, result):
    if (
        frame.f_code is runner._run_one_case_pipeline.__code__
        and event == "return"
        and "res" in frame.f_locals
    ):
        res = frame.f_locals["res"]
        captured.update(
            raw_metrics={
                k: getattr(res, k)
                for k in ("Q_W", "dP_A_Pa", "dP_B_Pa", "T_out_A_K", "T_out_B_K")
            },
            diagnostics=res.diagnostics,
            warnings=list(res.warnings or []),
            config=frame.f_locals["cc"].to_dict(),
        )


failed = False
for index in range(16):
    captured = {}
    sys.setprofile(observe)
    try:
        captured["reported_row"] = runner._run_one_case_pipeline(index, df)
        captured["execution"] = "completed"
    except Exception as exc:
        failed = True
        captured.update(
            execution="failed", exception=type(exc).__name__, message=str(exc)
        )
    finally:
        sys.setprofile(None)
    (root / f"case-{index + 1:02d}.json").write_text(
        json.dumps(captured, default=encode, indent=2) + "\n"
    )
    print(index + 1, captured["execution"], captured.get("raw_metrics"), flush=True)
sys.exit(1 if failed else 0)

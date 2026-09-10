"""TM1's Python bridge from immutable cases to the existing pipeline."""
from __future__ import annotations

from typing import Any

from sjtu_tpmshx.controllers.compute_pipeline import pipeline_for
from sjtu_tpmshx.domain.case_data import CaseData
from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.domain.compute_result import ComputeResult
from sjtu_tpmshx.domain.field_result import FieldResult
from sjtu_tpmshx.domain.module_ports import RunControl


def build_case(case_id: str, config: ComputeConfig, **kwargs: Any) -> CaseData:
    """Freeze the established typed configuration at the preprocessing seam."""
    return CaseData.from_compute_config(case_id, config, **kwargs)


def field_result_from_compute_result(
    case: CaseData, result: ComputeResult, backend: str = "python",
) -> FieldResult:
    """Preserve the native pipeline result without changing its units or verdict."""
    fields = result.fields
    grid = {
        name: fields[name]
        for name in ("N_x", "N_y", "dx_arr", "dy_arr", "dx", "dy", "dz",
                     "L", "H", "Lx", "Ly", "Lz")
        if name in fields
    }
    return FieldResult(
        result_id=f"{case.case_id}:{backend}",
        case_id=case.case_id,
        backend_id=backend,
        grid=grid,
        fields=fields,
        boundary_fluxes={
            "Q_W": result.Q_W,
            "T_out_A_K": result.T_out_A_K,
            "T_out_B_K": result.T_out_B_K,
        },
        pressure_evidence={"dP_A_Pa": result.dP_A_Pa, "dP_B_Pa": result.dP_B_Pa},
        run_status={
            "converged": result.converged,
            "residuals": result.residuals,
            "warnings": result.warnings,
        },
        metadata={
            "coeffs": result.coeffs,
            "props": result.props,
            "zones": result.zones,
            "diagnostics": result.diagnostics,
            "extrap_reasons": result.extrap_reasons,
        },
    )


def run_case(case: CaseData, control: RunControl = RunControl()) -> FieldResult:
    """Run a prepared case through the one established production pipeline."""
    if control.backend != "python":
        raise ValueError(f"unsupported TM1 backend: {control.backend}")
    config = ComputeConfig.from_dict(dict(case.config_snapshot))
    return field_result_from_compute_result(case, pipeline_for(config).run(), control.backend)


__all__ = ["build_case", "field_result_from_compute_result", "run_case"]

from __future__ import annotations

import numpy as np
import pytest

from sjtu_tpmshx.controllers import module_adapter
from sjtu_tpmshx.domain.compute_config import ComputeConfig, GeometryConfig, SolverConfig
from sjtu_tpmshx.domain.compute_result import ComputeResult
from sjtu_tpmshx.domain.module_ports import RunControl


def _result() -> ComputeResult:
    return ComputeResult(
        Q_W=12.5,
        dP_A_Pa=13.0,
        dP_B_Pa=14.0,
        T_out_A_K=350.0,
        T_out_B_K=320.0,
        converged=False,
        fields={"Ta": np.array([300.0]), "N_x": 1, "N_y": 1},
        residuals={"energy_imbalance_rel": 0.01},
        warnings=["domain warning"],
    )


@pytest.mark.parametrize(
    "config",
    [
        ComputeConfig(),
        ComputeConfig(
            geometry=GeometryConfig(Lz_m=0.042),
            solver=SolverConfig(Nz=2),
        ),
    ],
    ids=["2d", "3d"],
)
def test_case_adapter_preserves_pipeline_evidence_and_uses_case_snapshot(monkeypatch, config):
    case = module_adapter.build_case("case-1", config)
    seen = {}

    class Pipeline:
        def run(self):
            return _result()

    def fake_pipeline_for(config):
        seen["config"] = config
        return Pipeline()

    monkeypatch.setattr(module_adapter, "pipeline_for", fake_pipeline_for)
    result = module_adapter.run_case(case)

    assert seen["config"].geometry.L_dom_m == 0.182
    assert seen["config"].is_3d is config.is_3d
    assert result.case_id == case.case_id
    assert result.boundary_fluxes["Q_W"] == 12.5
    assert result.pressure_evidence["dP_A_Pa"] == 13.0
    assert result.run_status["converged"] is False
    assert result.run_status["warnings"] == ("domain warning",)
    with pytest.raises(ValueError):
        result.fields["Ta"][0] = 0.0


def test_case_adapter_rejects_an_unimplemented_backend():
    case = module_adapter.build_case("case-1", ComputeConfig())
    with pytest.raises(ValueError, match="unsupported"):
        module_adapter.run_case(case, RunControl(backend="openfoam"))

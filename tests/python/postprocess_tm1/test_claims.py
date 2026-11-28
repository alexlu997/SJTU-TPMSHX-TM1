"""Truth-table tests for independent claim field mapping."""
from __future__ import annotations

from dataclasses import replace
import json

import numpy as np
import pytest

from tm1.data_types.field_result import FieldResult
from tm1.data_types.portable_data import mutable_data
from tm1.postprocess.api import evaluate, evaluate_applicability, evaluate_qualification
from tm1.postprocess.claims import DESIGN_GATES, claim_fields
from tests.python.postprocess_tm1.test_applicability import sample
from tests.python.postprocess_tm1.test_qualification import qualified_result, required_metrics


def _range_sample(lo, hi, bounds=(100.0, 200.0), *, size=2, **overrides):
    row = sample(lo, hi, bounds=bounds, size=size)
    row.update(overrides)
    return row


def _qualified_2d_true_h():
    field = qualified_result(2)
    metadata = mutable_data(field.metadata)
    metadata["thermal_mode"] = "true_h"
    metadata["diagnostics"]["true_h_balance"] = {
        "converged": True,
        "enthalpy_clip_counts": {"total": [0, 0]},
        "effective_settings": {"coupled_energy_tol": 0.001, "equation_energy_tol": 0.001},
        "coupled_energy_balance": {"ratio": 0.0002},
        "equation_energy_balance": {"ratio": 0.0003},
    }
    return replace(field, metadata=metadata)


def _assert_json_safe_and_no_claim_level(claims: dict) -> None:
    assert "claim_level" not in claims
    assert claims["experimental_validation"] == "not_established"
    json.dumps(claims, allow_nan=False)


def test_eligible_2d_run_claims():
    field = _qualified_2d_true_h()
    qualification = evaluate_qualification(field, required_metrics(2))
    claims = claim_fields(
        "run",
        qualification,
        applicability_evidence=field.metadata["applicability_evidence"],
    )

    _assert_json_safe_and_no_claim_level(claims)
    assert "study" not in claims
    assert claims["design"]["status"] == "eligible"
    assert claims["design"]["reasons"] == []
    assert claims["design"]["gates"] == {gate: True for gate in DESIGN_GATES}
    assert claims["optimization"] == {"status": "passed", "reasons": [], "deferred": []}
    assert claims["extrapolated"] is False
    assert claims["screening"] is False
    assert len(claims["ranges"]) == 2
    assert [row["group"] for row in claims["ranges"]] == ["inlet", "final"]
    for row in claims["ranges"]:
        assert row["status"] == "within_original"
        assert row["observed_min"] == pytest.approx(100.0)
        assert row["observed_max"] == pytest.approx(200.0)
        assert row["allowed_min"] == pytest.approx(90.0)
        assert row["allowed_max"] == pytest.approx(220.0)
        assert row["unit"] == "-"
        assert row["bounds_status"] == "recorded"
        assert row["extrapolated"] is False
        assert row["study_exception"] is False


def test_rejected_applicability_outside_limit():
    field = _qualified_2d_true_h()
    metadata = mutable_data(field.metadata)
    metadata["applicability_evidence"]["final"][0]["minimum"] = (85.0, (0,))
    metadata["applicability_evidence"]["final"][0]["low"] = 1
    field = replace(field, metadata=metadata)
    qualification = evaluate_qualification(field, required_metrics(2))

    claims = claim_fields(
        "run",
        qualification,
        applicability_evidence=field.metadata["applicability_evidence"],
    )

    _assert_json_safe_and_no_claim_level(claims)
    assert claims["design"]["status"] == "rejected"
    assert claims["design"]["reasons"] == ["applicability"]
    assert claims["design"]["gates"]["applicability"] is False
    assert claims["design"]["gates"]["convergence"] is True
    assert claims["optimization"] == {
        "status": "failed",
        "reasons": ["applicability"],
        "deferred": [],
    }
    assert claims["extrapolated"] is False
    inlet, final = claims["ranges"]
    assert inlet["status"] == "within_original"
    assert final["status"] == "outside_limit"
    assert final["observed_min"] == pytest.approx(85.0)
    assert final["observed_max"] == pytest.approx(200.0)
    assert final["allowed_min"] == pytest.approx(90.0)
    assert final["allowed_max"] == pytest.approx(220.0)
    assert final["extrapolated"] is False
    assert final["study_exception"] is False


def test_unverified_not_a_full_solve():
    quick_field = FieldResult(
        result_id="quick-1",
        case_id="case-1",
        backend_id="cpp",
        backend_version="quick_design_v1",
        fields={"Ta": np.full((2, 2, 1), 400.0), "Tb": np.full((2, 2, 1), 350.0), "Ts": np.full((2, 2, 1), 375.0)},
        boundary_fluxes={
            side: {"mass_flow_kg_s": 0.1, "cp_J_kgK": 1000.0, "inlet_temperature_K": tin}
            for side, tin in (("A", 500.0), ("B", 300.0))
        },
        pressure_evidence={
            side: {"inlet_absolute_Pa": 200000.0, "outlet_absolute_Pa": 199000.0}
            for side in ("A", "B")
        },
        run_status={"execution": "completed", "converged": True, "screening": True},
        metadata={
            "mode": "quick_design",
            "dimension": 3,
            "model": "plug_ltne_analytic_dp_v1",
            "parameters": {"arrangement": "cross"},
        },
    )
    performance = evaluate(quick_field)
    claims = claim_fields("run", performance.qualification)

    _assert_json_safe_and_no_claim_level(claims)
    assert claims["design"]["status"] == "unverified"
    assert claims["design"]["gates"]["execution"] is True
    assert claims["design"]["gates"]["convergence"] is True
    assert claims["design"]["gates"]["full_solve"] is None
    assert claims["design"]["gates"]["physical"] is None
    assert "full_solve" in claims["design"]["reasons"]
    assert claims["optimization"]["status"] == "unverified"
    assert claims["ranges"] == []
    assert claims["extrapolated"] is False
    assert claims["screening"] is False


def test_sco2_with_model_scope_deferred():
    field = qualified_result(3)
    metadata = mutable_data(field.metadata)
    metadata["execution_record"]["sides"]["A"]["fluid"] = "sco2"
    field = replace(field, metadata=metadata)
    qualification = evaluate_qualification(field, required_metrics(3))

    claims = claim_fields(
        "run",
        qualification,
        applicability_evidence=field.metadata["applicability_evidence"],
    )

    _assert_json_safe_and_no_claim_level(claims)
    assert claims["design"]["status"] == "unverified"
    assert claims["design"]["reasons"] == ["model_scope"]
    assert claims["design"]["gates"]["model_scope"] is None
    assert claims["design"]["gates"]["applicability"] is True
    assert claims["optimization"] == {
        "status": "passed",
        "reasons": [],
        "deferred": ["model_scope"],
    }
    assert claims["extrapolated"] is False


def test_within_margin_marks_extrapolation_while_keeping_eligibility():
    field = _qualified_2d_true_h()
    metadata = mutable_data(field.metadata)
    metadata["applicability_evidence"]["final"][0]["minimum"] = (95.0, (0,))
    metadata["applicability_evidence"]["final"][0]["low"] = 1
    field = replace(field, metadata=metadata)
    qualification = evaluate_qualification(field, required_metrics(2))

    claims = claim_fields(
        "run",
        qualification,
        applicability_evidence=field.metadata["applicability_evidence"],
    )

    _assert_json_safe_and_no_claim_level(claims)
    assert claims["design"]["status"] == "eligible"
    assert claims["optimization"]["status"] == "passed"
    assert claims["extrapolated"] is True
    inlet, final = claims["ranges"]
    assert inlet["status"] == "within_original" and inlet["extrapolated"] is False
    assert final["status"] == "within_margin" and final["extrapolated"] is True
    assert final["study_exception"] is False
    assert final["observed_min"] == pytest.approx(95.0)
    assert final["allowed_min"] == pytest.approx(90.0)
    assert final["allowed_max"] == pytest.approx(220.0)


def test_nonfinite_raw_temperature_invalid_with_saved_converged_flag():
    field = _qualified_2d_true_h()
    fields = mutable_data(field.fields)
    fields["Ta"] = np.full((2, 2), 350.0)
    fields["Ta"][0, 1] = float("nan")
    metadata = mutable_data(field.metadata)
    bad_temp = _range_sample(
        300.0,
        400.0,
        bounds=(250.0, 500.0),
        source=("property", "air_cp"),
        quantity="T",
        unit="K",
        nonfinite=1,
        maximum=None,
    )
    metadata["applicability_evidence"]["final"].append(bad_temp)
    field = replace(field, fields=fields, metadata=metadata)
    assert field.run_status["converged"] is True
    qualification = evaluate_qualification(field, required_metrics(2))

    claims = claim_fields(
        "run",
        qualification,
        applicability_evidence=field.metadata["applicability_evidence"],
    )

    _assert_json_safe_and_no_claim_level(claims)
    assert claims["design"]["status"] == "rejected"
    assert claims["design"]["gates"]["convergence"] is False
    assert claims["design"]["gates"]["applicability"] is False
    assert "convergence" in claims["design"]["reasons"]
    assert "applicability" in claims["design"]["reasons"]
    assert claims["optimization"]["status"] == "failed"
    assert claims["extrapolated"] is False
    temp_rows = [row for row in claims["ranges"] if row["quantity"] == "T"]
    assert len(temp_rows) == 1
    assert temp_rows[0]["group"] == "final"
    assert temp_rows[0]["status"] == "invalid"
    assert temp_rows[0]["observed_min"] == pytest.approx(300.0)
    assert temp_rows[0]["observed_max"] is None
    assert temp_rows[0]["allowed_min"] == pytest.approx(225.0)
    assert temp_rows[0]["allowed_max"] == pytest.approx(550.0)
    assert temp_rows[0]["unit"] == "K"
    assert temp_rows[0]["bounds_status"] == "recorded"
    assert temp_rows[0]["extrapolated"] is False


def test_same_side_and_quantity_keep_distinct_inlet_and_final_groups():
    field = _qualified_2d_true_h()
    metadata = mutable_data(field.metadata)
    source = ("nu", "air", "Gyroid")
    inlet_row = _range_sample(420.0, 420.0, bounds=(400.0, 16000.0), source=source, side="A", quantity="Re", unit="-")
    final_row = _range_sample(380.0, 2000.0, bounds=(400.0, 16000.0), source=source, side="A", quantity="Re", unit="-")
    metadata["applicability_evidence"] = {
        "version": "applicability_evidence_v1",
        "inlet_recorded": True,
        "inlet": [inlet_row],
        "final": [final_row],
        "required": [{"group": "final", "side": "A", "source": source}],
        "scope_notes": [],
    }
    field = replace(field, metadata=metadata)
    qualification = evaluate_qualification(field, required_metrics(2))

    claims = claim_fields(
        "run",
        qualification,
        applicability_evidence=field.metadata["applicability_evidence"],
    )

    _assert_json_safe_and_no_claim_level(claims)
    assert len(claims["ranges"]) == 2
    inlet, final = claims["ranges"]
    assert inlet["group"] == "inlet" and final["group"] == "final"
    assert inlet["side"] == final["side"] == "A"
    assert inlet["quantity"] == final["quantity"] == "Re"
    assert inlet["source"] == final["source"] == ["nu", "air", "Gyroid"]
    assert inlet["status"] == "within_original"
    assert inlet["observed_min"] == pytest.approx(420.0)
    assert inlet["extrapolated"] is False
    assert final["status"] == "within_margin"
    assert final["observed_min"] == pytest.approx(380.0)
    assert final["observed_max"] == pytest.approx(2000.0)
    assert final["extrapolated"] is True
    assert claims["extrapolated"] is True


def test_bo_condition_strict_failure_with_study_permission_on_one_group_only():
    field = _qualified_2d_true_h()
    metadata = mutable_data(field.metadata)
    source = ("nu", "air", "Gyroid")
    inlet_row = _range_sample(200.0, 200.0, bounds=(400.0, 16000.0), source=source, side="A", quantity="Re", unit="-")
    final_row = _range_sample(300.0, 2000.0, bounds=(400.0, 16000.0), source=source, side="A", quantity="Re", unit="-")
    metadata["applicability_evidence"] = {
        "version": "applicability_evidence_v1",
        "inlet_recorded": True,
        "inlet": [inlet_row],
        "final": [final_row],
        "required": [{"group": "final", "side": "A", "source": source}],
        "scope_notes": [],
    }
    field = replace(field, metadata=metadata)
    qualification = evaluate_qualification(field, required_metrics(2))
    applicability = evaluate_applicability(field)
    final_check = {"group": "final", **mutable_data(applicability["checks"]["final"][0])}
    study_acceptance = {
        "passed": True,
        "strict_passed": False,
        "nu_re_extrapolated": True,
        "extrapolation_checks": [final_check],
    }

    claims = claim_fields(
        "bo_condition",
        qualification,
        applicability_evidence=field.metadata["applicability_evidence"],
        study_acceptance=study_acceptance,
    )

    _assert_json_safe_and_no_claim_level(claims)
    assert claims["design"]["status"] == "rejected"
    assert claims["design"]["gates"]["applicability"] is False
    assert claims["design"]["reasons"] == ["applicability"]
    assert claims["optimization"]["status"] == "failed"
    assert claims["optimization"]["reasons"] == ["applicability"]
    assert claims["study"]["accepted"] is True
    assert claims["study"]["strict_passed"] is False
    assert claims["study"]["exception"] == "nu_re_extrapolation"
    assert len(claims["study"]["checks"]) == 1
    assert claims["study"]["checks"][0]["group"] == "final"
    assert claims["study"]["checks"][0]["observed_min"] == pytest.approx(300.0)
    assert claims["study"]["checks"][0]["allowed_min"] == pytest.approx(360.0)
    assert claims["study"]["checks"][0]["allowed_max"] == pytest.approx(17600.0)

    inlet, final = claims["ranges"]
    assert inlet["group"] == "inlet"
    assert inlet["status"] == "outside_limit"
    assert inlet["study_exception"] is False
    assert inlet["extrapolated"] is False
    assert final["group"] == "final"
    assert final["status"] == "outside_limit"
    assert final["study_exception"] is True
    assert final["extrapolated"] is True
    assert claims["extrapolated"] is True
    assert claims["screening"] is False


def test_bo_condition_without_applicability_evidence_marks_bounds_not_recorded():
    field = _qualified_2d_true_h()
    qualification = evaluate_qualification(field, required_metrics(2))
    study_acceptance = {
        "passed": True,
        "strict_passed": True,
        "nu_re_extrapolated": False,
        "extrapolation_checks": [],
    }

    claims = claim_fields(
        "bo_condition",
        qualification,
        applicability_evidence=None,
        study_acceptance=study_acceptance,
    )

    _assert_json_safe_and_no_claim_level(claims)
    assert claims["design"]["status"] == "eligible"
    assert claims["study"] == {
        "accepted": True,
        "strict_passed": True,
        "exception": "none",
        "checks": [],
    }
    assert len(claims["ranges"]) == 2
    for row in claims["ranges"]:
        assert row["status"] == "within_original"
        assert row["bounds_status"] == "not_recorded"
        assert row["observed_min"] is None
        assert row["observed_max"] is None
        assert row["allowed_min"] is None
        assert row["allowed_max"] is None
        assert row["unit"] is None


@pytest.mark.parametrize(
    ("row", "expected_execution", "expected_convergence"),
    [
        (
            {
                "feasible": False,
                "reason": "case 1: water-state-invalid@final: liquid water required",
                "percase": [
                    {
                        "case": 1,
                        "run_status": {"execution": "failed", "converged": False},
                        "acceptance_reasons": ["water-state-invalid@final: liquid water required"],
                    }
                ],
            },
            False,
            False,
        ),
        (
            {
                "feasible": False,
                "reason": "dP>lim@s_max",
                "percase": [],
            },
            None,
            None,
        ),
    ],
)
def test_quick_design_failed_row_without_full_run_status(
    row, expected_execution, expected_convergence
):
    claims = claim_fields("quick_design_row", screening=row)

    _assert_json_safe_and_no_claim_level(claims)
    assert "study" not in claims
    assert claims["screening"] is True
    assert claims["design"]["status"] == "unverified"
    assert "execution" in claims["design"]["reasons"]
    assert claims["design"]["gates"]["execution"] is expected_execution
    assert claims["design"]["gates"]["convergence"] is expected_convergence
    assert claims["design"]["gates"]["full_solve"] is None
    assert claims["optimization"]["status"] == "unverified"
    assert "execution" in claims["optimization"]["reasons"]
    assert claims["ranges"] == []
    assert claims["extrapolated"] is False


def test_quick_design_feasible_row_is_screening_and_never_eligible():
    row = {
        "feasible": True,
        "reason": "",
        "validity": "",
        "percase": [
            {
                "case": 1,
                "run_status": {
                    "execution": "completed",
                    "converged": True,
                    "screening": True,
                    "physical_validation": "not_established",
                    "passes": [{"converged": True, "iterations": 12, "residual": 1e-12}],
                },
                "acceptance_reasons": [],
                "warnings": [],
            }
        ],
    }

    claims = claim_fields("quick_design_row", screening=row)

    _assert_json_safe_and_no_claim_level(claims)
    assert "study" not in claims
    assert claims["screening"] is True
    assert claims["design"]["status"] == "unverified"
    assert claims["design"]["gates"] == {
        "execution": True,
        "convergence": True,
        "physical": None,
        "applicability": None,
        "metrics": None,
        "model_scope": None,
        "full_solve": None,
    }
    assert claims["design"]["reasons"] == [
        "physical",
        "applicability",
        "metrics",
        "model_scope",
        "full_solve",
    ]
    assert claims["optimization"]["status"] == "unverified"
    assert claims["ranges"] == []
    assert claims["extrapolated"] is False


def test_duplicate_group_keys_pair_positionally_with_distinct_extrema():
    source = ("nu", "co2", "Diamond")
    preflight = _range_sample(1200.0, 1200.0, bounds=(1000.0, 5000.0), source=source, side="A", quantity="Re", stage="inlet-preflight")
    bulk = _range_sample(1250.0, 1250.0, bounds=(1000.0, 5000.0), source=source, side="A", quantity="Re", stage="inlet")
    qualification = {
        "definition": "result_qualification_v1",
        "design": {
            "status": "eligible",
            "eligible": True,
            "requirements": {gate: True for gate in DESIGN_GATES},
            "reasons": [],
        },
        "optimization": {"status": "passed", "passed": True, "reasons": [], "deferred": []},
        "applicability": {
            "passed": True,
            "checks": [
                {"group": "inlet", "side": "A", "source": list(source), "quantity": "Re", "status": "within_original", "passed": True},
                {"group": "inlet", "side": "A", "source": list(source), "quantity": "Re", "status": "within_original", "passed": True},
            ],
        },
    }
    evidence = {
        "version": "applicability_evidence_v1",
        "inlet_recorded": True,
        "inlet": [preflight, bulk],
        "final": [],
        "required": [],
        "scope_notes": [],
    }

    claims = claim_fields("run", qualification, applicability_evidence=evidence)

    _assert_json_safe_and_no_claim_level(claims)
    assert [row["observed_min"] for row in claims["ranges"]] == [pytest.approx(1200.0), pytest.approx(1250.0)]


def test_missing_qualification_and_unavailable_or_signed_range_samples():
    uncaptured = _range_sample(100.0, 200.0, captured=False, minimum=None, maximum=None)
    signed = _range_sample(-0.01, 0.3, bounds=(0.0, 1.0), source=("property", "signed_test"), quantity="x")
    evidence = {
        "version": "applicability_evidence_v1",
        "inlet_recorded": True,
        "inlet": [uncaptured],
        "final": [signed],
        "required": [],
        "scope_notes": [],
    }

    claims = claim_fields("run", None, applicability_evidence=evidence)

    _assert_json_safe_and_no_claim_level(claims)
    assert claims["design"] == {
        "status": "unverified",
        "reasons": [],
        "gates": {gate: None for gate in DESIGN_GATES},
    }
    assert claims["optimization"] == {"status": "unverified", "reasons": [], "deferred": []}
    assert claims["extrapolated"] is False
    first, second = claims["ranges"]
    assert first["status"] == "unavailable" and first["bounds_status"] == "unavailable"
    assert first["observed_min"] is None and first["allowed_min"] is None
    assert second["status"] == "domain_rule_required" and second["bounds_status"] == "recorded"
    assert second["extrapolated"] is False


def test_experimental_validation_cannot_be_overridden_and_invalid_inputs_fail():
    field = _qualified_2d_true_h()
    qualification = evaluate_qualification(field, required_metrics(2))
    rogue = dict(qualification, experimental_validation="validated")
    claims = claim_fields("run", rogue, applicability_evidence=field.metadata["applicability_evidence"])
    assert claims["experimental_validation"] == "not_established"

    with pytest.raises(ValueError, match="unsupported claim kind"):
        claim_fields("unknown")
    with pytest.raises(ValueError, match="study_acceptance"):
        claim_fields("run", qualification, study_acceptance={"passed": True})
    with pytest.raises(ValueError, match="screening"):
        claim_fields("run", qualification, screening={"feasible": True})
    with pytest.raises(ValueError, match="eligible"):
        claim_fields("quick_design_row", qualification)
    with pytest.raises(ValueError, match="unsupported qualification definition"):
        claim_fields("run", {"definition": "result_qualification_v9"})
    with pytest.raises(ValueError, match="unsupported applicability evidence version"):
        claim_fields("run", None, applicability_evidence={"version": "future"})

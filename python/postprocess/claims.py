"""Map recorded qualification, range, study, and screening evidence to claim fields."""
from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
import math
from typing import Any

from tm1.physical_models.range_policy import assess_range

CLAIM_KINDS: tuple[str, ...] = ("run", "bo_condition", "quick_design_row")
DESIGN_GATES: tuple[str, ...] = (
    "execution",
    "convergence",
    "physical",
    "applicability",
    "metrics",
    "model_scope",
    "full_solve",
)
DESIGN_STATUSES: tuple[str, ...] = ("eligible", "rejected", "unverified")
OPTIMIZATION_STATUSES: tuple[str, ...] = ("passed", "failed", "unverified")
STUDY_EXCEPTIONS: tuple[str, ...] = ("none", "nu_re_extrapolation")
EXPERIMENTAL_VALIDATION_NOT_ESTABLISHED = "not_established"
_RANGE_GROUPS: tuple[str, ...] = ("inlet", "final")


def _optional_bool(value: Any, name: str) -> bool | None:
    if value is None:
        return None
    if type(value) is bool:
        return value
    raise ValueError(f"{name} must be a boolean or None")


def _all_known(values: Sequence[bool | None]) -> bool | None:
    if not values:
        return None
    if any(value is False for value in values):
        return False
    if any(value is None for value in values):
        return None
    return True


def _finite_float(value: Any) -> float | None:
    if value is None or type(value) is bool:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _extrema_value(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        if not raw:
            return None
        return _finite_float(raw[0])
    return _finite_float(raw)


def _source_list(raw: Any, name: str) -> list[str]:
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise ValueError(f"{name} must be a sequence of strings")
    return [str(part) for part in raw]


def _range_key(group: str, side: str, quantity: str, source: Sequence[str]) -> tuple[str, str, str, tuple[str, ...]]:
    return (group, side, quantity, tuple(source))


def _design_from_qualification(
    qualification: Mapping[str, Any], *, quick_design: bool
) -> dict[str, Any]:
    design_raw = qualification.get("design")
    design_map = design_raw if isinstance(design_raw, Mapping) else {}
    req_raw = design_map.get("requirements")
    requirements = req_raw if isinstance(req_raw, Mapping) else None

    gates: dict[str, bool | None] = {}
    for gate in DESIGN_GATES:
        if requirements is not None and gate in requirements:
            raw_gate = requirements[gate]
        elif gate != "full_solve" and isinstance(qualification.get(gate), Mapping):
            raw_gate = qualification[gate].get("passed")
        else:
            raw_gate = None
        gates[gate] = _optional_bool(raw_gate, f"design.gates.{gate}")

    if "status" in design_map and design_map["status"] is not None:
        status = str(design_map["status"])
        if status not in DESIGN_STATUSES:
            raise ValueError(f"unsupported design qualification status: {status!r}")
    elif "eligible" in design_map:
        eligible = _optional_bool(design_map["eligible"], "design.eligible")
        status = "eligible" if eligible is True else "rejected" if eligible is False else "unverified"
    else:
        status = "unverified"

    if quick_design and (status == "eligible" or gates["full_solve"] is True):
        raise ValueError("quick_design_row cannot carry an eligible full-solve qualification")

    raw_reasons = design_map.get("reasons")
    if isinstance(raw_reasons, Sequence) and not isinstance(raw_reasons, (str, bytes)):
        reasons = [str(reason) for reason in raw_reasons]
    else:
        reasons = [gate for gate in DESIGN_GATES if gates[gate] is not True]

    return {"status": status, "reasons": reasons, "gates": gates}


def _optimization_from_qualification(qualification: Mapping[str, Any]) -> dict[str, Any]:
    opt_raw = qualification.get("optimization")
    if not isinstance(opt_raw, Mapping):
        return {"status": "unverified", "reasons": [], "deferred": []}

    if "status" in opt_raw and opt_raw["status"] is not None:
        status = str(opt_raw["status"])
        if status not in OPTIMIZATION_STATUSES:
            raise ValueError(f"unsupported optimization qualification status: {status!r}")
    elif "passed" in opt_raw:
        passed = _optional_bool(opt_raw["passed"], "optimization.passed")
        status = "passed" if passed is True else "failed" if passed is False else "unverified"
    else:
        status = "unverified"

    raw_reasons = opt_raw.get("reasons", ())
    raw_deferred = opt_raw.get("deferred", ())
    reasons = [str(item) for item in raw_reasons] if isinstance(raw_reasons, Sequence) and not isinstance(raw_reasons, (str, bytes)) else []
    deferred = [str(item) for item in raw_deferred] if isinstance(raw_deferred, Sequence) and not isinstance(raw_deferred, (str, bytes)) else []
    return {"status": status, "reasons": reasons, "deferred": deferred}


def _extract_quick_statuses(screening: Mapping[str, Any] | None) -> list[Mapping[str, Any] | None]:
    if screening is None:
        return []
    if "percase" in screening:
        percase = screening["percase"]
        if isinstance(percase, (str, bytes)) or not isinstance(percase, Sequence):
            raise TypeError("screening.percase must be a sequence")
        statuses: list[Mapping[str, Any] | None] = []
        for entry in percase:
            if isinstance(entry, Mapping):
                run_status = entry.get("run_status")
                statuses.append(run_status if isinstance(run_status, Mapping) else None)
            else:
                statuses.append(None)
        return statuses
    if "run_status" in screening:
        run_status = screening["run_status"]
        return [run_status] if isinstance(run_status, Mapping) else [None]
    if "execution" in screening or "converged" in screening:
        return [screening]
    return []


def _quick_design_verdicts(screening: Mapping[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    statuses = _extract_quick_statuses(screening)
    exec_values: list[bool | None] = []
    conv_values: list[bool | None] = []
    for status in statuses:
        if status is None:
            exec_values.append(None)
            conv_values.append(None)
            continue
        raw_exec = status.get("execution")
        if raw_exec is None:
            exec_values.append(None)
        elif isinstance(raw_exec, str):
            exec_values.append(raw_exec == "completed")
        else:
            raise ValueError("quick design run_status.execution must be a string or None")
        conv_values.append(_optional_bool(status.get("converged"), "quick design run_status.converged"))

    gates: dict[str, bool | None] = {
        "execution": _all_known(exec_values),
        "convergence": _all_known(conv_values),
        "physical": None,
        "applicability": None,
        "metrics": None,
        "model_scope": None,
        "full_solve": None,
    }
    reasons = [gate for gate in DESIGN_GATES if gates[gate] is not True]
    design = {"status": "unverified", "reasons": reasons, "gates": gates}
    optimization = {"status": "unverified", "reasons": list(reasons), "deferred": []}
    return design, optimization


def _normalize_study_check(row: Mapping[str, Any]) -> dict[str, Any]:
    group = str(row["group"])
    side = str(row["side"])
    quantity = str(row["quantity"])
    source = _source_list(row["source"], "study_acceptance.extrapolation_checks.source")
    status = str(row["status"]) if row.get("status") is not None else None
    unit = str(row["unit"]) if row.get("unit") is not None else None

    observed_min = _extrema_value(row["minimum"]) if "minimum" in row else _finite_float(row.get("observed_min"))
    observed_max = _extrema_value(row["maximum"]) if "maximum" in row else _finite_float(row.get("observed_max"))

    allowed_min: float | None = None
    allowed_max: float | None = None
    allowed_bounds = row.get("allowed_bounds")
    if isinstance(allowed_bounds, Sequence) and not isinstance(allowed_bounds, (str, bytes)) and len(allowed_bounds) == 2:
        allowed_min = _finite_float(allowed_bounds[0])
        allowed_max = _finite_float(allowed_bounds[1])
    elif "allowed_min" in row or "allowed_max" in row:
        allowed_min = _finite_float(row.get("allowed_min"))
        allowed_max = _finite_float(row.get("allowed_max"))
    elif "bounds" in row and "captured" in row:
        assessed = assess_range(row)
        bounds = assessed.get("allowed_bounds")
        if bounds is not None:
            allowed_min = _finite_float(bounds[0])
            allowed_max = _finite_float(bounds[1])

    return {
        "group": group,
        "side": side,
        "quantity": quantity,
        "source": source,
        "status": status,
        "observed_min": observed_min,
        "observed_max": observed_max,
        "allowed_min": allowed_min,
        "allowed_max": allowed_max,
        "unit": unit,
    }


def _study_from_acceptance(
    study_acceptance: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], set[tuple[str, str, str, tuple[str, ...]]]]:
    if study_acceptance is None:
        return {"accepted": None, "strict_passed": None, "exception": "none", "checks": []}, set()

    accepted = _optional_bool(study_acceptance.get("passed"), "study_acceptance.passed")
    strict_passed = _optional_bool(study_acceptance.get("strict_passed"), "study_acceptance.strict_passed")
    extrapolated = _optional_bool(
        study_acceptance.get("nu_re_extrapolated", False),
        "study_acceptance.nu_re_extrapolated",
    )
    exception = "nu_re_extrapolation" if extrapolated is True else "none"

    raw_checks = study_acceptance.get("extrapolation_checks", ())
    if isinstance(raw_checks, (str, bytes)) or not isinstance(raw_checks, Sequence):
        raise TypeError("study_acceptance.extrapolation_checks must be a sequence")
    checks = [_normalize_study_check(row) for row in raw_checks]

    exception_keys: set[tuple[str, str, str, tuple[str, ...]]] = set()
    if exception == "nu_re_extrapolation":
        for row in checks:
            exception_keys.add(_range_key(row["group"], row["side"], row["quantity"], row["source"]))

    study = {
        "accepted": accepted,
        "strict_passed": strict_passed,
        "exception": exception,
        "checks": checks,
    }
    return study, exception_keys


def _flatten_evidence(
    applicability_evidence: Mapping[str, Any] | None,
) -> list[tuple[str, Mapping[str, Any]]]:
    if applicability_evidence is None:
        return []
    rows: list[tuple[str, Mapping[str, Any]]] = []
    for group in _RANGE_GROUPS:
        entries = applicability_evidence.get(group, ())
        if isinstance(entries, (str, bytes)) or not isinstance(entries, Sequence):
            raise TypeError(f"applicability_evidence.{group} must be a sequence")
        for sample in entries:
            if not isinstance(sample, Mapping):
                raise TypeError(f"applicability_evidence.{group} entries must be mappings")
            rows.append((group, sample))
    return rows


def _pair_checks_and_evidence(
    checks: Sequence[Mapping[str, Any]],
    evidence_rows: Sequence[tuple[str, Mapping[str, Any]]],
) -> list[tuple[Mapping[str, Any], Mapping[str, Any] | None]]:
    if not evidence_rows:
        return [(check, None) for check in checks]

    if len(evidence_rows) == len(checks) and all(
        str(check["group"]) == group
        and str(check["side"]) == str(sample.get("side"))
        and str(check["quantity"]) == str(sample.get("quantity"))
        and tuple(_source_list(check["source"], "qualification.applicability.checks.source"))
        == tuple(_source_list(sample["source"], "applicability_evidence.source"))
        for check, (group, sample) in zip(checks, evidence_rows)
    ):
        return [(check, sample) for check, (_, sample) in zip(checks, evidence_rows)]

    by_key: dict[tuple[str, str, str, tuple[str, ...]], deque[Mapping[str, Any]]] = defaultdict(deque)
    for group, sample in evidence_rows:
        key = _range_key(
            group,
            str(sample["side"]),
            str(sample["quantity"]),
            _source_list(sample["source"], "applicability_evidence.source"),
        )
        by_key[key].append(sample)

    paired: list[tuple[Mapping[str, Any], Mapping[str, Any] | None]] = []
    for check in checks:
        key = _range_key(
            str(check["group"]),
            str(check["side"]),
            str(check["quantity"]),
            _source_list(check["source"], "qualification.applicability.checks.source"),
        )
        queue = by_key.get(key)
        if not queue:
            paired.append((check, None))
            continue
        if len(queue) == 1:
            paired.append((check, queue.popleft()))
            continue
        target_status = str(check["status"])
        chosen: Mapping[str, Any] | None = None
        for index, candidate in enumerate(queue):
            if assess_range(candidate)["status"] == target_status:
                del queue[index]
                chosen = candidate
                break
        if chosen is None:
            chosen = queue.popleft()
        paired.append((check, chosen))
    return paired


def _build_range_entry(
    *,
    kind: str,
    group: str,
    side: str,
    quantity: str,
    source: list[str],
    status: str,
    sample: Mapping[str, Any] | None,
    assessed: Mapping[str, Any] | None,
    exception_keys: set[tuple[str, str, str, tuple[str, ...]]],
) -> dict[str, Any]:
    observed_min: float | None = None
    observed_max: float | None = None
    allowed_min: float | None = None
    allowed_max: float | None = None
    unit: str | None = None

    if sample is None:
        bounds_status = "not_recorded"
    else:
        if assessed is None:
            assessed = assess_range(sample)
        raw_unit = sample.get("unit")
        unit = str(raw_unit) if raw_unit is not None else None
        if sample.get("captured") is True:
            bounds_status = "recorded"
            observed_min = _extrema_value(sample.get("minimum"))
            observed_max = _extrema_value(sample.get("maximum"))
            allowed_bounds = assessed.get("allowed_bounds")
            if allowed_bounds is not None:
                allowed_min = _finite_float(allowed_bounds[0])
                allowed_max = _finite_float(allowed_bounds[1])
        else:
            bounds_status = "unavailable"

    study_exception = (
        kind == "bo_condition"
        and status == "outside_limit"
        and _range_key(group, side, quantity, source) in exception_keys
    )
    extrapolated = status == "within_margin" or study_exception

    return {
        "group": group,
        "side": side,
        "quantity": quantity,
        "source": source,
        "status": status,
        "observed_min": observed_min,
        "observed_max": observed_max,
        "allowed_min": allowed_min,
        "allowed_max": allowed_max,
        "unit": unit,
        "bounds_status": bounds_status,
        "extrapolated": extrapolated,
        "study_exception": study_exception,
    }


def _build_ranges(
    *,
    kind: str,
    qualification: Mapping[str, Any] | None,
    applicability_evidence: Mapping[str, Any] | None,
    exception_keys: set[tuple[str, str, str, tuple[str, ...]]],
) -> list[dict[str, Any]]:
    evidence_rows = _flatten_evidence(applicability_evidence)
    app_section = qualification.get("applicability") if qualification else None
    raw_checks = app_section.get("checks") if isinstance(app_section, Mapping) else None

    if isinstance(raw_checks, Sequence) and not isinstance(raw_checks, (str, bytes)) and raw_checks:
        paired = _pair_checks_and_evidence(raw_checks, evidence_rows)
        return [
            _build_range_entry(
                kind=kind,
                group=str(check["group"]),
                side=str(check["side"]),
                quantity=str(check["quantity"]),
                source=_source_list(check["source"], "qualification.applicability.checks.source"),
                status=str(check["status"]),
                sample=sample,
                assessed=None,
                exception_keys=exception_keys,
            )
            for check, sample in paired
        ]

    if evidence_rows:
        ranges: list[dict[str, Any]] = []
        for group, sample in evidence_rows:
            assessed = assess_range(sample)
            ranges.append(
                _build_range_entry(
                    kind=kind,
                    group=group,
                    side=str(sample["side"]),
                    quantity=str(sample["quantity"]),
                    source=_source_list(sample["source"], "applicability_evidence.source"),
                    status=str(assessed["status"]),
                    sample=sample,
                    assessed=assessed,
                    exception_keys=exception_keys,
                )
            )
        return ranges

    return []


def claim_fields(
    kind: str,
    qualification: Mapping[str, Any] | None = None,
    *,
    applicability_evidence: Mapping[str, Any] | None = None,
    study_acceptance: Mapping[str, Any] | None = None,
    screening: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return independent claim fields from stored verdicts and evidence.

    This function maps recorded verdicts without changes and computes no
    physics. Supported ``kind`` values are ``"run"``, ``"bo_condition"``,
    and ``"quick_design_row"``.
    """
    if kind not in CLAIM_KINDS:
        raise ValueError(f"unsupported claim kind: {kind!r}")
    if study_acceptance is not None and kind != "bo_condition":
        raise ValueError("study_acceptance applies only to bo_condition claims")
    if screening is not None and kind != "quick_design_row":
        raise ValueError("screening applies only to quick_design_row claims")
    if qualification is not None and not isinstance(qualification, Mapping):
        raise TypeError("qualification must be a mapping or None")
    if applicability_evidence is not None and not isinstance(applicability_evidence, Mapping):
        raise TypeError("applicability_evidence must be a mapping or None")
    if study_acceptance is not None and not isinstance(study_acceptance, Mapping):
        raise TypeError("study_acceptance must be a mapping or None")
    if screening is not None and not isinstance(screening, Mapping):
        raise TypeError("screening must be a mapping or None")

    if qualification and "definition" in qualification and qualification["definition"] != "result_qualification_v1":
        raise ValueError(f"unsupported qualification definition: {qualification['definition']!r}")
    if (
        applicability_evidence
        and "version" in applicability_evidence
        and applicability_evidence["version"] != "applicability_evidence_v1"
    ):
        raise ValueError(
            f"unsupported applicability evidence version: {applicability_evidence['version']!r}"
        )

    if kind == "quick_design_row" and not qualification:
        design, optimization = _quick_design_verdicts(screening)
    elif qualification:
        design = _design_from_qualification(qualification, quick_design=(kind == "quick_design_row"))
        optimization = _optimization_from_qualification(qualification)
    else:
        design = {
            "status": "unverified",
            "reasons": [],
            "gates": {gate: None for gate in DESIGN_GATES},
        }
        optimization = {"status": "unverified", "reasons": [], "deferred": []}

    exception_keys: set[tuple[str, str, str, tuple[str, ...]]] = set()
    study: dict[str, Any] | None = None
    if kind == "bo_condition":
        study, exception_keys = _study_from_acceptance(study_acceptance)

    ranges = _build_ranges(
        kind=kind,
        qualification=qualification,
        applicability_evidence=applicability_evidence,
        exception_keys=exception_keys,
    )

    output: dict[str, Any] = {
        "design": design,
        "optimization": optimization,
    }
    if study is not None:
        output["study"] = study
    output.update(
        {
            "ranges": ranges,
            "extrapolated": any(row["extrapolated"] for row in ranges),
            "screening": kind == "quick_design_row",
            "experimental_validation": EXPERIMENTAL_VALIDATION_NOT_ESTABLISHED,
        }
    )
    return output

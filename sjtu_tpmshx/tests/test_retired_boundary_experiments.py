"""Removed research controls fail before solving instead of changing meaning."""
from types import SimpleNamespace

import pytest

from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.solvers.backends.prepared_3d import build_execution_inputs


@pytest.mark.parametrize('key,value', [
    ('partial_B_closure', 'm4_effective_area'),
    ('partial_B_closure', 'per_cell_chi_b'),
    ('partial_B_closure', 'none'),
    ('m4_exponent', .67),
    ('chi_B_method', 'velocity_threshold'),
    ('chi_B_kernel_threshold', .3),
    ('chi_B_kernel_threshold', 0.),
    ('audit_zero_K_ffB_at_outlet', True),
    ('audit_zero_K_ffB_at_outlet', False),
    ('audit_h2_n_layers', 1),
    ('outer_anderson', True),
    ('outer_anderson', False),
    ('outer_anderson_m', 3),
    ('outer_anderson_trust', 5.),
    ('outer_anderson_patience', 3),
])
@pytest.mark.parametrize('entry', ['canonical', 'prepared', 'native'])
def test_retired_control_rejected_before_numerical_work(monkeypatch, key, value, entry):
    # Incomplete physical inputs deliberately prove the retired-key check
    # happens before preparation or a solver can consume any other setting.
    data = {key: value}
    message = ('Outer property Anderson is retired' if key.startswith('outer_anderson')
               else 'experiments are retired')
    with pytest.raises(ValueError, match=rf'{message}:.*{key}'):
        if entry == 'canonical':
            ComputeConfig.from_dict(data)
        elif entry == 'prepared':
            build_execution_inputs(SimpleNamespace(
                grid={'dimension': 3, 'length_unit': 'm'}, parameters=data))
        else:
            from sjtu_tpmshx.solvers.backends.cpp.full_3d import NativeFull3DDriver
            driver = NativeFull3DDriver.__new__(NativeFull3DDriver)
            driver.run_prepared(data, {})


@pytest.mark.parametrize('section', ['solver', 'flags'])
@pytest.mark.parametrize('key,value', [
    ('chi_B_method', 'mass_flux_threshold'), ('outer_anderson', False),
])
def test_nested_canonical_research_option_explains_retirement(section, key, value):
    with pytest.raises(ValueError, match=rf'retired:.*{key}'):
        ComputeConfig.from_dict({section: {key: value}})








def test_retired_audit_case_does_not_silently_run_empty_matrix(monkeypatch, tmp_path):
    from sjtu_tpmshx.validation.cases import audit_3d_conservation as audit
    monkeypatch.setattr('sys.argv', ['audit', '--cases', 'T4_H2', '--out', str(tmp_path/'audit.md')])
    monkeypatch.setattr(audit, 'run_case', lambda *args: pytest.fail('retired case ran'))
    with pytest.raises(SystemExit) as stopped:
        audit.main()
    assert stopped.value.code == 2

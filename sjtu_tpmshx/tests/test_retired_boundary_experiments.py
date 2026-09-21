"""Removed research controls fail before solving instead of changing meaning."""
from types import SimpleNamespace

import pytest

from sjtu_tpmshx.domain.compute_config import ComputeConfig
from sjtu_tpmshx.pipelines.run_stack_3d import _build_3d_problem
from sjtu_tpmshx.solvers.backends.python.three_d.execution import build_execution_inputs
from sjtu_tpmshx.solvers.backends.python.three_d import runtime


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
])
@pytest.mark.parametrize('entry', ['canonical', 'raw', 'prepared', 'runtime'])
def test_retired_control_rejected_before_numerical_work(monkeypatch, key, value, entry):
    def unexpected_solve(*args, **kwargs):
        pytest.fail('retired research control reached the numerical solver')
    monkeypatch.setattr(runtime.SIMPLESolver3D, 'solve', unexpected_solve)
    # Incomplete physical inputs deliberately prove the retired-key check
    # happens before preparation or a solver can consume any other setting.
    data = {key: value}
    with pytest.raises(ValueError, match=rf'experiments are retired:.*{key}'):
        if entry == 'canonical':
            ComputeConfig.from_dict(data)
        elif entry == 'raw':
            _build_3d_problem(data)
        elif entry == 'prepared':
            build_execution_inputs(SimpleNamespace(
                grid={'dimension': 3, 'length_unit': 'm'}, parameters=data))
        else:
            runtime.build_problem(data, {})


@pytest.mark.parametrize('section', ['solver', 'flags'])
def test_nested_canonical_research_option_explains_retirement(section):
    with pytest.raises(ValueError, match='experiments are retired:.*chi_B_method'):
        ComputeConfig.from_dict({section: {'chi_B_method': 'mass_flux_threshold'}})


@pytest.mark.parametrize('key', ['chi_B_field', 'chi_B_kernel_threshold'])
def test_removed_temperature_kwarg_is_rejected_at_call_boundary(key):
    from sjtu_tpmshx.solvers.ltne_energy_3d import solve_full_domain_3d
    with pytest.raises(TypeError, match=rf'unexpected keyword argument.*{key}'):
        solve_full_domain_3d(**{key: 0.})


def test_removed_temperature_positionals_cannot_become_mms_sources():
    from sjtu_tpmshx.solvers.ltne_energy_3d import solve_full_domain_3d
    # The old 52nd/53rd positional slots were chi_B_field/threshold.
    # Reject at binding, before these values can be mistaken for MMS sources.
    with pytest.raises(TypeError, match='positional arguments'):
        solve_full_domain_3d(*([None] * 51), object(), 0.)


@pytest.mark.parametrize('name,preceding_args', [
    ('_face_flux_weights', 4),
    ('_mass_weighted_T_out', 4),
    ('_mass_weighted_h_out', 6),
])
def test_removed_chi_face_positional_cannot_become_porosity(name, preceding_args):
    from sjtu_tpmshx.solvers.backends.python.three_d import flux
    with pytest.raises(TypeError, match='positional arguments'):
        getattr(flux, name)(*([None] * preceding_args), object())


def test_retired_audit_case_does_not_silently_run_empty_matrix(monkeypatch, tmp_path):
    from sjtu_tpmshx.validation.cases import audit_3d_conservation as audit
    monkeypatch.setattr('sys.argv', ['audit', '--cases', 'T4_H2', '--out', str(tmp_path/'audit.md')])
    monkeypatch.setattr(audit, '_run_3d_stack', lambda *args: pytest.fail('retired case ran'))
    with pytest.raises(SystemExit) as stopped:
        audit.main()
    assert stopped.value.code == 2

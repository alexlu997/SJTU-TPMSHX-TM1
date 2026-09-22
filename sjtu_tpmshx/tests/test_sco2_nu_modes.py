"""Current total amplitudes and synthetic parameters share one Nu call chain."""
from dataclasses import asdict, replace
import numpy as np
import pytest
from sjtu_tpmshx.domain.compute_config import ComputeConfig, Sco2NuConfig
from sjtu_tpmshx.models import fluid_props, nu_correlations as nu, tpms_calc

SYNTHETIC = Sco2NuConfig('experimental', .8, 1.2, 'synthetic-test-v1',
                        'unit test, not measured', 'synthetic; no experimental validation')


@pytest.mark.parametrize('topology,total', [('Diamond', 4.1064), ('Gyroid', 2.4824)])
def test_current_effective_parameters_roundtrip_and_apply_once(tmp_path, topology, total):
    from sjtu_tpmshx.models.local_heat_transfer import _sco2_hv_local_field

    settings = nu.sco2_effective_nu_config()
    assert settings.parameter_version == 'sco2-effective-nu-20260920-v1'
    assert settings.mode == 'experimental'
    path = tmp_path / 'current.json'
    config = ComputeConfig(sco2_nu=settings)
    config.to_json(path)
    assert ComputeConfig.from_json(path).sco2_nu == settings
    assert Sco2NuConfig().mode == 'cfd_smooth'
    args = (topology, np.array([10000., 20000.]), .4, 7., 3., 1.2)
    assert np.array_equal(fluid_props.get('sco2', sco2_nu=settings).nu(*args),
                          total * fluid_props.get('sco2').nu(*args))
    temperature = np.array([[350., 400.], [430., 470.]])
    args = (temperature, 10e6, np.ones((2, 2)), 500., .003, topology, 7.)
    smooth = _sco2_hv_local_field(*args)
    selected = _sco2_hv_local_field(*args, sco2_nu=settings)
    np.testing.assert_allclose(selected, total * smooth, rtol=1e-14)
    metadata = nu.sco2_nu_metadata(settings)
    assert metadata['alpha_D'] == 4.1064 and metadata['alpha_G'] == 2.4824
    assert metadata['parameter_version'] == settings.parameter_version


def test_modes_roundtrip_and_missing_parameters(tmp_path):
    cfg = ComputeConfig(sco2_nu=SYNTHETIC)
    path = tmp_path / 'config.json'
    cfg.to_json(path)
    assert ComputeConfig.from_json(path) == cfg
    old = asdict(cfg)
    del old['sco2_nu']
    assert ComputeConfig.from_dict(old).sco2_nu == Sco2NuConfig()
    assert ComputeConfig.from_dict({'sco2_nu': asdict(SYNTHETIC)}).sco2_nu == SYNTHETIC
    with pytest.raises(ValueError):
        ComputeConfig.from_dict({'sco2_nu': {'mode': 'experimental'}})
    for changes in ({'alpha_D': None}, {'alpha_G': 0}, {'alpha_D': float('nan')},
                    {'alpha_G': True}, {'source': ''}, {'mode': 'unknown'}):
        with pytest.raises(ValueError):
            replace(SYNTHETIC, **changes).validate()


@pytest.mark.parametrize('topology,alpha', [('Diamond', .8), ('Gyroid', 1.2)])
def test_shared_scalar_array_nu_and_unchanged_other_fluids(topology, alpha):
    args = (topology, np.array([1., 5000., 20000.]), .4, 7., 3., 1.2)
    base = fluid_props.get('sco2').nu(*args)
    assert np.array_equal(fluid_props.get('sco2', sco2_nu=Sco2NuConfig()).nu(*args), base)
    assert np.array_equal(fluid_props.get('sco2', sco2_nu=SYNTHETIC).nu(*args), alpha * base)
    for fluid in ('air', 'water'):
        assert fluid_props.get(fluid, sco2_nu=SYNTHETIC) is fluid_props.get(fluid)
    with pytest.raises(NotImplementedError):
        fluid_props.get('sco2', sco2_nu=SYNTHETIC).nu('Primitive', *args[1:])


@pytest.mark.parametrize('shape', [(2, 3), (2, 3, 2)])
def test_local_hv_multiplier_before_floor_without_extra_eos(monkeypatch, shape):
    from sjtu_tpmshx.models.local_heat_transfer import _sco2_hv_local_field
    from sjtu_tpmshx.models import sco2_props
    def properties(keys, T, P):
        assert keys == ('D', 'V', 'L', 'C')
        return np.array([np.full_like(T, value) for value in (2., .5, .25, 4.)])
    monkeypatch.setattr(sco2_props, 'sco2_prop', properties)
    T=np.full(shape, 320.); u=np.linspace(0.,10000.,T.size).reshape(shape)
    args=(T, 10e6, u, 10., 1., 'Diamond', 7.)
    raw=nu.nu_sco2_topo('Diamond', np.maximum(4*u,1.), 8., 7., 1000.)
    expected=2.5*np.maximum(.8*raw, nu.NU_LAM_FLOOR)
    observation = {}
    assert np.array_equal(_sco2_hv_local_field(*args, sco2_nu=SYNTHETIC, observation=observation), expected)
    assert observation['floor_cells'] == int(np.count_nonzero(.8*raw < nu.NU_LAM_FLOOR))
    assert observation['cells'] == T.size
    assert observation['stage'].endswith('(lagged temperature)')
    assert np.array_equal(_sco2_hv_local_field(*args), _sco2_hv_local_field(*args, sco2_nu=Sco2NuConfig()))


def test_compute_cache_separates_parameters_and_versions():
    args=('Diamond',7.,.6,1.,400.,10e6,16.,'sco2')
    tpms_calc.compute.cache_clear()
    base=tpms_calc.compute(*args)
    corrected=tpms_calc.compute(*args,sco2_nu=SYNTHETIC)
    assert corrected['Nu'] == .8*base['Nu']
    assert corrected['K_df'] == base['K_df'] and corrected['cF_df'] == base['cF_df']
    assert tpms_calc.compute(*args,sco2_nu=replace(SYNTHETIC,alpha_D=1.1))['Nu'] == 1.1*base['Nu']
    tpms_calc.compute(*args,sco2_nu=replace(SYNTHETIC,parameter_version='synthetic-v2'))
    assert tpms_calc.compute.cache_info().misses == 4
    assert tpms_calc.compute(*args) == base
    tpms_calc.compute.cache_clear()


def test_metadata_and_source_notice_are_independent_of_df():
    from sjtu_tpmshx.domain.compute_config import FluidConfig
    cfg = ComputeConfig(fluid_A=FluidConfig(type='sco2'), sco2_nu=SYNTHETIC)
    for df in ('cfd_smooth', 'experimental'):
        cfg.df_mode = df
        assert nu.sco2_nu_metadata(cfg.sco2_nu)['alpha_D'] == .8
        assert 'unit test, not measured' in nu.sco2_nu_notices(cfg)[0]
    cfg.sco2_nu = Sco2NuConfig()
    assert nu.sco2_nu_notices(cfg) == []
    assert 'alpha_D' not in nu.sco2_nu_metadata(cfg.sco2_nu)


def test_real_pipeline_heat_builders_share_selected_parameters():
    from types import SimpleNamespace
    from sjtu_tpmshx.domain.compute_config import FluidConfig, GeometryConfig
    from sjtu_tpmshx.preprocess.api import prepare_case
    from sjtu_tpmshx.solvers.backends.python.three_d.runtime import _build_hv_machinery
    from sjtu_tpmshx.preprocess.three_d.preparation import _parse_inputs_3d_cfg
    cfg = ComputeConfig(fluid_A=FluidConfig(type='sco2', u_mps=1., T_in_K=400., P_in_Pa=10e6),
                        fluid_B=FluidConfig(type='sco2', u_mps=1., T_in_K=350., P_in_Pa=10e6),
                        geometry=GeometryConfig(tpms='Diamond', Lz_m=.042))
    original = prepare_case(cfg, case_id='nu-default').parameters['static_properties']
    cfg.sco2_nu = SYNTHETIC
    selected = prepare_case(cfg, case_id='nu-selected').parameters['static_properties']
    for side in ('A', 'B'):
        assert selected[side]['A_0'] * selected[side]['H_sf'] == pytest.approx(
            .8 * original[side]['A_0'] * original[side]['H_sf'])
    cfg.solver.Nz = 2
    assert _parse_inputs_3d_cfg(cfg)['sco2_nu'] is SYNTHETIC
    # Actual production h_v builders, with a prepared geometric/problem seam;
    # no momentum or thermal PDE is run in this functional check.
    from sjtu_tpmshx.preprocess.thermal_geometry import prepare_thermal_geometry
    problem = SimpleNamespace(D_h=.003, L_mm_field=None, Lcell=7., Nx=2, Ny=3, Nz=2,
        P_inA=10e6, P_inB=10e6, T_inA=400., T_inB=350., eps=.7,
        fluid_type_A='sco2', fluid_type_B='sco2', mu_A=1e-5, mu_B=1e-5,
        rho_A=100., rho_B=200., sB=True, t_field_3d=None, t_wall=.6,
        tpms_type='Diamond', u_A=1., k_s=16., cfg={'sco2_nu': Sco2NuConfig(),
        'thermal_geometry': prepare_thermal_geometry('Diamond', 7., .6, 16.),
        'roughness_resolved': dict(mode='norris_1a', eps_m=100e-6)})
    cfd = _build_hv_machinery(problem)
    problem.cfg={**problem.cfg, 'sco2_nu': SYNTHETIC}
    exp = _build_hv_machinery(problem)
    assert np.allclose(exp.h_vA_field, .8*cfd.h_vA_field, rtol=1e-14)
    assert np.allclose(exp.h_vB_field, .8*cfd.h_vB_field, rtol=1e-14)
    for temperature in (400., np.full((2,3,2),400.)):
        args=(None,np.ones((2,3,2)),temperature,10e6,'sco2')
        assert np.allclose(exp._build_hv_local_3d(*args), .8*cfd._build_hv_local_3d(*args), rtol=1e-14)


def test_cli_preserves_selected_model_and_reports_it(tmp_path, monkeypatch, capsys):
    import json
    from types import SimpleNamespace
    from sjtu_tpmshx.cli import main
    from sjtu_tpmshx.domain.compute_result import ComputeResult
    import sjtu_tpmshx.controllers.compute_pipeline as pipeline
    path=tmp_path/'synthetic-config.json'
    ComputeConfig(sco2_nu=SYNTHETIC).to_json(path)
    expected=nu.sco2_nu_metadata(SYNTHETIC)
    def dispatch(cfg):
        assert cfg.sco2_nu == SYNTHETIC
        return SimpleNamespace(run=lambda: ComputeResult(converged=True, metadata={'sco2_nu':expected}))
    monkeypatch.setattr(pipeline,'pipeline_for',dispatch)
    assert main([str(path),'--json']) == 0
    assert json.loads(capsys.readouterr().out)['metadata']['sco2_nu'] == expected

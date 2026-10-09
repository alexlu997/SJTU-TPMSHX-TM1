"""Native empirical/EOS properties and QD Nu against current Python owners.

Frozen before execution: rtol=2e-10 throughout; SI atol rho/mu/k/cp/Pr =
2e-8/2e-14/2e-10/2e-5/1e-10, Nu=1e-10, melting T=2e-8 K.
Fit extrapolation remains computable. Primitive native calls do not emit the
future run-layer warning records; Python warning evidence is checked separately.
"""
import csv
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
FIELDS = ('rho','mu','k','cp','Pr','Nu','melting_K')
PROPERTY_ATOL = (2e-8,2e-14,2e-10,2e-5,1e-10)
REFERENCE = r'''
import json,sys,warnings
sys.path.insert(0,sys.argv[1])
import CoolProp.CoolProp as CP
from sjtu_tpmshx.models.design_fluids import fluid_props,fluid_nu
from sjtu_tpmshx.models.fluid_props import check_water_state
from sjtu_tpmshx.models.fluid_props import get as fluid_model
from sjtu_tpmshx.models.nu_correlations import nu_from_Re,nu_water_topo,nu_sco2_selected
from sjtu_tpmshx.models.roughness import nu_extra_factor
from sjtu_tpmshx.domain.compute_config import Sco2NuConfig
from sjtu_tpmshx.domain.run_warnings import warning_scope,warning_messages
payload=json.load(sys.stdin)
if payload.get('mode')=='boundaries':
    state=CP.AbstractState('HEOS','Water')
    print(json.dumps(dict(psat=CP.PropsSI('P','T',380.,'Q',0.,'Water'),
        melting=[state.melting_line(CP.iT,CP.iP,p) for p in (101325.,200000.)])))
    raise SystemExit(0)
rows=[]
for inp in payload['rows']:
    row=dict(id=inp['id'],status=0,values=[float('nan')]*7,error='',warnings=[])
    records={}
    with warnings.catch_warnings(record=True) as caught,warning_scope(records):
        warnings.simplefilter('always')
        try:
            op,fluid,a,b,c=inp['op'],inp['fluid'],inp['a'],inp['b'],inp.get('c',0.)
            if op=='props':
                props=fluid_props(fluid,a,b)
                row['values'][:5]=[float(getattr(props,k)) for k in ('rho','mu','k','cp','Pr')]
            elif op=='transport':
                model=fluid_model(fluid)
                values=[float(getattr(model,k)(a,b)) for k in ('rho','mu','k','cp')]
                row['values'][:5]=values+[values[1]*values[3]/values[2]]
            elif op=='water':
                check_water_state('water',a,b)
                state=CP.AbstractState('HEOS','Water')
                row['values'][6]=state.melting_line(CP.iT,CP.iP,b)
            elif op=='nu':
                row['values'][5]=float(fluid_nu(fluid,inp['topology'],a,.37,b*1000.,c*1000.))
            elif op=='fullnu':
                pr,multiplier=inp['pr'],inp['multiplier']
                if fluid=='air':
                    value=nu_from_Re(inp['topology'],a,.37,b*1000.,c*1000.)
                elif fluid=='co2':
                    from sjtu_tpmshx.models.co2_correlations import nusselt
                    value=nusselt(inp['topology'],a,pr,b*1000.,c*1000.)
                elif fluid=='water':
                    value=nu_water_topo(inp['topology'],a,pr)
                else:
                    settings=Sco2NuConfig(mode='experimental',alpha_D=multiplier,alpha_G=multiplier,
                        parameter_version='qualification',source='qualification',applicability='qualification')
                    value=nu_sco2_selected(inp['topology'],a,pr,b*1000.,c*1000.,settings=settings)
                row['values'][5]=float(value)
            elif op=='roughness':
                row['values'][5]=nu_extra_factor(a,inp['roughness'],eps_um=b*1e6,D_h_mm=c*1000.)
            else: raise ValueError('unknown reference operation')
        except (ValueError,RuntimeError) as error:
            row.update(status=1,error=str(error),values=[float('nan')]*7)
    row['warnings']=list(warning_messages(records))+[str(w.message) for w in caught]
    rows.append(row)
print(json.dumps(rows))
'''


def props(identifier,fluid,temperature=300.,pressure=2e5,*,op='props'):
    return dict(id=identifier,op=op,fluid=fluid,a=temperature,b=pressure)


def nu(identifier,fluid,topology,re=3000.,length=.007,diameter=.003):
    return dict(id=identifier,op='nu',fluid=fluid,topology=topology,a=re,b=length,c=diameter)


@pytest.fixture(scope='module')
def property_program():
    system = 'macos' if sys.platform == 'darwin' else ('windows' if os.name == 'nt' else 'linux')
    arch = platform.machine().lower()
    if arch in ('amd64','x86_64'): arch = 'x64' if os.name == 'nt' else 'x86_64'
    default = ROOT / '.cache/native-deps/build' / f'pilot-{system}-{arch}' / (
        'fluid_properties_smoke.exe' if os.name == 'nt' else 'fluid_properties_smoke')
    path = Path(os.environ.get('TPMSHX_FLUID_PROPERTIES_SMOKE',str(default))).resolve()
    if not path.is_file():
        message = 'native properties executable is not built: '+str(path)
        if 'TPMSHX_FLUID_PROPERTIES_SMOKE' in os.environ or os.environ.get('TPMSHX_REQUIRE_NATIVE_DEPS_TESTS') == '1':
            pytest.fail(message)
        pytest.skip(message)
    env = {k:v for k,v in os.environ.items() if not k.startswith(('PYTHON','CONDA'))
           and k not in ('VIRTUAL_ENV','DYLD_LIBRARY_PATH','DYLD_FALLBACK_LIBRARY_PATH')}
    if os.name != 'nt': env['PATH'] = '/usr/bin:/bin'
    return path,env


@pytest.fixture(scope='module')
def native_properties(property_program):
    path,env = property_program
    def run(rows=(),*,workers=1,text=None):
        if text is None:
            lines=[]
            for row in rows:
                suffix = ('{topology} {a:.17g} {b:.17g} {c:.17g}' if row['op'] in ('nu','fullnu')
                          else '{a:.17g} {b:.17g}').format(**row)
                if row['op']=='fullnu':
                    suffix+=' {pr:.17g} {multiplier:.17g}'.format(**row)
                elif row['op']=='roughness':
                    suffix='{roughness} {a:.17g} {b:.17g} {c:.17g}'.format(**row)
                lines.append('{id} {op} {fluid} '.format(**row)+suffix+'\n')
            text=''.join(lines)
        process=subprocess.run([str(path),'--workers',str(workers)],cwd=ROOT,env=env,
            input=text,text=True,capture_output=True,timeout=60,check=True)
        lines=process.stdout.splitlines()
        assert lines[0]=='#workers\t'+str(workers)
        results=list(csv.DictReader(io.StringIO('\n'.join(lines[1:])),delimiter='\t'))
        for row in results:
            row['status']=int(row['status'])
            row['values']=[float(row[key]) for key in FIELDS]
            row['error']=bytes.fromhex(row['error_hex']).decode('utf-8')
        return results
    return run


@pytest.fixture(scope='module')
def python_properties():
    def run(rows=(),*,mode='states'):
        process=subprocess.run([sys.executable,'-c',REFERENCE,str(ROOT)],cwd=ROOT,
            input=json.dumps(dict(rows=rows,mode=mode)),text=True,capture_output=True,timeout=60,check=True)
        return json.loads(process.stdout)
    return run


def equal_rows(actual,expected,requests):
    assert len(actual)==len(expected)==len(requests)
    for got,want,request in zip(actual,expected,requests):
        assert got['id']==want['id']==request['id']
        assert got['status']==want['status'],(request,got,want)
        if got['status']:
            assert got['error'] and np.isnan(got['values']).all()
            continue
        assert not got['error']
        if request['op'] in ('props','transport'):
            for value,target,atol in zip(got['values'][:5],want['values'][:5],PROPERTY_ATOL):
                assert value == pytest.approx(target,rel=2e-10,abs=atol)
            assert np.isnan(got['values'][5:]).all()
        elif request['op'] in ('nu','fullnu','roughness'):
            np.testing.assert_allclose(got['values'][5],want['values'][5],rtol=2e-10,atol=1e-10,equal_nan=True)
            assert np.isnan(got['values'][:5]+got['values'][6:]).all()
        else:
            assert got['values'][6] == pytest.approx(want['values'][6],rel=0.,abs=2e-8)
            assert np.isnan(got['values'][:6]).all()


@pytest.mark.parametrize('fluid',['air','water','sco2'])
def test_properties_follow_current_empirical_and_heos_owners(native_properties,python_properties,fluid):
    if fluid=='air':
        states=[(t,p) for t in (200.,250.,273.15,300.,500.,1000.,1100.) for p in (1e4,101325.,2e5,1e6)]
    elif fluid=='water':
        states=[(274.,101325.),(300.,2e5),(320.,2e5),(350.,2e5),(363.15,2e5),
                (380.,2e5),(400.,3e6),(500.,3e6),(300.,20e6)]
    else:
        states=[(t,p) for t in (280.,300.,304.,307.,310.,320.,480.,700.)
                for p in (7.9e6,8e6,9e6,12e6,16e6)]
    rows=[props(str(i),fluid,t,p) for i,(t,p) in enumerate(states)]
    expected=python_properties(rows)
    assert all(row['status']==0 for row in expected)
    equal_rows(native_properties(rows),expected,rows)


def test_water_polynomials_preserve_separate_numpy_operations(native_properties):
    from sjtu_tpmshx.models.tpms_props import water_density, water_conductivity
    temperature = np.linspace(275., 362., 127)
    rows = [props(str(i), 'water', float(t), op='transport') for i, t in enumerate(temperature)]
    actual = np.array([row['values'] for row in native_properties(rows)])
    np.testing.assert_array_equal(actual[:, 0], water_density(temperature))
    np.testing.assert_array_equal(actual[:, 2], water_conductivity(temperature))


def test_water_viscosity_keeps_original_pow_at_actual_outer_state(native_properties):
    from sjtu_tpmshx.models.tpms_props import water_viscosity
    # First differing property sample from a real 24x22 coarse outer replay:
    # replacing pow(10, exponent) with exp10 moved this sample by one ulp.
    t = 300.0624090934865
    temperature = np.array([np.nextafter(t, -np.inf), t, np.nextafter(t, np.inf)])
    rows = [props(str(i), 'water', float(value), op='transport') for i, value in enumerate(temperature)]
    actual = np.array([row['values'][1] for row in native_properties(rows)])
    np.testing.assert_array_equal(actual, water_viscosity(temperature))


@pytest.mark.parametrize('fluid',['air','water','sco2'])
@pytest.mark.parametrize('topology',['Diamond','Gyroid'])
def test_qd_nu_keeps_fixed_representative_pr_and_no_local_floor(native_properties,python_properties,fluid,topology):
    rows=[nu(f'{i}-{j}',fluid,topology,re,length,diameter)
          for i,re in enumerate((0.,.5,1.,89.,90.,400.,2600.,16000.,51000.,128000.,200000.))
          for j,(length,diameter) in enumerate(((.004,.001),(.007,.003),(.008,.005)))]
    expected=python_properties(rows); actual=native_properties(rows)
    assert all(row['status']==0 for row in expected)
    equal_rows(actual,expected,rows)
    if fluid=='air': assert actual[0]['values'][5]==0.
    else:
        for j in range(3):
            assert actual[j]['values'][5]==actual[3+j]['values'][5]==actual[6+j]['values'][5]


def test_fit_extrapolation_warns_in_python_and_remains_computable(native_properties,python_properties):
    rows=[props('low-air','air',190.),props('high-air','air',1200.),
          props('warm-water','water',400.,3e6),nu('low-nu','air','Diamond',0.),
          nu('high-water-nu','water','Gyroid',60000.),nu('representative-co2','sco2','Gyroid',3000.)]
    expected=python_properties(rows)
    assert all(row['status']==0 and row['warnings'] for row in expected)
    equal_rows(native_properties(rows),expected,rows)
    assert any('representative Pr' in message for message in expected[-1]['warnings'])


@pytest.mark.parametrize('fluid',['air','water','sco2'])
@pytest.mark.parametrize('topology',['Diamond','Gyroid'])
def test_full_nu_uses_actual_pr_and_selected_multiplier_before_floor(native_properties,python_properties,fluid,topology):
    rows=[]
    for re in (0.,.5,1.,400.,16000.,200000.):
        for pr in (.21,.72,7.,125.):
            for multiplier in (.03,1.,2.7):
                rows.append(dict(nu(str(len(rows)),fluid,topology,re),op='fullnu',pr=pr,multiplier=multiplier))
    actual=native_properties(rows)
    equal_rows(actual,python_properties(rows),rows)
    # The low-Re/factor case must remain below the caller's laminar floor.
    assert actual[0]['values'][5]<4.36
    if fluid!='sco2':
        assert actual[0]['values'][5]==actual[1]['values'][5]==actual[2]['values'][5]


def test_full_nu_invalid_actual_pr_or_multiplier_recovers(native_properties):
    text='\n'.join(('a fullnu water Diamond 1000 .007 .003 nan 1',
        'b fullnu sco2 Gyroid 1000 .007 .003 7 0',
        'c fullnu air Diamond 1000 .007 .003 0 1',
        'd fullnu sco2 Gyroid 1000 .007 .003 7 1'))+'\n'
    actual=native_properties(text=text)
    assert [r['status'] for r in actual]==[1,1,1,0]
    assert all(np.isnan(r['values']).all() for r in actual[:3])
    assert actual[-1]['values'][5]>0


@pytest.mark.parametrize('mode',['baseline','norris_1a','bhatti_shah_1b'])
def test_optional_air_roughness_preserves_original_formula(native_properties,python_properties,mode):
    rows=[dict(id=str(i),op='roughness',fluid='air',roughness=mode,a=re,b=eps,c=diameter)
          for i,(re,eps,diameter) in enumerate((
              (0.,1e-4,.003),(1.,0.,.001),(3000.,0.,.003),(10000.,3.1e-5,.003),
              (50000.,1e-4,.004),(1e6,1e-5,.006)))]
    actual=native_properties(rows)
    equal_rows(actual,python_properties(rows),rows)
    if mode!='bhatti_shah_1b':
        assert all(r['values'][5]==1 for r in actual)
    else:
        assert np.isnan(actual[0]['values'][5])  # no invented zero-Re fallback


def test_full_transport_keeps_actual_water_phase_guard_separate(native_properties,python_properties):
    rows=[props('actual-valid','water',400.,3e6), props('sample-at-pin','water',400.,2e5,op='transport'),
          props('qd-invalid','water',400.,2e5),props('hot-air','air',450.,160000.,op='transport'),
          props('near-co2','sco2',304.,8e6,op='transport'),props('bad-co2','sco2',304.,7e6,op='transport')]
    actual=native_properties(rows)
    equal_rows(actual,python_properties(rows),rows)
    assert [r['status'] for r in actual]==[0,0,1,0,0,1]
    np.testing.assert_array_equal(actual[0]['values'][:5],actual[1]['values'][:5])


def test_empirical_pressure_dependence_is_preserved(native_properties,python_properties):
    rows=[props(f'{fluid}-{p}',fluid,350.,p) for fluid in ('air','water') for p in (2e5,2e6)]
    actual=native_properties(rows); equal_rows(actual,python_properties(rows),rows)
    assert actual[1]['values'][0] == pytest.approx(10*actual[0]['values'][0],rel=2e-10)
    np.testing.assert_array_equal(actual[0]['values'][1:5],actual[1]['values'][1:5])
    np.testing.assert_array_equal(actual[2]['values'][:5],actual[3]['values'][:5])


def test_water_saturation_melting_high_pressure_and_co2_domain_guards(native_properties,python_properties):
    bounds=python_properties(mode='boundaries')
    rows=[props('sat-'+str(i),'water',380.,bounds['psat']*ratio) for i,ratio in enumerate((.999,1.,1.001))]
    for i,(p,melting) in enumerate(zip((101325.,2e5),bounds['melting'])):
        rows.extend(props(f'melt-{i}-{j}','water',melting+delta,p,op='water')
                    for j,delta in enumerate((-.001,0.,.001)))
    rows.extend(props('bad-water-'+str(i),'water',t,p) for i,(t,p) in enumerate(
        ((260.,101325.),(300.,30e6),(700.,30e6),(float('nan'),2e5),(300.,0.),(300.,float('inf')))))
    rows.extend(props('bad-co2-'+str(i),'sco2',t,p) for i,(t,p) in enumerate(
        ((279.99,9e6),(700.01,9e6),(300.,7.899e6),(300.,16.001e6),(float('nan'),9e6))))
    expected=python_properties(rows); actual=native_properties(rows)
    equal_rows(actual,expected,rows)
    assert [r['status'] for r in actual[:3]]==[1,1,0]
    assert [r['status'] for r in actual[3:9]]==[1,1,0,1,1,0]
    assert 'high-pressure liquid' in next(r['error'] for r in actual if r['id']=='bad-water-1')


def test_invalid_then_valid_requests_do_not_publish_stale_values(native_properties,python_properties):
    rows=[props('water-first','water',300.),props('water-invalid','water',700.,30e6),
          props('water-recovered','water',320.),props('co2-first','sco2',304.,8e6),
          props('co2-invalid','sco2',300.,7e6),props('co2-recovered','sco2',500.,12e6)]
    equal_rows(native_properties(rows),python_properties(rows),rows)


def test_two_fresh_contexts_construct_eos_concurrently_and_keep_input_order(native_properties,python_properties):
    rows=[]
    for i in range(8):
        rows.extend([props(f'co2a-{i}','sco2',304.+i,8e6),props(f'waterb-{i}','water',300.+i),
                     props(f'watera-{i}','water',370.+i,2e5),props(f'co2b-{i}','sco2',480.+i,12e6)])
    rows.insert(10,props('bad-middle','water',700.,30e6))
    expected=python_properties(rows)
    equal_rows(native_properties(rows,workers=1),expected,rows)
    equal_rows(native_properties(rows,workers=2),expected,rows)
    equal_rows(native_properties(rows[::-1],workers=2),expected[::-1],rows[::-1])


def test_protocol_and_primitive_reject_nonfinite_nonpositive_inputs(native_properties):
    text='\n'.join(('bad','a props air nope 200000','b props oil 300 200000',
        'c props air nan 200000','d props air 300 0','e props air -1 200000',
        'f nu air Diamond -1 .007 .003','g nu water Gyroid 1000 0 .003',
        'h nu sco2 Gyroid 1000 .007 inf','i nu air Unknown 1000 .007 .003',
        'j props air 10000 200000','k props air 300 200000'))+'\n'
    actual=native_properties(text=text)
    assert len(actual)==12
    assert all(row['status'] and row['error'] and np.isnan(row['values']).all() for row in actual[:-1])
    assert actual[-2]['status']==2  # finite input producing nonphysical cp
    assert actual[-1]['status']==0 and all(np.isfinite(actual[-1]['values'][:5]))


@pytest.mark.parametrize('topology', ['Diamond', 'Gyroid'])
def test_co2_full_nu_and_heos_are_independent_of_sco2_selection(native_properties, python_properties, topology):
    rows = [props(f'p{i}', 'co2', t, p) for i, (t, p) in enumerate(
        ((280., 3e6), (300., 5e6), (300., 9e6), (340., 8e6), (360., 12e6)))]
    rows += [dict(nu(f'n{i}', 'co2', topology, re), op='fullnu', pr=pr, multiplier=m)
             for i, (re, pr, m) in enumerate((
                 (.5, 1.2, .1), (1., 2., 1.), (3000., 1.2, 4.), (60000., 3., 1.)))]
    expected = python_properties(rows)
    assert all(row['status'] == 0 for row in expected)
    equal_rows(native_properties(rows, workers=2), expected, rows)


def test_co2_native_rejects_invalid_states_and_recovers(native_properties):
    import CoolProp.CoolProp as CP
    requests = [props('below-triple', 'co2', 200., 1e6),
                props('saturation', 'co2', 280., CP.PropsSI('P', 'T', 280., 'Q', 0., 'CO2')),
                props('critical', 'co2', CP.PropsSI('Tcrit', 'CO2'), CP.PropsSI('Pcrit', 'CO2')),
                props('valid', 'co2', 340., 8e6)]
    actual = native_properties(requests)
    assert all(row['status'] != 0 and row['error'] for row in actual[:3])
    assert actual[-1]['status'] == 0

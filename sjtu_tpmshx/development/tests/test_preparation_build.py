"""Preparation builds use locked EOS inputs without the full solver."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from engineering.scripts import build_native_dependencies as native


@pytest.fixture(params=['macos-arm64', 'windows-x64'])
def preparation_build(request, tmp_path, monkeypatch):
    host = request.param
    root = tmp_path / 'project'
    cache = root / '.cache/native-deps'
    python = root / 'configured python'
    lock = root / 'engineering/requirements/selected-role.txt'
    cmake = cache / 'tools/bin' / ('cmake.exe' if host == 'windows-x64' else 'cmake')
    cmake.parent.mkdir(parents=True)
    cmake.write_bytes(b'locked tool placeholder')
    for role in ('solver', 'preparation'):
        library = native.coolprop_library(cache, host, role)
        library.parent.mkdir(parents=True, exist_ok=True)
        library.write_bytes(b'locked static EOS input')
        archive_role = 'preparation' if host == 'macos-arm64' and role == 'preparation' else 'solver'
        flags = '-Os -DNDEBUG' if archive_role == 'preparation' else '-O3 -DNDEBUG'
        (native.coolprop_build_dir(cache, host, role) / 'coolprop-build.json').write_text(json.dumps(
            dict(role=archive_role, platform=host, version='8.0.0', revision='locked-eos',
                 compile_groups=[dict(language=language, compileCommandFragments=[dict(fragment=flags)])
                                 for language in ('C', 'CXX')],
                 toolchains=[dict(language='CXX', compiler=dict(path='/actual/compiler'))],
                 sdk=dict(source='actual configured SDK'))))
    library = native.coolprop_library(cache, host, 'preparation')
    generator = 'Visual Studio 17 2022' if host == 'windows-x64' else 'Unix Makefiles'
    monkeypatch.setattr(native, 'ROOT', root)
    monkeypatch.setattr(native, 'LOCK', {'cmake': {'version': '4.4.4', host: {
        'generator': generator, 'executable': cmake.relative_to(cache/'tools').as_posix()}}
        , 'sources': {'coolprop': {'version': '8.0.0', 'commit': 'locked-eos'}}})
    sources, commands = [], []
    monkeypatch.setattr(native, 'verify_sources', lambda cache, **kw: sources.append(kw))

    def forbidden(*args, **kwargs):
        pytest.fail('independent preparation entered a full-solver or LU operation')

    for name in ('apply_lu_patch', 'verify_lu_patch', 'fetch_source'):
        monkeypatch.setattr(native, name, forbidden)

    def run(command, *args, **kwargs):
        commands.append(tuple(str(value) for value in command))
        return 'cmake version 4.4.4\n' if '--version' in command else ''

    monkeypatch.setattr(native, 'run', run)
    monkeypatch.setattr(native, 'verify_model_exports', lambda *args: None)
    def backend(version, version_count, revision, revision_count, error, error_count):
        version.value, revision.value, error.value = b'8.0.0', b'locked-eos', b''
        return 0
    monkeypatch.setattr(native.ct, 'CDLL', lambda path: SimpleNamespace(
        tpmshx_preparation_property_backend_v1=backend))
    return host, root, cache, python, lock, cmake, library, sources, commands


def test_preparation_build_checks_role_and_uses_only_standalone_target(preparation_build):
    host, root, cache, python, lock, cmake, library, sources, commands = preparation_build
    native.build(cache, host, python, lock, 'preparation')
    assert commands[:2] == [
        (str(python), '-m', 'sjtu_tpmshx.development.runs.tools.check_locked_environment', str(lock)),
        (str(python), '-m', 'pip', 'check')]
    assert sources == [{'models_only': True}]
    generated = cache/'generated/tpmshx'
    assert (str(python), '-m', 'engineering.scripts.generate_native_model_coefficients', '--output',
            str(generated/'model_coefficients.hpp'), '--df-output', str(generated/'preparation_df_data.hpp')) in commands
    configure, = (command for command in commands if '-S' in command)
    assert configure[0] == str(cmake)
    assert configure[configure.index('-S')+1] == str(root/'sjtu_tpmshx/solvers/native/preparation')
    assert configure[configure.index('-B')+1] == str(cache/'build'/('preparation-'+host))
    assert f'-DTPMSHX_COOLPROP_LIBRARY={library}' in configure
    assert not any('dependency-pilot' in value or 'SuperLU' in value for value in configure)
    build, = (command for command in commands if '--build' in command)
    assert build[build.index('--build')+1] == str(cache/'build'/('preparation-'+host))


def test_preparation_verify_does_not_load_full_solver_programs(preparation_build):
    host, _, cache, _, _, cmake, _, sources, commands = preparation_build
    native.verify(cache, host, 'preparation')
    assert sources == [{'models_only': True}]
    assert commands[0] == (str(cmake), '--version')
    suffix = '.exe' if host == 'windows-x64' else ''
    names = {Path(command[0]).name for command in commands[1:]}
    assert names == {name+suffix for name in ('geometry_c_static', 'geometry_c_shared',
        'geometry_kernel_smoke', 'preparation_c_static', 'preparation_c_shared')}


def test_pilot_build_keeps_solver_archive_and_builds_preparation_separately(preparation_build, monkeypatch):
    host, root, cache, python, lock, _, preparation_library, _, commands = preparation_build
    monkeypatch.setattr(native, 'apply_lu_patch', lambda cache: None)
    native.build(cache, host, python, lock, 'pilot')
    configure = [command for command in commands if '-S' in command]
    assert len(configure) == 2
    for command, name, source, role in zip(configure, ('pilot', 'preparation'),
            ('dependency-pilot', 'preparation'), ('solver', 'preparation')):
        assert command[command.index('-B')+1] == str(cache/'build'/f'{name}-{host}')
        assert command[command.index('-S')+1] == str(root/'sjtu_tpmshx/solvers/native'/source)
        assert f'-DTPMSHX_COOLPROP_LIBRARY={native.coolprop_library(cache, host, role)}' in command
    solver_library = native.coolprop_library(cache, host, 'solver')
    assert (solver_library == preparation_library) is (host == 'windows-x64')


def test_missing_or_wrong_archive_record_stops_preparation_build(preparation_build):
    host, _, cache, python, lock, _, _, _, commands = preparation_build
    path = native.coolprop_build_dir(cache, host, 'preparation')/'coolprop-build.json'
    record = json.loads(path.read_text())
    record['revision'] = 'different-source'
    path.write_text(json.dumps(record))
    with pytest.raises(RuntimeError, match='required role/source'):
        native.build(cache, host, python, lock, 'preparation')
    assert not any('-S' in command for command in commands)
    path.unlink()
    with pytest.raises(RuntimeError, match='metadata first'):
        native.build(cache, host, python, lock, 'preparation')


def test_effective_optimization_record_cannot_mislabel_solver_archive(preparation_build):
    host, _, cache, _, _, _, _, _, _ = preparation_build
    if host != 'macos-arm64':
        return
    path = native.coolprop_build_dir(cache, host, 'solver')/'coolprop-build.json'
    record = json.loads(path.read_text())
    record['compile_groups'][1]['compileCommandFragments'][0]['fragment'] = '-O3 -DNDEBUG -Os'
    path.write_text(json.dumps(record))
    with pytest.raises(RuntimeError, match='effective optimization differs from solver'):
        native.coolprop_build_record(cache, host, 'solver')


def test_full_verify_uses_independent_preparation_programs(preparation_build, monkeypatch):
    host, _, cache, _, _, _, _, _, _ = preparation_build
    programs, loads, exports = [], [], []

    def run(command, log, **kwargs):
        name = Path(command[0]).stem
        programs.append(Path(command[0]))
        if name == 'cmake':
            return 'cmake version 4.4.4\n'
        if name == 'eos_smoke':
            if '--version' in command:
                return '8.0.0\tlocked-eos\n'
            return 'id\tstatus\tT_K\trho_kg_m3\tcp_J_kgK\tmu_Pas\tk_W_mK\n' + ''.join(
                f'{name}\t0\t300\t1\t1\t1\t1\n' for name in ('co2', 'water'))
        return '{"status":"passed"}' if name == 'pressure_smoke' else ''

    def load(path):
        loads.append(Path(path))
        def backend(version, version_count, revision, revision_count, error, error_count):
            version.value, revision.value = b'8.0.0', b'locked-eos'
            return 0
        return SimpleNamespace(tpmshx_preparation_property_backend_v1=backend)

    monkeypatch.setattr(native, 'run', run)
    monkeypatch.setattr(native.ct, 'CDLL', load)
    monkeypatch.setattr(native, 'verify_model_exports', lambda directory, host, kind, log: exports.append((directory, kind)))
    native.verify(cache, host, 'pilot')
    preparation = cache/'build'/f'preparation-{host}'
    assert loads[0].parent == preparation
    assert (preparation, 'preparation') in exports
    assert all(path.parent == preparation for path in programs if path.name.startswith('preparation_c_'))
    assert any(path.parent == cache/'build'/f'pilot-{host}' and path.stem == 'full_2d_c_static' for path in programs)


@pytest.mark.parametrize('host,role', [('macos-arm64', 'preparation'), ('windows-x64', 'solver')])
def test_coolprop_record_uses_actual_cmake_flags_and_sdk(tmp_path, monkeypatch, host, role):
    cache = tmp_path/'cache'
    build = native.coolprop_build_dir(cache, host, role)
    archive = native.coolprop_library(cache, host, role)
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b'built archive')
    reply = build/'.cmake/api/v1/reply'
    reply.mkdir(parents=True)
    flags = '-Os -DNDEBUG' if host == 'macos-arm64' else '/O2 /Ob2 /DNDEBUG /MD'
    objects = [dict(kind=name, jsonFile=name+'.json') for name in ('codemodel', 'toolchains')]
    (reply/'index-now.json').write_text(json.dumps(dict(objects=objects)))
    (reply/'codemodel.json').write_text(json.dumps(dict(configurations=[dict(name='Release',
        targets=[dict(name='CoolProp', jsonFile='coolprop.json')])])))
    sdk = tmp_path/'SDKs/Test.sdk'
    sdk.mkdir(parents=True)
    (sdk/'SDKSettings.json').write_text('{"Version":"27.0","CanonicalName":"macosx27.0"}')
    toolchain = dict(language='CXX', compiler=dict(path='/actual/compiler', id='ActualCompiler',
        version='21.0', implicit=dict(includeDirectories=[str(sdk/'usr/include')])))
    (reply/'toolchains.json').write_text(json.dumps(dict(toolchains=[toolchain])))
    (reply/'coolprop.json').write_text(json.dumps(dict(artifacts=[dict(path=archive.relative_to(build).as_posix())],
        compileGroups=[dict(language=language, compileCommandFragments=[dict(fragment=flags)])
                       for language in ('C', 'CXX')])))
    (build/'CMakeCache.txt').write_text('CMAKE_CXX_FLAGS_RELEASE:STRING='+flags+'\nCMAKE_OSX_SYSROOT:STRING=\n')
    if host == 'windows-x64':
        (build/'CoolProp.vcxproj').write_text('<Project><PropertyGroup><WindowsTargetPlatformVersion>10.0.1</WindowsTargetPlatformVersion></PropertyGroup></Project>')
    native._record_coolprop_build(cache, host, role)
    record = native.coolprop_build_record(cache, host, role)
    assert record['compile_groups'][1]['compileCommandFragments'][0]['fragment'] == flags
    assert record['toolchains'][0]['compiler']['path'] == '/actual/compiler'
    assert record['consumed_archive'] == str(archive)
    if host == 'macos-arm64':
        assert record['sdk']['sdk_settings'][0]['version'] == '27.0'
    else:
        assert record['sdk']['windows_target_platform_versions'] == ['10.0.1']


def test_model_source_verification_excludes_pressure_solver_inputs(tmp_path, monkeypatch):
    checked = []
    lock = {'sources': {'coolprop': {'directory': 'CP', 'commit': 'locked'},
                       'eigen': {'directory': 'Eigen', 'commit': 'locked', 'cpm-name': 'Eigen'},
                       'superlu': {'directory': 'LU', 'commit': 'locked'},
                       'amgcl': {'directory': 'AMG', 'commit': 'locked'}}}
    monkeypatch.setattr(native, 'LOCK', lock)

    def run(command, log, *, cwd):
        checked.append(cwd.name)
        return 'locked\n' if 'rev-parse' in command else ''

    monkeypatch.setattr(native, 'run', run)
    native.verify_sources(tmp_path, models_only=True)
    assert set(checked) == {'CP', 'Eigen'}

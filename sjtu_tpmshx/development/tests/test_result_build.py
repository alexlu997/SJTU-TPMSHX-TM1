"""Result builds need only a locked tool and the standard C++ runtime."""
import json
from pathlib import Path
import sys

import pytest

from engineering.scripts import build_native_dependencies as native


HOSTS = ('macos-arm64', 'windows-x64', 'linux-x86_64')


@pytest.fixture(params=HOSTS)
def result_build(request, tmp_path, monkeypatch):
    host = request.param
    root = tmp_path/'project'
    cache = root/'.cache/native-deps'
    python, lock = root/'configured python', root/'selected lock'
    cmake = cache/'tools/bin'/('cmake.exe' if host == 'windows-x64' else 'cmake')
    cmake.parent.mkdir(parents=True)
    cmake.write_bytes(b'locked tool placeholder')
    generator = 'Visual Studio 17 2022' if host == 'windows-x64' else 'Unix Makefiles'
    monkeypatch.setattr(native, 'ROOT', root)
    monkeypatch.setattr(native, 'LOCK', {'cmake': {'version': '4.4.4', host: {
        'generator': generator, 'executable': cmake.relative_to(cache/'tools').as_posix()}}})
    commands, records = [], []

    def run(command, *args, **kwargs):
        commands.append(tuple(map(str, command)))
        return 'cmake version 4.4.4\n' if '--version' in command else ''

    def forbidden(*args, **kwargs):
        pytest.fail('standalone result entered a model, solver source, or EOS operation')

    for name in ('verify_sources', 'apply_lu_patch', 'fetch_source', 'coolprop_build_record'):
        monkeypatch.setattr(native, name, forbidden)
    monkeypatch.setattr(native.ct, 'CDLL', forbidden)
    monkeypatch.setattr(native, 'run', run)
    monkeypatch.setattr(native, 'record_result_build', lambda cache, host: records.append(host))
    monkeypatch.setattr(native, 'result_build_record', lambda *args: {})
    monkeypatch.setattr(native, 'verify_model_exports', lambda *args: None)
    return host, root, cache, python, lock, cmake, commands, records


def test_result_build_has_no_source_or_model_generation_step(result_build):
    host, root, cache, python, lock, cmake, commands, records = result_build
    native.build(cache, host, python, lock, 'result')
    assert commands[:2] == [(str(python), '-m',
        'sjtu_tpmshx.development.runs.tools.check_locked_environment', str(lock)),
        (str(python), '-m', 'pip', 'check')]
    configure, = (command for command in commands if '-S' in command)
    assert configure[0] == str(cmake)
    assert configure[configure.index('-S')+1] == str(root/'sjtu_tpmshx/solvers/native/result')
    assert configure[configure.index('-B')+1] == str(cache/'build'/f'result-{host}')
    assert '-DCMAKE_BUILD_TYPE=Release' in configure
    assert '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON' in configure
    if host == 'windows-x64':
        assert configure[configure.index('-A')+1] == 'x64'
    elif host == 'macos-arm64':
        assert '-DCMAKE_OSX_ARCHITECTURES=arm64' in configure
    else:
        assert not any('OSX' in value for value in configure)
    assert all('generate_native_model_coefficients' not in value and 'COOLPROP' not in value
               and 'NATIVE_DEPS_ROOT' not in value and 'MODEL_INCLUDE_DIR' not in value
               for command in commands for value in command)
    assert not (cache/'src').exists() and not (cache/'generated').exists()
    assert records == [host]
    query = cache/'build'/f'result-{host}/.cmake/api/v1/query'
    assert {path.name for path in query.iterdir()} == {'codemodel-v2', 'toolchains-v1'}


@pytest.mark.parametrize('failure', ['check_locked_environment', 'pip'])
def test_result_environment_failure_stops_before_configure(result_build, monkeypatch, failure):
    host, _, cache, python, lock, _, commands, records = result_build

    def fail(command, *args, **kwargs):
        commands.append(tuple(map(str, command)))
        if (command[2] == 'pip' if failure == 'pip' else command[2].endswith('check_locked_environment')):
            raise RuntimeError('environment gate failed')
        return ''

    monkeypatch.setattr(native, 'run', fail)
    with pytest.raises(RuntimeError, match='environment gate failed'):
        native.build(cache, host, python, lock, 'result')
    assert not any('-S' in command for command in commands) and records == []


def test_result_verification_runs_all_independent_callers(result_build, monkeypatch):
    host, _, cache, _, _, cmake, commands, _ = result_build
    exported, metadata = [], []
    monkeypatch.setattr(native, 'verify_model_exports', lambda *args: exported.append(args[:3]))
    monkeypatch.setattr(native, 'result_build_record', lambda *args: metadata.append(args))
    native.verify(cache, host, 'result')
    suffix = '.exe' if host == 'windows-x64' else ''
    build = cache/'build'/f'result-{host}'
    assert commands == [(str(cmake), '--version')] + [(str(build/(name+suffix)),)
        for name in ('result_c_static', 'result_c_shared', 'result_kernel_smoke', 'result_stage_smoke')]
    assert exported == [(build, host, 'result')] and metadata == [(cache, host)]


@pytest.mark.parametrize('action', ['fetch-cmake', 'build', 'verify', 'publish', 'check-stages'])
def test_linux_cli_allows_only_result_actions(tmp_path, monkeypatch, action):
    cache = tmp_path/'.cache/native-deps'
    monkeypatch.setattr(native, 'ROOT', tmp_path)
    monkeypatch.setattr(native, 'configured_python', lambda: Path('/python'))
    monkeypatch.setattr(native, 'platform_name', lambda: 'linux-x86_64')
    monkeypatch.setattr(native, 'check_environment', lambda *args: None)
    calls = []
    for name in ('fetch_cmake', 'build', 'verify', 'publish', 'check_stages'):
        monkeypatch.setattr(native, name, lambda *args, name=name: calls.append((name, args)))
    monkeypatch.setattr(sys, 'argv', ['native-build', action, '--cache', str(cache), '--component', 'result'])
    native.main()
    assert [name for name, _ in calls] == [action.replace('-', '_')]
    assert calls[0][1][:2] == (cache, 'linux-x86_64')


@pytest.mark.parametrize('action,component', [('fetch', 'result'), ('fetch-eigen', 'result'),
    ('fetch-cmake', 'all'), ('build', 'pilot'), ('verify', 'all'), ('publish', 'preparation')])
def test_linux_cli_rejects_full_solver_scope_before_actions(tmp_path, monkeypatch, action, component):
    monkeypatch.setattr(native, 'ROOT', tmp_path)
    monkeypatch.setattr(native, 'configured_python', lambda: Path('/python'))
    monkeypatch.setattr(native, 'platform_name', lambda: 'linux-x86_64')

    def forbidden(*args, **kwargs):
        pytest.fail('unsupported Linux action reached execution')

    for name in ('fetch', 'fetch_eigen', 'fetch_cmake', 'build', 'verify', 'publish', 'check_stages', 'check_environment'):
        monkeypatch.setattr(native, name, forbidden)
    monkeypatch.setattr(sys, 'argv', ['native-build', action, '--cache', str(tmp_path/'.cache/native-deps'),
                                    '--component', component])
    with pytest.raises(RuntimeError, match='Linux'):
        native.main()


@pytest.mark.parametrize('operation', ['fetch', 'build', 'verify', 'publish', 'check_stages'])
def test_linux_direct_full_solver_calls_stop_before_environment(tmp_path, monkeypatch, operation):
    def forbidden(*args, **kwargs):
        pytest.fail('unsupported Linux component reached a build or source operation')
    monkeypatch.setattr(native, 'check_environment', forbidden)
    monkeypatch.setattr(native, 'fetch_source', forbidden)
    function = getattr(native, operation)
    args = (tmp_path, 'linux-x86_64')
    if operation in {'build', 'publish', 'check_stages'}:
        args += (Path('/python'), Path('/lock'), 'all')
    with pytest.raises(RuntimeError, match='only --component result'):
        function(*args)


@pytest.mark.parametrize('host', ['macos-arm64', 'windows-x64'])
def test_all_build_adds_result_without_changing_pilot_scope(tmp_path, monkeypatch, host):
    selected = []
    monkeypatch.setattr(native, 'check_environment', lambda *args: None)
    monkeypatch.setattr(native, 'verify_sources', lambda *args: None)
    monkeypatch.setattr(native, 'apply_lu_patch', lambda *args: None)
    monkeypatch.setattr(native, 'cmake_path', lambda *args: Path('/cmake'))
    monkeypatch.setattr(native, '_request_build_metadata', lambda *args: None)
    monkeypatch.setattr(native, '_record_coolprop_build', lambda *args: None)
    monkeypatch.setattr(native, 'coolprop_build_record', lambda *args: {})
    monkeypatch.setattr(native, 'run', lambda *args, **kwargs: '')
    monkeypatch.setattr(native, 'build_result', lambda cache, host: selected.append((cache, host)))
    native.build(tmp_path, host, Path('/python'), Path('/lock'), 'all')
    assert selected == [(tmp_path, host)]
    selected.clear()
    native.build(tmp_path, host, Path('/python'), Path('/lock'), 'pilot')
    assert selected == []


@pytest.fixture(params=HOSTS)
def result_metadata(request, tmp_path):
    host = request.param
    build = tmp_path/'build'/f'result-{host}'
    image = build/native.shared_library_name(host, 'result')
    image.parent.mkdir(parents=True)
    image.write_bytes(b'actual result image')
    reply = build/'.cmake/api/v1/reply'
    reply.mkdir(parents=True)
    (reply/'index-current.json').write_text(json.dumps(dict(objects=[
        dict(kind=kind, jsonFile=kind+'.json') for kind in ('codemodel', 'toolchains')])))
    names = ('tpmshx_result', 'tpmshx_result_c', 'tpmshx_result_shared')
    (reply/'codemodel.json').write_text(json.dumps(dict(configurations=[dict(name='Release',
        targets=[dict(name=name, jsonFile=name+'.json') for name in names])])) )
    compiler = dict(path='/actual/cxx', id='ActualCompiler', version='21.0')
    sdk = tmp_path/'SDKs/Test.sdk'
    sdk.mkdir(parents=True)
    (sdk/'SDKSettings.json').write_text('{"Version":"27.0","CanonicalName":"macosx27.0"}')
    if host == 'macos-arm64':
        compiler['implicit'] = dict(includeDirectories=[(sdk/'usr/include').as_posix()])
    toolchains = [dict(language='CXX', compiler=compiler)]
    if host == 'macos-arm64':
        toolchains.append(dict(language='C', compiler=dict(path='/actual/c', id='ActualCCompiler', version='21.0',
            implicit=dict(includeDirectories=[(sdk/'usr/include').as_posix()]))))
    (reply/'toolchains.json').write_text(json.dumps(dict(toolchains=toolchains)))
    for name in names:
        sources = [dict(path='src/actual.cpp')]
        groups = [dict(language='CXX', compileCommandFragments=[dict(fragment='actual optimized strict CXX options')])]
        if host == 'macos-arm64' and name == 'tpmshx_result':
            groups.append(dict(language='C', compileCommandFragments=[dict(fragment='actual strict C11 options')]))
            sources.append(dict(path='src/result_complex_sqrt.c'))
        (reply/(name+'.json')).write_text(json.dumps(dict(artifacts=[dict(path=image.name)],
            sources=sources, compileGroups=groups, link=dict(language='CXX'))))
    (build/'CMakeCache.txt').write_text('CMAKE_CXX_FLAGS_RELEASE:STRING=actual release options\n'
        f'CMAKE_OSX_SYSROOT:STRING={sdk}\nCMAKE_SYSTEM_VERSION:STRING=actual-system-version\n')
    if host == 'windows-x64':
        (build/'tpmshx_result_shared.vcxproj').write_text('<Project><PropertyGroup>'
            '<WindowsTargetPlatformVersion>10.0.1</WindowsTargetPlatformVersion></PropertyGroup></Project>')
    return tmp_path, host, build, reply, compiler, sdk


def test_result_metadata_records_actual_targets_and_toolchain(result_metadata):
    cache, host, _, _, compiler, sdk = result_metadata
    native.record_result_build(cache, host)
    record = native.result_build_record(cache, host)
    assert record['toolchains'][0]['compiler'] == compiler
    assert set(record['targets']) == {'tpmshx_result', 'tpmshx_result_c', 'tpmshx_result_shared'}
    expected_sources = [dict(path='src/actual.cpp')]
    if host == 'macos-arm64':
        expected_sources.append(dict(path='src/result_complex_sqrt.c'))
    assert record['targets']['tpmshx_result']['sources'] == expected_sources
    for name, target in record['targets'].items():
        languages = {'C', 'CXX'} if host == 'macos-arm64' and name == 'tpmshx_result' else {'CXX'}
        assert {group['language'] for group in target['compile_groups']} == languages
    if host == 'macos-arm64':
        assert record['toolchains'][1]['compiler']['path'] == '/actual/c'
        assert record['targets']['tpmshx_result']['compile_groups'][1]['compileCommandFragments'] == [
            dict(fragment='actual strict C11 options')]
        assert record['sdk']['sdk_settings'] == [dict(path=str(sdk.resolve()/'SDKSettings.json'),
            version='27.0', canonical_name='macosx27.0')]
    assert record['sdk']['cmake_cache']['CMAKE_SYSTEM_VERSION'] == 'actual-system-version'
    assert 'coolprop_build' not in record
    if host == 'windows-x64':
        assert record['sdk']['windows_target_platform_versions'] == ['10.0.1']


@pytest.mark.parametrize('fault', ['missing-language', 'unexpected-c', 'extra-language', 'missing-options'])
def test_result_metadata_rejects_unexpected_target_languages_or_missing_options(result_metadata, fault):
    cache, host, build, reply, _, _ = result_metadata
    name = 'tpmshx_result_c' if fault == 'unexpected-c' and host == 'macos-arm64' else 'tpmshx_result'
    path = reply/(name+'.json')
    target = json.loads(path.read_text())
    groups = target['compileGroups']
    if fault == 'missing-language':
        groups.pop()
    elif fault in {'unexpected-c', 'extra-language'}:
        groups.append(dict(language='C' if fault == 'unexpected-c' else 'Fortran',
            compileCommandFragments=[dict(fragment='unexpected options')]))
    else:
        groups[-1].pop('compileCommandFragments')
    path.write_text(json.dumps(target))
    with pytest.raises(RuntimeError, match='required compilation options or languages'):
        native.record_result_build(cache, host)
    assert not (build/'result-toolchain.json').exists()


@pytest.mark.parametrize('host', HOSTS)
@pytest.mark.parametrize('fault', [None, 'extra-export', 'missing-export', 'private-import', 'foreign-runtime'])
def test_result_exports_and_runtime_dependencies_are_explicit(tmp_path, monkeypatch, host, fault):
    root = tmp_path/'project'
    manifest = root/'sjtu_tpmshx/solvers/native/result/result.exports'
    manifest.parent.mkdir(parents=True)
    symbol = 'tpmshx_result_abi_version_v1'
    manifest.write_text('_'+symbol+'\n')
    monkeypatch.setattr(native, 'ROOT', root)
    exported = [] if fault == 'missing-export' else [symbol]
    if fault == 'extra-export':
        exported.append('_ZN6tpmshx6result7privateEv')

    def run(command, log):
        if command[:2] == ['nm', '-gU']:
            return ''.join('0000000000000100 T _'+name+'\n' for name in exported)
        if command[:2] == ['nm', '-gu']:
            return 'U _ZN6tpmshx6result7privateEv\n' if fault == 'private-import' else 'U _malloc\n'
        if command[0] == 'otool':
            dependency = '/tmp/foreign.dylib' if fault == 'foreign-runtime' else '/usr/lib/libSystem.B.dylib'
            return f'library:\n\t@rpath/library (compatibility version 0.0.0)\n\t{dependency} (compatibility version 1.0.0)\n'
        if command[:3] == ['nm', '-D', '--defined-only']:
            return ''.join('0000000000000100 T '+name+'\n' for name in exported)
        if command[:3] == ['nm', '-D', '--undefined-only']:
            return 'U _ZN6tpmshx6result7privateEv\n' if fault == 'private-import' else 'U malloc@GLIBC_2.2.5\n'
        if command[0] == 'readelf':
            dependency = 'libforeign.so' if fault == 'foreign-runtime' else 'libstdc++.so.6'
            return f' 0x0000000000000001 (NEEDED) Shared library: [{dependency}]\n'
        if '/EXPORTS' in command:
            return ''.join(f' {index+1} {index:X} 00000100 {name}\n' for index, name in enumerate(exported))
        assert '/DEPENDENTS' in command
        dependency = ('foreign.dll' if fault == 'foreign-runtime' else 'tpmshx_solver_shared.dll'
                      if fault == 'private-import' else 'VCRUNTIME140.dll')
        return 'Dump of file result.dll\n\n    KERNEL32.dll\n    '+dependency+'\n'

    monkeypatch.setattr(native, 'run', run)
    if fault is None:
        native.verify_model_exports(tmp_path/'build', host, 'result', tmp_path/'verify.log')
    else:
        with pytest.raises(RuntimeError, match='exports differ|private model symbols|numerical library|non-system dynamic'):
            native.verify_model_exports(tmp_path/'build', host, 'result', tmp_path/'verify.log')


@pytest.mark.parametrize('host', ['windows-x64', 'linux-x86_64'])
def test_result_verifier_requires_an_actual_dependency_listing(tmp_path, monkeypatch, host):
    root = tmp_path/'project'
    manifest = root/'sjtu_tpmshx/solvers/native/result/result.exports'
    manifest.parent.mkdir(parents=True)
    symbol = 'tpmshx_result_abi_version_v1'
    manifest.write_text('_'+symbol+'\n')
    monkeypatch.setattr(native, 'ROOT', root)

    def run(command, log):
        if '/EXPORTS' in command:
            return ' 1 0 00000100 '+symbol+'\n'
        if command[:3] == ['nm', '-D', '--defined-only']:
            return '0000000000000100 T '+symbol+'\n'
        return ''

    monkeypatch.setattr(native, 'run', run)
    with pytest.raises(RuntimeError, match='non-system dynamic dependency'):
        native.verify_model_exports(tmp_path/'build', host, 'result', tmp_path/'verify.log')


def test_result_publication_uses_its_platform_image_without_eos_records(result_build, monkeypatch):
    host, root, cache, python, lock, _, _, _ = result_build
    (root / '.git').write_text('gitdir: mock-worktree\n', encoding='utf-8')
    name = native.shared_library_name(host, 'result')
    source = cache/'build'/f'result-{host}'/name
    source.parent.mkdir(parents=True)
    source.write_bytes(b'new verified result image')
    target = root/'sjtu_tpmshx/solvers/native/lib'/host/name
    target.parent.mkdir(parents=True)
    target.write_bytes(b'previous result image')
    record = target.with_name('result-build.json')
    record.write_text('{"source_commit":"previous-result"}\n')
    events = []
    monkeypatch.setattr(native, 'build', lambda *args: events.append(('build', args[-1])))
    monkeypatch.setattr(native, 'verify', lambda *args: events.append(('verify', args[-1])))
    monkeypatch.setattr(native, 'run', lambda command, *args, **kwargs: 'actual-commit\n' if 'rev-parse' in command else '')
    monkeypatch.setattr(native, 'result_build_record', lambda *args: dict(toolchains=[dict(language='CXX')]))
    assert native.publish(cache, host, python, lock, 'result') == target
    assert events == [('build', 'result'), ('verify', 'result')]
    assert target.read_bytes() == source.read_bytes()
    metadata = json.loads(record.read_text())
    assert metadata['component'] == 'result' and metadata['dependencies'] == {}
    assert metadata['source_commit'] == 'actual-commit' and 'coolprop_build' not in metadata
    assert metadata['target_library'] == str(target) and metadata['source_library'] == str(source)
    assert (target.parent/'previous'/name).read_bytes() == b'previous result image'
    assert json.loads((target.parent/'previous/result-build.json').read_text())['source_commit'] == 'previous-result'
    assert not any('solver' in path.name or 'preparation' in path.name or 'geometry' in path.name
                   for path in target.parent.iterdir())


def test_installed_result_stage_has_no_eos_or_python_runtime(result_build, monkeypatch):
    host, root, cache, python, lock, cmake, commands, _ = result_build
    examples = root / 'examples/cpp'
    examples.mkdir(parents=True)
    (examples / 'CMakeLists.txt').write_text('project(test)\n')
    runs = []
    original = native.run

    def record(command, *args, **kwargs):
        runs.append((tuple(map(str, command)), kwargs))
        return original(command, *args, **kwargs)

    monkeypatch.setattr(native, 'run', record)
    monkeypatch.setenv('PYTHONPATH', '/must-not-reach-native-caller')
    monkeypatch.setenv('VIRTUAL_ENV', '/must-not-reach-native-caller')
    native.check_stages(cache, host, python, lock, 'result')
    configure = next(command for command in commands if '-DTPMSHX_COMPONENTS=result' in command)
    assert f'-DTPMSHX_RESULT_BUILD_DIR={cache / "build" / f"result-{host}"}' in configure
    assert not any('COOLPROP' in part for command in commands for part in command)
    checks, = [(command, options) for command, options in runs if '--test-dir' in command]
    consumer_build = checks[0][checks[0].index('--test-dir') + 1]
    consumer, = [command for command in commands
                 if '--build' in command and command[command.index('--build') + 1] == consumer_build]
    assert '--target' not in consumer
    assert not checks[1]['cwd'].is_relative_to(root)
    assert 'PYTHONPATH' not in checks[1]['env'] and 'VIRTUAL_ENV' not in checks[1]['env']

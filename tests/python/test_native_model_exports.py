"""Reject exported or imported private EOS state at the final library boundary."""
import pytest

from engineering.scripts import build_native_dependencies as native


@pytest.mark.parametrize('host', ['macos-arm64', 'windows-x64'])
@pytest.mark.parametrize('fault', [None, 'extra-cpp-export', 'missing-c-export', 'cross-image-import'])
def test_private_model_image_gate(tmp_path, monkeypatch, host, fault):
    root = tmp_path/'project'
    manifest = root/'sjtu_tpmshx/solvers/native/preparation/preparation.exports'
    manifest.parent.mkdir(parents=True)
    manifest.write_text('_tpmshx_preparation_abi_version_v1\n')
    monkeypatch.setattr(native, 'ROOT', root)
    symbol = 'tpmshx_preparation_abi_version_v1'
    export_symbols = [] if fault == 'missing-c-export' else [symbol]
    if fault == 'extra-cpp-export':
        export_symbols.append('_ZN8CoolProp16backend_registryE')
    commands = []

    def run(command, log):
        commands.append(command)
        if command[:2] == ['nm', '-gU']:
            return ''.join('0000000000000100 T _'+name+'\n' for name in export_symbols)
        if command[:2] == ['nm', '-gu']:
            return 'U _ZN8CoolProp7factoryEv\n' if fault == 'cross-image-import' else 'U _malloc\n'
        if command[0] == 'otool':
            return 'library:\n\t@rpath/library (compatibility version 0.0.0)\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n'
        if '/EXPORTS' in command:
            return ''.join(f'          {index+1}    {index:X} 00000100 {name}\n' for index, name in enumerate(export_symbols))
        assert '/DEPENDENTS' in command
        dependencies = '    KERNEL32.dll\n    VCRUNTIME140.dll\n'
        if fault == 'cross-image-import':
            dependencies += '    tpmshx_solver_shared.dll\n'
        return 'Dump of file tpmshx_preparation_shared.dll\n\n'+dependencies

    monkeypatch.setattr(native, 'run', run)
    if fault is None:
        native.verify_model_exports(tmp_path/'build', host, 'preparation', tmp_path/'check.log')
    else:
        with pytest.raises(RuntimeError, match='exports differ|imports private model symbols|imports another numerical library'):
            native.verify_model_exports(tmp_path/'build', host, 'preparation', tmp_path/'check.log')
    assert commands

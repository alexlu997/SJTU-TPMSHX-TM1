"""Select CI checks and require their expected job results."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

TIERS = ('docs', 'application', 'full')
PLATFORMS = ('macos-15', 'windows-2022')
# The build, installed SDK, generated headers, independent callers, and runtime notices.
NATIVE_INPUTS = (
    '.gitattributes', 'CMakeLists.txt', 'LICENSE', 'geometry', 'include', 'numerics',
    'preprocess', 'solver', 'postprocess', 'tests/cpp', 'examples/cpp',
    'engineering/native_build', 'engineering/requirements/base.txt',
    'engineering/__init__.py', 'engineering/scripts/__init__.py',
    'engineering/scripts/build_coolprop.py', 'engineering/scripts/build_native_dependencies.py',
    'engineering/scripts/generate_native_model_coefficients.py',
    'sjtu_tpmshx.py', 'python/__init__.py', 'python/model_configs',
    'python/physical_models/df_surrogate/_prebuilt', 'python/development/__init__.py',
    'python/development/runs/__init__.py', 'python/development/runs/tools/__init__.py',
    'python/development/runs/tools/check_locked_environment.py',
    'docs/native-stages.md', 'docs/native-stages.zh-CN.md',
)
DISPLAY_FILES = {
    'python/applications/gui/ui/' + name for name in (
        'icons.py', 'ui_constants.py', 'vis3d_constants.py', 'responsive.py',
        'matplotlib_canvas.py', 'typography.py', 'theme.py', 'theme_manager.py',
        'microanim.py', 'sparkline.py', 'plot_2d_results.py', 'plot_3d_results.py',
        'panel_vis_3d.py', 'coord_inspector.py', 'field_menu.py', 'layout_drawer.py',
    )
} | {
    'tests/python/' + name for name in (
        'test_ui_typography.py', 'test_ui_layout_hygiene.py',
        'test_lazy_result_plots.py',
    )
}


def document(path):
    return (path in {'README.md', 'README.en.md', 'AGENTS.md'}
            or path.startswith('docs/') and not path.startswith('docs/contracts/')
            and path not in NATIVE_INPUTS
            and path.endswith('.md'))


def select_scope(event, paths):
    if event not in {'pull_request', 'push'} or not paths:
        return 'full'
    if all(document(path) for path in paths):
        return 'docs'
    if event == 'pull_request' and all(
            document(path) or path in DISPLAY_FILES
            or path.startswith('python/applications/gui/ui/assets/icons/')
            and PurePosixPath(path).suffix == '.svg' for path in paths):
        return 'application'
    return 'full'


def require_jobs(tier, needs, stage):
    if tier not in TIERS or stage not in {'summary', 'minimal'}:
        raise ValueError('Unknown CI tier or gate')
    result = 'skipped' if tier == 'docs' else 'success'
    expected = {'scope': 'success', 'native-macos': result}
    if stage == 'summary':
        expected['native-windows'] = result
    else:
        expected['result-build'] = result
    actual = {name: job['result'] for name, job in needs.items()}
    if actual != expected:
        raise ValueError(f'Expected CI jobs {expected}; got {actual}')


def native_fingerprint(commit):
    """Identify the checked-in inputs and the build recipe at this commit."""
    import yaml

    tree = subprocess.check_output(['git', 'ls-tree', '-rz', commit])
    digest = hashlib.sha256()
    directories = tuple(path + '/' for path in NATIVE_INPUTS)
    for entry in tree.split(b'\0')[:-1]:
        path = entry.split(b'\t', 1)[1].decode()
        if (path in NATIVE_INPUTS or path.startswith(directories)
                or path.endswith(('/CMakeLists.txt', '.cmake', '.c', '.cpp', '.cc', '.cxx',
                                  '.h', '.hpp', '.hxx', '.inc', '.exports', '.def', '.map'))):
            digest.update(entry + b'\0')
    recipe = []
    for filename in ('ci.yml', 'native.yml'):
        workflow = yaml.safe_load(subprocess.check_output(
            ['git', 'show', f'{commit}:.github/workflows/{filename}']))
        recipe.extend([workflow.get('env'), workflow.get('defaults')])
        if filename == 'ci.yml':
            for name in ('native-macos', 'native-windows'):
                caller = workflow['jobs'][name]
                recipe.append([caller['uses'], {k: v for k, v in caller['with'].items()
                                                if k not in {'tier', 'reuse'}}])
        else:
            build = workflow['jobs']['native-build']
            parallel = workflow['jobs'].get('native-qualification', build)
            scheduling = {'name', 'needs', 'if', 'timeout-minutes'}
            recipes = [{k: v for k, v in j.items() if k not in scheduling} for j in (build, parallel)]
            if recipes[0] != recipes[1]:
                raise ValueError('Both build jobs must use the same native recipe')
            recipe.append(recipes[0])
    digest.update(json.dumps(recipe, sort_keys=True).encode())
    return digest.hexdigest()


def github(resource):
    url = f'{os.environ["GITHUB_API_URL"]}/repos/{os.environ["GITHUB_REPOSITORY"]}/actions/{resource}'
    request = Request(url, headers={'User-Agent': 'TM1-CI'})
    # Send the token only to the API. Log and artifact downloads redirect to storage.
    request.add_unredirected_header('Authorization', 'Bearer ' + os.environ['GH_TOKEN'])
    return urlopen(request, timeout=60)


def records(resource, key):
    separator = '&' if '?' in resource else '?'
    page = 1
    while True:
        with github(f'{resource}{separator}per_page=100&page={page}') as response:
            rows = json.load(response)[key]
        yield from rows
        if len(rows) < 100:
            return
        page += 1


def qualified_pair(run_id):
    with github(f'runs/{run_id}') as response:
        run = json.load(response)
    if (run['path'] != '.github/workflows/ci.yml' or run['event'] != 'push'
            or run['conclusion'] != 'success' or run['status'] != 'completed'):
        return {}
    attempt = run['run_attempt']
    files = list(records(f'runs/{run_id}/artifacts', 'artifacts'))
    jobs = list(records(f'runs/{run_id}/jobs?filter=all', 'jobs'))
    pair = {}
    for platform in PLATFORMS:
        matching = [f for f in files if not f['expired'] and f['name'] == f'native-build-{platform}']
        if len(matching) != 1:
            return {}
        file = matching[0]
        # A successful retry can keep a build from an earlier attempt.
        producers = [j for j in jobs if platform in j['labels'] and j['conclusion'] == 'success'
                     and j['started_at'] <= file['created_at'] <= j['completed_at']
                     and any(s['name'] == 'Pack native runtime files with executable permissions'
                             and s['conclusion'] == 'success' for s in j['steps'])]
        if len(producers) != 1:
            return {}
        with github(f'jobs/{producers[0]["id"]}/logs') as response:
            log = response.read().decode('utf-8').splitlines()
        # The producer records the actual runner OS, architecture, and image in its exact cache key.
        image = next((m[1] for line in log if (m := re.search(
            r'Z   key: coolprop-(\S+)-[a-f0-9]{64}-[a-f0-9]{64}$', line))), None)
        python = next((m[1] for line in log if (m := re.search(
            r'Successfully set up CPython \(([\d.]+)\)', line))), None)
        url = f'{run["html_url"]}/artifacts/{file["id"]}'
        if not (image and python and file['digest']
                and any(line.endswith('Artifact download URL: ' + url) for line in log)):
            return {}
        pair[platform] = dict(id=file['id'], digest=file['digest'], image=image, python=python,
                              attempt=producers[0]['run_attempt'])
    print(f'Trusted main {run["head_sha"]}, run {run_id}, attempt {attempt}: {json.dumps(pair)}')
    return pair


def native_source(base):
    """Find a pair of archives built by one successful push to main."""
    fingerprint = native_fingerprint('HEAD')
    print(f'Native source and recipe: {fingerprint}')
    if not base.strip('0') or native_fingerprint(base) != fingerprint:
        print('Native inputs changed or the base is unavailable. Build both platforms.')
        return {}
    repo_id = int(os.environ['GITHUB_REPOSITORY_ID'])
    # Start with existing artifacts, so documentation runs and old runs without files cost no lookup.
    for artifact in records('artifacts?name=native-build-macos-15', 'artifacts'):
        origin = artifact['workflow_run']
        if (artifact['expired'] or origin['head_branch'] != 'main'
                or origin['head_repository_id'] != repo_id or origin['repository_id'] != repo_id):
            continue
        sha = origin['head_sha']
        if subprocess.run(['git', 'merge-base', '--is-ancestor', sha, base]).returncode:
            continue
        if native_fingerprint(sha) != fingerprint:
            continue
        run_id = origin['id']
        try:
            pair = qualified_pair(run_id)
        except HTTPError as error:
            if error.code not in {404, 410}:
                raise
            print(f'Main run {run_id} or its build evidence is no longer available.')
            continue
        if pair:
            return pair
    print('No complete, unexpired pair from a matching successful main build. Build both platforms.')
    return {}


def matching_compiler_and_sdk(archive, platform):
    host = 'macos-arm64' if platform == 'macos-15' else 'windows-x64'
    with tarfile.open(archive) as runtime:
        record = json.load(runtime.extractfile(f'coolprop-{host}/coolprop-build.json'))
    compilers = {t['language']: t['compiler'] for t in record['toolchains']}
    expected = [f'{compilers[lang]["id"]} {compilers[lang]["version"]}' for lang in ('C', 'CXX')]
    lock = tomllib.loads(Path('engineering/native_build/dependencies-lock.toml').read_text())
    generator = lock['cmake'][host]['generator']
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'CMakeLists.txt').write_text(
            'cmake_minimum_required(VERSION 3.31.8)\nproject(probe LANGUAGES C CXX)\n'
            'file(WRITE "${CMAKE_BINARY_DIR}/toolchain" "${CMAKE_C_COMPILER_ID} ${CMAKE_C_COMPILER_VERSION}\\n"\n'
            '  "${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}\\n${CMAKE_VS_WINDOWS_TARGET_PLATFORM_VERSION}")\n',
            encoding='utf-8')
        arch = ['-A', 'x64'] if host == 'windows-x64' else ['-DCMAKE_OSX_ARCHITECTURES=arm64']
        subprocess.run(['cmake', '-S', root, '-B', root / 'build', '-G', generator, *arch], check=True)
        actual = (root / 'build/toolchain').read_text().splitlines()
    if host == 'macos-arm64':
        sdk_path = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
        actual.append(json.loads((Path(sdk_path) / 'SDKSettings.json').read_text())['Version'])
        sdk = [s['version'] for s in record['sdk']['sdk_settings']]
    else:
        sdk = record['sdk']['windows_target_platform_versions']
    expected.extend(dict.fromkeys(sdk))
    print(f'{host}, {generator}: current {actual}, archive {expected}')
    return actual == expected


def restore_native(platform, source):
    minor = f'{sys.version_info.major}.{sys.version_info.minor}'
    host = f'{os.environ["RUNNER_OS"]}-{os.environ["RUNNER_ARCH"]}-py{minor}-{os.environ["ImageVersion"]}'
    python = '.'.join(map(str, sys.version_info[:3]))
    if (host, python) != (source['image'], source['python']):
        print(f'Hosted toolchain changed ({host}, Python {python}). Build both platforms.')
        return False
    archive = Path('.cache/ci-native-build/native-binaries.tar')
    with tempfile.TemporaryFile() as download:
        try:
            with github(f'artifacts/{source["id"]}/zip') as response:
                shutil.copyfileobj(response, download)
        except HTTPError as error:
            if error.code not in {404, 410}:
                raise
            print(f'Artifact {source["id"]} is missing or expired. Build both platforms.')
            return False
        download.seek(0)
        if 'sha256:' + hashlib.file_digest(download, 'sha256').hexdigest() != source['digest']:
            raise ValueError(f'Artifact {source["id"]} digest differs from the GitHub record')
        with zipfile.ZipFile(download) as package, package.open(archive.name) as contents:
            archive.parent.mkdir(parents=True, exist_ok=True)
            with archive.open('wb') as output:
                shutil.copyfileobj(contents, output)
    if not matching_compiler_and_sdk(archive, platform):
        print('The compiler or SDK changed. Build both platforms.')
        return False
    print(f'Validated {platform} artifact {source["id"]} ({source["digest"]}) on {host}, Python {python}.')
    return True


def job_output(name, value):
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        print(f'{name}={value}', file=output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    select = commands.add_parser('select')
    select.add_argument('--event', required=True)
    select.add_argument('--base', default='')
    select.add_argument('--head', default='')
    source = commands.add_parser('native-source')
    source.add_argument('--base', required=True)
    restore = commands.add_parser('restore-native')
    restore.add_argument('--os', choices=PLATFORMS, required=True)
    gate = commands.add_parser('gate')
    gate.add_argument('--tier', required=True, choices=TIERS)
    gate.add_argument('--stage', required=True, choices=('summary', 'minimal'))
    args = parser.parse_args()
    if args.action == 'select':
        paths = []
        if args.event in {'pull_request', 'push'} and args.base.strip('0') and args.head:
            diff = subprocess.run(
                ['git', 'diff', '--name-only', '--no-renames', '-z',
                 args.base, args.head, '--'], capture_output=True, text=True)
            if diff.returncode == 0:
                paths = [path for path in diff.stdout.split('\0') if path]
        print(select_scope(args.event, paths))
    elif args.action == 'native-source':
        pair = native_source(args.base)
        job_output('source', json.dumps(pair) if pair else '')
    elif args.action == 'restore-native':
        if restore_native(args.os, json.loads(os.environ['NATIVE_SOURCE'])[args.os]):
            job_output(args.os.split('-')[0], 'ready')
    else:
        require_jobs(args.tier, json.loads(os.environ['NEEDS_JSON']), args.stage)


if __name__ == '__main__':
    main()

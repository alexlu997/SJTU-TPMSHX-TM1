"""Record or compare the TM1 numerical reference. Run as a module at the repository root.

    python -m engineering.scripts.restructure_reference run NEW_DIR NATIVE_DIR
    python -m engineering.scripts.restructure_reference compare OLD_DIR NEW_DIR
    python -m engineering.scripts.restructure_reference handoff NEW_DIR LINUX_NATIVE_DIR MAC_2D_H5 MAC_3D_H5

Use the BO lock for a full run and the postprocess lock on Linux x86_64.
NATIVE_DIR contains the published images and build records. Set TM1_PACKAGE after a package rename.
"""
import argparse
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
import hashlib
from importlib import import_module
import json
import math
import os
from pathlib import Path
import platform
import struct
import sys
from threading import Event
from time import perf_counter

import h5py
import numpy as np


PACKAGE = os.environ.get('TM1_PACKAGE', 'sjtu_tpmshx')
ROOT = Path(__file__).resolve().parents[2]
CASES = Path(__file__).with_name('restructure_cases.json')


def module(name):
    return import_module(f'{PACKAGE}.{name}')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def without(values, *names):
    return {key: item for key, item in values.items() if key not in names}


def exact(value):
    """Keep array types and all float bits, including the bits of a non-standard NaN."""
    if is_dataclass(value):
        value = {field.name: getattr(value, field.name) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: exact(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [exact(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        if math.isnan(value) and struct.pack('>d', value).hex() != '7ff8000000000000':
            return 'nan:' + struct.pack('>d', value).hex()
        return value.hex()
    return value


def difference(left, right, path):
    if type(left) is not type(right):
        return f'{path}: {type(left).__name__} != {type(right).__name__}'
    if isinstance(left, np.ndarray):
        if (left.dtype.str, left.shape) != (right.dtype.str, right.shape):
            return f'{path}: {left.dtype.str}{left.shape} != {right.dtype.str}{right.shape}'
        width = left.dtype.itemsize
        a, b = (np.frombuffer(x.tobytes(), dtype=f'V{width}') for x in (left, right))
        mismatches = np.flatnonzero(a != b)
        if mismatches.size:
            i = int(mismatches[0])
            index = tuple(map(int, np.unravel_index(i, left.shape)))
            return f'{path}{index}: {exact(left.flat[i])} != {exact(right.flat[i])} (bytes {a[i].tobytes().hex()} / {b[i].tobytes().hex()})'
    elif isinstance(left, dict):
        for key in sorted(left.keys() | right.keys()):
            if key not in left or key not in right:
                return f'{path}.{key}: {"added" if key in right else "missing"}'
            if message := difference(left[key], right[key], f'{path}.{key}'):
                return message
    elif isinstance(left, list):
        if len(left) != len(right):
            return f'{path}: length {len(left)} != {len(right)}'
        for i, (a, b) in enumerate(zip(left, right)):
            if message := difference(a, b, f'{path}[{i}]'):
                return message
    elif left != right:
        return f'{path}: {left!r} != {right!r}'
    return None


def save(folder, manifest):
    with h5py.File(folder / 'arrays.h5', 'x') as arrays:
        def store_array(array):
            name = str(len(arrays))
            arrays[name] = array
            return {'$array': name}
        with (folder / 'manifest.json').open('x', encoding='utf-8') as stream:
            json.dump(manifest, stream, default=store_array, ensure_ascii=False, allow_nan=False)


def load(folder):
    with h5py.File(folder / 'arrays.h5') as arrays:
        return json.loads((folder / 'manifest.json').read_text(encoding='utf-8'),
            object_hook=lambda node: arrays[node['$array']][...] if node.keys() == {'$array'} else node)


def compare(reference, current):
    left, right = load(reference), load(current)
    images = [{name: row['sha256'] for name, row in run['native'].items()} for run in (left, right)]
    print('Native images:', 'identical' if images[0] == images[1] else 'different builds')
    a, b = left['cases'], right['cases']
    failed = 0
    for name in sorted(a.keys() | b.keys()):
        message = difference({name: a[name]} if name in a else {}, {name: b[name]} if name in b else {}, 'case')
        print(message or f'{name}: equal')
        failed += message is not None
    return bool(failed)


def runtime(directory, components, locks):
    native = {}
    for component in components:
        record = read(directory / ('build.json' if component == 'solver' else f'{component}-build.json'))
        image = directory / Path(record['target_library']).name
        os.environ[f'TPMSHX_{component.upper()}_LIBRARY'] = str(image)
        native[component] = {'image': image.name, 'sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
                             'build': record}
    lock_paths = [ROOT / 'engineering/requirements' / name for name in locks]
    lock_paths.append(ROOT / 'engineering/native_build/dependencies-lock.toml')
    return dict(source=module('run_control.provenance').source_context(), python=sys.version,
                host=platform.platform(), machine=platform.machine(), native=native,
                locks={p.name: p.read_text(encoding='utf-8') for p in lock_paths})


def configuration(spec, row):
    data = read(ROOT / 'examples/three_module' / row['example'])
    if 'profile' in row:
        data.update(fluid_A=spec['profiles'][row['profile']], fluid_B=spec['water'], extrap={'allow': True})
        data['geometry'].update(tpms=row['topology'], L_dom_m=.06, H_dom_m=.03, Lz_m=.03, t_wall_mm=.6)
        data['solver'].update(spec['small_grid'])
    if 'field' in row:
        data['zones'] = spec['fields'][row['field']]
    return module('data_types.compute_config').ComputeConfig.from_dict(data)


def evaluation(field, report):
    assert report.source_result_id == report.qualification['source_result_id'] == field.result_id
    return dict(metrics=report.metrics, qualification=without(report.qualification, 'source_result_id'))


def result_fields(field):
    # The saved-run driver adds elapsed times, host paths and checkpoint identity.
    return without(vars(field), 'result_id') | dict(metadata=without(
        field.metadata, 'provenance', 'timings_s', 'recovery', 'continuation'))


def pause_resume(case, control, folder, uninterrupted):
    recovery = module('applications.execution.recovery')
    pause = Event()
    try:
        recovery.compute_prepared_run(case, folder / 'paused', checkpoint_interval_s=3600,
            control=replace(control, iteration=lambda _: pause.set()), pause_check=pause.is_set)
    except module('run_control.paused_run').PausedRun as stopped:
        checkpoint = Path(stopped.checkpoint_file)
    else:
        raise AssertionError('The run did not pause.')
    paused = read(checkpoint.with_name('run.json'))
    _, field, report = recovery.resume_run(checkpoint, folder / 'resumed', checkpoint_interval_s=3600,
                                           control=control)
    actual = exact(dict(field=result_fields(field), performance=evaluation(field, report)))
    if message := difference(uninterrupted, actual, 'resume'):
        raise ValueError(message)
    continued = field.metadata['continuation']
    assert continued['build'] == paused['checkpoint_build']
    return dict(paused=paused['state'], resumed=read(folder / 'resumed/run.json')['state'],
                phase=continued['saved_phase'], completed_outer_steps=continued['completed_outer_steps'])


def proposal(spec, control, folder):
    import torch
    torch.set_num_threads(1)
    settings = spec['bo']
    cfg = module('data_types.compute_config').ComputeConfig.from_dict(
        dict(settings['config'], fluid_A=spec['profiles']['air-water'], fluid_B=spec['water']))
    record = module('applications.optimization.multi_condition_optimizer').run_multi_condition_optimization(
        [('air-water', cfg, *settings['mass_flows_kg_s'])], output_dir=folder / 'bo', workers=1,
        control=control, **without(settings, 'config', 'mass_flows_kg_s'))
    assert record['status'] == 'completed' and len(record['proposals']) == 1, record['reason']
    return without(record, 'elapsed_s') | dict(baseline=without(record['baseline'], 'elapsed_s'),
        history=[without(row, 'elapsed_s') for row in record['history']],
        proposals=[without(row, 'elapsed_s') for row in record['proposals']])


def run(args):
    spec = read(CASES)
    args.output.mkdir(parents=True)
    lock = 'bo-macos.txt' if sys.platform == 'darwin' else 'bo-windows.txt'
    manifest = runtime(args.native.resolve(), ('geometry', 'preparation', 'solver', 'result'), (lock, 'base.txt'))
    control = module('run_control.module_ports').RunControl(native_library=os.environ['TPMSHX_SOLVER_LIBRARY'],
        native_table_directory=str(args.tables.resolve()), cpu_threads=1)
    cases, times = {}, {}
    start = perf_counter()
    for name, row in spec['stages'].items():
        t = perf_counter()
        case = module('preprocess.api').prepare_case(configuration(spec, row), case_id=name)
        field = module('solvers.api').run_case(case, control)
        report = module('postprocess.api').evaluate(field)
        physical = exact(dict(field=result_fields(field), performance=evaluation(field, report)))
        cases[name] = dict(prepared=exact(vars(case) | dict(metadata=without(case.metadata, 'provenance'))), **physical)
        if name in spec['handoff']:
            module('file_io.result_io').save_result(field, args.output / f'{name}.h5')
        times[name] = perf_counter() - t
        print(f'{name}: {times[name]:.2f} s', flush=True)
        if name == spec['pause_resume']:
            t = perf_counter()
            cases['pause-resume'] = pause_resume(case, control, args.output, physical)
            times['pause-resume'] = perf_counter() - t

    t = perf_counter()
    rejected = spec['rejected']
    cfg = configuration(spec, spec['stages'][rejected['case']])
    cfg.fluid_A.P_in_Pa = rejected['P_in_Pa']
    try:
        module('preprocess.api').prepare_case(cfg, case_id='rejected')
    except ValueError as exc:
        cases['rejected'] = {'type': type(exc).__name__, 'reason': str(exc)}
    else:
        raise AssertionError('Preparation accepted the rejected input.')
    times['rejected'] = perf_counter() - t
    t = perf_counter()
    cases['bo'] = exact(proposal(spec, control, args.output))
    times['bo'] = perf_counter() - t
    print(f'BO: {times["bo"]:.2f} s', flush=True)
    t = perf_counter()
    operating_point = module('applications.design.cases').DesignCase(**spec['quick_design'])
    rows, best = module('applications.design.workflow').run_design([operating_point], mode='auto',
                                                                    n_jobs=args.jobs, control=control)
    assert len(rows) == 40
    cases['quick-design'] = exact(dict(rows=rows, best=best))
    times['quick-design'] = perf_counter() - t
    manifest.update(case_list=spec, cases=cases, seconds=times, total_seconds=perf_counter()-start,
                    quick_design_jobs=args.jobs, cpu_threads=control.cpu_threads)
    save(args.output, manifest)
    print(f'Full run: {manifest["total_seconds"]:.2f} s')


def handoff(args):
    if sys.platform != 'linux' or platform.machine() != 'x86_64':
        raise ValueError('Run the independent handoff on Linux x86_64.')
    args.output.mkdir(parents=True)
    manifest = runtime(args.native.resolve(), ('result',), ('postprocess.txt',))
    cases, sources = {}, {}
    start = perf_counter()
    for path in args.mac_files:
        field = module('file_io.result_io').load_result(path)
        name = f"handoff-{field.grid['dimension']}d"
        cases[name] = exact(dict(field=result_fields(field),
                                 performance=evaluation(field, module('postprocess.api').evaluate(field))))
        sources[name] = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                             provenance=field.metadata['provenance'])
    assert cases.keys() == {'handoff-2d', 'handoff-3d'}
    save(args.output, manifest | dict(cases=cases, files=sources, total_seconds=perf_counter()-start))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='action', required=True)
    full = commands.add_parser('run')
    linux = commands.add_parser('handoff')
    for cmd in (full, linux):
        cmd.add_argument('output', type=Path)
        cmd.add_argument('native', type=Path)
    full.add_argument('--tables', type=Path, default=ROOT / '.cache/native-deps/tables')
    full.add_argument('--jobs', type=int, default=-1, help='Quick Design processes (1 for serial)')
    linux.add_argument('mac_files', type=Path, nargs=2, metavar='H5')
    check = commands.add_parser('compare')
    check.add_argument('reference', type=Path)
    check.add_argument('current', type=Path)
    args = parser.parse_args()
    if args.action == 'compare':
        return compare(args.reference, args.current)
    if args.action == 'handoff':
        handoff(args)
    else:
        run(args)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

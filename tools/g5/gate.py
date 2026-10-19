"""G5 resident API reproduction, identity and release qualification.

Uses the installed satellite ctypes declarations, but calls the public native
API directly. Run through run.sh for timing exclusion and physical VRAM guard.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes as C
import hashlib
import itertools
import json
import os
from pathlib import Path
import threading
import time

import cupy as cp
import numpy as np
import pynvml as nv
import gjxl_backend as host
from gjxl_resident import CreateOptions, DeviceBatch, DeviceTile, tile_descriptor

ROOT = Path('/w/g5')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def memory():
    device = nv.nvmlDeviceGetHandleByIndex(0)
    vram = sum(p.usedGpuMemory for p in nv.nvmlDeviceGetComputeRunningProcesses(device)
               if p.pid == os.getpid())
    rss = int(next(s.split()[1] for s in Path('/proc/self/smaps_rollup').read_text().splitlines()
                   if s.startswith('Rss:'))) * 1024
    return dict(vram_bytes=vram, rss_bytes=rss)


class Encoder:
    def __init__(self, library, contexts):
        self.api = C.CDLL(library)
        host._declare(self.api)
        for name, args, result in (
            ('create', [C.POINTER(CreateOptions), C.POINTER(C.c_void_p)], C.c_int32),
            ('destroy', [C.c_void_p], None),
            ('release_device_memory', [C.c_void_p, C.POINTER(C.c_uint64)], C.c_int32),
            ('device_memory_bytes', [C.c_void_p, C.POINTER(C.c_uint64)], C.c_int32),
            ('encode_host', [C.c_void_p, C.POINTER(host._Image), C.c_size_t,
                             C.POINTER(host._EncoderOptions), C.POINTER(host._Buffer)], C.c_int32),
            ('encode_device', [C.c_void_p, C.POINTER(DeviceBatch),
                               C.POINTER(host._EncoderOptions), C.POINTER(host._Buffer)], C.c_int32),
        ):
            f = getattr(self.api, 'gjxl_encoder_' + name)
            f.argtypes, f.restype = args, result
        self.handle = C.c_void_p()
        opts = CreateOptions(C.sizeof(CreateOptions), 0, contexts, 2048 * 1024**2, contexts)
        self.check(self.api.gjxl_encoder_create(C.byref(opts), C.byref(self.handle)))

    def check(self, status):
        if status:
            raise RuntimeError(f'{status}: {self.api.gjxl_get_last_error().decode()}')

    def release(self):
        released, live = C.c_uint64(), C.c_uint64()
        self.check(self.api.gjxl_encoder_release_device_memory(self.handle, C.byref(released)))
        self.check(self.api.gjxl_encoder_device_memory_bytes(self.handle, C.byref(live)))
        return dict(released_bytes=released.value, live_bytes=live.value)

    def encode(self, pixels, distance, layout):
        options = host._EncoderOptions()
        self.check(self.api.gjxl_encoder_options_init(C.byref(options), C.sizeof(options)))
        options.distance, options.effort, options.entropy_behavior = distance, 8, 1
        n = len(pixels)
        outputs = (host._Buffer*n)()
        device = None
        try:
            if layout == 'host':
                views = (host._Image*n)(*(host._Image(C.sizeof(host._Image),
                    p.shape[1], p.shape[0], 1, p.ctypes.data, p.nbytes, p.strides[0]) for p in pixels))
                self.check(self.api.gjxl_encoder_encode_host(self.handle, views, n,
                                                            C.byref(options), outputs))
            else:
                device = [cp.asarray(p) if layout == 'hwc' else
                          cp.asarray(np.ascontiguousarray(p.transpose(2, 0, 1))).transpose(1, 2, 0)
                          for p in pixels]
                ready = cp.cuda.Event(disable_timing=True)
                consumed = cp.cuda.Event(disable_timing=True)
                ready.record()
                views = (DeviceTile*n)(*(tile_descriptor(p) for p in device))
                batch = DeviceBatch(C.sizeof(DeviceBatch), views, n, ready.ptr, consumed.ptr)
                self.check(self.api.gjxl_encoder_encode_device(self.handle, C.byref(batch),
                                                              C.byref(options), outputs))
                consumed.synchronize()
            return [C.string_at(o.data, o.size) for o in outputs]
        finally:
            for o in outputs:
                self.api.gjxl_buffer_free(C.byref(o))

    def close(self):
        self.api.gjxl_encoder_destroy(self.handle)


def rows_for_source(path, distance):
    pixels = np.load(path, mmap_mode='r')
    assert pixels.dtype == np.uint8 and pixels.shape[2] == 3
    for factor in (1, 4, 16):
        h, w = ((pixels.shape[i] + factor - 1)//factor for i in (0, 1))
        for y in range(0, h, 512):
            for x in range(0, w, 512):
                yield dict(name=f'{path.parent.name}/{path.stem}/l{factor}-{y}-{x}',
                           source=str(path), factor=factor, y=y, x=x,
                           distance=distance, kind='npy')


def manifest(args):
    rows = []
    for dataset in ('poc120', 'dev'):
        rows += [dict(name=dataset+'/'+p.stem, source=str(p), kind='rgb', distance=1.2)
                 for p in sorted(Path('/w/corpus', dataset).glob('*.rgb'))]
    for value in (0, 1, 2, 4, 16, 127, 255):
        rows.append(dict(name=f'edge/constant-{value}', value=value, kind='constant', distance=1.19))
    for h, w in ((1, 1), (1, 512), (512, 1), (13, 17), (511, 509), (512, 512), (257, 129)):
        rows.append(dict(name=f'edge/random-{h}-{w}', shape=[h, w, 3], kind='random', distance=1.19))
    sources = [
        ('eumetsatrapid-F-202610121200/original.npy', 1.19),
        ('eumetsatrapid-F-202610131500/original.npy', 1.19),
        ('eumetsatrapid-F-202610141200/original.npy', 1.19),
        ('eumetsatrapid-F-202610152325/original.npy', 1.19),
        ('eumetsat-F-202610121200/original.npy', 1.19),
        ('eumetsatmtg-F-202610131800-staged/full-original.npy', 1.19),
        ('goes18-F-202610122100-staged/full-original.npy', host.ROUTE_DISTANCES['goesfd']),
        ('himawari-F-202610121500-ahi-night-staged-guarded/primary-original.npy', 1.275),
        ('himawari-F-202610121500-ahi-night-staged-guarded/east-original.npy', 1.275),
    ]
    for source, distance in sources:
        path = Path('/captures', source)
        if not path.exists():
            raise FileNotFoundError(path)
        rows += list(rows_for_source(path, distance))
    Path(args.output).write_text(json.dumps(rows, indent=2)+'\n')
    print(json.dumps(dict(tiles=len(rows), sources=len(sources))))


def pixels(row):
    if row['kind'] == 'rgb':
        return np.fromfile(row['source'], np.uint8).reshape(512, 512, 3)
    if row['kind'] == 'mutate':
        tile = np.fromfile(row['source'], np.uint8).reshape(512, 512, 3)
        if row['operation'] == 'scale':
            return np.clip(np.round(tile.astype(float)*row['value']), 0, 255).astype(np.uint8)
        if row['operation'] == 'threshold':
            tile[tile < row['value']] = 0
            return tile
        if row['operation'] == 'noise':
            noise = np.random.default_rng(row['value']).integers(-1, 2, tile.shape, np.int16)
            return np.clip(tile.astype(np.int16)+noise, 0, 255).astype(np.uint8)
        return tile
    if row['kind'] == 'constant':
        return np.full((512, 512, 3), row['value'], np.uint8)
    if row['kind'] == 'random':
        return np.random.default_rng(71).integers(0, 256, row['shape'], np.uint8)
    if row['kind'] == 'sparse':
        tile = np.zeros((512, 512, 3), np.uint8)
        size, value, pattern, offset = (row[k] for k in ('size', 'value', 'pattern', 'offset'))
        rng = np.random.default_rng(71)
        patch = rng.integers(0, value+1, (size, size, 3), np.uint8)
        if pattern == 'flat':
            patch[:] = value
        elif pattern == 'wave':
            y, x = np.mgrid[:size, :size]
            patch[:] = np.round((np.sin(x*2.3)+np.cos(y*1.7)+2)*value/4).astype(np.uint8)[:, :, None]
        tile[offset:offset+size, offset:offset+size] = patch
        return tile
    if row['kind'] == 'mixture':
        rng = np.random.default_rng(row['seed'])
        tile = rng.integers(0, row['noise']+1, (512, 512, 3), np.uint8)
        part = np.fromfile(row['source'], np.uint8).reshape(512, 512, 3)
        y, x = np.mgrid[:512, :512]
        mask = ((x < row['cut']) if row['pattern'] == 0 else
                ((x+y < 2*row['cut']) if row['pattern'] == 1 else
                 ((x-256)**2+(y-256)**2 < row['cut']**2)))
        tile[mask] = part[mask]
        return tile
    source = np.load(row['source'], mmap_mode='r')
    f, y, x = row['factor'], row['y'], row['x']
    # DeviceOverviews samples the original RGB at global phase zero, [::f].
    h, w = ((source.shape[i] + f - 1)//f for i in (0, 1))
    yy = np.arange(y, min(y+512, h))*f
    xx = np.arange(x, min(x+512, w))*f
    tile = np.zeros((512, 512, 3), np.uint8)
    tile[:len(yy), :len(xx)] = source[yy[:, None], xx[None, :], :]
    return tile


def batches(rows, count):
    for _, grouped in itertools.groupby(rows, key=lambda r: r['distance']):
        grouped = list(grouped)
        for offset in range(0, len(grouped), count):
            yield grouped[offset:offset+count]


def scan(args):
    rows = json.loads(Path(args.manifest).read_text())
    if args.select:
        rows = [r for r in rows if args.select in r['name']]
    rows = rows[args.start:args.start+args.count]
    baseline = json.loads(Path(args.baseline).read_text())['records'] if args.baseline else {}
    records, releases, mismatches = {}, 0, []
    stop = threading.Event()
    peak = [0]
    def sample():
        device = nv.nvmlDeviceGetHandleByIndex(0)
        while not stop.is_set():
            used = sum(p.usedGpuMemory for p in nv.nvmlDeviceGetComputeRunningProcesses(device)
                       if p.pid == os.getpid())
            peak[0] = max(peak[0], used)
            stop.wait(.02)
    monitor = threading.Thread(target=sample)
    monitor.start()
    e = None
    try:
        e = Encoder(args.library, args.contexts)
        for batch in batches(rows, args.batch):
            images = [pixels(r) for r in batch]
            if args.release:
                assert e.release()['live_bytes'] == 0
                releases += 1
            results = [{} for r in batch]
            for layout in args.layouts.split(','):
                try:
                    outputs = e.encode(images, batch[0]['distance'], layout)
                except RuntimeError:
                    outputs = []
                    for row, p in zip(batch, images):
                        try:
                            outputs.append(e.encode([p], row['distance'], layout)[0])
                        except RuntimeError as error:
                            outputs.append(str(error))
                for row, p, result, out in zip(batch, images, results, outputs):
                    if isinstance(out, str):
                        result[layout] = dict(error=out)
                        target = ROOT/'failures'/(row['name'].replace('/', '_')+'.rgb')
                        target.parent.mkdir(exist_ok=True)
                        p.tofile(target)
                        print(json.dumps(dict(name=row['name'], layout=layout, error=out)), flush=True)
                    else:
                        result[layout] = dict(sha256=digest(out), bytes=len(out))
                        if args.save:
                            target = Path(args.save, row['name']+'.jxl')
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(out)
            for row, result in zip(batch, results):
                hashes = {v['sha256'] for v in result.values() if 'sha256' in v}
                if len(hashes) > 1:
                    mismatches.append(row['name'])
                if row['name'] in baseline:
                    for layout, old in baseline[row['name']].items():
                        if 'sha256' in old and result.get(layout, {}).get('sha256') != old['sha256']:
                            mismatches.append(row['name']+'/'+layout)
                records[row['name']] = result
            print(json.dumps(dict(completed=len(records), last=batch[-1]['name'])), flush=True)
        failures = sum('error' in v for row in records.values() for v in row.values())
        report = dict(tiles=len(rows), failures=failures, mismatches=mismatches,
                      records=records, releases=releases, contexts=args.contexts,
                      manifest_sha256=digest(Path(args.manifest).read_bytes()),
                      blocking_waits=os.environ.get('GJXL_E4_BLOCKING_WAITS'),
                      library_sha256=digest(Path(args.library).read_bytes()), memory=memory(),
                      peak_process_vram_bytes=peak[0])
        Path(args.output).write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k != 'records'}), flush=True)
    finally:
        if e:
            e.close()
        stop.set()
        monitor.join()


def synthetic(args):
    rows = []
    for distance, size, value, pattern in itertools.product(
            (1.19, 1.21, 1.275),
            (1, 2, 7, 8, 15, 16, 31, 32, 63, 64, 127, 128, 255, 256, 511),
            (1, 2, 3, 5, 10, 32, 128, 255), ('flat', 'noise', 'wave')):
        for offset in sorted({0, (512-size)//2}):
            rows.append(dict(kind='sparse', distance=distance, size=size, value=value,
                             pattern=pattern, offset=offset,
                             name=f'sparse/{distance}-{size}-{value}-{pattern}-{offset}'))
    Path(args.output).write_text(json.dumps(rows, indent=2)+'\n')
    print(json.dumps(dict(tiles=len(rows))))


def mixtures(args):
    sources = sorted(Path('/w/corpus/poc120').glob('*.rgb'))[::8]
    rows = []
    for source, noise, cut, pattern in itertools.product(
            sources, (0, 1, 2, 4),
            (31, 64, 127, 192, 248, 256, 264, 320, 352, 360, 368, 384, 448, 481),
            (0, 1, 2)):
        rows.append(dict(kind='mixture', name=f'mixture/{source.stem}-{noise}-{cut}-{pattern}',
                         source=str(source), distance=1.19, seed=123, noise=noise,
                         cut=cut, pattern=pattern))
    Path(args.output).write_text(json.dumps(rows, indent=2)+'\n')
    print(json.dumps(dict(tiles=len(rows))))


def mutations(args):
    sources = [r for r in json.loads((ROOT/'published.json').read_text()) if '/l0-' not in r['name']]
    rows = []
    for source in sources:
        for operation, values in [('scale', np.linspace(.5, 1.5, 41)),
                                  ('threshold', range(1, 33)), ('noise', range(32)),
                                  ('distance', np.linspace(.8, 1.6, 81))]:
            for value in values:
                rows.append(dict(kind='mutate', source=source['source'], operation=operation,
                                 value=float(value) if operation in ('scale', 'distance') else int(value),
                                 name=source['name']+f'/{operation}-{value}',
                                 distance=float(value) if operation == 'distance' else 1.19))
    Path(args.output).write_text(json.dumps(rows, indent=2)+'\n')
    print(json.dumps(dict(tiles=len(rows))))


def endurance(args):
    rows = json.loads(Path(args.manifest).read_text())
    if args.select:
        rows = [r for r in rows if args.select in r['name']]
    assert rows
    rows = [rows[i % len(rows)] for i in range(10)]
    images = [pixels(r) for r in rows]
    # One route per concurrent call; the repro manifest uses the same distance.
    distance = rows[0]['distance']
    samples = []
    stop = threading.Event()
    peak = [0]
    def sample():
        device = nv.nvmlDeviceGetHandleByIndex(0)
        while not stop.is_set():
            used = sum(p.usedGpuMemory for p in nv.nvmlDeviceGetComputeRunningProcesses(device)
                       if p.pid == os.getpid())
            peak[0] = max(peak[0], used)
            stop.wait(.02)
    monitor = threading.Thread(target=sample)
    monitor.start()
    e = None
    try:
        e = Encoder(args.library, args.contexts)
        oracle = e.encode(images, distance, 'host')
        with ThreadPoolExecutor(max_workers=4) as pool:
            # Exercise deferred release during a genuinely active call.
            pending = pool.submit(e.encode, [images[0]]*1170, distance, 'host')
            time.sleep(.02)
            assert not pending.done(), 'Busy call completed before release probe'
            busy = e.release()
            assert busy['released_bytes'] == 0, busy
            assert pending.result() == [oracle[0]]*1170
            assert e.release()['live_bytes'] == 0
            for cycle in range(args.cycles):
                calls = []
                for caller, (start, end) in enumerate(((0, 3), (3, 6), (6, 8), (8, 10))):
                    layout = ('host', 'hwc', 'chw')[(cycle+caller) % 3]
                    calls.append((start, end, pool.submit(e.encode, images[start:end], distance, layout)))
                for start, end, call in calls:
                    assert call.result() == oracle[start:end], (cycle, start)
                released = e.release()
                assert released['live_bytes'] == 0
                cp.get_default_memory_pool().free_all_blocks()
                samples.append(dict(cycle=cycle, encodes=(cycle+1)*10, **released, **memory()))
                if cycle % 50 == 0:
                    print(json.dumps(samples[-1]), flush=True)
        steady = samples[20:]
        spans = {key: max(s[key] for s in steady)-min(s[key] for s in steady)
                 for key in ('rss_bytes', 'vram_bytes')}
        assert spans['rss_bytes'] <= 32*1024**2 and spans['vram_bytes'] <= 16*1024**2, spans
        assert peak[0] <= 2048*1024**2, peak
        report = dict(passed=True, encodes=args.cycles*10, cycles=args.cycles,
                      concurrent_callers=4, contexts=args.contexts,
                      peak_process_vram_bytes=peak[0], steady_spans_bytes=spans,
                      busy_release=busy, records=samples,
                      blocking_waits=os.environ.get('GJXL_E4_BLOCKING_WAITS'),
                      library_sha256=digest(Path(args.library).read_bytes()))
        Path(args.output).write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k != 'records'}), flush=True)
    finally:
        if e:
            e.close()
        stop.set()
        monitor.join()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['manifest', 'scan', 'synthetic', 'mixtures', 'mutations', 'endurance'])
    p.add_argument('--output', required=True)
    p.add_argument('--library', default='/w/g5/baseline/libgjxl.so')
    p.add_argument('--manifest', default='/w/g5/manifest.json')
    p.add_argument('--contexts', type=int, default=12)
    p.add_argument('--select', default='')
    p.add_argument('--start', type=int, default=0)
    p.add_argument('--count', type=int, default=100000)
    p.add_argument('--batch', type=int, default=24)
    p.add_argument('--cycles', type=int, default=1000)
    p.add_argument('--layouts', default='host,hwc,chw')
    p.add_argument('--baseline')
    p.add_argument('--save')
    p.add_argument('--release', action='store_true')
    args = p.parse_args()
    nv.nvmlInit()
    try:
        globals()[args.mode](args)
    finally:
        nv.nvmlShutdown()

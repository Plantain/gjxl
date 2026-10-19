"""Fail-closed collector for the G5 qualification evidence."""
import argparse
import hashlib
import json
from pathlib import Path

BASE = 'f98f28726b8ce2c9f5f263510e29e830fc6addfa00d512adfa25499632546cb8'
FIX = '1eadf15abc87a7dd36e4ff1420674d46145479c26c25d12af33cbb018d150aff'


def collect(root):
    sources = {}
    guards = []
    def read(name):
        path = root/name
        data = path.read_bytes()
        sources[name] = hashlib.sha256(data).hexdigest()
        return json.loads(data)
    def guard(label):
        value = read(label+'.guard.json')
        assert value['returncode'] == 0 and value['stopped'] is None, label
        assert value['minimum_free_bytes'] >= 12*1024**3, label
        assert value['seconds'] <= 270, label
        assert (root/(label+'.exitcode')).read_text().strip() == '0', label
        guards.append(value)
        return value
    def receipt(label):
        value = read(label+'.receipt.json')
        assert value['passed']
        guard(value['receipt'])
        return value['receipt']
    decode = read('decode.json')
    assert decode['passed'] and decode['decoded'] == len(decode['hashes'])
    assert decode['decoded'] >= 128
    assert decode['seconds'] <= 270
    assert (root/'stock-decode.exitcode').read_text().strip() == '0'
    decoded_names = {name.removesuffix('.jxl') for name in decode['hashes']}
    assert all(set(sample) <= decoded_names for sample in decode['group_samples'].values())
    comparisons, newly_encodable, tiles = 0, [], 0
    names = set()
    peak = 0
    for task in [f'matrix-{i}' for i in range(12)] + ['mutations', 'published']:
        baseline = read(task+'-baseline.json')
        candidate = read(task+'-candidate.json')
        receipt(task+'-baseline')
        receipt(task+'-candidate')
        assert baseline['library_sha256'] == BASE and candidate['library_sha256'] == FIX, task
        assert baseline['manifest_sha256'] == candidate['manifest_sha256'], task
        manifest = 'manifest-exact' if task.startswith('matrix-') else task
        assert candidate['manifest_sha256'] == decode['manifest_sha256'][manifest+'.json'], task
        assert not baseline['mismatches'] and not candidate['mismatches'], task
        assert candidate['failures'] == 0, task
        assert baseline['records'].keys() == candidate['records'].keys(), task
        assert candidate['tiles'] == len(candidate['records']), task
        tiles += candidate['tiles']
        peak = max(peak, candidate['peak_process_vram_bytes'])
        for name, result in candidate['records'].items():
            assert name not in names, ('Duplicate identity input', name)
            names.add(name)
            assert set(result) == {'host', 'hwc', 'chw'}, name
            assert len({v['sha256'] for v in result.values()}) == 1, name
            if name in decoded_names:
                assert decode['hashes'][name+'.jxl'] == result['host']['sha256'], name
            if name.startswith('edge/'):
                assert name in decoded_names, name
            for layout, old in baseline['records'][name].items():
                if 'error' in old:
                    assert 'raw-quant readback is invalid' in old['error'], name
                    newly_encodable.append(name+'/'+layout)
                else:
                    assert result[layout] == old, (name, layout)
                    comparisons += 1
    assert tiles == 13197 and len(newly_encodable) == 3, (tiles, newly_encodable)
    assert len(names) == tiles
    assert decoded_names <= names | {'repro/raw-quant-257'}
    newly_encodable_names = {name.rsplit('/', 1)[0] for name in newly_encodable}
    assert set(decode['previously_failed']) == newly_encodable_names
    assert newly_encodable_names <= decoded_names
    fresh = read('repro-baseline-fresh.json')
    guard('repro-baseline-fresh')
    assert fresh['library_sha256'] == BASE and fresh['failures'] == 3
    assert fresh['contexts'] == 1 and fresh['releases'] == 0
    for waits in (0, 1):
        base = read(f'repro-base-{waits}.json')
        fix = read(f'repro-fix-{waits}.json')
        guard(f'repro-base-{waits}')
        guard(f'repro-fix-{waits}')
        assert base['library_sha256'] == BASE and base['failures'] == 3
        assert fix['library_sha256'] == FIX and fix['failures'] == 0
        assert not fix['mismatches']
        for result in fix['records']['repro/raw-quant-257'].values():
            assert result['sha256'] == decode['hashes']['repro/raw-quant-257.jxl']
    plateau = []
    for waits in (0, 1):
        data = read(f'plateau-{waits}.json')
        receipt(f'plateau-{waits}')
        assert data['passed'] and data['library_sha256'] == FIX
        assert data['blocking_waits'] == str(waits)
        assert data['encodes'] >= 10000 and data['cycles'] >= 1000
        assert data['contexts'] == 12 and data['concurrent_callers'] == 4
        assert data['steady_spans_bytes']['rss_bytes'] <= 32*1024**2
        assert data['steady_spans_bytes']['vram_bytes'] <= 16*1024**2
        assert all(r['live_bytes'] == 0 for r in data['records'])
        assert data['busy_release']['released_bytes'] == 0
        peak = max(peak, data['peak_process_vram_bytes'])
        plateau.append({k:v for k,v in data.items() if k != 'records'})
    assert peak <= 2048*1024**2
    sanitizers = {}
    for kind in ('memcheck', 'initcheck', 'racecheck'):
        label = receipt('sanitize-'+kind)
        log = (root/(label+'.log')).read_text()
        expected = ('RACECHECK SUMMARY: 0 hazards displayed (0 errors, 0 warnings)'
                    if kind == 'racecheck' else 'ERROR SUMMARY: 0 errors')
        assert expected in log and 'Raw-quant regression passed: 3 encodes' in log, kind
        sanitizers[kind] = 'clean'
    label = receipt('regression-native')
    assert '30 encodes' in (root/(label+'.log')).read_text()
    receipt('ctest')
    patch = read('patch-check.json')
    assert patch['passed']
    assert hashlib.sha256((root/'elastic-vram-rawquant.patch').read_bytes()).hexdigest() == patch['patch_sha256']
    release = read('release.json')
    assert release['library_sha256'] == FIX and release['patch_sha256'] == patch['patch_sha256']
    return dict(passed=True, baseline_library_sha256=BASE, library_sha256=FIX,
                tiles=tiles, unchanged_layout_outputs=comparisons,
                newly_encodable_layout_outputs=newly_encodable,
                decoded=decode['decoded'], sanitizers=sanitizers, plateau=plateau,
                peak_process_vram_bytes=peak,
                minimum_free_bytes=min(g['minimum_free_bytes'] for g in guards),
                longest_guarded_seconds=max(g['seconds'] for g in guards),
                patch_sha256=patch['patch_sha256'], artifact_sha256=sources)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('evidence', type=Path)
    args = parser.parse_args()
    report = collect(args.evidence)
    (args.evidence/'gate.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('artifact_sha256', 'plateau')}))

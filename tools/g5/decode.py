"""Stock djxl conformance for a deterministic, stratified candidate sample."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time

started = time.monotonic()
root = Path('/w/g5')
decoder = Path('/w/wp0/libjxl/build/tools/djxl')
groups = defaultdict(list)
selected = {'repro/raw-quant-257'}
manifest_sha256 = {}
for manifest in ('manifest-exact', 'mutations', 'published'):
    data = (root/(manifest+'.json')).read_bytes()
    manifest_sha256[manifest+'.json'] = hashlib.sha256(data).hexdigest()
    for row in json.loads(data):
        name = row['name']
        if name.startswith('edge/'):
            selected.add(name)
        if row['kind'] == 'npy':
            group = name.rsplit('/', 1)[0]+'/l'+str(row['factor'])
        elif row['kind'] == 'mutate':
            group = 'mutations/'+row['operation']
        elif manifest == 'published':
            group = name.rsplit('-', 2)[0]
        else:
            group = name.split('/')[0]
        groups[group].append(name)

group_samples = {}
for group, names in sorted(groups.items()):
    names = sorted(names)
    sample = sorted({names[0], names[len(names)//2], names[-1]})
    group_samples[group] = sample
    selected.update(sample)
# Explicitly decode every input newly accepted by this fix.
baseline = json.loads((root/'results/mutations-baseline.json').read_text())
previously_failed = sorted(name for name, result in baseline['records'].items()
                           if any('error' in value for value in result.values()))
assert previously_failed
selected.update(previously_failed)
# Fill to at least 128 by a stable hash order, independent of file timestamps.
population = {name for names in groups.values() for name in names}
for name in sorted(population, key=lambda n: hashlib.sha256(n.encode()).digest()):
    if len(selected) >= 128:
        break
    selected.add(name)
files = [root/'codestreams'/(name+'.jxl') for name in sorted(selected)]


def decode(path):
    with tempfile.TemporaryDirectory(prefix='g5-decode-') as tmp:
        result = subprocess.run([str(decoder), str(path), tmp+'/decoded.ppm', '--num_threads=1'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            raise RuntimeError((str(path), result.stderr.decode()))
    return str(path.relative_to(root/'codestreams')), hashlib.sha256(path.read_bytes()).hexdigest()


with ThreadPoolExecutor(max_workers=8) as pool:
    decoded = list(pool.map(decode, files))
report = dict(passed=True, decoded=len(decoded), hashes=dict(decoded),
              decoder=str(decoder),
              decoder_version=subprocess.check_output(
                  [str(decoder), '--version'], stderr=subprocess.STDOUT, text=True).strip(),
              decoder_sha256=hashlib.sha256(decoder.read_bytes()).hexdigest(),
              seconds=time.monotonic()-started,
              manifest_sha256=manifest_sha256,
              selection='All edge cases and formerly failing inputs; first/middle/last '
                        'per corpus, source/overview, mutation operation and published '
                        'overview; stable SHA256 order fills to 128; plus regression.',
              group_samples=group_samples, previously_failed=previously_failed)
(root/'results/decode.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(dict(passed=True, decoded=len(decoded))))

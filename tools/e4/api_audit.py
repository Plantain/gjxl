#!/usr/bin/env python3
"""Count all traced CUDA APIs in a warmed graph capture; no speed inference."""
import argparse
from collections import Counter
import json
import sqlite3


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('sqlite')
    p.add_argument('--tiles', type=int, required=True)
    a = p.parse_args()
    if a.tiles <= 0:
        p.error('Positive tile count required')
    db = sqlite3.connect(a.sqlite)
    strings = dict(db.execute('select id,value from StringIds'))
    tables = {r[0] for r in db.execute('select name from sqlite_master')}
    counts = {}
    for table in ('CUPTI_ACTIVITY_KIND_RUNTIME', 'CUPTI_ACTIVITY_KIND_DRIVER'):
        if table not in tables:
            continue
        counts[table] = {
            strings[name]: count for name, count in db.execute(
                f'select nameId,count(*) from {table} group by nameId')}
    runtime = Counter()
    for name, count in counts['CUPTI_ACTIVITY_KIND_RUNTIME'].items():
        runtime[name.split('_v')[0]] += count
    assert runtime.get('cudaGraphLaunch', 0) == 3 * a.tiles, runtime
    lifecycle = {table: {name: count for name, count in calls.items()
                        if any(s in name for s in ('Alloc', 'Malloc', 'Free',
                                                   'Create', 'Destroy', 'Instantiate'))}
                 for table, calls in counts.items()}
    result = dict(source=a.sqlite, tiles=a.tiles, cuda_api_counts=counts,
                  lifecycle_calls=lifecycle,
                  graph_launches_per_tile=runtime['cudaGraphLaunch'] / a.tiles,
                  graph_parameter_updates_per_tile=
                      runtime.get('cudaGraphExecKernelNodeSetParams', 0) / a.tiles,
                  caveat='Warmed API-count audit on loaded host; no timing comparison.')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()

"""Decode published COGs, retaining all base and actual overview tile pixels."""
import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio

root = Path('/w/g5')
rows, sources = [], []
for source in sorted((root/'published').glob('*.tiff')):
    sources.append(dict(path=str(source), sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    for level in (-1, 0, 1):
        options = {} if level == -1 else dict(overview_level=level)
        with rasterio.open(source, **options) as ds:
            for index, window in ds.block_windows(1):
                image = ds.read(window=window)[:3].transpose(1, 2, 0)
                tile = np.zeros((512, 512, 3), np.uint8)
                tile[:image.shape[0], :image.shape[1]] = image
                name = f'published/{source.stem}/l{level+1}-{index[0]}-{index[1]}'
                output = root/'published-rgb'/(name+'.rgb')
                output.parent.mkdir(parents=True, exist_ok=True)
                tile.tofile(output)
                rows.append(dict(kind='rgb', source=str(output), name=name, distance=1.19,
                                 rgb_sha256=hashlib.sha256(tile).hexdigest()))
(root/'published.json').write_text(json.dumps(rows, indent=2)+'\n')
(root/'results/published-sources.json').write_text(json.dumps(sources, indent=2)+'\n')
print(json.dumps(dict(tiles=len(rows), sources=len(sources))))

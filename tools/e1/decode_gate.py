#!/usr/bin/env python3
"""Decode every saved identity codestream with pinned stock djxl, eight jobs."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(sys.argv[1])
djxl = sys.argv[2]
files = sorted(root.rglob("*.jxl"))
assert files


def check(path):
    with tempfile.TemporaryDirectory(prefix="e1-decode-") as directory:
        output = Path(directory) / "decoded.ppm"
        run = subprocess.run([djxl, str(path), str(output), "--num_threads=1", "--quiet"],
                             capture_output=True, text=True)
        if run.returncode:
            raise RuntimeError(f"{path}: {run.stderr}")
        if not output.exists() or output.stat().st_size < 512 * 512 * 3:
            raise RuntimeError(f"Incomplete decoded tile: {path}")
    return {"file": str(path.relative_to(root)), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "decoded": True}


with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    rows = list(pool.map(check, files))
print(json.dumps({"stock_djxl": djxl, "decoded": len(rows), "failed": 0, "files": rows}, indent=2))

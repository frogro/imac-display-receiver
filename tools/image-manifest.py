#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
import hashlib
import json
from pathlib import Path
import sys

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while b := f.read(4*1024*1024):
            h.update(b)
    return h.hexdigest()

if __name__ == '__main__':
    raw = Path(sys.argv[1])
    compressed = raw.with_suffix(raw.suffix+'.gz')
    result = {'project':'imac-display-receiver','schema':1,'image':compressed.name,
              'raw_bytes':raw.stat().st_size,'raw_sha256':digest(raw),
              'gzip_sha256':digest(compressed)}
    Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n')

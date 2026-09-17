"""
core/atomicfile.py – write a file so it is never left half-written.

A plain write_text() truncates the file first and then writes. A crash,
a kill or a power cut in between leaves an empty or cut-off JSON file -
for the app config that means "all settings back to default" on the next
start.

Instead: write a sibling .tmp file, flush it to disk, then os.replace()
it over the real one. os.replace is a single step on Linux and Windows:
afterwards the file is either completely old or completely new.
"""

# Copyright (C) 2026 yakuda
# SPDX-License-Identifier: GPL-3.0-or-later

import os
from pathlib import Path


def write_text_atomic(path, text, encoding="utf-8"):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding=encoding) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except PermissionError:
        # Windows: a virus scanner or an editor holding the target can
        # make os.replace fail. Saving the old way beats not saving.
        try:
            tmp.unlink()
        except OSError:
            pass
        path.write_text(text, encoding=encoding)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise

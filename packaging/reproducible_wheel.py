#!/usr/bin/env python3
"""The wheel the same bytes for the same commit.

``reproducible_wheel.py WHEEL...`` writes each .whl again: its files in name order (the .dist-info folder
last, RECORD its last file, as the wheel format asks), each one's time ``$SOURCE_DATE_EPOCH`` (the commit's:
release.yml), modes 0644 / 0755, made "on Unix", no extra fields, no comments, no folder entries, one
compression. setuptools kept the modes of the build's own files, which follow the builder's umask and
checkout (0644, 0600 and 0664 gave three wheels of one commit). The files' contents are not touched, so
RECORD - their hashes - stays true; ``--check WHEEL...`` fails unless each file is the one RECORD names
(its SHA-256 and size) and the wheel is written as this script writes it. Python's standard library only.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import sys
import time
import zipfile

#: The earliest time a zip entry can carry (1980-01-01): the time without SOURCE_DATE_EPOCH.
ZIP_EPOCH = 315532800


def _order(name: str) -> tuple:
    """Files in name order - the .dist-info folder's after the others, RECORD the last of all."""
    top = name.split("/", 1)[0]
    return (top.endswith(".dist-info"), name.endswith(".dist-info/RECORD"), name)


def rewritten(data: bytes, epoch: int) -> bytes:
    """The wheel *data* written again as described above."""
    stamp = time.gmtime(max(epoch, ZIP_EPOCH))[:6]
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as target:
        names = [info.filename for info in source.infolist() if not info.is_dir()]
        if len(set(names)) != len(names):
            raise ValueError("a file is in the wheel twice")
        for name in sorted(names, key=_order):
            old = source.getinfo(name)
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.create_system = 3  # (Unix: the mode below is read as one)
            runs = (old.external_attr >> 16) & 0o111
            info.external_attr = (0o100755 if runs else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(info, source.read(name), compresslevel=9)
    return out.getvalue()


def problems(data: bytes) -> list[str]:
    """What is wrong with the wheel *data*: a file RECORD does not name or names with another hash or
    size, a file of RECORD that is missing, and - not written by :func:`rewritten` - a mode, an order or a
    time of the build's own."""
    found = []
    with zipfile.ZipFile(io.BytesIO(data)) as wheel:
        infos = [info for info in wheel.infolist() if not info.is_dir()]
        names = [info.filename for info in infos]
        records = [name for name in names if name.endswith(".dist-info/RECORD") and name.count("/") == 1]
        if len(records) != 1:
            return [f"{len(records)} RECORD files"]
        listed = {}
        for row in csv.reader(io.StringIO(wheel.read(records[0]).decode("utf-8"))):
            if len(row) == 3:
                listed[row[0]] = (row[1], row[2])
        for name in names:
            if name == records[0]:
                continue
            if name not in listed:
                found.append(f"{name} is not in RECORD")
                continue
            content = wheel.read(name)
            digest = "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
            if listed[name] != (digest, str(len(content))):
                found.append(f"{name} is not the file RECORD names")
        found += [f"{name} of RECORD is missing" for name in listed if name not in names and name != records[0]]
        if names != sorted(names, key=_order):
            found.append("the files are not in order")
        if len(wheel.infolist()) != len(infos):
            found.append("folder entries")
        modes = {(info.external_attr >> 16) for info in infos} - {0o100644, 0o100755}
        if modes:
            found.append("modes of the build's own: " + ", ".join(sorted(oct(mode) for mode in modes)))
        if len({info.date_time for info in infos}) > 1:
            found.append("more than one time")
        if any(info.extra or info.comment or info.create_system != 3 for info in infos) or wheel.comment:
            found.append("extra fields, comments or another system's entries")
    return found


def main(argv: list[str]) -> int:
    check = "--check" in argv
    paths = [arg for arg in argv[1:] if arg != "--check"]
    if not paths:
        print(__doc__, file=sys.stderr)
        return 2
    failed = 0
    for path in paths:
        with open(path, "rb") as handle:
            data = handle.read()
        if check:
            for problem in problems(data):
                print(f"::error::{os.path.basename(path)}: {problem}")
                failed = 1
            continue
        epoch = int(os.environ.get("SOURCE_DATE_EPOCH", str(ZIP_EPOCH)))
        with open(path, "wb") as handle:
            handle.write(rewritten(data, epoch))
        print(f"{os.path.basename(path)}: written again (time {epoch})")
    return failed


if __name__ == "__main__":
    sys.exit(main(sys.argv))

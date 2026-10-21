"""Fingerprint a local file; never approve it for use on a camera."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys


CHUNK_SIZE = 1024 * 1024


def _identity(info):
    # Windows Python can expose different ctime meanings in stat and fstat.
    # Compare only portable fields; this is not an adversarial snapshot check.
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def inspect_file(path, expected_sha256=None):
    """Read an ordinary file and return its fingerprint, not firmware validation.

    Metadata checks catch ordinary concurrent edits, not adversarial changes
    that restore metadata. Use a stable local copy, not a live camera/card.
    """
    if expected_sha256 is not None:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
            raise ValueError("expected SHA-256 must contain exactly 64 hexadecimal characters")
        expected_sha256 = expected_sha256.lower()

    path = Path(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("input must be an ordinary file, not a directory or device")
    if before.st_size == 0:
        raise ValueError("input file is empty")

    digest = hashlib.sha256()
    with path.open("rb") as source:
        opened = os.fstat(source.fileno())
        if not stat.S_ISREG(opened.st_mode) or _identity(opened) != _identity(before):
            raise ValueError("input changed before reading; retry with a stable local copy")

        # Bound the read to the initial size so an appending writer cannot
        # make this loop run indefinitely. Do not accept partial fingerprints.
        remaining = before.st_size
        while remaining:
            block = source.read(min(CHUNK_SIZE, remaining))
            if not block:
                raise ValueError("input was truncated while reading")
            digest.update(block)
            remaining -= len(block)

        if (_identity(os.fstat(source.fileno())) != _identity(before)
                or _identity(path.stat()) != _identity(before)):
            raise ValueError("input changed while reading; retry with a stable local copy")

    actual = digest.hexdigest()
    return {
        "size_bytes": before.st_size,
        "sha256": actual,
        "expected_sha256": expected_sha256,
        "hash_match": None if expected_sha256 is None else actual == expected_sha256,
        "firmware_format": "unverified",
        "camera_model": "unverified",
        "firmware_version": "unverified",
        "camera_compatibility": "unverified",
        "safe_to_flash": False,
        "notice": "Fingerprint only. A hash match does not authenticate Canon firmware or authorize installation.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Read-only file fingerprinting. Does not validate firmware or camera compatibility."
    )
    parser.add_argument("file", type=Path, help="stable local copy of a file; no camera connection needed")
    parser.add_argument("--expect-sha256", help="compare with a separately obtained SHA-256")
    args = parser.parse_args(argv)
    try:
        report = inspect_file(args.file, args.expect_sha256)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["hash_match"] is False else 0


if __name__ == "__main__":
    raise SystemExit(main())

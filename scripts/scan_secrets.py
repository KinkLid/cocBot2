#!/usr/bin/env python3
"""Conservative scanner whose findings expose only locations and SHA-256 fingerprints."""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
from pathlib import Path

PATTERNS = [re.compile(rb"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")]


def findings(label: str, content: bytes) -> list[str]:
    return [f"{label}: sha256={hashlib.sha256(match.group()).hexdigest()[:12]}" for pattern in PATTERNS for match in pattern.finditer(content)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args()
    found: list[str] = []
    tracked = subprocess.check_output(["git", "ls-files", "-z"]).split(b"\0")
    for raw in tracked:
        if not raw: continue
        path = Path(raw.decode())
        if path == Path(".env.example"): continue
        try: found.extend(findings(str(path), path.read_bytes()))
        except OSError: pass
    if args.history:
        objects: dict[str, str] = {}
        for line in subprocess.check_output(["git", "rev-list", "--objects", "--all"]).decode(errors="replace").splitlines():
            oid, _, path = line.partition(" ")
            if path and path != ".env.example": objects.setdefault(oid, path)
        process = subprocess.Popen(["git", "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        assert process.stdin is not None and process.stdout is not None
        for oid, path in objects.items():
            process.stdin.write((oid + "\n").encode()); process.stdin.flush()
            header = process.stdout.readline().decode(errors="replace").split()
            if len(header) != 3:
                continue
            content = process.stdout.read(int(header[2])); process.stdout.read(1)
            if header[1] != "blob":
                continue
            found.extend(findings(f"object={oid[:12]} path={path}", content))
        process.stdin.close(); process.wait()
    for item in found: print(item)
    return 1 if found else 0


if __name__ == "__main__": raise SystemExit(main())

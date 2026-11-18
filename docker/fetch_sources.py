#!/usr/bin/env python3
"""Fetch only the public, digest-pinned native build inputs in sources.lock.json."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit


ALLOWED_HOSTS = {
    "www.python.org", "www.klayout.org", "codeload.github.com",
    "downloads.sourceforge.net", "nodejs.org", "github.com",
    "ngspice.sourceforge.io",
}


def validate_lock(record: dict) -> list[dict]:
    rows = record.get("files")
    if record.get("schema_version") != 1 or not isinstance(rows, list) or not rows:
        raise ValueError("Invalid native source lock")
    names = set()
    for row in rows:
        name, url, digest = row["name"], row["url"], row["sha256"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in names:
            raise ValueError("Invalid or duplicate native source filename")
        names.add(name)
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password:
            raise ValueError("Native source must use an allowed public HTTPS origin")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Missing SHA256 for native source")
    return rows


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fetch(lock: Path, destination: Path) -> None:
    rows = validate_lock(json.loads(lock.read_text()))
    destination.mkdir(parents=True, exist_ok=True)
    for row in rows:
        target = destination / row["name"]
        if target.is_file() and not target.is_symlink() and sha256(target) == row["sha256"]:
            print(f"Verified cached source: {row['name']}", flush=True)
            continue
        if target.exists() or target.is_symlink():
            raise ValueError(f"Existing source has a different digest: {row['name']}")
        partial = target.with_name(target.name + ".partial")
        subprocess.run([
            "curl", "--fail", "--show-error", "--location", "--proto", "=https",
            "--proto-redir", "=https", "--connect-timeout", "30", "--max-time", "900",
            "--retry", "3", "--retry-delay", "2", "--output", str(partial), row["url"],
        ], check=True)
        if partial.is_symlink() or sha256(partial) != row["sha256"]:
            raise ValueError(f"Downloaded source failed SHA256 verification: {row['name']}")
        partial.replace(target)
        print(f"Fetched and verified: {row['name']}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=Path(__file__).with_name("sources.lock.json"))
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    fetch(args.lock, args.destination)

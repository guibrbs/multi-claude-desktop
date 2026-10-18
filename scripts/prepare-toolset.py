#!/usr/bin/env python3
"""Developer-only package builder. Installation itself needs no Python/network."""
import argparse
import hashlib
from pathlib import Path
import re
import shutil
import subprocess

FILES = (
    "claude-apps-refresh.sh", "claude-build-worker.sh", "claude-cache-worker.sh",
    "claude-checkpoint-worker.sh", "claude-checkpoint.c", "claude-clear-caches.sh",
    "claude-instance-check.sh", "claude-instances-common.sh", "claude-integrity.c",
    "claude-maintenance.h", "claude-profile-checkpoint.sh", "claude-recolor-icon.sh",
    "claude-recolor-icon.swift", "claude-stale-check.sh", "claude-toolset.c",
    "claude-toolset.sh", "claude-transaction.c",
)


def mode_for(name):
    return 0o700 if name.endswith(".sh") and name != "claude-instances-common.sh" else 0o600


def prepare(source, destination, commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("commit must be a full lowercase Git commit identifier")
    names = {path.name for path in (source / "bin").iterdir()}
    if names != set(FILES):
        raise ValueError("unexpected or missing bin files; review the protocol inventory")
    destination.mkdir(mode=0o700)
    (destination / "bin").mkdir(mode=0o700)
    lines = ["MCD_TOOLSET 1", "protocol 1", "commit " + commit]
    for name in FILES:
        original = source / "bin" / name
        if original.is_symlink() or not original.is_file() or original.stat().st_nlink != 1:
            raise ValueError("source must contain regular single-link files")
        target = destination / "bin" / name
        shutil.copyfile(original, target)
        target.chmod(mode_for(name))
        lines.append(f"file {name} {mode_for(name):04o} {hashlib.sha256(target.read_bytes()).hexdigest()}")
    manifest = destination / "manifest.txt"
    manifest.write_text("\n".join(lines) + "\n", encoding="ascii")
    manifest.chmod(0o600)
    return hashlib.sha256(manifest.read_bytes()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="new package directory; never overwritten")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--commit", help="reviewed source identifier; defaults to source HEAD")
    args = parser.parse_args()
    if args.commit is None:
        changes = subprocess.check_output(["/usr/bin/git", "-C", str(args.source), "status", "--porcelain", "--untracked-files=all", "--", "bin"], text=True)
        if changes:
            parser.error("commit the reviewed bin changes before preparing a release package")
    commit = args.commit or subprocess.check_output(
        ["/usr/bin/git", "-C", str(args.source), "rev-parse", "HEAD"], text=True).strip()
    print(prepare(args.source, args.destination, commit))

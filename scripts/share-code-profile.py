#!/usr/bin/env python3
"""Share selected Claude Code files from the original profile with the Duo.

Links (destination -> source): CLAUDE.md, skills, output-styles, tools,
plugins and every projects/<project>/memory directory. settings.json is
copied once, without keys that would select another account or provider.
Never touches login, sessions, history, transcripts, caches or account state:
only the allowlisted names below are read or written.

Default is a dry run. --apply makes the changes with the Duo app closed;
an existing destination item is moved, never deleted, into a backup folder
only with --backup-existing.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

LINKED = ("CLAUDE.md", "skills", "output-styles", "tools", "plugins")
MANIFEST = ".shared-from-original.json"
# Keys that choose a different login, provider or credential source.
ACCOUNT_KEYS = {"apiKeyHelper", "awsAuthRefresh", "awsCredentialExport", "gcpAuthRefresh",
                "forceLoginMethod", "forceLoginOrgUUID", "otelHeadersHelper"}
ACCOUNT_ENV_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_USE_", "CLAUDE_CODE_OAUTH", "AWS_", "GOOGLE_",
                        "CLOUD_ML_", "VERTEX_", "CLAUDE_CONFIG_DIR")
MERGED_FROM_DESTINATION = ("extraKnownMarketplaces",)


class Refused(Exception):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refused("duplicate JSON key in settings.json: " + key)
        result[key] = value
    return result


def owned_private_dir(path, label):
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode):
        raise Refused(f"{label} must be a real directory (not a link): {path}")
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise Refused(f"{label} must be owned by you and not writable by others: {path}")


def safe_source(path):
    """A source item must be a real file/directory owned by the user."""
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise Refused(f"source is a link; refusing to chain links: {path}")
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        raise Refused(f"source is not a regular file or directory: {path}")
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise Refused(f"source must be owned by you and not writable by others: {path}")


def app_running(app):
    prefix = str(app) + "/Contents/MacOS/"
    listing = subprocess.run(["/bin/ps", "-axo", "comm="], capture_output=True, text=True, check=True).stdout
    return any(line.startswith(prefix) for line in listing.splitlines())


def plan_link(source, destination):
    if not os.path.lexists(destination):
        return "link", None
    info = os.lstat(destination)
    if stat.S_ISLNK(info.st_mode):
        if os.readlink(destination) == str(source):
            return "ok", None
        return "conflict", "link to another place"
    if stat.S_ISDIR(info.st_mode) and not any(os.scandir(destination)):
        return "replace-empty", None
    return "conflict", "existing Duo item"


def filtered_settings(source, destination):
    original = json.loads(source.read_text(), object_pairs_hook=unique_object)
    if not isinstance(original, dict):
        raise Refused("settings.json must be a JSON object")
    removed = sorted(k for k in original if k in ACCOUNT_KEYS)
    result = {k: v for k, v in original.items() if k not in ACCOUNT_KEYS}
    env = result.get("env")
    if env is not None:
        if not isinstance(env, dict):
            raise Refused("settings.json env must be an object")
        dropped = sorted(k for k in env if k.startswith(ACCOUNT_ENV_PREFIXES))
        removed += ["env." + k for k in dropped]
        result["env"] = {k: v for k, v in env.items() if k not in dropped}
    if destination.exists():
        current = json.loads(destination.read_text(), object_pairs_hook=unique_object)
        if not isinstance(current, dict):
            raise Refused("Duo settings.json must be a JSON object")
        for key in MERGED_FROM_DESTINATION:
            if isinstance(current.get(key), dict):
                merged = dict(current[key])
                merged.update(result.get(key) or {})
                result[key] = merged
    return result, removed


def main(argv=None):
    home = Path(os.path.expanduser("~"))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=home / ".claude")
    parser.add_argument("--destination", type=Path, default=home / ".claude-duo")
    parser.add_argument("--app", type=Path, default=home / "Applications/Claude Duo.app")
    parser.add_argument("--apply", action="store_true", help="make the changes (default: dry run)")
    parser.add_argument("--backup-existing", action="store_true",
                        help="move existing Duo items aside instead of refusing")
    args = parser.parse_args(argv)
    try:
        source, destination = args.source.absolute(), args.destination.absolute()
        owned_private_dir(source, "source")
        owned_private_dir(destination, "destination")
        real_source, real_destination = os.path.realpath(source), os.path.realpath(destination)
        if real_source == real_destination or real_destination.startswith(real_source + "/") or real_source.startswith(real_destination + "/"):
            raise Refused("source and destination must be separate folders")
        if args.apply and app_running(args.app):
            raise Refused("Claude Duo is running; quit it (Command-Q) and run again")

        actions = []  # (kind, source, destination, note)
        for name in LINKED:
            item = source / name
            if not os.path.lexists(item):
                actions.append(("skip", item, destination / name, "not in the original"))
                continue
            safe_source(item)
            kind, note = plan_link(item, destination / name)
            actions.append((kind, item, destination / name, note))
        projects = source / "projects"
        if os.path.lexists(projects):
            safe_source(projects)
            for entry in sorted(os.scandir(projects), key=lambda e: e.name):
                memory = Path(entry.path) / "memory"
                if not entry.is_dir(follow_symlinks=False) or not os.path.lexists(memory):
                    continue
                safe_source(memory)
                target = destination / "projects" / entry.name / "memory"
                kind, note = plan_link(memory, target)
                actions.append((kind, memory, target, note))
        duo_projects = destination / "projects"
        duo_only = []
        if duo_projects.is_dir() and not duo_projects.is_symlink():
            for entry in os.scandir(duo_projects):
                memory = Path(entry.path) / "memory"
                if memory.is_dir() and not memory.is_symlink() and not (projects / entry.name / "memory").exists():
                    duo_only.append(memory)

        settings_source, settings_destination = source / "settings.json", destination / "settings.json"
        settings, removed, settings_kind = None, [], "skip"
        if settings_source.exists():
            safe_source(settings_source)
            if settings_destination.is_symlink():
                raise Refused("Duo settings.json is a link; review it first")
            settings, removed = filtered_settings(settings_source, settings_destination)
            manifest = destination / MANIFEST
            copied_before = manifest.exists() and json.loads(manifest.read_text()).get("settings_copied")
            if copied_before:
                settings_kind = "ok"  # Copied once; later edits in the Duo are kept.
            elif settings_destination.exists() and json.loads(settings_destination.read_text()) == settings:
                settings_kind = "ok"
            else:
                settings_kind = "copy"

        conflicts = [a for a in actions if a[0] == "conflict"]
        for kind, src, dst, note in actions:
            print(f"{kind:14} {dst} -> {src}" + (f"  ({note})" if note else ""))
        print(f"{settings_kind:14} {settings_destination} (copy once from the original)")
        for key in removed:
            print(f"{'not copied':14} settings.json {key} (selects an account or provider)")
        for memory in duo_only:
            print(f"{'kept':14} {memory} (memory only in the Duo; not merged)")
        if not args.apply:
            if conflicts and not args.backup_existing:
                print("Existing Duo items above would be moved aside: add --backup-existing.")
            print("Dry run: nothing changed. Use --apply with the Duo closed.")
            return 0
        if conflicts and not args.backup_existing:
            raise Refused("existing Duo items above would be replaced; rerun with --backup-existing to move them aside")

        backup = destination / (".share-backup-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))

        def move_aside(path):
            relative = path.relative_to(destination)
            target = backup / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.rename(path, target)

        for kind, src, dst, _ in actions:
            if kind in ("skip", "ok"):
                continue
            dst.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if kind == "replace-empty":
                os.rmdir(dst)
            elif kind == "conflict":
                move_aside(dst)
            os.symlink(str(src), dst)
        if settings_kind == "copy":
            if settings_destination.exists():
                move_aside(settings_destination)
            temporary = destination / ".settings.json.share-new"
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                json.dump(settings, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.rename(temporary, settings_destination)
        record = {
            "source": str(source),
            "links": sorted(str(a[2].relative_to(destination)) for a in actions if a[0] != "skip"),
            "settings_copied": settings_kind in ("copy", "ok"),
            "settings_sha256": hashlib.sha256(settings_destination.read_bytes()).hexdigest() if settings_destination.exists() else None,
            "updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        temporary = destination / (MANIFEST + ".new")
        temporary.write_text(json.dumps(record, indent=2) + "\n")
        os.chmod(temporary, 0o600)
        os.rename(temporary, destination / MANIFEST)
        if backup.exists():
            print(f"Previous Duo items moved to {backup}")
        print("Applied. Login, sessions, history and transcripts were not touched.")
        return 0
    except Refused as error:
        print("refused: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

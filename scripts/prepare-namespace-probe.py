#!/usr/bin/env python3
"""Reproduce the helper-name experiment that failed namespace separation.

Experimental packaging outside the production toolset. No Keychain APIs, profile
imports, ASAR edits, process argv/environment inspection or LaunchServices calls.
The GUI test still requested Claude Safe Storage. Use the separate product-name
experiment for further work; this baseline requires an explicit reproduction flag.
"""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import pwd
import stat
import struct
import subprocess
import sys
import tempfile
import uuid

REPO = Path(__file__).resolve().parents[1]
SOURCE = Path('/Applications/Claude.app')
REQUIREMENT = '=anchor apple generic and certificate leaf[subject.OU] = "Q6L2SF6YDW" and identifier "com.anthropic.claudefordesktop"'
ROLES = ('', ' (GPU)', ' (Plugin)', ' (Renderer)')
SIGNATURE_FILES = ('CodeResources', 'CodeDirectory', 'CodeRequirements', 'CodeSignature')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unsigned_payload(blob):
    """Bind all pre-signature bytes, normalizing only signature size fields.

    Deliberately supports thin little-endian 64-bit Mach-O only. Reject changed
    load-command shape, code/data, signature offsets, unsigned or unknown images.
    This is a narrow signing comparison, not an executable safety assessment.
    """
    if len(blob) < 32 or struct.unpack_from('<I', blob)[0] != 0xFEEDFACF:
        raise ValueError('probe requires a thin little-endian 64-bit Mach-O')
    count, size = struct.unpack_from('<II', blob, 16)
    end = 32 + size
    if not 0 < count <= 1024 or end > len(blob):
        raise ValueError('invalid load-command bounds')
    body = bytearray(blob)
    offset, signature, linkedit = 32, None, 0
    for _ in range(count):
        if offset + 8 > end:
            raise ValueError('truncated load command')
        command, length = struct.unpack_from('<II', blob, offset)
        if length < 8 or length % 8 or offset + length > end:
            raise ValueError('invalid load-command size')
        if command == 0x1D:  # LC_CODE_SIGNATURE
            if signature is not None or length != 16:
                raise ValueError('ambiguous signature command')
            signature = struct.unpack_from('<II', blob, offset + 8)
            body[offset + 8:offset + 16] = bytes(8)
        if command == 0x19:  # LC_SEGMENT_64
            if length < 72:
                raise ValueError('truncated segment command')
            if blob[offset + 8:offset + 24].rstrip(b'\0') == b'__LINKEDIT':
                linkedit += 1
                body[offset + 32:offset + 40] = bytes(8)  # vmsize
                body[offset + 48:offset + 56] = bytes(8)  # filesize
        offset += length
    if offset != end or signature is None or linkedit != 1:
        raise ValueError('unsupported command/signature layout')
    start, length = signature
    if start < end or not length or start + length != len(blob):
        raise ValueError('signature must be the final bounded region')
    return digest(body[:start])


def helper_prefix(role, name='Claude'):
    return f'Contents/Frameworks/{name} Helper{role}.app'


def mapped_path(path, name):
    for role in ROLES:
        old, new = helper_prefix(role), helper_prefix(role, name)
        if path == old or path.startswith(old + '/'):
            result = new + path[len(old):]
            executable = new + f'/Contents/MacOS/Claude Helper{role}'
            return new + f'/Contents/MacOS/{name} Helper{role}' if result == executable else result
    return path


def expected_plist(original, name, identifier, role=None):
    result = dict(original)
    if role is None:
        result.update(CFBundleName=name, CFBundleDisplayName=name,
                      CFBundleIdentifier=identifier, CFBundleExecutable='launcher')
        result.pop('CFBundleURLTypes', None)
        result.pop('NSUserActivityTypes', None)
    else:
        suffix = {'': '', ' (GPU)': '.gpu', ' (Plugin)': '.plugin', ' (Renderer)': '.renderer'}[role]
        helper = name + ' Helper' + role
        result.update(CFBundleName=helper, CFBundleDisplayName=helper,
                      CFBundleIdentifier=identifier + '.helper' + suffix,
                      CFBundleExecutable=helper)
    return result


def inventory(root):
    result = {}
    for item in sorted(root.rglob('*')):
        info, rel = item.lstat(), item.relative_to(root).as_posix()
        if stat.S_ISLNK(info.st_mode):
            target = os.readlink(item)
            if os.path.isabs(target) or not item.resolve(strict=True).is_relative_to(root):
                raise ValueError('unsupported escaping bundle link')
            result[rel] = ('link', target)
        elif stat.S_ISDIR(info.st_mode):
            result[rel] = ('directory', info.st_mode & 0o700)
        elif stat.S_ISREG(info.st_mode):
            result[rel] = ('file', info.st_mode & 0o700, digest(item.read_bytes()))
        else:
            raise ValueError('unsupported special bundle entry')
    return result


def validate_candidate(source, app, name, identifier, launcher):
    before, after = inventory(source), inventory(app)
    roots = [''] + [helper_prefix(role, name) + '/' for role in ROLES]
    metadata = {'Contents/Info.plist': None}
    binaries = {'Contents/MacOS/Claude'}
    signatures = {prefix + 'Contents/_CodeSignature/' + leaf for prefix in roots for leaf in SIGNATURE_FILES}
    for role in ROLES:
        prefix = helper_prefix(role, name)
        metadata[prefix + '/Contents/Info.plist'] = role
        binaries.add(prefix + f'/Contents/MacOS/{name} Helper{role}')
    expected = {mapped_path(path, name): item for path, item in before.items()}
    added = set(after) - set(expected)
    if added - signatures != {'Contents/MacOS/launcher'} or set(expected) - set(after):
        raise ValueError('unexpected added/removed bundle entries')
    for old_path in before:
        new_path = mapped_path(old_path, name)
        if new_path in metadata:
            want = expected_plist(plistlib.loads((source / old_path).read_bytes()), name, identifier, metadata[new_path])
            if plistlib.loads((app / new_path).read_bytes()) != want:
                raise ValueError('unexpected plist changes')
        elif new_path in binaries:
            if unsigned_payload((source / old_path).read_bytes()) != unsigned_payload((app / new_path).read_bytes()):
                raise ValueError('executable bytes changed beyond signature fields')
        elif new_path not in signatures and before[old_path] != after[new_path]:
            raise ValueError('unexpected resource, link or mode change: ' + new_path)
    if (app / 'Contents/MacOS/launcher').read_bytes() != launcher:
        raise ValueError('launcher differs from reviewed render')
    return {'entries_compared': len(expected), 'executables_compared': len(binaries),
            'helper_roles': len(ROLES), 'asar_unchanged': before['Contents/Resources/app.asar'] == after['Contents/Resources/app.asar']}


def main():
    if sys.argv[1:] != ['--reproduce-helper-only-failure']:
        raise SystemExit('helper-only renaming failed in the GUI; explicit --reproduce-helper-only-failure required')
    if os.uname().sysname != 'Darwin' or os.uname().machine != 'arm64' or os.getuid() == 0:
        raise SystemExit('this disposable prototype currently requires macOS arm64 and a non-root user')
    account = pwd.getpwuid(os.getuid())
    home = Path(account.pw_dir).resolve()
    if Path(os.environ['HOME']).resolve() != home or not REPO.resolve().is_relative_to(home):
        raise SystemExit('use the real user home and a repository inside that home')
    os.umask(0o077)
    scratch = Path(tempfile.mkdtemp(prefix='duo-namespace-probe-', dir=REPO.parent)).resolve()
    name = 'Claude Duo Probe ' + uuid.uuid4().hex[:8]
    identifier = 'local.multi-claude.namespace-probe.' + uuid.uuid4().hex
    app = scratch / (name + '.app')
    receipt = {'schema': 1, 'status': 'preparing', 'app': str(app), 'name': name,
               'identifier': identifier, 'source': str(SOURCE), 'checks': [],
               'vendor_executable_launched': False, 'installed_apps_modified': False,
               'keychain_accessed_by_probe_preparation': False,
               'account_independence_established': False}

    def run(label, args, expected=0):
        result = subprocess.run(list(map(str, args)), capture_output=True, timeout=180)
        (scratch / (label + '.log')).write_bytes(result.stdout + result.stderr)
        receipt['checks'].append({'name': label, 'exit': result.returncode, 'expected': expected})
        if result.returncode != expected:
            raise RuntimeError(label + ' failed; no fallback; see ' + str(scratch))

    try:
        run('compile_native_guard', ['/usr/bin/clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', '-mmacosx-version-min=12.0', REPO / 'bin/claude-transaction.c', '-o', scratch / 'guard'])
        run('desktop_idle_before', [scratch / 'guard', 'desktop-idle'], 1)
        run('source_identity', ['/usr/bin/codesign', '--verify', '--strict', '--all-architectures', '-R', REQUIREMENT, SOURCE])
        run('source_nested', ['/usr/bin/codesign', '--verify', '--deep', '--strict', '--all-architectures', SOURCE])
        run('source_gatekeeper', ['/usr/sbin/spctl', '--assess', '--type', 'execute', SOURCE])
        info = plistlib.loads((SOURCE / 'Contents/Info.plist').read_bytes())
        framework = plistlib.loads((SOURCE / 'Contents/Frameworks/Electron Framework.framework/Resources/Info.plist').read_bytes())
        if info['CFBundleShortVersionString'] != '2.42304.0' or framework['CFBundleVersion'] != '44.7.2':
            raise ValueError('unreviewed vendor version; stop and review packaging again')
        if sorted(p.name for p in (SOURCE / 'Contents/Frameworks').glob('*Helper*.app')) != sorted('Claude Helper' + role + '.app' for role in ROLES):
            raise ValueError('unreviewed helper layout')
        original = inventory(SOURCE)
        run('copy_official_app', ['/bin/cp', '-Rc', SOURCE, app])
        run('copied_identity', ['/usr/bin/codesign', '--verify', '--deep', '--strict', '--all-architectures', '-R', REQUIREMENT, app])
        for role in ROLES:
            old = app / helper_prefix(role)
            old.rename(app / helper_prefix(role, name))
            helper = app / helper_prefix(role, name)
            (helper / f'Contents/MacOS/Claude Helper{role}').rename(helper / f'Contents/MacOS/{name} Helper{role}')
            path = helper / 'Contents/Info.plist'
            path.write_bytes(plistlib.dumps(expected_plist(plistlib.loads(path.read_bytes()), name, identifier, role)))
            run('sign_helper_binary_' + str(ROLES.index(role)), ['/usr/bin/codesign', '--force', '-s', '-', helper / f'Contents/MacOS/{name} Helper{role}'])
            run('sign_helper_bundle_' + str(ROLES.index(role)), ['/usr/bin/codesign', '--force', '-s', '-', helper])
        data = scratch / 'data'
        (data / 'desktop').mkdir(parents=True, mode=0o700)
        (data / 'code').mkdir(mode=0o700)
        render = 'PATH=/usr/bin:/bin:/usr/sbin:/sbin; export PATH; source "$1"; CI_USER="$2"; CI_MODE=original-copy; dirs=("$3"); code_dirs=("$4"); ci_render_launcher 0'
        launcher = subprocess.check_output(['/bin/bash', '-p', '-c', render, 'namespace-probe', str(REPO / 'bin/claude-instances-common.sh'), account.pw_name, str(data / 'desktop'), str(data / 'code')])
        launcher_path = app / 'Contents/MacOS/launcher'
        launcher_path.write_bytes(launcher)
        launcher_path.chmod(0o755)
        path = app / 'Contents/Info.plist'
        path.write_bytes(plistlib.dumps(expected_plist(info, name, identifier)))
        run('launcher_syntax', ['/bin/bash', '-n', launcher_path])
        run('sign_main_binary', ['/usr/bin/codesign', '--force', '-s', '-', app / 'Contents/MacOS/Claude'])
        run('sign_outer_bundle', ['/usr/bin/codesign', '--force', '-s', '-', app])
        run('candidate_nested', ['/usr/bin/codesign', '--verify', '--deep', '--strict', '--all-architectures', app])
        receipt['content_comparison'] = validate_candidate(SOURCE, app, name, identifier, launcher)
        run('desktop_idle_after', [scratch / 'guard', 'desktop-idle'], 1)
        run('source_nested_after', ['/usr/bin/codesign', '--verify', '--deep', '--strict', '--all-architectures', '-R', REQUIREMENT, SOURCE])
        if inventory(SOURCE) != original:
            raise ValueError('source changed during preparation')
        receipt.update(status='prepared_static_checks_passed_gui_not_executed', source_version=info['CFBundleShortVersionString'],
                       source_content_unchanged=True, expected_electron_service_name=name + ' Safe Storage',
                       service_name_observed_at_runtime=False, additional_ad_hoc_helper_bundles=4)
    except Exception as error:
        receipt.update(status='failed_not_approved', error=str(error))
        raise
    finally:
        (scratch / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps({'status': receipt['status'], 'receipt': str(scratch / 'receipt.json'), 'app': str(app)}), flush=True)


if __name__ == '__main__':
    main()

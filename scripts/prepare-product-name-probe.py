#!/usr/bin/env python3
"""Prepare a separate productName experiment; do not launch or install it."""
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import pwd
import subprocess
import sys
import tempfile
import uuid

from asar_product_name import patch_product_name, unpack, verify_change, sha

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('namespace_probe', REPO / 'scripts/prepare-namespace-probe.py')
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)


def validate(source, app, identifier, name, launcher):
    before, after = base.inventory(source), base.inventory(app)
    signatures = {'Contents/_CodeSignature/' + x for x in base.SIGNATURE_FILES}
    if set(before) - set(after) or (set(after) - set(before)) - signatures != {'Contents/MacOS/launcher'}:
        raise ValueError('unexpected added/removed bundle entries')
    old_asar = (source / 'Contents/Resources/app.asar').read_bytes()
    new_asar = (app / 'Contents/Resources/app.asar').read_bytes()
    comparison = verify_change(old_asar, new_asar, name)
    original = plistlib.loads((source / 'Contents/Info.plist').read_bytes())
    expected = dict(original)
    expected.update(CFBundleIdentifier=identifier, CFBundleDisplayName=name, CFBundleExecutable='launcher')
    expected.pop('CFBundleURLTypes', None)
    expected.pop('NSUserActivityTypes', None)
    integrity = dict(expected['ElectronAsarIntegrity'])
    integrity['Resources/app.asar'] = {'algorithm': 'SHA256', 'hash': comparison['header_sha256']}
    expected['ElectronAsarIntegrity'] = integrity
    if plistlib.loads((app / 'Contents/Info.plist').read_bytes()) != expected:
        raise ValueError('unexpected outer metadata changes')
    for path, entry in before.items():
        if path in signatures or path in ('Contents/Info.plist', 'Contents/Resources/app.asar'):
            continue
        if path == 'Contents/MacOS/Claude':
            if base.unsigned_payload((source / path).read_bytes()) != base.unsigned_payload((app / path).read_bytes()):
                raise ValueError('main executable payload changed')
        elif entry != after[path]:
            raise ValueError('unexpected unchanged-file drift: ' + path)
    if (app / 'Contents/MacOS/launcher').read_bytes() != launcher:
        raise ValueError('unexpected launcher')
    comparison.update(entries_compared=len(before), helper_bundles_byte_unchanged=4,
                      helper_signatures_preserved=True, main_unsigned_payload_unchanged=True)
    return comparison


def main():
    if len(sys.argv) != 1:
        raise SystemExit('this fixed experiment does not accept arguments')
    if os.uname().sysname != 'Darwin' or os.uname().machine != 'arm64' or os.getuid() == 0:
        raise SystemExit('this prototype requires a non-root macOS arm64 session')
    account = pwd.getpwuid(os.getuid())
    home = Path(account.pw_dir).resolve()
    if Path(os.environ['HOME']).resolve() != home:
        raise SystemExit('real HOME required')
    os.umask(0o077)
    scratch = Path(tempfile.mkdtemp(prefix='duo-product-name-probe-')).resolve()
    name = 'Claude Duo Probe ' + uuid.uuid4().hex[:8]
    identifier = 'local.multi-claude.product-probe.' + uuid.uuid4().hex
    app = scratch / (name + '.app')
    receipt = {'status': 'preparing', 'app': str(app), 'name': name, 'identifier': identifier,
               'method': 'package_product_name_preserve_helper_bundles', 'checks': [],
               'vendor_executable_launched': False, 'keychain_accessed_by_preparation': False,
               'installed_apps_modified': False, 'account_independence_established': False}

    def run(label, args, expected=0):
        result = subprocess.run(list(map(str, args)), capture_output=True, timeout=180)
        (scratch / (label + '.log')).write_bytes(result.stdout + result.stderr)
        receipt['checks'].append({'name': label, 'exit': result.returncode, 'expected': expected})
        if result.returncode != expected:
            raise RuntimeError(label + ' failed; no fallback; see ' + str(scratch))

    try:
        run('compile_native_guard', ['/usr/bin/clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', '-mmacosx-version-min=12.0', REPO / 'bin/claude-transaction.c', '-o', scratch / 'guard'])
        run('desktop_idle_before', [scratch / 'guard', 'desktop-idle'], 1)
        for label, args in [('identity', ['--strict', '--all-architectures', '-R', base.REQUIREMENT]), ('nested', ['--deep', '--strict', '--all-architectures'])]:
            run('source_' + label, ['/usr/bin/codesign', '--verify', *args, base.SOURCE])
        run('source_gatekeeper', ['/usr/sbin/spctl', '--assess', '--type', 'execute', base.SOURCE])
        info = plistlib.loads((base.SOURCE / 'Contents/Info.plist').read_bytes())
        framework = plistlib.loads((base.SOURCE / 'Contents/Frameworks/Electron Framework.framework/Resources/Info.plist').read_bytes())
        if info['CFBundleShortVersionString'] != '2.42304.0' or framework['CFBundleVersion'] != '44.7.2':
            raise ValueError('unreviewed vendor version')
        source_asar = (base.SOURCE / 'Contents/Resources/app.asar').read_bytes()
        _, _, raw_header = unpack(source_asar)
        if info['ElectronAsarIntegrity']['Resources/app.asar'] != {'algorithm': 'SHA256', 'hash': sha(raw_header)}:
            raise ValueError('source ASAR header does not match the sealed plist')
        original = base.inventory(base.SOURCE)
        patched, _ = patch_product_name(source_asar, name)
        run('copy_official', ['/bin/cp', '-Rc', base.SOURCE, app])
        run('copied_identity', ['/usr/bin/codesign', '--verify', '--deep', '--strict', '--all-architectures', '-R', base.REQUIREMENT, app])
        (app / 'Contents/Resources/app.asar').write_bytes(patched)
        # Outside Documents: avoid requesting that permission just to read the
        # experimental app/data. These are new empty directories, not real profiles.
        caches = home / 'Library/Caches'
        check = 'PATH=/usr/bin:/bin:/usr/sbin:/sbin; export PATH; source "$1"; ci_owned_directory_chain "$2" "$HOME"'
        run('cache_parent_check', ['/bin/bash', '-p', '-c', check, 'product-probe', REPO / 'bin/claude-instances-common.sh', caches])
        profiles = Path(tempfile.mkdtemp(prefix='claude-duo-product-probe-', dir=caches)).resolve()
        receipt['new_empty_profile_root'] = str(profiles)
        for kind in ('desktop', 'code'):
            (profiles / kind).mkdir(mode=0o700)
        render = 'PATH=/usr/bin:/bin:/usr/sbin:/sbin; export PATH; source "$1"; CI_USER="$2"; CI_MODE=original-copy; dirs=("$3"); code_dirs=("$4"); ci_render_launcher 0'
        launcher = subprocess.check_output(['/bin/bash', '-p', '-c', render, 'product-probe', str(REPO / 'bin/claude-instances-common.sh'), account.pw_name, str(profiles / 'desktop'), str(profiles / 'code')])
        launcher_path = app / 'Contents/MacOS/launcher'
        launcher_path.write_bytes(launcher)
        launcher_path.chmod(0o755)
        expected = dict(info)
        expected.update(CFBundleIdentifier=identifier, CFBundleDisplayName=name, CFBundleExecutable='launcher')
        expected.pop('CFBundleURLTypes', None)
        expected.pop('NSUserActivityTypes', None)
        _, _, new_header = unpack(patched)
        sealed = dict(expected['ElectronAsarIntegrity'])
        sealed['Resources/app.asar'] = {'algorithm': 'SHA256', 'hash': sha(new_header)}
        expected['ElectronAsarIntegrity'] = sealed
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(expected))
        run('launcher_syntax', ['/bin/bash', '-n', launcher_path])
        run('sign_main', ['/usr/bin/codesign', '--force', '-s', '-', app / 'Contents/MacOS/Claude'])
        run('sign_outer', ['/usr/bin/codesign', '--force', '-s', '-', app])
        run('candidate_nested', ['/usr/bin/codesign', '--verify', '--deep', '--strict', '--all-architectures', app])
        receipt['content_comparison'] = validate(base.SOURCE, app, identifier, name, launcher)
        run('desktop_idle_after', [scratch / 'guard', 'desktop-idle'], 1)
        run('source_nested_after', ['/usr/bin/codesign', '--verify', '--deep', '--strict', '--all-architectures', '-R', base.REQUIREMENT, base.SOURCE])
        if base.inventory(base.SOURCE) != original:
            raise ValueError('source changed during preparation')
        receipt.update(status='prepared_static_checks_passed_gui_not_executed', source_content_unchanged=True,
                       expected_electron_service_name=name + ' Safe Storage', runtime_service_name_observed=False)
    except Exception as error:
        receipt.update(status='failed_not_approved', error=str(error))
        raise
    finally:
        (scratch / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps({'status': receipt['status'], 'receipt': str(scratch / 'receipt.json'), 'app': str(app)}), flush=True)


if __name__ == '__main__':
    main()

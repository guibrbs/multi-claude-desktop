"""Offline validation of the experimental namespace packaging boundary."""
import importlib.util
from pathlib import Path
import plistlib
import shutil
import struct
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / 'scripts/prepare-namespace-probe.py'
SPEC = importlib.util.spec_from_file_location('namespace_probe', PATH)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def macho(signature=b'old signature'):
    header = struct.pack('<8I', 0xFEEDFACF, 0x100000C, 0, 2, 2, 88, 0, 0)
    segment = struct.pack('<II16sQQQQiiII', 0x19, 72, b'__LINKEDIT', 0, 4096,
                          128, len(signature), 1, 1, 0, 0)
    command = struct.pack('<4I', 0x1D, 16, 128, len(signature))
    return header + segment + command + b'PAYLOAD!' + signature


class MachSigningComparisonTests(unittest.TestCase):
    def test_signature_resize_preserves_bound_payload(self):
        self.assertEqual(probe.unsigned_payload(macho()), probe.unsigned_payload(macho(b'new and longer signature')))

    def test_code_change_is_not_hidden_by_resigning(self):
        self.assertNotEqual(probe.unsigned_payload(macho()), probe.unsigned_payload(macho().replace(b'PAYLOAD!', b'CHANGED!')))

    def test_load_command_change_is_not_hidden_by_resigning(self):
        changed = bytearray(macho())
        struct.pack_into('<Q', changed, 32 + 40, 64)  # __LINKEDIT fileoff is not mutable.
        self.assertNotEqual(probe.unsigned_payload(macho()), probe.unsigned_payload(changed))

    def test_unsigned_truncated_ambiguous_and_nonfinal_signatures_are_rejected(self):
        duplicate = bytearray(macho())
        struct.pack_into('<II', duplicate, 32, 0x1D, 72)
        for blob in [b'not Mach-O', macho()[:100], macho() + b'trailing bytes', duplicate]:
            with self.subTest(size=len(blob)), self.assertRaises(ValueError):
                probe.unsigned_payload(blob)

    def test_signature_offset_change_is_not_hidden_by_resigning(self):
        changed = bytearray(macho())
        struct.pack_into('<II', changed, 112, 129, len(b'old signature') - 1)
        self.assertNotEqual(probe.unsigned_payload(macho()), probe.unsigned_payload(changed))


class NamespaceBundleComparisonTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='namespace-probe-tests-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source, self.app = self.root / 'source.app', self.root / 'probe.app'
        self.name, self.identifier, self.launcher = 'Claude Duo Probe fixture', 'local.fixture.probe', b'#!/bin/bash -p\nexit 0\n'
        self.info = {'CFBundleName': 'Claude', 'CFBundleDisplayName': 'Claude',
                     'CFBundleIdentifier': 'com.anthropic.claudefordesktop', 'CFBundleExecutable': 'Claude',
                     'CFBundleURLTypes': [{'CFBundleURLSchemes': ['claude']}], 'NSUserActivityTypes': ['fixture']}
        self.write('Contents/Info.plist', plistlib.dumps(self.info))
        self.write('Contents/MacOS/Claude', macho())
        self.write('Contents/Resources/app.asar', b'fixture ASAR, never executed')
        self.write('Contents/_CodeSignature/CodeResources', b'old signature resource')
        for role in probe.ROLES:
            prefix = probe.helper_prefix(role)
            self.write(prefix + '/Contents/Info.plist', plistlib.dumps(self.info))
            self.write(prefix + f'/Contents/MacOS/Claude Helper{role}', macho())
            self.write(prefix + '/Contents/_CodeSignature/CodeResources', b'old helper signature')
        shutil.copytree(self.source, self.app)
        for role in probe.ROLES:
            (self.app / probe.helper_prefix(role)).rename(self.app / probe.helper_prefix(role, self.name))
            helper = self.app / probe.helper_prefix(role, self.name)
            binary = helper / f'Contents/MacOS/{self.name} Helper{role}'
            (helper / f'Contents/MacOS/Claude Helper{role}').rename(binary)
            binary.write_bytes(macho(b'new fixture signature'))
            (helper / 'Contents/Info.plist').write_bytes(plistlib.dumps(probe.expected_plist(self.info, self.name, self.identifier, role)))
        (self.app / 'Contents/Info.plist').write_bytes(plistlib.dumps(probe.expected_plist(self.info, self.name, self.identifier)))
        (self.app / 'Contents/MacOS/launcher').write_bytes(self.launcher)

    def write(self, relative, data):
        path = self.source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def check(self):
        return probe.validate_candidate(self.source, self.app, self.name, self.identifier, self.launcher)

    def test_all_four_helpers_map_to_native_expected_names_and_preserve_payloads(self):
        result = self.check()
        self.assertEqual(result['executables_compared'], 5)
        self.assertTrue(result['asar_unchanged'])
        identifiers = set()
        for role in probe.ROLES:
            helper = self.app / probe.helper_prefix(role, self.name)
            info = plistlib.loads((helper / 'Contents/Info.plist').read_bytes())
            self.assertTrue((helper / 'Contents/MacOS' / info['CFBundleExecutable']).is_file())
            identifiers.add(info['CFBundleIdentifier'])
        self.assertEqual(len(identifiers), 4)

    def test_unplanned_resource_is_refused(self):
        (self.app / 'Contents/Resources/injected.js').write_text('fixture drift')
        with self.assertRaisesRegex(ValueError, 'added/removed'):
            self.check()

    def test_helper_payload_tampering_is_refused(self):
        helper = self.app / probe.helper_prefix(' (Renderer)', self.name) / f'Contents/MacOS/{self.name} Helper (Renderer)'
        helper.write_bytes(helper.read_bytes().replace(b'PAYLOAD!', b'CHANGED!'))
        with self.assertRaisesRegex(ValueError, 'executable bytes'):
            self.check()

    def test_helper_plist_tampering_is_refused(self):
        path = self.app / probe.helper_prefix('', self.name) / 'Contents/Info.plist'
        info = plistlib.loads(path.read_bytes())
        info['CFBundleIdentifier'] = 'unexpected.identity'
        path.write_bytes(plistlib.dumps(info))
        with self.assertRaisesRegex(ValueError, 'plist'):
            self.check()

    def test_asar_changes_are_refused(self):
        (self.app / 'Contents/Resources/app.asar').write_bytes(b'unexpected vendor code change')
        with self.assertRaisesRegex(ValueError, 'resource'):
            self.check()

    def test_missing_helper_file_is_refused(self):
        (self.app / probe.helper_prefix(' (GPU)', self.name) / 'Contents/Info.plist').unlink()
        with self.assertRaisesRegex(ValueError, 'added/removed'):
            self.check()

    def test_escaping_link_is_refused(self):
        (self.app / 'Contents/Resources/escape').symlink_to(self.root)
        with self.assertRaisesRegex(ValueError, 'escaping'):
            self.check()

"""Synthetic ASAR boundaries for the product-name experiment; no vendor run."""
import importlib.util
import json
from pathlib import Path
import struct
import unittest

SPEC = importlib.util.spec_from_file_location('asar_product_name', Path(__file__).resolve().parents[1] / 'scripts/asar_product_name.py')
asar = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(asar)
NAME = 'Claude Duo Probe 1234abcd'


def archive():
    package = b'{"productName":"Claude","main":"index.js","other":{"unchanged":true}}'
    before, after = b'BEFORE', b'console.log("synthetic code");'
    entry = {'offset': str(len(before)), 'size': len(package),
             'integrity': asar.integrity(package, {'algorithm': 'SHA256', 'blockSize': 16})}
    header = {'files': {'before.bin': {'offset': '0', 'size': len(before)}, 'package.json': entry,
                        'index.js': {'offset': str(len(before) + len(package)), 'size': len(after)},
                        'binding.node': {'unpacked': True, 'size': 100, 'integrity': {'hash': 'preserved'}},
                        'alias': {'link': 'index.js'}}}
    return asar.pack(header, before + package + after)


class AsarProductNameTests(unittest.TestCase):
    def test_only_product_metadata_changes_and_following_offsets_are_adjusted(self):
        original = archive()
        changed, report = asar.patch_product_name(original, NAME)
        h, payload, _ = asar.unpack(changed)
        entry = h['files']['package.json']
        package = json.loads(payload[int(entry['offset']):int(entry['offset']) + entry['size']])
        self.assertEqual(package, {'productName': NAME, 'main': 'index.js', 'other': {'unchanged': True}})
        self.assertTrue(report['javascript_payloads_unchanged'])
        self.assertEqual(h['files']['binding.node']['integrity']['hash'], 'preserved')
        self.assertEqual(report['members_checked'], 5)

    def test_existing_source_package_integrity_mismatch_is_refused(self):
        h, payload, _ = asar.unpack(archive())
        h['files']['package.json']['integrity']['hash'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'source package integrity'):
            asar.patch_product_name(asar.pack(h, payload), NAME)

    def test_changed_javascript_is_refused_even_with_a_valid_archive(self):
        original = archive()
        changed, _ = asar.patch_product_name(original, NAME)
        changed = changed.replace(b'synthetic code', b'INJECTED CODE!')
        with self.assertRaisesRegex(ValueError, 'outside package'):
            asar.verify_change(original, changed, NAME)

    def test_other_package_semantics_cannot_change(self):
        original = archive()
        changed, _ = asar.patch_product_name(original, NAME)
        changed = changed.replace(b'index.js', b'evilX.js')
        with self.assertRaises(ValueError):
            asar.verify_change(original, changed, NAME)

    def test_unrelated_header_metadata_change_is_refused(self):
        original = archive()
        changed, _ = asar.patch_product_name(original, NAME)
        h, payload, _ = asar.unpack(changed)
        h['files']['index.js']['executable'] = True
        with self.assertRaisesRegex(ValueError, 'header changes'):
            asar.verify_change(original, asar.pack(h, payload), NAME)

    def test_overlapping_member_is_refused(self):
        h, payload, _ = asar.unpack(archive())
        h['files']['index.js']['offset'] = '1'
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            asar.patch_product_name(asar.pack(h, payload), NAME)

    def test_escaped_payload_is_refused(self):
        h, payload, _ = asar.unpack(archive())
        h['files']['index.js']['size'] = len(payload) + 1
        with self.assertRaisesRegex(ValueError, 'escapes'):
            asar.patch_product_name(asar.pack(h, payload), NAME)

    def test_deduplicated_non_package_members_keep_their_shared_bytes(self):
        h, payload, _ = asar.unpack(archive())
        h['files']['second-index.js'] = dict(h['files']['index.js'])
        source = asar.pack(h, payload)
        changed, report = asar.patch_product_name(source, NAME)
        actual, _, _ = asar.unpack(changed)
        self.assertEqual(actual['files']['index.js'], actual['files']['second-index.js'])
        self.assertEqual(report['members_checked'], 6)

    def test_shared_package_region_is_refused(self):
        h, payload, _ = asar.unpack(archive())
        h['files']['other.json'] = dict(h['files']['package.json'])
        with self.assertRaisesRegex(ValueError, 'cannot share'):
            asar.patch_product_name(asar.pack(h, payload), NAME)

    def test_partial_overlap_stays_refused_next_to_duplicate_extents(self):
        h, payload, _ = asar.unpack(archive())
        h['files']['duplicate-before'] = dict(h['files']['before.bin'])
        h['files']['overlap'] = {'offset': '1', 'size': 2}
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            asar.patch_product_name(asar.pack(h, payload), NAME)

    def test_duplicate_json_keys_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            json.loads('{"productName":"Claude","productName":"Other"}', object_pairs_hook=asar.unique_object)

    def test_malformed_pickle_and_padding_are_refused(self):
        invalid = bytearray(archive())
        struct.pack_into('<I', invalid, 0, 5)
        for value in (b'bad', invalid, archive()[:20]):
            with self.subTest(length=len(value)), self.assertRaises(ValueError):
                asar.unpack(value)

    def test_unreviewed_or_unsafe_names_are_refused(self):
        for name in ('Claude', NAME + '/escape', NAME + '\n', 'Arbitrary Product'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                asar.patch_product_name(archive(), name)

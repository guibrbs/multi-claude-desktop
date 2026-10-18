"""App content/provenance guards using synthetic bundles; no vendor execution."""
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import unittest
import uuid

import test_hardening as hardening


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = hardening.HardeningTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def verify(self):
        return self.fixture.run_script("--verify")

    def record(self):
        identifier = (self.fixture.app / "Contents/Resources/mcd-build-id").read_text().strip()
        return self.fixture.home / ".local/share/claude-instances/integrity" / identifier / "record.txt"

    def test_added_modified_or_removed_resources_fail_even_when_local_signature_passes(self):
        resource = self.fixture.source / "Contents/Resources/data.js"
        resource.write_text("synthetic vendor bytes")
        self.fixture.build()
        copy = self.fixture.app / "Contents/Resources/data.js"
        for change in ("modified", "removed", "added"):
            with self.subTest(change=change):
                extra = self.fixture.app / "Contents/Resources/extra.js"
                if change == "modified":
                    copy.write_text("different code")
                elif change == "removed":
                    copy.unlink()
                else:
                    extra.write_text("unexpected resource")
                rejected = self.verify()
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn("drift", rejected.stderr)
                copy.write_text("synthetic vendor bytes")
                extra.unlink(missing_ok=True)
                self.assertEqual(self.verify().returncode, 0)

    def test_executable_bytes_and_mode_changes_are_detected(self):
        self.fixture.build()
        binary = self.fixture.app / "Contents/MacOS/Claude"
        original = binary.read_bytes()
        binary.write_bytes(original + b"\n# synthetic drift\n")
        self.assertNotEqual(self.verify().returncode, 0)
        binary.write_bytes(original)
        self.assertEqual(self.verify().returncode, 0)
        binary.chmod(0o700 if binary.stat().st_mode & 0o777 != 0o700 else 0o755)
        self.assertNotEqual(self.verify().returncode, 0)

    def test_framework_relative_links_work_but_retargeting_is_detected(self):
        framework = self.fixture.source / "Contents/Frameworks/Fixture.framework"
        (framework / "Versions/A").mkdir(parents=True)
        (framework / "Versions/A/data").write_text("synthetic framework")
        (framework / "Versions/Current").symlink_to("A", target_is_directory=True)
        (framework / "data").symlink_to("Versions/Current/data")
        self.fixture.build()
        self.assertEqual(self.verify().returncode, 0)
        link = self.fixture.app / "Contents/Frameworks/Fixture.framework/data"
        link.unlink()
        link.symlink_to("Versions/A/data")  # Same bytes, different link structure.
        self.assertNotEqual(self.verify().returncode, 0)

    def test_escaping_or_dangling_source_links_are_refused_before_publication(self):
        outside = self.fixture.root / "outside"
        outside.write_text("unrelated fixture")
        link = self.fixture.source / "Contents/Resources/escape"
        link.symlink_to(outside)
        result = self.fixture.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.fixture.app.exists())
        self.assertEqual(outside.read_text(), "unrelated fixture")

    def test_unplanned_resource_change_during_build_is_refused(self):
        signer = self.fixture.bin / "codesign"
        signer.write_text(signer.read_text().replace('exit 0\n', '''last="${!#}"
if [ "$1" = --force ] && [ -d "$last/Contents/Resources" ]; then
 printf 'unplanned fixture code' > "$last/Contents/Resources/unplanned.js"
fi
exit 0
'''))
        result = self.fixture.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("beyond planned files", result.stderr)
        self.assertFalse(self.fixture.app.exists())

    def test_nested_vendor_code_failure_prevents_publication(self):
        self.fixture.env["MOCK_NESTED_BAD"] = "1"
        result = self.fixture.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nested code/resource validation failed", result.stderr)
        self.assertFalse(self.fixture.app.exists())

    def test_unplanned_plist_semantics_during_build_are_refused(self):
        signer = self.fixture.bin / "codesign"
        signer.write_text(signer.read_text().replace('exit 0\n', '''last="${!#}"
if [ "$1" = --force ] && [ -d "$last/Contents" ]; then
 /usr/libexec/PlistBuddy -c 'Add :LSEnvironment dict' "$last/Contents/Info.plist"
fi
exit 0
'''))
        result = self.fixture.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Info.plist differs", result.stderr)
        self.assertFalse(self.fixture.app.exists())

    def test_script_main_detached_signature_files_are_planned_but_later_drift_is_refused(self):
        signer = self.fixture.bin / "codesign"
        signer.write_text(signer.read_text().replace('exit 0\n', '''last="${!#}"
if [ "$1" = --force ] && [ -d "$last/Contents/_CodeSignature" ]; then
 for item in CodeDirectory CodeRequirements CodeSignature; do
  printf 'synthetic detached signature' > "$last/Contents/_CodeSignature/$item"
 done
fi
exit 0
'''))
        self.fixture.build()
        self.assertEqual(self.verify().returncode, 0)
        signature = self.fixture.app / "Contents/_CodeSignature/CodeSignature"
        signature.write_text("different detached signature")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_record_is_private_bound_to_config_and_survives_source_unavailability(self):
        self.fixture.build()
        record = self.record()
        self.assertEqual(record.stat().st_mode & 0o777, 0o600)
        self.assertEqual(record.parent.stat().st_mode & 0o777, 0o700)
        self.fixture.write_config([("One", "com.audit.one", str(self.fixture.profile('profile one')), "143",
                                    "CLAUDE_CONFIG_DIR=" + str(self.fixture.code('code one')))])
        self.assertNotEqual(self.verify().returncode, 0)
        self.fixture.write_config()
        shutil.rmtree(self.fixture.source)
        self.assertEqual(self.verify().returncode, 0)

    def test_missing_malformed_or_linked_record_and_invalid_markers_are_refused(self):
        self.fixture.build()
        record = self.record()
        original = record.read_bytes()
        for data in (original[:-1], original + b"\0", original.replace(b"MCD_INTEGRITY 1", b"MCD_INTEGRITY 2")):
            record.write_bytes(data)
            self.assertNotEqual(self.verify().returncode, 0)
        record.write_bytes(original)
        saved = record.with_name("saved")
        record.rename(saved)
        record.symlink_to(saved)
        self.assertNotEqual(self.verify().returncode, 0)
        record.unlink()
        saved.rename(record)
        marker = self.fixture.app / "Contents/Resources/mcd-build-id"
        marker.write_text("../../outside\n")
        self.assertNotEqual(self.verify().returncode, 0)

    def test_security_xattr_drift_is_detected_and_observational_xattrs_are_ignored(self):
        self.fixture.build()
        file = self.fixture.app / "Contents/MacOS/Claude"
        subprocess.run(["/usr/bin/xattr", "-w", "com.apple.lastuseddate#PS", "synthetic", str(file)], check=True)
        self.assertEqual(self.verify().returncode, 0)
        subprocess.run(["/usr/bin/xattr", "-w", "com.apple.cs.fixture", "synthetic", str(file)], check=True)
        self.assertNotEqual(self.verify().returncode, 0)

"""Bounded re-check when app metadata moves during observation (exit 75 only)."""
import ctypes
import subprocess
import threading
import unittest

import test_hardening as hardening

FLAKY = '''#!/bin/bash
# Fixture wrapper: fail the first N calls of one helper mode, then run it.
counter="$MOCK_COUNTER_DIR/$2"
count=$(( $(cat "$counter" 2>/dev/null || echo 0) + 1 ))
echo "$count" > "$counter"
limit_var="MOCK_FAIL_$2"; limit="${!limit_var:-0}"
if [ "$count" -le "$limit" ]; then
 echo "integrity: app changed during tree observation" >&2
 exit "${MOCK_FAIL_CODE:-75}"
fi
exec "$@"
'''


class SettledVerificationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = hardening.HardeningTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.set_mode()
        common = self.fixture.bin / "claude-instances-common.sh"
        code = common.read_text()
        call = '"$CI_INTEGRITY_HELPER" "$@" && return 0'
        self.assertEqual(code.count(call), 1)
        common.write_text(code.replace(call, '"' + str(self.fixture.bin / "integrity-flaky") + '" ' + call))
        wrapper = self.fixture.bin / "integrity-flaky"
        wrapper.write_text(FLAKY)
        wrapper.chmod(0o755)
        self.counters = self.fixture.root / "counters"
        self.counters.mkdir()
        self.fixture.env["MOCK_COUNTER_DIR"] = str(self.counters)

    def calls(self, mode):
        path = self.counters / mode
        return int(path.read_text()) if path.exists() else 0

    def reset(self):
        for path in self.counters.iterdir():
            path.unlink()

    def test_transient_instability_after_publication_is_rechecked_and_passes(self):
        self.fixture.env["MOCK_FAIL_verify"] = "2"  # Staged check retries once, published check is clean.
        result = self.fixture.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("repeating the full check (2/3)", result.stderr)
        self.assertEqual(self.calls("verify"), 4)
        self.assertTrue(self.fixture.app.exists())

    def test_transient_instability_while_recording_is_rechecked(self):
        self.fixture.env["MOCK_FAIL_record"] = "1"
        result = self.fixture.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls("record"), 2)

    def test_persistent_instability_fails_after_three_full_checks(self):
        self.fixture.build()
        self.reset()
        self.fixture.env["MOCK_FAIL_verify"] = "99"
        result = self.fixture.run_script("--verify")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls("verify"), 3)
        self.assertIn("repeating the full check (3/3)", result.stderr)

    def test_content_failures_are_never_retried(self):
        self.fixture.build()
        self.reset()
        self.fixture.env.update(MOCK_FAIL_verify="99", MOCK_FAIL_CODE="1")
        result = self.fixture.run_script("--verify")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls("verify"), 1)
        self.assertNotIn("repeating", result.stderr)
        # Real drift through the real helper: one attempt, no retry message.
        self.fixture.env.pop("MOCK_FAIL_verify")
        self.fixture.env.pop("MOCK_FAIL_CODE")
        binary = self.fixture.app / "Contents/MacOS/Claude"
        binary.write_bytes(binary.read_bytes() + b"\n# drift\n")
        drift = self.fixture.run_script("--verify")
        self.assertNotEqual(drift.returncode, 0)
        self.assertIn("drift", drift.stderr)
        self.assertNotIn("repeating", drift.stderr)

    def test_real_helper_reports_concurrent_metadata_writes_as_exit_75(self):
        # Writes an unhashed attribute on the app root while the real helper
        # walks it; such a race must be classified as retryable, not drift.
        self.fixture.build()
        helper = self.fixture.root / "integrity-direct"
        subprocess.run(["/usr/bin/clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2", "-mmacosx-version-min=12.0",
                        "-framework", "CoreFoundation", str(hardening.REPO / "bin/claude-integrity.c"), "-o", str(helper)], check=True)
        for index in range(400):  # Larger tree so a walk spans several writes.
            (self.fixture.app / "Contents/Resources" / ("pad-%03d" % index)).write_bytes(b"x")
        identifier = (self.fixture.app / "Contents/Resources/mcd-build-id").read_text().strip()
        records = self.fixture.home / ".local/share/claude-instances/integrity"
        binding = (records / identifier / "record.txt").read_text().split("config ")[1].split()[0]
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        target = str(self.fixture.app).encode()
        stop = threading.Event()

        def writer():
            value = 0
            while not stop.is_set():
                value += 1
                data = str(value).encode()
                libc.setxattr(target, b"com.example.race", data, len(data), 0, 0)

        thread = threading.Thread(target=writer)
        thread.start()
        try:
            codes = []
            for _ in range(30):
                result = subprocess.run([str(helper), "verify", str(records), str(self.fixture.app), binding],
                                        capture_output=True, text=True, timeout=20)
                codes.append(result.returncode)
                self.assertIn(result.returncode, (0, 75), result.stderr)
                if result.returncode == 75:
                    self.assertIn("changed", result.stderr)
                    break
        finally:
            stop.set()
            thread.join()
        self.assertIn(75, codes)


if __name__ == "__main__":
    unittest.main()

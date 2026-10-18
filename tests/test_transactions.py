"""Real macOS rename/flock/fsync operations on disposable directories only.

The test build alone enables stop/failure injection. No Claude executable,
account, profile, Keychain credential, network or installed application is used.
"""
import os
from pathlib import Path
import select
import signal
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]


class TransactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compilation = tempfile.TemporaryDirectory(prefix="claude-native-tests-")
        cls.addClassCleanup(cls.compilation.cleanup)
        cls.helper = Path(cls.compilation.name) / "helper"
        subprocess.run(["/usr/bin/clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",
                        "-mmacosx-version-min=12.0", "-DMCD_TRANSACTION_TESTING",
                        str(REPO / "bin/claude-transaction.c"), "-o", str(cls.helper)], check=True)

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="claude-transaction-")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name).resolve()
        self.stage = self.root / ".claude-txn.aBc12345"
        self.stage.mkdir(mode=0o700)
        self.candidate = self.stage / "instance.app"
        self.candidate.mkdir()
        (self.candidate / "marker").write_text("new")
        self.live = self.root / "Claude One.app"
        self.env = os.environ.copy()
        for key in ["MCD_TRANSACTION_LOCK_FD", "MCD_TEST_STOP", "MCD_TEST_RENAME_UNSUPPORTED"]:
            self.env.pop(key, None)

    def old_bundle(self):
        self.live.mkdir()
        (self.live / "marker").write_text("old")

    def run_helper(self, *arguments):
        return subprocess.run([str(self.helper), *map(str, arguments)], env=self.env,
                              text=True, capture_output=True, timeout=10)

    def publish(self):
        return self.run_helper("publish", self.root, self.stage.name, "One")

    def inspect(self):
        return self.run_helper("inspect", self.root, self.stage.name)

    def stopped_publication(self, point):
        self.env["MCD_TEST_STOP"] = point
        process = subprocess.Popen([str(self.helper), "publish", str(self.root), self.stage.name, "One"],
                                   env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: self.kill_and_reap(process))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            pid, status = os.waitpid(process.pid, os.WNOHANG | os.WUNTRACED)
            if pid:
                if os.WIFSTOPPED(status):
                    return process
                self.fail("publication exited before its injection point")
            time.sleep(0.01)
        self.fail("publication did not reach its injection point")

    @staticmethod
    def kill_and_reap(process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)

    def test_atomic_exchange_retains_previous_bundle_and_immutable_journal(self):
        self.old_bundle()
        old_inode, new_inode = self.live.stat().st_ino, self.candidate.stat().st_ino
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COMMITTED One", result.stdout)
        self.assertEqual(self.live.stat().st_ino, new_inode)
        self.assertEqual(self.candidate.stat().st_ino, old_inode)
        self.assertEqual((self.candidate / "marker").read_text(), "old")
        journal = self.stage / "transaction.txt"
        before = journal.read_bytes()
        self.assertEqual(journal.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.inspect().returncode, 0)
        self.assertEqual(journal.read_bytes(), before)
        self.assertNotEqual(self.publish().returncode, 0)  # Cannot publish twice.
        self.assertEqual((self.live / "marker").read_text(), "new")

    def test_first_install_publishes_without_replacing_an_existing_path(self):
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.live.is_dir())
        self.assertFalse(self.candidate.exists())
        self.assertIn("COMMITTED", self.inspect().stdout)

    def test_exclusive_publication_refuses_a_destination_appearing_at_rename(self):
        process = self.stopped_publication("before-rename")
        self.old_bundle()  # Simulates a non-cooperating creator after the check.
        process.send_signal(signal.SIGCONT)
        stdout, stderr = process.communicate(timeout=5)
        self.assertNotEqual(process.returncode, 0, stdout)
        self.assertIn("no fallback", stderr)
        self.assertEqual((self.live / "marker").read_text(), "old")
        self.assertEqual((self.candidate / "marker").read_text(), "new")
        self.assertNotEqual(self.inspect().returncode, 0)  # Unknown, never guessed.

    def test_sigkill_before_exchange_preserves_old_and_releases_lock(self):
        self.old_bundle()
        process = self.stopped_publication("journal-synced")
        self.kill_and_reap(process)
        self.assertEqual((self.live / "marker").read_text(), "old")
        self.assertEqual((self.candidate / "marker").read_text(), "new")
        result = self.inspect()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PREPARED", result.stdout)

    def test_sigkill_after_exchange_is_recognized_without_deleting_backup(self):
        self.old_bundle()
        process = self.stopped_publication("exchanged")
        self.kill_and_reap(process)
        result = self.inspect()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COMMITTED", result.stdout)
        self.assertEqual((self.live / "marker").read_text(), "new")
        self.assertEqual((self.candidate / "marker").read_text(), "old")

    def test_sigkill_after_first_install_is_recognized(self):
        process = self.stopped_publication("exchanged")
        self.kill_and_reap(process)
        self.assertEqual(self.inspect().returncode, 0)
        self.assertEqual((self.live / "marker").read_text(), "new")

    def test_kernel_lock_blocks_another_worker_and_clears_on_sigkill(self):
        worker = self.root / "wait.sh"
        worker.write_text('"$1" locked "$2" || exit 1\nprintf "LOCKED\\n"\nexec /bin/sleep 10\n')
        process = subprocess.Popen([str(self.helper), "run", str(self.root), str(worker), str(self.root)],
                                   env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: self.kill_and_reap(process))
        self.assertTrue(select.select([process.stdout], [], [], 5)[0])
        self.assertEqual(process.stdout.readline().strip(), "LOCKED")
        blocked = self.publish()
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("holds the lock", blocked.stderr)
        self.kill_and_reap(process)
        self.assertEqual(self.publish().returncode, 0)

    def test_unsupported_atomic_operation_keeps_prepared_candidate_and_old_app(self):
        self.old_bundle()
        self.env["MCD_TEST_RENAME_UNSUPPORTED"] = "1"
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no fallback", result.stderr)
        self.assertEqual((self.live / "marker").read_text(), "old")
        self.assertEqual((self.candidate / "marker").read_text(), "new")
        self.assertIn("PREPARED", self.inspect().stdout)

    def test_links_and_nonprivate_transaction_directory_are_refused(self):
        self.old_bundle()
        self.candidate.rename(self.stage / "real.app")
        self.candidate.symlink_to(self.stage / "real.app", target_is_directory=True)
        self.assertNotEqual(self.publish().returncode, 0)
        self.candidate.unlink()
        (self.stage / "real.app").rename(self.candidate)
        self.candidate.chmod(0o777)
        self.assertNotEqual(self.publish().returncode, 0)
        self.candidate.chmod(0o755)
        self.stage.chmod(0o755)
        self.assertNotEqual(self.publish().returncode, 0)
        self.assertEqual((self.live / "marker").read_text(), "old")

    def test_lock_symlink_and_hardlink_are_refused(self):
        lock = self.root / ".claude-instances.lock"
        victim = self.root / "keep"
        victim.write_text("unchanged")
        victim.chmod(0o600)
        lock.symlink_to(victim)
        self.assertNotEqual(self.publish().returncode, 0)
        lock.unlink()
        os.link(victim, lock)
        self.assertNotEqual(self.publish().returncode, 0)
        self.assertEqual(victim.read_text(), "unchanged")

    def test_journal_links_and_partial_records_are_never_evaluated(self):
        self.old_bundle()
        journal = self.stage / "transaction.txt"
        victim = self.root / "keep"
        victim.write_text("unchanged")
        victim.chmod(0o600)
        journal.symlink_to(victim)
        self.assertNotEqual(self.publish().returncode, 0)
        self.assertNotEqual(self.inspect().returncode, 0)
        journal.unlink()
        os.link(victim, journal)
        self.assertNotEqual(self.inspect().returncode, 0)
        journal.unlink()
        marker = self.root / "executed"
        journal.write_text("MCD_TRANSACTION 1\ninstance $(touch " + str(marker) + ")\n")
        journal.chmod(0o600)
        self.assertNotEqual(self.inspect().returncode, 0)
        self.assertFalse(marker.exists())
        self.assertEqual(victim.read_text(), "unchanged")
        self.assertEqual((self.live / "marker").read_text(), "old")

        journal.unlink()
        self.assertEqual(self.publish().returncode, 0)
        valid = journal.read_bytes()
        malformed = [
            valid.replace(b"root ", b"root 18446744073709551616 ", 1),
            valid.replace(b"root ", b"root -1 ", 1),
            valid.replace(b"old 1 ", b"old 4294967296 ", 1),
            valid.replace(b"old 1 ", b"old 18446744073709551616 ", 1),
            valid + b"\x00ignored",
            valid.replace(b"MCD_TRANSACTION 1", b"MCD_TRANSACTION 01", 1),
        ]
        for content in malformed:
            with self.subTest(content=content[:70]):
                journal.write_bytes(content)
                self.assertNotEqual(self.inspect().returncode, 0)
                self.assertEqual((self.live / "marker").read_text(), "new")
                self.assertEqual((self.candidate / "marker").read_text(), "old")

    def test_changed_bundle_identity_and_journal_directory_are_unknown(self):
        self.assertEqual(self.publish().returncode, 0)
        self.live.rename(self.root / "saved.app")
        self.old_bundle()
        self.assertNotEqual(self.inspect().returncode, 0)
        self.assertEqual((self.live / "marker").read_text(), "old")
        journal = self.stage / "transaction.txt"
        journal.write_text(journal.read_text().replace("root ", "root 0 ", 1))
        self.assertNotEqual(self.inspect().returncode, 0)

    def test_native_acl_checks_allow_deny_but_refuse_allow_entries(self):
        subprocess.run(["/bin/chmod", "+a", "everyone deny delete", str(self.stage)], check=True)
        self.assertEqual(self.publish().returncode, 0)
        subprocess.run(["/bin/chmod", "+a", "everyone allow add_file", str(self.stage)], check=True)
        self.assertNotEqual(self.inspect().returncode, 0)
        subprocess.run(["/bin/chmod", "-N", str(self.stage)], check=True)

    def test_unsafe_names_and_inherited_descriptor_are_refused(self):
        for name in ["../escape", "Claude.app", "-bad", "A/../../Claude", "One;touch"]:
            self.assertNotEqual(self.run_helper("publish", self.root, self.stage.name, name).returncode, 0)
        for name in ["../escape", ".claude-txn.short", str(self.stage)]:
            self.assertNotEqual(self.run_helper("inspect", self.root, name).returncode, 0)
        self.env["MCD_TRANSACTION_LOCK_FD"] = "1"
        self.assertNotEqual(self.publish().returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

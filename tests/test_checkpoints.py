"""Native checkpoint faults and shell policy, synthetic data only.

No installed application, real profile, credential, Keychain or service is read.
"""
import os
from pathlib import Path
import signal
import select
import subprocess
import tempfile
import time
import unittest

import test_hardening as hardening

REPO = Path(__file__).resolve().parents[1]
IDENTIFIER = "01234567-89ab-cdef-0123-456789abcdef"
BINDING = "ab" * 32


class CheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compilation = tempfile.TemporaryDirectory(prefix="claude-checkpoint-native-")
        cls.addClassCleanup(cls.compilation.cleanup)
        cls.helper = Path(cls.compilation.name) / "helper"
        cls.production = Path(cls.compilation.name) / "production"
        command = ["/usr/bin/clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",
                   "-mmacosx-version-min=12.0", str(REPO / "bin/claude-checkpoint.c")]
        subprocess.run(command + ["-DMCD_CHECKPOINT_TESTING", "-o", str(cls.helper)], check=True)
        subprocess.run(command + ["-o", str(cls.production)], check=True)

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="claude-checkpoint-")
        self.addCleanup(self.scratch.cleanup)
        self.base = Path(self.scratch.name).resolve()
        self.root = self.base / "checkpoints"
        self.desktop = self.base / "desktop"
        self.code = self.base / "code"
        for path in (self.root, self.desktop, self.code):
            path.mkdir(mode=0o700)
        (self.desktop / "state").write_bytes(b"synthetic desktop\0data\n")
        (self.code / "settings").write_text("synthetic code")
        self.pending = self.root / (".pending-" + IDENTIFIER)
        self.published = self.root / IDENTIFIER
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("MCD_CHECKPOINT_")}

    def command(self, action, binding=BINDING):
        arguments = [action, self.root, IDENTIFIER, binding]
        if action != "verify":
            arguments += [self.desktop, self.code]
        return list(map(str, arguments))

    def run_helper(self, action, binding=BINDING):
        return subprocess.run([str(self.helper), *self.command(action, binding)], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def prepare(self):
        result = self.run_helper("prepare")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PREPARED", result.stdout)

    def commit(self):
        result = self.run_helper("commit")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COMMITTED", result.stdout)

    def stop(self, action, point):
        self.env["MCD_CHECKPOINT_STOP"] = point
        process = subprocess.Popen([str(self.helper), *self.command(action)], env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: self.kill(process))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            pid, status = os.waitpid(process.pid, os.WNOHANG | os.WUNTRACED)
            if pid:
                if os.WIFSTOPPED(status):
                    return process
                self.fail("helper exited before requested stop point")
            time.sleep(0.01)
        self.fail("helper did not reach requested stop point")

    @staticmethod
    def kill(process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)

    def test_pair_is_verified_private_and_source_bytes_and_metadata_are_unchanged(self):
        nested = self.code / "projects"
        nested.mkdir()
        (nested / "unicode-é\n'$(ignored)").write_bytes(b"invented history")
        executable = self.code / "hook"
        executable.write_text("synthetic")
        executable.chmod(0o755)
        source_stat = (self.desktop / "state").stat()
        self.prepare()
        self.assertNotEqual(self.run_helper("verify").returncode, 0)
        self.commit()
        self.assertFalse(self.pending.exists())
        self.assertEqual(self.run_helper("verify").returncode, 0)
        self.assertEqual((self.published / "desktop/state").read_bytes(), (self.desktop / "state").read_bytes())
        self.assertEqual((self.published / "code/projects" / "unicode-é\n'$(ignored)").read_bytes(), b"invented history")
        self.assertEqual((self.published / "code/hook").stat().st_mode & 0o777, 0o700)
        for path in self.published.rglob("*"):
            self.assertEqual(path.stat().st_mode & 0o077, 0)
        self.assertEqual(self.published.stat().st_mode & 0o777, 0o700)
        after = (self.desktop / "state").stat()
        self.assertEqual((source_stat.st_ino, source_stat.st_mode, source_stat.st_mtime_ns, source_stat.st_ctime_ns),
                         (after.st_ino, after.st_mode, after.st_mtime_ns, after.st_ctime_ns))

    def test_wrong_identity_or_build_binding_is_refused_without_source_mutation(self):
        self.prepare()
        rejected = self.run_helper("commit", "cd" * 32)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("different profile pair or app build", rejected.stderr)
        self.assertFalse(self.published.exists())
        self.commit()
        self.assertNotEqual(self.run_helper("verify", "cd" * 32).returncode, 0)
        self.assertEqual((self.code / "settings").read_text(), "synthetic code")

    def test_source_changes_between_observations_prevent_preparation(self):
        process = self.stop("prepare", "sources-recorded")
        (self.code / "settings").write_text("changed externally")
        process.send_signal(signal.SIGCONT)
        _, errors = process.communicate(timeout=5)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn("changed", errors)
        self.assertFalse(self.published.exists())

    def test_source_changes_after_preparation_prevent_commit(self):
        self.prepare()
        (self.desktop / "state").write_bytes(b"later data")
        self.assertNotEqual(self.run_helper("commit").returncode, 0)
        self.assertFalse(self.published.exists())
        self.assertEqual((self.desktop / "state").read_bytes(), b"later data")

    def test_source_root_replacement_with_identical_bytes_prevents_commit(self):
        self.prepare()
        self.code.rename(self.base / "old-code")
        self.code.mkdir(mode=0o700)
        (self.code / "settings").write_text("synthetic code")
        self.assertNotEqual(self.run_helper("commit").returncode, 0)
        self.assertFalse(self.published.exists())

    def test_sigkill_while_copying_never_publishes_partial_pair(self):
        process = self.stop("prepare", "file-copied")
        self.kill(process)
        self.assertTrue(self.pending.exists())
        self.assertFalse((self.pending / "manifest.txt").exists())
        self.assertNotEqual(self.run_helper("verify").returncode, 0)
        self.assertNotEqual(self.run_helper("commit").returncode, 0)
        self.assertFalse(self.published.exists())

    def test_sigkill_after_preparation_is_not_a_published_checkpoint(self):
        process = self.stop("prepare", "prepared")
        self.kill(process)
        self.assertTrue((self.pending / "manifest.txt").exists())
        self.assertNotEqual(self.run_helper("verify").returncode, 0)
        self.assertFalse(self.published.exists())

    def test_sigkill_after_atomic_publication_leaves_verifiable_pair(self):
        self.prepare()
        process = self.stop("commit", "published")
        self.kill(process)
        self.assertFalse(self.pending.exists())
        self.assertEqual(self.run_helper("verify").returncode, 0)

    def test_destination_appearing_at_publication_is_not_overwritten(self):
        self.prepare()
        process = self.stop("commit", "before-publish")
        self.published.mkdir(mode=0o700)
        (self.published / "keep").write_text("unrelated")
        process.send_signal(signal.SIGCONT)
        process.communicate(timeout=5)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual((self.published / "keep").read_text(), "unrelated")
        self.assertTrue(self.pending.exists())

    def test_unsupported_atomic_operation_has_no_fallback(self):
        self.prepare()
        self.env["MCD_CHECKPOINT_RENAME_UNSUPPORTED"] = "1"
        result = self.run_helper("commit")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no fallback", result.stderr)
        self.assertTrue(self.pending.exists())
        self.assertFalse(self.published.exists())

    def test_corrupted_manifest_extra_bytes_and_partial_data_fail_closed(self):
        self.prepare()
        manifest = self.pending / "manifest.txt"
        original = manifest.read_bytes()
        for bad in (original[:-1], original + b"\0", original.replace(b"MCD_CHECKPOINT 1", b"MCD_CHECKPOINT 2"),
                    original.replace(BINDING.encode(), b"G" * 64), b"../escape\n"):
            with self.subTest(bad=bad[:25]):
                manifest.write_bytes(bad)
                self.assertNotEqual(self.run_helper("commit").returncode, 0)
                self.assertFalse(self.published.exists())
        manifest.write_bytes(original)
        self.commit()

    def test_checkpoint_tampering_and_unexpected_entries_are_detected(self):
        self.prepare()
        self.commit()
        payload = self.published / "code/settings"
        payload.write_text("tampered")
        self.assertNotEqual(self.run_helper("verify").returncode, 0)
        payload.write_text("synthetic code")
        self.assertEqual(self.run_helper("verify").returncode, 0)
        (self.published / "unexpected").write_text("not part of pair")
        self.assertNotEqual(self.run_helper("verify").returncode, 0)

    def test_links_fifos_and_hardlinks_are_refused_without_reading_targets(self):
        victim = self.base / "outside"
        victim.write_text("do not read/copy")
        for kind in ("symlink", "hardlink", "fifo"):
            with self.subTest(kind=kind):
                bad = self.code / "bad"
                if kind == "symlink":
                    bad.symlink_to(victim)
                elif kind == "hardlink":
                    os.link(victim, bad)
                else:
                    os.mkfifo(bad)
                result = self.run_helper("prepare")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.published.exists())
                self.assertFalse((self.pending / "code/bad").exists())
                bad.unlink()
                self.pending.rmdir()  # Fails before copying, no manifest.
        self.assertEqual(victim.read_text(), "do not read/copy")

    def test_xattrs_and_acls_are_refused_rather_than_silently_dropped(self):
        file = self.code / "settings"
        subprocess.run(["/usr/bin/xattr", "-w", "com.example.checkpoint", "synthetic metadata", str(file)], check=True)
        self.assertNotEqual(self.run_helper("prepare").returncode, 0)
        subprocess.run(["/usr/bin/xattr", "-d", "com.example.checkpoint", str(file)], check=True)
        self.pending.rmdir()
        subprocess.run(["/bin/chmod", "+a", "everyone deny delete", str(file)], check=True)
        self.assertNotEqual(self.run_helper("prepare").returncode, 0)
        subprocess.run(["/bin/chmod", "-N", str(file)], check=True)
        self.assertFalse(self.published.exists())

    def test_only_the_os_provenance_attribute_is_tolerated(self):
        # macOS stamps com.apple.provenance on files created by app-launched
        # processes; it is creator metadata, not content, and is not copied.
        file = self.code / "settings"
        for target in (file, self.code):
            subprocess.run(["/usr/bin/xattr", "-wx", "com.apple.provenance", "01020000000000000000", str(target)], check=True)
        self.prepare()
        self.commit()
        self.assertEqual(self.run_helper("verify").returncode, 0)
        self.assertEqual((self.published / "code/settings").read_bytes(), file.read_bytes())

    def test_quarantine_and_other_attributes_still_fail_beside_provenance(self):
        file = self.code / "settings"
        subprocess.run(["/usr/bin/xattr", "-wx", "com.apple.provenance", "01020000000000000000", str(file)], check=True)
        for name in ("com.apple.quarantine", "com.apple.provenance.extra", "com.example.checkpoint"):
            with self.subTest(name=name):
                subprocess.run(["/usr/bin/xattr", "-w", name, "synthetic", str(file)], check=True)
                result = self.run_helper("prepare")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("extended attributes are unsupported", result.stderr)
                subprocess.run(["/usr/bin/xattr", "-d", name, str(file)], check=True)
                if self.pending.exists():
                    self.pending.rmdir()
        self.assertFalse(self.published.exists())

    def test_unsafe_modes_paths_and_linked_manifest_are_refused(self):
        (self.code / "settings").chmod(0o666)
        self.assertNotEqual(self.run_helper("prepare").returncode, 0)
        (self.code / "settings").chmod(0o600)
        self.pending.rmdir()
        self.prepare()
        manifest = self.pending / "manifest.txt"
        manifest.rename(self.base / "manifest")
        manifest.symlink_to(self.base / "manifest")
        self.assertNotEqual(self.run_helper("commit").returncode, 0)
        self.assertFalse(self.published.exists())

    def test_invalid_ids_bindings_overlap_and_symlink_roots_are_refused(self):
        bad_arguments = [[], ["restore", self.root, IDENTIFIER, BINDING],
                         ["verify", self.root, "../escape", BINDING],
                         ["verify", self.root, IDENTIFIER, "x" * 64],
                         ["prepare", self.root, IDENTIFIER, BINDING, self.desktop, self.desktop]]
        for arguments in bad_arguments:
            result = subprocess.run([str(self.helper), *map(str, arguments)], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.published.exists())
        self.pending.rmdir()
        self.root.rename(self.base / "real-checkpoints")
        self.root.symlink_to(self.base / "real-checkpoints", target_is_directory=True)
        self.assertNotEqual(self.run_helper("prepare").returncode, 0)

    def test_production_build_ignores_all_fault_injection_environment(self):
        self.env.update({"MCD_CHECKPOINT_STOP": "file-copied", "MCD_CHECKPOINT_FAIL": "file-copied",
                         "MCD_CHECKPOINT_RENAME_UNSUPPORTED": "1"})
        for action in ("prepare", "commit", "verify"):
            result = subprocess.run([str(self.production), *self.command(action)], env=self.env,
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_deep_tree_is_bounded_without_unbounded_stack_or_publication(self):
        path = self.code
        for _ in range(129):
            path = path / "d"
            path.mkdir(mode=0o700)
        result = self.run_helper("prepare")
        self.assertGreater(result.returncode, 0)  # An ordinary error, not a crash/signal.
        self.assertIn("depth or entry limit", result.stderr)
        self.assertFalse(self.published.exists())


class CheckpointPolicyTests(unittest.TestCase):
    def setUp(self):
        # Reuse fixture construction, without inheriting/running its test cases.
        self.fixture = hardening.HardeningTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.build()
        signature = self.fixture.app / "Contents/_CodeSignature"
        signature.mkdir(exist_ok=True)
        (signature / "CodeResources").write_text("synthetic signature resources")
        (self.fixture.profile("profile one") / "state").write_text("synthetic desktop")
        (self.fixture.code("code one") / "settings").write_text("synthetic code")
        self.root = self.fixture.home / "Library/Application Support/Multi Claude Desktop/Checkpoints"
        source = REPO / "bin/claude-checkpoint.c"
        (self.fixture.bin / source.name).write_bytes(source.read_bytes())
        lsof = self.fixture.bin / "lsof"
        lsof.write_text('''#!/bin/bash
if [ "$2" = -a ]; then
 [ "${MOCK_LSOF_PROBE_UNKNOWN:-}" != 1 ] || exit 1
 printf 'p%s\\nf8\\n' "$4"; exit 0
fi
case "${MOCK_LSOF:-}" in
 busy) echo p999; exit 0 ;;
 error) echo 'synthetic inspection failure' >&2; exit 1 ;;
 unknown) exit 2 ;;
 late) [ ! -e "$MOCK_LSOF_MARKER" ] || { echo p999; exit 0; }; touch "$MOCK_LSOF_MARKER" ;;
esac
exit 1
''')
        lsof.chmod(0o755)
        worker = self.fixture.bin / "claude-checkpoint-worker.sh"
        worker.write_text(worker.read_text().replace("/usr/sbin/lsof", str(lsof)))

    def run_script(self, *args):
        return self.fixture.run_script(*args, script="claude-profile-checkpoint.sh")

    def test_shell_create_and_verify_bind_both_paths_and_app_bytes(self):
        result = self.run_script("create", "One")
        self.assertEqual(result.returncode, 0, result.stderr)
        identifier = next(path.name for path in self.root.iterdir() if not path.name.startswith("."))
        self.assertEqual(self.run_script("verify", "One", identifier).returncode, 0)
        # Mock signature verification still passes; byte binding must catch this.
        with (self.fixture.app / "Contents/MacOS/Claude").open("a") as handle:
            handle.write("\n# changed fixture build\n")
        self.assertNotEqual(self.run_script("verify", "One", identifier).returncode, 0)
        self.assertEqual((self.fixture.code("code one") / "settings").read_text(), "synthetic code")

    def test_running_apps_and_unknown_process_observation_prevent_copy(self):
        for values in ({"MOCK_RUNNING_APP": str(self.fixture.app)}, {"MOCK_PS_FAIL": "1"}):
            with self.subTest(values=values):
                self.fixture.env.update(values)
                result = self.run_script("create", "One")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(list(self.root.glob(".pending-*")))
                for key in values:
                    self.fixture.env.pop(key)

    def test_open_handles_errors_and_unknown_lsof_exit_prevent_copy(self):
        for observation in ("busy", "error", "unknown"):
            with self.subTest(observation=observation):
                self.fixture.env["MOCK_LSOF"] = observation
                result = self.run_script("create", "One")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(list(self.root.glob(".pending-*")))

    def test_invisible_observer_probe_is_not_mistaken_for_idle_profiles(self):
        self.fixture.env["MOCK_LSOF_PROBE_UNKNOWN"] = "1"
        result = self.run_script("create", "One")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not see its own probe", result.stderr)
        self.assertFalse(list(self.root.glob(".pending-*")))

    def test_post_copy_handle_observation_blocks_publication(self):
        # First two calls (both roots) are idle; the next observation is busy.
        self.fixture.env["MOCK_LSOF_MARKER"] = str(self.fixture.root / "lsof-count")
        lsof = self.fixture.bin / "lsof"
        lsof.write_text('''#!/bin/bash
if [ "$2" = -a ]; then printf 'p%s\\nf8\\n' "$4"; exit 0; fi
n=0
[ ! -f "$MOCK_LSOF_MARKER" ] || read -r n < "$MOCK_LSOF_MARKER"
n=$((n+1)); echo "$n" > "$MOCK_LSOF_MARKER"
[ "$n" -le 2 ] || { echo p999; exit 0; }
exit 1
''')
        result = self.run_script("create", "One")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(list(self.root.glob(".pending-*"))), 1)
        self.assertFalse([path for path in self.root.iterdir() if not path.name.startswith(".")])

    def test_missing_source_unknown_instance_and_restore_are_rejected(self):
        self.assertNotEqual(self.run_script("create", "Missing").returncode, 0)
        self.assertNotEqual(self.run_script("restore", "One", IDENTIFIER).returncode, 0)
        (self.fixture.code("code one") / "settings").unlink()
        self.fixture.code("code one").rmdir()
        self.assertNotEqual(self.run_script("create", "One").returncode, 0)
        self.assertFalse(self.fixture.code("code one").exists())

    def test_rebuild_checkpoint_and_cache_workers_share_one_kernel_lock(self):
        tx = self.fixture.bin / "transaction"
        subprocess.run(["/usr/bin/clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",
                        "-mmacosx-version-min=12.0", str(REPO / "bin/claude-transaction.c"), "-o", str(tx)], check=True)
        worker = self.fixture.bin / "hold.sh"
        worker.write_text('"$1" locked "$2" || exit 1\nprintf "LOCKED\\n"\nexec /bin/sleep 20\n')
        process = subprocess.Popen([str(tx), "run", str(self.fixture.apps), str(worker), str(self.fixture.apps)],
                                   env=self.fixture.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: CheckpointTests.kill(process))
        self.assertTrue(select.select([process.stdout], [], [], 5)[0])
        self.assertEqual(process.stdout.readline().strip(), "LOCKED")
        cache = self.fixture.profile("profile one") / "Cache"
        cache.mkdir()
        (cache / "keep").write_text("regenerable, but locked")
        for script, args in (("claude-apps-refresh.sh", ()), ("claude-clear-caches.sh", ()),
                             ("claude-profile-checkpoint.sh", ("create", "One"))):
            with self.subTest(script=script):
                result = self.fixture.run_script(*args, script=script)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("holds the lock", result.stderr)
        self.assertTrue((cache / "keep").exists())
        CheckpointTests.kill(process)
        self.assertEqual(self.run_script("create", "One").returncode, 0)

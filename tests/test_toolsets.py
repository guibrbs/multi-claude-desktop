"""Real Darwin toolset publication, synthetic packages/home; no app/accounts."""
import hashlib
import importlib.util
import os
from pathlib import Path
import pwd
import signal
import select
import shutil
import subprocess
import tempfile
import time
import unittest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prepare_toolset", REPO / "scripts/prepare-toolset.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ToolsetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compilation = tempfile.TemporaryDirectory(prefix="claude-toolset-native-")
        cls.addClassCleanup(cls.compilation.cleanup)
        cls.helper = Path(cls.compilation.name) / "fixture-helper"
        cls.production = Path(cls.compilation.name) / "production-helper"
        cls.alternate = Path(cls.compilation.name) / "alternate-helper"
        source = REPO / "bin/claude-toolset.c"
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        command = ["/usr/bin/clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",
                   "-mmacosx-version-min=12.0", f'-DMCD_TOOLSET_SOURCE_SHA="{digest}"', str(source)]
        subprocess.run(command + ["-DMCD_TOOLSET_TESTING", "-o", str(cls.helper)], check=True)
        subprocess.run(command + ["-o", str(cls.production)], check=True)
        alternate = ["-O0" if arg == "-O2" else arg for arg in command]
        subprocess.run(alternate + ["-DMCD_TOOLSET_TESTING", "-o", str(cls.alternate)], check=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="claude-toolsets-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / "home"
        self.home.mkdir(mode=0o700)
        self.root = self.home / ".local/share/claude-instances/toolsets"
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("MCD_TOOLSET_")}
        self.env["MCD_TOOLSET_TEST_HOME"] = str(self.home)
        self.packages = {}

    def package(self, label="a", script=None):
        source = self.base / ("source-" + label)
        (source / "bin").mkdir(parents=True, mode=0o700)
        for name in builder.FILES:
            shutil.copyfile(REPO / "bin" / name, source / "bin" / name)
        common = source / "bin/claude-instances-common.sh"
        common.write_text(common.read_text() + f"\nTOOLSET_CANARY={label}\n")
        entry = source / "bin/claude-instance-check.sh"
        entry.write_text(script or '#!/bin/bash -p\nsource "${BASH_SOURCE[0]%/*}/claude-instances-common.sh"\nprintf "%s\\n" "$TOOLSET_CANARY"\n')
        destination = self.base / ("package-" + label)
        digest = builder.prepare(source, destination, "a" * 40)
        self.packages[label] = (destination, digest)
        return destination, digest

    def refresh_manifest(self, package):
        lines = ["MCD_TOOLSET 1", "protocol 1", "commit " + "a" * 40]
        for name in builder.FILES:
            path = package / "bin" / name
            lines.append(f"file {name} {builder.mode_for(name):04o} {hashlib.sha256(path.read_bytes()).hexdigest()}")
        manifest = package / "manifest.txt"
        manifest.write_text("\n".join(lines) + "\n")
        return hashlib.sha256(manifest.read_bytes()).hexdigest()

    def call(self, *args, helper=None, env=None):
        return subprocess.run([str(helper or self.helper), *map(str, args)], env=env or self.env,
                              text=True, capture_output=True, timeout=40)

    def install(self, label="a", **kwargs):
        package, digest = self.packages.get(label) or self.package(label, **kwargs)
        result = self.call("install", package, digest)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.current(), digest)
        return package, digest

    def current(self):
        return (self.root / "current").read_text().strip()

    def stopped_install(self, package, digest, point, helper=None):
        env = dict(self.env, MCD_TOOLSET_STOP=point)
        process = subprocess.Popen([str(helper or self.helper), "install", str(package), digest], env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.kill, process)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            pid, status = os.waitpid(process.pid, os.WNOHANG | os.WUNTRACED)
            if pid:
                if os.WIFSTOPPED(status):
                    return process
                self.fail("installer exited before stop: " + process.stderr.read())
            time.sleep(0.02)
        self.fail("installer did not reach stop point")

    @staticmethod
    def kill(process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)

    def test_install_verifies_full_payload_and_dispatches_public_entry(self):
        package, digest = self.install()
        self.assertEqual(self.call("verify").returncode, 0)
        result = self.call("run", "claude-instance-check.sh", helper=self.root / "dispatcher")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "a")
        release = self.root / "releases" / digest
        self.assertEqual((release / "manifest.txt").read_bytes(), (package / "manifest.txt").read_bytes())
        for name in builder.FILES:
            self.assertEqual((release / "bin" / name).stat().st_mode & 0o7777, builder.mode_for(name))
        self.assertEqual((self.root / "current").stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.home / "bin").exists())

    def test_upgrade_retains_versions_and_tools_only_activation_can_return(self):
        _, first = self.install("a")
        _, second = self.install("b")
        self.assertNotEqual(first, second)
        self.assertEqual(self.call("run", "claude-instance-check.sh").stdout.strip(), "b")
        self.assertEqual(self.call("activate", first).returncode, 0)
        self.assertEqual(self.call("run", "claude-instance-check.sh").stdout.strip(), "a")
        self.assertTrue((self.root / "releases" / second).exists())

    def test_inflight_entry_reads_its_own_common_after_an_upgrade(self):
        script = '#!/bin/bash -p\nprintf "READY\\n"\nIFS= read -r proceed\nsource "${BASH_SOURCE[0]%/*}/claude-instances-common.sh"\nprintf "%s\\n" "$TOOLSET_CANARY"\n'
        self.install("a", script=script)
        process = subprocess.Popen([str(self.root / "dispatcher"), "run", "claude-instance-check.sh"],
                                   env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.kill, process)
        self.assertTrue(select.select([process.stdout], [], [], 5)[0])
        self.assertEqual(process.stdout.readline().strip(), "READY")
        self.install("b")
        out, err = process.communicate("continue\n", timeout=5)
        self.assertEqual(process.returncode, 0, err)
        self.assertEqual(out.strip(), "a")
        self.assertEqual(self.call("run", "claude-instance-check.sh").stdout.strip(), "b")

    def test_bad_pin_missing_and_extra_files_never_activate(self):
        package, digest = self.package()
        self.assertNotEqual(self.call("install", package, "0" * 64).returncode, 0)
        extra = package / "bin/extra.sh"
        extra.write_text("synthetic")
        self.assertNotEqual(self.call("install", package, digest).returncode, 0)
        extra.unlink()
        (package / "bin/claude-maintenance.h").unlink()
        self.assertNotEqual(self.call("install", package, digest).returncode, 0)
        self.assertFalse((self.root / "current").exists())

    def test_manifest_grammar_is_canonical_bounded_and_never_shell(self):
        package, _ = self.package()
        manifest = package / "manifest.txt"
        original = manifest.read_bytes()
        for content in [original + b"extra\n", original + b"\0", original.replace(b"protocol 1", b"protocol 2"),
                        original.replace(b"claude-build-worker.sh", b"../claude-build-worker.sh"), b"x" * 5000]:
            with self.subTest(content=content[:30]):
                manifest.write_bytes(content)
                digest = hashlib.sha256(content).hexdigest()
                self.assertNotEqual(self.call("package-check", package, digest).returncode, 0)
        self.assertFalse((self.root / "current").exists())

    def test_package_links_hardlinks_and_unsafe_modes_are_refused(self):
        package, digest = self.package()
        file = package / "bin/claude-maintenance.h"
        saved = self.base / "saved"
        file.rename(saved)
        file.symlink_to(saved)
        self.assertNotEqual(self.call("package-check", package, digest).returncode, 0)
        file.unlink()
        saved.rename(file)
        linked = self.base / "linked"
        os.link(file, linked)
        self.assertNotEqual(self.call("package-check", package, digest).returncode, 0)
        linked.unlink()
        file.chmod(0o666)
        self.assertNotEqual(self.call("package-check", package, digest).returncode, 0)

    def test_package_provenance_is_tolerated_but_other_attributes_are_refused(self):
        package, digest = self.package()
        file = package / "bin/claude-maintenance.h"
        subprocess.run(["/usr/bin/xattr", "-wx", "com.apple.provenance", "01020000000000000000", str(file)], check=True)
        self.assertEqual(self.call("package-check", package, digest).returncode, 0)
        for name in ("com.apple.quarantine", "com.example.toolset"):
            with self.subTest(name=name):
                subprocess.run(["/usr/bin/xattr", "-w", name, "synthetic", str(file)], check=True)
                refused = self.call("package-check", package, digest)
                self.assertNotEqual(refused.returncode, 0)
                self.assertIn("file attributes are unsupported", refused.stderr)
                subprocess.run(["/usr/bin/xattr", "-d", name, str(file)], check=True)
        self.install()
        self.assertEqual(self.call("verify").returncode, 0)

    def test_installed_content_and_manifest_drift_are_detected_before_dispatch(self):
        _, digest = self.install()
        release = self.root / "releases" / digest
        script = release / "bin/claude-instance-check.sh"
        script.write_text(script.read_text() + "\n# changed\n")
        self.assertNotEqual(self.call("run", "claude-instance-check.sh").returncode, 0)
        new_hash = self.refresh_manifest(release)
        self.assertNotEqual(new_hash, digest)
        self.assertNotEqual(self.call("verify").returncode, 0)

    def test_current_pointer_and_release_links_are_refused(self):
        _, digest = self.install()
        pointer = self.root / "current"
        saved = self.root / "saved-pointer"
        pointer.rename(saved)
        pointer.symlink_to(saved)
        self.assertNotEqual(self.call("verify").returncode, 0)
        pointer.unlink()
        saved.rename(pointer)
        release = self.root / "releases" / digest
        moved = self.root / "saved-release"
        release.rename(moved)
        release.symlink_to(moved, target_is_directory=True)
        self.assertNotEqual(self.call("verify").returncode, 0)

    def test_private_workers_and_traversal_cannot_be_dispatched(self):
        self.install()
        for name in ["claude-build-worker.sh", "claude-instances-common.sh", "../claude-instance-check.sh", "claude-toolset.sh"]:
            self.assertNotEqual(self.call("run", name).returncode, 0)

    def test_failed_syntax_preflight_does_not_execute_or_activate_package(self):
        marker = self.base / "unexpected-execution"
        package, digest = self.package(script=f'#!/bin/bash -p\n: > "{marker}"\nif\n')
        result = self.call("install", package, digest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("preflight failed", result.stderr)
        self.assertFalse(marker.exists())
        self.assertFalse((self.root / "current").exists())

    def test_actual_installer_wrapper_uses_private_compilation_and_fixed_path(self):
        source = self.base / "wrapper-source"
        (source / "bin").mkdir(parents=True)
        for name in builder.FILES:
            data = (REPO / "bin" / name).read_text()
            if name.endswith(".sh"):
                data = data.replace("$HOME", "$MULTI_CLAUDE_TEST_HOME")
            if name == "claude-toolset.c":
                data = "#define MCD_TOOLSET_TESTING\n" + data
            (source / "bin" / name).write_text(data)
        package = self.base / "wrapper-package"
        digest = builder.prepare(source, package, "a" * 40)
        hostile = self.base / "hostile"
        hostile.mkdir()
        marker = self.base / "hostile-executed"
        for name in ["clang", "cp", "shasum", "dirname"]:
            path = hostile / name
            path.write_text(f'#!/bin/bash\n: > "{marker}"\nexit 99\n')
            path.chmod(0o755)
        startup = self.base / "startup.sh"
        startup.write_text(f': > "{marker}"\n')
        env = dict(self.env, MULTI_CLAUDE_TEST_HOME=str(self.home), BASH_ENV=str(startup), PATH=str(hostile))
        result = subprocess.run(["/bin/bash", "-p", str(source / "bin/claude-toolset.sh"), "install", str(package), digest],
                                env=env, text=True, capture_output=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(self.current(), digest)
        self.assertFalse(list((self.home / ".local/share/claude-instances").glob(".toolset-native.*")))

    def test_compilation_failure_and_mismatched_installer_do_not_activate(self):
        package, _ = self.package()
        source = package / "bin/claude-checkpoint.c"
        source.write_text("this is deliberately invalid C\n")
        digest = self.refresh_manifest(package)
        self.assertNotEqual(self.call("install", package, digest).returncode, 0)
        source = package / "bin/claude-toolset.c"
        source.write_text(source.read_text() + "\n/* different reviewed installer required */\n")
        digest = self.refresh_manifest(package)
        result = self.call("install", package, digest)
        self.assertIn("matching reviewed installer", result.stderr)
        self.assertFalse((self.root / "current").exists())

    def test_sigkill_at_each_publication_boundary_keeps_a_complete_release(self):
        _, first = self.install()
        for index, point in enumerate(["file-copied", "release-published", "journal-synced", "bootstrap-published", "pointer-published"]):
            with self.subTest(point=point):
                self.assertEqual(self.call("activate", first).returncode, 0)
                package, digest = self.package("next" + str(index))
                process = self.stopped_install(package, digest, point)
                self.kill(process)
                self.assertEqual(self.call("verify").returncode, 0)
                self.assertEqual(self.current(), digest if point == "pointer-published" else first)
                self.assertTrue((self.root / "releases" / first).exists())
                self.assertEqual(self.call("run", "claude-instance-check.sh", helper=self.root / "dispatcher").returncode, 0)

    def test_concurrent_install_is_refused_and_lock_releases_after_sigkill(self):
        self.install()
        package, digest = self.package("b")
        process = self.stopped_install(package, digest, "journal-synced")
        result = self.call("install", package, digest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("holds the lock", result.stderr)
        self.kill(process)
        self.assertEqual(self.call("verify").returncode, 0)
        self.assertEqual(self.call("install", package, digest).returncode, 0)

    def test_source_change_after_validation_never_becomes_active(self):
        _, first = self.install()
        package, digest = self.package("b")
        process = self.stopped_install(package, digest, "package-verified")
        common = package / "bin/claude-instances-common.sh"
        common.write_text(common.read_text() + "\n# changed after validation\n")
        process.send_signal(signal.SIGCONT)
        out, err = process.communicate(timeout=10)
        self.assertNotEqual(process.returncode, 0, out)
        self.assertIn("changed during copy", err)
        self.assertEqual(self.current(), first)

    def test_injected_enospc_and_partial_journal_leave_previous_release_active(self):
        _, first = self.install()
        package, digest = self.package("b")
        for variable in [{"MCD_TOOLSET_ENOSPC": "1"}, {"MCD_TOOLSET_FAIL": "partial-journal"}]:
            result = self.call("install", package, digest, env=dict(self.env, **variable))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("No space left", result.stderr)
            self.assertEqual(self.current(), first)
        partial = [p for p in self.root.glob(".install-*/operation.txt") if p.stat().st_size == 8]
        self.assertEqual(len(partial), 1)
        self.assertNotEqual(self.call("inspect", partial[0].parent.name).returncode, 0)

    def test_compilation_rejects_inherited_include_and_sdk_overrides(self):
        package, digest = self.package()
        hostile = self.base / "hostile-headers"
        (hostile / "sys").mkdir(parents=True)
        (hostile / "sys/stat.h").write_text("#error unexpected caller include path\n")
        env = dict(self.env, CPATH=str(hostile), C_INCLUDE_PATH=str(hostile), SDKROOT=str(hostile), TMPDIR=str(hostile))
        result = self.call("install", package, digest, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_new_dispatcher_and_old_release_remain_protocol_compatible(self):
        _, first = self.install()
        before = (self.root / "dispatcher").read_bytes()
        package, digest = self.package("b")
        process = self.stopped_install(package, digest, "bootstrap-published", helper=self.alternate)
        self.kill(process)
        self.assertEqual(self.current(), first)
        self.assertNotEqual(before, (self.root / "dispatcher").read_bytes())
        result = self.call("run", "claude-instance-check.sh", helper=self.root / "dispatcher")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "a")

    def test_interrupted_first_install_has_no_partial_active_payload(self):
        package, digest = self.package()
        process = self.stopped_install(package, digest, "bootstrap-published")
        self.kill(process)
        self.assertFalse((self.root / "current").exists())
        result = self.call("status", helper=self.root / "dispatcher")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no active", result.stderr)
        stage = next(self.root.glob(".install-*"))
        inspected = self.call("inspect", stage.name)
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        self.assertIn("NO_ACTIVE_RELEASE", inspected.stdout)
        self.assertEqual(self.call("install", package, digest).returncode, 0)

    def test_failure_after_pointer_swap_is_reported_as_requested_active(self):
        self.install()
        package, digest = self.package("b")
        result = self.call("install", package, digest, env=dict(self.env, MCD_TOOLSET_FAIL="pointer-published"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.current(), digest)
        stage = [line.split()[-1] for line in result.stderr.splitlines() if "retained operation" in line][0]
        inspected = self.call("inspect", stage)
        self.assertEqual(inspected.returncode, 0, inspected.stderr)
        self.assertIn("REQUESTED_RELEASE_ACTIVE", inspected.stdout)

    def test_unsupported_atomic_operation_never_uses_a_weaker_fallback(self):
        _, first = self.install()
        package, digest = self.package("b")
        result = self.call("install", package, digest, env=dict(self.env, MCD_TOOLSET_RENAME_UNSUPPORTED="1"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no fallback", result.stderr)
        self.assertEqual(self.current(), first)

    def test_read_only_inspection_refuses_extra_record_bytes_and_unknown_layout(self):
        self.install()
        stage = next(self.root.glob(".install-*"))
        record = stage / "operation.txt"
        before = record.read_bytes()
        result = self.call("inspect", stage.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("REQUESTED_RELEASE_ACTIVE", result.stdout)
        self.assertEqual(record.read_bytes(), before)
        record.write_bytes(before + b"extra\n")
        self.assertNotEqual(self.call("inspect", stage.name).returncode, 0)
        record.write_bytes(before)
        (self.root / "current").write_text("0" * 64 + "\n")
        self.assertNotEqual(self.call("inspect", stage.name).returncode, 0)
        self.assertTrue(record.exists())

    def test_unsafe_lock_and_root_symlink_do_not_redirect_writes(self):
        self.install()
        lock = self.root / ".toolset.lock"
        linked = self.root / "linked-lock"
        os.link(lock, linked)
        self.assertNotEqual(self.call("verify").returncode, 0)
        linked.unlink()
        outside = self.base / "outside"
        outside.mkdir(mode=0o700)
        renamed = self.root.parent / "previous-tools"
        self.root.rename(renamed)
        self.root.symlink_to(outside, target_is_directory=True)
        package, digest = self.package("b")
        self.assertNotEqual(self.call("install", package, digest).returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])

    def test_production_ignores_fixture_home_faults_and_stop_variables(self):
        package, digest = self.package()
        env = dict(self.env, MCD_TOOLSET_STOP="package-verified", MCD_TOOLSET_FAIL="package-verified")
        result = self.call("package-check", package, digest, helper=self.production, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.call("where", helper=self.production)
        expected = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local/share/claude-instances/toolsets"
        self.assertEqual(result.stdout.strip(), str(expected))
        self.assertFalse(self.root.exists())

    def test_protocol_inventory_matches_every_repository_bin_file(self):
        self.assertEqual(set(builder.FILES), {p.name for p in (REPO / "bin").iterdir()})

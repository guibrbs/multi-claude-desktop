"""Sharing selected Code files with the Duo; synthetic profiles only."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts/share-code-profile.py"
SECRET = "sk-ant-synthetic-never-printed"


class ShareProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="share-profile-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.source, self.duo, self.app = root / "claude", root / "claude-duo", root / "Apps/Claude Duo.app"
        for folder in (self.source, self.duo):
            folder.mkdir(mode=0o700)
        (self.source / "CLAUDE.md").write_text("instructions\n")
        for name in ("skills/demo", "output-styles", "tools/arc", "plugins/cache"):
            (self.source / name).mkdir(parents=True)
        (self.source / "skills/demo/SKILL.md").write_text("skill\n")
        (self.source / "tools/arc/arc.py").write_text("print('tool')\n")
        (self.source / "plugins/installed_plugins.json").write_text("{}\n")
        (self.source / "projects/-proj-a/memory").mkdir(parents=True)
        (self.source / "projects/-proj-a/memory/MEMORY.md").write_text("- fact\n")
        (self.source / "projects/-proj-a/session.jsonl").write_text("transcript of account A\n")
        (self.source / "projects/-proj-b").mkdir()
        (self.source / ".claude.json").write_text('{"oauthAccount": {"emailAddress": "a@example.com"}}\n')
        (self.source / "sessions").mkdir()
        (self.source / "history.jsonl").write_text("history of account A\n")
        self.settings = {"model": "opus", "permissions": {"allow": ["Bash(ls)"]}, "hooks": {},
                         "env": {"MCP_TOOL_TIMEOUT": "60000", "ANTHROPIC_API_KEY": SECRET},
                         "apiKeyHelper": "/bin/echo " + SECRET,
                         "extraKnownMarketplaces": {"team": {"source": "github"}}}
        (self.source / "settings.json").write_text(json.dumps(self.settings))
        (self.duo / ".claude.json").write_text('{"oauthAccount": {"emailAddress": "b@example.com"}}\n')
        (self.duo / "sessions").mkdir()
        (self.duo / "settings.json").write_text(json.dumps({"extraKnownMarketplaces": {"org": {"source": "url"}}}))

    def run_script(self, *args):
        return subprocess.run(["/usr/bin/python3", "-I", str(SCRIPT), "--source", str(self.source),
                               "--destination", str(self.duo), "--app", str(self.app), *args],
                              capture_output=True, text=True, timeout=30)

    def snapshot(self, root):
        return {str(p.relative_to(root)): (p.is_symlink(), os.readlink(p) if p.is_symlink() else
                                           (p.read_bytes() if p.is_file() else None))
                for p in sorted(root.rglob("*"))}

    def test_dry_run_changes_nothing_and_never_prints_secrets(self):
        before = (self.snapshot(self.source), self.snapshot(self.duo))
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Dry run", result.stdout)
        self.assertEqual((self.snapshot(self.source), self.snapshot(self.duo)), before)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        self.assertIn("env.ANTHROPIC_API_KEY", result.stdout)

    def test_apply_links_selected_items_and_copies_filtered_settings(self):
        source_before = self.snapshot(self.source)
        result = self.run_script("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("CLAUDE.md", "skills", "output-styles", "tools", "plugins"):
            self.assertTrue((self.duo / name).is_symlink(), name)
            self.assertEqual(os.readlink(self.duo / name), str(self.source / name))
        memory = self.duo / "projects/-proj-a/memory"
        self.assertTrue(memory.is_symlink())
        self.assertEqual((memory / "MEMORY.md").read_text(), "- fact\n")
        self.assertFalse((self.duo / "projects/-proj-a/session.jsonl").exists())
        self.assertFalse((self.duo / "projects/-proj-b").exists())
        self.assertFalse((self.duo / "history.jsonl").exists())
        self.assertIn("b@example.com", (self.duo / ".claude.json").read_text())
        self.assertFalse((self.duo / "sessions").is_symlink())
        settings = json.loads((self.duo / "settings.json").read_text())
        self.assertEqual(settings["model"], "opus")
        self.assertEqual(settings["env"], {"MCP_TOOL_TIMEOUT": "60000"})
        self.assertNotIn("apiKeyHelper", settings)
        self.assertEqual(set(settings["extraKnownMarketplaces"]), {"org", "team"})
        self.assertNotIn(SECRET, (self.duo / "settings.json").read_text() + result.stdout + result.stderr)
        self.assertEqual((self.duo / "settings.json").stat().st_mode & 0o777, 0o600)
        backups = list(self.duo.glob(".share-backup-*/settings.json"))
        self.assertEqual(len(backups), 1)  # Previous Duo settings kept, not deleted.
        self.assertEqual(self.snapshot(self.source), source_before)
        # A memory written through either profile is the same file.
        (memory / "MEMORY.md").write_text("- fact\n- from the Duo\n")
        self.assertIn("from the Duo", (self.source / "projects/-proj-a/memory/MEMORY.md").read_text())

    def test_second_run_is_a_no_op_and_settings_are_copied_only_once(self):
        self.assertEqual(self.run_script("--apply").returncode, 0)
        settings = json.loads((self.duo / "settings.json").read_text())
        settings["model"] = "sonnet"  # A Duo-only adjustment.
        (self.duo / "settings.json").write_text(json.dumps(settings))
        again = self.run_script("--apply")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertNotIn("link ", again.stdout.replace("ok ", ""))
        self.assertEqual(json.loads((self.duo / "settings.json").read_text())["model"], "sonnet")
        self.assertEqual(len(list(self.duo.glob(".share-backup-*"))), 1)

    def test_new_original_project_memory_is_linked_on_rerun_and_duo_only_memory_is_kept(self):
        self.assertEqual(self.run_script("--apply").returncode, 0)
        (self.source / "projects/-proj-c/memory").mkdir(parents=True)
        duo_only = self.duo / "projects/-proj-d/memory"
        duo_only.mkdir(parents=True)
        (duo_only / "MEMORY.md").write_text("duo only\n")
        result = self.run_script("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.duo / "projects/-proj-c/memory").is_symlink())
        self.assertFalse(duo_only.is_symlink())
        self.assertEqual((duo_only / "MEMORY.md").read_text(), "duo only\n")
        self.assertIn("memory only in the Duo", result.stdout)

    def test_existing_duo_items_are_refused_or_moved_aside_never_deleted(self):
        (self.duo / "plugins/marketplaces/official").mkdir(parents=True)
        (self.duo / "plugins/known_marketplaces.json").write_text("{\"duo\": 1}\n")
        refused = self.run_script("--apply")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("--backup-existing", refused.stderr)
        self.assertFalse((self.duo / "skills").exists())  # Nothing applied after a refusal.
        moved = self.run_script("--apply", "--backup-existing")
        self.assertEqual(moved.returncode, 0, moved.stderr)
        self.assertTrue((self.duo / "plugins").is_symlink())
        kept = list(self.duo.glob(".share-backup-*/plugins/known_marketplaces.json"))
        self.assertEqual([p.read_text() for p in kept], ["{\"duo\": 1}\n"])

    def test_links_elsewhere_linked_sources_and_unsafe_folders_are_refused(self):
        other = Path(self.temp.name) / "elsewhere"
        other.mkdir()
        (self.duo / "skills").symlink_to(other)
        self.assertNotEqual(self.run_script("--apply").returncode, 0)
        (self.duo / "skills").unlink()
        (self.source / "tools").rename(Path(self.temp.name) / "tools-real")
        (self.source / "tools").symlink_to(Path(self.temp.name) / "tools-real")
        linked = self.run_script()
        self.assertNotEqual(linked.returncode, 0)
        self.assertIn("source is a link", linked.stderr)
        (self.source / "tools").unlink()
        (Path(self.temp.name) / "tools-real").rename(self.source / "tools")
        self.duo.chmod(0o770)
        unsafe = self.run_script()
        self.assertNotEqual(unsafe.returncode, 0)
        self.assertIn("not writable by others", unsafe.stderr)
        self.duo.chmod(0o700)
        nested = subprocess.run(["/usr/bin/python3", "-I", str(SCRIPT), "--source", str(self.source),
                                 "--destination", str(self.source / "skills")], capture_output=True, text=True)
        self.assertNotEqual(nested.returncode, 0)

    def test_duplicate_settings_keys_are_refused(self):
        (self.source / "settings.json").write_text('{"model": "opus", "model": "haiku"}')
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate JSON key", result.stderr)

    def test_running_duo_blocks_apply_but_not_the_dry_run(self):
        executable = self.app / "Contents/MacOS/Claude"
        executable.parent.mkdir(parents=True)
        source = Path(self.temp.name) / "wait.c"
        source.write_text('#include <unistd.h>\nint main(void){char c;write(1,"R\\n",2);return read(0,&c,1)<0;}\n')
        subprocess.run(["/usr/bin/clang", str(source), "-o", str(executable)], check=True)
        process = subprocess.Popen([str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        self.addCleanup(lambda: (process.poll() is None and process.kill(), process.communicate(timeout=5)))
        self.assertEqual(process.stdout.readline(), b"R\n")
        self.assertEqual(self.run_script().returncode, 0)
        blocked = self.run_script("--apply")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("Claude Duo is running", blocked.stderr)
        self.assertFalse((self.duo / "skills").exists())


if __name__ == "__main__":
    unittest.main()

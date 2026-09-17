# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.

"""Exercise project configuration linking through its public CLI."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "link_agent_config.py"


class LinkAgentConfigTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="agent-config-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.start_dir = self.root / "agent startup"
        self.start_dir.mkdir()
        self.work_dir = self.root / "new work" / "nested"

    def run_linker(self, start_dir=None, work_dir=None, cwd=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT),
             "--start-dir", str(self.start_dir if start_dir is None else start_dir),
             "--work-dir", str(self.work_dir if work_dir is None else work_dir)],
            cwd=cwd, capture_output=True, text=True,
        )

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, (result.stdout or "") + (result.stderr or ""))

    def test_links_installer_configuration_and_instructions(self):
        directories = (
            ".opencode", ".claude", ".codex", ".agents", ".traecli",
            ".marscode", ".trae", ".trae-cn", ".dsh",
        )
        for name in directories:
            (self.start_dir / name).mkdir()
            (self.start_dir / name / "config.txt").write_text(name)
        for name in ("AGENTS.md", "CLAUDE.md"):
            (self.start_dir / name).write_text(name)
        for name in (".git", ".workflow", "node_modules"):
            (self.start_dir / name).mkdir()
        (self.start_dir / ".env").write_text("local settings")

        self.assert_success(self.run_linker())

        self.assertEqual(
            {path.name for path in self.work_dir.iterdir()},
            set(directories) | {"AGENTS.md", "CLAUDE.md"},
        )
        for name in directories + ("AGENTS.md", "CLAUDE.md"):
            with self.subTest(name=name):
                target = self.work_dir / name
                self.assertTrue(target.is_symlink())
                self.assertEqual(os.readlink(target), str(self.start_dir / name))
                content = target / "config.txt" if name in directories else target
                self.assertEqual(content.read_text(), name)

    def test_repeated_run_preserves_link_and_adds_missing_entries(self):
        (self.start_dir / ".opencode").mkdir()
        self.assert_success(self.run_linker())
        target = self.work_dir / ".opencode"
        original = target.lstat()
        (self.start_dir / ".claude").mkdir()

        self.assert_success(self.run_linker())

        self.assertEqual(target.lstat().st_ino, original.st_ino)
        self.assertEqual(target.lstat().st_mtime_ns, original.st_mtime_ns)
        self.assertTrue((self.work_dir / ".claude").is_symlink())

    def test_preserves_existing_links_even_when_dangling_or_pointing_elsewhere(self):
        self.work_dir.mkdir(parents=True)
        other = self.root / "other config"
        other.mkdir()
        for name, destination in ((".opencode", other),
                                  (".claude", self.root / "missing config")):
            (self.start_dir / name).mkdir()
            (self.work_dir / name).symlink_to(destination)
        (self.start_dir / ".codex").mkdir()

        self.assert_success(self.run_linker())

        self.assertEqual(os.readlink(self.work_dir / ".opencode"), str(other))
        self.assertEqual(os.readlink(self.work_dir / ".claude"),
                         str(self.root / "missing config"))
        self.assertTrue((self.work_dir / ".codex").is_symlink())

    def test_preserves_existing_real_directories_and_files(self):
        self.work_dir.mkdir(parents=True)
        (self.start_dir / ".claude").mkdir()
        (self.start_dir / "AGENTS.md").write_text("source instructions")
        (self.work_dir / ".claude").mkdir()
        (self.work_dir / ".claude" / "keep.txt").write_text("local config")
        (self.work_dir / "AGENTS.md").write_text("local instructions")

        self.assert_success(self.run_linker())

        self.assertFalse((self.work_dir / ".claude").is_symlink())
        self.assertEqual((self.work_dir / ".claude" / "keep.txt").read_text(),
                         "local config")
        self.assertEqual((self.work_dir / "AGENTS.md").read_text(),
                         "local instructions")

    def test_missing_configuration_still_creates_work_directory(self):
        self.assert_success(self.run_linker())
        self.assertTrue(self.work_dir.is_dir())
        self.assertEqual(list(self.work_dir.iterdir()), [])

    def test_prints_arguments_and_linking_result_without_writing_a_log(self):
        (self.start_dir / ".codex").mkdir()

        result = self.run_linker()
        self.assert_success(result)

        self.assertIn(f"start-dir: {self.start_dir}", result.stdout)
        self.assertIn(f"work-dir: {self.work_dir}", result.stdout)
        self.assertIn("linked .codex", result.stdout)
        self.assertFalse((self.work_dir / "orchestrator.log").exists())

    def test_skill_style_stdout_redirect_appends_to_orchestrator_log(self):
        self.work_dir.mkdir(parents=True)
        log_path = self.work_dir / "orchestrator.log"
        log_path.write_text("existing workflow output\n")

        with log_path.open("a", encoding="utf-8") as log:
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--start-dir", str(self.start_dir),
                 "--work-dir", str(self.work_dir)],
                stdout=log, stderr=subprocess.PIPE, text=True,
            )
        self.assert_success(result)

        log = log_path.read_text()
        self.assertTrue(log.startswith("existing workflow output\n"))
        self.assertIn(f"start-dir: {self.start_dir}", log)

    def test_relative_paths_link_to_explicit_start_directory(self):
        (self.start_dir / ".codex").mkdir()
        (self.root / ".claude").mkdir()

        self.assert_success(self.run_linker(
            start_dir="agent startup", work_dir="new work/nested", cwd=self.root,
        ))

        self.assertEqual(os.readlink(self.work_dir / ".codex"),
                         str(self.start_dir / ".codex"))
        self.assertFalse((self.work_dir / ".claude").exists())

    def test_source_symlink_retains_indirection(self):
        original = self.root / "shared config"
        original.mkdir()
        (self.start_dir / ".agents").symlink_to(original)

        self.assert_success(self.run_linker())

        target = self.work_dir / ".agents"
        self.assertEqual(os.readlink(target), str(self.start_dir / ".agents"))
        self.assertEqual(target.resolve(), original)

    def test_same_start_and_work_directory_preserves_source(self):
        (self.start_dir / ".claude").mkdir()

        self.assert_success(self.run_linker(work_dir=self.start_dir))

        self.assertTrue((self.start_dir / ".claude").is_dir())
        self.assertFalse((self.start_dir / ".claude").is_symlink())

    def test_invalid_start_directory_fails_without_creating_work_directory(self):
        source_file = self.root / "source file"
        source_file.write_text("keep")
        for source in (self.root / "missing source", source_file):
            with self.subTest(source=source):
                result = self.run_linker(start_dir=source)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("start directory", result.stderr.lower())
                self.assertFalse(self.work_dir.exists())

    def test_work_directory_conflicting_with_file_reports_failure(self):
        self.work_dir.parent.mkdir()
        self.work_dir.write_text("keep")

        result = self.run_linker()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.work_dir.read_text(), "keep")
        self.assertIn("error", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()

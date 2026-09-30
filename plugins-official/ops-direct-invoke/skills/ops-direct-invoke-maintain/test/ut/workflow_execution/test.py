#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# ----------------------------------------------------------------------------
"""Check our launcher and generated input, trusting harness execution semantics."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).absolute().parents[1]))
from support import (
    SCRIPTS,
    WORKFLOWS,
    available_workflows,
    generate_workflow,
    load_yaml,
    run_tests,
    run_workflow,
)


class WorkflowExecutionTests(unittest.TestCase):
    def test_every_template_assembles_and_runs_through_public_cli(self):
        for entry in available_workflows():
            with self.subTest(template=entry["file"]):
                self.check_template(entry)

    def check_template(self, entry):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = WORKFLOWS / entry["file"]
            sources = {source: source.read_bytes()}
            for node in load_yaml(source)["nodes"]:
                if "yaml" in node:
                    task = source.parent / node["yaml"]
                    sources[task] = task.read_bytes()
            generated = generate_workflow(self, entry, folder)
            definition = load_yaml(generated)
            self.assertEqual(len(definition["nodes"]), len(load_yaml(source)["nodes"]))
            self.assertNotIn("use_when", definition)
            for node in definition["nodes"]:
                self.assertNotIn("yaml", node)
                self.assertNotIn("variables", node)
            before = generated.read_bytes()
            run_workflow(self, "--yaml", generated, folder / "run")
            self.assertEqual(generated.read_bytes(), before)
            for path, content in sources.items():
                self.assertEqual(path.read_bytes(), content)

    def test_launcher_passes_arguments_and_preserves_existing_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            harness = folder / "harness with spaces"
            (harness / "scripts").mkdir(parents=True)
            (harness / "scripts/orchestrator.py").write_text(
                "import json, pathlib, sys\n"
                'pathlib.Path("received.json").write_text(json.dumps(sys.argv[1:]))\n'
                "sys.exit(7)\n"
            )
            work = folder / "workflow1"
            prompt = folder / "prompt.txt"
            prompt.write_text(
                '原始需求\n"quoted" $WORK_DIR $(false) `false`', encoding="utf-8"
            )
            template = available_workflows()[0]["file"]
            command = [
                sys.executable,
                str(SCRIPTS / "run_workflow.py"),
                "--work-dir",
                str(work),
                "--provider",
                "fixture-provider",
                "--harness-skill",
                str(harness),
                "--foreground",
                "--dry-run",
                "--prompt-file",
                str(prompt),
            ]
            result = subprocess.run(
                command + ["--template", template],
                cwd=folder,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 7, result.stderr)
            generated = work / "workflow1.yaml"
            before = generated.read_bytes()
            self.assertEqual(
                json.loads((work / "received.json").read_text()),
                [
                    "--yaml",
                    str(generated),
                    "--work-dir",
                    str(work),
                    "--provider",
                    "fixture-provider",
                    "--prompt",
                    prompt.read_text(encoding="utf-8"),
                    "--dry-run",
                ],
            )
            result = subprocess.run(
                command + ["--template", template],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("resume with --yaml", result.stderr)
            result = subprocess.run(
                command + ["--yaml", str(generated)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertEqual(generated.read_bytes(), before)


if __name__ == "__main__":
    run_tests()

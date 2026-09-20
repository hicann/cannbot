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

"""Probe retry feedback through the real public CLI with a deterministic provider."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support
from support import SCRIPTS, SKILL_ROOT, run_tests


class RetryFeedbackTests(unittest.TestCase):
    def test_retry_preserves_report_but_does_not_inject_verifier_feedback(self):
        with tempfile.TemporaryDirectory(prefix='workflow-feedback-') as temp:
            work = Path(temp)
            binaries = work / 'bin'
            binaries.mkdir()
            cli = binaries / 'codex'
            shutil.copyfile(Path(__file__).parent / 'fixtures/codex.py', cli)
            cli.chmod(0o755)
            definition = work / 'workflow.yaml'
            assembled = subprocess.run([
                sys.executable, str(SCRIPTS / 'assemble_workflow.py'),
                str(SKILL_ROOT / 'tasks/知识搜集.yaml'), '--max-retries', '1',
                '--output', str(definition)], capture_output=True, text=True, timeout=30)
            self.assertEqual(assembled.returncode, 0, assembled.stderr)
            env = {**os.environ, 'PATH': str(binaries) + os.pathsep + os.environ['PATH'],
                   'WORKFLOW_PROBE_DIR': str(work)}
            result = subprocess.run([
                sys.executable, str(support.HARNESS_SKILL / 'scripts/orchestrator.py'),
                '--yaml', str(definition), '--work-dir', str(work), '--provider', 'codex',
                '--prompt', 'CLI contract probe only; no real operator development'],
                env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            calls = [json.loads(line) for line in (work / 'provider-calls.jsonl').read_text().splitlines()]
            self.assertEqual([call['verification'] for call in calls], [False, True, False, True])
            initial, retry = calls[0], calls[2]
            self.assertEqual(initial['prompt'], retry['prompt'])
            self.assertNotIn('RETRY_FEEDBACK_SENTINEL', retry['prompt'])
            self.assertIn('0-验收报告.md', retry['prompt'])
            self.assertIn('RETRY_FEEDBACK_SENTINEL', retry['report'])
            status = json.loads((work / '.workflow/status.json').read_text())['tasks']['0']
            self.assertEqual((status['status'], status['retries']), ('pass', 1))


if __name__ == '__main__':
    run_tests()

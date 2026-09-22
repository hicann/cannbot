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

"""Deterministic Codex CLI stand-in; no model, network or harness internals."""
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stdout)
work = Path(os.environ['WORKFLOW_PROBE_DIR'])
prompt = sys.argv[-1]
verification = 'Procedure:' in prompt
capture = work / 'provider-calls.jsonl'
calls = [json.loads(line) for line in capture.read_text().splitlines()] if capture.exists() else []
report = work / '0-验收报告.md'
report_reference = re.search(r'RETRY_REPORT: ([^\n]+)', prompt)
report_path = Path(report_reference[1]) if report_reference and not verification else None
seen_report = report_path.read_text() if report_path else ''
with capture.open('a') as stream:
    stream.write(json.dumps({'prompt': prompt, 'verification': verification,
                             'report': seen_report, 'report_path': str(report_path) if report_path else None},
                            ensure_ascii=False) + '\n')
if verification:
    prior_verifications = [call for call in calls if call['verification']]
    if not prior_verifications:
        report.write_text('Missing boundary case evidence.\n' * 30 + 'REPORT_DETAIL_SENTINEL')
        reply = 'fail'
    else:
        reply = 'pass' if any('REPORT_DETAIL_SENTINEL' in call['report']
                              for call in calls if not call['verification']) else 'fail'
        report.write_text('pass: prior feedback addressed' if reply == 'pass' else 'fail')
    scripts = Path(os.environ['WORKFLOW_HARNESS_SCRIPTS'])
    command = [sys.executable, str(scripts / f'verdict_{reply}.py'),
               '--work-dir', str(work), '--task-id', '0']
    if reply == 'fail':
        reason = f'RETRY_REPORT: {report}\nRETRY_FEEDBACK_SENTINEL: missing boundary case'
        command += ['--reason', reason]
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=10)
else:
    reply = 'executed'
logging.info(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': reply}}))

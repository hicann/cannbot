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
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stdout)
work = Path(os.environ['WORKFLOW_PROBE_DIR'])
prompt = sys.argv[-1]
verification = 'Procedure:' in prompt
capture = work / 'provider-calls.jsonl'
calls = [json.loads(line) for line in capture.read_text().splitlines()] if capture.exists() else []
report = work / '0-验收报告.md'
seen_report = report.read_text() if report.exists() else ''
with capture.open('a') as stream:
    stream.write(json.dumps({'prompt': prompt, 'verification': verification,
                             'report': seen_report}, ensure_ascii=False) + '\n')
if verification:
    prior_verifications = [call for call in calls if call['verification']]
    if not prior_verifications:
        report.write_text('RETRY_FEEDBACK_SENTINEL: missing boundary case')
        logging.info(json.dumps({'type': 'item.completed', 'item': {
            'type': 'agent_message', 'text': report.read_text()}}))
        reply = 'fail'
    else:
        reply = 'pass' if any('RETRY_FEEDBACK_SENTINEL' in call['report']
                              for call in calls if not call['verification']) else 'fail'
        report.write_text('pass: prior feedback addressed' if reply == 'pass' else 'fail')
else:
    reply = 'executed'
logging.info(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': reply}}))

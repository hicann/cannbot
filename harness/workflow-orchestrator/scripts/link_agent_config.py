#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.

"""Expose the current Agent's project configuration in a workflow directory."""

import argparse
import logging
import os
from pathlib import Path
import sys


# Keep this list aligned with script/bin/cannbot.js TOOL_DIRECTORIES and its
# instruction files.  Missing entries are normal for tools not used by a task.
CONFIG_ENTRIES = (
    ".opencode",
    ".claude",
    ".codex",
    ".agents",
    ".traecli",
    ".marscode",
    ".trae",
    ".trae-cn",
    ".dsh",
    "AGENTS.md",
    "CLAUDE.md",
)


def link_agent_config(start_dir: Path, work_dir: Path) -> list[str]:
    """Link existing supported entries, returning the entries created."""
    if not start_dir.is_dir():
        raise ValueError(f"start directory is not a directory: {start_dir}")
    work_dir.mkdir(parents=True, exist_ok=True)
    if not work_dir.is_dir():
        raise ValueError(f"work directory is not a directory: {work_dir}")
    created = []
    for name in CONFIG_ENTRIES:
        source = start_dir / name
        destination = work_dir / name
        # lexists keeps dangling destination links intact.  This also makes
        # reruns idempotent without replacing local files or directories.
        if os.path.lexists(destination) or not os.path.lexists(source):
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(source)
        created.append(name)
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-dir", required=True, help="Agent session startup directory")
    parser.add_argument("--work-dir", required=True, help="Workflow working directory")
    args = parser.parse_args()
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.addFilter(lambda record: record.levelno < logging.ERROR)
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    logging.basicConfig(
        level=logging.INFO,
        format="[link-agent-config] %(message)s",
        handlers=[stdout_handler, stderr_handler],
    )
    start_dir = Path(args.start_dir).expanduser().absolute()
    work_dir = Path(args.work_dir).expanduser().absolute()
    logging.info("start-dir: %s", start_dir)
    logging.info("work-dir: %s", work_dir)
    try:
        created = link_agent_config(start_dir, work_dir)
    except (OSError, ValueError) as error:
        logging.error("error: %s", error)
        return 1
    if created:
        result = f"linked {', '.join(created)}"
    else:
        result = "no new configuration entries"
    logging.info("%s", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())

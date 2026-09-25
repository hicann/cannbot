# ----------------------------------------------------------------------------------------------------------
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# ----------------------------------------------------------------------------------------------------------

"""YAML frontmatter 解析工具 — 供 skills_linter / agents_linter 共用."""
import logging
import re
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

NAME_PATTERN = re.compile(r'^[a-z0-9][a-z0-9\-]*$')  # 小写字母、数字、连字符
MAX_NAME_LENGTH = 64


class YAMLFixSuggestion(Exception):
    """YAML 解析失败但可自动修复时抛出，携带修复建议."""

    def __init__(self, original_error: str, suggestion: str):
        self.original_error = original_error
        self.suggestion = suggestion
        super().__init__(original_error)


def _quoted_scalar(line: str):
    """A requoted `key: value` line, or None when the line needs no change."""
    stripped = line.strip()
    # 检测 "key: value" 格式且值未加引号的行
    if ':' not in stripped or stripped.startswith('#'):
        return None
    key_part, _, val_part = stripped.partition(':')
    val = val_part.strip()
    if not val or val.startswith(('"', "'", '>', '|', '[', '{', '&', '*')):
        return None
    # 用 yaml.dump 生成安全的标量表示
    safe_scalar = yaml.dump(
        {key_part.strip(): val},
        default_flow_style=False,
        allow_unicode=True,
    ).strip()
    return safe_scalar if safe_scalar != stripped else None


def parse_frontmatter(content: str) -> dict:
    """从 Markdown 文件中提取 YAML frontmatter.

    Args:
        content: Markdown 文件的完整内容.

    Returns:
        解析后的 YAML frontmatter 字典.

    Raises:
        ValueError: 当文件不以 '---' 开始或缺少闭合分隔符时抛出.
        YAMLFixSuggestion: YAML 解析失败但可通过加引号修复时抛出（携带建议）.
        yaml.YAMLError: YAML 解析失败且无法自动修复时抛出.
    """
    lines = content.split('\n')
    if not lines or lines[0].strip() != '---':
        raise ValueError("Markdown file does not start with YAML frontmatter delimiter '---'")

    # 找到第二个 '---' 分隔符
    frontmatter_lines = []
    found_closing = False
    for i in range(1, len(lines)):
        if lines[i].strip() == '---':
            found_closing = True
            break
        frontmatter_lines.append(lines[i])

    if not found_closing:
        raise ValueError("Markdown file does not have closing YAML frontmatter delimiter '---'")

    frontmatter_text = '\n'.join(frontmatter_lines)

    # 尝试直接解析
    try:
        data = yaml.safe_load(frontmatter_text)
        if not isinstance(data, dict):
            raise ValueError("YAML frontmatter must be a mapping (dict), but got "
                             f"{type(data).__name__ if data is not None else 'None'}")
        return data
    except yaml.YAMLError as original_exc:
        # YAML 解析失败 — 对所有字段尝试 auto-fix 以生成修复建议，但不静默通过
        fixed_lines = []
        fix_applied = []  # 记录修复了哪些字段
        for line in frontmatter_lines:
            safe_scalar = _quoted_scalar(line)
            if safe_scalar is None:
                fixed_lines.append(line)
                continue
            fixed_lines.append(safe_scalar)
            fix_applied.append(safe_scalar)

        if not fix_applied:
            # 没有可修复的字段 — 抛原始错误
            raise

        fixed_frontmatter_text = '\n'.join(fixed_lines)
        # auto-fix 后再次解析；若解析为 dict 则抛出带建议的异常，
        # 解析仍失败（yaml.YAMLError）则异常自然向上传播。
        fixed_data = yaml.safe_load(fixed_frontmatter_text)
        if isinstance(fixed_data, dict):
            # auto-fix 能修复 — 抛出带建议的异常（linting 仍不通过）
            suggestion_lines = '\n'.join(f"      {s}" for s in fix_applied)
            suggestion = f"将包含保留字符的值用引号包裹:\n{suggestion_lines}"
            raise YAMLFixSuggestion(str(original_exc), suggestion) from original_exc
        # auto-fix 结果不是 dict 或其他情况 — 抛原始错误
        raise


def report_frontmatter_error(file_path: Path, error: Exception) -> None:
    """按两个 linter 共用的格式输出 frontmatter 解析失败信息."""
    if isinstance(error, YAMLFixSuggestion):
        logger.info(f"❌ {file_path}: YAML 解析失败 — 字段值包含未转义的保留字符")
        logger.info(f"   原始错误: {error.original_error}")
        if error.suggestion:
            logger.info(f"   💡 建议修复: {error.suggestion}")
    elif isinstance(error, yaml.YAMLError):
        logger.info(f"⚠️ {file_path}: YAML 解析失败 - {str(error)}")
    elif isinstance(error, ValueError):
        logger.info(f"⚠️ {file_path}: Frontmatter 解析失败 - {str(error)}")
    else:
        logger.info(f"⚠️ {file_path}: 未知错误 - {str(error)}")


def check_name_field(file_path: Path, data: dict):
    """校验共用的 name 规则（存在性、格式、长度）.

    Returns:
        (passed, name)；name 在缺少字段时为 None，由调用方另行校验一致性.
    """
    if "name" not in data:
        logger.info(f"⚠️ {file_path}: 缺少 'name' 字段")
        return False, None
    name = str(data["name"]).strip()
    passed = True
    if not NAME_PATTERN.match(name):
        logger.info(f"⚠️ {file_path}: name 格式错误，只能包含小写字母、数字和连字符，且必须以字母或数字开头: '{name}'")
        passed = False
    if len(name) > MAX_NAME_LENGTH:
        logger.info(f"⚠️ {file_path}: name 长度超标（{len(name)}/{MAX_NAME_LENGTH}）")
        passed = False
    return passed, name

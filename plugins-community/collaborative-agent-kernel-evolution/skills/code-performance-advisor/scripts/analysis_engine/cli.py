#!/usr/bin/env python3
# ----------------------------------------------------------------------------------------------------------
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# ----------------------------------------------------------------------------------------------------------

"""Minimal rule index and scoring CLI for code-performance-advisor.

Usage:
    python cli.py build-index --rule assets/rules/special_rules/RMATMUL_CUTK.md
    python cli.py update-index --rule assets/rules/special_rules/RMATMUL_CUTK.md --general
    python cli.py score --tag-file workspace/cache/tags/tag_xxx.json

Design goals:
- Minimal dependencies (stdlib only for core functions)
- Read rule paths from an index.json
- Score rules by tag overlap (weighted Jaccard)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# Import goal_loader (optional dependency)
try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from utils.goal_loader import load_goal, GoalConfig
    GOAL_LOADER_AVAILABLE = True
except ImportError:
    GOAL_LOADER_AVAILABLE = False


class CliError(Exception):
    """Raised by command handlers to signal a controlled, non-zero exit.

    The top-level main() catches this and exits with the carried code,
    preserving the previous exit semantics without calling sys.exit in
    non-entrypoint functions.
    """

    def __init__(self, code: int = 1, message: str = ""):
        super().__init__(message)
        self.code = code


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDEX = ROOT / "assets" / "manifests" / "index.json"
DEFAULT_TAG_DIR = ROOT / "workspace" / "cache" / "tags"
DEFAULT_OUTPUT = ROOT / "assets" / "manifests" / "scored_results.json"
DEFAULT_OP_INPUT_DIR = ROOT / "workspace" / "inputs"


@dataclass(frozen=True)
class RuleMeta:
    rule_path: Path
    is_general: bool
    source_hash: str
    source_mtime: float
    tags: list[str]
    required_tags: list[str]


def _hash_file(path: Path) -> str:
    try:
        data = path.read_bytes()
    except Exception:
        return ""
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def _hash_meta(is_general: bool, tags: list[str], required_tags: list[str]) -> str:
    payload = {
        "is_general": bool(is_general),
        "tags": sorted(set(tags)),
        "required_tags": sorted(set(required_tags)),
    }
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.md5(blob, usedforsecurity=False).hexdigest()


def _is_general_rule(rule_path: Path) -> bool:
    parts = {p.lower() for p in rule_path.parts}
    if "general_rules" in parts:
        return True
    if "special_rules" in parts:
        return False
    return False


def _load_index(path: Path) -> list[RuleMeta]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    rules = raw.get("rules", []) if isinstance(raw, dict) else []
    out: list[RuleMeta] = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        paths_raw = r.get("rule_paths", [])
        if isinstance(paths_raw, str):
            paths = [paths_raw]
        elif isinstance(paths_raw, list):
            paths = [str(x) for x in paths_raw if str(x).strip()]
        else:
            paths = []
        is_general = bool(r.get("is_general", False))
        source_hash = str(r.get("source_hash", ""))
        source_mtime = float(r.get("source_mtime", 0))
        tags = r.get("tags", []) if isinstance(r.get("tags", []), list) else []
        required = r.get("required_tags", []) if isinstance(r.get("required_tags", []), list) else []
        for p in paths:
            rule_path = Path(p).expanduser()
            if not rule_path.is_absolute():
                rule_path = (ROOT / rule_path).resolve()
            if not rule_path.exists():
                continue
            out.append(
                RuleMeta(
                    rule_path=rule_path,
                    is_general=is_general,
                    source_hash=source_hash,
                    source_mtime=source_mtime,
                    tags=[str(x).strip() for x in tags if str(x).strip()],
                    required_tags=[str(x).strip() for x in required if str(x).strip()],
                )
            )
    return out


def _save_index(path: Path, rules: Iterable[RuleMeta]) -> None:
    payload = {
        "version": "1.0",
        "rules": [
            {
                "rule_paths": [str(r.rule_path)],
                "is_general": r.is_general,
                "tags": r.tags,
                "required_tags": r.required_tags,
                "source_hash": r.source_hash,
                "source_mtime": r.source_mtime,
            }
            for r in rules
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _parse_front_matter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm = parts[1]
    meta: dict[str, str] = {}
    for line in fm.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta


def _parse_inline_list(value: str) -> list[str]:
    value = value.strip()
    if not value:
        return []
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [x.strip() for x in inner.split(",") if x.strip()]
    return [value]


def _load_sidecar_tags(candidate) -> "tuple[list[str], list[str]] | None":
    """Read a `<rule_id>_tags.json` sidecar. None when absent or unreadable."""
    if not candidate.exists():
        return None
    try:
        data = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug("Failed to load sidecar tags from %s: %s", candidate, e)
        return None
    if not isinstance(data, dict):
        return None
    tags = []
    for key in ("domain_tags", "symptom_tags", "context_tags"):
        value = data.get(key, [])
        if isinstance(value, list):
            tags.extend([str(x).strip() for x in value if str(x).strip()])
        elif isinstance(value, str) and value.strip():
            tags.append(value.strip())
    required = data.get("required_tags", [])
    if isinstance(required, list):
        required_tags = [str(x).strip() for x in required if str(x).strip()]
    elif isinstance(required, str) and required.strip():
        required_tags = [required.strip()]
    else:
        required_tags = []
    return sorted(set(tags)), sorted(set(required_tags))


def _load_rule_tags(rule_path: Path, inline_tags: list[str], inline_required: list[str]) -> tuple[list[str], list[str]]:
    """Load rule tags from sidecar JSON or front matter.

    Priority:
    1. Inline tags (if provided)
    2. Sidecar JSON ({rule_id}_tags.json) - inferred from filename
    3. Front matter in markdown
    """
    if inline_tags or inline_required:
        return sorted(set(inline_tags)), sorted(set(inline_required))

    # Try to infer rule_id from filename (e.g., R_API_VECTOR_COUNTER_MODE.md -> R_API_VECTOR_COUNTER_MODE)
    rule_id_from_filename = rule_path.stem  # Remove .md extension
    candidate = rule_path.parent / f"{rule_id_from_filename}_tags.json"
    sidecar = _load_sidecar_tags(candidate)
    if sidecar is not None:
        return sidecar

    # Fallback: Try front matter
    text = rule_path.read_text(encoding="utf-8")
    meta = _parse_front_matter(text)
    rule_id = meta.get("rule_id", "").strip()
    if rule_id:
        sidecar = _load_sidecar_tags(rule_path.parent / f"{rule_id}_tags.json")
        if sidecar is not None:
            return sidecar

    tags: list[str] = []
    for key in ("domain_tags", "symptom_tags", "context_tags"):
        tags.extend(_parse_inline_list(meta.get(key, "")))
    required = _parse_inline_list(meta.get("required_tags", ""))
    return sorted(set(tags)), sorted(set(required))


def _load_query_tags(tag_file: Path) -> list[str]:
    raw = json.loads(tag_file.read_text(encoding="utf-8"))
    tags = []
    for key in ("domain_tags", "symptom_tags", "context_tags"):
        value = raw.get(key, [])
        if isinstance(value, list):
            tags.extend([str(x).strip() for x in value if str(x).strip()])
    return sorted(set(tags))


def _tag_weight(tag: str) -> int:
    if tag.startswith("S."):
        return 3
    if tag.startswith("U.") or tag.startswith("O.") or tag.startswith("T."):
        return 2
    if tag.startswith("C."):
        return 1
    return 1


def _weighted_jaccard(query: list[str], rule: list[str]) -> float:
    q = set(query)
    r = set(rule)
    if not q and not r:
        return 0.0
    inter = q & r
    union = q | r
    inter_w = sum(_tag_weight(t) for t in inter)
    union_w = sum(_tag_weight(t) for t in union)
    return inter_w / union_w if union_w else 0.0


def _coverage_ratio(query: list[str], required: list[str]) -> float:
    if not required:
        return 1.0
    q = set(query)
    r = set(required)
    return len(q & r) / float(len(r))


def _find_latest_tag_file(tag_dir: Path) -> Optional[Path]:
    if not tag_dir.exists():
        return None
    candidates = [p for p in tag_dir.glob("*.json") if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def build_index(index_path: Path, rule_path: Path, is_general: bool) -> None:
    rule_path = rule_path.resolve()
    if not rule_path.exists():
        logger.info(f"❌ Error: Rule file not found")
        logger.info(f"   Path: {rule_path}")
        logger.info(f"\n💡 Suggestions:")
        logger.info(f"   - Check if the file path is correct")
        logger.info(f"   - Ensure you're in the correct working directory")
        logger.info(f"   - Rules should be in: {ROOT}/assets/rules/special_rules/")
        raise CliError(1)

    is_general = _is_general_rule(rule_path)
    tags, required_tags = _load_rule_tags(rule_path, [], [])
    meta = RuleMeta(
        rule_path=rule_path,
        is_general=is_general,
        source_hash=_hash_meta(is_general, tags, required_tags),
        source_mtime=rule_path.stat().st_mtime,
        tags=tags,
        required_tags=required_tags,
    )
    _save_index(index_path, [meta])
    logger.info(f"✅ Index created successfully!")
    logger.info(f"   Index: {index_path}")
    logger.info(f"   Seed rule: {rule_path.stem}")


def update_index(index_path: Path, rule_path: Path, is_general: bool) -> None:
    # Auto-initialize empty index if missing (supports bootstrap.sh workflow)
    if not index_path.exists():
        index_path.parent.mkdir(parents=True, exist_ok=True)
        _save_index(index_path, [])

    rules = _load_index(index_path)
    rule_path = rule_path.resolve()

    # Check if rule file exists
    if not rule_path.exists():
        logger.info(f"❌ Error: Rule file not found")
        logger.info(f"   Path: {rule_path}")
        logger.info(f"\n💡 Suggestions:")
        logger.info(f"   - Verify the rule file path is correct")
        logger.info(f"   - Rule files should end with .md")
        logger.info(f"   - Example: assets/rules/special_rules/R_XXX/R_XXX.md")
        raise CliError(1)

    is_general = _is_general_rule(rule_path)

    try:
        tags, required_tags = _load_rule_tags(rule_path, [], [])
    except Exception as e:
        logger.info(f"❌ Error: Failed to parse rule tags")
        logger.info(f"   Rule: {rule_path.stem}")
        logger.info(f"   Reason: {e}")
        logger.info(f"\n💡 Suggestion:")
        logger.info(f"   - Check if the rule file has valid 'tags:' section")
        logger.info(f"   - Ensure tags are in format: tags: [D.xxx, O.xxx, ...]")
        raise CliError(1) from e

    entry = RuleMeta(
        rule_path=rule_path,
        is_general=is_general,
        source_hash=_hash_meta(is_general, tags, required_tags),
        source_mtime=rule_path.stat().st_mtime,
        tags=tags,
        required_tags=required_tags,
    )
    updated: list[RuleMeta] = []
    found = False
    for r in rules:
        if r.rule_path == rule_path:
            updated.append(entry)
            found = True
        else:
            updated.append(r)

    if not found:
        updated.append(entry)

    _save_index(index_path, updated)

    # Success message
    action = "updated" if found else "added"
    logger.info(f"✅ Rule {action} successfully!")
    logger.info(f"   Rule: {rule_path.stem}")
    logger.info(f"   Index: {index_path}")
    logger.info(f"   Total rules: {len(updated)}")


def _merge_pattern(pattern_best: dict, p: dict, source_name: str) -> None:
    """同一 pattern_id 只保留置信度最高的一条检测结果。"""
    pid = p.get("pattern_id")
    if not pid:
        return
    prev = pattern_best.get(pid)
    if (prev is None) or (p.get("confidence", 0.0) > prev.get("confidence", 0.0)):
        pattern_best[pid] = dict(p, source_file=source_name)


def _scan_applied_patterns(detector, cpp_files: list) -> list:
    """调研方法改进：扫描所有 .cpp，按 pattern_id 聚合（取最高置信度）。"""
    pattern_best = {}
    for cpp_file in cpp_files:
        for p in detector.detect_from_file(cpp_file):
            _merge_pattern(pattern_best, p, str(cpp_file.name))

    patterns = sorted(pattern_best.values(), key=lambda x: x.get("confidence", 0.0), reverse=True)
    if patterns:
        logger.info(f"\n🔍 Detected applied patterns in code (scanned {len(cpp_files)} .cpp files):")
        for p in patterns:
            if p.get("confidence", 0.0) > 0.7:
                src = p.get("source_file", "?")
                logger.info(f"   ✓ {p['pattern_name']} ({p['confidence']:.0%}) @ {src}")
    return patterns


def _applied_patterns_from_code(op_name: Optional[str], op_dir: Optional[Path]) -> set:
    """✅ 尝试从代码中检测 applied patterns (作为补充)"""
    if not op_name:
        return set()
    from applied_pattern_detector import AppliedPatternDetector
    kernel_code_path = (op_dir or (DEFAULT_OP_INPUT_DIR / op_name)) / "code" / "op_kernel"
    if not kernel_code_path.exists():
        return set()
    cpp_files = sorted(kernel_code_path.glob("*.cpp"))
    if not cpp_files:
        return set()
    detector = AppliedPatternDetector()
    try:
        patterns = _scan_applied_patterns(detector, cpp_files)
    except Exception as e:
        logger.info(f"\n⚠️  Pattern detection failed: {e}")
        return set()
    return {p["pattern_id"] for p in patterns if p.get("confidence", 0.0) > 0.7}


def _load_rule_pattern_map() -> dict:
    """规则ID→Pattern ID 映射：从 AppliedPatternDetector 读取，与 pattern 定义同源，
    新增模式时无需改此处。"""
    try:
        from applied_pattern_detector import AppliedPatternDetector as _APD
        return _APD.RULE_PATTERN_MAP
    except Exception:
        return {}


def _infer_op_name(op_name: Optional[str], tag_file: Path) -> Optional[str]:
    """Use provided op_name or infer from tag file name (e.g., tag_fastgelu.json -> fastgelu)."""
    if op_name:
        return op_name
    tag_filename = tag_file.stem  # e.g., "tag_fastgelu"
    return tag_filename[4:] if tag_filename.startswith("tag_") else None


def _log_goal(op_name: str, goal) -> None:
    """Display goal information to user"""
    logger.info(f"\n✅ Loaded Performance Goal for '{op_name}':")
    logger.info(f"   Target improvement: >= {goal.improvement_percentage}")
    logger.info(f"   Max iterations: {goal.stop_conditions['max_iterations']}")
    logger.info(f"   Stop after failures: {goal.stop_conditions['consecutive_failures']}")
    if goal.absolute_metrics:
        logger.info("   Absolute metrics:")
        for key, value in goal.absolute_metrics.items():
            logger.info(f"     - {key}: {value}")


def _load_goal_info(op_name: Optional[str], op_dir: Optional[Path], tag_file: Path):
    """Try to infer operator directory and load performance goal."""
    if not GOAL_LOADER_AVAILABLE:
        logger.info("\n⚠️  Goal loader not available (missing PyYAML dependency)")
        logger.info("   Using default goal configuration (20% improvement)")
        return None
    try:
        op_name = _infer_op_name(op_name, tag_file)
        if not op_name:
            logger.info("\n⚠️  Could not infer operator name from tag file")
            logger.info("   Use --op <name> to specify operator explicitly")
            logger.info("   Using default goal configuration (20% improvement)")
            return None
        effective_op_dir = (op_dir or (DEFAULT_OP_INPUT_DIR / op_name))
        if not effective_op_dir.exists():
            logger.info(f"\n⚠️  Operator directory not found: {effective_op_dir}")
            logger.info("   Using default goal configuration (20% improvement)")
            return None
        goal = load_goal(effective_op_dir)
        goal_info = {
            "op_name": op_name,
            "relative_improvement": goal.relative_improvement,
            "improvement_percentage": goal.improvement_percentage,
            "absolute_metrics": goal.absolute_metrics,
            "stop_conditions": goal.stop_conditions,
            "notes": goal.notes
        }
        _log_goal(op_name, goal)
        return goal_info
    except Exception as e:
        logger.info(f"\n⚠️  Warning: Failed to load goal configuration: {e}")
        logger.info("   Using default goal configuration (20% improvement)")
        return None


def _score_one_rule(rule, query_tags, rule_to_pattern_map: dict, applied_patterns: set) -> dict:
    """对单条规则打分，并标注是否因 pattern 已应用而冗余。"""
    rule_tags, required_tags = _load_rule_tags(rule.rule_path, rule.tags, rule.required_tags)
    score = _weighted_jaccard(query_tags, rule_tags)
    coverage = _coverage_ratio(query_tags, required_tags)
    general_boost = 0.01 if rule.is_general and score < 0.2 else 0.0
    effective_score = score + general_boost

    # ✅ 检查规则是否已应用 (去重)
    rule_id = rule.rule_path.parent.name  # 如 R_COUNTER_MODE_VECTORIZATION
    pattern_id = rule_to_pattern_map.get(rule_id)
    redundant = pattern_id in applied_patterns if pattern_id else False
    redundant_reason = None
    if redundant:
        # ✅ 对于已应用的规则，大幅降低分数(几乎排除)
        effective_score *= 0.05  # 降到原分数的 5%
        redundant_reason = f"Pattern '{pattern_id}' already applied in baseline code"

    return {
        "rule_path": str(rule.rule_path),
        "is_general": rule.is_general,
        "score": round(effective_score, 6),
        "raw_score": round(score, 6),
        "coverage_ratio": round(coverage, 6),
        "conflict": coverage < 1.0,
        "matched_tags": sorted(set(query_tags) & set(rule_tags)),
        "missing_tags": sorted(set(rule_tags) - set(query_tags)),
        # check: score >= 0.3, worth investigating
        # valid: all required_tags matched, rule can fire without gating conflict
        "check": effective_score >= 0.3,
        "valid": coverage >= 1.0,
        # ✅ 新增字段
        "redundant": redundant,
        "redundant_reason": redundant_reason,
        "pattern_id": pattern_id
    }


def _log_scoring_summary(output_path: Path, results: list) -> None:
    """Display summary"""
    logger.info("\n✅ Scoring completed!")
    logger.info(f"   Output: {output_path}")
    logger.info(f"   Total rules scored: {len(results)}")

    # ✅ 显示 redundant 规则统计
    redundant_count = sum(1 for r in results if r.get("redundant", False))
    if redundant_count > 0:
        logger.info(f"   Redundant rules filtered: {redundant_count}")

    if not results:
        return
    # 找到第一个非 redundant 的规则作为 top rule
    non_redundant = [r for r in results if not r.get("redundant", False)]
    if non_redundant:
        top_rule = non_redundant[0]
        logger.info(f"   Top rule: {Path(top_rule['rule_path']).stem} (score: {top_rule['score']:.3f})")
        return
    # 所有规则都是 redundant
    logger.info("   ⚠️  All matching rules are redundant (already applied)")
    logger.info("   Suggestion: Explore other optimization directions")


def score_rules(
        index_path: Path,
        tag_file: Path,
        output_path: Path,
        op_name: Optional[str] = None,
        op_dir: Optional[Path] = None,
) -> None:
    rules = _load_index(index_path)
    query_tags = _load_query_tags(tag_file)

    # ✅ 读取 tag 文件中的 applied_patterns (如果有)
    tag_data = json.loads(tag_file.read_text(encoding="utf-8"))
    applied_patterns_from_tag = set(tag_data.get("applied_patterns", []))

    # ✅ 合并两种来源的 applied patterns
    applied_patterns = applied_patterns_from_tag | _applied_patterns_from_code(op_name, op_dir)
    rule_to_pattern_map = _load_rule_pattern_map()

    if applied_patterns:
        logger.info("\n📋 Applied patterns will be filtered:")
        for pat in applied_patterns:
            logger.info(f"   - {pat}")

    goal_info = _load_goal_info(op_name, op_dir, tag_file)

    results = [_score_one_rule(rule, query_tags, rule_to_pattern_map, applied_patterns)
               for rule in rules]
    results.sort(
        key=lambda r: (
            r["conflict"],
            -r["score"],
            0 if r["is_general"] else 1,
            r["rule_path"],
        )
    )

    payload = {
        "version": "1.0",
        "query_tag_file": str(tag_file),
        "query_tags": query_tags,
        "applied_patterns": sorted(list(applied_patterns)),  # ✅ 记录已应用的 patterns
        "results": results,
    }

    # Add goal information to output if available
    if goal_info:
        payload["performance_goal"] = goal_info

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _log_scoring_summary(output_path, results)


_CLI_EPILOG = """
Examples:
  # Initialize rule index (first time setup)
  python cli.py build-index

  # Score rules using auto-detected tag file
  python cli.py score

  # Score rules with explicit tag file
    python cli.py score --tag-file workspace/cache/tags/tag_fastgelu_*.json

  # Update index after adding a new rule
  python cli.py update-index --rule assets/rules/special_rules/R_NEW_RULE/R_NEW_RULE.md
        """


def _add_index_parsers(sub) -> None:
    """build-index / update-index 两个子命令。"""
    build = sub.add_parser("build-index", help="Create initial rule index from assets/rules/special_rules/")
    build.add_argument(
        "--index",
        default=str(DEFAULT_INDEX),
        help="Path to index.json (default: assets/manifests/index.json)")
    build.add_argument(
        "--rule",
        default=str(ROOT / "assets" / "rules" / "special_rules" / "R030_MATMUL_CUTK.md"),
        help="Seed rule file (for index initialization)"
    )
    build.add_argument("--general", action="store_true", help="Mark rule as general (not operator-specific)")

    update = sub.add_parser("update-index", help="Add or update a single rule in index.json")
    update.add_argument("--index", default=str(DEFAULT_INDEX), help="Path to index.json")
    update.add_argument("--rule", required=True, help="Path to rule markdown file (e.g., R_XXX/R_XXX.md)")
    update.add_argument("--general", action="store_true", help="Mark rule as general (not operator-specific)")


def _add_score_parser(sub) -> None:
    """score 子命令（Phase 0 routing）。"""
    score = sub.add_parser("score", help="Score rules against operator tags (Phase 0 routing)")
    score.add_argument("--index", default=str(DEFAULT_INDEX), help="Path to index.json")
    score.add_argument(
        "--tag-file",
        default=None,
        help="Path to tag JSON file. If omitted, auto-detects latest from workspace/cache/tags/"
    )
    score.add_argument(
        "--op",
        default=None,
        help="Operator name (e.g., 'fastgelu'). Used for applied-pattern detection "
             "and optional goal loading. If omitted, infers from tag file name."
    )
    score.add_argument(
        "--op-dir",
        default=None,
        help="Operator directory (workspace/inputs/<op>). Overrides default "
             "workspace for applied-pattern detection/goal loading."
    )
    score.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="Output path for scored_results.json (default: assets/manifests/scored_results.json)"
    )


def _add_suggest_parser(sub) -> None:
    """suggest 子命令（Phase 1）。"""
    suggest = sub.add_parser("suggest", help="Generate optimization suggestions from scored results (Phase 1)")
    suggest.add_argument(
        "--scored-results",
        default=str(DEFAULT_OUTPUT),
        help="Path to scored_results.json from Phase 0 (default: assets/manifests/scored_results.json)"
    )
    suggest.add_argument(
        "--op",
        required=True,
        help="Operator name (e.g., 'fastgelu')"
    )
    suggest.add_argument(
        "--op-dir",
        default=None,
        help="Operator directory (auto-detects workspace/inputs/{op} if omitted)"
    )
    suggest.add_argument(
        "--output",
        default=None,
        help="Output markdown file (default: workspace/sessions/<session_id>/suggestions/...)"
    )
    suggest.add_argument(
        "--top-n",
        type=int,
        default=3,
        help="Number of top rules to generate suggestions for (default: 3)"
    )
    suggest.add_argument(
        "--threshold",
        type=float,
        default=0.3,
        help="Minimum score threshold (default: 0.3)"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rule index and scoring CLI for Code Performance Advisor",
        epilog=_CLI_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    _add_index_parsers(sub)
    _add_score_parser(sub)
    _add_suggest_parser(sub)
    return parser


def _log_missing_tag_file_help() -> None:
    """自动探测不到 tag 文件时，说明如何生成。"""
    logger.info(f"❌ Error: No tag file found in {DEFAULT_TAG_DIR}/")
    logger.info("\n💡 How to create a tag file:")
    logger.info("   1. Ensure inputs exist: workspace/inputs/<op>/ (use init_workspace.py if needed)")
    logger.info(f"   2. Run the code_tag subskill to generate tag JSON into: {DEFAULT_TAG_DIR}/")
    logger.info("   3. Or provide explicit path: --tag-file <path>")
    logger.info("\n📝 Tag file format:")
    logger.info("   {")
    logger.info('     "domain_tags": ["U.xxx", "O.xxx", "T.xxx"],')
    logger.info('     "symptom_tags": ["S.xxx"],')
    logger.info('     "context_tags": ["C.xxx"]')
    logger.info("   }")


def _resolve_tag_file_arg(args):
    """Get tag file (explicit or auto-detect)；返回 None 表示已打印错误提示。"""
    if not args.tag_file:
        tag_file = _find_latest_tag_file(DEFAULT_TAG_DIR)
        if not tag_file:
            _log_missing_tag_file_help()
            return None
        return tag_file
    tag_file = Path(args.tag_file)
    if tag_file.exists():
        return tag_file
    logger.info("❌ Error: Tag file not found")
    logger.info(f"   Path: {tag_file}")
    logger.info("\n💡 Suggestions:")
    logger.info("   - Check if the file path is correct")
    logger.info(f"   - Tag files should be in: {DEFAULT_TAG_DIR}/")
    logger.info("   - Generate tags using the code_tag subskill "
                "(save JSON under workspace/cache/tags/)")
    return None


def _cmd_score(args) -> int:
    """score 子命令。"""
    tag_file = _resolve_tag_file_arg(args)
    if tag_file is None:
        return 1
    # Get operator name from --op or infer from tag file
    op_name = args.op if hasattr(args, 'op') and args.op else None
    op_dir = Path(args.op_dir) if getattr(args, 'op_dir', None) else None
    score_rules(Path(args.index), tag_file, Path(args.output), op_name, op_dir=op_dir)
    return 0


def _suggest_output_path(args) -> Path:
    """Set default output path if not provided.
    Prefer session-based workspace layout: write into latest session's suggestions/ if available."""
    if args.output is not None:
        return Path(args.output)
    sessions_dir = ROOT / "workspace" / "sessions"
    if sessions_dir.exists():
        candidates = sorted(
            [p for p in sessions_dir.glob(f"*_{args.op}_*") if p.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return candidates[0] / "suggestions" / f"{args.op}_cli_suggestions.md"
    # Fallback: cache area
    return ROOT / "workspace" / "cache" / "suggestions" / f"{args.op}_cli_suggestions.md"


def _log_suggestion_success(args, suggestions, output_path) -> None:
    """建议生成成功后的后续步骤提示。"""
    logger.info("\n✅ Suggestion generation completed!")
    logger.info(f"   Generated {len(suggestions)} optimization suggestions")
    logger.info(f"   Review: {output_path}")
    logger.info("\n💡 Next steps:")
    logger.info("   - Review suggestions in the markdown file")
    logger.info("   - Apply recommended code changes")
    logger.info(f"   - Rebuild operator: python scripts/analysis_engine/build_operator.py --op {args.op}")
    logger.info("   - Re-profile and verify improvement")


def _log_suggestion_failure(args, e: Exception) -> None:
    """建议生成失败时的排查提示。"""
    import traceback
    logger.info("\n❌ Error during suggestion generation:")
    logger.info(f"   {type(e).__name__}: {e}")
    logger.info("\n💡 Debugging tips:")
    logger.info(f"   - Check operator directory exists: workspace/inputs/{args.op}/")
    logger.info(f"   - Ensure operator code exists: workspace/inputs/{args.op}/code/op_kernel/")
    logger.info(f"   - Ensure profiling data exists: workspace/inputs/{args.op}/profiling/op_summary.csv")
    traceback.print_exc()


def _generate_suggestions(generator_cls, args, scored_results_path, output_path) -> int:
    """Create SuggestionGenerator and generate suggestions"""
    try:
        logger.info(f"\n🚀 Starting suggestion generation for '{args.op}'...")
        generator = generator_cls(
            scored_results_path=scored_results_path,
            op_name=args.op,
            op_dir=args.op_dir,
            root_dir=ROOT
        )
        suggestions = generator.generate(
            top_n=args.top_n,
            score_threshold=args.threshold
        )
        if not suggestions:
            logger.info("\n⚠️  No suggestions generated")
            logger.info(f"   - All rules scored below threshold ({args.threshold})")
            logger.info("   - Try lowering --threshold or adding more rules to index")
            return 1
        generator.render_markdown(suggestions, output_path)
        _log_suggestion_success(args, suggestions, output_path)
        return 0
    except Exception as e:
        _log_suggestion_failure(args, e)
        return 1


def _cmd_suggest(args) -> int:
    """suggest 子命令。"""
    # Import suggest_template module
    try:
        from suggest_template import SuggestionGenerator
    except ImportError as e:
        logger.info("❌ Error: Failed to import SuggestionGenerator")
        logger.info(f"   {e}")
        logger.info("\n💡 Suggestions:")
        logger.info("   - Ensure suggest_template.py is in the same directory")
        logger.info("   - Check Python path and working directory")
        return 1

    # Validate scored_results file exists
    scored_results_path = Path(args.scored_results)
    if not scored_results_path.exists():
        logger.info("❌ Error: Scored results file not found")
        logger.info(f"   Path: {scored_results_path}")
        logger.info("\n💡 Suggestions:")
        logger.info(f"   - Run Phase 0 first: python cli.py score --op {args.op}")
        logger.info("   - Or provide explicit path: --scored-results <path>")
        return 1

    return _generate_suggestions(SuggestionGenerator, args,
                                 scored_results_path, _suggest_output_path(args))


def _log_unexpected_error(e: Exception) -> None:
    """未预期异常的排查提示。"""
    logger.info("\n❌ Unexpected error occurred:")
    logger.info(f"   {type(e).__name__}: {e}")
    logger.info("\n💡 Debugging tips:")
    logger.info("   - Run with Python's -v flag for verbose output")
    logger.info("   - Check file permissions and paths")
    logger.info("   - Ensure you're in the correct working directory")
    logger.info("   - Report issues to: https://github.com/anthropics/claude-code/issues")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    args = build_parser().parse_args()

    # Wrap main logic in try-except to catch unexpected errors
    try:
        if args.command == "build-index":
            build_index(Path(args.index), Path(args.rule), bool(args.general))
            return 0
        if args.command == "update-index":
            update_index(Path(args.index), Path(args.rule), bool(args.general))
            return 0
        if args.command == "score":
            return _cmd_score(args)
        if args.command == "suggest":
            return _cmd_suggest(args)
        return 1
    except KeyboardInterrupt:
        logger.info("\n\n⚠️  Operation cancelled by user")
        return 130
    except CliError as e:
        return e.code
    except Exception as e:
        _log_unexpected_error(e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

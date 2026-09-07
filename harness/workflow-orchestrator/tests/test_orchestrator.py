"""Blackbox tests for the workflow-orchestrator skill.

These tests exercise ``orchestrator.py`` only through its documented CLI in
``--dry-run`` mode (simulated agents), asserting on exit codes, stdout, and the
persisted artifacts (``status.json`` / ``log.jsonl``). The orchestrator is a
blackbox — its source is intentionally not read here.

Run from the skill root (or anywhere)::

    python3 -m unittest discover -s harness/workflow-orchestrator/tests

or directly::

    python3 harness/workflow-orchestrator/tests/test_orchestrator.py
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

SKILL_ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = SKILL_ROOT / "scripts" / "orchestrator.py"


def _node(node_id, **overrides):
    """A valid normal task node; overrides let a test break one field."""
    node = {
        "id": node_id,
        "task_type": "normal",
        "title": f"Task {node_id}",
        "goal": ["finish the task"],
        "approach": ["do the work"],
        "acceptance": ["true"],
        "out_of_scope": ["nothing"],
        "depends_on": [],
        "executor": "general-executor",
        "verifier": "general-verifier",
        "max_retries": 0,
        "on_exhaust": "exit",
    }
    node.update(overrides)
    return node


def _workflow_yaml(nodes, max_parallel=1):
    return yaml.safe_dump(
        {"workflow": "test", "max_parallel": max_parallel, "nodes": nodes},
        sort_keys=False,
    )


def run_orchestrator(nodes=None, yaml_text=None, dry_replies=None, max_parallel=1, prompt="test"):
    """Run orchestrator.py with --dry-run; return (exit_code, output, work_dir)."""
    work_dir = tempfile.mkdtemp(prefix="wo-test-")
    wf_path = Path(work_dir) / "workflow.yaml"
    wf_path.write_text(yaml_text if yaml_text is not None else _workflow_yaml(nodes, max_parallel))
    if dry_replies is not None:
        wr = Path(work_dir) / ".workflow"
        wr.mkdir(parents=True, exist_ok=True)
        (wr / "dry_replies.json").write_text(json.dumps(dry_replies))
    proc = subprocess.run(
        [sys.executable, str(ORCHESTRATOR), "--yaml", str(wf_path),
         "--work-dir", work_dir, "--dry-run", "--prompt", prompt],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr, work_dir


def read_status(work_dir):
    return json.loads((Path(work_dir) / ".workflow" / "status.json").read_text())


def read_log(work_dir):
    lines = (Path(work_dir) / ".workflow" / "log.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


class OrchestratorTest(unittest.TestCase):
    def setUp(self):
        self._work_dirs = []

    def tearDown(self):
        for d in self._work_dirs:
            shutil.rmtree(d, ignore_errors=True)

    def _run(self, **kwargs):
        code, out, work_dir = run_orchestrator(**kwargs)
        self._work_dirs.append(work_dir)
        return code, out, work_dir

    def test_happy_path_single_node(self):
        code, out, wd = self._run(nodes=[_node("setup")])
        self.assertEqual(code, 0, out)
        self.assertEqual(read_status(wd)["tasks"]["setup"]["status"], "pass")
        events = [e["event"] for e in read_log(wd)]
        self.assertIn("init", events)
        self.assertIn("finish", events)

    def test_dependency_chain_completes(self):
        nodes = [_node("a"), _node("b", depends_on=["a"])]
        code, out, wd = self._run(nodes=nodes)
        self.assertEqual(code, 0, out)
        tasks = read_status(wd)["tasks"]
        self.assertEqual(tasks["a"]["status"], "pass")
        self.assertEqual(tasks["b"]["status"], "pass")

    def test_independent_nodes_run_in_parallel(self):
        nodes = [_node("a"), _node("b")]
        code, out, wd = self._run(nodes=nodes, max_parallel=2)
        self.assertEqual(code, 0, out)
        tasks = read_status(wd)["tasks"]
        self.assertEqual(tasks["a"]["status"], "pass")
        self.assertEqual(tasks["b"]["status"], "pass")

    def test_empty_nodes_rejected(self):
        code, out, _ = self._run(yaml_text="workflow: test\nmax_parallel: 1\nnodes: []\n")
        self.assertEqual(code, 1, out)
        self.assertIn("没有任务节点", out)

    def test_missing_node_key_rejected(self):
        node = _node("t1")
        del node["approach"]
        code, out, _ = self._run(nodes=[node])
        self.assertEqual(code, 2, out)
        self.assertIn("approach", out)

    def test_invalid_task_type_rejected(self):
        code, out, _ = self._run(nodes=[_node("t1", task_type="bogus")])
        self.assertEqual(code, 2, out)
        self.assertIn("normal/subgraph", out)

    def test_retry_then_pass(self):
        node = _node("t1", max_retries=1)
        code, out, wd = self._run(
            nodes=[node], dry_replies={"t1": ["executed", "fail", "executed", "pass"]},
        )
        self.assertEqual(code, 0, out)
        task = read_status(wd)["tasks"]["t1"]
        self.assertEqual(task["status"], "pass")
        self.assertEqual(task["retries"], 1)

    def test_fail_exhausts_budget(self):
        node = _node("t1", max_retries=1)
        code, out, wd = self._run(
            nodes=[node], dry_replies={"t1": ["executed", "fail", "executed", "fail"]},
        )
        self.assertEqual(code, 1, out)
        task = read_status(wd)["tasks"]["t1"]
        self.assertEqual(task["status"], "fail")
        self.assertTrue(task["exhausted"])
        self.assertGreaterEqual(task["retries"], 1)


if __name__ == "__main__":
    unittest.main()
